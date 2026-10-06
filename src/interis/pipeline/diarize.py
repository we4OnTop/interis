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
            progress: Progress | None = None) -> Diarization:
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
