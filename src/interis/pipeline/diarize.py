"""Speaker diarization with pyannote.audio 4 and the community-1 pipeline.

* Audio is passed in memory (``{"waveform", "sample_rate"}``), so pyannote never decodes
  files itself (no torchcodec/FFmpeg DLLs needed on Windows).
* The known number of speakers is passed in (interviewer + interviewee = 2), which
  noticeably reduces speaker confusion.
* Both the regular diarization (with overlaps) and the *exclusive* one (one speaker at a
  time, designed for matching with transcription timestamps) are kept.
* pyannote loads its checkpoints with ``torch.load(weights_only=False)``; every checkpoint
  is therefore re-scanned for dangerous pickle imports right before loading, in addition
  to the hash check in :func:`interis.models.verify_ready`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from interis._bootstrap import require_offline
from interis.pipeline.types import Diarization, SpeakerSpan
from interis.security.pickle_scan import assert_safe_checkpoint

SAMPLE_RATE = 16000
Progress = Callable[[str, float], None]


def _spans(annotation: Any) -> list[SpeakerSpan]:
    return [
        SpeakerSpan(round(float(seg.start), 3), round(float(seg.end), 3), str(label))
        for seg, _track, label in annotation.itertracks(yield_label=True)
    ]


def diarize(audio: np.ndarray, model_dir: Path, num_speakers: int | None = 2,
            progress: Progress | None = None,
            min_duration_off: float | None = None) -> Diarization:
    require_offline()
    for ckpt in sorted(model_dir.rglob("*.bin")):
        assert_safe_checkpoint(ckpt)

    import torch
    from pyannote.audio import Pipeline
    from pyannote.audio.telemetry import set_telemetry_metrics

    set_telemetry_metrics(False)
    pipeline = Pipeline.from_pretrained(model_dir)
    if pipeline is None:
        raise RuntimeError(f"pyannote could not load the pipeline from {model_dir}")
    pipeline.to(torch.device("cpu"))
    if min_duration_off is not None:  # pauses of one speaker shorter than this are bridged
        params = pipeline.parameters(instantiated=True)
        params["segmentation"]["min_duration_off"] = float(min_duration_off)
        pipeline.instantiate(params)

    def hook(step_name: str, _artifact: Any, file: Any = None, total: int | None = None,
             completed: int | None = None) -> None:
        if progress and total:
            progress(f"diarize:{step_name}", (completed or 0) / total)

    waveform = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
    kwargs = {"num_speakers": num_speakers} if num_speakers else {}
    output = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, hook=hook, **kwargs)

    labels = output.speaker_diarization.labels()
    embeddings: dict[str, list[float]] = {}
    if output.speaker_embeddings is not None:
        for label, vector in zip(labels, output.speaker_embeddings, strict=False):
            embeddings[str(label)] = [float(x) for x in vector]
    return Diarization(
        regular=_spans(output.speaker_diarization),
        exclusive=_spans(output.exclusive_speaker_diarization),
        embeddings=embeddings,
    )


FRAME_S = 0.05


def by_channel(left: np.ndarray, right: np.ndarray, min_gap_s: float = 0.3) -> Diarization:
    """Who speaks when, for a recording where each person has their own microphone on one
    stereo channel (lavalier or headset microphones): in every 50 ms the louder channel
    speaks. Each microphone also picks up the other person, but much more quietly, so the
    level difference decides. Pauses are where both channels are near their noise floor.

    Raises ValueError for a recording without two different channels (mono, or one
    microphone recorded in stereo)."""
    n = int(FRAME_S * SAMPLE_RATE)
    frames = min(len(left), len(right)) // n
    if frames < 2:
        return Diarization(regular=[], exclusive=[], embeddings={})
    lf = left[:frames * n].reshape(frames, n)
    rf = right[:frames * n].reshape(frames, n)
    if np.sqrt(np.mean((lf - rf) ** 2)) < 0.05 * np.sqrt(np.mean((lf + rf) ** 2)) + 1e-9:
        raise ValueError("the recording has no separate left and right channel")
    db_l = 10 * np.log10(np.mean(lf ** 2, axis=1) + 1e-10)
    db_r = 10 * np.log10(np.mean(rf ** 2, axis=1) + 1e-10)
    loud = np.maximum(db_l, db_r)
    active = loud > np.percentile(loud, 10) + 12  # 12 dB above the noise floor
    # median over 250 ms: one loud frame (a cough, a knock) does not change the speaker
    k = 5
    diff = np.pad(db_l - db_r, k // 2, mode="edge")
    diff = np.median(np.lib.stride_tricks.sliding_window_view(diff, k), axis=1)
    who = np.where(diff >= 0, "KANAL_L", "KANAL_R")

    spans: list[SpeakerSpan] = []
    for i in np.flatnonzero(active):
        start, end, speaker = i * FRAME_S, (i + 1) * FRAME_S, str(who[i])
        last = spans[-1] if spans else None
        if last and last.speaker == speaker and start - last.end <= min_gap_s:
            last.end = round(end, 3)
        else:
            spans.append(SpeakerSpan(round(start, 3), round(end, 3), speaker))
    # ponytail: no overlap detection (both talking): the louder one wins. Compare both
    # channels' levels against their own speech level if overlaps matter.
    return Diarization(regular=spans, exclusive=list(spans), embeddings={})
