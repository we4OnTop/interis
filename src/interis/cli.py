"""Command line interface.

Heavy libraries are imported only inside the command functions, *after* the privacy
bootstrap has configured the environment (see :mod:`interis._bootstrap`)."""

from __future__ import annotations

import argparse
import json
import os
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
    if args.use_system_certs:
        # Needed when local software (e.g. an antivirus "HTTPS scan") re-signs TLS traffic
        # with its own root certificate that only the Windows certificate store trusts.
        # TLS stays verified – just against the OS store instead of certifi's bundle.
        import truststore

        truststore.inject_into_ssl()
        print("Using the Windows certificate store for TLS verification.")
    for key in keys:
        try:
            # The token is only sent for gated models.
            setup_model(paths, key, token if MODELS[key].gated else None,
                        allow_mirror=args.allow_verified_mirror)
        except ModelError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    print("\nDone. Next: run scripts\\firewall.ps1 as administrator, then `interis doctor`.")
    return 0


def cmd_doctor(args: argparse.Namespace, paths: Paths) -> int:
    from interis.doctor import run_doctor

    return run_doctor(paths)


def _analysis_options(args: argparse.Namespace, paths: Paths, redo_roles: bool):
    from interis.analysis.analyze import AnalysisOptions
    from interis.analysis.guide import load_guide
    from interis.analysis.roles import load_voice

    guide = load_guide(Path(args.guide)) if args.guide else None
    voice = load_voice(paths.voices / f"{args.voice}.json")
    if voice is None and redo_roles:
        print(f"Note: no voice profile '{args.voice}' – interviewer is guessed from the share "
              "of questions (run `interis enroll` for voice-based recognition).")
    return AnalysisOptions(guide=guide, voice=voice, redo_roles=redo_roles,
                           match_threshold=args.match_threshold,
                           match_margin=args.match_margin, answer_z=args.answer_z)


def _write_outputs(transcript, out_dir: Path, formats: str) -> None:
    from interis.export import write_docx, write_json, write_txt

    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / transcript.meta["interview_id"]
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
    from interis.analysis.roles import save_voice, voice_embedding
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
    target = paths.voices / f"{args.label}.json"
    save_voice(target, args.label, embedding, MODELS[DIARIZATION_MODEL].revision)
    print(f"Voice profile saved: {target}")
    return 0


def cmd_analyze(args: argparse.Namespace, paths: Paths) -> int:
    from interis.models import ModelError
    from interis.pipeline.run import run_analysis
    from interis.pipeline.types import Transcript

    if args.all:
        sources = [p for p in sorted(paths.exports.glob("*/*.json")) if p.stem == p.parent.name]
    elif args.transcript:
        sources = [Path(args.transcript).resolve()]
    else:
        print("ERROR: give a transcript JSON or --all", file=sys.stderr)
        return 2
    for src in sources:
        transcript = Transcript.from_dict(json.loads(src.read_text(encoding="utf-8")))
        has_roles = any(s.get("role") in ("interviewer", "interviewee")
                        for s in transcript.speakers)
        try:
            run_analysis(transcript, paths, _analysis_options(args, paths, not has_roles),
                         threads=args.threads)
        except ModelError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        _write_outputs(transcript, src.parent, args.formats)
        print(f"{transcript.meta['interview_id']}: {_summary(transcript)}")
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

    audio = Path(args.audio).resolve()
    if not audio.is_file():
        print(f"ERROR: file not found: {audio}", file=sys.stderr)
        return 2
    Store(paths.root / "interis.db").register_interview(args.id, audio)
    print(f"Audio for {args.id}: {audio}")
    return 0


def cmd_transcribe(args: argparse.Namespace, paths: Paths) -> int:
    from interis.models import ModelError
    from interis.pipeline.asr import AsrOptions
    from interis.pipeline.run import PipelineOptions, run_pipeline

    audio = Path(args.audio).resolve()
    if not audio.is_file():
        print(f"ERROR: file not found: {audio}", file=sys.stderr)
        return 2
    opts = PipelineOptions(
        asr_model=args.model,
        asr=AsrOptions(compute_type=args.compute_type, beam_size=args.beam_size,
                       hotwords=args.hotwords, initial_prompt=args.initial_prompt,
                       threads=args.threads),
        align=not args.no_align,
        diarize=not args.no_diarize,
        num_speakers=args.speakers or None,
        interview_id=args.id,
        analysis=_analysis_options(args, paths, redo_roles=True),
    )
    started = time.monotonic()
    try:
        progress = _progress_json() if args.progress_json else _progress_printer()
        transcript = run_pipeline(audio, paths, opts, progress)
    except ModelError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    print()

    out_dir = paths.exports / transcript.meta["interview_id"]
    _write_outputs(transcript, out_dir, args.formats)
    from interis.web.store import Store

    Store(paths.root / "interis.db").register_interview(transcript.meta["interview_id"], audio)
    elapsed = time.monotonic() - started
    duration = transcript.meta["audio"]["duration_s"]
    print(f"{_summary(transcript)}")
    print(f"Done in {elapsed / 60:.1f} min for {duration / 60:.1f} min audio "
          f"(factor {elapsed / max(duration, 1):.2f}×). Output: {out_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from interis.models import ASR_MODELS, MODELS

    parser = argparse.ArgumentParser(prog="interis", description=__doc__)
    parser.add_argument("--data-dir", help="data directory (default: $INTERIS_DATA_DIR)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup-models", help="one-time download + verification of models "
                                            "(the only command that uses the network)")
    p.add_argument("--only", nargs="+", choices=list(MODELS), help="only these models")
    p.add_argument("--use-system-certs", action="store_true",
                   help="verify TLS against the Windows certificate store (needed behind "
                        "TLS-intercepting antivirus/proxies)")
    p.add_argument("--allow-verified-mirror", action="store_true",
                   help="without HF_TOKEN: fetch gated models from their ungated mirror; "
                        "files are verified against the official repo's hashes")
    p.set_defaults(func=cmd_setup_models)

    p = sub.add_parser("doctor", help="check privacy and integrity guarantees")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("transcribe", help="transcribe one interview (offline)")
    p.add_argument("audio", help="audio or video file")
    p.add_argument("--id", help="interview pseudonym, e.g. I01 (default: derived from hash)")
    p.add_argument("--model", choices=ASR_MODELS, default="whisper-large-v3",
                   help="large-v3 = most precise (default), large-v3-turbo = faster draft")
    p.add_argument("--compute-type", choices=["int8", "float32"], default="int8")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--speakers", type=int, default=2, help="number of speakers (0 = auto)")
    p.add_argument("--hotwords", help="glossary of names/terms to help spelling")
    p.add_argument("--initial-prompt", help="optional Whisper prompt (experimental)")
    p.add_argument("--threads", type=int, help="CPU threads (default: all)")
    p.add_argument("--no-align", action="store_true", help="skip word alignment")
    p.add_argument("--no-diarize", action="store_true", help="skip speaker diarization")
    p.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)
    _add_analysis_args(p)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("analyze", help="re-run question/guide analysis on a transcript JSON "
                                       "(e.g. after editing the guide)")
    p.add_argument("transcript", nargs="?", help="path to <ID>.json")
    p.add_argument("--all", action="store_true", help="all transcripts in the data directory")
    p.add_argument("--threads", type=int, help="CPU threads (default: all)")
    _add_analysis_args(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("serve", help="open the review website (only reachable from this PC)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--guide", help="interview guide (default: <data>/leitfaden.md)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("set-audio", help="link an interview to its audio file (for playback)")
    p.add_argument("id", help="interview ID, e.g. I01")
    p.add_argument("audio", help="audio file")
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
        paths = resolve_paths(args.data_dir)
    except ConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    apply_paths(paths)
    return args.func(args, paths)


if __name__ == "__main__":
    raise SystemExit(main())
