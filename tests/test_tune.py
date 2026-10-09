import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from interis import cli
from interis.config import Paths
from interis.models import sha256_file
from interis.pipeline import tune as tune_mod
from interis.pipeline.evaluate import reference_from_transcript
from interis.pipeline.tune import (
    TuneError,
    Window,
    coordinate_descent,
    merge_hotwords,
    pipeline_options,
    snap_to_turns,
    split_windows,
    suggest_span,
    tune,
)
from interis.pipeline.types import Transcript, Turn, Word
from interis.web.app import create_app
from interis.web.jobs import JobRunner
from interis.web.store import Store

BASE = "http://127.0.0.1:8765"
H = {"X-Interis": "1"}
TEXT_Q = "wie nutzen sie Kubernetes in Ihrem Alltag heute eigentlich"
TEXT_A = "wir nutzen es seit zwei Jahren und sind damit sehr zufrieden"


def _transcript(q=TEXT_Q, a=TEXT_A, second="B", reps=5):
    """reps x (question by A, answer by B), 1 s per word."""
    turns, clock = [], 0.0
    for _ in range(reps):
        for spk, text in (("A", q), (second, a)):
            words = [Word(f" {t}", clock + i, clock + i + 1, 0.9, speaker=spk)
                     for i, t in enumerate(text.split())]
            turns.append(Turn(spk, clock, clock + len(words), words))
            clock += len(words) + 1
    speakers = [{"label": "A", "role": "interviewer"}, {"label": "B", "role": "interviewee"}]
    return Transcript({"interview_id": "I01", "audio": {"duration_s": clock}}, speakers, turns)


def _window(name="I01", start=0.0, end=400.0):
    return Window(name, [], start, end, reference_from_transcript(_transcript(), start, end))


def fake_run(settings, window, hotwords):
    """Pretend pipeline: beam 8 fixes the wording, the glossary a term, sentence_level and
    the voice the speakers."""
    a = TEXT_A if settings["beam_size"] >= 8 else TEXT_A.replace("zwei", "drei")
    q = TEXT_Q if hotwords and "Kubernetes" in hotwords else TEXT_Q.replace("Kubernetes", "Kuber")
    wrong = not (settings["sentence_level"] or settings.get("voice_margin"))
    return _transcript(q, a, "A" if wrong else "B")


def test_descent_finds_optimum_and_stops():
    best, why = coordinate_descent(lambda p: abs(p["x"] - 2) + abs(p["y"] - 1),
                                   {"x": [0, 1, 2], "y": [0, 1, 2]}, {"x": 0, "y": 0}, 50, None)
    assert best == {"x": 2, "y": 1} and why == "converged"


def test_descent_ignores_noise_and_respects_budgets():
    best, _ = coordinate_descent(lambda p: 1 - 0.0005 * p["x"], {"x": [0, 1, 2]}, {"x": 0},
                                 50, None)
    assert best == {"x": 0}
    _, why = coordinate_descent(lambda p: 1.0 - p["x"], {"x": [0, 1, 2, 3]}, {"x": 0}, 2, None)
    assert why == "evaluation budget used up"
    _, why = coordinate_descent(lambda p: 1.0, {"x": [0, 1]}, {"x": 0}, 50,
                                time.monotonic() - 1)
    assert why == "time budget used up"


def test_split_holds_out_every_third_window_and_never_all():
    ws = [_window("I01", s) for s in (0, 100, 200, 300, 400, 500)]
    train, val = split_windows(ws)
    assert [w.start for w in val] == [200, 500] and len(train) == 4
    assert split_windows(ws[:2]) == ([ws[0]], [ws[1]])
    one_train, one_val = split_windows(ws[:1])
    assert one_train == one_val


def test_tune_improves_settings_and_learns_the_glossary():
    r = tune([_window("I01"), _window("I02")], fake_run, {"beam_size": 5})
    assert r["settings"]["beam_size"] == 8 and r["settings"]["sentence_level"] is True
    assert "Kubernetes" in r["glossary"] and r["changed"]["glossary"] is True
    assert r["baseline"]["validation"]["loss"] > 0 and r["best"]["validation"]["loss"] == 0
    assert r["held_out"] and r["improved"] and r["stopped"] == "converged"
    assert "voice_margin" not in r["changed"]  # no profile: not searched


def test_voice_margin_is_searched_only_with_a_profile():
    def run(settings, window, hotwords):
        return fake_run({**settings, "beam_size": 8}, window, "Kubernetes")

    r = tune([_window()], run, {}, has_profile=True)
    # sentence_level comes first in the search and already fixes the speakers
    assert r["best"]["validation"]["loss"] == 0 and r["held_out"] is False
    assert any(t["params"]["voice_margin"] for t in r["trials"]) or r["evaluations"] > 1


def test_tune_keeps_the_settings_when_the_held_out_window_does_not_improve():
    def run(settings, window, hotwords):
        good = window.interview == "I01" and settings["beam_size"] >= 8
        return _transcript(a=TEXT_A if good else TEXT_A.replace("zwei", "drei"), second="B")

    r = tune([_window("I01"), _window("I02")], run, {})
    assert r["settings"]["beam_size"] == 5 and not r["improved"] and "held-out" in r["note"]


def test_no_windows_is_an_error():
    with pytest.raises(TuneError):
        tune([], fake_run, {})


def test_merge_hotwords_dedupes_and_caps():
    assert merge_hotwords("SAP, Müller", ["müller", "Kubernetes"]) == "SAP, Müller, Kubernetes"
    assert merge_hotwords(None, []) is None
    assert len(merge_hotwords("", [f"Begriff{i}" for i in range(500)])) <= 800


def test_pipeline_options_follow_the_website_settings():
    o = pipeline_options({"beam_size": 8, "compute_type": "float32", "room_mic": True,
                          "dereverb": True, "wpe_taps": 12, "voice_margin": 0.2,
                          "speakers": 0, "sentence_level": True, "vad_threshold": 0.4,
                          "min_duration_off": 0.6}, hotwords="SAP", clip=(60.0, 120.0))
    assert (o.asr.beam_size, o.asr.compute_type, o.asr.hotwords) == (8, "float32", "SAP")
    assert o.asr.room_mic and o.asr.vad_threshold == 0.4 and o.num_speakers is None
    assert o.dereverb == (12, 3, 3) and o.clip == (60.0, 120.0) and o.voice_margin == 0.2
    assert o.sentence_level and o.min_duration_off == 0.6


# ------------------------------------------------------------------ command and website

@pytest.fixture
def interview(tmp_path):
    """A transcribed, partly corrected interview with its recording."""
    paths = Paths(tmp_path)
    paths.ensure()
    c = TestClient(create_app(paths, "t", 8765), base_url=BASE)
    assert c.post("/api/login", json={"token": "t"}, headers=H).status_code == 200
    c.post("/api/projects", json={"name": "P"}, headers=H)
    c.post("/api/projects/1/interviews", json={"interview": "I01"}, headers=H)
    c.post("/api/interviews/I01/parts?ext=wav", content=b"RIFF0000" * 10, headers=H)
    store = Store(tmp_path / "interis.db")
    audio = store.part_paths("I01")[0]
    t = _transcript(reps=20)
    t.meta["audio"] = {"duration_s": 440.0, "sha256": "x",
                       "parts": [{"sha256": sha256_file(audio), "offset_s": 0.0,
                                  "duration_s": 440.0}]}
    out = tmp_path / "exports" / "I01"
    out.mkdir(parents=True)
    (out / "I01.json").write_text(json.dumps(t.to_dict()), encoding="utf-8")
    return paths, c, store


def test_website_starts_a_tuning_job_for_corrected_stretches(interview):
    paths, c, store = interview
    body = {"windows": [{"interview": "I01", "start": 0, "end": 120}], "budget_minutes": 30}
    r = c.post("/api/tuning", json=body, headers=H)
    assert r.status_code == 422 and "noch nichts korrigiert" in r.json()["detail"]
    store.set_reviewed("I01", True)
    w = {"interview": "NOPE", "start": 0, "end": 120}
    assert c.post("/api/tuning", json={"windows": [w]}, headers=H).status_code in (404, 422)
    w = {"interview": "I01", "start": 9999, "end": 12000}
    assert c.post("/api/tuning", json={"windows": [w]}, headers=H).status_code == 422
    job = store.job(c.post("/api/tuning", json=body, headers=H).json()["job"])
    assert job["kind"] == "tune" and job["interview_id"] == ""
    # the job gets the stretch with its edges on speaker turns (120 s falls inside a turn)
    spans = _transcript(reps=20).turns
    end = max(t.end for t in spans if t.start < 120)
    assert job["options"]["windows"] == [{"interview": "I01", "start": 0.0, "end": end}]
    assert c.post("/api/tuning", json=body, headers=H).status_code == 409
    cmd = JobRunner(paths, store, lambda _i: None, lambda _i: "").command(job)
    assert cmd[cmd.index("tune"):] == ["tune", "--progress-json", "--window",
                                       f"I01:0.0-{end}", "--budget-minutes", "30.0"]
    assert sys.executable in cmd[0]
    assert c.get("/api/tuning").json()["job"]["id"] == job["id"]


def test_command_corrected_text_is_the_ground_truth_and_best_settings_become_default(
        interview, monkeypatch):
    paths, _c, store = interview
    # the user corrected "zwei" -> "drei" in the first answer
    store.set_word_edits("I01", [{"turn": 1, "word": 4, "kind": "correction", "tag": "",
                                  "action": "replace", "text": "drei"}])
    seen = {}

    def runner(_paths, analysis, threads=None, progress=None):
        def run(settings, window, hotwords):
            seen["ref"] = window.ref.norm
            seen["start"] = settings
            return fake_run(settings, window, hotwords)
        return run

    monkeypatch.setattr(tune_mod, "make_runner", runner)
    args = cli.build_parser().parse_args(["tune", "--window", "I01:0-120", "--max-evals", "30"])
    assert cli.cmd_tune(args, paths) == 0
    assert "drei" in seen["ref"] and "preset" not in seen["start"]  # your correction counts
    default = next(p for p in store.presets() if p["is_default"])
    assert default["name"].startswith("Optimiert") and default["options"]["beam_size"] >= 5
    assert (paths.root / "tuning" / "last.json").is_file()


def test_command_rejects_a_recording_that_changed_and_short_stretches(interview):
    paths, _c, store = interview
    ok = cli._tune_window("I01:0-120", paths, store)
    assert ok.audio == store.part_paths("I01") and len(ok.ref.norm) >= 50
    short = cli._tune_window("I01:0-20", paths, store)  # too short: grows by whole turns
    assert short.end - short.start >= 60
    store.part_paths("I01")[0].write_bytes(b"other")
    with pytest.raises(ValueError, match="differ"):
        cli._tune_window("I01:0-120", paths, store)
    with pytest.raises(ValueError, match="no transcript"):
        cli._tune_window("I99:0-120", paths, store)


# ------------------------------------------------------------------ where the stretch lies

def test_edges_move_to_whole_turns_and_never_cut_a_sentence():
    t = _transcript()
    starts = [x.start for x in t.turns]
    span = snap_to_turns(t, starts[3] + 4, starts[3] + 40)  # starts inside turn 3
    assert span.start == starts[3] and span.first == 3
    assert t.turns[span.last].end >= starts[3] + 40  # ends where that turn ends
    assert span.end == t.turns[span.last].end and span.end - span.start >= 36


def test_too_short_stretches_grow_and_too_long_ones_shrink_by_whole_turns():
    t = _transcript(reps=40)
    short = snap_to_turns(t, 0, 5)
    assert short.end - short.start >= 60 and short.end == t.turns[short.last].end
    long = snap_to_turns(t, 0, 5000)
    assert long.end - long.start <= 900 and long.end == t.turns[long.last].end
    with pytest.raises(TuneError, match="behind the end"):
        snap_to_turns(t, 9999, 10000)


def test_suggestion_covers_the_corrected_turns_or_the_start_if_all_was_checked():
    t = _transcript(reps=40)
    span = suggest_span(t, [10, 14], reviewed=False)
    assert span.first <= 10 and span.last >= 14 and span.start == t.turns[span.first].start
    assert suggest_span(t, [], reviewed=False) is None
    start = suggest_span(t, [], reviewed=True)
    assert start.start == 0 and start.end - start.start <= 600 + 25
    capped = suggest_span(t, [0, 70], reviewed=False)
    assert capped.end - capped.start <= 600 + 25


def test_website_shows_what_a_stretch_contains_and_suggests_one(interview):
    _paths, c, store = interview
    ask = {"interview": "I01", "start": 30, "end": 200}
    assert c.get("/api/tuning/suggest?interview=I01").status_code == 422  # nothing corrected
    store.set_word_edits("I01", [{"turn": 2, "word": 1, "kind": "correction", "tag": "",
                                  "action": "replace", "text": "x"},
                                 {"turn": 6, "word": 0, "kind": "correction", "tag": "",
                                  "action": "replace", "text": "y"}])
    p = c.post("/api/tuning/preview", json=ask, headers=H).json()
    t = _transcript(reps=20)
    assert p["start"] in [x.start for x in t.turns] and p["end"] in [x.end for x in t.turns]
    assert p["words"] > 50 and p["begins"] and p["ends"] and p["turns"] >= 4
    assert p["start"] <= 30 and p["end"] >= 200
    sug = c.get("/api/tuning/suggest?interview=I01").json()
    assert sug["start"] == t.turns[2].start and sug["end"] >= t.turns[6].end
    assert sug["corrections"] == 2 and sug["speaker_corrections"] == 0
