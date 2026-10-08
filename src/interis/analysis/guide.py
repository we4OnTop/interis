"""Interview guide (Leitfaden) as a simple Markdown file.

Format::

    # Leitfaden Masterarbeit            (optional title)
    ## Einstieg                          (section)
    - F1: Erzählen Sie mir doch zuerst, wie Ihr Arbeitsalltag aussieht.
      ~ Wie sieht ein typischer Arbeitstag bei Ihnen aus?      (alternative wording)
      > Seit wann arbeiten Sie dort?                            (planned probe / Nachfrage)
    - Welche Rolle spielt KI in Ihrer Arbeit?                  (code is generated: F2)

Codes are optional. A question without one gets the next number above the highest code of
the guide (explicit codes never change). Saving a guide in the website writes these codes
into the text (:func:`label_guide`), so they stay with their question when the guide is edited.
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

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""] if self.title else []
        section = None
        for q in self.questions:
            if q.section and q.section != section:
                section = q.section
                lines += ["", f"## {section}"]
            lines.append(f"- {q.code}: {q.text}")
            lines += [f"  ~ {v}" for v in q.variants]
            lines += [f"  > {p}" for p in q.probes]
        return "\n".join(lines).strip() + "\n"


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

    top = max((_number(q.code) for q in questions if q.code), default=0)
    for q in questions:
        if not q.code:
            top += 1
            q.code = f"F{top}"
    codes = [q.code for q in questions]
    duplicates = sorted({c for c in codes if codes.count(c) > 1})
    if duplicates:
        raise GuideError(f"duplicate question codes: {duplicates}")
    if not questions:
        raise GuideError("the guide contains no questions (lines starting with '- ')")
    return Guide(title, questions)


def _number(code: str) -> int:
    m = re.search(r"\d+", code)
    return int(m.group()) if m else 0


def label_guide(text: str) -> str:
    """The guide text with the codes of its unlabelled questions written in, as
    :func:`parse_guide` numbers them. Everything else is kept as it is."""
    codes = iter([q.code for q in parse_guide(text).questions])
    out = []
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if stripped and not stripped.startswith(("## ", "# ", "~", ">")) \
                and (m := _ITEM.match(line.rstrip())):
            code = next(codes)
            if not _CODE.match(m.group(1).strip()):
                line = re.sub(r"^(\s*(?:[-*]|\d+[.)])\s+)", rf"\g<1>{code}: ", line.rstrip(),
                              count=1)
        out.append(line + raw[len(raw.rstrip("\r\n")):])
    return "".join(out)


def load_guide(path: Path) -> Guide:
    # utf-8-sig: Windows editors (Notepad, PowerShell) often write a BOM
    return parse_guide(Path(path).read_text(encoding="utf-8-sig"))


def docx_to_guide_text(data: bytes) -> str:
    """Turn a Word interview guide into the Markdown format above, as a starting point
    for editing: headings become sections, paragraphs and table cells ending with "?" or
    formatted as list items become questions, everything else is kept as plain text
    (which the parser ignores)."""
    import io

    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    lines: list[str] = []
    seen: set[str] = set()

    def add(p: Paragraph) -> None:
        text = " ".join(p.text.split())
        if not text:
            return
        style = (p.style.name if p.style is not None else "").lower()
        if style.startswith(("heading", "überschrift", "title", "titel")):
            lines.extend(["", f"## {text}"])
        elif text.endswith("?") or "list" in style or "liste" in style:
            if text not in seen:  # merged table cells repeat their text
                seen.add(text)
                lines.append(f"- {text.lstrip('-•*– ').strip()}")
        else:
            lines.append(text)

    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            add(Paragraph(child, doc))
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        add(p)
    return "\n".join(lines).strip() + "\n"
