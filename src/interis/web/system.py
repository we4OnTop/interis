"""System page and first-start setup: where the data and the models are, model status,
model download (as a background job) and choosing folders.

The setup app runs before a data folder exists; it only offers these routes."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from interis.config import HOME_ENV, Paths, save_settings, settings_file
from interis.models import MODELS, quick_status
from interis.web.base import secure_app

MODEL_INFO = {
    "whisper-large-v3": ("Spracherkennung – genau", "3,1 GB"),
    "whisper-large-v3-turbo": ("Spracherkennung – schnell", "1,6 GB"),
    "pyannote-community-1": ("Sprechertrennung", "0,03 GB"),
    "wav2vec2-german": ("Wort-Zeitstempel (Deutsch)", "1,3 GB"),
    "e5-large": ("Fragen-Zuordnung", "2,2 GB"),
}


class FolderCheck(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


class Folders(BaseModel):
    data_dir: str = Field(min_length=1, max_length=1000)
    models_dir: str | None = Field(default=None, max_length=1000)
    create: bool = False


def _risky(p: Path) -> str | None:
    """Warn about folders that Windows may sync to the cloud."""
    text = str(p).lower()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        od = os.environ.get(var)
        if od and text.startswith(od.lower()):
            return "Der Ordner liegt in OneDrive und würde in die Cloud synchronisiert."
    home = Path.home()
    for sub in ("Desktop", "Documents", "Dokumente"):
        if text.startswith(str(home / sub).lower()):
            return (f"Der Ordner liegt unter {sub}; Windows sichert diesen Ordner oft in "
                    "OneDrive. Besser: verschlüsseltes VeraCrypt-Laufwerk.")
    return None


def models_status(models_dir: Path) -> list[dict[str, Any]]:
    paths = Paths(models_dir.parent, models_dir)
    return [{"key": key, "label": MODEL_INFO.get(key, (key, ""))[0],
             "size": MODEL_INFO.get(key, ("", "?"))[1], "repo": spec.repo,
             "license": spec.license, "status": quick_status(paths, key)}
            for key, spec in MODELS.items()]


def check_folder(raw: str, purpose: str) -> dict[str, Any]:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise HTTPException(422, "Bitte einen vollständigen Pfad angeben, z. B. X:\\interis-data")
    exists = p.is_dir()
    out: dict[str, Any] = {"path": str(p.resolve()) if exists else str(p), "exists": exists,
                           "warning": _risky(p) if purpose == "data" else None}
    if purpose == "models" and exists:
        status = models_status(p)
        ready = sum(m["status"] == "ready" for m in status)
        inner = p / "models"  # the user picked a data folder that contains the models
        if not ready and inner.is_dir():
            inner_status = models_status(inner)
            if any(m["status"] == "ready" for m in inner_status):
                p, status = inner, inner_status
                ready = sum(m["status"] == "ready" for m in status)
                out["path"] = str(p.resolve())
        out["models"] = status
        out["ready"] = ready
    if purpose == "data" and exists:
        out["has_interis"] = (p / "interis.db").is_file()
    return out


def _apply_folders(body: Folders) -> Path:
    data = Path(body.data_dir).expanduser()
    if not data.is_absolute():
        raise HTTPException(422, "Datenordner: bitte vollständigen Pfad angeben")
    if not data.is_dir():
        if not body.create:
            raise HTTPException(409, "Datenordner existiert nicht")
        data.mkdir(parents=True)
    models = Path(body.models_dir).expanduser() if body.models_dir else None
    if models is not None:
        if not models.is_absolute():
            raise HTTPException(422, "Modell-Ordner: bitte vollständigen Pfad angeben")
        models.mkdir(parents=True, exist_ok=True)
    return save_settings(data, models)


def _later(fn: Callable[[], None]) -> None:
    """Run after the HTTP response went out."""
    threading.Timer(0.5, fn).start()


def app_info(paths: Paths | None, on_restart: Callable[[], None] | None) -> dict[str, Any]:
    return {
        "mode": "main" if paths else "setup",
        "portable": bool(os.environ.get(HOME_ENV)),
        "desktop": on_restart is not None,
        "settings_file": str(settings_file()),
        "data_dir": str(paths.root) if paths else None,
        "models_dir": str(paths.models) if paths else None,
        "models_linked": bool(paths and paths.models_dir),
    }


def add_system_routes(app: FastAPI, paths: Paths, store, runner,
                      on_restart: Callable[[], None] | None) -> None:
    @app.get("/api/app")
    def info() -> dict[str, Any]:
        jobs = [j for j in store.jobs() if j["kind"] == "models"]
        return {**app_info(paths, on_restart), "models": models_status(paths.models),
                "models_job": jobs[-1] if jobs else None}

    @app.post("/api/app/check-folder/{purpose}")
    def check(purpose: str, body: FolderCheck) -> dict[str, Any]:
        if purpose not in ("data", "models"):
            raise HTTPException(404, "unknown purpose")
        return check_folder(body.path, purpose)

    @app.post("/api/app/models/download")
    def download() -> dict[str, int]:
        if any(j["kind"] == "models" and j["status"] in ("queued", "running")
               for j in store.jobs()):
            raise HTTPException(409, "Download läuft bereits")
        job_id = store.add_job("models", "")
        runner.notify()
        return {"job": job_id}

    @app.post("/api/app/folders")
    def folders(body: Folders) -> dict[str, Any]:
        if any(j["status"] == "running" for j in store.jobs()):
            raise HTTPException(409, "Erst laufende Aufträge abwarten oder abbrechen")
        f = _apply_folders(body)
        if on_restart:
            _later(on_restart)
        return {"saved": str(f), "restart": on_restart is not None}


def create_setup_app(login_token: str, port: int,
                     on_restart: Callable[[], None] | None) -> FastAPI:
    """First start: no data folder yet. Only folder selection is possible."""
    app = secure_app(login_token, port)

    @app.get("/api/app")
    def info() -> dict[str, Any]:
        return {**app_info(None, on_restart), "models": None, "models_job": None,
                "suggested_models_dir": str(Path(os.environ[HOME_ENV]) / "models")
                if os.environ.get(HOME_ENV) else None}

    @app.post("/api/app/check-folder/{purpose}")
    def check(purpose: str, body: FolderCheck) -> dict[str, Any]:
        if purpose not in ("data", "models"):
            raise HTTPException(404, "unknown purpose")
        return check_folder(body.path, purpose)

    @app.post("/api/app/folders")
    def folders(body: Folders) -> dict[str, Any]:
        f = _apply_folders(body)
        if on_restart:
            _later(on_restart)
        return {"saved": str(f), "restart": on_restart is not None}

    return app
