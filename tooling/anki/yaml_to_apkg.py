#!/usr/bin/env python3
"""
Convert YAML card files to Anki .apkg decks.

Reads cards from extract_cards.py YAML output and generates importable
Anki decks using genanki. Supports per-course and combined deck output.

Configuration: reads anki section from guide_qa.yaml (--config) for
deck_prefix, source_pattern, and course_map. Falls back to CLI args
or hardcoded defaults for backward compatibility.

MathJax: Converts $...$ -> \\(...\\) and $$...$$ -> \\[...\\] during export
so Anki 2.1.54+ renders math natively (also works on AnkiDroid).

Usage:
    # Config-driven (recommended):
    python yaml_to_apkg.py cards/all_cards.yml -o decks/ --config ../../guide_qa.yaml

    # Legacy CLI (backward compat):
    python yaml_to_apkg.py cards/all_cards.yml -o decks/
    python yaml_to_apkg.py cards/all_cards.yml -o decks/ --combined-only
    python yaml_to_apkg.py cards/all_cards.yml -o decks/ --deck-prefix "ML Foundations"
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    import genanki
except ImportError:
    print("Error: genanki not installed. Run: pip install genanki", file=sys.stderr)
    sys.exit(1)

from tooling.anki.anki_common import (
    BASIC_MODEL_ID,
    BASIC_TEMPLATE,
    CARD_CSS,
    CARD_FIELDS,
    card_guid,
    deck_id_from_name,
)
from tooling.anki.format_card_text import format_card_text

# The canonical LaTeX/markdown → HTML converter (single source of truth: markdown
# bold/tables, \textbf/\emph/\textit, code-block protection, math delimiters, lists).
# The .apkg pipeline produces the same HTML as the manual generate_anki route.
from tooling.cards.generate_anki import convert_latex_to_anki


# =============================================================================
# Default Course Map (backward compat — used when no --config provided)
# =============================================================================

FALLBACK_COURSE_MAP = {
    'c1': {'name': 'C1 Fundamentals', 'file_stem': 'RL_C1_Fundamentals'},
    'c2': {'name': 'C2 Sample-Based Methods', 'file_stem': 'RL_C2_SampleBased'},
    'c3': {'name': 'C3 Function Approximation', 'file_stem': 'RL_C3_FunctionApprox'},
    'c4': {'name': 'C4 Complete System', 'file_stem': 'RL_C4_CompleteSystem'},
}

FALLBACK_PREFIX = 'RL Specialization'
FALLBACK_SOURCE_PATTERN = r'(c[1-4])m\d+'


# =============================================================================
# Configuration Loading
# =============================================================================

def load_anki_config(config_path: Path) -> dict[str, Any]:
    """Load anki configuration from guide_qa.yaml.

    Expected structure:
        anki:
          deck_prefix: "DE Course Guide"
          separator: " - "          # optional; default " - ". Use "::" for nested Anki decks.
          source_pattern: "c([1-4])w\\d+"
          course_key_prefix: "c"    # optional; default "c". Set to "" if pattern captures full key.
          course_map:
            c1: {name: "C1 Introduction", file_stem: "DE_C1_Introduction"}
            c2: ...

    Args:
        config_path: Path to guide_qa.yaml.

    Returns:
        Dict with deck_prefix, separator, source_pattern, course_key_prefix,
        course_map keys. Empty dict if anki section missing.
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config.get('anki', {})


def prefix_to_slug(prefix: str) -> str:
    """Convert deck prefix to filesystem-safe slug.

    Example: "DE Course Guide" -> "DE_Course_Guide"
    """
    return re.sub(r'[^a-zA-Z0-9]+', '_', prefix).strip('_')


# =============================================================================
# Math Delimiter Conversion
# =============================================================================

def _find_next_single_dollar(text: str, start: int) -> int:
    """Return the next unescaped dollar delimiter, or -1 if absent."""
    i = start
    while i < len(text):
        if text[i] != '$':
            i += 1
            continue
        if i > 0 and text[i - 1] == '\\':
            i += 1
            continue
        return i
    return -1


def _looks_like_math_span(content: str) -> bool:
    r"""Heuristic for deciding whether a bounded ``$...$`` span is math.

    Card text also contains literal currency dollars, often near math spans:
    ``$\sim$$1.10/hr`` or ``$50-$150``. Those currency dollars are not paired
    math delimiters and must not consume the next real math opener.
    """
    stripped = content.strip()
    if not stripped or '\n' in stripped:
        return False
    if len(stripped) > 240:
        return False
    if re.search(r'\s{2,}', stripped):
        return False
    if re.search(r'\b(?:per|hour|hr|month|year|cost|data|gpu)\b', stripped, re.I):
        return False
    if re.search(r'[/–—]', stripped):
        return False
    if stripped.endswith('-'):
        return False
    return True


def convert_math_delimiters(text: str) -> str:
    r"""Convert LaTeX $ delimiters to Anki-compatible \( \) delimiters.

    Anki 2.1.54+ natively renders \(...\) and \[...\] via MathJax.
    Our YAML cards use $...$ (inline) and $$...$$ (display).

    Conversion order matters:
    1. $$...$$ -> \[...\] (display math, must come first)
    2. $...$ -> \(...\) (inline math)

    Args:
        text: Card text with $ delimiters.

    Returns:
        Text with Anki-compatible delimiters.
    """
    if '$' not in text:
        return text

    # Display math: $$...$$ -> \[...\]
    text = re.sub(r'\$\$(.*?)\$\$', r'\\[\1\\]', text, flags=re.DOTALL)

    # Inline math: scan instead of using one regex so literal currency dollars
    # do not accidentally pair with the next math opener.
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch != '$':
            out.append(ch)
            i += 1
            continue
        if i > 0 and text[i - 1] == '\\':
            out.append(ch)
            i += 1
            continue
        if i + 1 < len(text) and text[i + 1] == '$':
            out.append('$$')
            i += 2
            continue

        close = _find_next_single_dollar(text, i + 1)
        if close == -1:
            out.append('$')
            i += 1
            continue

        content = text[i + 1:close]
        if _looks_like_math_span(content):
            out.append(rf'\({content}\)')
            i = close + 1
        else:
            out.append('$')
            i += 1

    return ''.join(out)


def escape_html_outside_math(text: str) -> str:
    r"""Escape `<`, `>` outside math regions and legitimate HTML tags.

    Anki cards are rendered as HTML. Literal `<` in prose (e.g. ChatML
    tokens like `<|im_start|>`) is misparsed as a tag-start by the HTML
    parser. Math regions (\\(...\\) and \\[...\\]) and legitimate HTML
    tags from markdown conversion (<p>, <li>, <code>, etc.) must be
    preserved unchanged. All other `<` / `>` are escaped to `&lt;`/`&gt;`.

    Args:
        text: Card text (post math-delimiter conversion).

    Returns:
        Text with unsafe angle brackets escaped.
    """
    # Step 1: protect math regions
    math_regions: list[str] = []

    def _protect_math(m: re.Match) -> str:
        math_regions.append(
            m.group(0).replace('<', '&lt;').replace('>', '&gt;')
        )
        return f'\x00MATH{len(math_regions) - 1}\x00'

    text = re.sub(r'\\\[.*?\\\]', _protect_math, text, flags=re.DOTALL)
    text = re.sub(r'\\\(.*?\\\)', _protect_math, text, flags=re.DOTALL)

    # Step 2: protect legitimate HTML tags (markdown-converted content)
    html_tags: list[str] = []
    _safe_tags = (
        'a|b|br|code|dd|div|dl|dt|em|h[1-6]|hr|i|img|li|ol|p|pre|span|'
        'strong|sub|sup|table|tbody|td|th|thead|tr|u|ul'
    )

    def _protect_html(m: re.Match) -> str:
        html_tags.append(m.group(0))
        return f'\x00HTML{len(html_tags) - 1}\x00'

    text = re.sub(rf'</?(?:{_safe_tags})\b[^>]*/?>', _protect_html, text,
                  flags=re.IGNORECASE)
    # Also protect HTML comments
    text = re.sub(r'<!--.*?-->', _protect_html, text, flags=re.DOTALL)

    # Step 3: escape remaining bare angle brackets
    text = text.replace('<', '&lt;').replace('>', '&gt;')

    # Step 4: restore protected regions
    text = re.sub(r'\x00HTML(\d+)\x00',
                  lambda m: html_tags[int(m.group(1))], text)
    text = re.sub(r'\x00MATH(\d+)\x00',
                  lambda m: math_regions[int(m.group(1))], text)

    return text


# =============================================================================
# Media Files (Rendered Figures) Helper
# =============================================================================

def _collect_media_files(cards: list[dict], figures_dir: Path) -> list[str]:
    """Return absolute paths of PNG media referenced by `figures:` in `cards`.

    Deduplicates across cards. Silently skips entries whose file doesn't
    exist (e.g. render failed for that snippet). When no card has a
    `figures:` entry, returns [] so genanki.Package receives an empty list
    (backward-compatible with guides that haven't opted into TikZ rendering).
    """
    seen: set[str] = set()
    paths: list[str] = []
    for card in cards:
        for fname in card.get('figures') or []:
            if fname in seen:
                continue
            seen.add(fname)
            fpath = figures_dir / fname
            if fpath.exists():
                paths.append(str(fpath))
    return paths


# =============================================================================
# Source Field Helpers
# =============================================================================

def source_to_course(source: str, pattern: str, key_prefix: str = 'c') -> str | None:
    """Map source filename to a course_map key via regex.

    Uses configurable regex pattern to match source filenames across
    different guide conventions (RL uses cXmY, DE uses cXwY, Manning RLHF uses mN_, etc.).

    Returns None for appendices or unrecognized sources.

    Args:
        source: Source field, e.g. "vol0/01_c1w1_introduction_...tex".
        pattern: Regex with one capture group. The captured value is prefixed
                 with `key_prefix` to form the course_map key.
                 - Legacy patterns like "c([1-4])m\\d+" capture "1" and default
                   `key_prefix='c'` yields key "c1".
                 - New patterns like "(m\\d+)_" capture "m5" and can set
                   `key_prefix=''` to yield key "m5" directly.
        key_prefix: String prepended to the captured group. Defaults to "c"
                    for backward compatibility with existing courses.

    Returns:
        Course map key (e.g. "c1" or "m5"), or None if no match.
    """
    match = re.search(pattern, source)
    if match:
        return f'{key_prefix}{match.group(1)}'
    return None


def source_to_readable(source: str) -> str:
    """Convert source filename to human-readable label.

    Handles multiple naming conventions:
        'vol0/01_c1m1_an_introduction_...' -> 'Ch01: An Introduction ...'
        'vol0/01_c1w1_introduction_...'    -> 'Ch01: Introduction ...'
        'vol0/A_quick_reference.tex'       -> 'App A: Quick Reference'
    """
    name = source.replace('vol0/', '').replace('.tex', '')

    # Chapter files: NN_cXmY_title or NN_cXwY_title
    match = re.match(r'(\d+)_c\d[mw]\d+_(.*)', name)
    if match:
        ch_num = match.group(1)
        title = match.group(2).replace('_', ' ').title()
        return f"Ch{ch_num}: {title}"

    # Appendix files: X_title
    match = re.match(r'([A-E])_(.*)', name)
    if match:
        letter = match.group(1)
        title = match.group(2).replace('_', ' ').title()
        return f"App {letter}: {title}"

    return source


def card_type_to_topic(card: dict[str, Any]) -> str:
    """Generate topic string from card type and source chapter.

    Args:
        card: Card dict with 'type' and 'source' fields.

    Returns:
        Topic string like "Ch01 [Term]" or "App A [Formula]".
    """
    card_type = card.get('type', 'term').capitalize()
    source = card.get('source', '')

    ch_match = re.match(r'vol0/(\d+)_', source)
    if ch_match:
        return f"Ch{ch_match.group(1)} [{card_type}]"

    app_match = re.match(r'vol0/([A-E])_', source)
    if app_match:
        return f"App {app_match.group(1)} [{card_type}]"

    return f"[{card_type}]"


# =============================================================================
# Deck Building
# =============================================================================

def create_model(model_name: str) -> genanki.Model:
    """Create the basic note model for course learning cards.

    Uses fixed BASIC_MODEL_ID so re-imports don't create schema conflicts.

    Args:
        model_name: Display name for the model in Anki.

    Returns:
        genanki.Model instance.
    """
    return genanki.Model(
        BASIC_MODEL_ID,
        model_name,
        fields=CARD_FIELDS,
        templates=[BASIC_TEMPLATE],
        css=CARD_CSS,
    )


def build_deck(
    deck_name: str,
    cards: list[dict[str, Any]],
    model: genanki.Model,
    guid_namespace: str,
) -> genanki.Deck:
    """Build an Anki deck from a list of card dicts.

    Args:
        deck_name: Anki deck name (shown in deck browser).
        cards: List of card dicts from YAML.
        model: genanki.Model to use for all notes.
        guid_namespace: Fixed namespace for GUID generation. Using the same
            namespace across combined and per-course decks ensures importing
            both doesn't create duplicates.

    Returns:
        genanki.Deck ready for packaging.
    """
    deck = genanki.Deck(deck_id_from_name(deck_name), deck_name)

    for idx, card in enumerate(cards):
        # Full LaTeX/markdown → HTML pipeline (canonical, shared with
        # generate_anki.py). Handles `**bold**`, markdown tables, `\textbf{}`,
        # code blocks (with `**`/Python `**kwargs` protection), lists, math.
        # convert_math_delimiters() below is now a no-op since the converter
        # already produced \(...\) form, but we keep it as a defensive pass in
        # case the converter is ever bypassed for a given input.
        front = convert_latex_to_anki(card.get('front') or '')
        back = convert_latex_to_anki(card.get('back') or '')

        front = convert_math_delimiters(front)
        back = convert_math_delimiters(back)

        # Apply auto-formatting for inline lists
        front = format_card_text(front, 'front')
        back = format_card_text(back, 'back')

        # Escape bare `<` / `>` outside math & known HTML tags (Anki parses
        # card body as HTML; `<|im_start|>` etc. would otherwise render as
        # broken tags).
        front = escape_html_outside_math(front)
        back = escape_html_outside_math(back)

        los_id = card.get('los_id') or ''
        source_str = source_to_readable(card.get('source') or '')
        topic = card_type_to_topic(card)

        # Deterministic GUID — same namespace for all decks prevents duplicates
        card_id = card.get('id')
        if not card_id:
            card_id = f'_auto_{idx}'
            print(f"  Warning: Card {idx} missing 'id' field, using '{card_id}'",
                  file=sys.stderr)
        guid = card_guid(guid_namespace, card_id)

        tags = card.get('tags', [])
        # Sanitize tags: Anki/genanki forbids spaces in tags
        tags = [re.sub(r'\s+', '_', t) for t in tags]

        note = genanki.Note(
            model=model,
            fields=[front, back, los_id, source_str, topic],
            tags=tags,
            guid=guid,
        )
        deck.add_note(note)

    return deck


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    """Entry point: parse args, load config, generate .apkg files."""
    parser = argparse.ArgumentParser(
        description='Convert YAML cards to Anki .apkg decks',
    )
    parser.add_argument('input', type=Path, help='YAML card file (e.g., all_cards.yml)')
    parser.add_argument('-o', '--output', type=Path, default=Path('decks'),
                        help='Output directory (default: decks/)')
    parser.add_argument('--config', type=Path, default=None,
                        help='Path to guide_qa.yaml with anki: section')
    parser.add_argument('--combined-only', action='store_true',
                        help='Only generate the combined deck, skip per-course')
    parser.add_argument('--deck-prefix', default=None,
                        help='Deck name prefix (overrides config)')
    args = parser.parse_args()

    # --- Load config ---
    anki_config: dict[str, Any] = {}
    if args.config and args.config.exists():
        anki_config = load_anki_config(args.config)
        if anki_config:
            print(f"  Config loaded from {args.config}")

    # Resolve settings: CLI > config > slug-derived > hardcoded RL fallback.
    # The slug-derived step replaces the original fallback-to-RL behavior for
    # guides that pass a --config with no deck_prefix set — producing
    # "A2A Protocol" instead of the misleading "RL Specialization".
    slug_fallback = FALLBACK_PREFIX
    guide_slug = None
    if args.config and args.config.exists():
        guide_slug = args.config.resolve().parent.name
    else:
        # When invoked from <guide>/notes/notebook/ (the canonical Makefile
        # cwd), the guide slug is two dirs up. This makes the legacy
        # `decks:` Makefile target (without --config) produce sensibly-named
        # decks instead of the hardcoded 'RL Specialization' fallback.
        cwd = Path.cwd()
        if cwd.name == "notebook" and cwd.parent.name == "notes":
            guide_slug = cwd.parent.parent.name
    if guide_slug and "_" in guide_slug:
        _family, rest = guide_slug.split("_", 1)
        slug_fallback = rest.replace("_", " ").title()
    deck_prefix = (
        args.deck_prefix
        or anki_config.get('deck_prefix')
        or slug_fallback
    )
    separator: str = anki_config.get('separator', ' - ')  # default preserves prior behavior; "::" = nested
    source_pattern = anki_config.get('source_pattern', FALLBACK_SOURCE_PATTERN)
    key_prefix: str = anki_config.get('course_key_prefix', 'c')  # default "c" preserves prior behavior
    course_map = anki_config.get('course_map', FALLBACK_COURSE_MAP)
    slug = prefix_to_slug(deck_prefix)

    # --- Load YAML ---
    if not args.input.exists():
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    with open(args.input, 'r', encoding='utf-8') as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"Error: Invalid YAML in {args.input}: {e}", file=sys.stderr)
            sys.exit(1)

    cards = data.get('cards', [])
    if not cards:
        print("Error: No cards found in input file", file=sys.stderr)
        sys.exit(1)

    # --- Setup ---
    args.output.mkdir(parents=True, exist_ok=True)
    model = create_model(f'{deck_prefix} Basic')

    # Use a fixed GUID namespace so the same card in combined + per-course
    # decks gets the same GUID (no duplicates on import)
    guid_namespace = deck_prefix

    print(f"Generating decks: prefix='{deck_prefix}', {len(cards)} cards")

    # Figures directory sits alongside cards/*.yml at cards/figures/.
    # Collect per-deck media files; pass to genanki.Package(media_files=...)
    # so referenced PNGs embed in the .apkg.
    figures_dir = args.input.parent / 'figures'

    # --- Combined deck ---
    combined_name = f'{deck_prefix}{separator}Complete'
    combined_deck = build_deck(combined_name, cards, model, guid_namespace)
    combined_file = args.output / f'{slug}_Complete_{len(cards)}.apkg'
    combined_media = _collect_media_files(cards, figures_dir)
    genanki.Package(combined_deck, media_files=combined_media).write_to_file(
        str(combined_file)
    )
    media_note = f", {len(combined_media)} media" if combined_media else ""
    print(f"  {combined_file.name}  ({len(cards)} cards{media_note})")

    if args.combined_only:
        print(f"\nTotal: {len(cards)} cards exported")
        return

    # --- Per-course decks ---
    course_cards: dict[str, list[dict]] = {k: [] for k in course_map}
    appendix_cards: list[dict] = []

    for card in cards:
        course_key = source_to_course(card.get('source', ''), source_pattern, key_prefix)
        if course_key and course_key in course_cards:
            course_cards[course_key].append(card)
        else:
            appendix_cards.append(card)

    for course_key, info in course_map.items():
        course_name = info['name']
        file_stem = info['file_stem']
        deck_name = f'{deck_prefix}{separator}{course_name}'
        deck_cards = course_cards[course_key]

        if not deck_cards:
            print(f"  {file_stem}.apkg  (0 cards — skipped)")
            continue

        deck = build_deck(deck_name, deck_cards, model, guid_namespace)
        out_file = args.output / f'{file_stem}.apkg'
        deck_media = _collect_media_files(deck_cards, figures_dir)
        genanki.Package(deck, media_files=deck_media).write_to_file(str(out_file))
        media_note = f", {len(deck_media)} media" if deck_media else ""
        print(f"  {out_file.name}  ({len(deck_cards)} cards{media_note})")

    if appendix_cards:
        deck_name = f'{deck_prefix}{separator}Appendices'
        deck = build_deck(deck_name, appendix_cards, model, guid_namespace)
        out_file = args.output / f'{slug}_Appendices.apkg'
        app_media = _collect_media_files(appendix_cards, figures_dir)
        genanki.Package(deck, media_files=app_media).write_to_file(str(out_file))
        media_note = f", {len(app_media)} media" if app_media else ""
        print(f"  {out_file.name}  ({len(appendix_cards)} cards{media_note})")

    # --- Summary ---
    per_course_total = sum(len(v) for v in course_cards.values()) + len(appendix_cards)
    print(f"\nTotal: {len(cards)} cards exported ({per_course_total} across per-course decks)")


if __name__ == '__main__':
    main()
