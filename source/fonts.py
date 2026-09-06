"""Font handling for the HTML pipeline.

Two ways to get the brand faces into the PDF:

1. installed system-wide (fontconfig) — nothing to do, the CSS stack finds them;
2. dropped as files into `thesis2pdf/assets/fonts/` (or --fonts-dir) — we emit
   @font-face rules pointing at them, so the build is self-contained.

Without either, the stylesheet falls back to Helvetica/Arial.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

BRAND_FAMILIES = ("Inter", "Titillium Web")
FONT_SUFFIXES = (".ttf", ".otf", ".woff2", ".woff")

FALLBACK_CSS = """:root {
  --sans: "Helvetica Neue", Helvetica, Arial, sans-serif;
  --text: "Helvetica Neue", Helvetica, Arial, sans-serif;
}"""

INSTALL_HINT = """Brand fonts not found. Either install them system-wide:

  Google Fonts   https://fonts.google.com/specimen/Titillium+Web
                 https://fonts.google.com/specimen/Inter
  Debian/Ubuntu  sudo apt install fonts-inter fonts-titillium-web
  any Linux      copy the .ttf files to ~/.local/share/fonts && fc-cache -f

…or simply drop the .ttf files into thesis2pdf/assets/fonts/ (no install
needed). Meanwhile the document is typeset with Helvetica/Arial."""


def installed_families() -> set[str] | None:
    """Families known to fontconfig, or None when fontconfig is unavailable."""
    fc = shutil.which("fc-list")
    if not fc:
        return None
    try:
        out = subprocess.run([fc, ":", "family"], capture_output=True,
                             text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    families: set[str] = set()
    for line in out.splitlines():
        for name in line.split(","):
            if name.strip():
                families.add(name.strip())
    return families


def _describe(path: Path) -> tuple[str, int, str]:
    """Guess (family, weight, style) from a font file name."""
    stem = path.stem.replace("_", "-")
    family = "Titillium Web" if "titillium" in stem.lower() else (
        "Inter" if "inter" in stem.lower() else stem.split("-")[0]
    )
    low = stem.lower()
    weight = 400
    for needle, value in (("thin", 200), ("light", 300), ("regular", 400), ("medium", 500),
                          ("semibold", 600), ("bold", 700), ("black", 900)):
        if needle in low:
            weight = value
    if "semibold" in low:
        weight = 600
    style = "italic" if "italic" in low or "oblique" in low else "normal"
    return family, weight, style


def font_face_css(dirs: list[Path]) -> str:
    rules: list[str] = []
    for directory in dirs:
        if not directory or not Path(directory).is_dir():
            continue
        for path in sorted(Path(directory).iterdir()):
            if path.suffix.lower() not in FONT_SUFFIXES:
                continue
            family, weight, style = _describe(path)
            fmt = {".ttf": "truetype", ".otf": "opentype",
                   ".woff2": "woff2", ".woff": "woff"}[path.suffix.lower()]
            rules.append(
                f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
                f'font-style: {style}; src: url("{path.resolve().as_uri()}") format("{fmt}"); }}'
            )
    return "\n".join(rules)


def status(font_dirs: list[Path]) -> tuple[bool, str]:
    """(brand fonts available, human-readable description)."""
    embedded = font_face_css(font_dirs)
    if embedded:
        return True, f"{embedded.count('@font-face')} font file(s) embedded from disk"
    families = installed_families()
    if families is None:
        return True, "fontconfig unavailable — relying on the CSS font stack"
    found = [f for f in BRAND_FAMILIES if f in families]
    if len(found) == len(BRAND_FAMILIES):
        return True, "Inter and Titillium Web installed system-wide"
    missing = [f for f in BRAND_FAMILIES if f not in families]
    return False, "missing: " + ", ".join(missing)
