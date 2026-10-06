import numpy as np
import pytest

from interis.analysis.analyze import AnalysisOptions, analyze, group_questions
from interis.analysis.guide import GuideError, parse_guide
from interis.analysis.questions import classify, detect, is_backchannel
from interis.analysis.roles import assign_roles
from interis.analysis.sentences import Sentence, split_sentences
from interis.pipeline.types import Transcript, Turn, Word


def _turn(speaker, start, text):
    words, t = [], start
    for tok in text.split():
        words.append(Word(" " + tok, t, t + 0.3, 0.9))
        t += 0.35
    return Turn(speaker, start, t, words)


def _sentence(text, speaker="A"):
    return Sentence(0, 0, 0, text, 0.0, 1.0, speaker)


# ------------------------------------------------------------------ sentences

def test_split_sentences_respects_abbreviations_and_ordinals():
    turn = _turn("A", 0, "Wir haben z.B. am 3. Mai angefangen. Wie war das für Sie?")
    sents = split_sentences([turn])
    assert [s.text for s in sents] == ["Wir haben z.B. am 3. Mai angefangen.",
                                       "Wie war das für Sie?"]
    assert (sents[1].first, sents[1].last) == (7, 11)  # words 0–6 form the first sentence


# ------------------------------------------------------------------ questions

@pytest.mark.parametrize("text", [
    "Wie sieht Ihr Arbeitsalltag aus?",
    "Und warum haben Sie sich dafür entschieden?",
    "Inwiefern hat sich das verändert",
    "Welche Rolle spielt KI dabei?",
    "Haben Sie damit schon Erfahrungen gemacht?",
    "Können Sie mir das genauer erklären",
    "Erzählen Sie mal, wie das angefangen hat.",
    "Beschreiben Sie bitte einen typischen Tag.",
    "Mich würde interessieren, wie Ihr Team damit umgeht.",
    "Ich würde gerne wissen, was Sie davon halten.",
    "Okay, und wer entscheidet das bei Ihnen?",
    "Das heißt, Sie nutzen das täglich?",
])
def test_questions_are_detected(text):
    assert classify(_sentence(text)) is not None, text


@pytest.mark.parametrize("text", [
    "Ich arbeite seit 2019 in Stuttgart.",
    "Das war eine schwierige Zeit.",
    "Mhm.",
    "Okay?",
    "Ja, genau.",
    "Vielen Dank.",
    "Hat gut geklappt.",
    "Wir nutzen das für Übersetzungen.",
])
def test_statements_and_backchannels_are_not_questions(text):
    assert classify(_sentence(text)) is None, text


def test_reasons_and_kind():
    c = classify(_sentence("Erzählen Sie mal, wie das war."))
    assert c.kind == "prompt" and c.reasons == ["narrative_prompt"]
    c = classify(_sentence("Wie war das?"))
    assert c.kind == "question" and set(c.reasons) == {"question_mark", "interrogative"}
    assert c.confidence > 0.9


def test_backchannel():
    assert is_backchannel("Mhm, okay.")
    assert not is_backchannel("Okay, und warum?")


# ------------------------------------------------------------------ guide

GUIDE = """# Leitfaden
## Einstieg
- F1: Erzählen Sie mir doch zuerst, wie Ihr Arbeitsalltag aussieht.
  ~ Wie sieht ein typischer Arbeitstag aus?
  > Seit wann arbeiten Sie dort?
## Hauptteil
- Welche Rolle spielt künstliche Intelligenz für Sie?
- F3.1) Wie gehen Sie mit vertraulichen Daten um?
"""


def test_parse_guide():
    g = parse_guide(GUIDE)
    assert g.title == "Leitfaden"
    assert [q.code for q in g.questions] == ["F1", "F2", "F3.1"]
    assert g.questions[0].variants == ["Wie sieht ein typischer Arbeitstag aus?"]
    assert g.questions[0].probes == ["Seit wann arbeiten Sie dort?"]
    assert g.questions[1].section == "Hauptteil"


def test_guide_errors():
    with pytest.raises(GuideError):
        parse_guide("## nur ein Abschnitt")
    with pytest.raises(GuideError):
        parse_guide("- F1: a\n- F1: b")


# ------------------------------------------------------------------ roles

def _interview() -> Transcript:
    turns = [
        _turn("S0", 0, "Wie sieht Ihr Arbeitsalltag aus?"),
        _turn("S1", 3, "Ich bin Projektleiterin. Ich plane und bespreche viel mit dem Team."),
        _turn("S0", 10, "Mhm. Und welche Rolle spielt KI dabei?"),
        _turn("S1", 14, "Wir nutzen KI für Übersetzungen. Bei vertraulichen Daten sind wir "
                        "aber vorsichtig."),
        _turn("S0", 22, "Wie gehen Sie mit vertraulichen Daten um?"),
        _turn("S1", 25, "Das hatte ich ja schon gesagt, wir sind vorsichtig."),
    ]
    speakers = [{"label": "S0", "display_name": "S0"}, {"label": "S1", "display_name": "S1"}]
    meta = {"interview_id": "T", "models": {}}
    return Transcript(meta, speakers, turns)


def test_heuristic_roles():
    t = _interview()
    sents = split_sentences(t.turns)
    roles = assign_roles(t.speakers, sents, detect(sents), {}, None)
    assert roles["method"] == "heuristic" and roles["interviewer"] == "S0"
    assert [s["display_name"] for s in t.speakers] == ["Interviewer", "Befragte:r"]


def test_voice_profile_overrides_heuristic():
    t = _interview()
    sents = split_sentences(t.turns)
    voice = {"embedding": [0.0, 1.0]}
    emb = {"S0": [1.0, 0.0], "S1": [0.1, 0.99]}
    roles = assign_roles(t.speakers, sents, detect(sents), emb, voice)
    assert roles["method"] == "voice" and roles["interviewer"] == "S1"


def test_ambiguous_voice_falls_back_to_heuristic():
    t = _interview()
    sents = split_sentences(t.turns)
    roles = assign_roles(t.speakers, sents, detect(sents),
                         {"S0": [1.0, 0.9], "S1": [0.9, 1.0]}, {"embedding": [1.0, 1.0]})
    assert roles["method"] == "heuristic"


# ------------------------------------------------------------------ analyze

class FakeEncoder:
    """Bag-of-keywords vectors: similarity = shared topic keywords."""
    TOPICS = ["arbeitsalltag", "ki", "daten"]

    def encode(self, texts, prefix="query: "):
        vecs = []
        for t in texts:
            low = t.lower()
            v = np.array([1.0 if k in low else 0.0 for k in self.TOPICS] + [0.05])
            vecs.append(v / np.linalg.norm(v))
        return np.vstack(vecs)


def test_analyze_end_to_end_with_fake_encoder():
    t = _interview()
    guide = parse_guide(
        "- F1: Wie sieht Ihr Arbeitsalltag aus?\n- F2: Welche Rolle spielt KI?\n"
        "- F3: Wie gehen Sie mit vertraulichen Daten um?\n")
    opts = AnalysisOptions(guide=guide, match_threshold=0.9, answer_z=0.5)
    result = analyze(t, opts, None, FakeEncoder)

    qs = result["questions"]
    assert [(q["guide_code"], q["match"]) for q in qs] == [
        ("F1", "main"), ("F2", "main"), ("F3", "main")]
    assert qs[1]["text"] == "Und welche Rolle spielt KI dabei?"  # "Mhm." is not part of it

    direct = {a["question_id"]: [p["turn"] for p in a["passages"]] for a in result["answers"]}
    assert direct == {"Q1": [1], "Q2": [3], "Q3": [5]}

    # F3 (data) was already touched in turn 3, before it was asked → "anticipated"
    f3 = [s for s in result["suggestions"] if s["guide_code"] == "F3"]
    assert f3 and f3[0]["type"] == "anticipated" and f3[0]["passages"][0]["turn"] == 3


def test_group_questions_merges_adjacent_sentences():
    turn = _turn("S0", 0, "Wie war das? Und warum?")
    cands = detect(split_sentences([turn]))
    grouped = group_questions(cands)
    assert len(grouped) == 1 and grouped[0].text == "Wie war das? Und warum?"


def test_no_roles_without_diarization_keeps_all_questions():
    t = _interview()
    for turn in t.turns:
        turn.speaker = None
    t.speakers = []
    result = analyze(t, AnalysisOptions(), None, None)
    assert result["roles"]["method"] == "none"
    assert len(result["questions"]) == 3 and result["answers"] == []
