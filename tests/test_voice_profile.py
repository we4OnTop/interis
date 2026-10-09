"""Voice profile refinement and speaker assignment during transcription. Embeddings are
faked: each speaker's "voice" is a direction."""

import numpy as np
import pytest

from interis.analysis.roles import interviewer_by_voice, load_voice, merge_voice, save_voice
from interis.analysis.sentences import split_sentences
from interis.analysis.speakers import assign_by_voice, learn_voice
from interis.pipeline.types import Turn, Word

A, B = np.array([1.0, 0.0, 0.1]), np.array([0.0, 1.0, 0.1])


def _turn(speaker, start, text):
    words = [Word(f" {w}", start + i, start + i + 1, 0.9, speaker=speaker)
             for i, w in enumerate(text.split())]
    return Turn(speaker, start, start + len(words), words)


def test_learn_voice_drops_a_wrongly_labelled_sentence_and_counts_seconds():
    truth = {}
    turns = []
    for i in range(10):  # nine of the interviewer, one that is really the other person
        start = i * 10
        turns.append(_turn("A", start, "Wie sieht das denn bei Ihnen aus?"))
        truth[start] = B if i == 4 else A
    sentences = split_sentences(turns)
    rng = np.random.default_rng(0)

    def embed(a, _b):
        return truth[int(a // 10) * 10] + 0.02 * rng.standard_normal(3)

    learned = learn_voice(sentences, embed, "A")
    assert learned["n_segments"] == 9 and learned["seconds"] == pytest.approx(9 * 7)
    unit = learned["embedding"] / np.linalg.norm(learned["embedding"])
    assert unit @ (A / np.linalg.norm(A)) > 0.99


def test_learn_voice_can_be_limited_to_the_checked_part():
    turns = [_turn("A", i * 10, "Wie sieht das denn bei Ihnen aus?") for i in range(10)]
    learned = learn_voice(split_sentences(turns), lambda a, b: A, "A", until=60)
    assert learned["n_segments"] == 6
    with pytest.raises(ValueError, match="too few"):
        learn_voice(split_sentences(turns), lambda a, b: A, "A", until=30)


def test_merge_refines_instead_of_replacing(tmp_path):
    first = {"embedding": A, "seconds": 30.0, "n_segments": 5}
    second = {"embedding": B, "seconds": 10.0, "n_segments": 3}
    p1 = merge_voice(None, first, "I01", "rev")
    save_voice(tmp_path / "v.json", "interviewer", p1["embedding"], "rev",
               **{k: v for k, v in p1.items() if k != "embedding"})
    stored = load_voice(tmp_path / "v.json")
    assert stored["seconds"] == 30.0 and stored["sources"][0]["id"] == "I01"
    created = stored["created_at"]
    p2 = merge_voice(stored, second, "I02", "rev")
    assert p2["seconds"] == 40.0 and p2["n_segments"] == 8 and p2["created_at"] == created
    assert [s["id"] for s in p2["sources"]] == ["I01", "I02"]
    assert p2["embedding"][0] > p2["embedding"][1]  # the longer passage weighs more
    # a profile made with another model, or an old one without statistics, is replaced
    assert merge_voice({**stored, "model_revision": "old"}, second, "I02", "rev")["seconds"] == 10
    assert merge_voice({"embedding": [1, 0], "model_revision": "rev"}, second, "I02",
                       "rev")["seconds"] == 10.0


def test_interviewer_is_the_clearly_closest_cluster():
    voice = {"embedding": [1.0, 0.0]}
    emb = {"S0": [0.0, 1.0], "S1": [0.95, 0.1]}
    assert interviewer_by_voice(voice, emb, ["S0", "S1"])[0] == "S1"
    assert interviewer_by_voice(voice, {"S0": [1.0, 0.9], "S1": [0.9, 1.0]}, ["S0", "S1"])[0] \
        is None


def test_assign_by_voice_moves_sentences_to_the_closer_voice_and_merges_turns():
    # diarization put the 2nd sentence (really the interviewer) on B and the 3rd on A
    turns = [_turn("A", 0, "Wie geht es Ihnen heute?"),
             _turn("B", 10, "Und was machen Sie beruflich?"),
             _turn("B", 20, "Ich arbeite im Vertrieb seit Jahren."),
             _turn("A", 30, "Das klingt spannend sehr."),
             _turn("B", 40, "Ja es ist ein schöner Beruf.")]
    truth = {0: A, 10: A, 20: B, 30: A, 40: B}
    audio = np.zeros(60 * 16000, dtype=np.float32)
    for start, v in truth.items():  # the embedding is read from the audio level
        audio[start * 16000:(start + 9) * 16000] = 1.0 if v is A else 2.0

    def embed(piece):
        return A if piece.mean() < 1.5 else B

    voice = {"embedding": [1.0, 0.0, 0.1]}
    emb = {"A": [1.0, 0.0, 0.1], "B": [0.0, 1.0, 0.1]}
    new, report = assign_by_voice(turns, audio, embed, voice, emb, margin=0.1, min_s=1.0)
    assert report["applied"] and report["changed"] == 1
    assert [(t.speaker, t.start) for t in new] == [("A", 0), ("B", 20), ("A", 30), ("B", 40)]
    assert "A" not in {w.speaker for t in new if t.speaker == "B" for w in t.words}


def test_assign_by_voice_leaves_other_cases_alone():
    turns = [_turn("A", 0, "Wie geht es Ihnen heute?")]
    _, report = assign_by_voice(turns, np.zeros(16000), lambda x: A, {"embedding": [1, 0, 0]},
                                {"A": [1, 0, 0]}, 0.1)
    assert not report["applied"] and "two" in report["reason"]
    two = [_turn("A", 0, "a b c d e"), _turn("B", 10, "f g h i j")]
    _, report = assign_by_voice(two, np.zeros(16000), lambda x: A, {"embedding": [1, 1, 0]},
                                {"A": [1, 1, 0.1], "B": [1, 1, 0.2]}, 0.1)
    assert not report["applied"] and "not clearly" in report["reason"]
