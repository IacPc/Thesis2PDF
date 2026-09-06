"""Minimal BibTeX support: [@key] citations -> numeric references.

No LaTeX, no biber. Entries are parsed with a small brace-aware scanner and
formatted in an IEEE-like numeric style, ordered by first appearance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# [@key] · [@a; @b] · [see @key, p. 12] · bare @key (only for keys in the .bib)
CITE_RE = re.compile(r"\[([^\[\]]*@[^\[\]]+)\]")
BARE_CITE_RE = re.compile(r"(?<![\w@/])@([A-Za-z][A-Za-z0-9_:.+-]*)")
KEY_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_:.#$%&+?<>~/-]*)")
FENCE_RE = re.compile(r"^(?P<f>```+|~~~+).*?^(?P=f)\s*$", re.M | re.S)
CODE_SPAN_RE = re.compile(r"`[^`\n]+`")
ENTRY_RE = re.compile(r"@(?P<type>\w+)\s*\{", re.S)
LATEX_ACCENTS = {
    r"\&": "&", r"\_": "_", r"\%": "%", r"\#": "#", r"\$": "$",
    "--": "–", "~": " ", "\\": "",
}


@dataclass
class Reference:
    key: str
    type: str
    fields: dict[str, str] = field(default_factory=dict)


def parse_bib(path: Path) -> dict[str, Reference]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    entries: dict[str, Reference] = {}
    pos = 0
    while True:
        m = ENTRY_RE.search(text, pos)
        if not m:
            break
        body, end = _read_braced(text, m.end() - 1)
        pos = end
        if m.group("type").lower() in ("comment", "preamble", "string"):
            continue
        key, _, rest = body.partition(",")
        entries[key.strip()] = Reference(key.strip(), m.group("type").lower(), _fields(rest))
    return entries


def _read_braced(text: str, start: int) -> tuple[str, int]:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
    return text[start + 1 :], len(text)


def _fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    pos = 0
    while True:
        m = re.compile(r"(\w+)\s*=\s*").search(text, pos)
        if not m:
            break
        pos = m.end()
        if pos < len(text) and text[pos] == "{":
            value, pos = _read_braced(text, pos)
        elif pos < len(text) and text[pos] == '"':
            end = text.find('"', pos + 1)
            value, pos = text[pos + 1 : end], end + 1
        else:
            end = text.find(",", pos)
            end = len(text) if end == -1 else end
            value, pos = text[pos:end], end
        out[m.group(1).lower()] = _clean(value)
    return out


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip().strip(",").strip()
    for src, dst in LATEX_ACCENTS.items():
        value = value.replace(src, dst)
    return value.replace("{", "").replace("}", "").strip()


def _authors(raw: str) -> str:
    if not raw:
        return ""
    people = [p.strip() for p in re.split(r"\s+and\s+", raw) if p.strip()]
    formatted = []
    for person in people[:6]:
        if "," in person:
            last, _, first = person.partition(",")
        else:
            parts = person.split()
            last, first = parts[-1], " ".join(parts[:-1])
        initials = " ".join(f"{n[0]}." for n in first.split() if n)
        formatted.append(f"{initials} {last.strip()}".strip())
    if len(people) > 6:
        formatted.append("et al.")
    if len(formatted) > 1:
        return ", ".join(formatted[:-1]) + " and " + formatted[-1]
    return formatted[0] if formatted else ""


def format_reference(ref: Reference) -> str:
    f = ref.fields
    bits: list[str] = []
    authors = _authors(f.get("author") or f.get("editor", ""))
    if authors:
        bits.append(f"{authors},")
    if f.get("title"):
        bits.append(f'“{f["title"]},”')
    container = f.get("journal") or f.get("booktitle")
    if container:
        prefix = "in " if f.get("booktitle") and not f.get("journal") else ""
        bits.append(f"<em>{prefix}{container}</em>,")
    if f.get("institution") or f.get("publisher") or f.get("school"):
        bits.append(f'{f.get("institution") or f.get("publisher") or f.get("school")},')
    if f.get("volume"):
        bits.append(f'vol. {f["volume"]},')
    if f.get("number"):
        bits.append(f'no. {f["number"]},')
    if f.get("pages"):
        bits.append(f'pp. {f["pages"].replace("--", "–")},')
    if f.get("year"):
        bits.append(f'{f["year"]}.')
    line = " ".join(bits).replace(",.", ".")
    if f.get("doi"):
        line += f' doi: <a href="https://doi.org/{f["doi"]}">{f["doi"]}</a>.'
    elif f.get("url"):
        line += f' [Online]. Available: <a href="{f["url"]}">{f["url"]}</a>.'
    return line


class Bibliography:
    """Replaces [@key] in the markdown source and renders the reference list."""

    def __init__(self, path: Path | None):
        self.entries = parse_bib(path) if path else {}
        self.order: list[str] = []
        self.missing: set[str] = set()

    # ------------------------------------------------------------ citations
    def _number(self, key: str) -> str:
        if key not in self.order:
            self.order.append(key)
        return f'<a class="cite" href="#ref-{key}">{self.order.index(key) + 1}</a>'

    def substitute(self, text: str) -> str:
        """Replace citation markers, leaving code spans and code blocks alone."""
        if not self.entries:
            return text

        # protect fenced/indented code and inline code from substitution
        vault: list[str] = []

        def stash(m: re.Match) -> str:
            vault.append(m.group(0))
            return f"\x00CODE{len(vault) - 1}\x00"

        text = FENCE_RE.sub(stash, text)
        text = CODE_SPAN_RE.sub(stash, text)

        def bracket(m: re.Match) -> str:
            inner = m.group(1)
            found = [k for k in KEY_RE.findall(inner) if k in self.entries]
            self.missing.update(k for k in KEY_RE.findall(inner) if k not in self.entries)
            if not found:
                return m.group(0)
            rest = KEY_RE.sub("", inner).strip(" ;,")
            numbers = ", ".join(self._number(k) for k in found)
            return f"[{numbers}{', ' + rest if rest else ''}]"

        text = CITE_RE.sub(bracket, text)

        def bare(m: re.Match) -> str:
            key = m.group(1)
            if key not in self.entries:
                return m.group(0)
            return "[" + self._number(key) + "]"

        text = BARE_CITE_RE.sub(bare, text)

        for i, chunk in enumerate(vault):
            text = text.replace(f"\x00CODE{i}\x00", chunk)
        return text

    def report(self, text: str) -> dict:
        """Diagnostics for `thesis2pdf cites`: what is in the .bib vs. the text."""
        used = [k for k in KEY_RE.findall(text)]
        return {
            "entries": sorted(self.entries),
            "cited": [k for k in dict.fromkeys(used) if k in self.entries],
            "unknown": [k for k in dict.fromkeys(used) if k not in self.entries],
        }

    def html(self, title: str = "References") -> str:
        if not self.order:
            return ""
        items = "".join(
            f'<li id="ref-{key}"><span class="refnum">[{i + 1}]</span>'
            f"<span class=\"refbody\">{format_reference(self.entries[key])}</span></li>"
            for i, key in enumerate(self.order)
        )
        return (
            f'<section class="references" id="references">'
            f'<h1 class="unnumbered" data-header="{title}">{title}</h1>'
            f"<ol>{items}</ol></section>"
        )
