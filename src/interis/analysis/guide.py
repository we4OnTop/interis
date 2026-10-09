"""Interview guide (Leitfaden) as a simple Markdown file.

Format::

    # Leitfaden Masterarbeit            (optional title)
    ## Einstieg                          (section)
    - F1: Erzählen Sie mir doch zuerst, wie Ihr Arbeitsalltag aussieht.
      ~ Wie sieht ein typischer Arbeitstag bei Ihnen aus?      (alternative wording)
      > Seit wann arbeiten Sie dort?                            (planned probe / Nachfrage)
      ! nur stellen, wenn der Alltag noch nicht erzählt wurde   (interviewer note, not matched)
    - Welche Rolle spielt KI in Ihrer Arbeit? [optional]       (code is generated: F2)

Tags in square brackets at the end of a question line mark it; ``[optional]``,
``[Nebenfrage]`` and ``[Impuls]`` questions may be left out, so a missing one is not an
open point of the review.

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
_TAGS = re.compile(r"(?:\s*\[[^\[\]]{1,30}\])+\s*$")
DROPPABLE = {"optional", "nebenfrage", "kürzbar", "impuls"}


@dataclass
class GuideQuestion:
    code: str
    text: str
    section: str | None = None
    variants: list[str] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    hint: str = ""

    @property
    def droppable(self) -> bool:
        return any(t.lower() in DROPPABLE for t in self.tags)


@dataclass
class Guide:
    title: str | None
    questions: list[GuideQuestion]

    @classmethod
    def from_dict(cls, d: dict) -> Guide:
        fields = GuideQuestion.__dataclass_fields__
        return cls(d.get("title"), [GuideQuestion(**{k: v for k, v in q.items() if k in fields})
                                    for q in d["questions"]])

    def by_code(self, code: str) -> GuideQuestion:
        return next(q for q in self.questions if q.code == code)

    def to_dict(self) -> dict:
        return {"title": self.title,
                "questions": [{**q.__dict__, "droppable": q.droppable} for q in self.questions]}

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", ""] if self.title else []
        section = None
        for q in self.questions:
            if q.section and q.section != section:
                section = q.section
                lines += ["", f"## {section}"]
            lines.append(f"- {q.code}: {q.text}" + "".join(f" [{t}]" for t in q.tags))
            lines += [f"  ~ {v}" for v in q.variants]
            lines += [f"  > {p}" for p in q.probes]
            lines += [f"  ! {q.hint}"] if q.hint else []
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
        elif stripped.startswith("!"):
            if not questions:
                raise GuideError(f"line {lineno}: note before any question")
            q = questions[-1]
            q.hint = f"{q.hint} {stripped[1:].strip()}".strip()
        elif m := _ITEM.match(line):
            body = m.group(1).strip()
            code_match = _CODE.match(body)
            code, qtext = (code_match.group(1), code_match.group(2)) if code_match else ("", body)
            tags = []
            if (t := _TAGS.search(qtext)) and t.start() > 0:
                tags = re.findall(r"\[([^\[\]]+)\]", t.group())
                qtext = qtext[:t.start()]
            questions.append(GuideQuestion(code, qtext.strip(), section,
                                           tags=[x.strip() for x in tags]))
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


# --- Typst guides -------------------------------------------------------------------------
# A guide written with the ``#frage(...)[...]`` / ``#impuls[...]`` template (headings ``=``)
# is turned into the format above. Codes follow the template's own numbering (F1, F2, …),
# so the printed guide and the codes match.

def _skip(s: str, i: int, close: str, code: bool) -> int:
    """Index after the bracket that closes at ``close``; ``i`` is just after the opener.
    In code mode ``"…"`` is a string; in content (``[…]``) quotes are plain text."""
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == close:
            return i + 1
        if c == "[":
            i = _skip(s, i + 1, "]", False)
        elif c == "(":
            i = _skip(s, i + 1, ")", code)
        elif c == "{":
            i = _skip(s, i + 1, "}", True)
        elif c == '"' and code:
            i += 1
            while i < len(s) and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
        else:
            i += 1
    raise GuideError("Typst: Klammer nicht geschlossen")


def _split_args(s: str) -> dict[str, str]:
    """Named arguments ``key: value`` of a call's argument text (top level only)."""
    parts, start, i = [], 0, 0
    while i < len(s):
        c = s[i]
        if c == ",":
            parts.append(s[start:i])
            start = i + 1
            i += 1
        elif c in "[({":
            i = _skip(s, i + 1, {"[": "]", "(": ")", "{": "}"}[c], c != "[")
        elif c == '"':
            i = _skip(s, i + 1, '"', False)
        else:
            i += 1
    parts.append(s[start:])
    out: dict[str, str] = {}
    for part in parts:
        key, sep, value = part.partition(":")
        if sep and key.strip().isidentifier():
            out[key.strip()] = value.strip()
    return out


def _blocks(value: str) -> list[str]:
    """The ``[…]`` content blocks of an argument value (one, or an array of them)."""
    out, i = [], 0
    while (i := value.find("[", i)) != -1:
        end = _skip(value, i + 1, "]", False)
        out.append(value[i + 1:end - 1])
        i = end
    return out


def _plain(content: str) -> str:
    """Typst markup to plain text: function calls keep only their content block."""
    out, i = [], 0
    while i < len(content):
        c = content[i]
        if c == "\\" and i + 1 < len(content):
            out.append(content[i + 1])
            i += 2
        elif c == "#" and (m := re.match(r"#[A-Za-z_][\w.-]*", content[i:])):
            i += m.end()
            if i < len(content) and content[i] == "(":
                i = _skip(content, i + 1, ")", True)
            if i < len(content) and content[i] == "[":
                end = _skip(content, i + 1, "]", False)
                out.append(_plain(content[i + 1:end - 1]))
                i = end
        elif c in "*_":
            i += 1
        else:
            out.append(c)
            i += 1
    return " ".join("".join(out).split())


def typst_to_guide_text(text: str) -> str:
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    lines: list[str] = []
    for m in re.finditer(r"\btitel:\s*\[", text):  # the first one is often the empty default
        if title := _plain(text[m.end():_skip(text, m.end(), "]", False) - 1]):
            lines += [f"# {title}", ""]
            break
    n_frage = n_impuls = 0
    token = re.compile(r"(?m)^[ \t]*(=+)[ \t]+(.+)$|#(frage|impuls|rangfolge)(?![\w-])")
    pos = 0
    while m := token.search(text, pos):
        pos = m.end()
        if m.group(1):
            lines += ["", f"## {_plain(m.group(2))}"]
            continue
        kind, args = m.group(3), {}
        if pos < len(text) and text[pos] == "(":
            end = _skip(text, pos + 1, ")", True)
            args = _split_args(text[pos + 1:end - 1])
            pos = end
        body = ""
        if pos < len(text) and text[pos] == "[":
            end = _skip(text, pos + 1, "]", False)
            body, pos = text[pos + 1:end - 1], end
        if kind == "rangfolge":
            items = [_plain(b) for b in _blocks(text[m.end():pos])]
            lines.append("Rangfolge: " + " · ".join(i for i in items if i))
            continue
        if kind == "impuls":
            plain = _plain(body)
            if "?" not in plain:  # a transition, not a question: kept as a note
                lines.append(f"Impuls: {plain}")
                continue
            n_impuls += 1
            lines.append(f"- I{n_impuls}: {plain} [Impuls]")
            continue
        n_frage += 1
        # "#underline[A] / B": two wordings of the same question
        variants = [_plain(v) for v in re.split(r"(?<=\])\s*/\s*", body)] \
            if "#underline" in body else [_plain(body)]
        tags = [t for flag, t in (("optional", "optional"), ("kuerzbar", "Nebenfrage"))
                if args.get(flag) == "true"]
        lines.append(f"- F{n_frage}: {variants[0]}" + "".join(f" [{t}]" for t in tags))
        lines += [f"  ~ {v}" for v in variants[1:] if v]
        lines += [f"  > {_plain(b)}" for b in _blocks(args.get("nachfragen", ""))]
        hint = " ".join(_plain(b) for b in _blocks(args.get("hinweis", "")))
        chapter = " ".join(_plain(b) for b in _blocks(args.get("kapitel", "")))
        if chapter:
            hint = f"{hint} (Kapitel {chapter})".strip()
        if hint:
            lines.append(f"  ! {hint}")
    if not n_frage and not n_impuls:
        raise GuideError("Typst: keine #frage(...)[...] gefunden")
    return "\n".join(lines).strip() + "\n"
