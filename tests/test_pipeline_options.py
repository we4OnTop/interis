"""Pipeline wiring of the trial options (excerpt, reverberation reduction) with the
models replaced by stand-ins, and the WPE dereverberation itself."""

import numpy as np

from interis.config import Paths
from interis.pipeline import dereverb as dereverb_mod
from interis.pipeline import run as run_mod
from interis.pipeline.dereverb import istft, stft, wpe
from interis.pipeline.types import Segment, Word

SR = 16000


def _stub(monkeypatch, heard: list):
    audio = (0.1 * np.sin(np.arange(SR * 20) / 7)).astype(np.float32)
    monkeypatch.setattr(run_mod, "decode", lambda _p: audio)
    monkeypatch.setattr(run_mod, "verify_ready", lambda _paths, _model: None)
    monkeypatch.setattr(run_mod, "run_analysis", lambda *a, **k: None)
    monkeypatch.setattr(run_mod, "require_offline", lambda: None)  # no network guard in tests
    monkeypatch.setattr(run_mod, "version", lambda _p: "0")

    def transcribe(x, _dir, _opts, _say):
        heard.append(x)
        return [Segment(0, 0.0, 1.0, " Hallo", [Word(" Hallo", 0.0, 1.0, 0.9)], -0.1, 0.0,
                        1.0, 0.0)]

    import interis.pipeline.asr as asr

    monkeypatch.setattr(asr, "transcribe", transcribe)


def test_excerpt_and_dereverb_reach_the_models_and_are_cached(tmp_path, monkeypatch):
    heard: list = []
    calls: list = []
    _stub(monkeypatch, heard)
    monkeypatch.setattr(dereverb_mod, "dereverb",
                        lambda x, *a, progress=None: calls.append(a) or x * 0.5)
    paths = Paths(tmp_path)
    paths.ensure()
    f = tmp_path / "a.wav"
    f.write_bytes(b"x")
    opts = run_mod.PipelineOptions(align=False, diarize=False, clip=(5.0, 4.0),
                                   dereverb=(12, 2, 1), interview_id="PROBE")
    t = run_mod.run_pipeline(f, paths, opts)
    assert len(heard[0]) == 4 * SR and calls == [(12, 2, 1)]
    assert np.allclose(heard[0], 0.05 * np.sin(np.arange(5 * SR, 9 * SR) / 7), atol=1e-6)
    assert t.meta["audio"]["clip"] == {"start_s": 5.0, "duration_s": 4.0}
    assert t.meta["options"]["dereverb"] == [12, 2, 1]

    run_mod.run_pipeline(f, paths, opts)  # cached: neither step runs again
    assert len(heard) == 1 and len(calls) == 1
    run_mod.run_pipeline(f, paths, run_mod.PipelineOptions(align=False, diarize=False,
                                                           clip=(5.0, 4.0)))
    assert len(heard) == 2 and len(calls) == 1  # other settings, other cache entry


def test_stft_round_trip_is_exact():
    x = np.random.default_rng(0).standard_normal(SR).astype(np.float32)
    assert np.abs(istft(stft(x), len(x)) - x).max() < 1e-5


def test_wpe_removes_a_predictable_echo():
    rng = np.random.default_rng(0)
    frames = 3000
    source = (rng.standard_normal((frames, 4)) + 1j * rng.standard_normal((frames, 4)))
    source *= rng.random((frames, 1)) < 0.3  # speech pauses
    y = source.copy()
    for t in range(5, frames):  # late reflections, 5 and 8 frames later
        y[t] += 0.7 * y[t - 5] + 0.2 * y[t - 8]
    x = wpe(y.astype(np.complex64), taps=10, delay=3, iterations=3)
    assert np.mean(np.abs(x - source) ** 2) < 0.01 * np.mean(np.abs(y - source) ** 2)
