"""Interview guide (Leitfaden) as a simple Markdown file.

Format::

    # Leitfaden Masterarbeit            (optional title)
    ## Einstieg                          (section)
    - F1: Erzählen Sie mir doch zuerst, wie Ihr Arbeitsalltag aussieht.
      ~ Wie sieht ein typischer Arbeitstag bei Ihnen aus?      (alternative wording)
      > Seit wann arbeiten Sie dort?                            (planned probe / Nachfrage)
    - Welche Rolle spielt KI in Ihrer Arbeit?                  (code is generated: F2)

Codes are optional; missing ones are numbered F1, F2, … in order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$")
_CODE = re.compile(r"^([A-Za-zÄÖÜ]{0,4}\d+(?:\.\d+)*)\s*[:)]\s+(.+)$")


@dataclass
class GuideQuestion:
    code: str
    text: str
    section: str | None = None
    variants: list[str] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)


@dataclass
class Guide:
    title: str | None
    questions: list[GuideQuestion]

    def by_code(self, code: str) -> GuideQuestion:
        return next(q for q in self.questions if q.code == code)

    def to_dict(self) -> dict:
        return {"title": self.title, "questions": [q.__dict__ for q in self.questions]}


class GuideError(ValueError):
    pass


def parse_guide(text: str) -> Guide:
    title: str | None = None
    section: str | None = None
    questions: list[GuideQuestion] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            section = stripped[3:].strip()
        elif stripped.startswith("# "):
            title = stripped[2:].strip()
        elif stripped.startswith("~"):
            if not questions:
                raise GuideError(f"line {lineno}: variant before any question")
            questions[-1].variants.append(stripped[1:].strip())
        elif stripped.startswith(">"):
            if not questions:
                raise GuideError(f"line {lineno}: probe before any question")
            questions[-1].probes.append(stripped[1:].strip())
        elif m := _ITEM.match(line):
            body = m.group(1).strip()
            code_match = _CODE.match(body)
            code, qtext = (code_match.group(1), code_match.group(2)) if code_match else ("", body)
            questions.append(GuideQuestion(code, qtext.strip(), section))
        # other lines (free text, comments) are ignored

    used = {q.code for q in questions if q.code}
    n = 0
    for q in questions:
        if not q.code:
            n += 1
            while f"F{n}" in used:
                n += 1
            q.code = f"F{n}"
            used.add(q.code)
    codes = [q.code for q in questions]
    duplicates = sorted({c for c in codes if codes.count(c) > 1})
    if duplicates:
        raise GuideError(f"duplicate question codes: {duplicates}")
    if not questions:
        raise GuideError("the guide contains no questions (lines starting with '- ')")
    return Guide(title, questions)


def load_guide(path: Path) -> Guide:
    # utf-8-sig: Windows editors (Notepad, PowerShell) often write a BOM
    return parse_guide(Path(path).read_text(encoding="utf-8-sig"))
