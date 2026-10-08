"""Reverberation reduction with WPE (weighted prediction error), single channel.

Late reverberation is predicted from the signal's own past (``delay`` frames back, over
``taps`` frames) and subtracted, separately in every frequency band; the prediction filter
is re-estimated ``iterations`` times, weighting frames by the estimated speech power. This
is classic signal processing without a trained model (Nakatani et al. 2010, Yoshioka &
Nakatani 2012), so nothing is learned from other recordings and no model file is needed.

With one microphone it removes less than with several, and whether it helps Whisper on a
given recording has to be measured (trial run, ``bench/wer.py``).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

SAMPLE_RATE = 16000
FFT = 512  # 32 ms
HOP = 128  # 8 ms
BLOCK_S = 30.0  # the filter is estimated per block (memory, slowly changing rooms)
CONTEXT_S = 1.0  # extra signal on both sides of a block, so its edges are processed fully

_WINDOW = np.hanning(FFT + 1)[:FFT].astype(np.float32)  # periodic Hann


def stft(x: np.ndarray) -> np.ndarray:
    """(frames, FFT // 2 + 1) complex spectrum; the signal is padded by one frame each side."""
    padded = np.pad(x, (FFT, FFT + (-len(x)) % HOP))
    frames = np.lib.stride_tricks.sliding_window_view(padded, FFT)[::HOP] * _WINDOW
    return np.fft.rfft(frames, axis=1).astype(np.complex64)


def istft(spec: np.ndarray, length: int) -> np.ndarray:
    frames = np.fft.irfft(spec, n=FFT, axis=1).astype(np.float32) * _WINDOW
    n, k = len(frames), FFT // HOP
    out = np.zeros((n + k - 1, HOP), np.float32)
    norm = np.zeros((n + k - 1, HOP), np.float32)
    for i in range(k):  # overlap-add, one quarter of each frame at a time
        out[i:i + n] += frames[:, i * HOP:(i + 1) * HOP]
        norm[i:i + n] += (_WINDOW[i * HOP:(i + 1) * HOP] ** 2)
    out = out.ravel() / np.maximum(norm.ravel(), 1e-8)
    return out[FFT:FFT + length]


def wpe(spec: np.ndarray, taps: int, delay: int, iterations: int) -> np.ndarray:
    """Dereverberated spectrum; ``spec``: (frames, bins)."""
    y = spec.T  # (bins, frames)
    bins, frames = y.shape
    if frames <= delay + taps:
        return spec
    past = np.zeros((bins, frames, taps), np.complex64)  # past[f, t, k] = y[f, t - delay - k]
    for k in range(taps):
        past[:, delay + k:, k] = y[:, :frames - delay - k]
    x = y
    eye = np.eye(taps)
    for _ in range(iterations):
        power = np.abs(x) ** 2
        power = np.maximum(power, 1e-6 * power.mean() + 1e-12)
        weighted = np.conj(past / power[..., None]).transpose(0, 2, 1)  # (bins, taps, frames)
        cov = (weighted @ past).astype(np.complex128)
        cross = (weighted @ y[..., None]).astype(np.complex128)
        reg = 1e-6 * np.trace(cov, axis1=1, axis2=2).real[:, None, None] / taps + 1e-12
        filt = np.linalg.solve(cov + reg * eye, cross).astype(np.complex64)
        x = y - (past @ filt)[..., 0]
    return x.T


def dereverb(audio: np.ndarray, taps: int = 10, delay: int = 3, iterations: int = 3,
             progress: Callable[[str, float], None] | None = None) -> np.ndarray:
    block, context = int(BLOCK_S * SAMPLE_RATE), int(CONTEXT_S * SAMPLE_RATE)
    out = np.empty_like(audio, dtype=np.float32)
    starts = range(0, len(audio), block)
    # ponytail: blocks are joined without a crossfade; their filters differ slightly, which
    # can leave a faint click every 30 s. Crossfade the contexts if that ever matters.
    for i, s in enumerate(starts):
        a, b = max(0, s - context), min(len(audio), s + block + context)
        y = audio[a:b]
        clean = istft(wpe(stft(y), taps, delay, iterations), len(y))
        n = min(block, len(audio) - s)
        out[s:s + n] = clean[s - a:s - a + n]
        if progress:
            progress("dereverb", (i + 1) / len(starts))
    return np.clip(out, -1.0, 1.0)
