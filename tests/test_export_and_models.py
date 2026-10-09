import json

import pytest
from docx import Document

from interis.config import Paths
from interis.export import fmt_time, write_docx, write_json, write_txt
from interis.models import MODELS, ModelError, _write_lock, hash_tree, verify_ready
from interis.pipeline.types import Transcript, Turn, Word


def _transcript() -> Transcript:
    turns = [
        Turn("SPEAKER_00", 0.0, 1.0, [Word(" Wie", 0, 0.4, 0.95), Word(" bitte?", 0.4, 1, 0.3)]),
        Turn("SPEAKER_01", 1.2, 2.0, [Word(" Gut.", 1.2, 2.0, 0.9, overlap=True)]),
    ]
    meta = {"interview_id": "I01", "note": "Raw machine transcript – not reviewed.",
            "created_at": "2026-10-06T00:00:00+00:00",
            "audio": {"sha256": "ab" * 32, "duration_s": 3725.0},
            "models": {"whisper-large-v3": {"repo": "openai/whisper-large-v3",
                                            "revision": "06f233fe06e7"}}}
    speakers = [{"label": "SPEAKER_00", "display_name": "SPEAKER_00"},
                {"label": "SPEAKER_01", "display_name": "SPEAKER_01"}]
    return Transcript(meta, speakers, turns)


def test_fmt_time():
    assert fmt_time(3725.9) == "01:02:05"


def test_json_roundtrip(tmp_path):
    t = _transcript()
    write_json(t, tmp_path / "t.json")
    back = Transcript.from_dict(json.loads((tmp_path / "t.json").read_text(encoding="utf-8")))
    assert back.turns[0].text == "Wie bitte?"
    assert back.turns[1].words[0].overlap is True


def test_txt_and_docx(tmp_path):
    t = _transcript()
    write_txt(t, tmp_path / "t.txt")
    assert "[00:00:00] SPEAKER_00: Wie bitte?" in (tmp_path / "t.txt").read_text(encoding="utf-8")
    write_docx(t, tmp_path / "t.docx")
    text = "\n".join(p.text for p in Document(str(tmp_path / "t.docx")).paragraphs)
    assert "SPEAKER_01: Gut." in text


def test_verify_ready_detects_tampering(tmp_path):
    paths = Paths(tmp_path)
    paths.ensure()
    key = "wav2vec2-german"
    model_dir = tmp_path / "models" / key
    model_dir.mkdir(parents=True)
    (model_dir / "model.safetensors").write_bytes(b"weights")
    _write_lock(paths, {key: {"revision": MODELS[key].revision, "files": hash_tree(model_dir)}})
    assert verify_ready(paths, key) == model_dir

    (model_dir / "model.safetensors").write_bytes(b"tampered")
    with pytest.raises(ModelError, match="integrity"):
        verify_ready(paths, key)

    (model_dir / "model.safetensors").write_bytes(b"weights")
    (model_dir / "extra.py").write_text("print('x')")
    with pytest.raises(ModelError, match="integrity"):
        verify_ready(paths, key)


def test_missing_model_reports_setup_hint(tmp_path):
    paths = Paths(tmp_path)
    paths.ensure()
    with pytest.raises(ModelError, match="setup-models"):
        verify_ready(paths, "whisper-large-v3")


def test_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    """An interrupted write must not leave a half-written transcript behind."""
    t = _transcript()
    path = tmp_path / "t.json"
    write_json(t, path)
    before = path.read_bytes()

    def interrupted(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(json, "dumps", interrupted)
    with pytest.raises(OSError):
        write_json(t, path)
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []
