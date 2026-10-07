"""Word-level edits of a transcript: corrections and smoothing (Glättung).

The machine transcript is never changed. Each edit refers to one word by its position
(turn, word index). Word indices never move, so every stored position (question marks,
answer links, extracts) stays valid. A deleted word keeps its timing and gets empty text.

Pure functions without I/O, so the logic is unit-testable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

from interis.pipeline.types import Transcript, Turn

KINDS = ("correction", "smoothing")
ACTIONS = ("replace", "delete")

# Reasons for smoothing (Glättung), following the usual rules for a "geglättetes Transkript"
# (Dresing & Pehl). Each project may replace this list; see ``project_tags``.
DEFAULT_TAGS = (
    "Füllwort",
    "Wortwiederholung",
    "Satzabbruch",
    "Grammatik",
    "Dialekt",
    "Anonymisierung",
    "Sonstiges",
)
MAX_TAGS = 30
MAX_TAG_LEN = 40
MAX_TEXT_LEN = 200

EMPTY_DIGEST = hashlib.sha256(b"[]").hexdigest()


def parse_tags(raw: str) -> list[str]:
    """Newline-separated tag list as typed by the user: trimmed, de-duplicated, no blanks."""
    seen: dict[str, None] = {}
    for line in raw.splitlines():
        tag = line.strip()
        if tag:
            seen.setdefault(tag, None)
    return list(seen)


def project_tags(raw: str) -> list[str]:
    """The smoothing tags of a project; the defaults while none are set."""
    return parse_tags(raw) or list(DEFAULT_TAGS)


def _new_text(original: str, new: str) -> str:
    """Keep the Whisper convention: a token carries its leading space, the text does not."""
    core = new.strip()
    if not core:
        return ""
    return (" " if original[:1].isspace() else "") + core


def apply_edits(t: Transcript, edits: list[dict[str, Any]]) -> Transcript:
    """A copy of ``t`` in which every edited word carries its effective text.

    ``edits``: dicts with ``turn``, ``word``, ``action`` (replace|delete) and ``text``.
    Words outside the transcript are ignored. ``t`` itself is not modified.
    """
    by_turn: dict[int, dict[int, dict[str, Any]]] = {}
    for e in edits:
        by_turn.setdefault(e["turn"], {})[e["word"]] = e

    turns = []
    for ti, turn in enumerate(t.turns):
        changes = by_turn.get(ti)
        if not changes:
            turns.append(turn)
            continue
        words = []
        for wi, w in enumerate(turn.words):
            e = changes.get(wi)
            if e is None:
                words.append(w)
            elif e["action"] == "delete":
                words.append(replace(w, text=""))
            else:
                words.append(replace(w, text=_new_text(w.text, e["text"])))
        turns.append(Turn(turn.speaker, turn.start, turn.end, words))
    return Transcript(meta=t.meta, speakers=t.speakers, turns=turns, analysis=t.analysis)


def edits_digest(edits: list[dict[str, Any]]) -> str:
    """Fingerprint of the edits. The analysis stores the digest of the edits it was run
    with, so a later edit shows up as "analysis outdated"."""
    if not edits:
        return EMPTY_DIGEST
    rows = sorted((e["turn"], e["word"], e["action"], e.get("text", ""), e.get("kind", ""),
                   e.get("tag", "")) for e in edits)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def edited_words(t: Transcript,
                 edits: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    """{(turn, word): {"orig", "kind", "tag", "action"}} for words whose text differs."""
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for e in edits:
        try:
            orig = t.turns[e["turn"]].words[e["word"]].text
        except IndexError:
            continue
        out[(e["turn"], e["word"])] = {"orig": orig, "kind": e["kind"], "tag": e.get("tag", ""),
                                       "action": e["action"]}
    return out
