"""Saved transcription settings, the global default and trial runs on an excerpt."""

import json
import sys

from fastapi.testclient import TestClient

from interis.config import Paths
from interis.web.app import create_app
from interis.web.jobs import JobRunner, settings_args, trial_file, trial_steps
from interis.web.store import Store

BASE = "http://127.0.0.1:8765"
H = {"X-Interis": "1"}


def _setup(tmp_path):
    paths = Paths(tmp_path)
    paths.ensure()
    c = TestClient(create_app(paths, "t", 8765), base_url=BASE)
    assert c.post("/api/login", json={"token": "t"}, headers=H).status_code == 200
    pid = c.post("/api/projects", json={"name": "P"}, headers=H).json()["id"]
    c.post(f"/api/projects/{pid}/interviews", json={"interview": "I01"}, headers=H)
    c.post("/api/interviews/I01/parts?ext=wav", content=b"RIFF0000", headers=H)
    return paths, c, Store(tmp_path / "interis.db")


def test_presets_and_the_default_used_by_a_new_transcription(tmp_path):
    _paths, c, store = _setup(tmp_path)
    assert c.get("/api/transcription/settings").json()["default"]["preset"] == "Standard"
    room = {"model": "whisper-large-v3-turbo", "room_mic": True, "speakers": 3,
            "min_duration_off": 0.5}
    pid = c.post("/api/transcription/presets", json={"name": "Raum", "settings": room},
                 headers=H).json()["id"]
    assert c.post("/api/transcription/presets", json={"name": "Raum", "settings": {}},
                  headers=H).status_code == 409
    assert c.post("/api/transcription/presets", json={"name": "X", "settings": {"beam_size": 99}},
                  headers=H).status_code == 422
    assert c.put("/api/transcription/default", json={"preset": pid}, headers=H).status_code == 200

    job = store.job(c.post("/api/interviews/I01/transcribe", json={}, headers=H).json()["job"])
    assert job["options"]["preset"] == "Raum" and job["options"]["room_mic"] is True
    args = settings_args(job["options"])
    assert args[args.index("--model") + 1] == "whisper-large-v3-turbo"
    assert args[args.index("--speakers") + 1] == "3" and "--room-mic" in args
    assert args[args.index("--min-duration-off") + 1] == "0.5"
    assert "--vad-threshold" not in args  # not set: the CLI's default
    assert "--dereverb" not in args and "--wpe-taps" not in args
    wpe = settings_args({"dereverb": True, "wpe_taps": 20})
    assert wpe[wpe.index("--wpe-taps") + 1] == "20" and wpe[wpe.index("--wpe-delay") + 1] == "3"

    c.delete(f"/api/transcription/presets/{pid}", headers=H)
    assert c.get("/api/transcription/settings").json()["default"]["preset"] == "Standard"


def test_trial_runs_on_an_excerpt_without_touching_the_interview(tmp_path):
    paths, c, store = _setup(tmp_path)
    r = c.post("/api/trials", json={"interview": "I01", "start": 60, "duration": 120,
                                    "settings": {"beam_size": 1}}, headers=H)
    job = store.job(r.json()["job"])
    assert job["kind"] == "trial" and job["interview_id"] == ""  # blocks no interview
    runner = JobRunner(paths, store, lambda _i: None, lambda _i: "")
    cmd = runner.command(job)
    assert cmd[:4] == [sys.executable, "-I", "-m", "interis.cli"]
    assert cmd[cmd.index("--start") + 1] == "60.0" and cmd[cmd.index("--duration") + 1] == "120.0"
    assert cmd[cmd.index("--out") + 1] == str(trial_file(paths, job["id"]))
    assert cmd[cmd.index("--beam-size") + 1] == "1" and "--guide" not in cmd
    assert cmd[cmd.index("--steps-dir") + 1] == str(trial_steps(paths, job["id"]))

    # the interview stays editable and shows no job while the trial waits
    detail = c.get("/api/projects/1").json()
    assert detail["interviews"][0]["job"] is None
    assert c.post("/api/trials", json={"interview": "I01", "duration": 5000, "settings": {}},
                  headers=H).status_code == 422
    assert c.post("/api/trials", json={"interview": "NOPE", "settings": {}},
                  headers=H).status_code == 404

    # a finished trial: its result is shown, and deleting removes file and cached steps
    sha = "a" * 64
    (paths.cache / sha[:16]).mkdir(parents=True)
    trial_file(paths, job["id"]).write_text(json.dumps({
        "meta": {"audio": {"sha256": sha, "duration_s": 120.0,
                           "clip": {"start_s": 60, "duration_s": 120.0}}},
        "speakers": [{"label": "SPEAKER_00", "role": "interviewer"}],
        "turns": [{"speaker": "SPEAKER_00", "start": 0.0, "end": 1.0,
                   "words": [{"text": " Hallo", "start": 0.0, "end": 1.0, "prob": 0.4}]}],
    }), encoding="utf-8")
    store.update_job(job["id"], status="done")
    listed = c.get("/api/trials?interview=I01").json()
    assert listed[0]["has_result"] and listed[0]["options"]["start"] == 60
    result = c.get(f"/api/trials/{job['id']}").json()
    assert result["turns"][0]["words"][0] == {"text": " Hallo", "start": 0.0, "prob": 0.4}
    assert result["speakers"] == [{"label": "SPEAKER_00", "role": "interviewer"}]
    steps = trial_steps(paths, job["id"])
    steps.mkdir()
    (steps / "01-original.wav").write_bytes(b"RIFF")
    (steps / "steps.json").write_text(json.dumps({"seconds": {"transcribe": 3.2}}),
                                      encoding="utf-8")
    assert c.get(f"/api/trials/{job['id']}").json()["steps"]["seconds"]["transcribe"] == 3.2
    assert c.get(f"/api/trials/{job['id']}/audio/01-original.wav").content == b"RIFF"
    assert c.get(f"/api/trials/{job['id']}/audio/steps.json").status_code == 404
    assert c.delete(f"/api/trials/{job['id']}", headers=H).status_code == 200
    assert not trial_file(paths, job["id"]).exists() and not (paths.cache / sha[:16]).exists()
    assert not steps.exists()
    assert c.get("/api/trials").json() == []


def test_deleting_the_interview_removes_its_trials(tmp_path):
    paths, c, store = _setup(tmp_path)
    job_id = c.post("/api/trials", json={"interview": "I01", "settings": {}},
                    headers=H).json()["job"]
    store.update_job(job_id, status="done")
    trial_file(paths, job_id).parent.mkdir(parents=True, exist_ok=True)
    trial_file(paths, job_id).write_text("{}", encoding="utf-8")
    assert c.delete("/api/interviews/I01", headers=H).status_code == 200
    assert not trial_file(paths, job_id).exists() and store.job(job_id) is None


def test_old_job_table_accepts_trials_after_the_upgrade(tmp_path):
    import sqlite3

    db = tmp_path / "interis.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK
            (kind IN ('transcribe', 'analyze', 'models')), interview_id TEXT NOT NULL,
            options TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL, stage TEXT NOT NULL
            DEFAULT '', progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
        INSERT INTO jobs (kind, interview_id, status, created_at)
            VALUES ('models', '', 'done', '2026-01-01');
    """)
    con.commit()
    con.close()
    store = Store(db)
    assert store.job(1)["kind"] == "models"
    assert store.job(store.add_job("trial", "", {}))["kind"] == "trial"
