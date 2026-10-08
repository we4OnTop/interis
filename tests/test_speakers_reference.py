"""Speakers by reference: a checked start of the interview teaches the voices, the rest is
assigned by voice. Embeddings are faked: each speaker's "voice" is a direction."""

import json
import sys

import numpy as np
import pytest

from interis.analysis.sentences import split_sentences
from interis.analysis.speakers import reassign
from interis.pipeline.types import Transcript, Turn, Word

VOICE = {"A": np.array([1.0, 0.0, 0.1]), "B": np.array([0.0, 1.0, 0.1])}


def _transcript(spec):
    """spec: (diarized speaker, true speaker, start, text) per turn; 1 s per word."""
    turns, truth = [], {}
    for speaker, true, start, text in spec:
        words = [Word(f" {w}", start + i, start + i + 1, 0.9, speaker=speaker)
                 for i, w in enumerate(text.split())]
        turns.append(Turn(speaker, start, start + len(words), words))
        truth[(start, start + len(words))] = true
    return Transcript({}, [{"label": "A"}, {"label": "B"}], turns), truth


def _embed(truth):
    def embed(a, b):
        true = next(v for (s, e), v in truth.items() if s <= a and b <= e)
        return VOICE[true] + 0.05 * np.random.default_rng(int(a)).standard_normal(3)
    return embed


def _words_of(t):
    return lambda s: [(s.turn, i, t.turns[s.turn].words[i]) for i in range(s.first, s.last + 1)]


def test_later_sentences_go_to_the_voice_they_sound_like():
    t, truth = _transcript([
        ("A", "A", 0, "Wie geht es Ihnen heute?"),
        ("B", "B", 5, "Gut danke der Nachfrage."),
        # diarization got these wrong:
        ("B", "A", 20, "Und was machen Sie beruflich?"),
        ("A", "B", 25, "Ich arbeite im Vertrieb seit Jahren."),
        ("A", "A", 32, "Ja."),  # short: keeps its speaker
    ])
    changes, stats = reassign(split_sentences(t.turns), _words_of(t), _embed(truth), until=10,
                              min_s=1.5)
    moved = {(c["turn"], c["speaker"]) for c in changes}
    assert moved == {(2, "A"), (3, "B")}
    assert len(changes) == 5 + 6  # every word of both sentences
    assert stats == {"reference": 2, "checked": 2, "changed": 2, "unsure": 0, "short": 1}


def test_a_close_call_keeps_the_speaker_and_one_voice_is_not_enough():
    t, truth = _transcript([("A", "A", 0, "Wie geht es Ihnen heute?"),
                            ("B", "B", 5, "Gut danke der Nachfrage."),
                            ("B", "A", 20, "Und was machen Sie beruflich?")])
    sentences = split_sentences(t.turns)
    changes, stats = reassign(sentences, _words_of(t), _embed(truth), until=10, margin=2.0)
    assert changes == [] and stats["unsure"] == 1
    with pytest.raises(ValueError, match="two speakers"):
        reassign(sentences, _words_of(t), _embed(truth), until=4)


def test_cli_builds_the_timeline_and_writes_proposals(tmp_path, monkeypatch):
    from interis import cli
    from interis.analysis import roles
    from interis.models import sha256_file
    from interis.pipeline import run

    sr = 16000
    t, _ = _transcript([("A", "A", 0, "Wie geht es Ihnen heute?"),
                        ("B", "B", 5, "Gut danke der Nachfrage."),
                        ("B", "A", 20, "Und was machen Sie beruflich?")])
    # part 2 starts at 12 s: the voice is encoded in the audio level (A: 0.1, B: 0.2)
    level = {0: 0.1, 5: 0.2, 20: 0.1}
    parts_audio = [np.zeros(10 * sr, np.float32), np.zeros(20 * sr, np.float32)]
    for start, v in level.items():
        part, at = (0, start) if start < 12 else (1, start - 12)
        parts_audio[part][at * sr:(at + 5) * sr] = v
    files = []
    for i, x in enumerate(parts_audio):
        f = tmp_path / f"p{i}.wav"
        f.write_bytes(x.tobytes())
        files.append(f)
    t.meta = {"interview_id": "T1", "audio": {"duration_s": 32.0, "parts": [
        {"sha256": sha256_file(files[0]), "offset_s": 0.0},
        {"sha256": sha256_file(files[1]), "offset_s": 12.0}]}}
    src = tmp_path / "T1.json"
    src.write_text(json.dumps(t.to_dict()), encoding="utf-8")

    monkeypatch.setattr(run, "decode", lambda f: np.frombuffer(f.read_bytes(), np.float32))
    monkeypatch.setattr("interis.models.verify_ready", lambda *_a: tmp_path)
    monkeypatch.setattr(roles, "voice_embedder",
                        lambda _d: lambda x: np.array([1.0, 0.0]) if abs(x.mean() - 0.1) < 0.02
                        else np.array([0.0, 1.0]))
    out = tmp_path / "out.json"
    args = cli.build_parser().parse_args(["--data-dir", str(tmp_path), "speakers", str(src),
                                          "--audio", *map(str, files), "--until", "10",
                                          "--out", str(out)])
    from interis.config import Paths

    assert cli.cmd_speakers(args, Paths(tmp_path)) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert {c["speaker"] for c in result["changes"]} == {"A"} and len(result["changes"]) == 5
    # recordings that are not the transcript's are refused
    args.audio = [str(files[1]), str(files[0])]
    assert cli.cmd_speakers(args, Paths(tmp_path)) == 1


def test_api_job_and_results_layer_under_manual_corrections(tmp_path):
    from fastapi.testclient import TestClient

    from interis.config import Paths
    from interis.web.app import create_app
    from interis.web.jobs import JobRunner
    from interis.web.store import Store

    h = {"X-Interis": "1"}
    paths = Paths(tmp_path)
    paths.ensure()
    t, _ = _transcript([("A", "A", 0, "Wie geht es Ihnen heute?"),
                        ("B", "B", 5, "Gut danke der Nachfrage.")])
    t.meta = {"interview_id": "T1", "audio": {"duration_s": 10.0, "sha256": "x", "parts": []}}
    (tmp_path / "exports" / "T1").mkdir(parents=True)
    (tmp_path / "exports" / "T1" / "T1.json").write_text(json.dumps(t.to_dict()),
                                                          encoding="utf-8")
    c = TestClient(create_app(paths, "t", 8765), base_url="http://127.0.0.1:8765")
    c.post("/api/login", json={"token": "t"}, headers=h)
    c.post("/api/projects", json={"name": "P"}, headers=h)
    c.post("/api/projects/1/interviews", json={"interview": "T1"}, headers=h)
    store = Store(tmp_path / "interis.db")
    assert c.post("/api/interviews/T1/speakers/reference", json={"until": 60},
                  headers=h).status_code == 422  # no recording yet
    c.post("/api/interviews/T1/parts?ext=wav", content=b"RIFF0000", headers=h)
    r = c.post("/api/interviews/T1/speakers/reference", json={"until": 60}, headers=h)
    job = store.job(r.json()["job"])
    cmd = JobRunner(paths, store, lambda _i: None, lambda _i: "").command(job)
    assert cmd[:4] == [sys.executable, "-I", "-m", "interis.cli"]
    assert cmd[cmd.index("--until") + 1] == "60.0" and "--margin" in cmd
    store.update_job(job["id"], status="done")

    # a manual correction wins over the voice; the rest is marked as assigned by voice
    c.post("/api/interviews/T1/speakers", json={"turn": 1, "first": 0, "last": 0,
                                                "speaker": "A"}, headers=h)
    store.set_reference_speakers("T1", [{"turn": 1, "word": 0, "speaker": "B"},
                                        {"turn": 1, "word": 1, "speaker": "A"}])
    turn = c.get("/api/interviews/T1").json()["turns"][1]
    words = turn["words"]
    assert [w.get("so") for w in words] == [1, 2, None, None]
    assert [w.get("sp", turn["speaker"]) for w in words] == ["A", "A", "B", "B"]
    assert c.delete("/api/interviews/T1/speakers/reference", headers=h).status_code == 200
    assert [(s["word"], s["source"]) for s in store.speaker_edits("T1")] == [(0, "manual")]


def test_with_the_interviewers_voice_profile_no_reference_is_needed():
    from interis.analysis.speakers import voice_of

    spec = [("A", "A", 0, "Wie geht es Ihnen heute?")]
    start = 5
    for k in range(8):  # the interviewee speaks most; diarization got two of them wrong
        spec.append(("A" if k in (2, 5) else "B", "B", start, "Das ist eine längere Antwort."))
        start += 6
    spec.append(("B", "A", start, "Und was machen Sie beruflich?"))
    t, truth = _transcript(spec)
    sentences = split_sentences(t.turns)
    embed = _embed(truth)

    # learned from a completely corrected interview: here, the A sentences of this one
    t2, truth2 = _transcript([("A", "A", s, "Eine Frage von mir bitte.") for s in range(0, 60, 6)])
    profile = voice_of(split_sentences(t2.turns), _embed(truth2), "A")
    assert float(profile @ (VOICE["A"] / np.linalg.norm(VOICE["A"]))) > 0.95

    changes, stats = reassign(sentences, _words_of(t), embed, until=0, voice=profile,
                              labels=["A", "B"], interviewer="A")
    moved = {(c["turn"], c["speaker"]) for c in changes}
    assert moved == {(3, "B"), (6, "B"), (9, "A")} and stats["reference"] == 0
    with pytest.raises(ValueError, match="too few sentences"):
        voice_of(sentences[:2], embed, "A")


def test_learning_the_voice_profile_is_a_job_too(tmp_path):
    from interis.config import Paths
    from interis.web.jobs import JobRunner
    from interis.web.store import Store

    paths = Paths(tmp_path)
    paths.ensure()
    store = Store(tmp_path / "interis.db")
    store.add_interview("T1", store.create_project("P"))
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    store.add_part("T1", audio)
    (tmp_path / "exports" / "T1").mkdir(parents=True)
    (tmp_path / "exports" / "T1" / "T1.json").write_text("{}", encoding="utf-8")
    runner = JobRunner(paths, store, lambda _i: None, lambda _i: "")
    learn = runner.command(store.job(store.add_job("speakers", "T1", {"learn": "SPEAKER_01",
                                                                       "min_seconds": 1.0})))
    assert learn[learn.index("--save-voice") + 1] == "interviewer" and "--out" not in learn
    assert learn[learn.index("--speaker") + 1] == "SPEAKER_01"
    use = runner.command(store.job(store.add_job("speakers", "T1", {
        "until": 0.0, "margin": 0.1, "min_seconds": 1.0, "use_voice": True})))
    assert use[use.index("--voice") + 1] == "interviewer" and "--out" in use
