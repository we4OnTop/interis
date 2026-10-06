"""Your review decisions, stored in ``<data>/interis.db`` (SQLite, stdlib only).

The machine analysis inside each transcript JSON is never modified. Decisions are layered
on top, keyed by *position* (interview, turn, first word, last word), which stays stable
when the analysis is re-run on the same transcript.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS interviews (
    id          TEXT PRIMARY KEY,
    audio_path  TEXT,
    added_at    TEXT NOT NULL
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
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

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
        with self._conn() as c:
            c.execute(
                "INSERT INTO interviews (id, audio_path, added_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET audio_path = excluded.audio_path",
                (interview_id, str(audio_path) if audio_path else None, _now()),
            )

    def audio_path(self, interview_id: str) -> Path | None:
        with self._conn() as c:
            row = c.execute("SELECT audio_path FROM interviews WHERE id = ?",
                            (interview_id,)).fetchone()
        return Path(row["audio_path"]) if row and row["audio_path"] else None

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

    def set_link(self, interview_id: str, guide_code: str, turn: int, first: int, last: int,
                 status: str, source: str, omitted: bool = False, note: str = "") -> int:
        with self._conn() as c:
            c.execute(
                "INSERT INTO answer_links (interview_id, guide_code, turn, first, last, status,"
                " source, omitted, note, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(interview_id, guide_code, turn, first, last) DO UPDATE SET "
                "status = excluded.status, omitted = excluded.omitted, note = excluded.note, "
                "updated_at = excluded.updated_at",
                (interview_id, guide_code, turn, first, last, status, source, int(omitted),
                 note, _now()),
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
