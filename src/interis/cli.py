"""Command line interface.

Heavy libraries are imported only inside the command functions, *after* the privacy
bootstrap has configured the environment (see :mod:`interis._bootstrap`)."""

from __future__ import annotations

import argparse
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
            setup_model(paths, key, token if MODELS[key].gated else None)
        except ModelError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
    print("\nDone. Next: run scripts\\firewall.ps1 as administrator, then `interis doctor`.")
    return 0


def cmd_doctor(args: argparse.Namespace, paths: Paths) -> int:
    from interis.doctor import run_doctor

    return run_doctor(paths)


def cmd_transcribe(args: argparse.Namespace, paths: Paths) -> int:
    from interis.export import write_docx, write_json, write_txt
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
    )
    started = time.monotonic()
    try:
        transcript = run_pipeline(audio, paths, opts, _progress_printer())
    except ModelError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    print()

    out_dir = paths.exports / transcript.meta["interview_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / transcript.meta["interview_id"]
    writers = {"json": write_json, "txt": write_txt, "docx": write_docx}
    for fmt in args.formats.split(","):
        writers[fmt.strip()](transcript, base.with_suffix(f".{fmt.strip()}"))
    elapsed = time.monotonic() - started
    duration = transcript.meta["audio"]["duration_s"]
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
    p.add_argument("--formats", default="json,docx,txt", help="comma list of json,docx,txt")
    p.set_defaults(func=cmd_transcribe)
    return parser


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
