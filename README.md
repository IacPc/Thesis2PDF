# thesis2pdf

Turns a Markdown manuscript into a print-ready thesis PDF styled for the
**Master di Primo Livello in Cybersecurity — Università di Pisa**.

Pipeline: **Markdown → HTML/CSS → PDF** (WeasyPrint, or wkhtmltopdf). No LaTeX,
no pandoc — `pip install` is all it takes. The layout follows the university's
visual identity: Titillium Web headings, Inter text, blue `#225DD7` / navy
`#1B315C`, the Università di Pisa mark on the cover and in the running header.

The document is in English; only the course name stays in Italian.

---

## 1. Install

```bash
pip install -e .
thesis2pdf doctor        # checks every dependency and the fonts
```

Linux also needs the Pango libraries WeasyPrint renders with:

```bash
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi-dev
```

Fonts are optional: install **Inter** and **Titillium Web** system-wide, or drop
the `.ttf` files into `thesis2pdf/assets/fonts/` (they are embedded
automatically). Without them the text falls back to Helvetica/Arial.

## 2. Use

```bash
thesis2pdf thesis.md -o thesis.pdf
thesis2pdf init my-thesis                 # scaffold a complete sample thesis
thesis2pdf thesis.md --html -o out.html   # inspect the HTML in a browser
thesis2pdf thesis.md --watch              # rebuild on every save
thesis2pdf thesis.md -M student-id=654321 # override any metadata field
python -m thesis2pdf thesis.md            # without installing
```

Options: `--bib FILE`, `--engine auto|weasyprint|wkhtmltopdf`,
`--fonts auto|fallback`, `--fonts-dir DIR`, `--keep-build`, `-v`, `-q`.

> `--engine wkhtmltopdf` exists for machines where WeasyPrint cannot be
> installed. wkhtmltopdf ignores CSS paged media, so you lose page numbers in
> the table of contents, bottom-of-page footnotes and the running header.
> WeasyPrint renders the design as intended.

## 3. Front matter

Everything on the cover comes from the YAML block at the top of the `.md`.
Only `title` and `author` are really yours to fill in — the rest already
defaults to this course.

```yaml
---
title: "Detecting Lateral Movement with eBPF Host Telemetry"
subtitle: "A low-overhead sensor for enterprise estates"   # optional
author: "Marco Rossi"
student-id: "Matr. 654321"                                  # optional
supervisor: "Giuseppe Lettieri"
cosupervisor: "…"                                           # optional
university: "Università di Pisa"
department: "Department of Information Engineering"
course: "Master di Primo Livello in Cybersecurity"
academic-year: "2025/2026"      # auto-computed when omitted
date: "Pisa, March 2026"
bibliography: references.bib
keywords: [lateral movement, eBPF, detection engineering]
abstract: |                     # multi-paragraph markdown is fine
  …
acknowledgements: |             # optional
  …
dedication: "To …"              # optional
toc: true
lof: true                       # list of figures
lot: true                       # list of tables
logo: path/to/other-logo.png    # optional, overrides the bundled Unipi mark
extra-css: ".body h1 { color: #000 }"   # optional, last word on styling
---
```

## 4. Writing the thesis

| You write | You get |
|-----------|---------|
| `# Heading` | numbered chapter on a new page, "CHAPTER 3" kicker, blue rule |
| `## / ### / ####` | numbered sections down to three levels |
| `# Conclusion {: .unnumbered }` | unnumbered chapter, still in the TOC |
| `# Appendix title {: .appendix }` | switches to Appendix A, B, C… from there on |
| `![Caption](fig.png)` alone in a paragraph | centred figure, "Figure 3.1." caption, listed in the LoF |
| pipe table, then a `Table: caption` paragraph | ruled table, caption above, listed in the LoT |
| ```` ```python ```` | tinted code block with syntax highlighting |
| `Some claim [@key]` or `[@a; @b]` | numeric citation `[3]` + entry in **References** |
| `text[^1]` / `[^1]: note` | real footnote at the bottom of the page |
| `!!! note` / `!!! tip` / `!!! warning` | tinted callout box |
| `> quoted text` | indented navy italic block |
| raw `<div>…</div>`, `<table>`, `<img>` | passed through untouched; add `markdown="1"` to keep Markdown working inside |

Numeric columns in tables are right-aligned automatically; use `---:` in the
separator row to force alignment yourself.

Citations are resolved from a BibTeX file — `bibliography:` in the front matter,
`--bib`, or simply `references.bib` next to the manuscript — numbered by first
appearance and formatted IEEE-style.

## 5. Page setup

A4, single-sided, 1.5 line spacing, margins 3.2 cm (left) / 2.6 cm (right) /
3.0 cm (top) / 2.8 cm (bottom). Front matter is numbered in roman numerals, the
body restarts at 1. Running header: chapter name left, Unipi mark right, hairline
rule under both. Footer: course name left, page number right.

All of it lives in one readable stylesheet — `thesis2pdf/assets/thesis.css`.
The `@page` block at the top is the page geometry; the brand colours are CSS
variables in `:root`.

## 6. Troubleshooting

**`thesis2pdf doctor`** reports every dependency, the chosen PDF engine and the
font situation. Start there.

**WeasyPrint won't install** — use `--engine wkhtmltopdf` (with the caveats
above), or install the Pango libraries listed in §1.

**Something renders oddly** — run with `--html` and open the file in a browser;
the PDF is that HTML paginated. Browsers ignore `@page`, so headers, page
numbers and footnotes only appear in the PDF.

**Fonts look wrong** — `thesis2pdf doctor` tells you whether the brand faces
were found; `--fonts fallback` forces Helvetica/Arial.

## 7. Layout of this repository

```
thesis2pdf/
  cli.py                   argument parsing, doctor, init, watch
  builder.py               orchestration, metadata, cover, TOC/LoF/LoT, engines
  render.py                Markdown → HTML: numbering, figures, tables, footnotes
  bibliography.py          BibTeX parsing, [@key] citations, reference list
  fonts.py                 brand-font detection and @font-face embedding
  assets/thesis.css        the design
  assets/unipi-logo.png    Università di Pisa mark
  assets/fonts/            drop Inter / Titillium Web .ttf files here (optional)
  templates/document.html  document skeleton
  example/                 sample thesis, bibliography, figures
```
