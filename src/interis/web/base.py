"""The security frame shared by the main app and the first-start setup app.

* bound to 127.0.0.1 by the launcher; Host header allow-list against DNS rebinding;
* per-start login token (in the URL *fragment*, never sent in requests or logged),
  exchanged for an HttpOnly, SameSite=Strict session cookie required by every API call;
* state-changing requests must send a custom header (``X-Interis``), which a foreign
  website cannot send without a CORS preflight (there is no CORS). An ``Origin`` header,
  when the browser sends one, must be the local origin;
* strict Content-Security-Policy, no third-party resources, no API docs endpoints.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

UI = Path(__file__).parent / "dist"  # built from frontend/ (npm run build)
SESSION_COOKIE = "interis_session"
CSRF_HEADER = "x-interis"
NONCE_PLACEHOLDER = "__CSP_NONCE__"
# Radix Select renders one fixed <style> element (hide the list scrollbar) without a nonce.
# Its hash is allowed explicitly; if the library text changes, that element is refused and
# only the scrollbar styling is lost.
RADIX_SELECT_STYLE = "sha256-441zG27rExd4/il+NvIqyL8zFx5XmyNQtE381kSkUJk="
CSP = ("default-src 'self'; script-src 'self'; "
       f"style-src 'self' '{RADIX_SELECT_STYLE}'; img-src 'self' data:; "
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
        # A fresh nonce per response: the UI library may add <style> elements (scroll lock
        # while a dialog is open), and only those carrying this nonce are allowed.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({"detail": "bad origin"}, status_code=403)
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": "missing header"}, status_code=403)
        if path.startswith("/api/") and path != "/api/login":
            cookie = request.cookies.get(SESSION_COOKIE, "")
            if not secrets.compare_digest(cookie.encode("utf-8"), session_value.encode()):
                return JSONResponse({"detail": "not logged in"}, status_code=401)
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP.replace(
            "style-src 'self'", f"style-src 'self' 'nonce-{nonce}'", 1)
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
    def index(request: Request) -> Response:
        page = UI / "index.html"
        if not page.is_file():
            return PlainTextResponse("Oberfläche nicht gebaut: im Ordner frontend `npm ci` und "
                                     "`npm run build` ausführen.", status_code=500)
        html = page.read_text(encoding="utf-8").replace(NONCE_PLACEHOLDER,
                                                         request.state.csp_nonce)
        return HTMLResponse(html)

    @app.post("/api/login")
    def login(body: Login) -> Response:
        if not secrets.compare_digest(body.token.encode("utf-8"), login_token.encode()):
            raise HTTPException(401, "invalid token")
        response = JSONResponse({"ok": True})
        response.set_cookie(SESSION_COOKIE, session_value, httponly=True, samesite="strict",
                            path="/")
        return response

    if (UI / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=UI / "assets"), name="assets")
    return app
