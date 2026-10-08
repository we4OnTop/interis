"""Background jobs started from the website (transcription, re-analysis).

Each job runs the normal command line tool as a *separate process*, one job at a time:

* the website stays responsive while the CPU is busy for an hour;
* the models' memory is fully released after every job;
* the job can be cancelled by ending the process;
* the child process goes through the same privacy bootstrap (offline, network guard,
  firewall rule for the interpreter) as when started by hand.

Progress arrives as JSON lines on the child's stdout (``--progress-json``).
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 – fixed argument list, never a shell
import sys
import threading
import time
from collections import deque
from pathlib import Path

from interis._bootstrap import OFFLINE, proxy_env_removed
from interis.config import Paths
from interis.web.store import Store

POLL_S = 1.0


class JobRunner:
    def __init__(self, paths: Paths, store: Store, guide_file, hotwords) -> None:
        """``guide_file(interview_id)`` -> Path | None and ``hotwords(interview_id)`` -> str
        give the project settings at the moment a job starts."""
        self.paths = paths
        self.store = store
        self.guide_file = guide_file
        self.hotwords = hotwords
        self._proc: subprocess.Popen | None = None
        self._current: int | None = None
        self._cancel: set[int] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        self.store.requeue_interrupted_jobs()
        self._thread = threading.Thread(target=self._loop, name="interis-jobs", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        with self._lock:
            if self._proc is not None:
                self._proc.terminate()

    def notify(self) -> None:
        self._wake.set()

    def cancel(self, job_id: int) -> bool:
        job = self.store.job(job_id)
        if job is None or job["status"] not in ("queued", "running"):
            return False
        with self._lock:
            if self._current == job_id and self._proc is not None:
                self._cancel.add(job_id)
                self._proc.terminate()
                return True
        self.store.update_job(job_id, status="cancelled", message="abgebrochen")
        return True

    # ------------------------------------------------------------------ worker
    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.next_queued_job()
            if job is None:
                self._wake.wait(POLL_S)
                self._wake.clear()
                continue
            try:
                self._run(job)
            except Exception as e:  # noqa: BLE001 – a broken job must not stop the queue
                self.store.update_job(job["id"], status="failed", message=str(e)[:500])

    def command(self, job: dict) -> list[str]:
        iid = job["interview_id"]
        # -I: ignore PYTHON* variables and the working directory, so no other code can be
        # imported in place of the installed package
        base = [sys.executable, "-I", "-m", "interis.cli", "--data-dir", str(self.paths.root)]
        if self.paths.models_dir is not None:
            base += ["--models-dir", str(self.paths.models_dir)]
        if job["kind"] == "models":
            # The only job that uses the network: download + verify the pinned models.
            return [*base, "setup-models", "--use-system-certs", "--allow-verified-mirror",
                    "--progress-json"]
        guide = self.guide_file(iid)
        guide_args = ["--guide", str(guide)] if guide else []
        if job["kind"] == "transcribe":
            audio = self.store.part_paths(iid)
            missing = [p.name for p in audio if not p.is_file()]
            if not audio or missing:
                raise RuntimeError("Audiodatei nicht gefunden: " + ", ".join(missing))
            cmd = [*base, "transcribe", *map(str, audio), "--id", iid, "--progress-json",
                   "--model", job["options"].get("model", "whisper-large-v3"), *guide_args]
            if hotwords := self.hotwords(iid):
                cmd += ["--hotwords", hotwords]
            return cmd
        transcript = self.paths.exports / iid / f"{iid}.json"
        if not transcript.is_file():
            raise RuntimeError("Transkript nicht gefunden")
        return [*base, "analyze", str(transcript), *guide_args]

    def _write_edits(self, job: dict, path: Path) -> bool:
        """The word edits of an interview as a temporary JSON file (no transcript text is
        logged). False if there are no edits."""
        rows = [{k: e[k] for k in ("turn", "word", "action", "kind", "text", "tag")}
                for e in self.store.word_edits(job["interview_id"])]
        if not rows:
            return False
        self.paths.tmp.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return True

    def _run(self, job: dict) -> None:
        cmd = self.command(job)
        edits_file = self.paths.tmp / f"edits-{job['id']}.json"
        try:
            # The analysis runs on the edited text; the transcript itself is never changed.
            if job["kind"] == "analyze" and self._write_edits(job, edits_file):
                cmd = [*cmd, "--edits", str(edits_file)]
            self._execute(job, cmd)
        finally:
            edits_file.unlink(missing_ok=True)

    def _execute(self, job: dict, cmd: list[str]) -> None:
        job_id = job["id"]
        self.store.update_job(job_id, status="running", stage="start", progress=0.0,
                              message="")
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        if job["kind"] == "models":  # this process is offline; the download child is not
            for key in OFFLINE:
                env.pop(key, None)
            env.update(proxy_env_removed)  # the explicit download may need a proxy
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        tail: deque[str] = deque(maxlen=15)
        with self._lock:
            self._current = job_id
            self._proc = subprocess.Popen(  # noqa: S603 – own CLI, argument list, no shell
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env=env, encoding="utf-8", errors="replace", creationflags=flags)
            proc = self._proc
        last_write = 0.0
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith("{") and '"stage"' in line:
                try:
                    p = json.loads(line)
                except ValueError:
                    continue
                now = time.monotonic()
                try:
                    stage, fraction = str(p["stage"])[:40], float(p["fraction"])
                except (KeyError, TypeError, ValueError):
                    continue  # not one of our progress lines; keep reading the output
                if now - last_write >= 1.0 or fraction >= 1.0:
                    self.store.update_job(job_id, stage=stage, progress=fraction)
                    last_write = now
            else:
                tail.append(line)
        code = proc.wait()
        with self._lock:
            self._proc = None
            self._current = None
            cancelled = job_id in self._cancel
            self._cancel.discard(job_id)
        if cancelled:
            self.store.update_job(job_id, status="cancelled", message="abgebrochen")
        elif code == 0:
            self.store.update_job(job_id, status="done", progress=1.0,
                                  message=tail[-1] if tail else "")
        else:
            errors = [t for t in tail if "ERROR" in t or "Error" in t]
            self.store.update_job(job_id, status="failed",
                                  message=(errors[-1] if errors else "\n".join(tail))[-800:])


def guide_path_for(paths: Paths, project_id: int) -> Path:
    return paths.root / "projects" / str(project_id) / "leitfaden.md"
