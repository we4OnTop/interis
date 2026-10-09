"""Command line interface.

Heavy libraries are imported only inside the command functions, *after* the privacy
bootstrap has configured the environment (see :mod:`interis._bootstrap`)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from interis import _bootstrap
from interis.config import ConfigError, Paths, apply_paths, resolve_paths


def _progress_printer():
    state = {"stage": None, "last": 0.0}

    def report(stage: str, fraction: float) -> None:
        now = time.monotonic()
        if stage == state["stage"] and fraction < 1.0 and now - state["last"] < 1.0:
            return
        if stage != state["stage"] and state["stage"] is not None:
            print()
        state.update(stage=stage, last=now)
        print(f"\r  {stage:<28} {fraction * 100:5.1f}%", end="", flush=True)

    return report


def _progress_json():
    """Machine-readable progress for the website's job runner (one JSON object per line)."""
    state = {"stage": None, "last": 0.0}

    def report(stage: str, fraction: float) -> None:
        now = time.monotonic()
        if stage == state["stage"] and fraction < 1.0 and now - state["last"] < 1.0:
            return
        state.update(stage=stage, last=now)
        print(json.dumps({"stage": stage, "fraction": round(fraction, 4)}), flush=True)

    return report


def cmd_setup_models(args: argparse.Namespace, paths: Paths) -> int:
    from interis.models import MODELS, ModelError, setup_model

    keys = args.only or list(MODELS)
    token = os.environ.get("HF_TOKEN") or None
    for i, key in enumerate(keys):
        if args.progress_json:
            print(json.dumps({"stage": f"models:{key}", "fraction": i / len(keys)}), flush=True)
        try:
            # The token is only sent for gated models.
            setup_model(paths, key, token if MODELS[key].gated else None,
                        allow_mirror=args.allow_verified_mirror)
        except ModelError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    if args.progress_json:
        print(json.dumps({"stage": "models:done", "fraction": 1.0}), flush=True)
    print("\nDone. Next: run scripts\\firewall.ps1 as administrator, then `interis doctor`.")
    return 0


def cmd_doctor(args: argparse.Namespace, paths: Paths) -> int:
    from interis.doctor import run_doctor

    return run_doctor(paths)


def _analysis_options(args: argparse.Namespace, paths: Paths, redo_roles: bool):
    from interis.analysis.analyze import AnalysisOptions
    from interis.analysis.guide import load_guide
    from interis.analysis.roles import load_voice, voice_file

    guide = load_guide(Path(args.guide)) if args.guide else None
    voice = load_voice(voice_file(paths.voices, args.voice))
    if voice is None and redo_roles:
        print(f"Note: no voice profile '{args.voice}' – interviewer is guessed from the share "
              "of questions (run `interis enroll` for voice-based recognition).")
    return AnalysisOptions(guide=guide, voice=voice, redo_roles=redo_roles,
                           match_threshold=args.match_threshold,
                           match_margin=args.match_margin, answer_z=args.answer_z)


def _write_outputs(transcript, out_dir: Path, formats: str) -> None:
    from interis.export import write_docx, write_json, write_txt

    # the ID comes from the transcript file: it must not carry a path into the file name
    iid = transcript.meta["interview_id"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", str(iid)):
        raise ValueError(f"unsafe interview ID in the transcript: {iid!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / iid
    writers = {"json": write_json, "txt": write_txt, "docx": write_docx}
    for fmt in (f.strip() for f in formats.split(",")):
        writers[fmt](transcript, base.with_suffix(f".{fmt}"))


def _summary(transcript) -> str:
    a = transcript.analysis
    roles = a.get("roles", {})
    qs = a.get("questions", [])
    main = sum(q.get("match") == "main" for q in qs)
    parts = [f"interviewer: {roles.get('interviewer') or '?'} ({roles.get('method', 'none')})",
             f"questions: {len(qs)}"]
    if a.get("guide"):
        parts.append(f"matched to guide: {main}, suggestions elsewhere: "
                     f"{len(a.get('suggestions', []))}")
    return ", ".join(parts)


def cmd_enroll(args: argparse.Namespace, paths: Paths) -> int:
    from interis.analysis.roles import save_voice, voice_embedding, voice_file
    from interis.models import DIARIZATION_MODEL, MODELS, ModelError, verify_ready
    from interis.pipeline.run import decode

    audio_path = Path(args.audio).resolve()
    if not audio_path.is_file():
        print(f"ERROR: file not found: {audio_path}", file=sys.stderr)
        return 2
    try:
        model_dir = verify_ready(paths, DIARIZATION_MODEL)
    except ModelError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    audio = decode(audio_path)
    if len(audio) < 20 * 16000:
        print("ERROR: please use at least 20 s (ideally ~60 s) of only your own voice.",
              file=sys.stderr)
        return 2
    embedding = voice_embedding(audio, model_dir)
    target = voice_file(paths.voices, args.label)
    save_voice(target, args.label, embedding, MODELS[DIARIZATION_MODEL].revision)
    print(f"Voice profile saved: {target}")
    return 0


def _load_edits(path: str) -> tuple[list[dict], list[dict]]:
    """Word and speaker edits written by the website: {"words": [{turn, word, action, text,
    ...}], "speakers": [{turn, word, speaker}]}, or only the list of word edits."""
    from interis.web.edits import ACTIONS

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"words": data, "speakers": []}

    def pos(e: object) -> bool:
        return isinstance(e, dict) and isinstance(e.get("turn"), int) \
            and isinstance(e.get("word"), int)

    words, speakers = data.get("words"), data.get("speakers")
    valid = isinstance(words, list) and isinstance(speakers, list) and all(
        pos(e) and e.get("action") in ACTIONS and isinstance(e.get("text", ""), str)
        for e in words) and all(pos(s) and isinstance(s.get("speaker"), str) for s in speakers)
    if not valid:
        raise ValueError("edits file: expected {words: [{turn, word, action, text}], "
                         "speakers: [{turn, word, speaker}]}")
    return words, speakers


def cmd_speakers(args: argparse.Namespace, paths: Paths) -> int:
    """Speakers by voice (see interis.analysis.speakers): writes the proposed speaker
    corrections to --out, or with --save-voice a voice profile; the transcript itself is
    not changed."""
    import numpy as np

    from interis.analysis.roles import (
        load_voice,
        merge_voice,
        save_voice,
        voice_embedder,
        voice_file,
    )
    from interis.analysis.sentences import split_sentences
    from interis.analysis.speakers import learn_voice, reassign
    from interis.models import (
        DIARIZATION_MODEL,
        MODELS,
        ModelError,
        sha256_file,
        verify_ready,
    )
    from interis.pipeline.run import SAMPLE_RATE, decode
    from interis.pipeline.types import Transcript
    from interis.web.edits import apply_edits

    raw = Transcript.from_dict(json.loads(Path(args.transcript).read_text(encoding="utf-8")))
    parts = raw.meta["audio"].get("parts") or []
    files = [Path(a) for a in args.audio]
    try:
        if len(files) != len(parts) or any(sha256_file(f) != p["sha256"]
                                           for f, p in zip(files, parts, strict=True)):
            raise ValueError("the recordings differ from the ones this transcript was made "
                             "from")
        words, moved = _load_edits(args.edits) if args.edits else ([], [])
        model_dir = verify_ready(paths, DIARIZATION_MODEL)
        voice = None
        if args.voice:
            profile = load_voice(voice_file(paths.voices, args.voice))
            if profile is None:
                raise ValueError(f"no voice profile '{args.voice}'")
            voice = np.asarray(profile["embedding"])
        if not args.save_voice and not args.out:
            raise ValueError("give --out (assign speakers) or --save-voice (learn a voice)")
    except (OSError, ValueError, ModelError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    # the transcript's own timeline: every part at the offset it had when transcribed
    audio = np.zeros(int(raw.meta["audio"]["duration_s"] * SAMPLE_RATE) + SAMPLE_RATE,
                     np.float32)
    for f, p in zip(files, parts, strict=True):
        x = decode(f)
        at = int(p["offset_s"] * SAMPLE_RATE)
        audio[at:at + len(x)] = x[:len(audio) - at]
    effective = apply_edits(raw, words, moved)
    sentences = split_sentences(effective.turns)
    embed = voice_embedder(model_dir)
    progress = _progress_json() if args.progress_json else _progress_printer()

    def words_of(s):
        turn = effective.turns[s.turn]
        return [(s.turn, i, turn.words[i]) for i in range(s.first, s.last + 1)]

    def crop(a: float, b: float) -> np.ndarray:
        return embed(audio[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)])

    try:
        if args.save_voice:
            target = voice_file(paths.voices, args.save_voice)
            learned = learn_voice(sentences, crop, args.speaker, args.min_seconds,
                                  lambda x: progress("speakers", x), args.learn_until)
            revision = MODELS[DIARIZATION_MODEL].revision
            source = str(raw.meta.get("interview_id"))
            old = None if args.replace_voice else load_voice(target)
            merged = merge_voice(old, learned, source, revision)
            save_voice(target, args.save_voice, merged["embedding"], revision,
                       **{k: v for k, v in merged.items() if k != "embedding"})
            print(f"\nStimmprofil „{args.save_voice}“ aus {source} "
                  f"{'ergänzt' if len(merged['sources']) > 1 else 'gespeichert'}: "
                  f"{merged['seconds']:.0f} s aus {len(merged['sources'])} Abschnitt(en)")
            return 0
        interviewer = next((s["label"] for s in raw.speakers
                            if s.get("role") == "interviewer"), None)
        changes, stats = reassign(
            sentences, words_of, crop, args.until, args.margin, args.min_seconds,
            lambda x: progress("speakers", x), voice=voice,
            labels=[s["label"] for s in raw.speakers], interviewer=interviewer)
    except ValueError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    Path(args.out).write_text(json.dumps({"changes": changes, "stats": stats}),
                              encoding="utf-8")
    print(f"\nReferenz {stats['reference']} Sätze · geprüft {stats['checked']} · geändert "
          f"{stats['changed']} · unsicher {stats['unsure']} · zu kurz {stats['short']}")
    return 0


def cmd_analyze(args: argparse.Namespace, paths: Paths) -> int:
    from interis.models import ModelError
    from interis.pipeline.run import run_analysis
    from interis.pipeline.types import Transcript
    from interis.web.edits import apply_edits, edits_digest

    if args.all:
        sources = [p for p in sorted(paths.exports.glob("*/*.json")) if p.stem == p.parent.name]
    elif args.transcript:
        sources = [Path(args.transcript).resolve()]
    else:
        print("ERROR: give a transcript JSON or --all", file=sys.stderr)
        return 2
    if args.edits and len(sources) != 1:
        print("ERROR: --edits belongs to one transcript", file=sys.stderr)
        return 2
    try:
        edits, speakers = _load_edits(args.edits) if args.edits else ([], [])
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    for src in sources:
        raw = Transcript.from_dict(json.loads(src.read_text(encoding="utf-8")))
        has_roles = any(s.get("role") in ("interviewer", "interviewee")
                        for s in raw.speakers)
        effective = apply_edits(raw, edits, speakers)  # the analysis sees the edited text
        try:
            run_analysis(effective, paths, _analysis_options(args, paths, not has_roles),
                         threads=args.threads)
        except ModelError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        # Only the analysis goes back into the transcript; its words stay as recorded.
        raw.analysis = {**effective.analysis, "edits_digest": edits_digest(edits, speakers)}
        try:
            _write_outputs(raw, src.parent, args.formats)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(f"{raw.meta['interview_id']}: {_summary(raw)}")
    return 0


def cmd_serve(args: argparse.Namespace, paths: Paths) -> int:
    import secrets
    import webbrowser

    import uvicorn

    from interis.web.app import create_app

    token = secrets.token_urlsafe(24)
    app = create_app(paths, token, args.port, Path(args.guide) if args.guide else None)
    # The token sits in the URL fragment: browsers never send fragments to the server.
    url = f"http://127.0.0.1:{args.port}/#login={token}"
    print(f"Interis läuft nur auf diesem Rechner: {url}\n(Beenden mit Strg+C)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    return 0


def cmd_set_audio(args: argparse.Namespace, paths: Paths) -> int:
    from interis.web.store import Store

    audio = [Path(a).resolve() for a in args.audio]
    for a in audio:
        if not a.is_file():
            print(f"ERROR: file not found: {a}", file=sys.stderr)
            return 2
    Store(paths.root / "interis.db").register_parts(args.id, audio)
    print(f"Audio for {args.id}: " + ", ".join(str(a) for a in audio))
    return 0


def cmd_transcribe(args: argparse.Namespace, paths: Paths) -> int:
    from interis.models import ModelError
    from interis.pipeline.asr import AsrOptions
    from interis.pipeline.run import PipelineOptions, run_pipeline

    audio = [Path(a).resolve() for a in args.audio]
    for a in audio:
        if not a.is_file():
            print(f"ERROR: file not found: {a}", file=sys.stderr)
            return 2
    opts = PipelineOptions(
        asr_model=args.model,
        asr=AsrOptions(compute_type=args.compute_type, beam_size=args.beam_size,
                       hotwords=args.hotwords, initial_prompt=args.initial_prompt,
                       threads=args.threads, room_mic=args.room_mic,
                       vad_threshold=args.vad_threshold),
        align=not args.no_align,
        diarize=not args.no_diarize,
        num_speakers=args.speakers or None,
        min_duration_off=args.min_duration_off,
        dereverb=(args.wpe_taps, args.wpe_delay, args.wpe_iterations) if args.dereverb else None,
        clip=(args.start, args.duration) if args.duration else None,
        sentence_level=args.speaker_per_sentence,
        voice_margin=args.voice_margin,
        steps_dir=Path(args.steps_dir) if args.steps_dir else None,
        interview_id=args.id,
        analysis=_analysis_options(args, paths, redo_roles=True),
    )
    started = time.monotonic()
    try:
        progress = _progress_json() if args.progress_json else _progress_printer()
        transcript = run_pipeline(audio, paths, opts, progress)
    except (ModelError, ValueError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    print()
    if args.out:  # a trial run: only this file, the interview itself is not touched
        from interis.export import write_json

        write_json(transcript, Path(args.out))
        print(f"Done in {(time.monotonic() - started) / 60:.1f} min. Output: {args.out}")
        return 0

    out_dir = paths.exports / transcript.meta["interview_id"]
    _write_outputs(transcript, out_dir, args.formats)
    from interis.web.store import Store

    store = Store(paths.root / "interis.db")
    store.register_parts(transcript.meta["interview_id"], audio)
    # the new transcript has new word positions: markings made on the old one are removed
    store.delete_decisions(transcript.meta["interview_id"])
    elapsed = time.monotonic() - started
    duration = transcript.meta["audio"]["duration_s"]
    print(f"{_summary(transcript)}")
    print(f"Done in {elapsed / 60:.1f} min for {duration / 60:.1f} min audio "
          f"(factor {elapsed / max(duration, 1):.2f}×). Output: {out_dir}")
    return 0


MAX_TUNE_WINDOW_S = 900.0


def _tune_window(spec: str, paths: Paths, store):
    """``ID:start-end`` (seconds; ``ID`` alone = from the start to the end of the interview)
    -> the corrected stretch with its audio, checked against the stored recordings."""
    from interis.models import sha256_file
    from interis.pipeline.evaluate import reference_from_transcript
    from interis.pipeline.tune import MIN_WINDOW_S, Window
    from interis.pipeline.types import Transcript
    from interis.web.edits import apply_edits

    iid, _, span = spec.partition(":")
    src = paths.exports / iid / f"{iid}.json"
    if not src.is_file():
        raise ValueError(f"{iid}: no transcript")
    raw = Transcript.from_dict(json.loads(src.read_text(encoding="utf-8")))
    files = store.part_paths(iid)
    parts = raw.meta["audio"].get("parts") or []
    if not files or len(files) != len(parts) or any(
            not f.is_file() or sha256_file(f) != p["sha256"]
            for f, p in zip(files, parts, strict=True)):
        raise ValueError(f"{iid}: the recordings are missing or differ from the transcript")
    start, _, end = span.partition("-")
    a = float(start) if start else 0.0
    b = float(end) if end else min(raw.meta["audio"]["duration_s"], a + MAX_TUNE_WINDOW_S)
    if not 0 <= a < b <= raw.meta["audio"]["duration_s"] + 1:
        raise ValueError(f"{iid}: time window outside the recording")
    if b - a < MIN_WINDOW_S or b - a > MAX_TUNE_WINDOW_S:
        raise ValueError(f"{iid}: the stretch must be between {MIN_WINDOW_S:.0f} s and "
                         f"{MAX_TUNE_WINDOW_S / 60:.0f} min long")
    effective = apply_edits(raw, store.word_edits(iid), store.speaker_edits(iid))
    ref = reference_from_transcript(effective, a, b)
    if len(ref.norm) < 50:
        raise ValueError(f"{iid}: fewer than 50 words in this stretch")
    return Window(iid, files, a, b, ref)


def cmd_tune(args: argparse.Namespace, paths: Paths) -> int:
    """Find the transcription settings closest to what you corrected (see
    :mod:`interis.pipeline.tune`) and save them as a preset, which becomes the default."""
    from datetime import datetime

    from interis.analysis.analyze import AnalysisOptions
    from interis.analysis.roles import load_voice, voice_file
    from interis.models import ModelError
    from interis.pipeline.tune import TuneError, make_runner, tune
    from interis.web.store import Store
    from interis.web.transcription import default_settings

    store = Store(paths.root / "interis.db")
    progress = _progress_json() if args.progress_json else _progress_printer()
    try:
        windows = [_tune_window(spec, paths, store) for spec in args.window]
        voice = load_voice(voice_file(paths.voices, args.voice))
        start = {k: v for k, v in default_settings(store).items() if k != "preset"}
        report = tune(windows, make_runner(paths, AnalysisOptions(voice=voice), args.threads),
                      start, has_profile=voice is not None, max_evals=args.max_evals,
                      budget_s=args.budget_minutes * 60 if args.budget_minutes else None,
                      progress=progress)
    except (ModelError, TuneError, ValueError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    print()
    tuning = paths.root / "tuning"
    tuning.mkdir(exist_ok=True)
    (tuning / "last.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    for label, key in (("vorher", "baseline"), ("nachher", "best")):
        v = report[key]["validation"]
        print(f"{label}: falsche Wörter {v['wer']:.1%}, falscher Sprecher "
              f"{v['speaker_error']:.1%}"
              + (" (an ungesehenem Ausschnitt)" if report["held_out"] else ""))
    if report["note"]:
        print(f"Hinweis: {report['note']}")
    if not report["improved"]:
        print(f"Keine Verbesserung gefunden ({report['evaluations']} Einstellungen "
              "probiert) – die Einstellungen bleiben.")
        return 0
    name = f"Optimiert {datetime.now():%Y-%m-%d %H:%M}"
    settings = {**report["settings"], "glossary": report["glossary"]}
    store.set_default_preset(store.save_preset(name, settings))
    print(f"„{name}“ gespeichert und als Standard gesetzt "
          f"({report['evaluations']} Einstellungen probiert, {report['stopped']}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from interis.models import ASR_MODELS, MODELS

    parser = argparse.ArgumentParser(prog="interis", description=__doc__)
    parser.add_argument("--data-dir", help="data directory (default: $INTERIS_DATA_DIR)")
    parser.add_argument("--models-dir",
                        help="models directory (default: $INTERIS_MODELS_DIR or <data>/models)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup-models", help="one-time download + verification of models "
                                            "(the only command that uses the network)")
    p.add_argument("--only", nargs="+", choices=list(MODELS), help="only these models")
    p.add_argument("--allow-verified-mirror", action="store_true",
                   help="without HF_TOKEN: fetch gated models from their ungated mirror; "
                        "files are verified against the official repo's hashes")
    p.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_setup_models)

    p = sub.add_parser("doctor", help="check privacy and integrity guarantees")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("transcribe", help="transcribe one interview (offline)")
    p.add_argument("audio", nargs="+",
                   help="audio or video file; several files (e.g. before and after a break) "
                        "are joined in this order into one interview")
    p.add_argument("--id", help="interview pseudonym, e.g. I01 (default: derived from hash)")
    p.add_argument("--model", choices=ASR_MODELS, default="whisper-large-v3",
                   help="large-v3 = most precise (default), large-v3-turbo = faster draft")
    p.add_argument("--compute-type", choices=["int8", "float32"], default="int8")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--speakers", type=int, default=2, help="number of speakers (0 = auto)")
    p.add_argument("--hotwords", help="glossary of names/terms to help spelling")
    p.add_argument("--initial-prompt", help="optional Whisper prompt (experimental)")
    p.add_argument("--room-mic", action="store_true",
                   help="one room microphone, one speaker much quieter: even out loudness "
                        "and detect quiet speech (measure it with bench/wer.py)")
    p.add_argument("--vad-threshold", type=float,
                   help="speech detector, 0.1–0.9: lower finds quieter speech "
                        "(default 0.5, 0.35 with --room-mic)")
    p.add_argument("--min-duration-off", type=float,
                   help="speaker diarization: bridge pauses of one speaker shorter than this "
                        "(seconds, default: the model's setting)")
    p.add_argument("--dereverb", action="store_true",
                   help="reduce reverberation (WPE) before recognition and diarization")
    p.add_argument("--wpe-taps", type=int, default=10,
                   help="WPE: length of the predicted reverberation, in 8 ms frames")
    p.add_argument("--wpe-delay", type=int, default=3,
                   help="WPE: frames kept as direct sound before the prediction starts")
    p.add_argument("--wpe-iterations", type=int, default=3, help="WPE: estimation rounds")
    p.add_argument("--voice-margin", type=float,
                   help="with a voice profile: give every sentence to the voice it is "
                        "clearly closer to (cosine lead, e.g. 0.1); default: off")
    p.add_argument("--speaker-per-sentence", action="store_true",
                   help="one speaker per sentence (no switch inside a sentence)")
    p.add_argument("--steps-dir", help="trial run: write every processing stage's audio and "
                                       "every step's result into this folder")
    p.add_argument("--start", type=float, default=0.0, help="excerpt: start in seconds")
    p.add_argument("--duration", type=float, help="excerpt: length in seconds (default: all)")
    p.add_argument("--out", help="trial run: write only this JSON file; the interview, its "
                                 "exports and markings are not touched")
    p.add_argument("--threads", type=int, help="CPU threads (default: all)")
    p.add_argument("--no-align", action="store_true", help="skip word alignment")
    p.add_argument("--no-diarize", action="store_true", help="skip speaker diarization")
    p.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)
    _add_analysis_args(p)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("tune", help="find the transcription settings closest to what you "
                                    "corrected; saved as a preset and made the default")
    p.add_argument("--window", action="append", required=True, metavar="ID:START-END",
                   help="a corrected stretch (seconds), e.g. I01:0-300; repeat for more; "
                        "two or more allow a check on a stretch the search did not see")
    p.add_argument("--voice", default="interviewer", help="voice profile (if present, "
                                                          "its use is tuned too)")
    p.add_argument("--max-evals", type=int, default=40, help="maximum settings to try")
    p.add_argument("--budget-minutes", type=float, help="stop searching after this time")
    p.add_argument("--threads", type=int, help="CPU threads (default: all)")
    p.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_tune)

    p = sub.add_parser("analyze", help="re-run question/guide analysis on a transcript JSON "
                                       "(e.g. after editing the guide)")
    p.add_argument("transcript", nargs="?", help="path to <ID>.json")
    p.add_argument("--all", action="store_true", help="all transcripts in the data directory")
    p.add_argument("--edits", help="JSON list of word edits (corrections, smoothing); the "
                                   "analysis then runs on the edited text")
    p.add_argument("--threads", type=int, help="CPU threads (default: all)")
    _add_analysis_args(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("speakers", help="assign speakers by voice, learned from a checked "
                                         "reference stretch at the start (writes --out only)")
    p.add_argument("transcript", help="path to <ID>.json")
    p.add_argument("--audio", nargs="+", required=True, help="the interview's recordings, "
                                                             "in order")
    p.add_argument("--edits", help="word and speaker edits (JSON, as written by the website)")
    p.add_argument("--until", type=float, default=60.0,
                   help="the reference: from the start up to this second")
    p.add_argument("--margin", type=float, default=0.1,
                   help="how clearly a voice must match better than the other (cosine)")
    p.add_argument("--min-seconds", type=float, default=1.0,
                   help="shorter sentences keep their speaker")
    p.add_argument("--out", help="JSON file for the proposed changes")
    p.add_argument("--voice", help="the interviewer's voice profile to use (e.g. interviewer)")
    p.add_argument("--save-voice", help="instead: learn this voice profile from --speaker's "
                                        "sentences (a transcript you corrected completely)")
    p.add_argument("--speaker", help="with --save-voice: the speaker label to learn")
    p.add_argument("--learn-until", type=float,
                   help="with --save-voice: only the first N seconds were checked")
    p.add_argument("--replace-voice", action="store_true",
                   help="with --save-voice: start the profile over instead of refining it")
    p.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_speakers)

    p = sub.add_parser("serve", help="open the review website (only reachable from this PC)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--guide", help="interview guide (default: <data>/leitfaden.md)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("set-audio", help="link an interview to its audio file (for playback)")
    p.add_argument("id", help="interview ID, e.g. I01")
    p.add_argument("audio", nargs="+", help="audio file(s) in playing order")
    p.set_defaults(func=cmd_set_audio)

    p = sub.add_parser("enroll", help="create your voice profile from a recording of only "
                                      "your voice (~60 s)")
    p.add_argument("audio", help="recording with only your voice")
    p.add_argument("--label", default="interviewer", help="profile name (default: interviewer)")
    p.set_defaults(func=cmd_enroll)
    return parser


def _add_analysis_args(p: argparse.ArgumentParser) -> None:
    from interis.analysis.analyze import ANSWER_Z, MATCH_MARGIN, MATCH_THRESHOLD

    p.add_argument("--guide", help="interview guide (Markdown, see README)")
    p.add_argument("--voice", default="interviewer", help="voice profile to identify you")
    p.add_argument("--match-threshold", type=float, default=MATCH_THRESHOLD,
                   help="similarity needed to link a question to the guide")
    p.add_argument("--match-margin", type=float, default=MATCH_MARGIN,
                   help="required lead over the second-best guide question")
    p.add_argument("--answer-z", type=float, default=ANSWER_Z,
                   help="how strongly a passage must stand out to be suggested as an answer")
    p.add_argument("--formats", default="json,docx,txt", help="comma list of json,docx,txt")


def main(argv: list[str] | None = None) -> int:
    # Argument parsing imports no ML libraries, so the privacy bootstrap below still runs
    # before anything imports huggingface_hub/torch/pyannote.
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.command == "setup-models":
        _bootstrap.disable_telemetry()
    else:
        _bootstrap.go_offline()
    try:
        paths = resolve_paths(args.data_dir, args.models_dir)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    apply_paths(paths)
    try:
        return args.func(args, paths)
    except ValueError as e:  # wrong input (e.g. an invalid profile name), not a program error
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
