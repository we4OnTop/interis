"""Waveform overview of a recording, for the timeline next to the transcript.

One byte per 50 ms: the loudest sample of that frame, square-rooted so that the quiet
speaker is visible next to the loud one, scaled to the 99.5th percentile of the whole
recording. Recordings in several parts are placed at the offsets of the joint timeline."""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
RATE = 20  # values per second
FRAME = SAMPLE_RATE // RATE


def frame_peaks(audio: np.ndarray) -> np.ndarray:
    """Loudest absolute sample per frame (float, not yet scaled)."""
    n = len(audio) // FRAME
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    return np.abs(audio[:n * FRAME].reshape(n, FRAME)).max(axis=1)


def joint(parts: list[tuple[float, np.ndarray]], duration_s: float) -> np.ndarray:
    """Scaled (0-255) values for the whole interview; ``parts``: (offset in seconds,
    frame peaks of that recording)."""
    total = int(duration_s * RATE) + 1
    raw = np.zeros(total, dtype=np.float32)
    for offset, p in parts:
        at = int(round(offset * RATE))
        raw[at:at + len(p)] = p[:max(0, total - at)]
    ref = float(np.percentile(raw[raw > 0], 99.5)) if (raw > 0).any() else 1.0
    return np.minimum(255, np.sqrt(np.minimum(raw / max(ref, 1e-9), 1.0)) * 255).astype(np.uint8)


def encode(values: np.ndarray) -> str:
    return base64.b64encode(values.tobytes()).decode("ascii")


def peaks_file(paths, sha256: str) -> Path:
    """Where the overview of the recording(s) with this (combined) hash is kept."""
    return paths.cache / "peaks" / f"{sha256[:16]}.json"
