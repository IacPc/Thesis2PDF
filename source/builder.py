"""Markdown -> HTML -> PDF pipeline.

Rendering is done with Python-Markdown and a paged-media stylesheet; the PDF is
produced by WeasyPrint (default) or wkhtmltopdf. No LaTeX involved.
"""

from __future__ import annotations

import base64
import datetime as _dt
import html as _html
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import fonts as _fonts
from .bibliography import Bibliography
from .render import Entry, MD_CONFIG, MD_EXTENSIONS, Rendered, render

PKG = Path(__file__).resolve().parent
TEMPLATE = PKG / "templates" / "document.html"
CSS = PKG / "assets" / "thesis.css"
LOGO = PKG / "assets" / "unipi-logo.png"
FONT_DIR = PKG / "assets" / "fonts"
EXAMPLE = PKG / "example"

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n(?:---|\.\.\.)\s*\n", re.DOTALL)

DEFAULTS = {
    "university": "Università di Pisa",
    "department": "Department of Information Engineering",
    "course": "Master di Primo Livello in Cybersecurity",
    "supervisor": "Giuseppe Lettieri",
    "supervisor-label": "Supervisor",
    "author-label": "Candidate",
    "lang": "en",
    "toc": True,
    "lof": True,
    "lot": True,
    "toc-title": "Contents",
    "lof-title": "List of Figures",
    "lot-title": "List of Tables",
    "bibliography-title": "References",
}


class BuildError(RuntimeError):
    """Raised when the document cannot be produced."""


@dataclass
class ThesisBuilder:
    source: Path
    output: Path | None = None
    bibliography: Path | None = None
    engine: str = "auto"          # auto | weasyprint | wkhtmltopdf
    font_mode: str = "auto"       # auto | brand | fallback
    font_dirs: list[Path] = field(default_factory=list)
    overrides: dict[str, str] = field(default_factory=dict)
    html_only: bool = False
    keep_build: bool = False
    verbose: bool = False
    quiet: bool = False

    # ------------------------------------------------------------------ util
    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, file=sys.stderr)

    # -------------------------------------------------------------- metadata
    def _split_front_matter(self, text: str) -> tuple[dict, str]:
        match = FRONT_MATTER_RE.match(text)
        if not match:
            return {}, text
        try:
            import yaml
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise BuildError("PyYAML is required: pip install pyyaml") from exc
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except Exception as exc:
            raise BuildError(f"Invalid YAML front matter: {exc}") from exc
        if not isinstance(meta, dict):
            raise BuildError("The YAML front matter must be a mapping of key: value pairs.")
        return meta, text[match.end():]

    @staticmethod
    def _academic_year() -> str:
        today = _dt.date.today()
        start = today.year if today.month >= 9 else today.year - 1
        return f"{start}/{start + 1}"

    def _metadata(self, front: dict) -> dict:
        meta = dict(DEFAULTS)
        meta.update({k: v for k, v in front.items() if v is not None})
        meta.update(self.overrides)
        meta.setdefault("academic-year", self._academic_year())
        if not meta.get("academic-year"):
            meta["academic-year"] = self._academic_year()
        meta.setdefault("title", self.source.stem.replace("-", " ").replace("_", " ").title())
        return meta

    # ----------------------------------------------------------------- build
    def build(self) -> Path:
        if not self.source.exists():
            raise BuildError(f"Input file not found: {self.source}")
        src = self.source.resolve()
        workdir = src.parent
        default_ext = ".html" if self.html_only else ".pdf"
        out_path = (self.output or src.with_suffix(default_ext)).resolve()

        text = src.read_text(encoding="utf-8")
        front, body_md = self._split_front_matter(text)
        meta = self._metadata(front)

        # -- bibliography ---------------------------------------------------
        if self.bibliography is None:
            declared = front.get("bibliography")
            if isinstance(declared, str) and (workdir / declared).exists():
                self.bibliography = (workdir / declared).resolve()
            elif (workdir / "references.bib").exists():
                self.bibliography = workdir / "references.bib"
        bib = Bibliography(self.bibliography)
        if self.bibliography and not bib.entries:
            self._log(f"! no entries parsed from {self.bibliography}")
        body_md = bib.substitute(body_md)
        for key in ("abstract", "acknowledgements"):
            if isinstance(meta.get(key), str):
                meta[key] = bib.substitute(meta[key])
        # -- markdown -------------------------------------------------------
        self._log(f"› markdown  {src.name}")
        rendered = render(body_md, footnotes_inline=self._resolved_engine() == "weasyprint")
        if bib.entries:
            self._log(f"  {len(bib.order)} of {len(bib.entries)} bibliography "
                      f"entries cited")
        if bib.missing:
            self._log("! citation key(s) not in the .bib: "
                      + ", ".join(sorted(bib.missing)))

        document = self._assemble(meta, rendered, bib)

        build_dir = out_path.parent / ".thesis2pdf"
        html_path = (out_path if self.html_only else build_dir / (src.stem + ".html"))
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(document, encoding="utf-8")

        if self.html_only:
            self._log(f"✓ {html_path}")
            return html_path

        try:
            self._to_pdf(html_path, out_path, workdir)
        finally:
            if not self.keep_build:
                shutil.rmtree(build_dir, ignore_errors=True)
        self._log(f"✓ {out_path}")
        return out_path

    # -------------------------------------------------------------- assembly
    def _assemble(self, meta: dict, rendered: Rendered, bib: Bibliography) -> str:
        template = TEMPLATE.read_text(encoding="utf-8")
        css = CSS.read_text(encoding="utf-8")

        parts = [self._cover(meta)]
        front_sections: list[str] = []

        toc_entries: list[Entry] = []
        if meta.get("abstract"):
            front_sections.append(
                f'<section class="abstract" id="abstract">'
                f'<h1 class="unnumbered" data-header="Abstract">Abstract</h1>'
                f"{self._md(meta['abstract'])}{self._keywords(meta)}</section>"
            )
            toc_entries.append(Entry("abstract", "", "Abstract", 1, front=True))
        if meta.get("acknowledgements"):
            front_sections.append(
                f'<section class="acknowledgements" id="acknowledgements">'
                f'<h1 class="unnumbered" data-header="Acknowledgements">Acknowledgements</h1>'
                f"{self._md(meta['acknowledgements'])}</section>"
            )
            toc_entries.append(Entry("acknowledgements", "", "Acknowledgements", 1, front=True))

        toc_entries += rendered.toc
        if bib.order:
            toc_entries.append(Entry("references", "", meta["bibliography-title"], 1))

        if _truthy(meta.get("toc")):
            front_sections.append(
                self._contents("toc", meta["toc-title"], toc_entries, plain_labels=False)
            )
        if _truthy(meta.get("lof")) and rendered.figures:
            front_sections.append(
                self._contents("lof", meta["lof-title"],
                               [Entry(e.id, f"Figure {e.label}", e.text, 2) for e in rendered.figures],
                               plain_labels=True)
            )
        if _truthy(meta.get("lot")) and rendered.tables:
            front_sections.append(
                self._contents("lot", meta["lot-title"],
                               [Entry(e.id, f"Table {e.label}", e.text, 2) for e in rendered.tables],
                               plain_labels=True)
            )

        if meta.get("dedication"):
            parts.append(f'<section class="dedication"><div>{self._md(meta["dedication"])}</div></section>')
        if front_sections:
            parts.append('<div class="frontmatter">' + "".join(front_sections) + "</div>")
        parts.append(f'<main class="body">{rendered.body}</main>')
        parts.append(bib.html(meta["bibliography-title"]))

        extra = [f'@page {{ @bottom-left {{ content: "{_css_string(meta.get("course", ""))}"; }} }}']
        if self.font_mode == "fallback":
            extra.append(_fonts.FALLBACK_CSS)
        if meta.get("extra-css"):
            extra.append(str(meta["extra-css"]))

        replacements = {
            "{{lang}}": _html.escape(str(meta.get("lang", "en")), quote=True),
            "{{title}}": _html.escape(_plain(str(meta.get("title", "Thesis")))),
            "{{fontfaces}}": _fonts.font_face_css([FONT_DIR] + list(self.font_dirs)),
            "{{css}}": css,
            "{{codecss}}": rendered.code_css,
            "{{extracss}}": "\n".join(extra),
            "{{logo}}": self._logo_src(meta),
            "{{content}}": "".join(parts),
        }
        for token, value in replacements.items():
            template = template.replace(token, value)
        return template

    # ----------------------------------------------------------------- cover
    def _cover(self, meta: dict) -> str:
        def line(value, cls, tag="p"):
            return f'<{tag} class="{cls}">{self._inline(value)}</{tag}>' if value else ""

        authors = meta.get("author") or meta.get("candidate") or ""
        if isinstance(authors, str):
            authors = [authors]
        author_html = "".join(f'<p class="person">{self._inline(a)}</p>' for a in authors)

        cosup = ""
        if meta.get("cosupervisor"):
            cosup = (f'<p class="role">Co-supervisor</p>'
                     f'<p class="person">{self._inline(meta["cosupervisor"])}</p>')

        return f"""<section class="cover">
  <div class="logo"><img src="{self._logo_src(meta)}" alt=""></div>
  {line(meta.get('university'), 'university')}
  {line(meta.get('department'), 'department')}
  {line(meta.get('course'), 'course')}
  <div class="spacer"></div>
  <hr>
  <div class="title-block">
    <h1 class="title">{self._inline(meta.get('title', ''))}</h1>
    {line(meta.get('subtitle'), 'subtitle')}
  </div>
  <hr>
  <div class="spacer"></div>
  <div class="people">
    <div class="left">
      <p class="role">{_html.escape(str(meta.get('supervisor-label', 'Supervisor')))}</p>
      <p class="person">{self._inline(meta.get('supervisor', ''))}</p>
      {cosup}
    </div>
    <div class="right">
      <p class="role">{_html.escape(str(meta.get('author-label', 'Candidate')))}</p>
      {author_html}
      {line(meta.get('student-id'), 'student-id')}
    </div>
  </div>
  <div class="accent"></div>
  {line('Academic Year ' + str(meta['academic-year']) if meta.get('academic-year') else '', 'year')}
  {line(meta.get('date'), 'date')}
</section>"""

    def _keywords(self, meta: dict) -> str:
        kw = meta.get("keywords")
        if not kw:
            return ""
        if isinstance(kw, str):
            kw = [k.strip() for k in kw.split(",")]
        joined = " · ".join(_html.escape(str(k)) for k in kw)
        return f'<p class="keywords"><span class="lbl">Keywords</span>{joined}</p>'

    def _contents(self, kind: str, title: str, entries: list[Entry], plain_labels: bool) -> str:
        rows = []
        for e in entries:
            label = (f'<span class="label">{_html.escape(_html.unescape(e.label))}</span>'
                     if e.label else "")
            level = e.level if not plain_labels else 2
            front = " front" if e.front else ""
            rows.append(
                f'<a class="lvl{min(level, 3)}{front}" href="#{e.id}">{label}'
                f'<span class="text">{_html.escape(_html.unescape(e.text))}</span>'
                f'<span class="dots"></span></a>'
            )
        return (f'<section class="contents" id="{kind}">'
                f'<h1 class="unnumbered" data-header="{_html.escape(title)}">{_html.escape(title)}</h1>'
                f'{"".join(rows)}</section>')

    # ------------------------------------------------------------- fragments
    @staticmethod
    def _md(text) -> str:
        import markdown
        return markdown.Markdown(extensions=MD_EXTENSIONS,
                                 extension_configs=MD_CONFIG).convert(str(text))

    def _inline(self, text) -> str:
        html = self._md(text).strip()
        m = re.fullmatch(r"<p>(.*)</p>", html, re.S)
        return m.group(1) if m else html

    def _logo_src(self, meta: dict) -> str:
        path = Path(str(meta["logo"])) if meta.get("logo") else LOGO
        if not path.is_absolute():
            path = (self.source.resolve().parent / path)
        if not path.exists():
            self._log(f"! logo not found: {path}")
            return ""
        mime = "image/svg+xml" if path.suffix.lower() == ".svg" else f"image/{path.suffix.lstrip('.').lower()}"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{data}"

    # --------------------------------------------------------------- engines
    def _resolved_engine(self) -> str:
        if self.engine != "auto":
            return self.engine
        try:
            import weasyprint  # noqa: F401
            return "weasyprint"
        except ModuleNotFoundError:
            return "wkhtmltopdf" if shutil.which("wkhtmltopdf") else "weasyprint"

    def _to_pdf(self, html_path: Path, out_path: Path, workdir: Path) -> None:
        engine = self._resolved_engine()
        self._log(f"› {engine}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if engine == "weasyprint":
            self._weasyprint(html_path, out_path, workdir)
        elif engine == "wkhtmltopdf":
            self._wkhtmltopdf(html_path, out_path)
        else:
            raise BuildError(f"Unknown engine: {engine}")

    def _weasyprint(self, html_path: Path, out_path: Path, workdir: Path) -> None:
        try:
            from weasyprint import HTML
        except ModuleNotFoundError as exc:
            binary = shutil.which("weasyprint")
            if not binary:
                raise BuildError(
                    "WeasyPrint is not installed.\n"
                    "  pip install weasyprint\n"
                    "On Linux it also needs Pango: sudo apt install libpango-1.0-0 "
                    "libpangoft2-1.0-0 libharfbuzz0b\n"
                    "Alternatively use --engine wkhtmltopdf."
                ) from exc
            result = subprocess.run(
                [binary, "-u", str(workdir), str(html_path), str(out_path)],
                capture_output=True, text=True)
            if result.returncode != 0:
                raise BuildError("weasyprint failed:\n" + (result.stderr or result.stdout))
            return

        import logging
        logging.getLogger("weasyprint").setLevel(
            logging.INFO if self.verbose else logging.ERROR)
        HTML(filename=str(html_path), base_url=str(workdir)).write_pdf(str(out_path))

    def _wkhtmltopdf(self, html_path: Path, out_path: Path) -> None:
        binary = shutil.which("wkhtmltopdf")
        if not binary:
            raise BuildError(
                "wkhtmltopdf not found. Install it (https://wkhtmltopdf.org/downloads.html) "
                "or use the default WeasyPrint engine (pip install weasyprint)."
            )
        self._log("  note: wkhtmltopdf ignores CSS paged-media features — no page "
                  "numbers in the TOC and no bottom-of-page footnotes. WeasyPrint "
                  "renders the design as intended.")
        cmd = [
            binary, "--quiet", "--enable-local-file-access",
            "--page-size", "A4",
            "--margin-top", "22mm", "--margin-bottom", "20mm",
            "--margin-left", "27mm", "--margin-right", "22mm",
            "--footer-font-size", "8", "--footer-right", "[page]",
            "--footer-spacing", "6",
            "--print-media-type",
            str(html_path), str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise BuildError("wkhtmltopdf failed:\n" + (result.stderr or result.stdout))

    # ----------------------------------------------------------------- tools
    @staticmethod
    def tool_status() -> dict[str, str]:
        status: dict[str, str] = {}
        for module in ("markdown", "yaml", "pygments", "weasyprint"):
            try:
                mod = __import__(module)
                status[module] = getattr(mod, "__version__", "installed")
            except Exception as exc:  # noqa: BLE001 - report any import problem
                status[module] = f"NOT AVAILABLE ({exc.__class__.__name__})"
        status["wkhtmltopdf"] = shutil.which("wkhtmltopdf") or "not found (optional)"
        return status


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "0", "off")
    return bool(value)


def _plain(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _css_string(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def build(source, output=None, **kwargs) -> Path:
    """Convenience wrapper: build('thesis.md', 'thesis.pdf')."""
    return ThesisBuilder(Path(source), Path(output) if output else None, **kwargs).build()


def scaffold(target: Path) -> Path:
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(EXAMPLE.iterdir()):
        dest = target / item.name
        if dest.exists():
            continue
        shutil.copytree(item, dest) if item.is_dir() else shutil.copy2(item, dest)
    return target


def watch(builder: ThesisBuilder, interval: float = 1.0) -> None:  # pragma: no cover
    import time

    watched = [builder.source] + ([builder.bibliography] if builder.bibliography else [])
    stamps: dict[Path, float] = {}
    while True:
        for path in list(watched):
            if path and Path(path).exists():
                mtime = os.path.getmtime(path)
                if stamps.get(path) != mtime:
                    stamps[path] = mtime
                    try:
                        builder.build()
                    except BuildError as exc:
                        print(exc, file=sys.stderr)
        time.sleep(interval)
