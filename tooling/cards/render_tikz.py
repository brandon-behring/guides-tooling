"""Render TikZ snippets from card content to PNG images.

Called by extract_cards.py's clean_latex() pipeline via the import hook at
extract_cards.py:111-125. When rendering is enabled via configure(), each
`\\begin{tikzpicture}...\\end{tikzpicture}` block found in card content is
compiled to a standalone PNG and replaced with an HTML `<img>` tag. When
disabled (the default), the block is replaced with the placeholder text
`[Diagram: see PDF for visual]` — preserving historical behavior for every
guide that has not opted in.

Opt-in per guide via `guide_qa.yaml.cards.render_tikz: true`; the caller
invokes `configure(enabled=True, output_dir=<cards/figures>)` once before
processing that guide's chapters.

Rendering pipeline: pdflatex -> pdftocairo. If either tool is missing or
a specific snippet fails to compile, the placeholder is emitted for that
snippet and processing continues — figure rendering NEVER blocks card
extraction.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

TIKZ_RE = re.compile(
    r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}",
    re.DOTALL,
)
IMG_SRC_RE = re.compile(r'<img src="([^"]+\.png)"\s*/?>')
PLACEHOLDER = "[Diagram: see PDF for visual]"

# Standalone preamble. Loads only what transformer_mathematics TikZ blocks
# reference — colors from interview-preamble-tufte.sty + math macros from
# transformer-extensions.sty. Kept as a module constant so standalone renders
# don't need the guide's full preamble (which pulls minted, biber, pgfplots,
# etc. — heavy and fragile).
_STANDALONE_PREAMBLE = r"""\documentclass[border=4pt]{standalone}
\usepackage{amsmath,amssymb,amsfonts}
\usepackage{xcolor}
\usepackage{tikz}
\usetikzlibrary{arrows.meta, positioning, fit, shapes.geometric,
                calc, decorations.pathreplacing, matrix, backgrounds,
                patterns}

% Palette from shared/latex/interview-preamble-tufte.sty
\definecolor{PrimaryBlue}{HTML}{3B6FA0}
\definecolor{ForestGreen}{HTML}{4A7E3F}
\definecolor{SunsetOrange}{HTML}{C97D4A}
\definecolor{CrimsonRed}{HTML}{B8453E}
\definecolor{SteelBlue}{HTML}{5C7E9E}
\definecolor{WarmPlum}{HTML}{8A4E82}
\definecolor{WarmTeal}{HTML}{4A8C8C}
\definecolor{CodeBg}{HTML}{F7F3EE}
\definecolor{CodeFrame}{HTML}{8F8470}

% Math macros from transformer-extensions.sty (subset used in TikZ labels)
\newcommand{\softmax}{\operatorname{softmax}}
\newcommand{\attn}{\operatorname{Attn}}
\newcommand{\MHA}{\operatorname{MHA}}
\newcommand{\FFN}{\operatorname{FFN}}
\newcommand{\LN}{\operatorname{LN}}
\newcommand{\Concat}{\operatorname{Concat}}
\newcommand{\Var}{\operatorname{Var}}
\newcommand{\PE}{\operatorname{PE}}
\newcommand{\dk}{d_k}
\newcommand{\dv}{d_v}
\newcommand{\dmodel}{d_{\text{model}}}
\newcommand{\dff}{d_{\text{ff}}}
\newcommand{\nheads}{h}
\newcommand{\reals}{\mathbb{R}}
\newcommand{\vocab}{\mathcal{V}}

\begin{document}
"""

_STANDALONE_POSTAMBLE = "\n\\end{document}\n"

# Module-level config. Single-threaded assumption (extract_cards.py is a
# single-process CLI); not safe under concurrent use, but nothing in this
# repo runs it concurrently.
_enabled: bool = False
_output_dir: Optional[Path] = None
_cache_hits: int = 0
_render_failures: int = 0


def configure(enabled: bool, output_dir: Optional[Path] = None) -> None:
    """Enable TikZ rendering for the current extraction run.

    When enabled, rendered PNGs land under `output_dir`. Filenames are
    content-hashed (`tikz-<12hex>.png`), so repeated runs with unchanged TikZ
    content are cache hits (no recompilation).
    """
    global _enabled, _output_dir, _cache_hits, _render_failures
    _enabled = bool(enabled)
    _output_dir = Path(output_dir) if output_dir else None
    _cache_hits = 0
    _render_failures = 0
    if _enabled and _output_dir is not None:
        _output_dir.mkdir(parents=True, exist_ok=True)


def stats() -> dict:
    """Return a dict of render stats accumulated since the last configure()."""
    return {
        "enabled": _enabled,
        "output_dir": str(_output_dir) if _output_dir else None,
        "cache_hits": _cache_hits,
        "render_failures": _render_failures,
    }


def has_tikzpicture(content: str) -> bool:
    """True if `content` contains at least one tikzpicture environment."""
    return r"\begin{tikzpicture}" in content


def extract_and_render_tikz(content: str) -> str:
    """Replace each tikzpicture block with either an <img> tag (when rendering
    succeeds) or the placeholder text (when disabled or when a single render
    fails).

    Always returns cleaned content; never raises.
    """
    if not _enabled or _output_dir is None:
        return TIKZ_RE.sub(PLACEHOLDER, content)
    return TIKZ_RE.sub(_render_match, content)


def extract_figures_from_back(back: str) -> list[str]:
    """Return the PNG filenames referenced by <img src="..."> tags in `back`,
    in order, deduped. Used by extract_cards.py to populate `card['figures']`
    after clean_latex has already injected the img tags.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for match in IMG_SRC_RE.findall(back):
        if match not in seen:
            seen.add(match)
            ordered.append(match)
    return ordered


def _render_match(match: re.Match) -> str:
    global _cache_hits, _render_failures
    tikz_src = match.group(0)
    png_name = _content_hash_name(tikz_src)
    assert _output_dir is not None  # guaranteed by the caller's guard
    png_path = _output_dir / png_name
    if png_path.exists():
        _cache_hits += 1
        return f'<img src="{png_name}" />'
    if _render_one(tikz_src, png_path):
        return f'<img src="{png_name}" />'
    _render_failures += 1
    return PLACEHOLDER


def _content_hash_name(tikz_source: str) -> str:
    h = hashlib.sha1(tikz_source.encode("utf-8")).hexdigest()[:12]
    return f"tikz-{h}.png"


def _render_one(tikz_source: str, out_png: Path) -> bool:
    """Compile one tikzpicture to a PNG at `out_png`. Returns True on success.

    Uses a tempdir adjacent to the output to keep auxiliary files (.aux, .log,
    .pdf) out of the way. Silently returns False if pdflatex or pdftocairo
    are unavailable.
    """
    tmpdir = out_png.parent / f".{out_png.stem}.build"
    try:
        tmpdir.mkdir(exist_ok=True)
        tex = _STANDALONE_PREAMBLE + tikz_source + _STANDALONE_POSTAMBLE
        tex_path = tmpdir / "fig.tex"
        tex_path.write_text(tex, encoding="utf-8")
        pdf_path = tmpdir / "fig.pdf"

        try:
            r = subprocess.run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-output-directory",
                    str(tmpdir),
                    str(tex_path),
                ],
                capture_output=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        if r.returncode != 0 or not pdf_path.exists():
            return False

        try:
            r = subprocess.run(
                [
                    "pdftocairo",
                    "-png",
                    "-r",
                    "200",
                    "-singlefile",
                    str(pdf_path),
                    str(out_png.with_suffix("")),
                ],
                capture_output=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        return r.returncode == 0 and out_png.exists()

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
