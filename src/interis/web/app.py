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

import hashlib
import io
import json
import re
import shutil
import threading
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import AfterValidator, BaseModel, Field

from interis.analysis.guide import (
    Guide,
    GuideError,
    docx_to_guide_text,
    label_guide,
    load_guide,
    parse_guide,
    typst_to_guide_text,
)
from interis.config import Paths
from interis.models import ASR_MODELS
from interis.pipeline.cache import combined_sha
from interis.pipeline.types import Transcript
from interis.web import extracts as export
from interis.web.base import secure_app
from interis.web.edits import (
    MAX_TAG_LEN,
    MAX_TAGS,
    MAX_TEXT_LEN,
    apply_edits,
    edited_words,
    parse_tags,
    project_tags,
)
from interis.web.jobs import JobRunner, guide_path_for
from interis.web.review import (
    edits_stale,
    guide_mismatch,
    interview_state,
    interviewer_of,
    passage,
)
from interis.web.store import Store
from interis.web.system import add_system_routes
from interis.web.workflow import workflow_state

INTERVIEW_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
AUDIO_EXT = {"m4a", "mp3", "wav", "aac", "flac", "ogg", "opus", "wma", "webm", "mp4", "mov",
             "mkv", "avi", "3gp", "amr"}
MAX_AUDIO_BYTES = 8 * 1024**3
MAX_DOCX_BYTES = 20 * 1024**2
# A .docx is a zip: its parts must stay small after decompression too (zip bomb).
MAX_DOCX_UNPACKED = 50 * 1024**2
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
MAX_GUIDE_CHARS = 200_000
LEGACY_PROJECT = "Bestehende Interviews"


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
    # None: keep the stored value of an existing link
    omitted: bool | None = None
    note: str | None = Field(default=None, max_length=2000)


class LinkUpdate(BaseModel):
    omitted: bool | None = None
    note: str | None = Field(default=None, max_length=2000)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    hotwords: str = Field(default="", max_length=2000)


# control, format, surrogate, line and paragraph separator characters
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def _plain(value: str) -> str:
    """One-line text: no control or invisible format characters at all."""
    if any(unicodedata.category(c) in _UNSAFE_CATEGORIES for c in value):
        raise ValueError("Steuerzeichen sind nicht erlaubt")
    return value


def _multiline(value: str) -> str:
    """Text from a textarea: line breaks allowed, other control characters not."""
    if any(unicodedata.category(c) in _UNSAFE_CATEGORIES and c not in "\r\n" for c in value):
        raise ValueError("Steuerzeichen sind nicht erlaubt")
    return value


Plain = Annotated[str, AfterValidator(_plain)]
Multiline = Annotated[str, AfterValidator(_multiline)]


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    hotwords: str | None = Field(default=None, max_length=2000)
    smoothing_tags: Multiline | None = Field(default=None, max_length=2000)


class WordRange(BaseModel):
    turn: int = Field(ge=0)
    first: int = Field(ge=0)
    last: int = Field(ge=0)


class EditCreate(WordRange):
    action: Literal["replace", "delete"]
    kind: Literal["correction", "smoothing"]
    text: Plain = Field(default="", max_length=MAX_TEXT_LEN)
    tag: Plain = Field(default="", max_length=MAX_TAG_LEN)


class ReviewedUpdate(BaseModel):
    reviewed: bool


class DecisionUpdate(BaseModel):
    reason: Literal["not_asked", "not_relevant", "other"] | None = None
    note: Multiline = Field(default="", max_length=2000)


class ExtractCreate(Span):
    guide_code: Plain = Field(max_length=40)
    paraphrase: Multiline = Field(max_length=2000)


class ExtractUpdate(BaseModel):
    paraphrase: Multiline = Field(max_length=2000)


class InterviewCreate(BaseModel):
    interview: str = Field(max_length=40)


class TranscribeRequest(BaseModel):
    model: str = Field(default="whisper-large-v3", max_length=60)
    # Re-transcribing changes all word positions, so earlier markings would point to
    # the wrong words. They are removed – only after the user confirmed it.
    discard_markings: bool = False


class PartOrder(BaseModel):
    order: list[int] = Field(max_length=100)


class GuideText(BaseModel):
    text: str = Field(max_length=MAX_GUIDE_CHARS)


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
            # an ID from the file contents becomes a path component later: accept only
            # IDs that match the folder name and the ID rules
            if (not INTERVIEW_ID.match(path.stem)
                    or cached[1].meta.get("interview_id") != path.stem):
                continue
            out[path.stem] = cached[1]
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
                return Guide.from_dict(t.analysis["guide"]).to_markdown()
        return None


def _docx_unpacked_size(data: bytes) -> int:
    """Sum of the declared sizes of all parts of a zip-based file (0 if it is not a zip)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        return 0


def create_app(paths: Paths, login_token: str, port: int,
               guide_path: Path | None = None,
               on_restart: Callable[[], None] | None = None) -> FastAPI:
    """``guide_path``: guide for interviews from before projects existed.
    ``on_restart``: provided by the desktop app, which can restart the server (e.g. after
    the data or models folder was changed)."""
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
    # Every check of the job queue or of word positions and the write it guards runs under
    # this lock, so a transcription cannot start between the check and the write.
    write_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        runner.start()
        yield
        runner.stop()

    app = secure_app(login_token, port, lifespan)
    app.state.runner = runner

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # The default answer echoes the rejected value; a lone surrogate in it cannot be
        # encoded as UTF-8, which turned the 422 into a 500. Location, message and type stay.
        detail = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
                  for e in exc.errors()]
        return JSONResponse({"detail": detail}, status_code=422)
    add_system_routes(app, paths, store, runner, on_restart)

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
        """Re-run the question analysis (not the transcription) after a guide change or edit.
        A running analysis does not block: it read the edits before they were changed."""
        n = 0
        with write_lock:
            pending = {j["interview_id"] for j in _active_jobs(ids)
                       if j["kind"] == "analyze" and j["status"] == "queued"}
            for iid in ids:
                if not (paths.exports / iid / f"{iid}.json").is_file() or iid in pending:
                    continue
                store.add_job("analyze", iid)
                n += 1
        runner.notify()
        return n

    def _parts_info(iid: str, t: Transcript | None) -> list[dict[str, Any]]:
        out = []
        timeline = t.parts if t else []
        for i, part in enumerate(store.parts(iid)):
            path = part["path"]
            out.append({
                "idx": part["idx"], "ext": path.suffix.lstrip("."), "sha256": part["sha256"],
                "exists": path.is_file(),
                "size": path.stat().st_size if path.is_file() else None,
                "uploaded": path.parent == paths.audio,
                "offset_s": timeline[i]["offset_s"] if i < len(timeline) else None,
                "duration_s": timeline[i]["duration_s"] if i < len(timeline) else None,
            })
        return out

    def _parts_changed(parts: list[dict[str, Any]], t: Transcript | None) -> bool:
        """Recordings added, removed or reordered since the transcript was made."""
        if t is None:
            return False
        recorded = [p.get("sha256") for p in t.meta["audio"].get("parts", [])]
        if not recorded:  # transcript from before multi-part support
            recorded = [t.meta["audio"]["sha256"]]
        current = [p["sha256"] for p in parts]
        if any(c is None for c in current):  # registered on the command line, unknown
            return len(current) != len(recorded)
        return current != recorded

    def _interview_in_project(interview: str) -> int:
        pid = store.project_of(interview) if INTERVIEW_ID.match(interview) else None
        if pid is None:
            raise HTTPException(404, "unknown interview")
        return pid

    def _has_work(interview: str) -> bool:
        """Anything a person did on this interview that word positions would break."""
        return bool(store.question_marks(interview) or store.links(interview)
                    or store.word_edits(interview) or store.extracts([interview])
                    or store.decisions(interview) or store.reviewed(interview))

    def _not_busy(interview: str) -> None:
        if any(j["status"] in ("queued", "running") for j in store.jobs([interview])):
            raise HTTPException(409, "Erst den laufenden Auftrag abbrechen")

    def _remove_upload(path: Path) -> None:
        """Only copies made by the upload are ever deleted, never original recordings."""
        if path.parent == paths.audio and path.is_file():
            path.unlink()

    def _state_of(interview: str, t: Transcript, guide: Guide | None) -> dict[str, Any]:
        """Review state on the effective transcript (word edits applied)."""
        return interview_state(t, store.question_marks(interview), store.links(interview),
                               guide, store.word_edits(interview), store.decisions(interview))

    def _with_passage(t: Transcript, lk: dict[str, Any]) -> dict[str, Any]:
        """A link with the passage fields of the effective transcript (none if the link
        points outside the transcript, as stale rows of a replaced transcript can)."""
        if lk["turn"] >= len(t.turns) or lk["last"] >= len(t.turns[lk["turn"]].words):
            return lk
        return {**lk, **passage(t, lk["turn"], lk["first"], lk["last"])}

    def _paraphrase(text: str) -> str:
        if not text.strip():
            raise HTTPException(422, "Kernaussage fehlt")
        return text.strip()

    def _tags_of(raw: str) -> list[str]:
        tags = parse_tags(raw)
        if len(tags) > MAX_TAGS or any(len(tag) > MAX_TAG_LEN for tag in tags):
            raise HTTPException(422, f"Höchstens {MAX_TAGS} Tags, je {MAX_TAG_LEN} Zeichen")
        return tags

    def _not_transcribing(interview: str) -> None:
        """Word positions change with a new transcription, so no marking is written meanwhile
        (edits, question marks, links, extracts, decisions, "Korrektur abgeschlossen")."""
        if any(j["kind"] == "transcribe" and j["status"] in ("queued", "running")
               for j in store.jobs([interview])):
            raise HTTPException(409, "Erst die laufende Transkription abwarten")

    def _extract_rows(pid: int) -> list[dict[str, Any]]:
        """Extracts of a project; ``text`` and times come from the effective transcript.
        ``in_guide`` is False for a guide code that the guide no longer has."""
        ids = store.project_interviews(pid)
        transcripts = data.transcripts(ids)
        guide, _ = data.guide(pid)
        codes = {q.code for q in guide.questions} if guide else set()
        effective: dict[str, Transcript] = {}
        rows = []
        for e in store.extracts(ids):
            iid = e["interview_id"]
            if iid not in transcripts:
                continue
            if iid not in effective:
                effective[iid] = apply_edits(transcripts[iid], store.word_edits(iid))
            t = effective[iid]
            if e["turn"] >= len(t.turns) or e["last"] >= len(t.turns[e["turn"]].words):
                continue
            p = passage(t, e["turn"], e["first"], e["last"])
            rows.append({"id": e["id"], "interview": iid, "guide_code": e["guide_code"],
                         "turn": e["turn"], "first": e["first"], "last": e["last"],
                         "start": p["start"], "end": p["end"], "text": p["text"],
                         "paraphrase": e["paraphrase"], "updated_at": e["updated_at"],
                         "in_guide": e["guide_code"] in codes})
        return rows

    def _check_span(t: Transcript, s: Span | QuestionDelete | WordRange,
                    last: int | None = None) -> None:
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
        tags = None if body.smoothing_tags is None else "\n".join(_tags_of(body.smoothing_tags))
        store.update_project(pid, body.name.strip() if body.name else None,
                             body.hotwords.strip() if body.hotwords is not None else None,
                             tags)
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
            parts = _parts_info(iid, t)
            interviews.append({
                "id": iid,
                "transcribed": t is not None,
                "duration_s": t.meta["audio"]["duration_s"] if t else None,
                "parts": parts,
                "parts_changed": _parts_changed(parts, t),
                "has_audio": bool(parts) and all(x["exists"] for x in parts),
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
            "tags": project_tags(p["smoothing_tags"]),
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
            text = label_guide(body.text)  # codes of unlabelled questions are kept from now on
            guide = parse_guide(text)
        except GuideError as e:
            raise HTTPException(422, f"Leitfaden: {e}") from e
        target = data.guide_file(pid)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
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

    @app.post("/api/guide/import-typst")
    def import_typst(body: GuideText) -> dict[str, str]:
        try:
            return {"text": typst_to_guide_text(body.text)}
        except GuideError as e:
            raise HTTPException(422, f"Typst-Leitfaden: {e}") from e

    @app.post("/api/guide/import-docx")
    async def import_docx(request: Request) -> dict[str, str]:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_DOCX_BYTES:
                raise HTTPException(413, "Datei zu groß")
        if _docx_unpacked_size(bytes(body)) > MAX_DOCX_UNPACKED:
            raise HTTPException(413, "Word-Datei enthält zu viel Inhalt")
        try:
            return {"text": docx_to_guide_text(bytes(body))}
        except Exception as e:  # noqa: BLE001 – any malformed file
            raise HTTPException(422, "Keine lesbare Word-Datei (.docx)") from e

    @app.post("/api/projects/{pid}/interviews")
    def create_interview(pid: int, body: InterviewCreate) -> dict[str, str]:
        _project(pid)
        iid = body.interview.strip()
        if not INTERVIEW_ID.match(iid):
            raise HTTPException(422, "Kürzel: nur Buchstaben, Ziffern, - und _ (max. 40)")
        if iid in store.interview_ids() or (paths.exports / iid).exists():
            raise HTTPException(409, f"Das Kürzel {iid} ist schon vergeben")
        store.add_interview(iid, pid)
        return {"id": iid}

    @app.post("/api/interviews/{interview}/parts")
    async def upload_part(interview: str, request: Request,
                          ext: str = Query(max_length=8)) -> dict[str, int]:
        """Streams one recording into ``<data>/audio/<ID>-<n>.<ext>``. The original file
        name never reaches the server (it may contain real names)."""
        _interview_in_project(interview)
        _not_busy(interview)
        ext = ext.lower().lstrip(".")
        if ext not in AUDIO_EXT:
            raise HTTPException(422, f"Dateityp .{ext} wird nicht unterstützt")
        paths.audio.mkdir(parents=True, exist_ok=True)
        n = 1
        while any(paths.audio.glob(f"{interview}-{n}.*")):
            n += 1
        target = paths.audio / f"{interview}-{n}.{ext}"
        tmp = target.with_name(target.name + ".upload")
        digest = hashlib.sha256()
        size = 0
        try:
            with tmp.open("wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise HTTPException(413, "Datei zu groß (max. 8 GB)")
                    digest.update(chunk)
                    f.write(chunk)
            if size == 0:
                raise HTTPException(422, "leere Datei")
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
        return {"idx": store.add_part(interview, target, digest.hexdigest())}

    @app.put("/api/interviews/{interview}/parts")
    def order_parts(interview: str, body: PartOrder) -> dict[str, bool]:
        _interview_in_project(interview)
        _not_busy(interview)
        parts = {p["idx"]: p for p in store.parts(interview)}
        if sorted(body.order) != sorted(parts):
            raise HTTPException(422, "order must list every part exactly once")
        store.set_parts(interview, [(parts[i]["path"], parts[i]["sha256"]) for i in body.order])
        return {"ok": True}

    @app.delete("/api/interviews/{interview}/parts/{idx}")
    def delete_part(interview: str, idx: int) -> dict[str, bool]:
        _interview_in_project(interview)
        _not_busy(interview)
        parts = store.parts(interview)
        gone = next((p for p in parts if p["idx"] == idx), None)
        if gone is None:
            raise HTTPException(404, "unknown part")
        store.set_parts(interview, [(p["path"], p["sha256"]) for p in parts if p is not gone])
        _remove_upload(gone["path"])
        return {"ok": True}

    @app.post("/api/interviews/{interview}/transcribe")
    def start_transcription(interview: str, body: TranscribeRequest) -> dict[str, int]:
        _interview_in_project(interview)
        if body.model not in ASR_MODELS:
            raise HTTPException(422, "unknown model")
        parts = store.parts(interview)
        if not parts:
            raise HTTPException(422, "Noch keine Aufnahme hochgeladen")
        if not all(p["path"].is_file() for p in parts):
            raise HTTPException(422, "Eine Aufnahme fehlt im Datenordner")
        with write_lock:
            _not_busy(interview)
            # The markings stay until the new transcript exists (see JobRunner): a job that is
            # cancelled or fails leaves the interview as it was.
            if ((paths.exports / interview / f"{interview}.json").is_file()
                    and _has_work(interview) and not body.discard_markings):
                raise HTTPException(409, "Neu transkribieren entfernt deine Markierungen")
            job_id = store.add_job("transcribe", interview, {"model": body.model})
        runner.notify()
        return {"job": job_id}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int) -> dict[str, bool]:
        return {"ok": runner.cancel(job_id)}

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: int) -> dict[str, int]:
        job = store.job(job_id)
        if job is None or job["status"] not in ("failed", "cancelled"):
            raise HTTPException(409, "job is not failed or cancelled")
        if job["kind"] == "transcribe" and _has_work(job["interview_id"]):
            # a transcription replaces the transcript and every position in it
            raise HTTPException(409, "Neu transkribieren entfernt deine Arbeit: bitte im "
                                     "Gespräch neu starten und bestätigen")
        new_id = store.add_job(job["kind"], job["interview_id"], job["options"])
        runner.notify()
        return {"job": new_id}

    @app.get("/api/projects/{pid}/compare")
    def compare(pid: int) -> dict[str, Any]:
        _project(pid)
        transcripts = data.transcripts(store.project_interviews(pid))
        guide, _ = data.guide(pid)
        states = {iid: _state_of(iid, t, guide) for iid, t in transcripts.items()}
        return {
            "guide": guide.to_dict() if guide else None,
            "interviews": list(transcripts),
            "cells": {iid: s["cells"] for iid, s in states.items()},
            "unassigned": {iid: s["unassigned"] for iid, s in states.items()},
            "stale": {iid: edits_stale(t, store.word_edits(iid))
                            for iid, t in transcripts.items()},
        }

    # ---------------------------------------------------------------- interviews
    @app.get("/api/interviews/{interview}")
    def interview(interview: str) -> dict[str, Any]:
        t = _transcript(interview)
        edits = store.word_edits(interview)
        original = edited_words(t, edits)  # {(turn, word): {orig, kind, tag, action}}
        guide = _guide_of(interview)
        state = _state_of(interview, t, guide)
        effective = apply_edits(t, edits)
        codes = {q.code for q in guide.questions} if guide else set()
        turns = []
        for ti, tu in enumerate(effective.turns):
            words = []
            for wi, w in enumerate(tu.words):
                item: dict[str, Any] = {"t": w.text, "s": w.start, "e": w.end,
                                        "p": round(w.prob, 2)}
                if (ti, wi) in original:
                    e = original[(ti, wi)]
                    item["o"], item["k"] = e["orig"], e["kind"]
                    if e["kind"] == "smoothing":
                        item["g"] = e["tag"]
                words.append(item)
            turns.append({"speaker": tu.speaker, "start": tu.start, "end": tu.end,
                          "words": words})
        return {
            "id": interview,
            "project": store.project_of(interview),
            "parts": [{"offset_s": p["offset_s"], "duration_s": p["duration_s"]}
                      for p in t.parts],
            "speakers": t.speakers,
            "turns": turns,
            "reviewed": store.reviewed(interview),
            "edits_stale": edits_stale(t, edits),
            "decisions": [{"guide_code": d["guide_code"], "reason": d["reason"],
                           "note": d["note"], "in_guide": d["guide_code"] in codes}
                          for d in store.decisions(interview)],
            "edits": [{k: e[k] for k in ("turn", "word", "action", "kind", "text", "tag")}
                      for e in edits],
            "questions": state["questions"],
            "links": [_with_passage(effective, lk) for lk in store.links(interview)],
            "cells": state["cells"],
        }

    @app.put("/api/interviews/{interview}/reviewed")
    def set_reviewed(interview: str, body: ReviewedUpdate) -> dict[str, bool]:
        _transcript(interview)
        with write_lock:
            _not_transcribing(interview)
            store.set_reviewed(interview, body.reviewed)
        return {"ok": True}

    @app.post("/api/interviews/{interview}/edits")
    def set_edit(interview: str, body: EditCreate) -> dict[str, int]:
        """Correction or smoothing of words. Replacing a span: the first word gets the text,
        the rest is deleted. Does not queue an analysis (the page shows "Analyse veraltet")."""
        project = _project(_interview_in_project(interview))
        t = _transcript(interview)
        _check_span(t, body, body.last)
        if body.kind == "correction":
            if body.action != "replace" or body.tag:
                raise HTTPException(422, "Korrektur: nur ersetzen, ohne Grund")
        elif body.tag not in project_tags(project["smoothing_tags"]):
            raise HTTPException(422, "Glättung: Grund aus den Projekt-Tags wählen")
        text = body.text.strip()
        if body.action == "replace" and not text:
            raise HTTPException(422, "Ersatztext fehlt")
        rows = []
        for w in range(body.first, body.last + 1):
            first_replaced = body.action == "replace" and w == body.first
            rows.append({"turn": body.turn, "word": w, "kind": body.kind, "tag": body.tag,
                         "action": "replace" if first_replaced else "delete",
                         "text": text if first_replaced else ""})
        with write_lock:
            _not_transcribing(interview)
            # a word carries one kind of edit: a smoothing is not silently replaced by a
            # correction (or the other way round); the same kind overwrites
            kinds = {(e["turn"], e["word"]): e["kind"] for e in store.word_edits(interview)}
            if any(kinds.get((body.turn, w), body.kind) != body.kind
                   for w in range(body.first, body.last + 1)):
                raise HTTPException(409, "Diese Stelle hat schon eine andere Änderung: "
                                         "erst zurücknehmen")
            store.set_word_edits(interview, rows)
        return {"ok": True, "edited": len(rows)}

    @app.post("/api/interviews/{interview}/edits/revert")
    def revert_edits(interview: str, body: WordRange) -> dict[str, bool]:
        _check_span(_transcript(interview), body, body.last)
        store.revert_word_edits(interview, body.turn, body.first, body.last)
        return {"ok": True}

    @app.post("/api/interviews/{interview}/analyze")
    def analyze_interview(interview: str) -> dict[str, int]:
        _transcript(interview)
        return {"queued": _queue_analysis([interview])}

    @app.put("/api/interviews/{interview}/questions/{code}/decision")
    def set_decision(interview: str, code: str, body: DecisionUpdate) -> dict[str, bool]:
        _transcript(interview)
        _check_code(code, _guide_of(interview))
        with write_lock:
            _not_transcribing(interview)
            if body.reason is None:
                store.delete_decision(interview, code)
            else:
                store.set_decision(interview, code, body.reason, body.note.strip())
        return {"ok": True}

    @app.get("/api/projects/{pid}/workflow")
    def workflow(pid: int) -> dict[str, Any]:
        _project(pid)
        ids = store.project_interviews(pid)
        transcripts = data.transcripts(ids)
        guide, _ = data.guide(pid)
        codes = [q.code for q in guide.questions] if guide else []
        extract_counts = Counter(r["interview"] for r in _extract_rows(pid) if r["in_guide"])
        rows = []
        for iid in ids:
            t = transcripts.get(iid)
            edits = store.word_edits(iid)
            cells: dict[str, str] = {}
            unassigned, stale = 0, False
            if t is not None:
                state = _state_of(iid, t, guide)
                cells = {code: cell["status"] for code, cell in state["cells"].items()}
                unassigned = len(state["unassigned"])
                stale = edits_stale(t, edits)
            rows.append({"id": iid, "transcribed": t is not None,
                         "reviewed": store.reviewed(iid), "edits": edits,
                         "edits_stale": stale, "cells": cells, "unassigned": unassigned,
                         "extracts": extract_counts[iid]})
        return workflow_state(codes, rows)

    @app.get("/api/projects/{pid}/extracts")
    def list_extracts(pid: int) -> dict[str, list[dict[str, Any]]]:
        _project(pid)
        return {"extracts": _extract_rows(pid)}

    @app.get("/api/projects/{pid}/extracts/export")
    def export_extracts(pid: int,
                        fmt: Literal["docx", "csv"] = Query(alias="format")) -> Response:
        """Generated in memory, nothing is written to disk."""
        _project(pid)
        guide, _ = data.guide(pid)
        titles = {q.code: q.text for q in guide.questions} if guide else {}
        rows = export.table(_extract_rows(pid), titles)
        if fmt == "csv":
            body, media = export.csv_bytes(rows), export.CSV_MIME
        else:
            body, media = export.docx_bytes(rows), export.DOCX_MIME
        return Response(body, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="extraktion-p{pid}.{fmt}"'})

    @app.post("/api/extracts")
    def create_extract(body: ExtractCreate) -> dict[str, int]:
        t = _transcript(body.interview)
        _check_span(t, body, body.last)
        _check_code(body.guide_code, _guide_of(body.interview))
        paraphrase = _paraphrase(body.paraphrase)
        with write_lock:
            _not_transcribing(body.interview)
            extract_id = store.add_extract(body.interview, body.guide_code, body.turn,
                                           body.first, body.last, paraphrase)
        return {"id": extract_id}

    @app.patch("/api/extracts/{extract_id}")
    def update_extract(extract_id: int, body: ExtractUpdate) -> dict[str, bool]:
        paraphrase = _paraphrase(body.paraphrase)
        with write_lock:
            extract = store.extract(extract_id)
            if extract is None:
                raise HTTPException(404, "unknown extract")
            _not_transcribing(extract["interview_id"])
            store.update_extract(extract_id, paraphrase)
        return {"ok": True}

    @app.delete("/api/extracts/{extract_id}")
    def delete_extract(extract_id: int) -> dict[str, bool]:
        with write_lock:
            extract = store.extract(extract_id)
            if extract is None:
                raise HTTPException(404, "unknown extract")
            _not_transcribing(extract["interview_id"])
            store.delete_extract(extract_id)
        return {"ok": True}

    @app.get("/api/interviews/{interview}/audio")
    def audio(interview: str) -> FileResponse:
        return audio_part(interview, 0)

    @app.get("/api/interviews/{interview}/audio/{part}")
    def audio_part(interview: str, part: int) -> FileResponse:
        """``part`` = position in playing order (0 = first recording)."""
        paths_ = store.part_paths(interview)
        if not 0 <= part < len(paths_) or not paths_[part].is_file():
            raise HTTPException(404, "no audio registered")
        return FileResponse(paths_[part])

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
        parts = store.parts(interview)
        shas = set()
        transcript = exports / f"{interview}.json"
        if transcript.is_file():
            shas.add(json.loads(transcript.read_text(encoding="utf-8"))["meta"]["audio"]["sha256"])
        known = [p["sha256"] for p in parts if p["sha256"]]
        if known:
            shas.add(combined_sha(known))
        for sha in shas:
            if not SHA256_HEX.match(sha):  # a crafted value like ".." must never reach rmtree
                continue
            cache = paths.cache / sha[:16]
            if cache.parent == paths.cache and cache.is_dir():
                shutil.rmtree(cache)
        if exports.is_dir() and exports.parent == paths.exports:
            shutil.rmtree(exports)
        for part in parts:
            _remove_upload(part["path"])
        store.delete_interview(interview)
        return {"ok": True}

    @app.post("/api/questions")
    def set_question(body: QuestionUpdate) -> dict[str, bool]:
        t = _transcript(body.interview)
        _check_span(t, body, body.last)
        _check_code(body.guide_code, _guide_of(body.interview))
        auto = {(q["turn"], q["first"]) for q in t.analysis.get("questions", [])}
        source = "auto" if (body.turn, body.first) in auto else "manual"
        with write_lock:
            _not_transcribing(body.interview)
            store.set_question(body.interview, body.turn, body.first, body.last, body.guide_code,
                               body.match, body.status, source)
        return {"ok": True}

    @app.post("/api/questions/reset")
    def reset_question(body: QuestionDelete) -> dict[str, bool]:
        _check_span(_transcript(body.interview), body)
        with write_lock:
            _not_transcribing(body.interview)
            store.delete_question(body.interview, body.turn, body.first)
        return {"ok": True}

    @app.post("/api/links")
    def create_link(body: LinkCreate) -> dict[str, int]:
        t = _transcript(body.interview)
        _check_span(t, body, body.last)
        _check_code(body.guide_code, _guide_of(body.interview))
        with write_lock:
            _not_transcribing(body.interview)
            link_id = store.set_link(body.interview, body.guide_code, body.turn, body.first,
                                     body.last, body.status, body.source, body.omitted,
                                     body.note)
        return {"id": link_id}

    @app.patch("/api/links/{link_id}")
    def update_link(link_id: int, body: LinkUpdate) -> dict[str, bool]:
        with write_lock:
            link = store.link(link_id)
            if link is None:
                raise HTTPException(404, "unknown link")
            _not_transcribing(link["interview_id"])
            store.update_link(link_id, body.omitted, body.note)
        return {"ok": True}

    @app.delete("/api/links/{link_id}")
    def delete_link(link_id: int) -> dict[str, bool]:
        with write_lock:
            link = store.link(link_id)
            if link is None:
                raise HTTPException(404, "unknown link")
            _not_transcribing(link["interview_id"])
            store.delete_link(link_id)
        return {"ok": True}

    return app
