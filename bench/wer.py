"""Word error rate of a transcript against your own reference, to compare settings on
your own recordings (e.g. with and without ``--room-mic``, large-v3 against turbo).

1. Cut 3–5 minutes from a real recording (any audio editor) and type out exactly what
   is said: ``ref.txt``. Punctuation and capitalisation do not count.
2. Transcribe the excerpt once per setting under its own ID, e.g.::

       uv run interis transcribe clip.wav --id TEST-A --no-diarize
       uv run interis transcribe clip.wav --id TEST-B --no-diarize --room-mic

3. Compare::

       uv run python bench/wer.py ref.txt <data>/exports/TEST-A/TEST-A.json \
           <data>/exports/TEST-B/TEST-B.json

"missing" words point to quiet speech that was not recognised, "wrong" ones to unclear
speech or unknown terms (add them to the project's glossary / hotwords).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def words(text: str) -> list[str]:
    return re.findall(r"[\wäöüß]+(?:[-'][\wäöüß]+)*", text.lower())


def transcript_text(path: Path) -> str:
    if path.suffix.lower() != ".json":
        return path.read_text(encoding="utf-8-sig")
    d = json.loads(path.read_text(encoding="utf-8"))
    return " ".join(w["text"] for t in d["turns"] for w in t["words"])


def errors(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """(wrong, missing, extra) words of the cheapest alignment."""
    # each cell: (total, wrong, missing, extra)
    prev = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i, r in enumerate(ref, 1):
        cur = [(i, 0, i, 0)]
        for j, h in enumerate(hyp, 1):
            d, s, ins = prev[j - 1], prev[j], cur[j - 1]
            cur.append(min(
                (d[0] + (r != h), d[1] + (r != h), d[2], d[3]),
                (s[0] + 1, s[1], s[2] + 1, s[3]),
                (ins[0] + 1, ins[1], ins[2], ins[3] + 1),
            ))
        prev = cur
    return prev[-1][1:]


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    ref = words(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    print(f"Referenz: {len(ref)} Wörter")
    for name in sys.argv[2:]:
        wrong, missing, extra = errors(ref, words(transcript_text(Path(name))))
        wer = 100 * (wrong + missing + extra) / max(len(ref), 1)
        print(f"{name}: WER {wer:.1f} %  (falsch {wrong}, fehlend {missing}, zusätzlich {extra})")


if __name__ == "__main__":
    main()
