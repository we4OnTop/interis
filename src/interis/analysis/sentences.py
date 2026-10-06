"""Split speaker turns into sentences, using Whisper's punctuation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from interis.pipeline.types import Turn

_ABBREVIATIONS = {
    "z.b.", "d.h.", "bzw.", "ca.", "dr.", "prof.", "u.a.", "usw.", "etc.", "nr.", "evtl.",
    "ggf.", "vgl.", "bspw.", "inkl.", "z.t.", "o.ä.", "u.ä.", "sog.", "min.", "max.", "s.",
    "u.", "o.", "a.", "frau.", "herr.", "abs.", "str.", "jh.",
}
_ORDINAL = re.compile(r"^\d+\.$")  # "am 3. Mai"


@dataclass
class Sentence:
    turn: int  # index into Transcript.turns
    first: int  # first word index within the turn
    last: int  # last word index within the turn (inclusive)
    text: str
    start: float
    end: float
    speaker: str | None


def _ends_sentence(token: str) -> bool:
    t = token.strip().lower()
    if not t.endswith((".", "?", "!", "…")):
        return False
    return t not in _ABBREVIATIONS and not _ORDINAL.match(t)


def split_sentences(turns: list[Turn]) -> list[Sentence]:
    out: list[Sentence] = []
    for ti, turn in enumerate(turns):
        first = 0
        for wi, word in enumerate(turn.words):
            if _ends_sentence(word.text) or wi == len(turn.words) - 1:
                words = turn.words[first:wi + 1]
                text = "".join(w.text for w in words).strip()
                if text:
                    out.append(Sentence(ti, first, wi, text, words[0].start, words[-1].end,
                                        turn.speaker))
                first = wi + 1
    return out
