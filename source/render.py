"""Markdown -> HTML, with thesis structure applied.

Everything the LaTeX pipeline used to do with counters and floats happens here:
chapter/section numbering, appendices, figure and table numbering, captions,
lists of figures/tables, and page-bottom footnotes for WeasyPrint.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

MD_EXTENSIONS = [
    "extra",        # tables, footnotes, attr_list, def_list, fenced_code, md_in_html, abbr
    "sane_lists",
    "smarty",
    "admonition",
    "toc",
    "codehilite",
]
MD_CONFIG = {
    "codehilite": {"css_class": "codehilite", "guess_lang": False, "linenums": False},
    "toc": {"permalink": False},
    "smarty": {"smart_dashes": True, "smart_quotes": True},
}

TOKEN_RE = re.compile(
    r"(?P<heading><h(?P<lvl>[1-4])(?P<hattrs>[^>]*)>(?P<htext>.*?)</h(?P=lvl)>)"
    r"|(?P<figure><p>\s*(?P<img><img[^>]*>)\s*</p>)"
    r"|(?P<table><table[^>]*>.*?</table>)",
    re.S,
)
TABLE_CAPTION_RE = re.compile(r"\s*<p>\s*(?:Table|Tabella)\s*:\s*(?P<cap>.*?)</p>", re.S)
CLASS_RE = re.compile(r'class="([^"]*)"')
ID_RE = re.compile(r'id="([^"]*)"')
ALT_RE = re.compile(r'alt="([^"]*)"')
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Entry:
    id: str
    label: str
    text: str
    level: int = 1
    front: bool = False   # paginated in roman numerals


@dataclass
class Rendered:
    body: str
    toc: list[Entry] = field(default_factory=list)
    figures: list[Entry] = field(default_factory=list)
    tables: list[Entry] = field(default_factory=list)
    code_css: str = ""


def _classes(attrs: str) -> set[str]:
    m = CLASS_RE.search(attrs or "")
    return set(m.group(1).split()) if m else set()


def _strip_tags(text: str) -> str:
    """Plain text of an HTML fragment, with entities decoded to real characters."""
    return _html.unescape(re.sub(r"\s+", " ", TAG_RE.sub("", text)).strip())


def _ensure_id(attrs: str, fallback: str) -> tuple[str, str]:
    m = ID_RE.search(attrs or "")
    if m:
        return attrs, m.group(1)
    return f'{attrs} id="{fallback}"', fallback


def render(text: str, footnotes_inline: bool = True) -> Rendered:
    import markdown

    md = markdown.Markdown(extensions=MD_EXTENSIONS, extension_configs=MD_CONFIG)
    html = md.convert(text)
    if footnotes_inline:
        html = _inline_footnotes(html)
    out = _structure(html)
    out.code_css = _pygments_css()
    return out


# --------------------------------------------------------------- structure --
def _structure(html: str) -> Rendered:
    result = Rendered(body="")
    pieces: list[str] = []
    chapter_no = 0
    appendix = False
    counters = [0, 0, 0]      # section, subsection, subsubsection
    fig_no = tab_no = 0
    chapter_label = ""
    pos = 0

    while True:
        m = TOKEN_RE.search(html, pos)
        if not m:
            pieces.append(html[pos:])
            break
        pieces.append(html[pos : m.start()])
        pos = m.end()

        # ---------------------------------------------------------- heading --
        if m.group("heading"):
            level = int(m.group("lvl"))
            attrs = m.group("hattrs") or ""
            inner = m.group("htext")
            classes = _classes(attrs)
            plain = _strip_tags(inner)

            if level == 1 and "appendix" in classes and not appendix:
                appendix = True
                chapter_no = 0

            numbered = "unnumbered" not in classes
            label = ""
            if numbered:
                if level == 1:
                    chapter_no += 1
                    counters = [0, 0, 0]
                    fig_no = tab_no = 0
                    chapter_label = LETTERS[(chapter_no - 1) % 26] if appendix else str(chapter_no)
                    label = chapter_label
                else:
                    counters[level - 2] += 1
                    for i in range(level - 1, 3):
                        counters[i] = 0
                    parts = [chapter_label] + [str(c) for c in counters[: level - 1] if c]
                    label = ".".join(parts)
            elif level == 1:
                chapter_label = chapter_label or ""

            attrs, hid = _ensure_id(attrs, f"h{level}-{len(pieces)}")
            kicker = ""
            if level == 1:
                head_word = "Appendix" if appendix else "Chapter"
                if numbered:
                    kicker = f'<p class="kicker">{head_word} {label}</p>'
                    header_string = f"{head_word} {label} — {plain}"
                else:
                    header_string = plain
                number_html = f'<span class="num">{label}.</span> ' if numbered else ""
                pieces.append(
                    f'{kicker}<h1{attrs} data-header="{_escape(header_string)}">'
                    f"{number_html}{inner}</h1>"
                )
            else:
                number_html = f'<span class="num">{label}</span> ' if numbered else ""
                pieces.append(f"<h{level}{attrs}>{number_html}{inner}</h{level}>")

            if numbered or level == 1:
                result.toc.append(Entry(hid, label, plain, level))

        # ----------------------------------------------------------- figure --
        elif m.group("figure"):
            img = m.group("img")
            alt = _html.unescape(
                (ALT_RE.search(img).group(1) if ALT_RE.search(img) else "").strip()
            )
            fig_no += 1
            label = f"{chapter_label}.{fig_no}" if chapter_label else str(fig_no)
            fid = f"fig-{label.replace('.', '-')}"
            caption = (
                f'<figcaption><span class="lbl">Figure {label}.</span>'
                f" {_escape_text(alt)}</figcaption>"
                if alt
                else ""
            )
            pieces.append(f'<figure id="{fid}">{img}{caption}</figure>')
            if alt:
                result.figures.append(Entry(fid, label, alt))

        # ------------------------------------------------------------ table --
        else:
            table = m.group("table")
            caption = ""
            cap_match = TABLE_CAPTION_RE.match(html, pos)
            if cap_match:
                caption = cap_match.group("cap").strip()
                pos = cap_match.end()
            tab_no += 1
            label = f"{chapter_label}.{tab_no}" if chapter_label else str(tab_no)
            tid = f"tbl-{label.replace('.', '-')}"
            table = _align_numeric_cells(table)
            cap_html = (
                f'<figcaption><span class="lbl">Table {label}.</span> {caption}</figcaption>'
                if caption
                else ""
            )
            pieces.append(f'<figure class="table" id="{tid}">{cap_html}{table}</figure>')
            if caption:
                result.tables.append(Entry(tid, label, caption))

    result.body = "".join(pieces)
    return result


NUMERIC_RE = re.compile(r"\A[\s$€£]*[-+]?[\d.,]+\s*[%×x]?\s*\Z")


def _align_numeric_cells(table: str) -> str:
    """Right-align cells that hold numbers, like a typeset thesis table."""

    def cell(m: re.Match) -> str:
        open_tag, inner, close = m.group(1), m.group(2), m.group(3)
        if "align" in open_tag or "class=" in open_tag:
            return m.group(0)
        if NUMERIC_RE.match(_strip_tags(inner)) and _strip_tags(inner):
            return f'{open_tag[:-1]} class="num-cell">{inner}{close}'
        return m.group(0)

    return re.sub(r"(<td[^>]*>)(.*?)(</td>)", cell, table, flags=re.S)


def _escape(text: str) -> str:
    """Escape for an attribute value (text must already be decoded)."""
    return (text.replace("&", "&amp;").replace('"', "&quot;")
                .replace("<", "&lt;").replace(">", "&gt;"))


def _escape_text(text: str) -> str:
    """Escape for element content, leaving quotes as typed."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------- footnotes --
FOOTNOTE_BLOCK_RE = re.compile(r'<div class="footnote">.*</div>', re.S)
FOOTNOTE_ITEM_RE = re.compile(r'<li id="(?P<id>fn:[^"]+)">(?P<body>.*?)</li>', re.S)
FOOTNOTE_REF_RE = re.compile(
    r'<sup id="fnref:(?P<key>[^"]+)">\s*<a[^>]*href="#fn:(?P=key)"[^>]*>.*?</a>\s*</sup>', re.S
)
BACKREF_RE = re.compile(r'<a[^>]*class="footnote-backref".*?</a>', re.S)


def _inline_footnotes(html: str) -> str:
    """Move Python-Markdown endnotes back inline as CSS `float: footnote`."""
    block = FOOTNOTE_BLOCK_RE.search(html)
    if not block:
        return html
    notes = {
        m.group("id"): BACKREF_RE.sub("", m.group("body")).strip()
        for m in FOOTNOTE_ITEM_RE.finditer(block.group(0))
    }
    if not notes:
        return html

    def replace(m: re.Match) -> str:
        body = notes.get("fn:" + m.group("key"))
        if body is None:
            return m.group(0)
        body = re.sub(r"\A<p>(.*)</p>\Z", r"\1", body.strip(), flags=re.S)
        return f'<span class="footnote">{body}</span>'

    html = FOOTNOTE_REF_RE.sub(replace, html)
    return FOOTNOTE_BLOCK_RE.sub("", html)


def _pygments_css() -> str:
    try:
        from pygments.formatters import HtmlFormatter
    except ModuleNotFoundError:
        return ""
    return HtmlFormatter(style="friendly").get_style_defs(".codehilite")
