"""Automatic tuning of the transcription settings against what you corrected.

The ground truth is the transcript as you corrected it in the website (word corrections and
speaker corrections applied). For a stretch of an interview (``Window``) the tuner
transcribes the same stretch with candidate settings and measures how far the result is from
your text: wrong words (WER) and wrongly attributed words (speaker error), see
:mod:`interis.pipeline.evaluate`.

Why not gradient descent: beam size, compute type, the room-microphone switch, "glossary on/off"
or a voice threshold are discrete and not differentiable, and every evaluation is a whole
transcription. A **coordinate descent** fits: starting from the current settings, each
setting is varied on its own, the best value is kept, and this repeats until a full round
brings no gain (or the time / evaluation budget is used up). The pipeline's step cache means a
change that only affects a later step (speaker handling, voice) does not repeat the slow
Whisper run, so those settings are tried first.

Overfitting guard: with two or more windows the settings are chosen on the *training*
windows and only accepted if they are also better on the held-out ones. With a single
window the result is flagged as not held out. The glossary (words you had to correct) is
learned from the training windows only.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from interis.pipeline.asr import AsrOptions
from interis.pipeline.evaluate import (
    RefTokens,
    Scores,
    glossary,
    hyp_tokens,
    pool,
    score,
)
from interis.pipeline.run import PipelineOptions
from interis.pipeline.types import Transcript

MIN_GAIN = 0.002  # smaller differences are noise (a few words), not an improvement
MIN_WINDOW_S = 60.0
MAX_WINDOW_S = 900.0
SUGGEST_S = 600.0
MAX_HOTWORDS_CHARS = 800

# Searched settings (keys of the website's transcription settings plus "glossary"), cheap
# steps first: speaker handling and voice reuse the cached recognition, the rest repeats it.
SPACE: dict[str, list[Any]] = {
    "sentence_level": [False, True],
    "min_duration_off": [None, 0.3, 0.6, 1.0],
    "voice_margin": [None, 0.05, 0.1, 0.2, 0.3],  # only with a voice profile
    "glossary": [False, True],
    "vad_threshold": [None, 0.35, 0.5, 0.65],
    "beam_size": [1, 3, 5, 8],
    "room_mic": [False, True],
    "dereverb": [False, True],
    "compute_type": ["int8", "float32"],  # slowest, therefore last
}
NO_PROFILE = ("voice_margin",)
DEFAULTS: dict[str, Any] = {"sentence_level": False, "min_duration_off": None,
                            "voice_margin": None, "glossary": False, "vad_threshold": None,
                            "beam_size": 5, "room_mic": False, "dereverb": False,
                            "compute_type": "int8"}


class TuneError(ValueError):
    pass


@dataclass
class Window:
    """A stretch of one interview that you corrected."""

    interview: str
    audio: list[Path]
    start: float
    end: float
    ref: RefTokens

    @property
    def name(self) -> str:
        return f"{self.interview} {int(self.start // 60)}:{int(self.start % 60):02d}"


@dataclass
class Span:
    """A stretch of whole speaker turns of the corrected transcript."""

    start: float
    end: float
    first: int  # first and last turn (index in ``Transcript.turns``)
    last: int


def snap_to_turns(t: Transcript, start: float, end: float, min_len: float = MIN_WINDOW_S,
                  max_len: float = MAX_WINDOW_S) -> Span:
    """Move the edges of ``start``..``end`` to the edges of the speaker turns they fall in,
    so the recording is never cut in the middle of what somebody says: the start moves back
    to the beginning of the turn, the end forward to the end of its turn. A stretch that gets
    too long loses turns at its end, one that is too short gains turns."""
    turns = [(i, x) for i, x in enumerate(t.turns) if x.words]
    first = next((n for n, (_, x) in enumerate(turns) if x.end > start), None)
    if first is None:
        raise TuneError("the stretch lies behind the end of the transcript")
    last = max((n for n, (_, x) in enumerate(turns) if x.start < end), default=first)
    last = max(last, first)
    while last > first and turns[last][1].end - turns[first][1].start > max_len:
        last -= 1
    while last < len(turns) - 1 and turns[last][1].end - turns[first][1].start < min_len:
        last += 1
    a, b = turns[first][1].start, turns[last][1].end
    if b - a < min_len:
        raise TuneError(f"the stretch is shorter than {min_len:.0f} s")
    if b - a > max_len:
        raise TuneError(f"one speaker turn is longer than {max_len / 60:.0f} minutes")
    return Span(a, b, turns[first][0], turns[last][0])


def suggest_span(t: Transcript, corrected_turns: list[int], reviewed: bool,
                 max_len: float = SUGGEST_S) -> Span | None:
    """Where the corrected text is: from the first to the last turn with a correction (at
    most ``max_len`` seconds), or, if the whole transcript was checked, its start."""
    if corrected_turns:
        a = t.turns[min(corrected_turns)].start
        b = t.turns[min(max(corrected_turns), len(t.turns) - 1)].end
    elif reviewed and t.turns:
        a = t.turns[0].start
        b = a + max_len
    else:
        return None
    return snap_to_turns(t, a, min(b, a + max_len))


Runner = Callable[[dict[str, Any], Window, str | None], Transcript]
Progress = Callable[[str, float], None]


def merge_hotwords(project: str | None, terms: list[str]) -> str | None:
    """The project's glossary first, then the terms learned from your corrections."""
    parts = [t.strip() for t in (project or "").split(",") if t.strip()]
    known = {p.casefold() for p in parts}
    parts += [t for t in terms if t.casefold() not in known]
    text = ", ".join(parts)
    if len(text) > MAX_HOTWORDS_CHARS:  # cut at a term boundary
        text = text[:MAX_HOTWORDS_CHARS].rsplit(",", 1)[0]
    return text or None


def pipeline_options(settings: dict[str, Any], *, hotwords: str | None = None,
                     clip: tuple[float, float] | None = None,
                     analysis: Any = None, threads: int | None = None) -> PipelineOptions:
    """The pipeline options for the website's transcription settings."""
    opts = PipelineOptions(
        asr_model=settings.get("model", "whisper-large-v3"),
        asr=AsrOptions(compute_type=settings.get("compute_type", "int8"),
                       beam_size=settings.get("beam_size", 5), hotwords=hotwords,
                       threads=threads, room_mic=bool(settings.get("room_mic")),
                       vad_threshold=settings.get("vad_threshold")),
        num_speakers=settings.get("speakers", 2) or None,
        min_duration_off=settings.get("min_duration_off"),
        dereverb=(settings.get("wpe_taps", 10), settings.get("wpe_delay", 3),
                  settings.get("wpe_iterations", 3)) if settings.get("dereverb") else None,
        clip=clip, sentence_level=bool(settings.get("sentence_level")),
        voice_margin=settings.get("voice_margin"), interview_id="PROBE")
    return replace(opts, analysis=analysis) if analysis is not None else opts


def make_runner(paths: Any, analysis: Any, threads: int | None = None,
                progress: Progress | None = None) -> Runner:
    from interis.pipeline.run import run_pipeline

    def run(settings: dict[str, Any], w: Window, hotwords: str | None) -> Transcript:
        opts = pipeline_options(settings, hotwords=hotwords,
                                clip=(w.start, w.end - w.start), analysis=analysis,
                                threads=threads)
        return run_pipeline(w.audio, paths, opts, progress)

    return run


# ------------------------------------------------------------------ search

def split_windows(windows: list[Window]) -> tuple[list[Window], list[Window]]:
    """(train, validation). Every third window is held out; one window is both."""
    windows = sorted(windows, key=lambda w: (w.interview, w.start))
    if len(windows) < 2:
        return windows, windows
    val = windows[2::3] or windows[-1:]
    return [w for w in windows if w not in val], val


def coordinate_descent(loss: Callable[[dict[str, Any]], float], space: dict[str, list[Any]],
                       start: dict[str, Any], max_evals: int, deadline: float | None,
                       ) -> tuple[dict[str, Any], str]:
    """Minimise ``loss`` over the discrete ``space``. Returns (best, why it stopped)."""
    best = dict(start)
    best_loss = loss(best)
    evals = 1
    improved = True
    while improved:
        improved = False
        for key, values in space.items():
            for value in values:
                if value == best.get(key):
                    continue
                if evals >= max_evals:
                    return best, "evaluation budget used up"
                if deadline is not None and time.monotonic() >= deadline:
                    return best, "time budget used up"
                trial = {**best, key: value}
                trial_loss = loss(trial)
                evals += 1
                if trial_loss < best_loss - MIN_GAIN:
                    best, best_loss, improved = trial, trial_loss, True
    return best, "converged"


def tune(windows: list[Window], run: Runner, start: dict[str, Any], *,
         has_profile: bool = False, project_hotwords: str | None = None,
         max_evals: int = 40, budget_s: float | None = None,
         progress: Progress | None = None) -> dict[str, Any]:
    """``start``: the settings to improve (the website's current default)."""
    if not windows:
        raise TuneError("no corrected stretch given")
    space = {k: v for k, v in SPACE.items() if has_profile or k not in NO_PROFILE}
    base = {k: start.get(k, default) for k, default in DEFAULTS.items()}
    base["glossary"] = False  # learned below, from the training windows only
    if not has_profile:
        base["voice_margin"] = None
    train, val = split_windows(windows)
    held_out = train != val
    say = progress or (lambda _s, _f: None)
    deadline = time.monotonic() + budget_s if budget_s else None
    full = {**start}  # settings the search does not touch (model, speakers, WPE values)

    def scores(params: dict[str, Any], subset: list[Window], terms: list[str]) -> Scores:
        hot = merge_hotwords(project_hotwords, terms if params.get("glossary") else [])
        settings = {**full, **{k: v for k, v in params.items() if k != "glossary"}}
        return pool([score(w.ref, hyp_tokens(run(settings, w, hot))) for w in subset])

    counts: dict[str, int] = {}
    for w in train:  # the words you had to correct on the training stretches
        hyp = hyp_tokens(run({**full, **{k: v for k, v in base.items() if k != "glossary"}},
                             w, merge_hotwords(project_hotwords, [])))
        for t in glossary(w.ref, hyp):
            counts[t] = counts.get(t, 0) + 1
    terms = [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:40]
    if not terms:
        space.pop("glossary")

    trials: list[dict[str, Any]] = []
    memo: dict[str, float] = {}

    def loss(params: dict[str, Any]) -> float:
        key = json.dumps(params, sort_keys=True)
        if key not in memo:
            say("tune", min(len(memo) / max_evals, 0.99))
            s = scores(params, train, terms)
            memo[key] = s.loss
            trials.append({"params": dict(params), "train": s.as_dict()})
        return memo[key]

    best, stopped = coordinate_descent(loss, space, base, max_evals, deadline)
    note = None
    base_val = scores(base, val, terms)
    best_val = base_val if best == base else scores(best, val, terms)
    if best != base and held_out and best_val.loss >= base_val.loss - MIN_GAIN:
        best, best_val = dict(base), base_val
        note = ("better on the stretches used for the search but not on the held-out one: "
                "the current settings were kept")
    base_train, best_train = scores(base, train, terms), scores(best, train, terms)
    say("tune", 1.0)
    changed = {k: v for k, v in best.items() if base.get(k) != v}
    return {
        "settings": {**full, **{k: v for k, v in best.items() if k != "glossary"}},
        "glossary": terms if best.get("glossary") else [],
        "changed": changed,
        "improved": bool(changed) and best_val.loss < base_val.loss - MIN_GAIN,
        "held_out": held_out,
        "windows": [w.name for w in windows],
        "baseline": {"train": base_train.as_dict(), "validation": base_val.as_dict()},
        "best": {"train": best_train.as_dict(), "validation": best_val.as_dict()},
        "evaluations": len(trials),
        "stopped": stopped,
        "note": note,
        "trials": trials,
    }
