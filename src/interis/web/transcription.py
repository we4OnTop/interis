"""Transcription settings for the website: saved presets ("Einstellungen"), the global
default used by every new transcription, and trial runs on a short excerpt to compare
settings before transcribing a whole interview.

A trial runs the normal pipeline on the excerpt and writes its result to
``<data>/trials/<job>.json`` only: the interview, its transcript and markings are never
touched.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from interis.config import Paths
from interis.models import ASR_MODELS
from interis.web.jobs import trial_file

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
MAX_TRIAL_S = 600


class TranscriptionSettings(BaseModel):
    model: str = Field(default="whisper-large-v3", max_length=60)
    compute_type: Literal["int8", "float32"] = "int8"
    beam_size: int = Field(default=5, ge=1, le=10)
    room_mic: bool = False
    vad_threshold: float | None = Field(default=None, ge=0.1, le=0.9)
    speakers: int = Field(default=2, ge=0, le=8)  # 0: detect the number
    min_duration_off: float | None = Field(default=None, ge=0.0, le=2.0)
    dereverb: bool = False  # WPE, see interis.pipeline.dereverb
    wpe_taps: int = Field(default=10, ge=3, le=40)
    wpe_delay: int = Field(default=3, ge=1, le=8)
    wpe_iterations: int = Field(default=3, ge=1, le=10)

    def checked(self) -> dict[str, Any]:
        if self.model not in ASR_MODELS:
            raise HTTPException(422, "unknown model")
        return self.model_dump()


BUILTIN = TranscriptionSettings().model_dump()


class PresetBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    settings: TranscriptionSettings


class DefaultBody(BaseModel):
    preset: int | None = None  # None: the built-in settings


class TrialBody(BaseModel):
    interview: str = Field(max_length=40)
    start: float = Field(default=0.0, ge=0.0, le=24 * 3600)
    duration: float = Field(default=180.0, ge=10.0, le=MAX_TRIAL_S)
    settings: TranscriptionSettings
    label: str = Field(default="", max_length=60)


def default_settings(store) -> dict[str, Any]:
    """The settings a new transcription uses, with the name of their preset."""
    preset = next((p for p in store.presets() if p["is_default"]), None)
    if preset is None:
        return {**BUILTIN, "preset": "Standard"}
    return {**BUILTIN, **preset["options"], "preset": preset["name"]}


def _seconds(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()


def _remove_trial(paths: Paths, store, job: dict[str, Any]) -> None:
    out = trial_file(paths, job["id"])
    if out.is_file():
        try:
            sha = json.loads(out.read_text(encoding="utf-8"))["meta"]["audio"]["sha256"]
        except (ValueError, KeyError, TypeError):
            sha = ""
        cache = paths.cache / sha[:16]
        # the cached steps hold the excerpt's text too; a crafted value never reaches rmtree
        if SHA256_HEX.match(sha) and cache.parent == paths.cache and cache.is_dir():
            shutil.rmtree(cache)
        out.unlink()
    store.delete_job(job["id"])


def trials_of(store, interview: str | None = None) -> list[dict[str, Any]]:
    return [j for j in store.jobs() if j["kind"] == "trial"
            and (interview is None or j["options"].get("interview") == interview)]


def remove_trials(paths: Paths, store, interview: str) -> None:
    """With an interview, its trial runs go as well."""
    for job in trials_of(store, interview):
        _remove_trial(paths, store, job)


def _words(result: dict[str, Any]) -> dict[str, Any]:
    """The part of a trial transcript the website shows."""
    roles = {s["label"]: s.get("role", "unknown") for s in result.get("speakers", [])}
    return {
        "clip": result["meta"]["audio"].get("clip"),
        "duration_s": result["meta"]["audio"]["duration_s"],
        "speakers": [{"label": label, "role": role} for label, role in roles.items()],
        "turns": [{"speaker": t["speaker"], "start": t["start"], "end": t["end"],
                   "words": [{"text": w["text"], "start": w["start"], "prob": w["prob"]}
                             for w in t["words"]]}
                  for t in result["turns"]],
    }


def add_transcription_routes(app: FastAPI, paths: Paths, store, runner,
                             interview_check) -> None:
    """``interview_check(id)`` raises 404 for an interview that is not in a project."""

    @app.get("/api/transcription/settings")
    def settings() -> dict[str, Any]:
        return {"builtin": BUILTIN, "presets": store.presets(), "models": list(ASR_MODELS),
                "default": default_settings(store)}

    @app.post("/api/transcription/presets")
    def create_preset(body: PresetBody) -> dict[str, int]:
        try:
            return {"id": store.save_preset(body.name.strip(), body.settings.checked())}
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, "Name schon vergeben") from e

    @app.put("/api/transcription/presets/{preset_id}")
    def update_preset(preset_id: int, body: PresetBody) -> dict[str, bool]:
        if all(p["id"] != preset_id for p in store.presets()):
            raise HTTPException(404, "unknown preset")
        try:
            store.save_preset(body.name.strip(), body.settings.checked(), preset_id)
        except sqlite3.IntegrityError as e:
            raise HTTPException(409, "Name schon vergeben") from e
        return {"ok": True}

    @app.delete("/api/transcription/presets/{preset_id}")
    def delete_preset(preset_id: int) -> dict[str, bool]:
        store.delete_preset(preset_id)  # if it was the default, the built-in one is again
        return {"ok": True}

    @app.put("/api/transcription/default")
    def set_default(body: DefaultBody) -> dict[str, bool]:
        if body.preset is not None and all(p["id"] != body.preset for p in store.presets()):
            raise HTTPException(404, "unknown preset")
        store.set_default_preset(body.preset)
        return {"ok": True}

    @app.post("/api/trials")
    def start_trial(body: TrialBody) -> dict[str, int]:
        interview_check(body.interview)
        if not store.part_paths(body.interview):
            raise HTTPException(422, "Noch keine Aufnahme hochgeladen")
        options = {**body.settings.checked(), "interview": body.interview,
                   "start": body.start, "duration": body.duration,
                   "label": body.label.strip()}
        job_id = store.add_job("trial", "", options)
        runner.notify()
        return {"job": job_id}

    @app.get("/api/trials")
    def list_trials(interview: str | None = None) -> list[dict[str, Any]]:
        return [{**j, "elapsed_s": _seconds(j["started_at"], j["finished_at"]),
                 "has_result": trial_file(paths, j["id"]).is_file()}
                for j in reversed(trials_of(store, interview))]

    @app.get("/api/trials/{job_id}")
    def trial_result(job_id: int) -> dict[str, Any]:
        job = store.job(job_id)
        out = trial_file(paths, job_id)
        if job is None or job["kind"] != "trial" or not out.is_file():
            raise HTTPException(404, "no result")
        return _words(json.loads(out.read_text(encoding="utf-8")))

    @app.delete("/api/trials/{job_id}")
    def delete_trial(job_id: int) -> dict[str, bool]:
        job = store.job(job_id)
        if job is None or job["kind"] != "trial":
            raise HTTPException(404, "unknown trial")
        if job["status"] in ("queued", "running"):
            raise HTTPException(409, "Erst den Probelauf abbrechen")
        _remove_trial(paths, store, job)
        return {"ok": True}

