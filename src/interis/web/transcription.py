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
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from interis.config import Paths
from interis.models import ASR_MODELS
from interis.pipeline.evaluate import reference_from_transcript
from interis.pipeline.tune import Span, TuneError, snap_to_turns, suggest_span
from interis.pipeline.types import Transcript
from interis.web.edits import apply_edits
from interis.web.jobs import trial_file, trial_steps

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
STAGE_WAV = re.compile(r"^\d\d-[a-z-]+\.wav$")
MAX_TRIAL_S = 600


class TranscriptionSettings(BaseModel):
    model: str = Field(default="whisper-large-v3", max_length=60)
    compute_type: Literal["int8", "float32"] = "int8"
    beam_size: int = Field(default=5, ge=1, le=10)
    room_mic: bool = False
    vad_threshold: float | None = Field(default=None, ge=0.1, le=0.9)
    speakers: int = Field(default=2, ge=0, le=8)  # 0: detect the number
    min_duration_off: float | None = Field(default=None, ge=0.0, le=2.0)
    sentence_level: bool = False  # one speaker per sentence, see pipeline.merge
    dereverb: bool = False  # WPE, see interis.pipeline.dereverb
    wpe_taps: int = Field(default=10, ge=3, le=40)
    wpe_delay: int = Field(default=3, ge=1, le=8)
    wpe_iterations: int = Field(default=3, ge=1, le=10)
    # With a voice profile: each sentence goes to the voice it is clearly closer to
    # (cosine lead; None: off), see interis.analysis.speakers.assign_by_voice
    voice_margin: float | None = Field(default=None, ge=0.01, le=0.9)
    # Terms learned from your corrections (set by the automatic tuning); added to the
    # project's glossary for every transcription with these settings
    glossary: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list,
                                                                 max_length=100)

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


class TuneWindow(BaseModel):
    interview: str = Field(max_length=40)
    start: float = Field(ge=0.0, le=24 * 3600)
    end: float = Field(ge=0.0, le=24 * 3600)


class TuneBody(BaseModel):
    windows: list[TuneWindow] = Field(min_length=1, max_length=8)
    budget_minutes: float | None = Field(default=None, ge=1, le=24 * 60)


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
    steps = trial_steps(paths, job["id"])
    if steps.is_dir():
        shutil.rmtree(steps)
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
        steps = trial_steps(paths, job_id) / "steps.json"
        return {**_words(json.loads(out.read_text(encoding="utf-8"))),
                "steps": json.loads(steps.read_text(encoding="utf-8"))
                if steps.is_file() else None}

    @app.get("/api/trials/{job_id}/audio/{name}")
    def trial_audio(job_id: int, name: str) -> FileResponse:
        """One processing stage of a trial as WAV (names as in its steps.json)."""
        path = trial_steps(paths, job_id) / name
        if not STAGE_WAV.match(name) or not path.is_file():
            raise HTTPException(404, "no such stage")
        return FileResponse(path, media_type="audio/wav")

    @app.delete("/api/trials/{job_id}")
    def delete_trial(job_id: int) -> dict[str, bool]:
        job = store.job(job_id)
        if job is None or job["kind"] != "trial":
            raise HTTPException(404, "unknown trial")
        if job["status"] in ("queued", "running"):
            raise HTTPException(409, "Erst den Probelauf abbrechen")
        _remove_trial(paths, store, job)
        return {"ok": True}

    # ---------------------------------------------------------------- automatic tuning
    def _effective(iid: str) -> Transcript:
        """The transcript as you corrected it: the ground truth of the tuning."""
        interview_check(iid)
        src = paths.exports / iid / f"{iid}.json"
        if not src.is_file():
            raise HTTPException(422, f"{iid}: noch nicht transkribiert")
        raw = Transcript.from_dict(json.loads(src.read_text(encoding="utf-8")))
        return apply_edits(raw, store.word_edits(iid), store.speaker_edits(iid))

    def _describe(iid: str, t: Transcript, span: Span) -> dict[str, Any]:
        """What the stretch contains, so you can see what the tuning will measure against."""
        ref = reference_from_transcript(t, span.start, span.end)
        edits = [e for e in store.word_edits(iid) if span.first <= e["turn"] <= span.last]
        moved = [e for e in store.speaker_edits(iid) if span.first <= e["turn"] <= span.last]
        return {"interview": iid, "start": span.start, "end": span.end,
                "turns": span.last - span.first + 1, "words": len(ref.norm),
                "corrections": sum(e["kind"] == "correction" for e in edits),
                "speaker_corrections": len(moved), "reviewed": store.reviewed(iid),
                "begins": " ".join(ref.raw[:8]), "ends": " ".join(ref.raw[-8:])}

    def _span(iid: str, t: Transcript, start: float, end: float) -> Span:
        try:
            return snap_to_turns(t, start, end)
        except TuneError as e:
            raise HTTPException(422, f"{iid}: {e}") from e

    @app.get("/api/tuning/turns")
    def turns_for_picker(interview: str) -> dict[str, Any]:
        """The corrected transcript block by block (a block = one turn of a speaker, up to
        the next change of speaker), to pick the stretch to measure against."""
        t = _effective(interview)
        names = {sp["label"]: sp.get("display_name") or sp["label"] for sp in t.speakers}
        corrected = ({e["turn"] for e in store.word_edits(interview)
                      if e["kind"] == "correction"}
                     | {e["turn"] for e in store.speaker_edits(interview)})
        out = []
        for i, turn in enumerate(t.turns):
            words = [w for w in turn.words if w.text.strip()]
            if not words:
                continue
            text = "".join(w.text for w in words).strip()
            out.append({"i": i, "speaker": turn.speaker, "start": turn.start, "end": turn.end,
                        "words": len(words), "corrected": i in corrected,
                        "text": text if len(text) <= 700 else text[:700] + " …"})
        return {"speakers": [{"label": sp["label"], "name": names[sp["label"]],
                              "role": sp.get("role", "unknown")} for sp in t.speakers],
                "turns": out, "reviewed": store.reviewed(interview)}

    @app.post("/api/tuning/preview")
    def preview_window(body: TuneWindow) -> dict[str, Any]:
        """The stretch with its edges moved to whole speaker turns, and what it contains."""
        t = _effective(body.interview)
        return _describe(body.interview, t, _span(body.interview, t, body.start, body.end))

    @app.get("/api/tuning/suggest")
    def suggest_window(interview: str) -> dict[str, Any]:
        """The stretch you corrected: from the first to the last turn with a correction."""
        t = _effective(interview)
        corrected = sorted({e["turn"] for e in store.word_edits(interview)
                            if e["kind"] == "correction"}
                           | {e["turn"] for e in store.speaker_edits(interview)})
        try:
            span = suggest_span(t, corrected, store.reviewed(interview))
        except TuneError as e:
            raise HTTPException(422, f"{interview}: {e}") from e
        if span is None:
            raise HTTPException(422, f"{interview}: noch nichts korrigiert und „Korrektur "
                                     "abgeschlossen“ nicht gesetzt")
        return _describe(interview, t, span)

    @app.post("/api/tuning")
    def start_tuning(body: TuneBody) -> dict[str, int]:
        """Search the settings closest to what you corrected in these stretches."""
        if any(j["kind"] == "tune" and j["status"] in ("queued", "running")
               for j in store.jobs()):
            raise HTTPException(409, "Die Optimierung läuft schon")
        windows = []
        for w in body.windows:
            interview_check(w.interview)
            if not store.part_paths(w.interview):
                raise HTTPException(422, f"{w.interview}: noch keine Aufnahme hochgeladen")
            if not (store.reviewed(w.interview) or store.word_edits(w.interview)
                    or store.speaker_edits(w.interview)):
                raise HTTPException(
                    422, f"{w.interview}: noch nichts korrigiert – die Optimierung misst "
                         "gegen deinen korrigierten Text (oder „Korrektur abgeschlossen“)")
            t = _effective(w.interview)
            span = _span(w.interview, t, w.start, w.end)  # the stretch the job really uses
            windows.append({"interview": w.interview, "start": span.start, "end": span.end})
        job = store.add_job("tune", "", {"windows": windows,
                                         "budget_minutes": body.budget_minutes})
        runner.notify()
        return {"job": job}

    @app.get("/api/tuning")
    def tuning() -> dict[str, Any]:
        """The newest tuning job and the result of the last finished one."""
        jobs = [j for j in store.jobs() if j["kind"] == "tune"]
        last = paths.root / "tuning" / "last.json"
        report = None
        if last.is_file():
            try:
                full = json.loads(last.read_text(encoding="utf-8"))
                report = {k: full[k] for k in ("changed", "improved", "held_out", "windows",
                                               "baseline", "best", "evaluations", "stopped",
                                               "note")}
                report["glossary"] = len(full["glossary"])
            except (ValueError, KeyError):
                report = None
        return {"job": jobs[-1] if jobs else None, "report": report,
                "has_profile": (paths.voices / "interviewer.json").is_file()}
