"""Your review decisions, stored in ``<data>/interis.db`` (SQLite, stdlib only).

The machine analysis inside each transcript JSON is never modified. Decisions are layered
on top, keyed by *position* (interview, turn, first word, last word), which stays stable
when the analysis is re-run on the same transcript.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
-- A project = one interview guide + the interviews conducted with it.
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    hotwords    TEXT NOT NULL DEFAULT '',  -- names/terms that help the spelling
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interviews (
    id          TEXT PRIMARY KEY,
    audio_path  TEXT,
    added_at    TEXT NOT NULL
);
-- The recordings of an interview in playing order (several if there was a break).
CREATE TABLE IF NOT EXISTS audio_parts (
    interview_id TEXT NOT NULL,
    idx          INTEGER NOT NULL,
    path         TEXT NOT NULL,
    sha256       TEXT,
    PRIMARY KEY (interview_id, idx)
);
-- Transcriptions / re-analyses started from the website, run one at a time.
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL CHECK (kind IN ('transcribe', 'analyze', 'models', 'trial')),
    interview_id TEXT NOT NULL,
    options      TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed',
                                                 'cancelled')),
    stage        TEXT NOT NULL DEFAULT '',
    progress     REAL NOT NULL DEFAULT 0,
    message      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);
-- Corrections of detected questions, and questions you mark yourself.
CREATE TABLE IF NOT EXISTS question_marks (
    interview_id TEXT NOT NULL,
    turn         INTEGER NOT NULL,
    first        INTEGER NOT NULL,
    last         INTEGER NOT NULL,
    guide_code   TEXT,
    match        TEXT NOT NULL CHECK (match IN ('main', 'probe', 'followup')),
    status       TEXT NOT NULL CHECK (status IN ('confirmed', 'rejected')),
    source       TEXT NOT NULL CHECK (source IN ('auto', 'manual')),
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (interview_id, turn, first)
);
-- "This passage (also) answers guide question X."
CREATE TABLE IF NOT EXISTS answer_links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id TEXT NOT NULL,
    guide_code   TEXT NOT NULL,
    turn         INTEGER NOT NULL,
    first        INTEGER NOT NULL,
    last         INTEGER NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('confirmed', 'rejected')),
    source       TEXT NOT NULL CHECK (source IN ('manual', 'suggestion')),
    omitted      INTEGER NOT NULL DEFAULT 0,  -- question left out because already answered
    note         TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL,
    UNIQUE (interview_id, guide_code, turn, first, last)
);
-- Corrections (misrecognised words) and smoothing (Glättung), one row per word.
-- Word indices never move, so all other positions stay valid.
CREATE TABLE IF NOT EXISTS word_edits (
    interview_id TEXT NOT NULL,
    turn         INTEGER NOT NULL,
    word         INTEGER NOT NULL,
    action       TEXT NOT NULL CHECK (action IN ('replace', 'delete')),
    kind         TEXT NOT NULL CHECK (kind IN ('correction', 'smoothing')),
    text         TEXT NOT NULL DEFAULT '',
    tag          TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (interview_id, turn, word)
);
-- Speaker corrections: the word belongs to another speaker than diarization said.
CREATE TABLE IF NOT EXISTS speaker_edits (
    interview_id TEXT NOT NULL,
    turn         INTEGER NOT NULL,
    word         INTEGER NOT NULL,
    speaker      TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (interview_id, turn, word)
);
-- Extraction: a passage of an answer, summarised in your own words for a guide question.
CREATE TABLE IF NOT EXISTS extracts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    interview_id TEXT NOT NULL,
    guide_code   TEXT NOT NULL,
    turn         INTEGER NOT NULL,
    first        INTEGER NOT NULL,
    last         INTEGER NOT NULL,
    paraphrase   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);
-- Why a guide question has no answer in an interview, when no passage answers it.
CREATE TABLE IF NOT EXISTS question_decisions (
    interview_id TEXT NOT NULL,
    guide_code   TEXT NOT NULL,
    reason       TEXT NOT NULL CHECK (reason IN ('not_asked', 'not_relevant', 'other')),
    note         TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (interview_id, guide_code)
);
-- Saved transcription settings ("Einstellungen"), for all projects. At most one is the
-- default; without one, the built-in settings are used.
CREATE TABLE IF NOT EXISTS asr_presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    options     TEXT NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0
);
"""


# Tables whose rows refer to word positions of one interview.
DECISION_TABLES = ("question_marks", "answer_links", "word_edits", "speaker_edits",
                   "extracts", "question_decisions")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)
            sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'jobs'").fetchone()
            if sql and "'trial'" not in sql["sql"]:  # databases from before trial runs
                c.execute("ALTER TABLE jobs RENAME TO jobs_old")
                c.executescript(SCHEMA)
                c.execute("INSERT INTO jobs SELECT * FROM jobs_old")
                c.execute("DROP TABLE jobs_old")
            cols = {r["name"] for r in c.execute("PRAGMA table_info(interviews)")}
            if "project_id" not in cols:  # databases from before projects existed
                c.execute("ALTER TABLE interviews ADD COLUMN project_id INTEGER "
                          "REFERENCES projects(id)")
            if "reviewed_at" not in cols:  # transcript check ("Korrektur abgeschlossen")
                c.execute("ALTER TABLE interviews ADD COLUMN reviewed_at TEXT")
            pcols = {r["name"] for r in c.execute("PRAGMA table_info(projects)")}
            if "smoothing_tags" not in pcols:  # one tag per line, empty = defaults
                c.execute("ALTER TABLE projects ADD COLUMN smoothing_tags TEXT NOT NULL "
                          "DEFAULT ''")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commits or rolls back
                yield conn
        finally:
            conn.close()

    # ---------------------------------------------------------------- interviews
    def register_interview(self, interview_id: str, audio_path: Path | None) -> None:
        self.register_parts(interview_id, [audio_path] if audio_path else [])

    def add_interview(self, interview_id: str, project_id: int,
                      audio_path: Path | None = None) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO interviews (id, added_at, project_id) VALUES (?, ?, ?)",
                      (interview_id, _now(), project_id))
        if audio_path is not None:
            self.add_part(interview_id, audio_path)

    # ---------------------------------------------------------------- recording parts
    def parts(self, interview_id: str) -> list[dict[str, Any]]:
        """[{idx, path, sha256}] in playing order (legacy single audio_path included)."""
        with self._conn() as c:
            rows = c.execute("SELECT idx, path, sha256 FROM audio_parts WHERE interview_id = ? "
                             "ORDER BY idx", (interview_id,)).fetchall()
            if not rows:
                row = c.execute("SELECT audio_path FROM interviews WHERE id = ?",
                                (interview_id,)).fetchone()
                if row and row["audio_path"]:
                    return [{"idx": 0, "path": Path(row["audio_path"]), "sha256": None}]
        return [{"idx": r["idx"], "path": Path(r["path"]), "sha256": r["sha256"]} for r in rows]

    def part_paths(self, interview_id: str) -> list[Path]:
        return [p["path"] for p in self.parts(interview_id)]

    def add_part(self, interview_id: str, path: Path, sha256: str | None = None) -> int:
        with self._conn() as c:
            row = c.execute("SELECT COALESCE(MAX(idx) + 1, 0) AS n FROM audio_parts "
                            "WHERE interview_id = ?", (interview_id,)).fetchone()
            c.execute("INSERT INTO audio_parts VALUES (?, ?, ?, ?)",
                      (interview_id, row["n"], str(path), sha256))
        return int(row["n"])

    def set_parts(self, interview_id: str, parts: list[tuple[Path, str | None]]) -> None:
        """Replace the parts (new order / removed part)."""
        with self._conn() as c:
            c.execute("DELETE FROM audio_parts WHERE interview_id = ?", (interview_id,))
            c.executemany("INSERT INTO audio_parts VALUES (?, ?, ?, ?)",
                          [(interview_id, i, str(p), sha) for i, (p, sha) in enumerate(parts)])

    def register_parts(self, interview_id: str, paths: list[Path]) -> None:
        """Command line: the interview was transcribed from these files."""
        with self._conn() as c:
            c.execute("INSERT INTO interviews (id, added_at) VALUES (?, ?) "
                      "ON CONFLICT(id) DO NOTHING", (interview_id, _now()))
        self.set_parts(interview_id, [(p, None) for p in paths])

    def interview_ids(self) -> set[str]:
        with self._conn() as c:
            return {r["id"] for r in c.execute("SELECT id FROM interviews")}

    def project_of(self, interview_id: str) -> int | None:
        with self._conn() as c:
            row = c.execute("SELECT project_id FROM interviews WHERE id = ?",
                            (interview_id,)).fetchone()
        return row["project_id"] if row else None

    def project_interviews(self, project_id: int) -> list[str]:
        with self._conn() as c:
            rows = c.execute("SELECT id FROM interviews WHERE project_id = ? ORDER BY id",
                             (project_id,)).fetchall()
        return [r["id"] for r in rows]

    def assign_project(self, interview_ids: list[str], project_id: int) -> None:
        with self._conn() as c:
            for iid in interview_ids:
                c.execute(
                    "INSERT INTO interviews (id, added_at, project_id) VALUES (?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET project_id = excluded.project_id",
                    (iid, _now(), project_id))

    def audio_path(self, interview_id: str) -> Path | None:
        """First recording part (kept for single-file callers)."""
        paths = self.part_paths(interview_id)
        return paths[0] if paths else None

    # ---------------------------------------------------------------- questions
    def question_marks(self, interview_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM question_marks WHERE interview_id = ?",
                             (interview_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_question(self, interview_id: str, turn: int, first: int, last: int,
                     guide_code: str | None, match: str, status: str, source: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO question_marks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(interview_id, turn, first) DO UPDATE SET last = excluded.last, "
                "guide_code = excluded.guide_code, match = excluded.match, "
                "status = excluded.status, updated_at = excluded.updated_at",
                (interview_id, turn, first, last, guide_code, match, status, source, _now()),
            )

    def delete_question(self, interview_id: str, turn: int, first: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM question_marks WHERE interview_id = ? AND turn = ? "
                      "AND first = ?", (interview_id, turn, first))

    # ---------------------------------------------------------------- answer links
    def links(self, interview_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as c:
            if interview_id is None:
                rows = c.execute("SELECT * FROM answer_links").fetchall()
            else:
                rows = c.execute("SELECT * FROM answer_links WHERE interview_id = ?",
                                 (interview_id,)).fetchall()
        return [{**dict(r), "omitted": bool(r["omitted"])} for r in rows]

    def link(self, link_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM answer_links WHERE id = ?", (link_id,)).fetchone()
        return {**dict(row), "omitted": bool(row["omitted"])} if row else None

    def set_link(self, interview_id: str, guide_code: str, turn: int, first: int, last: int,
                 status: str, source: str, omitted: bool | None = None,
                 note: str | None = None) -> int:
        """Create or update a link. ``omitted`` and ``note`` that are None keep the stored
        values of an existing link."""
        flag = None if omitted is None else int(omitted)
        with self._conn() as c:
            c.execute(
                "INSERT INTO answer_links (interview_id, guide_code, turn, first, last, status,"
                " source, omitted, note, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, 0), COALESCE(?, ''), ?) "
                "ON CONFLICT(interview_id, guide_code, turn, first, last) DO UPDATE SET "
                "status = excluded.status, omitted = COALESCE(?, answer_links.omitted), "
                "note = COALESCE(?, answer_links.note), updated_at = excluded.updated_at",
                (interview_id, guide_code, turn, first, last, status, source, flag, note,
                 _now(), flag, note),
            )
            row = c.execute(
                "SELECT id FROM answer_links WHERE interview_id = ? AND guide_code = ? AND "
                "turn = ? AND first = ? AND last = ?",
                (interview_id, guide_code, turn, first, last)).fetchone()
        return int(row["id"])

    def update_link(self, link_id: int, omitted: bool | None, note: str | None) -> None:
        with self._conn() as c:
            if omitted is not None:
                c.execute("UPDATE answer_links SET omitted = ?, updated_at = ? WHERE id = ?",
                          (int(omitted), _now(), link_id))
            if note is not None:
                c.execute("UPDATE answer_links SET note = ?, updated_at = ? WHERE id = ?",
                          (note, _now(), link_id))

    def delete_link(self, link_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM answer_links WHERE id = ?", (link_id,))

    # ---------------------------------------------------------------- transcript edits
    def word_edits(self, interview_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM word_edits WHERE interview_id = ? "
                             "ORDER BY turn, word", (interview_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_word_edits(self, interview_id: str, rows: list[dict[str, Any]]) -> None:
        """Insert or replace the edits of single words (one row per word)."""
        now = _now()
        with self._conn() as c:
            c.executemany(
                "INSERT INTO word_edits (interview_id, turn, word, action, kind, text, tag, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(interview_id, turn, word) DO UPDATE SET action = excluded.action, "
                "kind = excluded.kind, text = excluded.text, tag = excluded.tag, "
                "updated_at = excluded.updated_at",
                [(interview_id, r["turn"], r["word"], r["action"], r["kind"], r["text"],
                  r["tag"], now) for r in rows])

    def revert_word_edits(self, interview_id: str, turn: int, first: int, last: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM word_edits WHERE interview_id = ? AND turn = ? "
                      "AND word BETWEEN ? AND ?", (interview_id, turn, first, last))

    def speaker_edits(self, interview_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT turn, word, speaker FROM speaker_edits WHERE interview_id = ? "
                             "ORDER BY turn, word", (interview_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_speakers(self, interview_id: str, turn: int, words: dict[int, str | None]) -> None:
        """{word index: speaker}; ``None`` removes the correction (diarization's speaker)."""
        now = _now()
        with self._conn() as c:
            for word, speaker in words.items():
                if speaker is None:
                    c.execute("DELETE FROM speaker_edits WHERE interview_id = ? AND turn = ? "
                              "AND word = ?", (interview_id, turn, word))
                else:
                    c.execute("INSERT INTO speaker_edits (interview_id, turn, word, speaker, "
                              "updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(interview_id, "
                              "turn, word) DO UPDATE SET speaker = excluded.speaker, "
                              "updated_at = excluded.updated_at",
                              (interview_id, turn, word, speaker, now))

    def reviewed(self, interview_id: str) -> bool:
        with self._conn() as c:
            row = c.execute("SELECT reviewed_at FROM interviews WHERE id = ?",
                            (interview_id,)).fetchone()
        return bool(row and row["reviewed_at"])

    def set_reviewed(self, interview_id: str, reviewed: bool) -> None:
        with self._conn() as c:
            c.execute("UPDATE interviews SET reviewed_at = ? WHERE id = ?",
                      (_now() if reviewed else None, interview_id))

    # ---------------------------------------------------------------- extracts
    def extracts(self, interview_ids: list[str]) -> list[dict[str, Any]]:
        if not interview_ids:
            return []
        marks = ",".join("?" * len(interview_ids))
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM extracts WHERE interview_id IN ({marks}) "  # noqa: S608 – "?" only
                "ORDER BY interview_id, turn, first", interview_ids).fetchall()
        return [dict(r) for r in rows]

    def extract(self, extract_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM extracts WHERE id = ?", (extract_id,)).fetchone()
        return dict(row) if row else None

    def add_extract(self, interview_id: str, guide_code: str, turn: int, first: int,
                    last: int, paraphrase: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO extracts (interview_id, guide_code, turn, first, last, paraphrase, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (interview_id, guide_code, turn, first, last, paraphrase, _now()))
        return int(cur.lastrowid)

    def update_extract(self, extract_id: int, paraphrase: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE extracts SET paraphrase = ?, updated_at = ? WHERE id = ?",
                      (paraphrase, _now(), extract_id))

    def delete_extract(self, extract_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM extracts WHERE id = ?", (extract_id,))

    # ---------------------------------------------------------------- question decisions
    def decisions(self, interview_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM question_decisions WHERE interview_id = ?",
                             (interview_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_decision(self, interview_id: str, guide_code: str, reason: str, note: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO question_decisions (interview_id, guide_code, reason, note, "
                "updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(interview_id, guide_code) DO UPDATE SET reason = excluded.reason, "
                "note = excluded.note, updated_at = excluded.updated_at",
                (interview_id, guide_code, reason, note, _now()))

    def delete_decision(self, interview_id: str, guide_code: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM question_decisions WHERE interview_id = ? AND guide_code = ?",
                      (interview_id, guide_code))

    # ---------------------------------------------------------------- projects
    def create_project(self, name: str, hotwords: str = "") -> int:
        with self._conn() as c:
            cur = c.execute("INSERT INTO projects (name, hotwords, created_at) VALUES (?, ?, ?)",
                            (name, hotwords, _now()))
        return int(cur.lastrowid)

    def projects(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def project(self, project_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def update_project(self, project_id: int, name: str | None, hotwords: str | None,
                       smoothing_tags: str | None = None) -> None:
        with self._conn() as c:
            if name is not None:
                c.execute("UPDATE projects SET name = ? WHERE id = ?", (name, project_id))
            if hotwords is not None:
                c.execute("UPDATE projects SET hotwords = ? WHERE id = ?",
                          (hotwords, project_id))
            if smoothing_tags is not None:
                c.execute("UPDATE projects SET smoothing_tags = ? WHERE id = ?",
                          (smoothing_tags, project_id))

    # ---------------------------------------------------------------- jobs
    def add_job(self, kind: str, interview_id: str, options: dict[str, Any] | None = None,
                ) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO jobs (kind, interview_id, options, status, created_at) "
                "VALUES (?, ?, ?, 'queued', ?)",
                (kind, interview_id, json.dumps(options or {}), _now()))
        return int(cur.lastrowid)

    def jobs(self, interview_ids: list[str] | None = None) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        out = [{**dict(r), "options": json.loads(r["options"])} for r in rows]
        if interview_ids is not None:
            wanted = set(interview_ids)
            out = [j for j in out if j["interview_id"] in wanted]
        return out

    def job(self, job_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return {**dict(row), "options": json.loads(row["options"])} if row else None

    def next_queued_job(self) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY id "
                            "LIMIT 1").fetchone()
        return self.job(row["id"]) if row else None

    def update_job(self, job_id: int, **fields: Any) -> None:
        allowed = {"status", "stage", "progress", "message", "started_at", "finished_at"}
        assert set(fields) <= allowed, fields
        if fields.get("status") == "running":
            fields.setdefault("started_at", _now())
        if fields.get("status") in ("done", "failed", "cancelled"):
            fields.setdefault("finished_at", _now())
        cols = ", ".join(f"{k} = ?" for k in fields)  # keys checked against the allow-list
        with self._conn() as c:
            c.execute(f"UPDATE jobs SET {cols} WHERE id = ?",  # noqa: S608
                      (*fields.values(), job_id))

    def delete_job(self, job_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    # ---------------------------------------------------------------- settings
    def presets(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM asr_presets ORDER BY name").fetchall()
        return [{"id": r["id"], "name": r["name"], "options": json.loads(r["options"]),
                 "is_default": bool(r["is_default"])} for r in rows]

    def save_preset(self, name: str, options: dict[str, Any], preset_id: int | None = None,
                    ) -> int:
        """New preset, or replace name and options of ``preset_id``. Raises
        sqlite3.IntegrityError if the name is taken."""
        with self._conn() as c:
            if preset_id is None:
                cur = c.execute("INSERT INTO asr_presets (name, options) VALUES (?, ?)",
                                (name, json.dumps(options)))
                return int(cur.lastrowid)
            c.execute("UPDATE asr_presets SET name = ?, options = ? WHERE id = ?",
                      (name, json.dumps(options), preset_id))
        return preset_id

    def delete_preset(self, preset_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM asr_presets WHERE id = ?", (preset_id,))

    def set_default_preset(self, preset_id: int | None) -> None:
        """``None``: the built-in settings are the default again."""
        with self._conn() as c:
            c.execute("UPDATE asr_presets SET is_default = (id IS ?)", (preset_id,))

    def requeue_interrupted_jobs(self) -> None:
        """Jobs that were running when the server stopped continue (their finished steps
        are cached, so little work is repeated)."""
        with self._conn() as c:
            c.execute("UPDATE jobs SET status = 'queued', stage = '', progress = 0 "
                      "WHERE status = 'running'")

    def delete_decisions(self, interview_id: str) -> None:
        """Everything tied to word positions. Needed after a new transcription."""
        with self._conn() as c:
            for table in DECISION_TABLES:
                c.execute(f"DELETE FROM {table} WHERE interview_id = ?",  # noqa: S608 – constants
                          (interview_id,))
            c.execute("UPDATE interviews SET reviewed_at = NULL WHERE id = ?", (interview_id,))

    def delete_interview(self, interview_id: str) -> None:
        """Remove all review decisions and jobs of an interview (files: see the caller)."""
        with self._conn() as c:
            for table, col in ((*((t, "interview_id") for t in DECISION_TABLES),
                                ("audio_parts", "interview_id"), ("jobs", "interview_id"),
                                ("interviews", "id"))):
                c.execute(f"DELETE FROM {table} WHERE {col} = ?",  # noqa: S608 – constants
                          (interview_id,))
