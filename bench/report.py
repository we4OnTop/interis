"""Summarise bench/ami_bench.py results as a Markdown table.

    uv run python bench/report.py <data>/bench/results
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    rows = []
    for path in sorted(Path(sys.argv[1]).glob("*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        der = d["der_collar_0.25"]
        spm = d["seconds_per_audio_minute"]
        rows.append([
            d["meeting"], d["mic"], f"{d['minutes']:.0f}",
            f"{d['speakers_reference']}/{d['speakers_found']} ({d['speakers_given']})",
            f"{der['DER']}", f"{der['confusion']}", f"{der['missed']}", f"{der['false_alarm']}",
            f"{d.get('words_right_speaker_pct', '–')}", f"{d.get('WER', '–')}",
            d.get("asr_model", "–").replace("whisper-", ""), str(d["threads"]),
            f"{spm.get('diarize', 0)}", f"{spm.get('asr', '–')}", f"{spm['total']}",
        ])
    head = ["Meeting", "Mikrofon", "Min", "Sprecher Ref/gefunden (Vorgabe)", "DER %",
            "Verwechslung %", "verpasst %", "Fehlalarm %", "Wörter richtiger Sprecher %",
            "WER %", "ASR", "Threads", "s/min Sprechertrennung", "s/min ASR", "s/min gesamt"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for r in rows:
        print("| " + " | ".join(r) + " |")


if __name__ == "__main__":
    main()
