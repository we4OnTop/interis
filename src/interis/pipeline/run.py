"""Runs the full pipeline: decode → transcribe → align → diarize → merge.

Each step result is cached (see :mod:`interis.pipeline.cache`). The transcript records
which models (repo + pinned revision), package versions and options produced it, so the
result is reproducible and can be documented in the thesis methods section.
"""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np

import interis
from interis._bootstrap import require_offline
from interis.analysis.analyze import AnalysisOptions, analyze
from interis.config import Paths
from interis.models import (
    ALIGN_MODEL,
    DIARIZATION_MODEL,
    EMBEDDING_MODEL,
    MODELS,
    sha256_file,
    verify_ready,
)
from interis.pipeline.asr import AsrOptions
from interis.pipeline.cache import StepCache, combined_sha, params_key
from interis.pipeline.merge import build_turns
from interis.pipeline.types import Diarization, Segment, Transcript, to_dict

SAMPLE_RATE = 16000
PART_GAP_S = 2.0  # silence inserted between recording parts
Progress = Callable[[str, float], None]
_PACKAGES = ("faster-whisper", "ctranslate2", "torch", "transformers", "pyannote.audio",
             "numpy", "av")


@dataclass
class PipelineOptions:
    asr_model: str = "whisper-large-v3"
    asr: AsrOptions = field(default_factory=AsrOptions)
    align: bool = True
    diarize: bool = True
    num_speakers: int | None = 2
    # bridge pauses of one speaker shorter than this (seconds); None: the model's setting
    min_duration_off: float | None = None
    # (start, length) in seconds: transcribe only this excerpt, e.g. to compare settings
    clip: tuple[float, float] | None = None
    # (taps, delay, iterations): reduce reverberation with WPE before all models
    dereverb: tuple[int, int, int] | None = None
    interview_id: str | None = None
    analysis: AnalysisOptions = field(default_factory=AnalysisOptions)


def decode(path: Path) -> np.ndarray:
    """Decode any audio/video file to 16 kHz mono float32 using PyAV (bundled FFmpeg)."""
    from faster_whisper.audio import decode_audio

    return decode_audio(str(path), sampling_rate=SAMPLE_RATE)


def run_pipeline(audio_paths: Path | list[Path], paths: Paths, opts: PipelineOptions,
                 progress: Progress | None = None) -> Transcript:
    """Transcribe one interview. Several recordings (e.g. before and after a break) are
    joined in the given order with a short silence and processed as one conversation,
    so speakers keep the same label across the break."""
    require_offline()
    say = progress or (lambda _stage, _frac: None)
    files = [audio_paths] if isinstance(audio_paths, Path) else list(audio_paths)

    say("hash", 0.0)
    part_shas = []
    for i, f in enumerate(files):
        part_shas.append(sha256_file(f))
        say("hash", (i + 1) / len(files))
    audio_sha = combined_sha(part_shas)
    cache = StepCache(paths.cache, audio_sha)

    say("decode", 0.0)
    chunks, parts, offset = [], [], 0.0
    gap = np.zeros(int(PART_GAP_S * SAMPLE_RATE), dtype=np.float32)
    for i, (f, sha) in enumerate(zip(files, part_shas, strict=True)):
        if i:
            chunks.append(gap)
            offset += PART_GAP_S
        x = decode(f)
        chunks.append(x)
        parts.append({"sha256": sha, "duration_s": round(len(x) / SAMPLE_RATE, 2),
                      "offset_s": round(offset, 3)})
        offset += len(x) / SAMPLE_RATE
        say("decode", (i + 1) / len(files))
    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    boundaries = [p["offset_s"] for p in parts[1:]]
    clip = None
    if opts.clip:
        start, length = opts.clip
        audio = audio[int(start * SAMPLE_RATE):int((start + length) * SAMPLE_RATE)]
        if len(audio) < SAMPLE_RATE:
            raise ValueError("the excerpt lies outside the recording")
        clip = {"start_s": start, "duration_s": round(len(audio) / SAMPLE_RATE, 2)}
        boundaries = [b - start for b in boundaries if start < b < start + length]
        audio_sha = hashlib.sha256(f"{audio_sha}:clip:{start}:{length}".encode()).hexdigest()
        cache = StepCache(paths.cache, audio_sha)
    duration = len(audio) / SAMPLE_RATE

    memo: dict[str, np.ndarray] = {}

    def heard() -> np.ndarray:
        """The audio the models get: reverberation reduced if asked, computed only when a
        step is not cached."""
        if not opts.dereverb:
            return audio
        if "x" not in memo:
            from interis.pipeline.dereverb import dereverb

            memo["x"] = dereverb(audio, *opts.dereverb, progress=say)
        return memo["x"]

    # options left at their default are not part of the keys: earlier caches stay valid
    extra = {"dereverb": list(opts.dereverb)} if opts.dereverb else {}

    # --- transcribe
    asr_dir = verify_ready(paths, opts.asr_model)
    asr_params = {"model": opts.asr_model, "revision": MODELS[opts.asr_model].revision,
                  "fw": version("faster-whisper"), **opts.asr.as_params(), **extra}
    asr_key = params_key(asr_params)
    cached = cache.load("asr", asr_key)
    if cached is None:
        from interis.pipeline.asr import transcribe

        segments = transcribe(heard(), asr_dir, opts.asr, say)
        cache.save("asr", asr_key, [to_dict(s) for s in segments])
    else:
        segments = [Segment.from_dict(s) for s in cached]
    say("transcribe", 1.0)

    # --- align
    if opts.align:
        align_key = params_key({"asr": asr_key, "revision": MODELS[ALIGN_MODEL].revision,
                                "v": 1})
        cached = cache.load("align", align_key)
        if cached is None:
            from interis.pipeline.align import align

            model_dir = verify_ready(paths, ALIGN_MODEL)
            segments = align(heard(), segments, model_dir, opts.asr.threads, say)
            cache.save("align", align_key, [to_dict(s) for s in segments])
        else:
            segments = [Segment.from_dict(s) for s in cached]
            say("align", 1.0)

    # --- diarize
    diarization: Diarization | None = None
    if opts.diarize:
        diar_params = {"revision": MODELS[DIARIZATION_MODEL].revision,
                       "num_speakers": opts.num_speakers, "pyannote": version("pyannote.audio"),
                       **extra}
        if opts.asr.room_mic:
            diar_params["room_mic"] = True
        if opts.min_duration_off is not None:
            diar_params["min_duration_off"] = opts.min_duration_off
        diar_key = params_key(diar_params)
        cached = cache.load("diarize", diar_key)
        if cached is None:
            from interis.pipeline.asr import level
            from interis.pipeline.diarize import diarize

            model_dir = verify_ready(paths, DIARIZATION_MODEL)
            diarization = diarize(level(heard()) if opts.asr.room_mic else heard(), model_dir,
                                  opts.num_speakers, say, opts.min_duration_off)
            cache.save("diarize", diar_key, to_dict(diarization))
        else:
            diarization = Diarization.from_dict(cached)
            say("diarize", 1.0)

    turns = build_turns(segments, diarization, boundaries)
    labels = sorted({t.speaker for t in turns if t.speaker is not None})
    speakers = [
        {"label": label, "role": "unknown", "display_name": label,
         "speaking_time_s": round(sum(t.end - t.start for t in turns if t.speaker == label), 1)}
        for label in labels
    ]

    used = [opts.asr_model] + ([ALIGN_MODEL] if opts.align else []) + (
        [DIARIZATION_MODEL] if opts.diarize else [])
    meta = {
        "interview_id": opts.interview_id or f"I-{audio_sha[:8]}",
        "kind": "machine",
        "note": "Raw machine transcript – not reviewed.",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "interis_version": interis.__version__,
        "audio": {"sha256": audio_sha, "duration_s": round(duration, 2), "parts": parts,
                  **({"clip": clip} if clip else {})},
        "language": "de",
        "models": {k: {"repo": MODELS[k].repo, "revision": MODELS[k].revision,
                       "license": MODELS[k].license} for k in used},
        "options": {
            "asr_model": opts.asr_model, **opts.asr.as_params(),
            "align": opts.align, "diarize": opts.diarize, "num_speakers": opts.num_speakers,
            "min_duration_off": opts.min_duration_off, "vad_threshold": opts.asr.vad,
            "dereverb": list(opts.dereverb) if opts.dereverb else None,
            "condition_on_previous_text": False, "vad_filter": True, "language": "de",
        },
        "packages": {p: version(p) for p in _PACKAGES},
        "platform": f"{platform.system()} {platform.release()} / Python "
                    f"{platform.python_version()}",
    }
    transcript = Transcript(meta=meta, speakers=speakers, turns=turns)
    say("analyze", 0.0)
    run_analysis(transcript, paths, opts.analysis,
                 diarization.embeddings if diarization else None, opts.asr.threads)
    say("analyze", 1.0)
    return transcript


def run_analysis(transcript: Transcript, paths: Paths, aopts: AnalysisOptions,
                 speaker_embeddings: dict[str, list[float]] | None = None,
                 threads: int | None = None) -> None:
    """Run Phase 2 analysis and store it in ``transcript.analysis`` (in place).

    Speaker embeddings are biometric data: they are used here but never written into
    the transcript or any export."""
    require_offline()

    def encoder_factory():
        from interis.analysis.embed import Encoder

        return Encoder(verify_ready(paths, EMBEDDING_MODEL), threads)

    transcript.analysis = analyze(transcript, aopts, speaker_embeddings, encoder_factory)
    if aopts.guide is not None:
        transcript.meta["models"][EMBEDDING_MODEL] = {
            "repo": MODELS[EMBEDDING_MODEL].repo,
            "revision": MODELS[EMBEDDING_MODEL].revision,
            "license": MODELS[EMBEDDING_MODEL].license,
        }
