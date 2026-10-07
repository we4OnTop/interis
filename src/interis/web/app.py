"""Local review website (FastAPI). Reachable only from this computer.

Security (see ARCHITECTURE.md §6):
* bound to 127.0.0.1 by the launcher; Host header allow-list against DNS rebinding;
* per-start login token (in the URL *fragment*, never sent in requests or logged),
  exchanged for an HttpOnly, SameSite=Strict session cookie required by every API call;
* state-changing requests need a same-origin ``Origin`` and a custom header, which a
  foreign website cannot send without a CORS preflight (and there is no CORS);
* strict Content-Security-Policy, no third-party resources, no API docs endpoints;
* interview text is rendered with ``textContent`` only in the frontend;
* uploads: size limit, extension allow-list, stored under the interview ID only (the
  original file name never reaches the server).
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from interis.analysis.guide import (
    Guide,
    GuideError,
    GuideQuestion,
    docx_to_guide_text,
    load_guide,
    parse_guide,
)
from interis.config import Paths
from interis.models import ASR_MODELS, sha256_file
from interis.pipeline.types import Transcript
from interis.web.jobs import JobRunner, guide_path_for
from interis.web.review import guide_mismatch, interview_state, interviewer_of
from interis.web.store import Store

STATIC = Path(__file__).parent / "static"
SESSION_COOKIE = "interis_session"
CSRF_HEADER = "x-interis"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'none'")
INTERVIEW_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
AUDIO_EXT = {"m4a", "mp3", "wav", "aac", "flac", "ogg", "opus", "wma", "webm", "mp4", "mov",
             "mkv", "avi", "3gp", "amr"}
MAX_AUDIO_BYTES = 8 * 1024**3
MAX_DOCX_BYTES = 20 * 1024**2
MAX_GUIDE_CHARS = 200_000
LEGACY_PROJECT = "Bestehende Interviews"


class Login(BaseModel):
    token: str = Field(max_length=200)


class Span(BaseModel):
    interview: str = Field(max_length=100)
    turn: int = Field(ge=0)
    first: int = Field(ge=0)
    last: int = Field(ge=0)


class QuestionUpdate(Span):
    guide_code: str | None = Field(default=None, max_length=40)
    match: Literal["main", "probe", "followup"] = "main"
    status: Literal["confirmed", "rejected"] = "confirmed"


class QuestionDelete(BaseModel):
    interview: str = Field(max_length=100)
    turn: int = Field(ge=0)
    first: int = Field(ge=0)


class LinkCreate(Span):
    guide_code: str = Field(max_length=40)
    status: Literal["confirmed", "rejected"] = "confirmed"
    source: Literal["manual", "suggestion"] = "manual"
    omitted: bool = False
    note: str = Field(default="", max_length=2000)


class LinkUpdate(BaseModel):
    omitted: bool | None = None
    note: str | None = Field(default=None, max_length=2000)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    hotwords: str = Field(default="", max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    hotwords: str | None = Field(default=None, max_length=2000)


class GuideText(BaseModel):
    text: str = Field(max_length=MAX_GUIDE_CHARS)


def _guide_from_dict(d: dict[str, Any]) -> Guide:
    return Guide(d.get("title"), [GuideQuestion(**q) for q in d["questions"]])


class _Data:
    """Transcripts and guides are re-read only when their file changes."""

    def __init__(self, paths: Paths, store: Store, legacy_guide: Path | None) -> None:
        self.paths = paths
        self.store = store
        self.legacy_guide = legacy_guide
        self._cache: dict[Path, tuple[float, Transcript]] = {}
        self._guides: dict[Path, tuple[float, Guide | None, str | None]] = {}

    def transcripts(self, ids: list[str] | None = None) -> dict[str, Transcript]:
        out = {}
        for path in sorted(self.paths.exports.glob("*/*.json")):
            if path.stem != path.parent.name or (ids is not None and path.stem not in ids):
                continue
            mtime = path.stat().st_mtime
            cached = self._cache.get(path)
            if cached is None or cached[0] != mtime:
                t = Transcript.from_dict(json.loads(path.read_text(encoding="utf-8")))
                cached = self._cache[path] = (mtime, t)
            out[cached[1].meta["interview_id"]] = cached[1]
        return out

    def guide_file(self, project_id: int) -> Path:
        return guide_path_for(self.paths, project_id)

    def guide(self, project_id: int | None) -> tuple[Guide | None, str | None]:
        """(guide, error message) of a project."""
        if project_id is None:
            return None, None
        path = self.guide_file(project_id)
        if not path.is_file():
            return None, None
        mtime = path.stat().st_mtime
        cached = self._guides.get(path)
        if cached is None or cached[0] != mtime:
            try:
                cached = (mtime, load_guide(path), None)
            except GuideError as e:
                cached = (mtime, None, str(e))
            self._guides[path] = cached
        return cached[1], cached[2]

    def adopt_unassigned(self) -> None:
        """Interviews transcribed on the command line (or before projects existed) are
        put into the project "Bestehende Interviews", with the guide used so far."""
        loose = [iid for iid in self.transcripts() if self.store.project_of(iid) is None]
        if not loose:
            return
        project = next((p for p in self.store.projects() if p["name"] == LEGACY_PROJECT), None)
        if project is None:
            pid = self.store.create_project(LEGACY_PROJECT)
            guide = self._legacy_guide(loose)
            if guide is not None:
                target = self.guide_file(pid)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(guide, encoding="utf-8")
        else:
            pid = project["id"]
        self.store.assign_project(loose, pid)

    def _legacy_guide(self, ids: list[str]) -> str | None:
        for path in (self.legacy_guide, self.paths.root / "leitfaden.md"):
            if path and path.is_file():
                return path.read_text(encoding="utf-8-sig")
        for t in self.transcripts(ids).values():
            if t.analysis.get("guide"):
                return _guide_from_dict(t.analysis["guide"]).to_markdown()
        return None


def create_app(paths: Paths, login_token: str, port: int,
               guide_path: Path | None = None) -> FastAPI:
    """``guide_path``: guide for interviews from before projects existed."""
    store = Store(paths.root / "interis.db")
    data = _Data(paths, store, guide_path)
    data.adopt_unassigned()

    def job_guide(iid: str) -> Path | None:
        pid = store.project_of(iid)
        path = data.guide_file(pid) if pid is not None else None
        return path if path and path.is_file() else None

    def job_hotwords(iid: str) -> str:
        pid = store.project_of(iid)
        project = store.project(pid) if pid is not None else None
        return project["hotwords"].strip() if project else ""

    runner = JobRunner(paths, store, job_guide, job_hotwords)
    session_value = secrets.token_urlsafe(32)
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runner.start()
        yield
        runner.stop()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.runner = runner

    @app.middleware("http")
    async def security(request: Request, call_next):
        path = request.url.path
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({"detail": "bad origin"}, status_code=403)
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": "missing header"}, status_code=403)
        if path.startswith("/api/") and path != "/api/login":
            cookie = request.cookies.get(SESSION_COOKIE, "")
            if not secrets.compare_digest(cookie, session_value):
                return JSONResponse({"detail": "not logged in"}, status_code=401)
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:  # always revalidate the UI files, so updates are picked up on reload
            response.headers["Cache-Control"] = "no-cache"
        return response

    # Added last = outermost: reject foreign Host headers before anything else runs.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    # ------------------------------------------------------------------ helpers
    def _transcript(interview: str) -> Transcript:
        t = data.transcripts([interview]).get(interview)
        if t is None:
            raise HTTPException(404, "unknown interview")
        return t

    def _guide_of(interview: str) -> Guide | None:
        return data.guide(store.project_of(interview))[0]

    def _project(pid: int) -> dict[str, Any]:
        project = store.project(pid)
        if project is None:
            raise HTTPException(404, "unknown project")
        return project

    def _active_jobs(ids: list[str] | None = None) -> list[dict[str, Any]]:
        return [j for j in store.jobs(ids) if j["status"] in ("queued", "running")]

    def _queue_analysis(ids: list[str]) -> int:
        """Re-run the question analysis (not the transcription) after a guide change."""
        pending = {(j["kind"], j["interview_id"]) for j in _active_jobs(ids)}
        n = 0
        for iid in ids:
            if not (paths.exports / iid / f"{iid}.json").is_file():
                continue
            if ("analyze", iid) in pending or ("transcribe", iid) in pending:
                continue
            store.add_job("analyze", iid)
            n += 1
        runner.notify()
        return n

    def _check_span(t: Transcript, s: Span | QuestionDelete, last: int | None = None) -> None:
        if s.turn >= len(t.turns):
            raise HTTPException(422, "turn out of range")
        n = len(t.turns[s.turn].words)
        end = last if last is not None else s.first
        if not (s.first <= end < n):
            raise HTTPException(422, "word range out of range")

    def _check_code(code: str | None, guide: Guide | None) -> None:
        if code is not None and (guide is None or code not in {q.code for q in guide.questions}):
            raise HTTPException(422, "unknown guide code")

    # ------------------------------------------------------------------ routes
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.post("/api/login")
    def login(body: Login) -> Response:
        if not secrets.compare_digest(body.token, login_token):
            raise HTTPException(401, "invalid token")
        response = JSONResponse({"ok": True})
        response.set_cookie(SESSION_COOKIE, session_value, httponly=True, samesite="strict",
                            path="/")
        return response

    # ---------------------------------------------------------------- projects
    @app.get("/api/projects")
    def projects() -> list[dict[str, Any]]:
        data.adopt_unassigned()
        out = []
        for p in store.projects():
            ids = store.project_interviews(p["id"])
            guide, _ = data.guide(p["id"])
            out.append({**p, "interviews": len(ids),
                        "transcribed": len(data.transcripts(ids)),
                        "questions": len(guide.questions) if guide else 0,
                        "active_jobs": len(_active_jobs(ids))})
        return out

    @app.post("/api/projects")
    def create_project(body: ProjectCreate) -> dict[str, int]:
        return {"id": store.create_project(body.name.strip(), body.hotwords.strip())}

    @app.patch("/api/projects/{pid}")
    def update_project(pid: int, body: ProjectUpdate) -> dict[str, bool]:
        _project(pid)
        store.update_project(pid, body.name.strip() if body.name else None,
                             body.hotwords.strip() if body.hotwords is not None else None)
        return {"ok": True}

    @app.get("/api/projects/{pid}")
    def project(pid: int) -> dict[str, Any]:
        p = _project(pid)
        ids = store.project_interviews(pid)
        transcripts = data.transcripts(ids)
        guide, guide_error = data.guide(pid)
        guide_file = data.guide_file(pid)
        all_jobs = store.jobs()
        queue = [j["id"] for j in all_jobs if j["status"] in ("queued", "running")]
        latest: dict[str, dict[str, Any]] = {}
        for j in all_jobs:
            if j["interview_id"] in ids:
                pos = queue.index(j["id"]) if j["id"] in queue else None
                latest[j["interview_id"]] = {**j, "queue_pos": pos}
        interviews = []
        for iid in ids:
            t = transcripts.get(iid)
            audio = store.audio_path(iid)
            interviews.append({
                "id": iid,
                "transcribed": t is not None,
                "duration_s": t.meta["audio"]["duration_s"] if t else None,
                "has_audio": bool(audio and audio.exists()),
                "has_roles": bool(t and interviewer_of(t) is not None),
                "guide_mismatch": bool(t and guide_mismatch(t, guide)),
                "job": latest.get(iid),
            })
        taken = store.interview_ids() | {d.name for d in paths.exports.iterdir() if d.is_dir()}
        n = 1
        while f"I{n:02d}" in taken:
            n += 1
        return {
            "project": p,
            "guide": guide.to_dict() if guide else None,
            "guide_text": guide_file.read_text(encoding="utf-8-sig")
            if guide_file.is_file() else "",
            "guide_error": guide_error,
            "interviews": interviews,
            "next_id": f"I{n:02d}",
            "models": list(ASR_MODELS),
        }

    @app.put("/api/projects/{pid}/guide")
    def save_guide(pid: int, body: GuideText) -> dict[str, int]:
        _project(pid)
        try:
            guide = parse_guide(body.text)
        except GuideError as e:
            raise HTTPException(422, f"Leitfaden: {e}") from e
        target = data.guide_file(pid)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.text, encoding="utf-8")
        queued = _queue_analysis(store.project_interviews(pid))
        return {"questions": len(guide.questions), "reanalyze": queued}

    @app.post("/api/projects/{pid}/reanalyze")
    def reanalyze(pid: int) -> dict[str, int]:
        _project(pid)
        return {"reanalyze": _queue_analysis(store.project_interviews(pid))}

    @app.post("/api/guide/parse")
    def parse_guide_text(body: GuideText) -> dict[str, Any]:
        try:
            return {"guide": parse_guide(body.text).to_dict(), "error": None}
        except GuideError as e:
            return {"guide": None, "error": str(e)}

    @app.post("/api/guide/import-docx")
    async def import_docx(request: Request) -> dict[str, str]:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_DOCX_BYTES:
                raise HTTPException(413, "Datei zu groß")
        try:
            return {"text": docx_to_guide_text(bytes(body))}
        except Exception as e:  # noqa: BLE001 – any malformed file
            raise HTTPException(422, "Keine lesbare Word-Datei (.docx)") from e

    @app.post("/api/projects/{pid}/interviews")
    async def upload_interview(pid: int, request: Request,
                               interview: str = Query(max_length=40),
                               ext: str = Query(max_length=8),
                               model: str = Query("whisper-large-v3")) -> dict[str, Any]:
        """The recording is streamed into the data directory as ``audio/<ID>.<ext>``."""
        _project(pid)
        ext = ext.lower().lstrip(".")
        if not INTERVIEW_ID.match(interview):
            raise HTTPException(422, "Kürzel: nur Buchstaben, Ziffern, - und _ (max. 40)")
        if ext not in AUDIO_EXT:
            raise HTTPException(422, f"Dateityp .{ext} wird nicht unterstützt")
        if model not in ASR_MODELS:
            raise HTTPException(422, "unknown model")
        if interview in store.interview_ids() or (paths.exports / interview).exists():
            raise HTTPException(409, f"Das Kürzel {interview} ist schon vergeben")
        paths.audio.mkdir(parents=True, exist_ok=True)
        target = paths.audio / f"{interview}.{ext}"
        part = target.with_name(target.name + ".part")
        size = 0
        try:
            with part.open("wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise HTTPException(413, "Datei zu groß (max. 8 GB)")
                    f.write(chunk)
            if size == 0:
                raise HTTPException(422, "leere Datei")
            part.replace(target)
        finally:
            part.unlink(missing_ok=True)
        store.add_interview(interview, pid, target)
        job_id = store.add_job("transcribe", interview, {"model": model})
        runner.notify()
        return {"id": interview, "job": job_id}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int) -> dict[str, bool]:
        return {"ok": runner.cancel(job_id)}

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: int) -> dict[str, int]:
        job = store.job(job_id)
        if job is None or job["status"] not in ("failed", "cancelled"):
            raise HTTPException(409, "job is not failed or cancelled")
        new_id = store.add_job(job["kind"], job["interview_id"], job["options"])
        runner.notify()
        return {"job": new_id}

    @app.get("/api/projects/{pid}/compare")
    def compare(pid: int) -> dict[str, Any]:
        _project(pid)
        transcripts = data.transcripts(store.project_interviews(pid))
        guide, _ = data.guide(pid)
        states = {iid: interview_state(t, store.question_marks(iid), store.links(iid), guide)
                  for iid, t in transcripts.items()}
        return {
            "guide": guide.to_dict() if guide else None,
            "interviews": list(transcripts),
            "cells": {iid: s["cells"] for iid, s in states.items()},
            "unassigned": {iid: s["unassigned"] for iid, s in states.items()},
        }

    # ---------------------------------------------------------------- interviews
    @app.get("/api/interviews/{interview}")
    def interview(interview: str) -> dict[str, Any]:
        t = _transcript(interview)
        guide = _guide_of(interview)
        state = interview_state(t, store.question_marks(interview), store.links(interview),
                                guide)
        return {
            "id": interview,
            "project": store.project_of(interview),
            "speakers": t.speakers,
            "turns": [{"speaker": tu.speaker, "start": tu.start, "end": tu.end,
                       "words": [{"t": w.text, "s": w.start, "e": w.end, "p": round(w.prob, 2)}
                                 for w in tu.words]} for tu in t.turns],
            "questions": state["questions"],
            "links": store.links(interview),
            "cells": state["cells"],
        }

    @app.get("/api/interviews/{interview}/audio")
    def audio(interview: str) -> FileResponse:
        path = store.audio_path(interview)
        if path is None or not path.is_file():
            raise HTTPException(404, "no audio registered")
        return FileResponse(path)

    @app.delete("/api/interviews/{interview}")
    def delete_interview(interview: str) -> dict[str, bool]:
        """Removes the interview from Interis: transcript files, cached intermediate
        results, review decisions and the *uploaded copy* of the recording. A recording
        registered from elsewhere on the command line is left untouched."""
        if not INTERVIEW_ID.match(interview) or (
                store.project_of(interview) is None and interview not in data.transcripts()):
            raise HTTPException(404, "unknown interview")
        if any(j["status"] in ("queued", "running") for j in store.jobs([interview])):
            raise HTTPException(409, "Erst den laufenden Auftrag abbrechen")
        exports = paths.exports / interview
        audio = store.audio_path(interview)
        uploaded = audio is not None and audio.parent == paths.audio and audio.is_file()
        sha = None
        transcript = exports / f"{interview}.json"
        if transcript.is_file():
            sha = json.loads(transcript.read_text(encoding="utf-8"))["meta"]["audio"]["sha256"]
        elif uploaded:
            sha = sha256_file(audio)
        if sha:
            cache = paths.cache / sha[:16]
            if cache.parent == paths.cache and cache.is_dir():
                shutil.rmtree(cache)
        if exports.is_dir() and exports.parent == paths.exports:
            shutil.rmtree(exports)
        if uploaded:
            audio.unlink()
        store.delete_interview(interview)
        return {"ok": True}

    @app.post("/api/questions")
    def set_question(body: QuestionUpdate) -> dict[str, bool]:
        t = _transcript(body.interview)
        _check_span(t, body, body.last)
        _check_code(body.guide_code, _guide_of(body.interview))
        auto = {(q["turn"], q["first"]) for q in t.analysis.get("questions", [])}
        source = "auto" if (body.turn, body.first) in auto else "manual"
        store.set_question(body.interview, body.turn, body.first, body.last, body.guide_code,
                           body.match, body.status, source)
        return {"ok": True}

    @app.post("/api/questions/reset")
    def reset_question(body: QuestionDelete) -> dict[str, bool]:
        _check_span(_transcript(body.interview), body)
        store.delete_question(body.interview, body.turn, body.first)
        return {"ok": True}

    @app.post("/api/links")
    def create_link(body: LinkCreate) -> dict[str, int]:
        t = _transcript(body.interview)
        _check_span(t, body, body.last)
        _check_code(body.guide_code, _guide_of(body.interview))
        link_id = store.set_link(body.interview, body.guide_code, body.turn, body.first,
                                 body.last, body.status, body.source, body.omitted, body.note)
        return {"id": link_id}

    @app.patch("/api/links/{link_id}")
    def update_link(link_id: int, body: LinkUpdate) -> dict[str, bool]:
        store.update_link(link_id, body.omitted, body.note)
        return {"ok": True}

    @app.delete("/api/links/{link_id}")
    def delete_link(link_id: int) -> dict[str, bool]:
        store.delete_link(link_id)
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
