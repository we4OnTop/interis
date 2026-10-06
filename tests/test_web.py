import json

import pytest
from fastapi.testclient import TestClient

from interis.analysis.analyze import AnalysisOptions, analyze
from interis.analysis.guide import parse_guide
from interis.config import Paths
from interis.web.app import create_app
from interis.web.store import Store
from tests.test_analysis import FakeEncoder, _interview

GUIDE = ("- F1: Wie sieht Ihr Arbeitsalltag aus?\n- F2: Welche Rolle spielt KI?\n"
         "- F3: Wie gehen Sie mit vertraulichen Daten um?\n- F4: Was wünschen Sie sich?\n")
BASE = "http://127.0.0.1:8765"
TOKEN = "test-token"  # noqa: S105 – fixed token for tests only
H = {"X-Interis": "1"}


@pytest.fixture
def data_dir(tmp_path):
    paths = Paths(tmp_path)
    paths.ensure()
    (tmp_path / "leitfaden.md").write_text(GUIDE, encoding="utf-8")
    t = _interview()
    t.meta.update({"interview_id": "T1", "audio": {"duration_s": 30.0, "sha256": "x"}})
    t.analysis = analyze(t, AnalysisOptions(guide=parse_guide(GUIDE), match_threshold=0.9,
                                            answer_z=0.5), None, FakeEncoder)
    (tmp_path / "exports" / "T1").mkdir(parents=True)
    (tmp_path / "exports" / "T1" / "T1.json").write_text(json.dumps(t.to_dict()),
                                                          encoding="utf-8")
    return paths


@pytest.fixture
def client(data_dir):
    c = TestClient(create_app(data_dir, TOKEN, 8765), base_url=BASE)
    assert c.post("/api/login", json={"token": TOKEN}, headers=H).status_code == 200
    return c


# ------------------------------------------------------------------ security

def test_foreign_host_header_is_rejected(data_dir):
    c = TestClient(create_app(data_dir, TOKEN, 8765), base_url="http://evil.example")
    assert c.get("/").status_code == 400


def test_api_requires_login(data_dir):
    c = TestClient(create_app(data_dir, TOKEN, 8765), base_url=BASE)
    assert c.get("/api/overview").status_code == 401
    assert c.post("/api/login", json={"token": "wrong"}, headers=H).status_code == 401
    assert c.get("/api/overview").status_code == 401


def test_session_cookie_is_httponly_and_strict(data_dir):
    c = TestClient(create_app(data_dir, TOKEN, 8765), base_url=BASE)
    r = c.post("/api/login", json={"token": TOKEN}, headers=H)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_state_change_needs_custom_header_and_same_origin(client):
    body = {"interview": "T1", "turn": 3, "first": 0, "last": 2, "guide_code": "F3"}
    assert client.post("/api/links", json=body).status_code == 403
    assert client.post("/api/links", json=body,
                       headers={**H, "Origin": "http://evil.example"}).status_code == 403
    assert client.post("/api/links", json=body,
                       headers={**H, "Origin": BASE}).status_code == 200


def test_security_headers_and_no_api_docs(client):
    r = client.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_input_validation(client):
    bad_turn = {"interview": "T1", "turn": 99, "first": 0, "last": 0, "guide_code": "F1"}
    assert client.post("/api/links", json=bad_turn, headers=H).status_code == 422
    bad_code = {"interview": "T1", "turn": 1, "first": 0, "last": 0, "guide_code": "X9"}
    assert client.post("/api/links", json=bad_code, headers=H).status_code == 422
    assert client.get("/api/interviews/nope").status_code == 404


# ------------------------------------------------------------------ review logic

def _cell(client, code):
    return client.get("/api/compare").json()["cells"]["T1"][code]


def test_compare_shows_asked_questions_with_dialogue(client):
    c = _cell(client, "F2")
    assert c["status"] == "asked"
    turns = c["exchanges"][0]["dialogue"]
    assert turns[0]["role"] == "interviewer" and turns[1]["role"] == "interviewee"
    assert any(p.get("question") and p["code"] == "F2" for p in turns[0]["pieces"])


def test_link_answer_to_unasked_question_marks_it_omitted(client):
    assert _cell(client, "F4")["status"] == "missing"
    r = client.post("/api/links", headers=H, json={
        "interview": "T1", "turn": 1, "first": 0, "last": 2, "guide_code": "F4",
        "omitted": True})
    c = _cell(client, "F4")
    assert c["status"] == "omitted"
    link = c["links"][0]
    assert link["type"] == "unasked" and link["from_code"] == "F1"

    client.patch(f"/api/links/{r.json()['id']}", headers=H, json={"omitted": False})
    assert _cell(client, "F4")["status"] == "answered_elsewhere"
    client.delete(f"/api/links/{r.json()['id']}", headers=H)
    assert _cell(client, "F4")["status"] == "missing"


def test_rejecting_a_suggestion_hides_it(client):
    sug = _cell(client, "F3")["suggestions"]
    assert sug, "fixture should produce a suggestion for F3"
    s = sug[0]
    client.post("/api/links", headers=H, json={
        "interview": "T1", "turn": s["turn"], "first": s["first"], "last": s["last"],
        "guide_code": "F3", "status": "rejected", "source": "suggestion"})
    assert not _cell(client, "F3")["suggestions"]


def test_reassigning_a_question(client):
    q = next(q for q in client.get("/api/interviews/T1").json()["questions"]
             if q["guide_code"] == "F2")
    client.post("/api/questions", headers=H, json={
        "interview": "T1", "turn": q["turn"], "first": q["first"], "last": q["last"],
        "guide_code": "F4", "match": "main"})
    assert _cell(client, "F2")["status"] == "missing"
    assert _cell(client, "F4")["status"] == "asked"

    client.post("/api/questions/reset", headers=H,
                json={"interview": "T1", "turn": q["turn"], "first": q["first"]})
    assert _cell(client, "F2")["status"] == "asked"


def test_rejecting_a_question(client):
    q = client.get("/api/interviews/T1").json()["questions"][0]
    client.post("/api/questions", headers=H, json={
        "interview": "T1", "turn": q["turn"], "first": q["first"], "last": q["last"],
        "match": "followup", "status": "rejected"})
    ids = [(x["turn"], x["first"]) for x in client.get("/api/interviews/T1").json()["questions"]]
    assert (q["turn"], q["first"]) not in ids


def test_audio_streaming_with_range(client, data_dir, tmp_path):
    assert client.get("/api/interviews/T1/audio").status_code == 404
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF" + bytes(1000))
    Store(data_dir.root / "interis.db").register_interview("T1", audio)
    r = client.get("/api/interviews/T1/audio", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10
