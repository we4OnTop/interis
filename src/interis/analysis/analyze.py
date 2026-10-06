"""Phase 2 analysis on top of a transcript.

1. split turns into sentences
2. detect question candidates (rules, see :mod:`questions`)
3. decide who the interviewer is (voice profile, else heuristic, see :mod:`roles`)
4. group the interviewer's question sentences into *asked questions*
5. match asked questions to the interview guide (E5 embeddings):
   main question / planned probe / ad-hoc follow-up
6. direct answer = interviewee turns after a question up to the next question
   (for main questions: up to the next main question, so follow-ups stay attached)
7. "answered elsewhere" suggestions: interviewee passages that are semantically close to
   a guide question but lie outside its direct answer (anticipated / later / unasked)

Everything produced here is a *suggestion* (``status: "suggested"``) with its evidence
(reason codes, similarity scores); confirming or rejecting happens in the review UI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from interis.analysis.guide import Guide
from interis.analysis.questions import QuestionCandidate, detect
from interis.analysis.roles import assign_roles
from interis.analysis.sentences import Sentence, split_sentences
from interis.pipeline.types import Transcript

# Calibrated for intfloat/multilingual-e5-large on German interview questions (see
# ARCHITECTURE.md §6a). E5 cosine similarities are compressed into roughly 0.7–1.0, so a
# guide match needs both a high absolute score and a clear lead over the second-best guide
# question; ad-hoc follow-ups ("Wie meinen Sie das?") have small leads.
MATCH_THRESHOLD = 0.89
MATCH_MARGIN = 0.05
# Answer suggestions are relative: a passage must stand out among all interviewee passages
# of the same interview (z-score), plus an absolute floor.
ANSWER_Z = 1.5
ANSWER_FLOOR = 0.78
MAX_SUGGESTIONS = 3
ANALYSIS_VERSION = 1


@dataclass
class AskedQuestion:
    id: str
    turn: int
    first: int
    last: int
    start: float
    end: float
    text: str
    speaker: str | None
    kind: str
    reasons: list[str]
    confidence: float
    match: str | None = None  # "main" | "probe" | "followup" (None without guide)
    guide_code: str | None = None
    guide_score: float | None = None
    status: str = "suggested"


@dataclass
class Passage:
    turn: int
    first: int
    last: int
    start: float
    end: float
    text: str


@dataclass
class AnswerLink:
    question_id: str | None
    guide_code: str | None
    type: str  # "direct" | "anticipated" | "later" | "unasked"
    passages: list[Passage] = field(default_factory=list)
    score: float | None = None
    z: float | None = None  # how much this passage stands out (suggestions only)
    source: str = "auto"
    status: str = "suggested"


@dataclass
class AnalysisOptions:
    guide: Guide | None = None
    voice: dict[str, Any] | None = None
    redo_roles: bool = True
    match_threshold: float = MATCH_THRESHOLD
    match_margin: float = MATCH_MARGIN
    answer_z: float = ANSWER_Z


EncoderFactory = Callable[[], Any]


def group_questions(candidates: list[QuestionCandidate]) -> list[AskedQuestion]:
    """Merge consecutive question sentences of one turn into one asked question."""
    grouped: list[list[QuestionCandidate]] = []
    for c in sorted(candidates, key=lambda c: (c.sentence.turn, c.sentence.first)):
        prev = grouped[-1][-1].sentence if grouped else None
        if prev and prev.turn == c.sentence.turn and c.sentence.first == prev.last + 1:
            grouped[-1].append(c)
        else:
            grouped.append([c])
    out = []
    for n, group in enumerate(grouped, 1):
        first, last = group[0].sentence, group[-1].sentence
        reasons = sorted({r for c in group for r in c.reasons})
        out.append(AskedQuestion(
            id=f"Q{n}", turn=first.turn, first=first.first, last=last.last,
            start=first.start, end=last.end, text=" ".join(c.sentence.text for c in group),
            speaker=first.speaker,
            kind="question" if any(c.kind == "question" for c in group) else "prompt",
            reasons=reasons, confidence=max(c.confidence for c in group),
        ))
    return out


def _match_guide(questions: list[AskedQuestion], guide: Guide, encoder: Any,
                 threshold: float, margin: float) -> None:
    items: list[tuple[str, str]] = []  # (code, "main" | "probe")
    texts: list[str] = []
    for gq in guide.questions:
        for t in [gq.text, *gq.variants]:
            items.append((gq.code, "main"))
            texts.append(t)
        for t in gq.probes:
            items.append((gq.code, "probe"))
            texts.append(t)
    if not questions:
        return
    sims = encoder.encode([q.text for q in questions]) @ encoder.encode(texts).T
    codes = [code for code, _ in items]
    for q, row in zip(questions, sims, strict=True):
        best = int(np.argmax(row))
        # lead over the best entry belonging to a *different* guide question
        others = [row[i] for i in range(len(row)) if codes[i] != codes[best]]
        lead = float(row[best] - max(others)) if others else 1.0
        q.guide_score = round(float(row[best]), 3)
        if row[best] >= threshold and lead >= margin:
            q.guide_code, q.match = items[best]
        else:
            q.match = "followup"


def _turn_passage(transcript: Transcript, ti: int) -> Passage:
    turn = transcript.turns[ti]
    return Passage(ti, 0, len(turn.words) - 1, turn.start, turn.end, turn.text)


def _direct_answers(transcript: Transcript, questions: list[AskedQuestion],
                    interviewer: str) -> list[AnswerLink]:
    links = []
    for i, q in enumerate(questions):
        later = questions[i + 1:]
        if q.match == "main":
            boundary = next((n for n in later if n.match == "main"), None)
        else:
            boundary = later[0] if later else None
        end_turn = boundary.turn if boundary else len(transcript.turns)
        passages = [_turn_passage(transcript, ti) for ti in range(q.turn + 1, end_turn)
                    if transcript.turns[ti].speaker not in (interviewer, None)]
        if q.match != "main" and boundary is not None:
            # follow-up answers stop at the next question of any kind
            passages = [p for p in passages if p.turn < boundary.turn]
        links.append(AnswerLink(q.id, q.guide_code, "direct", passages))
    return links


def _windows(sentences: list[Sentence], interviewer: str) -> list[Passage]:
    """Interviewee passages of up to two consecutive sentences of one turn."""
    own = [s for s in sentences if s.speaker not in (interviewer, None)
           and len(s.text.split()) >= 4]
    out = []
    for i, s in enumerate(own):
        nxt = own[i + 1] if i + 1 < len(own) and own[i + 1].turn == s.turn else None
        group = [s, nxt] if nxt else [s]
        out.append(Passage(s.turn, s.first, group[-1].last, s.start, group[-1].end,
                           " ".join(g.text for g in group)))
    return out


def _elsewhere(sentences: list[Sentence], questions: list[AskedQuestion],
               direct: list[AnswerLink], guide: Guide, interviewer: str, encoder: Any,
               min_z: float) -> list[AnswerLink]:
    windows = _windows(sentences, interviewer)
    if len(windows) < 3:
        return []
    q_vecs = encoder.encode([" ".join([g.text, *g.variants]) for g in guide.questions])
    w_vecs = encoder.encode([w.text for w in windows], prefix="passage: ")
    sims = q_vecs @ w_vecs.T
    # z-score per guide question across all passages of this interview
    z = (sims - sims.mean(axis=1, keepdims=True)) / (sims.std(axis=1, keepdims=True) + 1e-6)

    direct_turns: dict[str, set[int]] = {}
    first_asked: dict[str, float] = {}
    for q, link in zip(questions, direct, strict=True):
        if q.guide_code and q.match == "main":
            direct_turns.setdefault(q.guide_code, set()).update(p.turn for p in link.passages)
            first_asked.setdefault(q.guide_code, q.start)

    suggestions = []
    for gi, gq in enumerate(guide.questions):
        order = np.argsort(-z[gi])
        taken: set[int] = set()
        for wi in order:
            score = float(sims[gi, wi])
            if z[gi, wi] < min_z or len(taken) >= MAX_SUGGESTIONS:
                break
            if score < ANSWER_FLOOR:
                continue
            w = windows[wi]
            if w.turn in direct_turns.get(gq.code, set()) or w.turn in taken:
                continue
            asked_at = first_asked.get(gq.code)
            kind = ("unasked" if asked_at is None
                    else "anticipated" if w.end <= asked_at else "later")
            suggestions.append(AnswerLink(None, gq.code, kind, [w], round(score, 3),
                                          z=round(float(z[gi, wi]), 2)))
            taken.add(w.turn)
    return suggestions


def analyze(transcript: Transcript, opts: AnalysisOptions,
            speaker_embeddings: dict[str, list[float]] | None = None,
            encoder_factory: EncoderFactory | None = None) -> dict[str, Any]:
    sentences = split_sentences(transcript.turns)
    candidates = detect(sentences)

    if opts.redo_roles:
        roles = assign_roles(transcript.speakers, sentences, candidates,
                             speaker_embeddings or {}, opts.voice)
    else:
        prior = transcript.analysis.get("roles", {})
        roles = {**prior, "interviewer": next(
            (s["label"] for s in transcript.speakers if s.get("role") == "interviewer"), None)}
    interviewer = roles.get("interviewer")

    if interviewer is not None:
        candidates = [c for c in candidates if c.sentence.speaker == interviewer]
    questions = group_questions(candidates)

    encoder = encoder_factory() if (opts.guide and encoder_factory) else None
    answers: list[AnswerLink] = []
    suggestions: list[AnswerLink] = []
    if encoder is not None and opts.guide is not None:
        _match_guide(questions, opts.guide, encoder, opts.match_threshold, opts.match_margin)
    if interviewer is not None:
        answers = _direct_answers(transcript, questions, interviewer)
        if encoder is not None and opts.guide is not None:
            suggestions = _elsewhere(sentences, questions, answers, opts.guide, interviewer,
                                     encoder, opts.answer_z)

    return {
        "version": ANALYSIS_VERSION,
        "roles": roles,
        "guide": opts.guide.to_dict() if opts.guide else None,
        "thresholds": {"match": opts.match_threshold, "match_margin": opts.match_margin,
                       "answer_z": opts.answer_z, "answer_floor": ANSWER_FLOOR},
        "questions": [asdict(q) for q in questions],
        "answers": [asdict(a) for a in answers],
        "suggestions": [asdict(s) for s in suggestions],
    }
