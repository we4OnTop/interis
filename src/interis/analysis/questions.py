"""Rule-based detection of interviewer questions in German.

Deterministic and explainable: every candidate records *why* it was marked (reason codes),
so the method can be described in the thesis and every mark can be checked.

Reason codes
------------
question_mark     sentence ends with "?"
interrogative     starts with a question word (wer, wie, warum, inwiefern, welche …)
verb_first        starts with a finite verb followed by a pronoun ("Haben Sie …")
narrative_prompt  imperative prompt ("Erzählen Sie mal …", "Beschreiben Sie …")
interest          indirect question ("Mich würde interessieren …", "Ich würde gern wissen …")

Backchannels ("Mhm?", "Okay.", "Ja, genau.") are never marked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from interis.analysis.sentences import Sentence

_FILLERS = {
    "und", "also", "ähm", "äh", "öhm", "ehm", "hm", "hmm", "mhm", "okay", "ok", "ja", "gut",
    "so", "jetzt", "dann", "nun", "aber", "na", "genau", "ach", "achso", "schön", "prima",
    "super", "danke", "interessant", "alles", "klar", "spannend", "verstehe", "aha",
}
_BACKCHANNEL = _FILLERS | {"richtig", "stimmt", "ne", "nee", "nein", "sicher", "toll", "echt",
                           "wirklich", "ah", "oh", "sehr", "vielen", "dank"}
_INTERROGATIVES = {
    "wer", "wen", "wem", "wessen", "was", "wann", "wie", "wieso", "weshalb", "warum",
    "weswegen", "wo", "woher", "wohin", "womit", "wofür", "worüber", "wozu", "wodurch",
    "woran", "worauf", "wovon", "wovor", "worin", "woraus", "inwiefern", "inwieweit",
    "wieviel", "wievielen",
}
_FINITE_VERBS = {
    "haben", "hast", "hat", "habt", "hatten", "hattest", "hätten", "hättest", "hätte",
    "sind", "bist", "ist", "seid", "war", "warst", "waren", "wäre", "wären", "wärst",
    "können", "kannst", "kann", "könnten", "könntest", "könnte", "konnten",
    "würden", "würdest", "würde", "wird", "werden", "wirst",
    "gibt", "gab", "gäbe", "möchten", "möchtest", "möchte", "wollen", "willst", "wollten",
    "sollen", "sollte", "sollten", "müssen", "musst", "muss", "mussten", "dürfen", "darf",
    "durften", "nutzen", "nutzt", "machen", "macht", "machst", "arbeiten", "arbeitest",
    "glauben", "glaubst", "denken", "denkst", "finden", "findest", "sehen", "siehst",
    "kennen", "kennst", "wissen", "weißt", "erinnern", "erinnerst", "fühlen", "fühlst",
    "spielt", "spielen", "verwenden", "verwendest", "haltet", "halten", "hältst", "erleben",
    "erlebst", "empfinden", "empfindest", "brauchen", "brauchst", "bekommen", "bekommst",
    "meinen", "meinst", "fällt", "fallen", "gehen", "geht", "gehst", "kommt", "kommen",
}
_PRONOUNS = {
    "sie", "du", "ihr", "man", "es", "das", "dies", "dieses", "er", "wir", "ich", "der", "die",
    "den", "dem", "euch", "ihnen", "dir", "dich", "da", "denn", "eigentlich", "mal", "bei",
    "in", "im", "ein", "eine", "einen", "jemand", "etwas",
}
_PROMPT_VERBS = {
    "erzählen", "erzähl", "erzählt", "beschreiben", "beschreib", "beschreibt", "schildern",
    "schilder", "erklären", "erklär", "berichten", "nennen", "stellen", "denken", "überlegen",
    "versetzen", "gehen",
}
_PROMPT_NEXT = {"sie", "du", "ihr", "mal", "doch", "bitte", "mir", "uns", "gerne", "gern"}
_INTEREST = re.compile(
    r"\b(mich würde (noch )?interessieren|mich interessiert|ich würde (sie )?(noch )?gerne? "
    r"(wissen|erfahren|hören|fragen)|ich möchte (sie )?(noch )?gerne? (wissen|erfahren|hören|"
    r"fragen)|ich wüsste gerne?|sagen sie mal|sag mal|meine (nächste )?frage)\b"
)
_WORD = re.compile(r"[^\wäöüß]+")

_WEIGHTS = {"question_mark": 0.9, "interrogative": 0.8, "narrative_prompt": 0.75,
            "interest": 0.7, "verb_first": 0.6}

Kind = Literal["question", "prompt"]


@dataclass
class QuestionCandidate:
    sentence: Sentence
    kind: Kind
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0


def _tokens(text: str) -> list[str]:
    return [t for t in (_WORD.sub("", w).lower() for w in text.split()) if t]


def _strip_fillers(tokens: list[str]) -> list[str]:
    i = 0
    while i < min(len(tokens) - 1, 4) and tokens[i] in _FILLERS:
        i += 1
    return tokens[i:]


def is_backchannel(text: str) -> bool:
    tokens = _tokens(text)
    return len(tokens) <= 4 and all(t in _BACKCHANNEL for t in tokens)


def classify(sentence: Sentence) -> QuestionCandidate | None:
    text = sentence.text.strip()
    if not text or is_backchannel(text):
        return None
    tokens = _strip_fillers(_tokens(text))
    if not tokens:
        return None

    reasons: list[str] = []
    if text.endswith("?"):
        reasons.append("question_mark")
    first = tokens[0]
    if first in _INTERROGATIVES or first.startswith("welch"):
        reasons.append("interrogative")
    if first in _FINITE_VERBS and len(tokens) > 1 and tokens[1] in _PRONOUNS:
        reasons.append("verb_first")
    if first in _PROMPT_VERBS and len(tokens) > 1 and tokens[1] in _PROMPT_NEXT:
        reasons.append("narrative_prompt")
    if _INTEREST.search(" ".join(_tokens(text))):
        reasons.append("interest")
    if not reasons:
        return None
    # A lone verb-first statement without "?" is too weak ("Hat gut geklappt.").
    if reasons == ["verb_first"] and len(tokens) < 4:
        return None

    confidence = max(_WEIGHTS[r] for r in reasons) + 0.05 * (len(reasons) - 1)
    is_question = "question_mark" in reasons or "interrogative" in reasons or (
        "verb_first" in reasons and "narrative_prompt" not in reasons)
    return QuestionCandidate(sentence, "question" if is_question else "prompt", reasons,
                             round(min(confidence, 1.0), 2))


def detect(sentences: list[Sentence]) -> list[QuestionCandidate]:
    return [c for s in sentences if (c := classify(s)) is not None]
