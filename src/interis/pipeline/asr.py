"""Speech-to-text with faster-whisper (CTranslate2, CPU).

Settings favour a raw, precise transcript:
* language fixed to German (no auto-detection errors),
* beam search (beam_size=5, best_of=5) with Whisper's temperature fallback,
* ``condition_on_previous_text=False`` – avoids repetition loops/hallucination cascades,
* Silero VAD (bundled ONNX, no download) – skips silence, where Whisper hallucinates,
* word timestamps + per-word probability (used later to flag uncertain words).

``room_mic`` is for one microphone in the room, where the person further away is much
quieter: the loudness is evened out (:func:`level`) and the speech detector is more
sensitive, so quiet passages are not skipped. It cannot remove echo or noise; measure it
on a few minutes of your own recording (``bench/wer.py``) before relying on it.
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
    language: str = "de"  # interviews are German; other values only for benchmarks
    room_mic: bool = False
    vad_threshold: float | None = None  # speech detector; None: 0.35 with room_mic, else 0.5

    def as_params(self) -> dict:
        params = dict(self.__dict__, threads=None)  # thread count does not change results
        # options left at their default are not part of the key, so the cache keys of
        # earlier transcripts stay valid
        if not self.room_mic:
            del params["room_mic"]
        if self.vad_threshold is None:
            del params["vad_threshold"]
        return params

    @property
    def vad(self) -> float:
        if self.vad_threshold is not None:
            return self.vad_threshold
        return 0.35 if self.room_mic else 0.5


def level(audio: np.ndarray, window_s: float = 0.4, target_db: float = -20.0,
          max_gain_db: float = 18.0) -> np.ndarray:
    """Even out loudness over time: quiet passages are raised by up to ``max_gain_db``,
    loud ones lowered, with gain changes smoothed over about two seconds. Pauses are not
    raised more than the quietest speech, so background noise does not take over."""
    n = int(window_s * SAMPLE_RATE)
    frames = len(audio) // n
    if frames < 2:
        return audio
    rms = np.sqrt(np.mean(audio[:frames * n].reshape(frames, n) ** 2, axis=1)) + 1e-9
    rms = np.maximum(rms, 2 * np.percentile(rms, 10))  # noise floor: pauses
    gain_db = np.clip(target_db - 20 * np.log10(rms), -max_gain_db, max_gain_db)
    gain_db = np.convolve(gain_db, np.ones(5) / 5, mode="same")
    centers = (np.arange(frames) + 0.5) * n
    gain = 10 ** (np.interp(np.arange(len(audio)), centers, gain_db) / 20)
    return np.clip(audio * gain, -1.0, 1.0).astype(np.float32)


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
    if opts.room_mic:
        audio = level(audio)
    segments_iter, info = model.transcribe(
        audio,
        language=opts.language,
        task="transcribe",
        beam_size=opts.beam_size,
        best_of=opts.beam_size,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500,
                        "threshold": opts.vad},
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
