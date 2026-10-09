"""Regression tests for the web-layer findings of the security audit."""

import io
import json
import zipfile

from fastapi.testclient import TestClient

from interis.config import Paths
from interis.web import app as web_app
from interis.web.app import create_app

BASE = "http://127.0.0.1:8765"
TOKEN = "test-token"  # noqa: S105 – fixed token for tests only
H = {"X-Interis": "1"}


def _client(tmp_path) -> TestClient:
    paths = Paths(tmp_path)
    paths.ensure()
    return TestClient(create_app(paths, TOKEN, 8765), base_url=BASE)


def _login(c: TestClient) -> None:
    assert c.post("/api/login", json={"token": TOKEN}, headers=H).status_code == 200


def test_non_ascii_session_cookie_is_refused_not_a_server_error(tmp_path):
    c = _client(tmp_path)
    # the header travels as latin-1 bytes, as the HTTP server decodes it
    r = c.get("/api/projects", headers={"cookie": b"interis_session=caf\xe9"})
    assert r.status_code == 401


def test_non_ascii_login_token_is_refused_not_a_server_error(tmp_path):
    c = _client(tmp_path)
    assert c.post("/api/login", json={"token": "café"}, headers=H).status_code == 401


def test_oversized_docx_is_refused_before_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "MAX_DOCX_UNPACKED", 1000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "a" * 5000)  # small compressed, large unpacked
    c = _client(tmp_path)
    _login(c)
    r = c.post("/api/guide/import-docx", content=buf.getvalue(), headers=H)
    assert r.status_code == 413


def test_delete_ignores_a_cache_key_that_is_not_a_sha256(tmp_path):
    # a transcript whose recorded audio hash is ".." must not make the delete reach the data root
    paths = Paths(tmp_path)
    paths.ensure()
    sentinel = tmp_path / "keep-me.txt"
    sentinel.write_text("data root", encoding="utf-8")
    (tmp_path / "exports" / "T1").mkdir(parents=True)
    (tmp_path / "exports" / "T1" / "T1.json").write_text(json.dumps({
        "meta": {"interview_id": "T1", "audio": {"sha256": "..", "duration_s": 1.0}},
        "speakers": [], "turns": [], "analysis": {}}), encoding="utf-8")
    c = TestClient(create_app(paths, TOKEN, 8765), base_url=BASE)
    _login(c)
    c.post("/api/projects", json={"name": "P"}, headers=H)
    c.post("/api/projects/1/interviews", json={"interview": "T1"}, headers=H)
    c.delete("/api/interviews/T1", headers=H)
    assert sentinel.read_text(encoding="utf-8") == "data root"


def test_retry_of_a_transcription_does_not_silently_replace_work(tmp_path):
    paths = Paths(tmp_path)
    paths.ensure()
    (tmp_path / "exports" / "T1").mkdir(parents=True)
    word = {"text": " Hallo", "start": 0.0, "end": 1.0, "prob": 0.9}
    (tmp_path / "exports" / "T1" / "T1.json").write_text(json.dumps({
        "meta": {"interview_id": "T1", "audio": {"sha256": "x", "duration_s": 1.0}},
        "speakers": [{"label": "A", "role": "unknown"}],
        "turns": [{"speaker": "A", "start": 0.0, "end": 1.0, "words": [word]}],
        "analysis": {}}), encoding="utf-8")
    c = TestClient(create_app(paths, TOKEN, 8765), base_url=BASE)
    _login(c)
    pid = c.post("/api/projects", json={"name": "P"}, headers=H).json()["id"]
    c.post(f"/api/projects/{pid}/interviews", json={"interview": "T1"}, headers=H)
    c.post("/api/interviews/T1/edits", json={"turn": 0, "first": 0, "last": 0,
                                             "action": "replace", "kind": "correction",
                                             "text": "Ja"}, headers=H)
    store = web_app.Store(tmp_path / "interis.db")
    job = store.job(store.add_job("transcribe", "T1", {"model": "whisper-large-v3"}))
    store.update_job(job["id"], status="failed")
    r = c.post(f"/api/jobs/{job['id']}/retry", headers=H)
    assert r.status_code == 409


def test_links_outside_the_transcript_are_ignored_not_fatal():
    # rows left behind by a transcript that was replaced must not turn the view into a 500
    from interis.analysis.guide import parse_guide
    from interis.pipeline.types import Transcript, Turn, Word
    from interis.web.review import interview_state

    t = Transcript(meta={}, speakers=[], turns=[Turn("A", 0.0, 1.0, [Word(" a", 0.0, 1.0, 0.9)])],
                   analysis={})
    stale = [{"id": 1, "guide_code": "F1", "turn": 5, "first": 0, "last": 3, "status": "confirmed",
              "omitted": False, "note": "", "source": "manual"}]
    state = interview_state(t, [], stale, parse_guide("- F1: Wie geht es Ihnen?"))
    assert state["cells"]["F1"]["status"] == "missing"
