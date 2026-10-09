"""The steps of the interview method and what counts as done for each interview.

Pure functions without I/O, so the logic is unit-testable. The texts are shown in the
website's "Ablauf" page; the server decides what is done, the page only shows it.
"""

from __future__ import annotations

from typing import Any

STEPS: list[dict[str, str]] = [
    {"id": "guide", "title": "Leitfaden festlegen",
     "text": "Die Fragen des Leitfadens eingeben oder als Datei laden. Jede Frage bekommt "
             "einen Code (F1, F2 …)."},
    {"id": "transcribe", "title": "Transkribieren",
     "text": "Die Aufnahme wird automatisch transkribiert. Das Ergebnis bleibt unverändert; "
             "alle Änderungen werden separat gespeichert."},
    {"id": "correct", "title": "Korrigieren",
     "text": "Falsch erkannte Wörter ersetzen (Modus „Korrigieren“). Danach „Korrektur "
             "abgeschlossen“ setzen. Korrekturen machen die Analyse veraltet: danach „Analyse "
             "aktualisieren“ wählen."},
    {"id": "smooth", "title": "Glätten (optional)",
     "text": "Füllwörter, Wortwiederholungen und Satzabbrüche entfernen (Modus „Glätten“) und "
             "jede Änderung mit einem Grund versehen. Die Analyse nutzt danach den geglätteten "
             "Text."},
    {"id": "assign", "title": "Fragen zuordnen",
     "text": "Erkannte Fragen prüfen und per Drag & Drop der richtigen Leitfadenfrage zuordnen. "
             "Fragen ohne Leitfaden-Bezug sind spontane Nachfragen."},
    {"id": "explain", "title": "Fehlende Fragen klären",
     "text": "Jede Leitfadenfrage braucht eine Antwort oder eine Begründung: Antwort an anderer "
             "Stelle verknüpfen (Vorschläge prüfen) oder Grund angeben (nicht gestellt, nicht "
             "relevant, sonstiges)."},
    {"id": "extract", "title": "Extrahieren",
     "text": "Die Kernaussagen je Frage und Gespräch in eigenen Worten festhalten. Ergebnis ist "
             "die Auswertungstabelle für die frühe Auswertung."},
    {"id": "export", "title": "Exportieren",
     "text": "Auswertungstabelle als Word oder CSV (Excel) herunterladen."},
]

CELL_STATUSES = ("asked", "answered_elsewhere", "omitted", "explained", "skipped", "missing")


def interview_row(i: dict[str, Any], guide_codes: list[str]) -> dict[str, Any]:
    """Progress of one interview. ``i``: id, transcribed, reviewed, edits (store rows),
    edits_stale, cells ({guide code: cell status}; a code without an entry counts as
    missing), unassigned (number of questions not matched to the guide), extracts (count)."""
    status = {code: i["cells"].get(code, "missing") for code in guide_codes}
    counts = {s: sum(v == s for v in status.values()) for s in CELL_STATUSES}
    smoothing = sum(e["kind"] == "smoothing" for e in i["edits"])
    return {
        "id": i["id"],
        "transcribed": i["transcribed"],
        "reviewed": i["reviewed"],
        "corrections": sum(e["kind"] == "correction" for e in i["edits"]),
        "smoothing": smoothing,
        "edits_stale": i["edits_stale"],
        "asked": counts["asked"],
        "answered_elsewhere": counts["answered_elsewhere"],
        "omitted": counts["omitted"],
        "explained": counts["explained"],
        "missing": [code for code in guide_codes if status[code] == "missing"],
        "unassigned": i["unassigned"],
        "extracts": i["extracts"],
        "done": {
            "transcribe": i["transcribed"],
            "correct": i["reviewed"],
            "smooth": smoothing > 0,
            "assign": i["transcribed"] and i["unassigned"] == 0,
            # without a guide there is nothing to explain yet
            "explain": i["transcribed"] and bool(guide_codes) and counts["missing"] == 0,
            "extract": i["extracts"] > 0,
        },
    }


def workflow_state(guide_codes: list[str], interviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Steps and per-interview progress for the "Ablauf" page (see :func:`interview_row`)."""
    return {"guide_questions": len(guide_codes), "steps": STEPS,
            "interviews": [interview_row(i, guide_codes) for i in interviews]}
