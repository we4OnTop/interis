"""Desktop app: runs the local server and shows the interface in its own window
(pywebview → Microsoft Edge WebView2, part of Windows 11).

Started by ``Interis.exe`` (portable version) or ``uv run interis-app``.

* First start (no data folder configured): a setup assistant asks for the data folder and
  where the models are (existing folder = linked in place, or download target).
* The server listens on 127.0.0.1 on a free port, with a fresh login token per start; the
  window logs in automatically.
* Changing folders restarts the server in place.
* Only one instance runs at a time (two would process the job queue twice).
"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from interis import _bootstrap

_bootstrap.go_offline()

from interis.config import ConfigError, apply_paths, resolve_paths, settings_file  # noqa: E402

log = logging.getLogger("interis.desktop")
TITLE = "Interis"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _single_instance() -> bool:
    """A named Windows mutex; False if Interis is already running."""
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, "Local\\Interis-desktop")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def _message(text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x40)
    else:
        print(text)


class Server:
    """uvicorn in a background thread; can be rebuilt with the current settings."""

    def __init__(self, on_restart) -> None:
        self.on_restart = on_restart
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        import uvicorn

        from interis.web.app import create_app
        from interis.web.system import create_setup_app

        port = _free_port()
        token = secrets.token_urlsafe(24)
        try:
            paths = resolve_paths(None, None)
            apply_paths(paths)
            app = create_app(paths, token, port, on_restart=self.on_restart)
            log.info("main app on port %s (data %s, models %s)", port, paths.root, paths.models)
        except ConfigError as e:
            log.info("setup app on port %s (%s)", port, e)
            app = create_setup_app(token, port, on_restart=self.on_restart)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                access_log=False, log_config=None)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="interis-server",
                                        daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 30
        while not self._server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self._server.started:
            raise RuntimeError("Der lokale Server ist nicht gestartet.")
        return f"http://127.0.0.1:{port}/#login={token}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=30)


class Api:
    """Exposed to the page as ``window.pywebview.api`` – only a folder picker."""

    def __init__(self) -> None:
        self.window = None

    def pick_folder(self, start: str = "") -> str | None:
        import webview

        start_dir = start if start and Path(start).is_dir() else ""
        result = self.window.create_file_dialog(webview.FileDialog.FOLDER,
                                                directory=start_dir)
        return result[0] if result else None


def main() -> int:
    if sys.stdout is None:  # pythonw.exe has no console
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    log_file = settings_file().parent / "interis-desktop.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    # The log holds folder paths and errors only – never interview content.
    logging.basicConfig(filename=log_file, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not _single_instance():
        _message("Interis läuft bereits.")
        return 0

    api = Api()
    holder: dict = {}

    def restart() -> None:
        log.info("restart requested")
        holder["server"].stop()
        url = holder["server"].start()
        if api.window is not None:
            api.window.load_url(url)

    server = Server(restart)
    holder["server"] = server
    try:
        url = server.start()
    except Exception:
        log.exception("start failed")
        _message(f"Interis konnte nicht starten. Details: {log_file}")
        return 1

    try:
        import webview
    except ImportError:
        webview = None
    if webview is None:  # fallback: Edge in app mode
        import webbrowser

        webbrowser.open(url)
        _message("Interis läuft im Browser. Dieses Fenster schließen beendet Interis.")
        server.stop()
        return 0

    storage = settings_file().parent / "webview"  # dark mode etc.; no interview data
    api.window = webview.create_window(TITLE, url, js_api=api, width=1440, height=920,
                                       min_size=(1000, 650), text_select=True)
    try:
        webview.start(private_mode=False, storage_path=str(storage))
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
