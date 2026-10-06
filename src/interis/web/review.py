"""Combine the machine analysis with your review decisions.

Pure functions without I/O, so the logic is unit-testable.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from interis.analysis.analyze import AskedQuestion, _direct_answers
from interis.analysis.guide import Guide
from interis.pipeline.types import Transcript


def interviewer_of(t: Transcript) -> str | None:
    return next((s["label"] for s in t.speakers if s.get("role") == "interviewer"), None)


def passage(t: Transcript, turn: int, first: int, last: int) -> dict[str, Any]:
    words = t.turns[turn].words[first:last + 1]
    return {"turn": turn, "first": first, "last": last, "start": words[0].start,
            "end": words[-1].end, "text": "".join(w.text for w in words).strip()}


def effective_questions(t: Transcript, marks: list[dict[str, Any]]) -> list[AskedQuestion]:
    """Machine-detected questions with your corrections applied, plus your own marks."""
    by_key = {(m["turn"], m["first"]): m for m in marks}
    out: list[AskedQuestion] = []
    for raw in t.analysis.get("questions", []):
        q = AskedQuestion(**raw)
        mark = by_key.pop((q.turn, q.first), None)
        if mark is not None:
            if mark["status"] == "rejected":
                continue
            q = replace(q, last=mark["last"], guide_code=mark["guide_code"],
                        match=mark["match"], status="confirmed")
            p = passage(t, q.turn, q.first, q.last)
            q.end, q.text = p["end"], p["text"]
        out.append(q)
    for mark in by_key.values():
        if mark["status"] == "rejected":
            continue
        p = passage(t, mark["turn"], mark["first"], mark["last"])
        out.append(AskedQuestion(
            id="", turn=mark["turn"], first=mark["first"], last=mark["last"],
            start=p["start"], end=p["end"], text=p["text"],
            speaker=t.turns[mark["turn"]].speaker, kind="question", reasons=["manual"],
            confidence=1.0, match=mark["match"], guide_code=mark["guide_code"],
            status="confirmed"))
    out.sort(key=lambda q: (q.turn, q.first))
    for n, q in enumerate(out, 1):
        q.id = f"Q{n}"
    return out


def _dialogue(t: Transcript, start_turn: int, end_turn: int,
              questions: list[AskedQuestion]) -> list[dict[str, Any]]:
    """Turns of a question/answer exchange, with question spans marked."""
    names = {s["label"]: s.get("display_name") or s["label"] for s in t.speakers}
    roles = {s["label"]: s.get("role", "unknown") for s in t.speakers}
    out = []
    for ti in range(start_turn, end_turn):
        turn = t.turns[ti]
        spans = sorted((q for q in questions if q.turn == ti), key=lambda q: q.first)
        pieces, pos = [], 0
        for q in spans:
            if q.first > pos:
                pieces.append({"text": "".join(w.text for w in turn.words[pos:q.first]).strip()})
            pieces.append({"text": q.text, "question": True, "code": q.guide_code,
                           "match": q.match, "turn": q.turn, "first": q.first,
                           "last": q.last, "status": q.status})
            pos = q.last + 1
        if pos < len(turn.words):
            pieces.append({"text": "".join(w.text for w in turn.words[pos:]).strip()})
        out.append({"turn": ti, "start": turn.start, "end": turn.end,
                    "n_words": len(turn.words), "speaker": names.get(turn.speaker, "?"),
                    "role": roles.get(turn.speaker, "unknown"),
                    "pieces": [p for p in pieces if p["text"]]})
    return out


def interview_state(t: Transcript, marks: list[dict[str, Any]],
                    links: list[dict[str, Any]], guide: Guide | None) -> dict[str, Any]:
    """Everything the comparison view needs for one interview, keyed by guide code."""
    questions = effective_questions(t, marks)
    interviewer = interviewer_of(t)
    direct = _direct_answers(t, questions, interviewer) if interviewer else []
    answer_of = {q.id: a for q, a in zip(questions, direct, strict=False)}

    # which guide question's direct answer contains a given turn
    turn_owner: dict[int, str] = {}
    for q in questions:
        if q.match == "main" and q.guide_code and q.id in answer_of:
            for p in answer_of[q.id].passages:
                turn_owner.setdefault(p.turn, q.guide_code)

    first_asked: dict[str, float] = {}
    for q in questions:
        if q.match == "main" and q.guide_code:
            first_asked.setdefault(q.guide_code, q.start)

    decided = {(lk["guide_code"], lk["turn"], lk["first"], lk["last"]) for lk in links}
    cells: dict[str, dict[str, Any]] = {}
    codes = [g.code for g in guide.questions] if guide else []
    for code in codes:
        asked = [q for q in questions if q.guide_code == code and q.match == "main"]
        exchanges = []
        for q in asked:
            i = questions.index(q)
            nxt = next((n for n in questions[i + 1:] if n.match == "main"), None)
            end_turn = nxt.turn if nxt else len(t.turns)
            exchanges.append({"question": asdict(q), "start": q.start,
                              "dialogue": _dialogue(t, q.turn, end_turn, questions)})

        def describe(lk: dict[str, Any], code: str = code) -> dict[str, Any]:
            p = passage(t, lk["turn"], lk["first"], lk["last"])
            asked_at = first_asked.get(code)
            kind = ("unasked" if asked_at is None
                    else "anticipated" if p["end"] <= asked_at else "later")
            return {**lk, **p, "type": kind, "from_code": turn_owner.get(lk["turn"])}

        confirmed = [describe(lk) for lk in links
                     if lk["guide_code"] == code and lk["status"] == "confirmed"]
        own_turns = {p.turn for q in asked if q.id in answer_of
                     for p in answer_of[q.id].passages}
        suggestions = []
        for s in t.analysis.get("suggestions", []):
            p0 = s["passages"][0]
            key = (code, p0["turn"], p0["first"], p0["last"])
            if s["guide_code"] != code or key in decided or p0["turn"] in own_turns:
                continue
            suggestions.append({**describe({"turn": p0["turn"], "first": p0["first"],
                                            "last": p0["last"]}),
                                "score": s.get("score"), "z": s.get("z")})
        if asked:
            status = "asked"
        elif any(lk["omitted"] for lk in confirmed):
            status = "omitted"
        elif confirmed:
            status = "answered_elsewhere"
        else:
            status = "missing"
        cells[code] = {"status": status, "exchanges": exchanges, "links": confirmed,
                       "suggestions": suggestions}

    unassigned = [asdict(q) for q in questions if not (q.match in ("main", "probe")
                                                       and q.guide_code)]
    return {"cells": cells, "unassigned": unassigned,
            "questions": [asdict(q) for q in questions]}


def guide_mismatch(t: Transcript, guide: Guide | None) -> bool:
    """True if the transcript was analysed with a different guide than the current one."""
    if guide is None:
        return False
    used = (t.analysis.get("guide") or {}).get("questions", [])
    return [(q["code"], q["text"]) for q in used] != [(q.code, q.text) for q in guide.questions]
