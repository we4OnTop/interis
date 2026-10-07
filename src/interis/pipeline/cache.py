"""Step cache: every pipeline step stores its result as JSON under
``<data>/cache/<audio-sha256-prefix>/<step>-<params-hash>.json``. A step whose inputs and
parameters are unchanged is skipped, so an interrupted run resumes where it stopped."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def params_key(params: dict[str, Any]) -> str:
    blob = json.dumps(params, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def combined_sha(part_shas: list[str]) -> str:
    """One recording keeps its own hash (so existing caches stay valid); several parts
    get a hash over the ordered part hashes."""
    if len(part_shas) == 1:
        return part_shas[0]
    return hashlib.sha256(("parts:" + ",".join(part_shas)).encode()).hexdigest()


class StepCache:
    def __init__(self, root: Path, audio_sha256: str) -> None:
        self.dir = root / audio_sha256[:16]

    def _path(self, step: str, key: str) -> Path:
        return self.dir / f"{step}-{key}.json"

    def load(self, step: str, key: str) -> Any | None:
        p = self._path(step, key)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, step: str, key: str, data: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self._path(step, key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
