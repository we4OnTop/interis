import json

from fastapi.testclient import TestClient

from interis.config import Paths, load_settings, resolve_paths, save_settings
from interis.web.app import create_app
from interis.web.jobs import JobRunner
from interis.web.store import Store
from interis.web.system import create_setup_app

BASE = "http://127.0.0.1:8765"
TOKEN = "test-token"  # noqa: S105 – fixed token for tests only
H = {"X-Interis": "1"}


def _login(app):
    c = TestClient(app, base_url=BASE)
    assert c.post("/api/login", json={"token": TOKEN}, headers=H).status_code == 200
    return c


def test_settings_file_relative_paths_and_resolution(tmp_path, monkeypatch):
    home = tmp_path / "Interis"
    home.mkdir()
    monkeypatch.setenv("INTERIS_HOME", str(home))
    monkeypatch.delenv("INTERIS_DATA_DIR", raising=False)
    monkeypatch.delenv("INTERIS_MODELS_DIR", raising=False)
    data, models = tmp_path / "data", tmp_path / "models"
    data.mkdir()
    models.mkdir()
    f = save_settings(data, models)
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert raw["data_dir"] == r"..\data" or raw["data_dir"] == "../data"  # same drive
    assert load_settings() == {"data_dir": data.resolve(), "models_dir": models.resolve()}
    paths = resolve_paths(None)
    assert paths.root == data.resolve() and paths.models == models.resolve()


def test_setup_app_only_offers_folder_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERIS_HOME", str(tmp_path))
    restarted = []
    c = _login(create_setup_app(TOKEN, 8765, lambda: restarted.append(1)))
    info = c.get("/api/app").json()
    assert info["mode"] == "setup" and info["desktop"] is True
    assert c.get("/api/projects").status_code == 404

    assert c.post("/api/app/check-folder/data", headers=H,
                  json={"path": "relativ"}).status_code == 422
    data = tmp_path / "daten"
    r = c.post("/api/app/folders", headers=H, json={"data_dir": str(data)})
    assert r.status_code == 409  # does not exist and create not requested
    r = c.post("/api/app/folders", headers=H,
               json={"data_dir": str(data), "models_dir": str(tmp_path / "m"), "create": True})
    assert r.json()["restart"] is True and data.is_dir()
    assert load_settings()["models_dir"] == (tmp_path / "m").resolve()


def test_setup_app_requires_login_and_csrf(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERIS_HOME", str(tmp_path))
    app = create_setup_app(TOKEN, 8765, None)
    c = TestClient(app, base_url=BASE)
    assert c.get("/api/app").status_code == 401
    c = _login(app)
    assert c.post("/api/app/folders", json={"data_dir": str(tmp_path)}).status_code == 403


def test_models_folder_detection_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERIS_HOME", str(tmp_path))
    # a data folder from another PC with models inside <folder>/models
    other = tmp_path / "other"
    key_dir = other / "models" / "e5-large"
    key_dir.mkdir(parents=True)
    (key_dir / "model.safetensors").write_bytes(b"w")
    from interis.models import MODELS

    lock = {"e5-large": {"revision": MODELS["e5-large"].revision,
                         "files": {"model.safetensors": "x"}}}
    (other / "models" / "models.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    c = _login(create_setup_app(TOKEN, 8765, None))
    r = c.post("/api/app/check-folder/models", headers=H, json={"path": str(other)}).json()
    assert r["ready"] == 1 and r["path"].endswith("models")
    status = {m["key"]: m["status"] for m in r["models"]}
    assert status["e5-large"] == "ready" and status["whisper-large-v3"] == "missing"


def test_main_app_reports_models_and_queues_download(tmp_path, monkeypatch):
    monkeypatch.setenv("INTERIS_HOME", str(tmp_path))
    paths = Paths(tmp_path / "data", tmp_path / "models")
    paths.root.mkdir()
    paths.ensure()
    c = _login(create_app(paths, TOKEN, 8765))
    info = c.get("/api/app").json()
    assert info["mode"] == "main" and info["models_linked"] is True
    assert all(m["status"] == "missing" for m in info["models"])
    assert c.post("/api/app/models/download", headers=H).status_code == 200
    assert c.post("/api/app/models/download", headers=H).status_code == 409
    assert c.get("/api/app").json()["models_job"]["kind"] == "models"


def test_model_download_job_is_the_only_online_command(tmp_path, monkeypatch):
    paths = Paths(tmp_path, tmp_path / "models")
    paths.ensure()
    store = Store(tmp_path / "interis.db")
    runner = JobRunner(paths, store, lambda _i: None, lambda _i: "")
    cmd = runner.command(store.job(store.add_job("models", "")))
    assert cmd[cmd.index("--models-dir") + 1] == str(tmp_path / "models")
    assert "setup-models" in cmd and "--allow-verified-mirror" in cmd


def test_old_jobs_table_is_migrated(tmp_path):
    import sqlite3

    db = tmp_path / "interis.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK (kind IN ('transcribe', 'analyze')),
            interview_id TEXT NOT NULL, options TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '',
            progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT)""")
        c.execute("INSERT INTO jobs (kind, interview_id, status, created_at) "
                  "VALUES ('analyze', 'X', 'done', 'now')")
    store = Store(db)
    store.add_job("models", "")
    assert [j["kind"] for j in store.jobs()] == ["analyze", "models"]
