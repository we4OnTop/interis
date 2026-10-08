"""Word-level edits of a transcript: corrections, smoothing (Glättung) and speaker
corrections.

The machine transcript is never changed. Each edit refers to one word by its position
(turn, word index). Word indices never move, so every stored position (question marks,
answer links, extracts) stays valid. A deleted word keeps its timing and gets empty text.

Pure functions without I/O, so the logic is unit-testable.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
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


def apply_edits(t: Transcript, edits: list[dict[str, Any]],
                speakers: list[dict[str, Any]] = ()) -> Transcript:
    """A copy of ``t`` in which every edited word carries its effective text and speaker.

    ``edits``: dicts with ``turn``, ``word``, ``action`` (replace|delete) and ``text``.
    ``speakers``: dicts with ``turn``, ``word`` and ``speaker``. A turn whose words were
    given to another speaker keeps its place (so every stored position stays valid); its
    own speaker is then the one who says most of its words.
    Words outside the transcript are ignored. ``t`` itself is not modified.
    """
    by_turn: dict[int, dict[int, dict[str, Any]]] = {}
    for e in edits:
        by_turn.setdefault(e["turn"], {})[e["word"]] = e
    who: dict[int, dict[int, str]] = {}
    for s in speakers:
        who.setdefault(s["turn"], {})[s["word"]] = s["speaker"]

    turns = []
    for ti, turn in enumerate(t.turns):
        changes, moved = by_turn.get(ti, {}), who.get(ti, {})
        if not changes and not moved:
            turns.append(turn)
            continue
        words = []
        for wi, w in enumerate(turn.words):
            e = changes.get(wi)
            if e is not None:
                w = replace(w, text="" if e["action"] == "delete"
                            else _new_text(w.text, e["text"]))
            if wi in moved:
                w = replace(w, speaker=moved[wi])
            words.append(w)
        speaker = turn.speaker
        if moved:
            said = Counter(w.speaker or turn.speaker for w in words if w.text.strip())
            speaker = said.most_common(1)[0][0] if said else speaker
        turns.append(Turn(speaker, turn.start, turn.end, words))
    return Transcript(meta=t.meta, speakers=t.speakers, turns=turns, analysis=t.analysis)


def edits_digest(edits: list[dict[str, Any]], speakers: list[dict[str, Any]] = ()) -> str:
    """Fingerprint of the edits. The analysis stores the digest of the edits it was run
    with, so a later edit shows up as "analysis outdated"."""
    if not edits and not speakers:
        return EMPTY_DIGEST
    rows = sorted((e["turn"], e["word"], e["action"], e.get("text", ""), e.get("kind", ""),
                   e.get("tag", "")) for e in edits)
    # speaker corrections only enter when there are some: earlier digests stay the same
    rows += sorted((s["turn"], s["word"], "speaker", s["speaker"], "", "") for s in speakers)
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
