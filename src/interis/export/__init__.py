"""Exporters. JSON is lossless (words, timings, probabilities, metadata); TXT and DOCX are
reading/review formats. Transcription rules (e.g. Dresing & Pehl) will be added later as
separate transformations applied at export time – the stored data stays raw."""

from __future__ import annotations

import json
from pathlib import Path

from interis.pipeline.types import Transcript

LOW_CONFIDENCE = 0.5  # words below this Whisper probability are highlighted for review


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def speaker_name(transcript: Transcript, label: str | None) -> str:
    if label is None:
        return "?"
    for sp in transcript.speakers:
        if sp["label"] == label:
            return sp.get("display_name") or label
    return label


def write_json(transcript: Transcript, path: Path) -> None:
    path.write_text(json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8")


def write_txt(transcript: Transcript, path: Path) -> None:
    lines = [
        f"# {transcript.meta['interview_id']} – {transcript.meta['note']}",
        "",
    ]
    for turn in transcript.turns:
        lines.append(f"[{fmt_time(turn.start)}] {speaker_name(transcript, turn.speaker)}: "
                     f"{turn.text}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_docx(transcript: Transcript, path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_COLOR_INDEX
    from docx.shared import Pt

    meta = transcript.meta
    doc = Document()
    doc.add_heading(f"Transkript {meta['interview_id']}", level=1)

    info = doc.add_table(rows=0, cols=2)
    rows = [
        ("Status", "Rohtranskript (maschinell, ungeprüft)"),
        ("Dauer", fmt_time(meta["audio"]["duration_s"])),
        ("Erstellt", meta["created_at"]),
        ("Modelle", ", ".join(f"{m['repo']}@{m['revision'][:10]}"
                              for m in meta["models"].values())),
        ("Audio SHA-256", meta["audio"]["sha256"]),
    ]
    for key, value in rows:
        cells = info.add_row().cells
        cells[0].text, cells[1].text = key, value

    legend = doc.add_paragraph()
    legend.add_run("Legende: ").bold = True
    marked = legend.add_run("gelb")
    marked.font.highlight_color = WD_COLOR_INDEX.YELLOW
    legend.add_run(f" = unsicher erkannt (Wahrscheinlichkeit < {LOW_CONFIDENCE:.0%}), ")
    over = legend.add_run("kursiv")
    over.italic = True
    legend.add_run(" = gleichzeitiges Sprechen.")

    for turn in transcript.turns:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        head = p.add_run(f"[{fmt_time(turn.start)}] {speaker_name(transcript, turn.speaker)}: ")
        head.bold = True
        for i, w in enumerate(turn.words):
            text = w.text.lstrip() if i == 0 else w.text
            run = p.add_run(text)
            if w.prob < LOW_CONFIDENCE:
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            if w.overlap:
                run.italic = True
    doc.save(str(path))
