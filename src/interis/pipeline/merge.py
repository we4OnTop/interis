"""Assign every word to a speaker and group words into speaker turns."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict

from interis.analysis.sentences import _ends_sentence
from interis.pipeline.types import Diarization, Segment, SpeakerSpan, Turn, Word

MAX_GAP_S = 1.0  # a word outside any speech span takes the nearest span within this gap


class _SpanIndex:
    def __init__(self, spans: list[SpeakerSpan]) -> None:
        self.spans = sorted(spans, key=lambda s: s.start)
        self.starts = [s.start for s in self.spans]
        self.max_len = max((s.end - s.start for s in self.spans), default=0.0)

    def overlapping(self, start: float, end: float) -> list[tuple[SpeakerSpan, float]]:
        hi = bisect_right(self.starts, end)
        lo = bisect_right(self.starts, start - self.max_len) - 1
        result = []
        for span in self.spans[max(lo, 0):hi]:
            ov = min(end, span.end) - max(start, span.start)
            if ov > 0:
                result.append((span, ov))
        return result

    def nearest(self, t: float) -> tuple[SpeakerSpan | None, float]:
        best, best_d = None, float("inf")
        i = bisect_right(self.starts, t)
        for span in self.spans[max(i - 2, 0):i + 2]:
            d = 0.0 if span.start <= t <= span.end else min(abs(t - span.start),
                                                            abs(t - span.end))
            if d < best_d:
                best, best_d = span, d
        return best, best_d


def assign_speakers(words: list[Word], diarization: Diarization) -> None:
    exclusive = _SpanIndex(diarization.exclusive)
    regular = _SpanIndex(diarization.regular)
    for w in words:
        start, end = w.start, max(w.end, w.start + 1e-3)
        totals: dict[str, float] = {}
        for span, ov in exclusive.overlapping(start, end):
            totals[span.speaker] = totals.get(span.speaker, 0.0) + ov
        if totals:
            w.speaker = max(totals, key=lambda k: totals[k])
        else:
            span, dist = exclusive.nearest((start + end) / 2)
            w.speaker = span.speaker if span is not None and dist <= MAX_GAP_S else None
        w.overlap = len({s.speaker for s, _ in regular.overlapping(start, end)}) > 1

    # Words still without speaker inherit from the previous word (or the next one).
    for i, w in enumerate(words):
        if w.speaker is None and i > 0:
            w.speaker = words[i - 1].speaker
    for i in range(len(words) - 2, -1, -1):
        if words[i].speaker is None:
            words[i].speaker = words[i + 1].speaker


def by_sentence(segments: list[Segment]) -> None:
    """Give every sentence one speaker: the one who has most of its speaking time.

    Word-level assignment flips the speaker inside a sentence wherever a diarization
    boundary is a little off, mostly at the first or last words of a turn. A sentence ends
    at sentence punctuation or at the end of a recognised segment (a pause), so short
    interjections ("Ja.", "Mhm.") stay their own sentence and keep their speaker."""
    for seg in segments:
        sentence: list[Word] = []
        for i, w in enumerate(seg.words):
            sentence.append(w)
            if _ends_sentence(w.text) or i == len(seg.words) - 1:
                time: dict[str | None, float] = defaultdict(float)
                for x in sentence:
                    time[x.speaker] += max(x.end - x.start, 1e-3)
                time.pop(None, None)
                if time:
                    speaker = max(time, key=lambda k: time[k])
                    for x in sentence:
                        x.speaker = speaker
                sentence = []


def group_words(words: list[Word], boundaries: list[float] | tuple[float, ...] = ()
                ) -> list[Turn]:
    """Consecutive words of one speaker form a turn; a turn never spans a break between
    two recordings (``boundaries``: start times of recording parts 2, 3, …)."""
    turns: list[Turn] = []
    for w in words:
        same_part = bool(turns) and not any(turns[-1].end <= b <= w.start for b in boundaries)
        if turns and same_part and turns[-1].speaker == w.speaker:
            turns[-1].words.append(w)
            turns[-1].end = max(turns[-1].end, w.end)
        else:
            turns.append(Turn(w.speaker, w.start, w.end, [w]))
    return turns


def build_turns(segments: list[Segment], diarization: Diarization | None,
                boundaries: list[float] | tuple[float, ...] = (),
                sentence_level: bool = False) -> list[Turn]:
    """``boundaries``: start times of recording parts 2, 3, … – a turn never spans a
    break between two recordings. ``sentence_level``: see :func:`by_sentence`."""
    if diarization is None:
        # Without diarization each ASR segment becomes one turn with unknown speaker.
        return [Turn(None, s.start, s.end, list(s.words)) for s in segments if s.words]

    words = [w for s in segments for w in s.words]
    assign_speakers(words, diarization)
    if sentence_level:
        by_sentence(segments)
    return group_words(words, boundaries)
