"""The security frame shared by the main app and the first-start setup app.

* bound to 127.0.0.1 by the launcher; Host header allow-list against DNS rebinding;
* per-start login token (in the URL *fragment*, never sent in requests or logged),
  exchanged for an HttpOnly, SameSite=Strict session cookie required by every API call;
* state-changing requests need a same-origin ``Origin`` and a custom header, which a
  foreign website cannot send without a CORS preflight (and there is no CORS);
* strict Content-Security-Policy, no third-party resources, no API docs endpoints.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

UI = Path(__file__).parent / "dist"  # built from frontend/ (npm run build)
SESSION_COOKIE = "interis_session"
CSRF_HEADER = "x-interis"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'none'")


class Login(BaseModel):
    token: str = Field(max_length=200)


def secure_app(login_token: str, port: int, lifespan=None) -> FastAPI:
    session_value = secrets.token_urlsafe(32)
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

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

    @app.get("/")
    def index() -> Response:
        page = UI / "index.html"
        if not page.is_file():
            return PlainTextResponse("Oberfläche nicht gebaut: im Ordner frontend `npm ci` und "
                                     "`npm run build` ausführen.", status_code=500)
        return FileResponse(page)

    @app.post("/api/login")
    def login(body: Login) -> Response:
        if not secrets.compare_digest(body.token, login_token):
            raise HTTPException(401, "invalid token")
        response = JSONResponse({"ok": True})
        response.set_cookie(SESSION_COOKIE, session_value, httponly=True, samesite="strict",
                            path="/")
        return response

    if (UI / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=UI / "assets"), name="assets")
    return app
