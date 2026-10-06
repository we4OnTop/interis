"""Benchmark on the AMI Meeting Corpus (CC-BY-4.0, real meetings, 4 speakers,
manually annotated words with speaker and time).

Measures
--------
* who spoke when   – diarization error rate (DER) = missed speech + false alarm + speaker
                     confusion, with pyannote.metrics (collar 0.25 s and 0 s)
* who said what    – share of recognised words attributed to the right person
                     (hypothesis speakers mapped to reference speakers optimally)
* what was said    – word error rate (WER) after light normalisation
* time             – seconds of processing per minute of audio, per step

Usage (files from https://groups.inf.ed.ac.uk/ami/ in one folder)::

    uv run python bench/ami_bench.py --ami-dir <dir> --meeting ES2004a --mic Mix-Headset \
        --minutes 10 --asr whisper-large-v3 --speakers 4
"""

from __future__ import annotations

import argparse
import json
import re
import time
import xml.etree.ElementTree as ET  # noqa: S405 – trusted, size-limited corpus files
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from interis import _bootstrap

_bootstrap.go_offline()

from interis.config import apply_paths, resolve_paths  # noqa: E402

FILLERS = {"um", "uh", "hmm", "mm", "mm-hmm", "uh-huh", "mhm", "hm", "ah", "eh", "er", "erm",
           "huh", "uhm", "mm-mm", "um-hum", "ooh", "oh"}


def load_reference(zip_path: Path, meeting: str) -> list[tuple[float, float, str, str]]:
    """Manual AMI words: (start, end, speaker letter, text), punctuation excluded."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for spk in "ABCDE":
            name = f"words/{meeting}.{spk}.words.xml"
            if name not in names:
                continue
            root = ET.fromstring(z.read(name))  # noqa: S314
            for w in root.iter("w"):
                if w.get("punc") == "true" or w.get("starttime") is None:
                    continue
                out.append((float(w.get("starttime")), float(w.get("endtime")), spk,
                            (w.text or "").strip()))
    out.sort()
    return out


def channels(zip_path: Path, meeting: str) -> dict[str, int]:
    """Speaker letter -> headset channel, from corpusResources/meetings.xml."""
    with zipfile.ZipFile(zip_path) as z:
        root = ET.fromstring(z.read("corpusResources/meetings.xml"))  # noqa: S314
    for m in root.iter("meeting"):
        if m.get("observation") == meeting:
            return {sp.get("nxt_agent"): int(sp.get("channel")) for sp in m.iter("speaker")}
    raise KeyError(meeting)


def reference_annotation(words, crop: float, gap: float = 0.3):
    """Speech regions per speaker from manual word timings (gaps < 0.3 s bridged)."""
    from pyannote.core import Annotation, Segment

    ann = Annotation()
    by_spk: dict[str, list[tuple[float, float]]] = {}
    for s, e, spk, _ in words:
        if s >= crop:
            continue
        by_spk.setdefault(spk, []).append((s, min(max(e, s + 0.01), crop)))
    for spk, spans in by_spk.items():
        cur_s, cur_e = spans[0]
        for s, e in spans[1:]:
            if s - cur_e <= gap:
                cur_e = max(cur_e, e)
            else:
                ann[Segment(cur_s, cur_e), len(ann)] = spk
                cur_s, cur_e = s, e
        ann[Segment(cur_s, cur_e), len(ann)] = spk
    return ann


def normalise(text: str) -> list[str]:
    tokens = re.sub(r"[^\w'\- ]+", " ", text.lower()).split()
    return [t for t in tokens if t not in FILLERS and t.strip("-'")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ami-dir", required=True)
    ap.add_argument("--meeting", required=True)
    ap.add_argument("--mic", default="Mix-Headset", help="Mix-Headset or Array1-01")
    ap.add_argument("--minutes", type=float, default=10.0, help="evaluate the first N minutes")
    ap.add_argument("--asr", default="whisper-large-v3",
                    help="whisper-large-v3 | whisper-large-v3-turbo | none")
    ap.add_argument("--speakers", type=int, default=4, help="known speaker count (0 = auto)")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--pair", action="store_true",
                    help="2-person conversation: mix the headset channels of the two speakers "
                         "who talk most in the window (interview-like)")
    args = ap.parse_args()

    paths = resolve_paths(None)
    apply_paths(paths)
    import torch
    from pyannote.core import Annotation, Segment, Timeline
    from pyannote.metrics.diarization import DiarizationErrorRate

    from interis.models import DIARIZATION_MODEL, verify_ready
    from interis.pipeline.asr import AsrOptions, transcribe
    from interis.pipeline.diarize import diarize
    from interis.pipeline.merge import assign_speakers
    from interis.pipeline.run import decode

    if args.threads:
        torch.set_num_threads(args.threads)
    ami = Path(args.ami_dir)
    timings: dict[str, float] = {}

    zip_path = ami / "ami_public_manual_1.6.2.zip"
    all_words = load_reference(zip_path, args.meeting)
    t0 = time.perf_counter()
    if args.pair:
        import numpy as np

        crop = args.minutes * 60
        talk: dict[str, float] = {}
        for s, e, spk, _ in all_words:
            if s < crop:
                talk[spk] = talk.get(spk, 0.0) + (e - s)
        pair = sorted(talk, key=talk.get, reverse=True)[:2]
        chans = channels(zip_path, args.meeting)
        tracks = []
        for spk in pair:
            x = decode(ami / f"{args.meeting}.Headset-{chans[spk]}.wav")[: int(crop * 16000)]
            tracks.append(x / (np.sqrt(np.mean(x ** 2)) + 1e-9))
        n = min(len(t) for t in tracks)
        audio = sum(t[:n] for t in tracks)
        audio = (audio / (np.abs(audio).max() + 1e-9) * 0.9).astype(np.float32)
        all_words = [w for w in all_words if w[2] in pair]
        args.mic, args.speakers = f"pair-{''.join(pair)}", (args.speakers and 2)
    else:
        audio = decode(ami / f"{args.meeting}.{args.mic}.wav")
    crop = min(args.minutes * 60, len(audio) / 16000)
    audio = audio[: int(crop * 16000)]
    timings["decode"] = time.perf_counter() - t0
    minutes = crop / 60

    ref_words = [w for w in all_words if w[0] < crop]
    reference = reference_annotation(ref_words, crop)
    uem = Timeline([Segment(0, crop)])

    # --- who spoke when
    t0 = time.perf_counter()
    diar = diarize(audio, verify_ready(paths, DIARIZATION_MODEL), args.speakers or None)
    timings["diarize"] = time.perf_counter() - t0
    hyp = Annotation()
    for i, s in enumerate(diar.regular):
        hyp[Segment(s.start, s.end), i] = s.speaker

    result: dict = {
        "meeting": args.meeting, "mic": args.mic, "minutes": round(minutes, 2),
        "speakers_given": args.speakers or "auto",
        "speakers_reference": len(reference.labels()), "speakers_found": len(hyp.labels()),
    }
    for collar in (0.25, 0.0):
        metric = DiarizationErrorRate(collar=collar, skip_overlap=False)
        comp = metric(reference, hyp, uem=uem, detailed=True)
        total = comp["total"] or 1
        result[f"der_collar_{collar}"] = {
            "DER": round(comp["diarization error rate"] * 100, 1),
            "confusion": round(comp["confusion"] / total * 100, 1),
            "missed": round(comp["missed detection"] / total * 100, 1),
            "false_alarm": round(comp["false alarm"] / total * 100, 1),
        }
    mapping = DiarizationErrorRate().optimal_mapping(reference, hyp)

    # --- what was said / who said what
    if args.asr != "none":
        t0 = time.perf_counter()
        segments = transcribe(audio, verify_ready(paths, args.asr),
                              AsrOptions(language="en", threads=args.threads))
        timings["asr"] = time.perf_counter() - t0
        words = [w for s in segments for w in s.words]
        t0 = time.perf_counter()
        assign_speakers(words, diar)
        timings["merge"] = time.perf_counter() - t0

        import jiwer

        ref_text = " ".join(normalise(" ".join(w[3] for w in ref_words)))
        hyp_text = " ".join(normalise(" ".join(w.text for w in words)))
        result["WER"] = round(jiwer.wer(ref_text, hyp_text) * 100, 1)

        correct = checked = 0
        for w in words:
            if not normalise(w.text):
                continue
            overlaps: dict[str, float] = {}
            for rs, re_, spk, _ in ref_words:
                ov = min(w.end, re_) - max(w.start, rs)
                if ov > 0:
                    overlaps[spk] = overlaps.get(spk, 0.0) + ov
            if not overlaps:
                continue
            checked += 1
            if mapping.get(w.speaker) == max(overlaps, key=overlaps.get):
                correct += 1
        result["words_right_speaker_pct"] = round(100 * correct / max(checked, 1), 1)
        result["words_checked"] = checked
        result["asr_model"] = args.asr

    result["seconds_per_audio_minute"] = {k: round(v / minutes, 1) for k, v in timings.items()}
    result["seconds_per_audio_minute"]["total"] = round(sum(timings.values()) / minutes, 1)
    result["threads"] = args.threads or torch.get_num_threads()
    result["created_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    out = paths.root / "bench" / "results"
    out.mkdir(parents=True, exist_ok=True)
    name = f"{args.meeting}_{args.mic}_{args.asr}_{args.speakers}spk_{result['threads']}thr.json"
    (out / name).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
