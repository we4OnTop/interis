"""Local review website (FastAPI). Reachable only from this computer.

Security (see ARCHITECTURE.md §6):
* bound to 127.0.0.1 by the launcher; Host header allow-list against DNS rebinding;
* per-start login token (in the URL *fragment*, never sent in requests or logged),
  exchanged for an HttpOnly, SameSite=Strict session cookie required by every API call;
* state-changing requests need a same-origin ``Origin`` and a custom header, which a
  foreign website cannot send without a CORS preflight (and there is no CORS);
* strict Content-Security-Policy, no third-party resources, no API docs endpoints;
* interview text is rendered with ``textContent`` only in the frontend.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from interis.analysis.guide import Guide, GuideQuestion, load_guide
from interis.config import Paths
from interis.pipeline.types import Transcript
from interis.web.review import guide_mismatch, interview_state, interviewer_of
from interis.web.store import Store

STATIC = Path(__file__).parent / "static"
SESSION_COOKIE = "interis_session"
CSRF_HEADER = "x-interis"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'none'")


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


def _guide_from_dict(d: dict[str, Any]) -> Guide:
    return Guide(d.get("title"), [GuideQuestion(**q) for q in d["questions"]])


class _Data:
    """Transcripts are re-read only when their file changes."""

    def __init__(self, paths: Paths, guide_path: Path | None) -> None:
        self.paths = paths
        self.guide_path = guide_path
        self._cache: dict[Path, tuple[float, Transcript]] = {}

    def transcripts(self) -> dict[str, Transcript]:
        out = {}
        for path in sorted(self.paths.exports.glob("*/*.json")):
            if path.stem != path.parent.name:
                continue
            mtime = path.stat().st_mtime
            cached = self._cache.get(path)
            if cached is None or cached[0] != mtime:
                t = Transcript.from_dict(json.loads(path.read_text(encoding="utf-8")))
                cached = self._cache[path] = (mtime, t)
            out[cached[1].meta["interview_id"]] = cached[1]
        return out

    def guide(self, transcripts: dict[str, Transcript]) -> Guide | None:
        if self.guide_path and self.guide_path.exists():
            return load_guide(self.guide_path)
        default = self.paths.root / "leitfaden.md"
        if default.exists():
            return load_guide(default)
        for t in transcripts.values():
            if t.analysis.get("guide"):
                return _guide_from_dict(t.analysis["guide"])
        return None


def create_app(paths: Paths, login_token: str, port: int,
               guide_path: Path | None = None) -> FastAPI:
    store = Store(paths.root / "interis.db")
    data = _Data(paths, guide_path)
    session_value = secrets.token_urlsafe(32)
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

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
        t = data.transcripts().get(interview)
        if t is None:
            raise HTTPException(404, "unknown interview")
        return t

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

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        transcripts = data.transcripts()
        guide = data.guide(transcripts)
        return {
            "guide": guide.to_dict() if guide else None,
            "interviews": [{
                "id": iid,
                "duration_s": t.meta["audio"]["duration_s"],
                "has_audio": bool((p := store.audio_path(iid)) and p.exists()),
                "has_roles": interviewer_of(t) is not None,
                "guide_mismatch": guide_mismatch(t, guide),
            } for iid, t in transcripts.items()],
        }

    @app.get("/api/compare")
    def compare() -> dict[str, Any]:
        transcripts = data.transcripts()
        guide = data.guide(transcripts)
        states = {iid: interview_state(t, store.question_marks(iid), store.links(iid), guide)
                  for iid, t in transcripts.items()}
        return {
            "guide": guide.to_dict() if guide else None,
            "interviews": list(transcripts),
            "cells": {iid: s["cells"] for iid, s in states.items()},
            "unassigned": {iid: s["unassigned"] for iid, s in states.items()},
        }

    @app.get("/api/interviews/{interview}")
    def interview(interview: str) -> dict[str, Any]:
        t = _transcript(interview)
        guide = data.guide(data.transcripts())
        state = interview_state(t, store.question_marks(interview), store.links(interview),
                                guide)
        return {
            "id": interview,
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

    @app.post("/api/questions")
    def set_question(body: QuestionUpdate) -> dict[str, bool]:
        t = _transcript(body.interview)
        _check_span(t, body, body.last)
        _check_code(body.guide_code, data.guide(data.transcripts()))
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
        _check_code(body.guide_code, data.guide(data.transcripts()))
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
