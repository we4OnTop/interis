"""Compare a machine transcript with the transcript you corrected.

* **WER** – word error rate (substitutions + deletions + insertions) / reference words,
  exact Levenshtein alignment (banded for very long texts).
* **speaker error** – share of aligned word pairs attributed to the wrong person. The
  machine's speaker labels are matched to your speakers in the way that fits best, so it
  does not matter which label the machine gave to whom ("who said it", not "what is the
  interviewer called").

Text is normalised the same way on both sides: case-folded, punctuation removed, bracketed
annotations such as ``[unverständlich]`` dropped. Numbers are compared as written
(``5`` ≠ ``fünf``).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import permutations

from interis.pipeline.types import Transcript, Word

_ANNOTATION = re.compile(r"\[[^\]]{0,60}\]")
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")
MIN_BAND = 100
MAX_EXACT_SPEAKERS = 8

Pair = tuple[int | None, int | None]  # (reference index, hypothesis index)


def tokenize(text: str) -> list[tuple[str, str]]:
    """[(normalised, as written)] for every word of ``text``."""
    return [(m.group().casefold().replace("’", "'"), m.group())
            for m in _TOKEN.finditer(_ANNOTATION.sub(" ", text))]


def align(ref: list[str], hyp: list[str]) -> list[Pair]:
    """Minimal edit alignment; ties prefer match/substitution over insert/delete."""
    n, m = len(ref), len(hyp)
    w = abs(n - m) + max(MIN_BAND, max(n, m) // 10)
    inf = 1 << 30

    def span(i: int) -> tuple[int, int]:
        c = round(i * m / n) if n else 0
        return max(0, c - w), min(m, c + w)

    spans = [span(i) for i in range(n + 1)]
    cost: list[list[int]] = []
    back: list[bytearray] = []  # 0 diagonal, 1 deletion (ref only), 2 insertion (hyp only)
    for i in range(n + 1):
        lo, hi = spans[i]
        row = [inf] * (hi - lo + 1)
        ptr = bytearray(hi - lo + 1)
        plo, phi, prev = 0, -1, row
        if i:
            (plo, phi), prev = spans[i - 1], cost[i - 1]
        for j in range(lo, hi + 1):
            k = j - lo
            if i == 0 and j == 0:
                row[k] = 0
                continue
            best, how = inf, 0
            if i and j and plo <= j - 1 <= phi:
                best = prev[j - 1 - plo] + (ref[i - 1] != hyp[j - 1])
            if i and plo <= j <= phi and prev[j - plo] + 1 < best:
                best, how = prev[j - plo] + 1, 1
            if j > lo and row[k - 1] + 1 < best:
                best, how = row[k - 1] + 1, 2
            row[k], ptr[k] = best, how
        cost.append(row)
        back.append(ptr)
    pairs: list[Pair] = []
    i, j = n, m
    while i or j:
        how = back[i][j - spans[i][0]]
        if i and j and how == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and how == 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return pairs[::-1]


@dataclass
class RefTokens:
    norm: list[str]
    raw: list[str]
    speakers: list[str]


def reference_from_transcript(t: Transcript, start: float = 0.0,
                              end: float = float("inf")) -> RefTokens:
    """The words (with speakers) of a corrected transcript between ``start`` and ``end``
    seconds. ``t`` is the *effective* transcript: corrections and speaker corrections
    already applied (see :func:`interis.web.edits.apply_edits`)."""
    out = RefTokens([], [], [])
    for turn in t.turns:
        if turn.end < start or turn.start > end:
            continue
        for w in turn.words:
            if not w.text.strip() or w.start < start - 0.05 or w.end > end + 0.05:
                continue
            for norm, raw in tokenize(w.text):
                out.norm.append(norm)
                out.raw.append(raw)
                out.speakers.append(w.speaker or turn.speaker or "?")
    return out


@dataclass
class HypTokens:
    norm: list[str]
    word: list[Word]  # the transcript word each token came from
    speakers: list[str]


def hyp_tokens(t: Transcript) -> HypTokens:
    out = HypTokens([], [], [])
    for turn in t.turns:
        for w in turn.words:
            for norm, _ in tokenize(w.text):
                out.norm.append(norm)
                out.word.append(w)
                out.speakers.append(w.speaker or turn.speaker or "?")
    return out


def _fitting_matches(pairs: Counter) -> int:
    """Most pairs that agree when each machine speaker stands for one real speaker."""
    refs = sorted({r for r, _ in pairs})
    hyps = sorted({h for _, h in pairs})
    if len(refs) > MAX_EXACT_SPEAKERS or len(hyps) > MAX_EXACT_SPEAKERS:
        taken, total = set(), 0  # greedy for absurd speaker counts
        for (r, h), n in pairs.most_common():
            if r not in {x for x, _ in taken} and h not in {y for _, y in taken}:
                taken.add((r, h))
                total += n
        return total
    best = 0
    for perm in permutations([*hyps, *([None] * len(refs))], len(refs)):
        best = max(best, sum(pairs[(r, h)] for r, h in zip(refs, perm, strict=True)
                             if h is not None))
    return best


@dataclass
class Scores:
    wer: float
    speaker_error: float
    ref_words: int
    substitutions: int
    deletions: int
    insertions: int
    aligned_pairs: int
    speaker_errors: int

    @property
    def loss(self) -> float:
        """What tuning minimises: wrong words plus wrongly attributed words."""
        return self.wer + self.speaker_error

    def as_dict(self) -> dict[str, float | int]:
        return {**asdict(self), "loss": round(self.loss, 4)}


def score(ref: RefTokens, hyp: HypTokens) -> Scores:
    sub = dele = ins = 0
    pairs: Counter = Counter()
    for i, j in align(ref.norm, hyp.norm):
        if i is None:
            ins += 1
        elif j is None:
            dele += 1
        else:
            sub += ref.norm[i] != hyp.norm[j]
            pairs[(ref.speakers[i], hyp.speakers[j])] += 1
    both = sum(pairs.values())
    wrong = both - _fitting_matches(pairs) if both else 0
    n = len(ref.norm)
    return Scores(
        wer=round((sub + dele + ins) / max(n, 1), 4),
        speaker_error=round(wrong / max(both, 1), 4),
        ref_words=n, substitutions=sub, deletions=dele, insertions=ins,
        aligned_pairs=both, speaker_errors=wrong,
    )


def pool(scores: list[Scores]) -> Scores:
    """Combine several references, weighted by their length."""
    n = sum(s.ref_words for s in scores)
    both = sum(s.aligned_pairs for s in scores)
    sub, dele, ins = (sum(getattr(s, k) for s in scores)
                      for k in ("substitutions", "deletions", "insertions"))
    wrong = sum(s.speaker_errors for s in scores)
    return Scores(round((sub + dele + ins) / max(n, 1), 4), round(wrong / max(both, 1), 4),
                  n, sub, dele, ins, both, wrong)


def glossary(ref: RefTokens, hyp: HypTokens, limit: int = 40) -> list[str]:
    """Words the corrections fixed: reference words (as written, e.g. names and technical
    terms) the machine got wrong, most frequent first."""
    wrong: dict[str, int] = {}
    for i, j in align(ref.norm, hyp.norm):
        if i is not None and (j is None or ref.norm[i] != hyp.norm[j]):
            raw = ref.raw[i]
            if len(raw) >= 4 and not raw.isdigit():
                wrong[raw] = wrong.get(raw, 0) + 1
    return [w for w, _ in sorted(wrong.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
