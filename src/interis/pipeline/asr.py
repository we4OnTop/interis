"""Speech-to-text with faster-whisper (CTranslate2, CPU).

Settings favour a raw, precise transcript:
* language fixed to German (no auto-detection errors),
* beam search (beam_size=5, best_of=5) with Whisper's temperature fallback,
* ``condition_on_previous_text=False`` – avoids repetition loops/hallucination cascades,
* Silero VAD (bundled ONNX, no download) – skips silence, where Whisper hallucinates,
* word timestamps + per-word probability (used later to flag uncertain words).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from interis._bootstrap import require_offline
from interis.pipeline.types import Segment, Word

SAMPLE_RATE = 16000
Progress = Callable[[str, float], None]


@dataclass
class AsrOptions:
    compute_type: str = "int8"  # "int8" (fast) or "float32" (max precision)
    beam_size: int = 5
    hotwords: str | None = None  # glossary: names, technical terms
    initial_prompt: str | None = None
    threads: int | None = None

    def as_params(self) -> dict:
        return dict(self.__dict__, threads=None)  # thread count does not change results


def transcribe(audio: np.ndarray, model_dir: Path, opts: AsrOptions,
               progress: Progress | None = None) -> list[Segment]:
    require_offline()
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(model_dir),
        device="cpu",
        compute_type=opts.compute_type,
        cpu_threads=opts.threads or (os.cpu_count() or 4),
        local_files_only=True,
    )
    segments_iter, info = model.transcribe(
        audio,
        language="de",
        task="transcribe",
        beam_size=opts.beam_size,
        best_of=opts.beam_size,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        word_timestamps=True,
        hotwords=opts.hotwords or None,
        initial_prompt=opts.initial_prompt or None,
    )
    duration = max(float(info.duration), 1e-6)
    out: list[Segment] = []
    for seg in segments_iter:
        words = [
            Word(text=w.word, start=float(w.start), end=float(w.end),
                 prob=float(w.probability), asr_start=float(w.start), asr_end=float(w.end))
            for w in (seg.words or [])
        ]
        out.append(Segment(
            id=len(out), start=float(seg.start), end=float(seg.end), text=seg.text,
            words=words, avg_logprob=float(seg.avg_logprob),
            no_speech_prob=float(seg.no_speech_prob),
            compression_ratio=float(seg.compression_ratio),
            temperature=float(seg.temperature or 0.0),
        ))
        if progress:
            progress("transcribe", min(seg.end / duration, 1.0))
    return out
