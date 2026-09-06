"""Command line interface: thesis2pdf input.md -o output.pdf"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly (PyCharm "Run cli.py", python thesis2pdf/cli.py)
# as well as via the installed `thesis2pdf` entry point or `python -m thesis2pdf`.
if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "thesis2pdf"

from . import __version__
from . import fonts as _fonts
from .builder import FONT_DIR, BuildError, ThesisBuilder, scaffold

DESCRIPTION = """\
Convert a Markdown thesis into a PDF styled for the
Master di Primo Livello in Cybersecurity, Università di Pisa.
Pipeline: Markdown -> HTML/CSS -> PDF (WeasyPrint or wkhtmltopdf)."""


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="thesis2pdf",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  thesis2pdf thesis.md -o thesis.pdf
  thesis2pdf thesis.md --html -o preview.html     # inspect the HTML in a browser
  thesis2pdf thesis.md --engine wkhtmltopdf
  thesis2pdf thesis.md -M "title=Zero Trust in OT Networks" -M student-id=123456
  thesis2pdf init my-thesis
  thesis2pdf cites thesis.md                      # which [@keys] resolve, which do not
  thesis2pdf doctor
""",
    )
    p.add_argument("input", nargs="?",
                   help="Markdown source file (or: init / doctor / cites)")
    p.add_argument("target", nargs="?",
                   help="destination folder for `init`")
    p.add_argument("-o", "--output",
                   help="output path (default: alongside the input)")
    p.add_argument("--bib",
                   help="BibTeX file (default: bibliography: in the front matter, "
                                 "or references.bib next to the input)")
    p.add_argument("--engine", choices=("auto", "weasyprint", "wkhtmltopdf"),
                   default="auto",
                   help="PDF engine (default: auto = WeasyPrint when installed)")
    p.add_argument("--html", action="store_true", help="write the HTML instead of a PDF")
    p.add_argument("--fonts", choices=("auto", "brand", "fallback"),
                   default="auto",
                   help="fallback = force Helvetica/Arial instead of the brand faces")
    p.add_argument("--fonts-dir", action="append", default=[], metavar="DIR",
                   help="folder of .ttf/.woff2 files to embed; repeatable")
    p.add_argument("-M", "--metadata", action="append", default=[],
                   metavar="KEY=VALUE",
                   help="override a metadata field; repeatable")
    p.add_argument("--keep-build", action="store_true",
                   help="keep the intermediate HTML")
    p.add_argument("--watch", action="store_true", help="rebuild on every save")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version",
                   version=f"thesis2pdf {__version__}")
    return p


def _doctor(font_dirs: list[Path]) -> int:
    print("thesis2pdf doctor\n")
    ok = True
    status = ThesisBuilder.tool_status()
    for name, state in status.items():
        required = name in ("markdown", "yaml", "pygments")
        bad = state.startswith("NOT AVAILABLE") or state.startswith("not found")
        if bad and required:
            ok = False
        mark = "✗" if (bad and required) else ("–" if bad else "✓")
        print(f"  {mark} {name:<12} {state}")

    engine_ok = (not status["weasyprint"].startswith("NOT AVAILABLE")
                 or not status["wkhtmltopdf"].startswith("not found"))
    if not engine_ok:
        ok = False
        print("\n  ✗ no PDF engine available — pip install weasyprint")

    brand, note = _fonts.status([FONT_DIR] + font_dirs)
    print(f"\n  {'✓' if brand else '–'} fonts        {note}")
    if not brand:
        print("\n" + _fonts.INSTALL_HINT)
    if not ok:
        print("\nInstall the missing pieces (pip install -e .), then run doctor again.")
    return 0 if ok else 1


def _cites(source: Path, bib_path: Path | None) -> int:
    from .bibliography import Bibliography
    from .builder import FRONT_MATTER_RE

    if not source or not source.exists():
        print("usage: thesis2pdf cites THESIS.md [--bib references.bib]", file=sys.stderr)
        return 2
    text = source.read_text(encoding="utf-8")
    if bib_path is None:
        m = FRONT_MATTER_RE.match(text)
        declared = None
        if m:
            found = [line.split(":", 1)[1].strip().strip("'\"")
                     for line in m.group(1).splitlines()
                     if line.strip().startswith("bibliography:")]
            declared = found[0] if found else None
        candidate = source.parent / (declared or "references.bib")
        bib_path = candidate if candidate.exists() else None
    if bib_path is None:
        print("no .bib found — pass --bib references.bib", file=sys.stderr)
        return 1

    bib = Bibliography(bib_path)
    info = bib.report(text)
    print(f"bibliography: {bib_path}  ({len(info['entries'])} entries parsed)")
    if not info["entries"]:
        print("  ✗ nothing parsed — is the file valid BibTeX?")
        return 1
    print(f"\ncited in {source.name} ({len(info['cited'])}):")
    for key in info["cited"]:
        print(f"  ✓ {key}")
    if info["unknown"]:
        print(f"\nnot found in the .bib ({len(info['unknown'])}):")
        for key in info["unknown"]:
            print(f"  ✗ {key}")
    if not info["cited"]:
        print("\n  no citation resolved. Write them as [@key] — for example "
              f"[@{info['entries'][0]}] — and keep them out of code blocks.")
    uncited = [k for k in info["entries"] if k not in info["cited"]]
    if uncited:
        print(f"\nnever cited ({len(uncited)}): " + ", ".join(uncited))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    font_dirs = [Path(d) for d in args.fonts_dir]

    if args.input == "doctor":
        return _doctor(font_dirs)
    if args.input == "cites":
        return _cites(Path(args.target or ""), Path(args.bib) if args.bib else None)
    if args.input == "init":
        target = scaffold(Path(args.target or "thesis"))
        print(f"✓ sample thesis created in {target}/\n"
              f"  cd {target} && thesis2pdf thesis.md -o thesis.pdf")
        return 0
    if not args.input:
        _parser().print_help()
        return 1

    overrides: dict[str, str] = {}
    for item in args.metadata:
        if "=" not in item:
            print(f"error: -M expects KEY=VALUE, got {item!r}", file=sys.stderr)
            return 2
        key, value = item.split("=", 1)
        overrides[key.strip()] = value

    builder = ThesisBuilder(
        source=Path(args.input),
        output=Path(args.output) if args.output else None,
        bibliography=Path(args.bib) if args.bib else None,
        engine=args.engine,
        font_mode=args.fonts,
        font_dirs=font_dirs,
        overrides=overrides,
        html_only=args.html,
        keep_build=args.keep_build,
        verbose=args.verbose,
        quiet=args.quiet,
    )

    try:
        if args.watch:
            from .builder import watch
            print("watching for changes — Ctrl-C to stop")
            watch(builder)
            return 0
        builder.build()
    except BuildError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
