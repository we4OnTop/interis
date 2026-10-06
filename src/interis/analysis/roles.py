"""Who is the interviewer?

1. **Voice profile** (preferred): cosine similarity between your enrolled voice embedding
   and each diarized speaker's embedding (pyannote centroids live in the same raw
   embedding space as a single-window embedding of the enrollment recording).
2. **Heuristic fallback**: the speaker with the highest share of question sentences.

The method and all scores are stored, and the result can always be corrected by hand.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from interis._bootstrap import require_offline
from interis.analysis.questions import QuestionCandidate
from interis.analysis.sentences import Sentence
from interis.security.pickle_scan import assert_safe_checkpoint

VOICE_THRESHOLD = 0.5  # minimum cosine similarity to accept a voice match
VOICE_MARGIN = 0.1  # best match must beat the runner-up by this much

INTERVIEWER, INTERVIEWEE = "Interviewer", "Befragte:r"


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def voice_embedding(audio: np.ndarray, pyannote_dir: Path) -> np.ndarray:
    """Embedding of a whole enrollment recording with community-1's embedding model."""
    require_offline()
    ckpt = pyannote_dir / "embedding" / "pytorch_model.bin"
    assert_safe_checkpoint(ckpt)
    import torch
    from pyannote.audio import Inference, Model

    model = Model.from_pretrained(pyannote_dir / "embedding")
    inference = Inference(model, window="whole")
    waveform = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
    return np.asarray(inference({"waveform": waveform, "sample_rate": 16000})).ravel()


def save_voice(path: Path, label: str, embedding: np.ndarray, model_revision: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "label": label,
        "embedding": [float(x) for x in embedding],
        "model_revision": model_revision,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }), encoding="utf-8")


def load_voice(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def assign_roles(speakers: list[dict[str, Any]], sentences: list[Sentence],
                 candidates: list[QuestionCandidate],
                 speaker_embeddings: dict[str, list[float]],
                 voice: dict[str, Any] | None) -> dict[str, Any]:
    """Set ``role`` and ``display_name`` on ``speakers`` (in place); return the evidence."""
    labels = [s["label"] for s in speakers]
    result: dict[str, Any] = {"method": "none", "interviewer": None, "scores": {}}
    if not labels:
        return result

    interviewer: str | None = None
    if voice and speaker_embeddings:
        ref = np.asarray(voice["embedding"])
        sims = {lab: round(_cos(ref, np.asarray(speaker_embeddings[lab])), 3)
                for lab in labels if lab in speaker_embeddings}
        result["scores"]["voice_similarity"] = sims
        ranked = sorted(sims.items(), key=lambda kv: kv[1], reverse=True)
        if ranked and ranked[0][1] >= VOICE_THRESHOLD and (
                len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= VOICE_MARGIN):
            interviewer, result["method"] = ranked[0][0], "voice"

    per_speaker = Counter(s.speaker for s in sentences)
    q_per_speaker = Counter(c.sentence.speaker for c in candidates)
    ratios = {lab: round(q_per_speaker[lab] / per_speaker[lab], 3) if per_speaker[lab] else 0.0
              for lab in labels}
    result["scores"]["question_ratio"] = ratios
    if interviewer is None and len(labels) >= 2:
        ranked_q = sorted(ratios.items(), key=lambda kv: kv[1], reverse=True)
        if ranked_q[0][1] > ranked_q[1][1]:
            interviewer, result["method"] = ranked_q[0][0], "heuristic"

    result["interviewer"] = interviewer
    others = [lab for lab in labels if lab != interviewer]
    for sp in speakers:
        if interviewer is None:
            sp["role"] = "unknown"
            continue
        if sp["label"] == interviewer:
            sp["role"], sp["display_name"] = "interviewer", INTERVIEWER
        else:
            sp["role"] = "interviewee"
            n = others.index(sp["label"]) + 1
            sp["display_name"] = INTERVIEWEE if len(others) == 1 else f"{INTERVIEWEE} {n}"
    return result
