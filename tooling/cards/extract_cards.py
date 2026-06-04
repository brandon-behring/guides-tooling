#!/usr/bin/env python3
r"""
Extract card definitions from LaTeX chapters for Anki generation.

Extracts:
- \term{name}{definition} - Term definitions (inline macro)
- \begin{definition}[Title]...\end{definition} - Math-reference formal definitions
- \begin{proposition}[Title]...\end{proposition} - Math-reference propositions
- \begin{theorem}[Title]...\end{theorem} - Math-reference theorems (priority:high)
- \begin{redflag}[title]...\end{redflag} - Common mistakes
- \begin{problem}[LOS]...\end{problem} + \begin{solution}...\end{solution} - Problems with solutions
- \begin{problembox}{Title}...\end{problembox} + \begin{solution}...\end{solution} - Vol 14 style problems
- \begin{vignette}[title]...\end{vignette} - CFA-style case studies
- \begin{interviewcontext}...\end{interviewcontext} - Interview strategy contexts
- \begin{actuarialbridge}[title]...\end{actuarialbridge} - SOA-to-DS concept mappings
- \companytags{...} - Company tags for filtering

Also auto-appends actuarial notes to cards matching concepts in shared/actuarial-mappings.yml.

Usage:
    python extract_cards.py vol1_experimentation/chapters/*.tex -o vol1_experimentation/cards/
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml


# Custom YAML dumper: force block style (|) for multi-line strings so that
# indentation in code blocks survives round-tripping.  width=1000 in the
# yaml.dump() call prevents PyYAML from inserting unwanted line-wraps.
class CardDumper(yaml.SafeDumper):
    """YAML dumper that uses literal block style for multi-line strings."""
    pass


def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


CardDumper.add_representer(str, _str_representer)


# ============================================================================
# Scaffolding Level Defaults (per card type)
# ============================================================================
# Maps card type -> default scaffolding_level indicating the depth of guidance
# provided on the back. Values:
#   - "none":   pure recall (no scaffolding; just the fact/definition)
#   - "partial": guided answer (approach + key insight + answer)
#   - "full":   detailed walkthrough (step-by-step reasoning, scenarios)
#
# Per-card overrides are honored: if a card already has a non-empty
# scaffolding_level key when apply_scaffolding_level() runs, it is preserved.

SCAFFOLDING_LEVEL_DEFAULTS: dict[str, str] = {
    # Pure recall
    'term': 'none',
    'drill': 'none',
    'clozeterm': 'none',
    'termbi': 'none',
    'formula': 'none',
    # Guided answer
    'checkpoint': 'partial',
    'problem': 'partial',
    'keyconcept': 'partial',
    'redflag': 'partial',
    'pitfall': 'partial',
    'decisiontree': 'partial',
    'sixtysec': 'partial',
    'levelcard': 'partial',
    'comparisoncard': 'partial',
    'mathdef': 'partial',
    'proposition': 'partial',
    'theorem': 'partial',
    'generatefirst': 'partial',
    'ordering': 'partial',
    'matching': 'partial',
    'actuarialbridge': 'partial',
    # Detailed walkthrough
    'vignette': 'full',
    'interview': 'full',
    'interviewtip': 'full',
    'starstory': 'full',
    'paradox': 'full',
}


def apply_scaffolding_level(card: dict[str, Any]) -> None:
    """Set card['scaffolding_level'] from SCAFFOLDING_LEVEL_DEFAULTS if absent.

    Honors per-card overrides: if the card already has a truthy
    scaffolding_level value, it is left unchanged. Unknown card types fall
    back to "partial".
    """
    if card.get('scaffolding_level'):
        return
    card_type = card.get('type', '')
    card['scaffolding_level'] = SCAFFOLDING_LEVEL_DEFAULTS.get(card_type, 'partial')


# Import tikzpicture renderer (optional - fails gracefully if unavailable)
try:
    from tooling.cards.render_tikz import (
        extract_and_render_tikz,
        extract_figures_from_back,
        has_tikzpicture,
        configure as configure_tikz_rendering,
        stats as tikz_render_stats,
    )
    TIKZ_RENDER_AVAILABLE = True
except ImportError:
    TIKZ_RENDER_AVAILABLE = False

    def has_tikzpicture(content: str) -> bool:
        return r'\begin{tikzpicture}' in content

    def extract_and_render_tikz(content: str) -> str:
        # Fallback: replace with placeholder
        pattern = r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}'
        return re.sub(pattern, '[Diagram: see PDF for visual]', content, flags=re.DOTALL)

    def extract_figures_from_back(back: str) -> list:
        return []

    def configure_tikz_rendering(enabled: bool, output_dir=None) -> None:
        pass

    def tikz_render_stats() -> dict:
        return {"enabled": False}


# ============================================================================
# Actuarial Mappings Support
# ============================================================================

# Global cache for actuarial mappings (loaded once)
_actuarial_mappings: list[dict] | None = None


def load_actuarial_mappings() -> list[dict]:
    """Load actuarial concept mappings from shared/actuarial-mappings.yml."""
    global _actuarial_mappings
    if _actuarial_mappings is not None:
        return _actuarial_mappings

    # Try to find the mappings file
    possible_paths = [
        Path(__file__).parent.parent / 'shared' / 'actuarial-mappings.yml',
        Path('shared/actuarial-mappings.yml'),
        Path('../shared/actuarial-mappings.yml'),
    ]

    for path in possible_paths:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                _actuarial_mappings = data.get('mappings', [])
                return _actuarial_mappings

    # No mappings file found - return empty list
    _actuarial_mappings = []
    return _actuarial_mappings


# ============================================================================
# Volume Mappings Support
# ============================================================================

# Global cache for volume folder → card ID prefix mappings
_volume_mappings: dict[str, str] | None = None


def load_volume_mappings() -> dict[str, str]:
    """Load volume folder to card ID prefix mappings from shared/volume-mappings.yml.

    Returns:
        Dict mapping folder names (e.g., 'vol_speed_drills') to prefixes (e.g., 'vol_spd')
    """
    global _volume_mappings
    if _volume_mappings is not None:
        return _volume_mappings

    # Try to find the mappings file
    possible_paths = [
        Path(__file__).parent.parent / 'shared' / 'volume-mappings.yml',
        Path('shared/volume-mappings.yml'),
        Path('../shared/volume-mappings.yml'),
    ]

    for path in possible_paths:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                # Filter out None values and comments
                _volume_mappings = {k: v for k, v in (data or {}).items()
                                    if isinstance(v, str)}
                return _volume_mappings

    # No mappings file found - return empty dict (graceful degradation)
    _volume_mappings = {}
    return _volume_mappings


def load_existing_los_ids(output_file: Path) -> dict[str, str]:
    """Load los_id values from existing YAML file for preservation.

    When extract_cards.py regenerates YAML from LaTeX, los_id values that were
    assigned via fix_vol*.py scripts (or manual editing) would normally be lost.
    This function reads the existing file to build a lookup table for preservation.

    Args:
        output_file: Path to the existing YAML card file

    Returns:
        Dict mapping card_id → los_id for cards that have los_id set
    """
    if not output_file.exists():
        return {}
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        if data is None:
            return {}
        # Handle both per-file format (data['cards']) and combined format
        cards = data.get('cards', [])
        return {
            card['id']: card.get('los_id')
            for card in cards
            if card.get('los_id')
        }
    except Exception:
        return {}


def find_actuarial_mapping(card_content: str, volume: str) -> dict | None:
    """Find matching actuarial mapping for card content.

    Searches the card's front+back for tech concepts and returns the matching
    actuarial mapping if found and applicable to this volume.
    """
    mappings = load_actuarial_mappings()
    content_lower = card_content.lower()

    for mapping in mappings:
        tech_concept = mapping.get('tech_concept', '').lower()
        applicable_volumes = mapping.get('volumes', [])

        # Check if concept appears in content and volume matches
        if tech_concept and tech_concept in content_lower:
            # Volume format: 'vol1' in mappings, 'vol1' from extract
            vol_key = volume.lower()
            if not applicable_volumes or vol_key in applicable_volumes:
                return mapping

    return None


def add_actuarial_note_to_card(card: dict, volume: str) -> None:
    """Add actuarial note to card back if matching mapping exists.

    Appends a footer like:
    ---
    📊 *Actuarial: Analogous to [concept] from [EXAM]*
    """
    content = f"{card.get('front', '')} {card.get('back', '')}"
    mapping = find_actuarial_mapping(content, volume)

    if mapping:
        actuarial = mapping.get('actuarial', '')
        exam = mapping.get('exam', '')
        if actuarial and exam:
            note = f"\n\n---\n📊 *Actuarial: Analogous to {actuarial} from {exam}*"
            card['back'] = card.get('back', '') + note
            card['actuarial_mapping'] = {
                'tech': mapping.get('tech_concept'),
                'actuarial': actuarial,
                'exam': exam
            }
            # Add actuarial tag
            if 'tags' in card:
                card['tags'].append('has_actuarial_note')


def slugify(text: str, max_len: int = 50) -> str:
    """Convert text to URL-safe slug for card IDs."""
    # Remove LaTeX commands
    text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    # Keep alphanumeric and spaces
    text = re.sub(r'[^a-zA-Z0-9\s]', '', text)
    # Replace spaces with underscores
    text = re.sub(r'\s+', '_', text.strip())
    # Uppercase and truncate
    return text.upper()[:max_len]


# Track warnings for reporting
_id_collision_warnings: list[str] = []
_generic_front_warnings: list[str] = []

# Module-level guide slug for cross-guide ID uniqueness.
# Set by main() via --guide-slug or auto-detected from output path.
_guide_slug_default: str | None = None


def make_unique_id(base_id: str, seen_ids: set) -> str:
    """Generate unique ID by adding counter suffix if collision detected.

    DEPRECATED: Use generate_card_id() instead for new code.
    This function is retained for backwards compatibility with existing
    extraction functions that have their own semantic fallback logic.
    """
    if base_id not in seen_ids:
        seen_ids.add(base_id)
        return base_id

    # Collision - add counter suffix and warn
    counter = 2
    while f"{base_id}_{counter}" in seen_ids:
        counter += 1
    unique_id = f"{base_id}_{counter}"
    seen_ids.add(unique_id)

    _id_collision_warnings.append(f"ID collision: {base_id} -> {unique_id}")
    return unique_id


# Default set of generic titles that require semantic content fallback
GENERIC_TITLES = frozenset({
    'practice question', 'example', 'question', 'case study',
    'vignette', 'scenario', 'key concept', 'common mistake',
    'warning', 'tip', 'formula', 'interview tip', 'interview context',
    'decision tree', 'pitfall', 'common pitfall', 'soa connection',
    'behavioral example', 'product tension', '',
})


def _extract_semantic_text(body: str) -> str:
    """Extract first meaningful line from body content for ID generation.

    Skips:
    - Empty lines
    - Difficulty markers (★)
    - Formatting prefixes (textbf, **)
    - Meta labels (Prompt:, Time:, Scenario:)
    - Company tag lines (DS-Google-L4, etc.)

    Returns:
        First meaningful text snippet (up to 100 chars) or empty string
    """
    body_clean = clean_latex(body)
    for line in body_clean.split('\n'):
        line = line.strip()
        if not line or len(line) < 10:
            continue
        # Skip formatting prefixes
        line = re.sub(r'^\[★+\]\s*', '', line)
        line = re.sub(r'^\\?textbf\{[^}]*\}\s*', '', line)
        line = re.sub(r'^\*\*[^*]+\*\*\s*', '', line)
        line = re.sub(r'^(Prompt|Time|Type|Context|Scenario|Question):\s*', '', line)
        # Skip company tags
        if re.match(r'^[A-Z]+-[A-Z][a-z]+-', line):
            continue
        # Skip pure list markers
        if re.match(r'^[-•]\s*$', line):
            continue
        if len(line) > 10:
            return line[:100]
    return ""


def generate_card_id(
    volume: str,
    chapter: str,
    card_type: str,
    title: str,
    body: str,
    los_id: str | None,
    seen_ids: set,
    generic_titles: frozenset | None = None,
    guide_slug: str | None = None
) -> str:
    """Generate stable, semantic card ID with intelligent fallbacks.

    Priority:
    1. Semantic slug from title (if not generic)
    2. Semantic slug from body content (if title is generic)
    3. LOS-based slug (if body is too short)
    4. Content hash (deterministic collision resolution)

    Args:
        volume: Volume identifier (e.g., 'vol1')
        chapter: Chapter identifier (e.g., 'ch04')
        card_type: Card type for ID prefix (e.g., 'TERM', 'RF', 'PROB')
        title: Card title (may be generic)
        body: Card body content for semantic extraction
        los_id: Optional LOS reference for fallback
        seen_ids: Set of already-used IDs for collision detection
        generic_titles: Optional override of default generic title set
        guide_slug: Optional guide identifier for cross-guide uniqueness

    Returns:
        Unique, deterministic card ID
    """
    generic_titles = generic_titles or GENERIC_TITLES

    # Step 1: Try title-based slug
    title_clean = title.lower().strip()
    if title_clean not in generic_titles:
        slug = slugify(title, 50)
    else:
        # Step 2: Extract semantic content from body
        semantic_text = _extract_semantic_text(body)
        slug = slugify(semantic_text[:60], 50) if semantic_text else ""

    # Step 3: LOS fallback if slug too short
    if len(slug) < 8 and los_id:
        los_parts = [p.strip().replace('-', '_').replace('.', '_').upper()
                     for p in los_id.split(',')]
        slug = '_'.join(sorted(los_parts))

    # Step 4: Content hash fallback if still too short
    if len(slug) < 4:
        content_hash = hashlib.md5((title + body).encode()).hexdigest()[:8]
        slug = f"H{content_hash.upper()}"

    # Build ID with optional guide prefix for cross-guide uniqueness
    # Use explicit arg first, then fall back to module-level default
    effective_slug = guide_slug or _guide_slug_default
    if effective_slug:
        base_id = f"{effective_slug}-{volume}-{chapter}-{card_type}-{slug}"
    else:
        base_id = f"{volume}-{chapter}-{card_type}-{slug}"

    # Collision resolution with deterministic hash
    if base_id in seen_ids:
        content_hash = hashlib.md5((title + body).encode()).hexdigest()[:6]
        base_id = f"{base_id}_H{content_hash.upper()}"
        _id_collision_warnings.append(f"Hash-resolved: {base_id}")

    seen_ids.add(base_id)
    return base_id


# Generic front patterns to warn about
GENERIC_FRONT_PATTERNS = [
    "Key Concept: Key Concept",
    "Case Study: Case Study",
    "Warning: Common Mistake",
    "Interview Tip: Interview Tip",
]


def check_generic_front(card: dict) -> None:
    """Check if a card has a generic front and warn if so."""
    front = card.get('front', '')
    card_id = card.get('id', 'unknown')

    for pattern in GENERIC_FRONT_PATTERNS:
        if front == pattern:
            _generic_front_warnings.append(f"Generic front: {card_id} has '{pattern}'")


_TRAILING_HEADER_RE = re.compile(
    r'(?:^|\n)\s*(?:Answer\s*:|Key\s+Insight\s*:).*',
    re.IGNORECASE | re.DOTALL,
)


def _has_unclosed_math(text: str) -> tuple[str, int] | None:
    r"""Detect whether ``text`` ends inside an unclosed math region.

    Returns a ``(kind, open_pos)`` tuple identifying the unclosed delimiter
    and its opening position, or ``None`` if math is balanced.

    Delimiter kinds (in check order):
        * ``"display_bracket"`` — unclosed ``\[``
        * ``"display_dollar"`` — odd count of ``$$``
        * ``"inline_paren"`` — unclosed ``\(``
        * ``"inline_dollar"`` — odd count of ``$`` after stripping ``\$``

    The checks are ordered so display math is diagnosed before inline math,
    matching the way clean_latex protects regions.
    """
    # \[ ... \] — count occurrences, flag if unbalanced.
    # Negative lookbehind excludes row-separator `\\[Npt]` (two backslashes +
    # bracket) inside align blocks — those are vertical-space arguments, not
    # display-math openers. Same for `\\]` row-separator closers. 2026-04-22.
    open_disp = [m.start() for m in re.finditer(r'(?<!\\)\\\[', text)]
    close_disp = [m.start() for m in re.finditer(r'(?<!\\)\\\]', text)]
    if len(open_disp) > len(close_disp):
        return ("display_bracket", open_disp[len(close_disp)])

    # $$ ... $$ — odd count of ``$$`` means unclosed.
    dollar_dollar = [m.start() for m in re.finditer(r'\$\$', text)]
    if len(dollar_dollar) % 2 == 1:
        return ("display_dollar", dollar_dollar[-1])

    # \( ... \) — count occurrences of ``\(`` and ``\)``.
    open_inl = [m.start() for m in re.finditer(r'\\\(', text)]
    close_inl = [m.start() for m in re.finditer(r'\\\)', text)]
    if len(open_inl) > len(close_inl):
        return ("inline_paren", open_inl[len(close_inl)])

    # $ ... $ — count single ``$`` that are not part of ``$$`` or ``\$``.
    # Strip ``$$`` and ``\$`` first so what remains is single-dollar math.
    stripped = re.sub(r'\$\$', '', text)
    stripped = re.sub(r'\\\$', '', stripped)
    if stripped.count('$') % 2 == 1:
        # Find the last unmatched ``$``.
        positions = [m.start() for m in re.finditer(r'(?<!\\)\$', text)
                     if not text[m.start():m.start() + 2] == '$$'
                     and not (m.start() + 1 < len(text) and text[m.start() + 1] == '$')]
        if positions:
            return ("inline_dollar", positions[-1])

    return None


def _extend_to_close_math(
    text: str, cut_pos: int, max_extension: int = 400
) -> int:
    r"""Extend ``cut_pos`` to include a math-region closing delimiter.

    If cutting ``text`` at ``cut_pos`` would leave a math region unclosed,
    search forward for the matching closer. Extends the cut up to
    ``max_extension`` additional characters. Returns the adjusted cut
    position or ``cut_pos`` if no adjustment is needed.

    Falls back to rolling the cut *back* to before the opening delimiter
    when extension would exceed the budget — better to drop the equation
    entirely than emit broken LaTeX.
    """
    prefix = text[:cut_pos]
    unclosed = _has_unclosed_math(prefix)
    if unclosed is None:
        return cut_pos

    kind, open_pos = unclosed
    closer_for = {
        "display_bracket": (r'\\\]', 2),    # \]
        "display_dollar": (r'\$\$', 2),     # $$
        "inline_paren": (r'\\\)', 2),       # \)
        "inline_dollar": (r'(?<!\\)\$', 1),  # $
    }
    pattern, closer_len = closer_for[kind]

    match = re.search(pattern, text[cut_pos:])
    if match is not None and match.start() <= max_extension:
        return cut_pos + match.start() + closer_len

    # Can't extend — roll back to before the opener so the truncated text
    # is at least well-formed (no half-equation).
    return open_pos


def truncate_at_sentence(text: str, max_len: int) -> str:
    """Truncate at sentence boundary, not mid-word, and math-safe.

    Finds the last sentence-ending punctuation before ``max_len``. If found
    at >40% of content, truncates there. Falls back to word boundary when
    no sentence boundary exists. Always preserves complete math regions —
    never leaves ``\\[`` without ``\\]`` or ``$`` without matching ``$``.

    Special handling:
    - Embedded images (base64): uses higher limit to preserve integrity.
    - Answer/Key Insight sections: if truncation would drop trailing
      structural headers, they are appended after the truncated body.
    - Math regions: if the chosen cut falls inside ``\\[...\\]``, ``$...$``,
      ``$$...$$``, or ``\\(...\\)``, the cut is extended to include the
      closing delimiter (up to 400 chars) or rolled back to before the
      opener.
    """
    # If content has embedded images, use higher limit to preserve them
    if 'data:image' in text and 'base64' in text:
        max_len = max(max_len, 15000)  # Allow up to 15KB for image content

    if len(text) <= max_len:
        return text
    truncated = text[:max_len]

    # Don't truncate in the middle of an HTML img tag
    if '<img ' in truncated and '</img>' not in truncated and '>' not in truncated[truncated.rfind('<img'):]:
        # Find the end of the last complete img tag before max_len
        last_img_end = truncated.rfind('>')
        if last_img_end > max_len * 0.5:
            truncated = truncated[:last_img_end + 1]

    # Try sentence boundary (40% threshold - was 60%)
    result = None
    cut_pos: int | None = None
    for punct in ['. ', '! ', '? ', '.\n', '!\n', '?\n']:
        last_boundary = truncated.rfind(punct)
        if last_boundary > max_len * 0.4:
            cut_pos = last_boundary + 1
            break

    if cut_pos is None:
        # Fallback: word boundary (don't cut mid-word)
        last_space = truncated.rfind(' ')
        if last_space > max_len * 0.8:
            cut_pos = last_space
            ellipsis = '...'
        else:
            # Last resort: hard truncate
            cut_pos = max_len
            ellipsis = '...'
    else:
        ellipsis = ''

    # Math-safety adjustment: never leave a math region unclosed.
    safe_cut = _extend_to_close_math(text, cut_pos)
    if safe_cut != cut_pos:
        # When math extension is applied, drop the ellipsis — the card ends
        # with a complete equation which is a natural terminator.
        ellipsis = ''
        cut_pos = safe_cut

    result = text[:cut_pos].strip()
    if ellipsis and not result.endswith(ellipsis):
        result = result + ellipsis

    # Preserve trailing Answer/Key Insight sections lost to truncation.
    # These headers are always at the END of solution blocks and are the
    # most important part for the solution quality audit.
    result = _restore_trailing_headers(text, result)

    return result


def _restore_trailing_headers(full_text: str, truncated: str) -> str:
    """Append Answer/Key Insight sections from full_text if truncation dropped them.

    Only appends sections that exist in full_text but not in truncated.
    Each restored section is capped at 300 chars to keep cards reviewable.
    """
    headers_to_check = [
        (re.compile(r'Answer\s*:', re.IGNORECASE), 'Answer'),
        (re.compile(r'Key\s+Insight\s*:', re.IGNORECASE), 'Key Insight'),
    ]

    appended: list[str] = []
    for pattern, label in headers_to_check:
        if pattern.search(truncated):
            continue  # Already present
        match = pattern.search(full_text)
        if not match:
            continue  # Not in source either

        # Extract from the header to the next header or end of text
        start = match.start()
        # Find the start of the next structural header after this one
        next_header = re.search(
            r'\n\s*(?:Answer\s*:|Key\s+Insight\s*:|Approach\s*:)',
            full_text[match.end():],
            re.IGNORECASE,
        )
        if next_header:
            section = full_text[start:match.end() + next_header.start()].strip()
        else:
            section = full_text[start:].strip()

        # Cap section length to keep cards reviewable
        if len(section) > 300:
            # Truncate at last sentence within 300 chars
            cut = section[:300]
            last_period = cut.rfind('. ')
            if last_period > 100:
                section = cut[:last_period + 1]
            else:
                section = cut.rstrip() + '...'

        appended.append(section)

    if appended:
        return truncated + '\n\n' + '\n\n'.join(appended)
    return truncated


def extract_volume_chapter(filepath: Path) -> tuple[str, str]:
    """Extract volume and chapter identifiers from filepath.

    Example: vol1_experimentation/chapters/04_sample_size.tex -> ('vol1', 'ch04')
    Special case: vol_speed_drills/chapters/01_*.tex -> ('vol_spd', 'ch01')

    Volume ID resolution order:
    1. Explicit mappings from shared/volume-mappings.yml
    2. Numeric pattern (vol1_*, vol2_*, etc.)
    3. Default to 'vol0' (should not happen with proper config)
    """
    parts = filepath.parts

    # Load volume mappings (cached after first call)
    mappings = load_volume_mappings()

    # Find volume directory
    volume = 'vol0'
    for part in parts:
        if part.startswith('vol'):
            # Check explicit mappings first (handles non-numeric volumes)
            if part in mappings:
                volume = mappings[part]
                break
            # Then try numeric pattern (e.g., 'vol1' from 'vol1_experimentation')
            match = re.match(r'(vol\d+)', part)
            if match:
                volume = match.group(1)
                break

    # Extract chapter from filename (e.g., '04_sample_size.tex' -> 'ch04')
    filename = filepath.stem
    chapter_match = re.match(r'(\d+)', filename)
    chapter = f"ch{chapter_match.group(1).zfill(2)}" if chapter_match else 'ch00'

    return volume, chapter


def clean_latex(text: str) -> str:
    """Clean LaTeX artifacts from text for card display."""
    # Handle tikzpicture environments first (render to embedded images)
    if has_tikzpicture(text):
        text = extract_and_render_tikz(text)

    # CRITICAL: Protect escaped \% BEFORE removing comments
    # This prevents "95\% confidence" from being truncated to "95"
    text = text.replace(r'\%', '\x00PERCENT\x00')

    # Remove comments (unescaped % to end of line)
    text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)

    # Restore escaped percent signs
    text = text.replace('\x00PERCENT\x00', '%')

    # === LaTeX-literal escape protection ==================================
    # Protect source escapes that would otherwise be destroyed downstream:
    #   \&                -> table-cell regex at the bottom rewrites bare `&`
    #                        to ` | ` and leaves an orphan backslash.
    #   \{ / \}           -> literal braces confuse the `[^{}]*` brace-counting
    #                        regex used by \texttt / \textbf / \emph cleanup,
    #                        so \texttt{\{x\}} leaves unmatched braces.
    #   \textbackslash    -> intended to render as a literal backslash `\` in
    #                        running text (e.g. "\n" escape in prompt templates).
    #   \# \_             -> symmetrical to \& for `#` and `_`.
    # Null-byte sentinels are guaranteed not to appear in user content.
    # Restoration runs after the full pipeline, just before the final strip.
    # Order matters: \textbackslash first (so its \ cannot be eaten by other
    # escape patches), then the punctuation escapes.
    # LaTeX command-name tokenization swallows one space after the command,
    # so `\textbackslash n` renders as `\n` (not `\ n`). Consume the optional
    # trailing `{}` or a single whitespace char to match LaTeX's behavior.
    text = re.sub(r'\\textbackslash(?:\{\}|[ \t])?', '\x00BACKSLASH\x00', text)
    text = text.replace(r'\&', '\x00AMP\x00')
    text = text.replace(r'\#', '\x00HASH\x00')
    text = text.replace(r'\_', '\x00USCORE\x00')
    text = text.replace(r'\{', '\x00LBRACE\x00')
    text = text.replace(r'\}', '\x00RBRACE\x00')

    # Sub-goal labels: \substep{label}{content} → **Step N: label**\ncontent
    # Must happen before general brace stripping
    step_counter = [0]
    def _replace_substep(m: re.Match) -> str:
        step_counter[0] += 1
        return f"\n**Step {step_counter[0]}: {m.group(1)}**\n{m.group(2)}\n"
    text = re.sub(r'\\substep\{([^}]+)\}\{([^}]+)\}', _replace_substep, text)

    # ════════════════════════════════════════════════════════════════════════
    # MATH PRESERVATION PIPELINE  (Stages A → B → C)
    #
    # Anki 2.1.54+ renders LaTeX via MathJax when delimiters ``\(...\)`` or
    # ``\[...\]`` are present. Downstream ``yaml_to_apkg.py`` converts
    # ``$...$`` → ``\(...\)`` and ``$$...$$`` → ``\[...\]`` at export time,
    # but only if the dollars survive cleanup. These three stages make sure
    # math markup reaches the YAML intact. Must run BEFORE the destructive
    # section that rewrites ``\\``, ``\frac``, ``\text``, etc.
    # ════════════════════════════════════════════════════════════════════════

    # Stage A — Expand transformer-extensions.sty macros to native LaTeX,
    # and strip cross-reference markup that survives MathJax rendering as
    # noise (``\label``, ``\autocite``, ``\footnote`` inside math environments).
    # Keeping the LaTeX form (rather than Unicode) means MathJax renders
    # them correctly inside math regions without a preamble definition.
    # Safe globally: these names do not collide with standard LaTeX.
    text = re.sub(r'\\label\{[^}]*\}', '', text)
    text = re.sub(r'\\autocite\{[^}]*\}', '', text)
    text = re.sub(r'\\reals\b', r'\\mathbb{R}', text)
    text = re.sub(r'\\vocab\b', r'\\mathcal{V}', text)
    text = re.sub(r'\\dmodel\b', r'd_{\\text{model}}', text)
    text = re.sub(r'\\dff\b', r'd_{\\text{ff}}', text)
    text = re.sub(r'\\dk\b', 'd_k', text)
    text = re.sub(r'\\dv\b', 'd_v', text)
    text = re.sub(r'\\nheads\b', 'h', text)
    text = re.sub(r'\\PE\b', r'\\operatorname{PE}', text)
    text = re.sub(r'\\softmax\b', r'\\operatorname{softmax}', text)
    text = re.sub(r'\\attn\b', r'\\operatorname{Attn}', text)
    text = re.sub(r'\\MHA\b', r'\\operatorname{MHA}', text)
    text = re.sub(r'\\FFN\b', r'\\operatorname{FFN}', text)
    text = re.sub(r'\\LN\b', r'\\operatorname{LN}', text)
    text = re.sub(r'\\Concat\b', r'\\operatorname{Concat}', text)
    text = re.sub(r'\\Var\b', r'\\operatorname{Var}', text)
    text = re.sub(r'\\Cov\b', r'\\operatorname{Cov}', text)
    text = re.sub(r'\\diag\b', r'\\operatorname{diag}', text)
    text = re.sub(r'\\rank\b', r'\\operatorname{rank}', text)
    # \top and \ell are standard LaTeX — MathJax renders them natively.

    # Stage B — Convert display-math environments to ``\[...\]`` so MathJax
    # renders them as display math. ``align`` is wrapped in ``aligned`` which
    # is the MathJax-compatible alignment environment.
    text = re.sub(
        r'\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}',
        r'\\[\1\\]', text, flags=re.DOTALL
    )
    text = re.sub(
        r'\\begin\{align\*?\}(.*?)\\end\{align\*?\}',
        r'\\[\\begin{aligned}\1\\end{aligned}\\]', text, flags=re.DOTALL
    )
    text = re.sub(
        r'\\begin\{gather\*?\}(.*?)\\end\{gather\*?\}',
        r'\\[\\begin{gathered}\1\\end{gathered}\\]', text, flags=re.DOTALL
    )

    # Stage C — Protect math regions from the downstream destructive cleanup.
    # Any ``\[...\]``, ``$$...$$``, or ``$...$`` becomes a placeholder token
    # that survives the rest of ``clean_latex`` unchanged, then gets restored
    # at the end of the function.
    _math_regions: list[str] = []

    def _preserve_math(m: re.Match) -> str:
        _math_regions.append(m.group(0))
        return f'__MATH_REGION_{len(_math_regions) - 1}__'

    text = re.sub(r'\\\[.+?\\\]', _preserve_math, text, flags=re.DOTALL)
    text = re.sub(r'\$\$.+?\$\$', _preserve_math, text, flags=re.DOTALL)
    # Inline: single ``$...$`` not adjacent to another ``$`` or preceded by
    # backslash (which would be escaped currency). Multi-line inline math
    # is common in source LaTeX (e.g. ``$\mathbf{M}_k = \diag(...)...$``
    # broken across lines), so newlines are allowed inside. Non-greedy
    # matching terminates at the nearest closing ``$``.
    # CL-EXTRACT-001: allow ``\$`` in math content (escaped currency) and
    # require closing ``$`` to NOT be preceded by ``\`` — without this, a
    # math expression like ``$X = \$0.01 = \$331.50$`` closes early on the
    # first ``\$`` and the trailing real ``$`` becomes a phantom opener that
    # consumes text through the next ``$`` later in the file (including
    # ``\end{itemize}`` tokens that should have been stripped).
    text = re.sub(
        r'(?<![\$\\])\$(?!\$)((?:\\\$|[^$])+?)(?<!\\)\$(?!\$)',
        _preserve_math, text, flags=re.DOTALL
    )

    # Common LaTeX artifacts
    text = text.replace('``', '"').replace("''", '"')
    text = re.sub(r'---', '—', text)
    text = re.sub(r'--', '–', text)
    text = re.sub(r'~', ' ', text)
    text = re.sub(r'\\\\', ' ', text)
    # LaTeX spacing primitives that render as (adjusted) space in text mode.
    # Common case: `vs.\ 2020` (non-sentence-ending space) — collapses to `vs. 2020`.
    # Also `\,` (thin), `\;` (thick), `\!` (negative thin).
    # Trailing tab / newline also counts as a swallowed inter-word space.
    text = re.sub(r'\\[ ,;\t\n]', ' ', text)
    text = re.sub(r'\\!', '', text)

    # Convert LaTeX escaped dollar sign to placeholder (for currency)
    # Must be done BEFORE math processing removes dollar signs
    # Use Unicode placeholder that won't appear in math: ¤ (currency sign)
    text = re.sub(r'\\\$', '¤DOLLAR¤', text)

    # Math commands - convert before handling dollar signs
    # Text in math mode: \text{...} → just the text
    for _ in range(3):
        text = re.sub(r'\\text\{([^{}]*)\}', r'\1', text)
    # Fractions: \frac{a}{b} → a/b (multiple passes for nested)
    for _ in range(5):  # More passes for deeply nested
        text = re.sub(r'\\frac\{([^{}]*)\}\{([^{}]*)\}', r'(\1)/(\2)', text)
    # Accents over letters: \bar{x} → x̄, \hat{x} → x̂
    text = re.sub(r'\\bar\{([^{}]*)\}', r'\1̄', text)
    text = re.sub(r'\\hat\{([^{}]*)\}', r'\1̂', text)
    text = re.sub(r'\\tilde\{([^{}]*)\}', r'\1̃', text)
    text = re.sub(r'\\vec\{([^{}]*)\}', r'\1⃗', text)
    text = re.sub(r'\\dot\{([^{}]*)\}', r'\1̇', text)
    # Subscript/superscript: x_n → x_n, x^2 → x²
    text = re.sub(r'\^2\b', '²', text)
    text = re.sub(r'\^3\b', '³', text)
    text = re.sub(r'\\sqrt\{([^{}]*)\}', r'√(\1)', text)
    text = re.sub(r'\\sum\b', 'Σ', text)
    text = re.sub(r'\\prod\b', 'Π', text)
    text = re.sub(r'\\int\b', '∫', text)
    # Table multicolumn - just extract the content (3rd arg)
    text = re.sub(r'\\multicolumn\{[^}]*\}\{[^}]*\}\{([^{}]*)\}', r'\1', text)

    # Math symbols - convert inline math to Unicode
    text = re.sub(r'\$\\times\$', '×', text)
    text = re.sub(r'\$\\cdot\$', '·', text)
    text = re.sub(r'\$\\rightarrow\$', '→', text)
    text = re.sub(r'\$\\leftarrow\$', '←', text)
    text = re.sub(r'\$\\Rightarrow\$', '⇒', text)
    text = re.sub(r'\$\\Leftarrow\$', '⇐', text)
    text = re.sub(r'\$\\leftrightarrow\$', '↔', text)
    text = re.sub(r'\$\\geq\$', '≥', text)
    text = re.sub(r'\$\\leq\$', '≤', text)
    text = re.sub(r'\$\\neq\$', '≠', text)
    text = re.sub(r'\$\\approx\$', '≈', text)
    text = re.sub(r'\$\\pm\$', '±', text)
    text = re.sub(r'\$\\infty\$', '∞', text)
    text = re.sub(r'\$\\alpha\$', 'α', text)
    text = re.sub(r'\$\\beta\$', 'β', text)
    text = re.sub(r'\$\\gamma\$', 'γ', text)
    text = re.sub(r'\$\\delta\$', 'δ', text)
    text = re.sub(r'\$\\epsilon\$', 'ε', text)
    text = re.sub(r'\$\\sigma\$', 'σ', text)
    text = re.sub(r'\$\\mu\$', 'μ', text)
    text = re.sub(r'\$\\rho\$', 'ρ', text)
    text = re.sub(r'\$\\theta\$', 'θ', text)
    text = re.sub(r'\$\\lambda\$', 'λ', text)
    text = re.sub(r'\$\\pi\$', 'π', text)
    # Also handle without dollar signs (for commands inside math mode)
    text = re.sub(r'\\times\b', '×', text)
    text = re.sub(r'\\cdot\b', '·', text)
    text = re.sub(r'\\rightarrow\b', '→', text)
    text = re.sub(r'\\leftarrow\b', '←', text)
    text = re.sub(r'\\Rightarrow\b', '⇒', text)
    text = re.sub(r'\\Leftarrow\b', '⇐', text)
    text = re.sub(r'\\leftrightarrow\b', '↔', text)
    text = re.sub(r'\\geq\b', '≥', text)
    text = re.sub(r'\\leq\b', '≤', text)
    text = re.sub(r'\\neq\b', '≠', text)
    text = re.sub(r'\\approx\b', '≈', text)
    text = re.sub(r'\\pm\b', '±', text)
    text = re.sub(r'\\infty\b', '∞', text)
    text = re.sub(r'\\alpha\b', 'α', text)
    text = re.sub(r'\\beta\b', 'β', text)
    text = re.sub(r'\\gamma\b', 'γ', text)
    text = re.sub(r'\\delta\b', 'δ', text)
    text = re.sub(r'\\epsilon\b', 'ε', text)
    text = re.sub(r'\\sigma\b', 'σ', text)
    text = re.sub(r'\\mu\b', 'μ', text)
    text = re.sub(r'\\rho\b', 'ρ', text)
    text = re.sub(r'\\theta\b', 'θ', text)
    text = re.sub(r'\\lambda\b', 'λ', text)
    text = re.sub(r'\\pi\b', 'π', text)

    # === \cref / \Cref → human-readable cross-references ===
    # ``\cref{def:tf-softmax}`` → ``(Definition: softmax)``. The label prefix
    # (``def``, ``prop``, ``thm``, …) maps to an English word; the rest of
    # the label becomes the target name with ``tf-`` prefix stripped and
    # hyphens converted to spaces. Falls back to bare label if unrecognized.
    _label_prefix = {
        'def': 'Definition', 'prop': 'Proposition', 'thm': 'Theorem',
        'eq': 'Equation', 'fig': 'Figure', 'sec': 'Section',
        'ch': 'Chapter', 'lem': 'Lemma', 'cor': 'Corollary',
        'alg': 'Algorithm', 'proof': 'Proof', 'tab': 'Table',
    }

    def _expand_cref(match: re.Match) -> str:
        label = match.group(1)
        if ':' in label:
            prefix, name = label.split(':', 1)
            readable = name.replace('tf-', '').replace('-', ' ')
            return f"{_label_prefix.get(prefix, prefix)} {readable}"
        return label

    text = re.sub(r'\\[Cc]ref\{([^}]+)\}', _expand_cref, text)

    # === \eqref / \ref → human-readable equation cross-references ===
    # ``\eqref{eq:ppo-clip}`` → ``(Eq. ppo-clip)``. The ``eq:`` prefix is
    # stripped since the whole cross-reference is to an equation by
    # construction. Falls back to the bare label if no ``eq:`` prefix.
    def _expand_eqref(match: re.Match) -> str:
        label = match.group(1)
        if label.startswith('eq:'):
            return f"(Eq. {label[3:]})"
        return f"(Eq. {label})"

    text = re.sub(r'\\eqref\{([^}]+)\}', _expand_eqref, text)
    # Bare \ref{...} to equation labels: convert to (Eq. name) as well.
    # Non-eq refs (e.g. \ref{sec:foo}) become plain (name) — less ambiguous
    # than dropping to empty string like the old behavior.
    def _expand_ref(match: re.Match) -> str:
        label = match.group(1)
        if ':' in label:
            prefix, name = label.split(':', 1)
            readable = {'eq': 'Eq.', 'sec': '§', 'fig': 'Fig.',
                        'ch': 'Ch.', 'tbl': 'Tbl.', 'tab': 'Tbl.',
                        'alg': 'Alg.', 'thm': 'Thm.', 'lem': 'Lem.',
                        'prop': 'Prop.', 'def': 'Def.', 'cor': 'Cor.'
                        }.get(prefix, prefix)
            return f"({readable} {name})"
        return f"({label})"

    text = re.sub(r'\\ref\{([^}]+)\}', _expand_ref, text)

    # Handle simple inline math (just remove dollar signs for simple expressions)
    text = re.sub(r'\$([^$\\]+)\$', r'\1', text)
    # Remove remaining dollar signs from math mode
    text = re.sub(r'\$', '', text)

    # Restore currency dollar signs from placeholder
    text = text.replace('¤DOLLAR¤', '$')

    def _texttt_replace(match: "re.Match[str]") -> str:
        """Preserve \\texttt{} content as inline code when it contains characters
        that genanki will HTML-escape (``<``, ``>``, ``|``, ``&``). Otherwise
        unwrap to plain text."""
        content = match.group(1)
        if any(c in content for c in "<>|&"):
            # Wrap in backticks so genanki renders it inside <code>...</code>,
            # which preserves the characters literally rather than escaping them.
            return f"`{content}`"
        return content

    # Remove formatting commands (keep content) - multiple passes for nested
    for _ in range(3):  # Handle nested formatting
        text = re.sub(r'\\textbf\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\textit\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\emph\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\texttt\{([^{}]*)\}', _texttt_replace, text)
        text = re.sub(r'\\underline\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\textsc\{([^{}]*)\}', r'\1', text)
        text = re.sub(r'\\textrm\{([^{}]*)\}', r'\1', text)

    # Clean up unclosed/orphan LaTeX commands
    text = re.sub(r'\\textbf\{', '', text)
    text = re.sub(r'\\textit\{', '', text)
    text = re.sub(r'\\emph\{', '', text)

    # Lists - convert to simple format. Optional argument (e.g.
    # ``\begin{itemize}[noitemsep]``) is consumed by the trailing ``(?:\[[^\]]*\])?``
    # so it does not leak into rendered text.
    text = re.sub(r'\\begin\{itemize\}(?:\[[^\]]*\])?', '', text)
    text = re.sub(r'\\end\{itemize\}', '', text)
    text = re.sub(r'\\begin\{enumerate\}(?:\[[^\]]*\])?', '', text)
    text = re.sub(r'\\end\{enumerate\}', '', text)
    text = re.sub(r'\\item\s*', '\n- ', text)

    # ``\verb<delim>content<delim>`` — LaTeX inline-verbatim. The delimiter is
    # any non-alphanumeric, non-space character. Convert to inline backticks
    # so the content (often containing ``<>|``) survives downstream HTML
    # processing intact. Use a backreference so we close on the same delimiter
    # that opened the verb region.
    def _verb_to_backticks(match: "re.Match[str]") -> str:
        content = match.group("content")
        # Pick a backtick wrapping that won't collide with any backticks in
        # content. Single ` works for >99% of cases; double `` falls back when
        # content has a single `.
        if "`" not in content:
            return f"`{content}`"
        if "``" not in content:
            return f"``{content}``"
        return content  # extreme corner case — no safe wrap, just inline
    text = re.sub(
        r'\\verb(?P<delim>[^A-Za-z0-9 \t\n*])(?P<content>.+?)(?P=delim)',
        _verb_to_backticks, text,
    )
    # ``\verb*`` is a starred variant that renders spaces as visible squares;
    # for card output we treat it identically to ``\verb``.
    text = re.sub(
        r'\\verb\*(?P<delim>[^A-Za-z0-9 \t\n*])(?P<content>.+?)(?P=delim)',
        _verb_to_backticks, text,
    )

    # Code-like environments: wrap content in fenced code blocks so that
    # downstream HTML-escape passes don't mangle ``<``/``>`` (e.g. Cypher
    # relationship syntax, Python type hints).
    for env, lang in (('verbatim', ''), ('pycode', 'python')):
        text = re.sub(
            rf'\\begin\{{{env}\}}(?:\[[^\]]*\])?(?:\{{[^{{}}]*\}})?(.*?)\\end\{{{env}\}}',
            lambda m, _lang=lang: f'\n```{_lang}\n{m.group(1).strip()}\n```\n',
            text, flags=re.DOTALL,
        )

    # Layout / formatting environments that carry no semantic weight in card
    # output. Without explicit handling, the extractor only strips the leading
    # ``\\begin{`` and trailing ``}``, leaving the bare environment name as
    # text (``sloppyparMATCH (n)-[:REL]->...sloppypar``). Strip the wrappers
    # entirely so contents flow through unchanged.
    for env in (
        'sloppypar', 'quote', 'quotation',
        'flushleft', 'flushright', 'center', 'tabular', 'tabularx',
    ):
        text = re.sub(rf'\\begin\{{{env}\}}(?:\[[^\]]*\])?(?:\{{[^{{}}]*\}})?', '', text)
        text = re.sub(rf'\\end\{{{env}\}}', '', text)

    # Description lists - convert [term:] description to **term:** description
    text = re.sub(r'\\begin\{description\}(?:\[[^\]]*\])?', '', text)
    text = re.sub(r'\\end\{description\}', '', text)
    # Handle \item[Label] Description format
    text = re.sub(r'\\item\[([^\]]+)\]\s*', r'\n**\1** ', text)
    # Handle - [Label:] Description format (alternative syntax)
    text = re.sub(r'-\s*\[([^\]]+):\]\s*', r'\n**\1:** ', text)

    # Remove other common LaTeX commands
    text = re.sub(r'\\label\{[^}]*\}', '', text)
    # \ref{} is handled earlier by _expand_ref; no-op here
    text = re.sub(r'\\cite\{[^}]*\}', '', text)
    text = re.sub(r'\\autocite\{[^}]*\}', '', text)
    text = re.sub(r'\\footcite\{[^}]*\}', '', text)
    text = re.sub(r'\\footnote\{[^}]*\}', '', text)

    # STAR story framework commands - convert to formatted headers
    text = re.sub(r'\\situation\{([^}]*)\}', r'\n\n**Situation:**\n\1', text)
    text = re.sub(r'\\task\{([^}]*)\}', r'\n\n**Task:**\n\1', text)
    text = re.sub(r'\\action\{([^}]*)\}', r'\n\n**Action:**\n\1', text)
    text = re.sub(r'\\result\{([^}]*)\}', r'\n\n**Result:**\n\1', text)
    text = re.sub(r'\\youredge\{([^}]*)\}', r'\n\n**Your Edge:**\n\1', text)

    # Code blocks (minted) - preserve code content with markdown formatting
    # Preserve language tag: \begin{minted}{python} → ```python
    text = re.sub(r'\\begin\{minted\}\{([^}]*)\}', r'\n```\1\n', text)
    text = re.sub(r'\\begin\{minted\}\[[^\]]*\]\{([^}]*)\}', r'\n```\1\n', text)
    text = re.sub(r'\\end\{minted\}', '\n```\n', text)

    # lstlisting environment - normalize to markdown code fences
    # Extract language from [language=Python] option if present
    text = re.sub(r'\\begin\{lstlisting\}\[language=(\w+)[^\]]*\]', lambda m: f'\n```{m.group(1).lower()}\n', text)
    text = re.sub(r'\\begin\{lstlisting\}(?:\[[^\]]*\])?', '\n```\n', text)  # fallback without language
    text = re.sub(r'\\end\{lstlisting\}', '\n```\n', text)

    # === PROTECT CODE BLOCKS FROM WHITESPACE NORMALIZATION ===
    # Pattern proven in generate_anki.py:666-680 — extract code regions before
    # cleanup, restore after. Without this, re.sub(r'[ \t]+', ' ', text) at line
    # ~682 collapses Python indentation to single spaces.
    _code_regions: list[str] = []

    def _preserve_code(match: re.Match) -> str:
        _code_regions.append(match.group(0))
        return f'__CODE_BLOCK_{len(_code_regions) - 1}__'

    # Protect both fenced (``` ... ```) and inline (`code`) regions so that
    # downstream regex passes (math-mode dollar removal, ``<``→``&lt;``
    # escaping, brace cleanup) leave them intact. Without inline-backtick
    # protection, Cypher relationship syntax ``(c)<-[:REL]-(p)`` gets the
    # ``<-`` HTML-escaped to ``&lt;-`` even when wrapped in backticks.
    text = re.sub(
        r'(?:```[a-zA-Z]*\n.*?\n```|`[^`]+?`)',
        _preserve_code, text, flags=re.DOTALL,
    )

    # Tables - convert simple tabular to readable format
    text = re.sub(r'\\begin\{table\}(\[[^\]]*\])?', '\n', text)  # table with optional placement
    text = re.sub(r'\\end\{table\}', '\n', text)
    # Handle tabular - match entire line containing \begin{tabular} to avoid partial matches
    text = re.sub(r'\\begin\{tabular\}[^\n]*', '\n', text)
    text = re.sub(r'\\end\{tabular\}', '\n', text)
    text = re.sub(r'\\begin\{tabularx\}[^\n]*', '\n', text)
    text = re.sub(r'\\end\{tabularx\}', '\n', text)
    text = re.sub(r'\\begin\{figure\}(\[[^\]]*\])?', '\n', text)  # figure with optional placement
    text = re.sub(r'\\end\{figure\}', '\n', text)
    text = re.sub(r'\\caption\{[^}]*\}', '', text)  # Remove captions
    text = re.sub(r'\\hline', '', text)
    text = re.sub(r'\\toprule', '', text)
    text = re.sub(r'\\midrule', '', text)
    text = re.sub(r'\\bottomrule', '', text)
    text = re.sub(r'@\{[^}]*\}', '', text)  # Remove @ column specifiers
    text = re.sub(r'&', ' | ', text)  # Table cell separator

    # Math environments - remove but keep content
    text = re.sub(r'\\begin\{equation\*?\}', '\n', text)
    text = re.sub(r'\\end\{equation\*?\}', '\n', text)
    text = re.sub(r'\\begin\{align\*?\}', '\n', text)
    text = re.sub(r'\\end\{align\*?\}', '\n', text)
    text = re.sub(r'\\begin\{gather\*?\}', '\n', text)
    text = re.sub(r'\\end\{gather\*?\}', '\n', text)
    text = re.sub(r'\\\[', '\n', text)  # Display math start
    text = re.sub(r'\\\]', '\n', text)  # Display math end

    # Other common environments
    text = re.sub(r'\\begin\{quote\}', '\n', text)
    text = re.sub(r'\\end\{quote\}', '\n', text)
    text = re.sub(r'\\begin\{center\}', '\n', text)
    text = re.sub(r'\\end\{center\}', '\n', text)
    text = re.sub(r'\\begin\{flushleft\}', '\n', text)
    text = re.sub(r'\\end\{flushleft\}', '\n', text)
    text = re.sub(r'\\begin\{flushright\}', '\n', text)
    text = re.sub(r'\\end\{flushright\}', '\n', text)

    # Additional LaTeX commands cleanup
    text = re.sub(r'\\par\b', '\n\n', text)
    text = re.sub(r'\\noindent\b', '', text)
    text = re.sub(r'\\hspace\*?\{[^}]*\}', ' ', text)
    text = re.sub(r'\\vspace\*?\{[^}]*\}', '\n', text)
    text = re.sub(r'\\medskip', '\n', text)
    text = re.sub(r'\\bigskip', '\n', text)
    text = re.sub(r'\\smallskip', '\n', text)
    text = re.sub(r'\\newline', '\n', text)
    text = re.sub(r'\\centering', '', text)

    # Clean up any remaining simple LaTeX commands (single backslash word)
    # Be careful not to remove content - only commands with no arguments
    text = re.sub(r'\\[a-z]+\b(?!\{)', ' ', text)

    # Final aggressive cleanup for remaining LaTeX with arguments
    # This handles nested braces by matching outer braces repeatedly
    for _ in range(5):
        # Remove \command{simple content} patterns
        text = re.sub(r'\\[a-zA-Z]+\{([^{}]*)\}', r'\1', text)
    # Remove empty braces or braces with just whitespace
    text = re.sub(r'\{\s*\}', '', text)
    # Clean up orphan table column specs like {lccc} or {|l|c|r|}
    text = re.sub(r'\{[lcr|@p\d\.\{\}\\]*\}', '', text)
    # Handle LaTeX thousand separator {,}
    text = re.sub(r'\{,\}', ',', text)
    # Last resort: remove any remaining \command{ patterns (incomplete/malformed)
    text = re.sub(r'\\[a-zA-Z]+\{', '', text)

    # Preserve paragraph breaks (double newlines) but normalize other whitespace
    # First, mark paragraph breaks
    text = re.sub(r'\n\s*\n', '\n\n', text)
    # Then normalize other whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    # Clean up excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Clean up artifacts left when citations / footnotes were stripped:
    # leading whitespace before terminal punctuation (e.g., ``task .`` → ``task.``)
    text = re.sub(r' +([.,;:!?])', r'\1', text)
    # Period stranded on its own line after a stripped citation
    text = re.sub(r'\n\s*([.,;:!?])', r'\1', text)

    # Escape bare < / > that originate from math subscripts (e.g. ``x_{<t}``).
    # Anki renders card bodies as HTML, so ``<t}`` is misparsed as an opening
    # tag. We only escape the math-artifact patterns — not well-formed HTML
    # tags that may have been intentionally emitted by upstream converters.
    # Pattern: ``<`` followed by a letter + closing brace (definitely math),
    # or ``<`` followed by a space / digit / math operator (also math).
    text = re.sub(r'<(?=[a-zA-Z]\})', '&lt;', text)       # x_{<t}, x_{<s} etc.
    text = re.sub(r'<(?=[\s0-9=+\-*/])', '&lt;', text)    # <= 5, < 0 etc.
    text = re.sub(r'(?<=[a-zA-Z0-9])\s*>(?=\s*[,.\])}])', '&gt;', text)  # n> ,

    # === RESTORE PROTECTED CODE BLOCKS ===
    for i, region in enumerate(_code_regions):
        text = text.replace(f'__CODE_BLOCK_{i}__', region)

    # === RESTORE PROTECTED MATH REGIONS ===
    # Math stays as ``$...$`` / ``$$...$$`` / ``\[...\]`` in the YAML so
    # yaml_to_apkg.py can apply its MathJax delimiter conversion at export.
    for i, region in enumerate(_math_regions):
        text = text.replace(f'__MATH_REGION_{i}__', region)

    # === RESTORE LATEX-LITERAL ESCAPE SENTINELS ===
    # Paired with the protection block near the top of this function.
    text = text.replace('\x00BACKSLASH\x00', '\\')
    text = text.replace('\x00AMP\x00', '&')
    text = text.replace('\x00HASH\x00', '#')
    text = text.replace('\x00USCORE\x00', '_')
    text = text.replace('\x00LBRACE\x00', '{')
    text = text.replace('\x00RBRACE\x00', '}')

    text = text.strip()

    return text


def extract_terms(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    """Extract term definitions from LaTeX content.

    Supports both legacy and new format:
    - \\term{name}{definition}           - backward compatible
    - \\term[LOS]{name}{definition}      - with LOS reference for traceability
    """
    cards = []
    # Pattern: \term[optional-LOS]{name}{definition}
    # Handle nested braces in definition (e.g., equations)
    pattern = r'\\term(?:\[([^\]]*)\])?\{([^}]+)\}\{((?:[^{}]|\{[^{}]*\})*)\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        los_id = match.group(1)  # Optional LOS bracket (None if not present)
        name = match.group(2).strip()
        definition = match.group(3).strip()
        definition = clean_latex(definition)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="TERM",
            title=name,
            body=definition,
            los_id=los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:term', f'term:{name.lower().replace(" ", "_")}']
        if los_id:
            # Handle multiple LOS IDs separated by comma
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        cards.append({
            'type': 'term',
            'id': card_id,
            'front': f"Define: {name}",
            'back': truncate_at_sentence(definition, 400),  # Increased from 300
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_redflags(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract common mistakes (red flags) from LaTeX content.

    Supports two-optional-parameter syntax:
    - \begin{redflag}[Title]...\end{redflag}           - backward compatible
    - \begin{redflag}[Title][LOS-ID]...\end{redflag}   - with LOS reference
    """
    cards = []
    # Pattern: \begin{redflag}[title][optional-LOS]...
    # Two optional bracket parameters: Group 1 = title, Group 2 = LOS
    pattern = r'\\begin\{redflag\}(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(.*?)\\end\{redflag\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Common Mistake"
        los_id = match.group(2)  # None if not present
        body = match.group(3).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="RF",
            title=title,
            body=body,
            los_id=los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:redflag', 'type:mistake']
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        cards.append({
            'type': 'redflag',
            'id': card_id,
            'front': f"Warning: {title}",
            'back': truncate_at_sentence(body, 500),
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_problems(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract problems with their solutions.

    Only extracts problems that have an explicit \begin{solution}...\end{solution} block.
    Problems without solutions are skipped (quality over quantity).

    Supports three formats:
    - \begin{problem}[LOS-ID]...\end{problem} - Standard format with LOS reference
    - \begin{problem}[][LOS-ID]...\end{problem} - Two-bracket format (empty title, LOS)
    - \begin{problembox}{Title}...\end{problembox} - Vol 14 format with title

    Special handling for Vol 4 SQL cards with SQL-X.Y LOS format.
    """
    cards = []

    # Pattern 1: \begin{problem}[title][LOS-ID][difficulty][scaffolding]body\end{problem}
    # Supports 1-4 brackets. Group 1-4 = brackets, 5 = body
    problem_pattern = r'\\begin\{problem\}(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(.*?)\\end\{problem\}'

    # Pattern 2: \begin{problembox}{Title}...\end{problembox} (Vol 14 style)
    problembox_pattern = r'\\begin\{problembox\}\{([^}]*)\}(.*?)\\end\{problembox\}'

    # Find all standard problems
    for match in re.finditer(problem_pattern, content, re.DOTALL):
        # Handle two-bracket vs one-bracket formats
        if match.group(2) is not None:
            # Two+ brackets: [][LOS] or [Title][LOS] - second is LOS
            los_id = match.group(2) or ""
        else:
            # One bracket: [LOS] - first is LOS
            los_id = match.group(1) or ""
        # Third bracket is difficulty (foundation|standard|stretch)
        difficulty = (match.group(3) or "").strip().lower() or None
        if difficulty and difficulty not in ("foundation", "standard", "stretch"):
            difficulty = None  # Ignore invalid values
        # Fourth bracket is scaffolding level (full|partial|none) for WFP tracking
        scaffolding = (match.group(4) or "").strip().lower() or None
        if scaffolding and scaffolding not in ("full", "partial", "none"):
            scaffolding = None
        problem_text = match.group(5).strip()

        # Look for solution immediately following the problem
        # Search in the content after this problem ends
        remaining_content = content[match.end():]

        # Check if solution block exists within reasonable distance (next 15000 chars)
        # Window increased from 8000 to handle long solutions with code blocks
        solution_pattern = r'\\begin\{solution\}(.*?)\\end\{solution\}'
        solution_match = re.search(solution_pattern, remaining_content[:15000], re.DOTALL)

        # Skip problems without explicit solution blocks
        if not solution_match:
            continue

        solution_text = solution_match.group(1).strip()

        # Clean up the text
        problem_clean = clean_latex(problem_text)
        solution_clean = clean_latex(solution_text)

        # Strip \companytags{} from problem text for ID generation
        problem_for_id = re.sub(r'\\companytags\{[^}]*\}', '', problem_clean)

        # Use unified ID generator with problem content as "title" (for semantic extraction)
        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="PROB",
            title="",  # Force semantic extraction from body
            body=problem_for_id,
            los_id=los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:problem']
        if los_id:
            # Handle multiple LOS IDs separated by comma
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    # Replace spaces with underscores for tag validity
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        card = {
            'type': 'problem',
            'id': card_id,
            'front': truncate_at_sentence(problem_clean, 800),   # Increased from 600
            'back': truncate_at_sentence(solution_clean, 2000),  # Increased from 1000 to preserve Answer/Key Insight at end
            'los_id': los_id if los_id else None,
            'source': source_file,
            'tags': tags,
        }
        if difficulty:
            card['difficulty'] = difficulty
            tags.append(f'difficulty:{difficulty}')
        if scaffolding:
            card['scaffolding_level'] = scaffolding
            tags.append(f'scaffolding:{scaffolding}')
        cards.append(card)

    # Find all problembox entries (Vol 14 style)
    for match in re.finditer(problembox_pattern, content, re.DOTALL):
        title = match.group(1).strip()
        problem_text = match.group(2).strip()

        # Look for solution immediately following the problembox
        remaining_content = content[match.end():]

        # Check if solution block exists within reasonable distance (next 15000 chars)
        solution_pattern = r'\\begin\{solution\}(.*?)\\end\{solution\}'
        solution_match = re.search(solution_pattern, remaining_content[:15000], re.DOTALL)

        # Skip problems without explicit solution blocks
        if not solution_match:
            continue

        solution_text = solution_match.group(1).strip()

        # Clean up the text
        problem_clean = clean_latex(problem_text)
        solution_clean = clean_latex(solution_text)

        # Use unified ID generator with title (problembox has explicit titles)
        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="PROB",
            title=title,
            body=problem_clean,
            los_id=None,
            seen_ids=seen_ids
        )

        # Build tags - use title as tag since no LOS ID
        tags = ['type:problem', f'title:{slugify(title, 30)}']

        cards.append({
            'type': 'problem',
            'id': card_id,
            'front': f"**{title}**\n\n{truncate_at_sentence(problem_clean, 750)}",
            'back': truncate_at_sentence(solution_clean, 2000),  # Match problem card limit
            'los_id': None,  # problembox doesn't have LOS ID
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_vignettes(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract CFA-style case study vignettes.

    Supports two-optional-parameter syntax:
    - \begin{vignette}[Title]...\end{vignette}           - backward compatible
    - \begin{vignette}[Title][LOS-ID]...\end{vignette}   - with LOS reference

    Intelligently splits vignette into:
    - FRONT: Scenario + data (everything before first Question marker)
    - BACK: Questions + Answer Rubric (if solution block follows vignette)
    """
    cards = []

    # Pattern: \begin{vignette}[title][optional-LOS]...
    # Two optional bracket parameters: Group 1 = title, Group 2 = LOS
    pattern = r'\\begin\{vignette\}(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(.*?)\\end\{vignette\}'

    # Question marker patterns (conservative - only known formats)
    # Order matters: more specific patterns first
    QUESTION_MARKERS = [
        r'(\\textbf\{Question\s*\d*[:\.]?\})',           # Question 1: or Question:
        r'(\\textbf\{Discussion Questions?[:\.]?\})',    # Discussion Questions:
        r'(\\textit\{Questions?[:\.]?\})',                # \textit{Questions:}
    ]

    def split_at_questions(body: str) -> tuple[str, str]:
        """Split vignette body at first question marker.

        Returns:
            (scenario, questions) - scenario is content before marker,
            questions is marker + everything after
        """
        for q_pattern in QUESTION_MARKERS:
            parts = re.split(q_pattern, body, maxsplit=1)
            if len(parts) >= 3:
                scenario = parts[0].strip()
                questions = parts[1] + parts[2]  # marker + rest
                return scenario, questions
        # No marker found - return full body as scenario, empty questions
        return body, ""

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Case Study"
        los_id = match.group(2)  # None if not present
        body = match.group(3).strip()

        # Search for solution block following this vignette (within 25000 chars)
        # Window increased from 5000 to handle long case study solutions
        solution_pattern = r'\\begin\{solution\}(.*?)\\end\{solution\}'
        search_window = content[match.end():match.end() + 25000]
        solution_match = re.search(solution_pattern, search_window, re.DOTALL)

        solution = ""
        if solution_match:
            solution = clean_latex(solution_match.group(1).strip())

        # Split at first question marker for better card structure
        scenario_raw, questions_raw = split_at_questions(body)

        if questions_raw:
            # Has questions: scenario is before, questions after
            scenario = clean_latex(scenario_raw)
            questions = clean_latex(questions_raw)

            front_text = f"Case Study: {title}\n\n{scenario}"
            back_text = questions
        else:
            # No clear question split, use full body as back
            body_cleaned = clean_latex(body)
            front_text = f"Case Study: {title}"
            back_text = truncate_at_sentence(body_cleaned, 2000)  # Match problem card limit

        # Append solution as Answer Rubric if found
        if solution:
            back_text = f"{back_text}\n\n---\n\n**Answer Rubric:**\n{solution}"

        # Use unified ID generator - pass scenario content for semantic extraction
        scenario_for_id = scenario_raw if questions_raw else body
        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="VIG",
            title=title,
            body=scenario_for_id,
            los_id=los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:vignette', 'type:case_study']
        if solution:
            tags.append('has_solution')
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        cards.append({
            'type': 'vignette',
            'id': card_id,
            'front': front_text,
            'back': back_text,
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_interview_contexts(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract interview strategy contexts with question-based fronts.

    Extracts actual interview questions from body content for active recall.
    Falls back to title-based front only if no question pattern found.

    Supports two-optional-parameter syntax:
    - \begin{interviewcontext}[Title]...\end{interviewcontext}           - backward compatible
    - \begin{interviewcontext}[Title][LOS-ID]...\end{interviewcontext}   - with LOS reference
    """
    cards = []

    # Pattern: \begin{interviewcontext}[title][optional-LOS]...
    # Two optional bracket parameters: Group 1 = title, Group 2 = LOS
    pattern = r'\\begin\{interviewcontext\}(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(.*?)\\end\{interviewcontext\}'

    # Patterns to extract interview questions from body
    question_patterns = [
        r'[Ww]hen asked (?:about |")([^",]+)',  # "When asked about X"
        r'[Hh]ow would you ([^?]+\?)',  # "How would you X?"
        r'[Ww]hat (?:is|are) ([^?]+\?)',  # "What is X?"
        r'[Ee]xplain (?:why |how )?([^.?]+)',  # "Explain why/how X"
        r'[Ww]alk (?:me |us )?through ([^.?]+)',  # "Walk me through X"
        r'[Dd]escribe ([^.?]+)',  # "Describe X"
    ]

    # Patterns to extract topic from body when no bracket title
    topic_patterns = [
        r'^(?:This|The) (?:question|topic|concept) (?:covers?|is about|addresses?) ([^.]+)',
        r'^(?:Focus on|Emphasize|Highlight) ([^.]+)',
        r'^Key (?:point|concept|idea)s?: ([^.]+)',
    ]

    for idx, match in enumerate(re.finditer(pattern, content, re.DOTALL)):
        bracket_title = match.group(1)
        los_id = match.group(2)  # None if not present
        los_ids = [x.strip() for x in los_id.split(',') if x.strip()] if los_id else []
        primary_los_id = los_ids[0] if los_ids else None
        body = match.group(3).strip()
        body_clean = clean_latex(body)

        # Determine title: use bracket title, or extract from body, or generic fallback
        if bracket_title:
            # Clean LaTeX quote marks from title
            title = bracket_title.replace("``", "").replace("''", "").replace('"', '').strip()
        else:
            # Try to extract topic from body
            extracted_topic = None
            for t_pattern in topic_patterns:
                t_match = re.search(t_pattern, body_clean)
                if t_match:
                    extracted_topic = t_match.group(1).strip()[:60]
                    break

            # If no topic extracted, use first meaningful words from body
            if not extracted_topic:
                # Get first sentence or first N words
                first_sentence = body_clean.split('.')[0][:80]
                if len(first_sentence) > 20:
                    extracted_topic = first_sentence.rsplit(' ', 1)[0] + '...'
                else:
                    extracted_topic = f"Strategy {idx + 1}"

            title = extracted_topic

        # Try to extract actual interview question from body
        front = None
        for q_pattern in question_patterns:
            q_match = re.search(q_pattern, body_clean)
            if q_match:
                question = q_match.group(1).strip()
                # Truncate long questions, ensure ends cleanly
                if len(question) > 100:
                    question = question[:100].rsplit(' ', 1)[0] + '...'
                front = f"Interview Q: {question}"
                break

        # Fallback to title if no question pattern found - generate specific prompt
        if not front:
            title_lower = title.lower()
            # Generate context-aware prompt based on title
            if 'why' in title_lower and 'matter' in title_lower:
                front = f"Interview: Why does this matter? What business context should you lead with?"
            elif 'example' in title_lower:
                # Extract the concept being exemplified
                concept = title.replace('Example', '').replace('example', '').strip()
                front = f"Interview: Tell a STAR story about {concept}. What was the situation and outcome?"
            elif 'practice' in title_lower and 'question' in title_lower:
                # Use first meaningful sentence from body as the prompt
                first_line = body_clean.split('\n')[0].strip()
                if first_line and len(first_line) > 10:
                    front = f"Interview: {first_line[:150]}"
                else:
                    front = f"Interview: Practice answering this question out loud."
            elif 'template' in title_lower or 'structure' in title_lower:
                front = f"Interview: What is the {title}? Walk through each step."
            elif 'recovery' in title_lower or 'phrase' in title_lower:
                front = f"Interview: What are key recovery phrases when stuck? When do you use each?"
            elif 'best practice' in title_lower:
                front = f"Interview: What are the {title}?"
            else:
                # Default: clean title and frame as "Explain..."
                clean_title = title.replace("``", "").replace("''", "").replace('"', '').strip()
                front = f"Interview: {clean_title}"

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="INT",
            title=title,
            body=body_clean,
            los_id=primary_los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:interview', 'type:strategy']
        for single_los in los_ids:
            tags.append(f'los:{single_los.replace(" ", "_")}')

        card = {
            'type': 'interview',
            'id': card_id,
            'front': front,
            'back': truncate_at_sentence(body_clean, 600),
            'los_id': primary_los_id,
            'source': source_file,
            'tags': tags
        }
        if len(los_ids) > 1:
            card['los_ids'] = los_ids
        cards.append(card)

    return cards


def extract_company_tags(content: str) -> list[str]:
    """Extract company tags from LaTeX content."""
    tags = []
    # Pattern: \companytags{tag1, tag2, tag3}
    pattern = r'\\companytags\{([^}]+)\}'

    for match in re.finditer(pattern, content):
        tag_list = match.group(1).split(',')
        tags.extend([t.strip() for t in tag_list if t.strip()])

    return sorted(set(tags))


# =============================================================================
# Vol 0 Quick Reference Environment Extractors
# =============================================================================

def extract_formulacards(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract formula cards from Vol 0 content.

    Pattern: \begin{formulacard}[title]...\end{formulacard}
    Card type: formula
    Front: "Formula: {title}"
    """
    cards = []
    pattern = r'\\begin\{formulacard\}(?:\[([^\]]*)\])?(.*?)\\end\{formulacard\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Formula"
        body = match.group(2).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="FORMULA",
            title=title,
            body=body,
            los_id=None,
            seen_ids=seen_ids
        )

        cards.append({
            'type': 'formula',
            'id': card_id,
            'front': f"Formula: {title}",
            'back': truncate_at_sentence(body, 600),
            'source': source_file,
            'tags': ['type:formula', f'formula:{slugify(title, 30).lower()}']
        })

    return cards


def _strip_leading_label(body: str) -> str:
    r"""Strip leading ``\label{...}`` (and surrounding whitespace) from body.

    Used by math-environment extractors where the first token inside the
    environment is almost always a label that should not appear on the card.

    Parameters
    ----------
    body : str
        Raw environment body, potentially starting with a label.

    Returns
    -------
    str
        Body with leading ``\label{...}`` removed; unchanged if no label.
    """
    return re.sub(r"^\s*\\label\{[^}]*\}\s*", "", body, count=1)


def _clean_title(title: str) -> str:
    r"""Strip noise from an environment title before it lands on a card front.

    Environment titles like ``\begin{theorem}[Low-Rank Factorization~\autocite{x}]``
    pass straight into the front template. We don't want to run the full
    ``clean_latex`` pipeline on them (it would mangle math, drop bold, etc.),
    but we do want to remove a small set of artifacts that are always wrong
    on a card front:

    - Citation macros (``\autocite``, ``\cite``, ``\citep``, ``\parencite``,
      ``\textcite``, ``\citet``) — only meaningful in the typeset PDF.
    - LaTeX non-breaking space ``~`` adjacent to citations becomes a stray
      space; collapse runs of whitespace.
    - LaTeX en-dash ``--`` and em-dash ``---`` are converted to their
      Unicode equivalents so titles read naturally.

    Math (e.g. ``$d_k$``), bold (``\textbf``), and other formatting are
    intentionally preserved — drill / theorem titles legitimately use them.

    Parameters
    ----------
    title : str
        Raw bracketed-argument title from ``\begin{env}[Title]``.

    Returns
    -------
    str
        Cleaned title suitable for direct use in a card-front template.
    """
    # Strip citation macros: \autocite, \cite, \citep, \parencite, \textcite, \citet
    title = re.sub(
        r'\\(?:autocite|cite|citep|parencite|textcite|citet)\*?'
        r'(?:\[[^\]]*\])?\{[^}]*\}',
        '',
        title,
    )
    # Convert LaTeX dashes to Unicode (em-dash before en-dash so --- wins).
    title = title.replace('---', '\u2014')   # em-dash
    title = title.replace('--', '\u2013')    # en-dash
    # ``~`` is LaTeX non-breaking space; treat as a normal space here.
    title = title.replace('~', ' ')
    # Collapse runs of whitespace introduced by stripped citations + spaces.
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def _extract_math_env(
    content: str,
    env_name: str,
    source_file: str,
    volume: str,
    chapter: str,
    seen_ids: set,
    *,
    card_type: str,
    front_template: str,
    type_tag: str,
    extra_tags: list[str] | None = None,
    default_title: str = "Untitled",
    back_max: int = 600,
) -> list[dict[str, Any]]:
    r"""Generic extractor for ``\begin{<env>}[Title]...\end{<env>}`` math environments.

    Unified implementation for ``definition``, ``proposition``, and ``theorem``
    environments used in math-reference guides (e.g. ``transformer_mathematics``).
    Each match emits a card whose front is ``front_template.format(title=...)``
    and whose back is the cleaned environment body with any leading
    ``\label{...}`` stripped.

    Parameters
    ----------
    content : str
        Full LaTeX source to scan.
    env_name : str
        Name of the LaTeX environment (e.g. ``"definition"``).
    source_file : str
        Source filename for provenance (already volume-prefixed).
    volume, chapter : str
        Identifiers used in ID generation.
    seen_ids : set
        Running set of emitted IDs for collision resolution.
    card_type : str
        Short tag used in the card ID (e.g. ``"MDEF"``).
    front_template : str
        Format string with ``{title}`` placeholder for card front.
    type_tag : str
        Value for the ``type`` key on each emitted card (e.g. ``"term"``).
    extra_tags : list[str] | None
        Extra tag strings merged into every card's ``tags`` list.
    default_title : str
        Title used when the optional ``[...]`` bracket is absent.
    back_max : int
        Max length (chars) before truncating the back at a sentence boundary.

    Returns
    -------
    list[dict[str, Any]]
        One card dict per matched environment, in document order.

    Raises
    ------
    ValueError
        If ``env_name`` is empty, or if ``front_template`` lacks ``{title}``.
    """
    if not env_name:
        raise ValueError("env_name must be non-empty")
    if "{title}" not in front_template:
        raise ValueError("front_template must contain '{title}' placeholder")

    extra_tags = list(extra_tags or [])
    cards: list[dict[str, Any]] = []
    pattern = (
        r"\\begin\{" + re.escape(env_name) + r"\}"
        r"(?:\[([^\]]*)\])?"
        r"(.*?)"
        r"\\end\{" + re.escape(env_name) + r"\}"
    )

    for match in re.finditer(pattern, content, re.DOTALL):
        title = _clean_title(match.group(1) or default_title)
        raw_body = match.group(2).strip()
        body_no_label = _strip_leading_label(raw_body)
        body = clean_latex(body_no_label).strip()
        if not body:
            # Skip empty environments: they carry no learnable content and
            # would produce a card with no back. Fail loudly only if the
            # title is also missing (should never happen with the regex above).
            if title == default_title:
                raise ValueError(
                    f"Empty {env_name} with default title in {source_file}: "
                    f"content[{match.start()}:{match.end()}]"
                )
            continue

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type=card_type,
            title=title,
            body=body,
            los_id=None,
            seen_ids=seen_ids,
        )

        tags = [f"type:{type_tag}", *extra_tags, f"env:{env_name}"]
        cards.append(
            {
                "type": type_tag,
                "id": card_id,
                "front": front_template.format(title=title),
                "back": truncate_at_sentence(body, back_max),
                "los_id": None,
                "source": source_file,
                "tags": tags,
            }
        )

    return cards


def extract_mathdefs(
    content: str, source_file: str, volume: str, chapter: str, seen_ids: set
) -> list[dict[str, Any]]:
    r"""Extract ``\begin{definition}[Title]\label{...}body\end{definition}`` → ``term`` cards.

    Distinct from :func:`extract_terms`, which handles the inline
    ``\term{name}{definition}`` macro. Math-reference guides place formal
    definitions in a ``definition`` environment with an optional bracketed
    title and a ``\label{...}`` token that is stripped from the card back.

    Emits cards with front ``"Define: {title}"`` and type ``term``.
    """
    return _extract_math_env(
        content, "definition", source_file, volume, chapter, seen_ids,
        card_type="MDEF",
        front_template="Define: {title}",
        type_tag="term",
        extra_tags=["type:definition", "source:mathenv"],
        default_title="Definition",
        # Math definitions often include 1-3 display equations (100-300 chars
        # each in LaTeX source). 1500 gives headroom without bloating.
        back_max=1500,
    )


def extract_propositions(
    content: str, source_file: str, volume: str, chapter: str, seen_ids: set
) -> list[dict[str, Any]]:
    r"""Extract ``\begin{proposition}[Title]\label{...}body\end{proposition}`` → ``formula`` cards.

    Propositions are the default theorem-like statement in math-reference
    guides. Emits cards with front ``"State: {title}"`` and type ``formula``
    so spaced repetition prompts explicit recall of the statement, not just
    recognition.
    """
    return _extract_math_env(
        content, "proposition", source_file, volume, chapter, seen_ids,
        card_type="PROP",
        front_template="State: {title}",
        type_tag="formula",
        extra_tags=["type:proposition", "source:mathenv"],
        default_title="Proposition",
        # Propositions state a result plus its conditions; display equations
        # common. 1600 fits most without cropping the conclusion.
        back_max=1600,
    )


def extract_theorems(
    content: str, source_file: str, volume: str, chapter: str, seen_ids: set
) -> list[dict[str, Any]]:
    r"""Extract ``\begin{theorem}[Title]\label{...}body\end{theorem}`` → ``formula`` cards.

    Theorems are higher-priority than propositions in math-reference guides
    (reserved for load-bearing results). Emits cards with front
    ``"Theorem: {title}"`` and the ``priority:high`` tag to allow deck
    filtering in Anki.
    """
    return _extract_math_env(
        content, "theorem", source_file, volume, chapter, seen_ids,
        card_type="THM",
        front_template="Theorem: {title}",
        type_tag="formula",
        extra_tags=["type:theorem", "source:mathenv", "priority:high"],
        default_title="Theorem",
        # Theorems frequently contain multi-line aligned equations + prose.
        # 2000 accommodates the largest proofs-in-statement without chopping.
        back_max=2000,
    )


def extract_sixtysec(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract 60-second explanation cards from Vol 0 content.

    Pattern: \begin{sixtysec}[concept]...\end{sixtysec}
    Card type: sixtysec
    Front: "60s Explain: {concept}"
    """
    cards = []
    pattern = r'\\begin\{sixtysec\}(?:\[([^\]]*)\])?(.*?)\\end\{sixtysec\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        concept = match.group(1) or "Concept"
        body = match.group(2).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="60SEC",
            title=concept,
            body=body,
            los_id=None,
            seen_ids=seen_ids
        )

        cards.append({
            'type': 'sixtysec',
            'id': card_id,
            'front': f"60s Explain: {concept}",
            'back': truncate_at_sentence(body, 500),
            'source': source_file,
            'tags': ['type:sixtysec', 'type:explanation']
        })

    return cards


def extract_drills(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract drill cards from speed-drill chapters.

    Pattern: \begin{drill}[LOS-ID]
               \drillprompt{question}
               \drillanswer{answer}
               \technique{note}          % optional
             \end{drill}

    Card type: drill
    Front: drill prompt text
    Back: structured answer + technique
    """
    cards = []
    # Match drill environment with optional LOS bracket
    pattern = r'\\begin\{drill\}(?:\[([^\]]*)\])?(.*?)\\end\{drill\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        los_id = match.group(1)  # Optional LOS-ID
        body = match.group(2).strip()

        # Extract drillprompt
        prompt_match = re.search(r'\\drillprompt\{((?:[^{}]|\{[^{}]*\})*)\}', body, re.DOTALL)
        if not prompt_match:
            continue
        prompt = clean_latex(prompt_match.group(1).strip())

        # Extract drillanswer
        answer_match = re.search(r'\\drillanswer\{((?:[^{}]|\{[^{}]*\}|\{[^{}]*\{[^{}]*\}[^{}]*\})*)\}', body, re.DOTALL)
        answer = clean_latex(answer_match.group(1).strip()) if answer_match else ""

        # Extract technique (optional)
        technique_match = re.search(r'\\technique\{((?:[^{}]|\{[^{}]*\}|\{[^{}]*\{[^{}]*\}[^{}]*\})*)\}', body, re.DOTALL)
        technique = clean_latex(technique_match.group(1).strip()) if technique_match else ""

        # Build back text
        back_parts = []
        if answer:
            back_parts.append(f"**Answer:**\n{answer}")
        if technique:
            back_parts.append(f"---\n\n**Technique:**\n{technique}")
        back_text = "\n\n".join(back_parts)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="DRILL",
            title=prompt[:60],
            body=back_text,
            los_id=los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:drill', 'type:timed']
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        cards.append({
            'type': 'drill',
            'id': card_id,
            'front': prompt,
            'back': truncate_at_sentence(back_text, 800),
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def _title_to_question(title: str) -> str:
    """Convert a keyconcept title to a recall-prompting question.

    Examples:
    - "GAME Framework" -> "Describe the GAME Framework. What does each component represent?"
    - "5-Step Investigation Framework" -> "What are the steps in the 5-Step Investigation Framework?"
    - "The Value Exchange" -> "Describe the Value Exchange concept."
    - "SUTVA Definition" -> "What is SUTVA? When does it apply?"
    """
    title_lower = title.lower()

    # Framework patterns
    if 'framework' in title_lower:
        if any(x in title_lower for x in ['step', '5-', '3-', 'level']):
            return f"What are the steps in the {title}?"
        return f"Describe the {title}. What does each component represent?"

    # Definition patterns
    if 'definition' in title_lower:
        concept = title.replace('Definition', '').replace('definition', '').strip()
        return f"What is {concept}? When does it apply?"

    # Formula patterns
    if 'formula' in title_lower or 'calculation' in title_lower:
        return f"What is the {title}? Show the formula and explain when to use it."

    # Template patterns
    if 'template' in title_lower:
        return f"What is the {title}? Walk through each component."

    # Checklist patterns
    if 'checklist' in title_lower:
        return f"What items are in the {title}?"

    # Comparison patterns
    if ' vs ' in title_lower or 'versus' in title_lower:
        return f"Compare and contrast: {title}. What are the key differences?"

    # Default: "Key Concept: title"
    return f"Key Concept: {title}"


def extract_keyconcepts(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract key concept cards from content.

    Pattern: \begin{keyconcept}[title]...\end{keyconcept}
    Card type: keyconcept
    Front: Question generated from title (prompts active recall)

    Supports multiple syntax variants:
    - \begin{keyconcept}[Title]...\end{keyconcept}           - title in brackets
    - \begin{keyconcept}[Title][LOS-ID]...\end{keyconcept}   - with LOS reference
    - \begin{keyconcept}[][LOS-ID]{Title}...\end{keyconcept} - title in braces (vol2 style)
    - \begin{keyconcept}{Title}...\end{keyconcept}           - title in braces only
    """
    cards = []
    # Pattern supports both bracket [Title] and brace {Title} formats
    # Groups: 1=bracket-title, 2=LOS, 3=brace-title, 4=body
    pattern = r'\\begin\{keyconcept\}(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(?:\{([^}]+)\})?(.*?)\\end\{keyconcept\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        bracket_title = match.group(1)  # Title in brackets [Title]
        los_id = match.group(2)          # LOS in second brackets [LOS]
        brace_title = match.group(3)     # Title in braces {Title}
        body = match.group(4).strip()

        # Prefer brace title (more specific), fall back to bracket title
        title = brace_title or bracket_title or "Key Concept"
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="CONCEPT",
            title=title,
            body=body,
            los_id=los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:keyconcept', 'type:concept']
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        # Convert title to question for better recall prompting
        front_question = _title_to_question(title)

        # Keep keyconcepts close to their full content — the canonical
        # 3-part form (Core Insight + Why It Matters + When It Breaks)
        # easily reaches 800-1000 chars for substantive concepts.
        # Truncate at 1500 (well above the 700 card_standards.md split
        # threshold). Cards >700 chars still get flagged by audit for
        # split per policy, but they extract fully so they remain useful
        # in the meantime.
        cards.append({
            'type': 'keyconcept',
            'id': card_id,
            'front': front_question,
            'back': truncate_at_sentence(body, 1500),
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_pitfalls(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract pitfall cards from Vol 0 content.

    Pattern: \begin{pitfall}[title]...\end{pitfall}
    Card type: pitfall
    Front: "Pitfall: {title}"
    """
    cards = []
    # Handle both [title] and {title} syntax
    pattern = r'\\begin\{pitfall\}(?:[\[{]([^\]\}]*)[\]}])?(.*?)\\end\{pitfall\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Common Pitfall"
        body = match.group(2).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="PITFALL",
            title=title,
            body=body,
            los_id=None,
            seen_ids=seen_ids
        )

        cards.append({
            'type': 'pitfall',
            'id': card_id,
            'front': f"Pitfall: {title}",
            'back': truncate_at_sentence(body, 500),
            'source': source_file,
            'tags': ['type:pitfall', 'type:mistake']
        })

    return cards


def extract_decisiontrees(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract decision tree cards from Vol 0 content.

    Patterns:
    - \begin{decisiontree}[title]...\end{decisiontree}            - backward compatible
    - \begin{decisiontree}[title][LOS-ID]...\end{decisiontree}    - with LOS reference
    Card type: decisiontree
    Front: "Decision: {title}"
    """
    cards = []
    # Match: optional [title], optional [LOS-ID], then body. Bracket form only.
    pattern = r'\\begin\{decisiontree\}(?:\[([^\]]*)\])?(?:\[([^\]]*)\])?(.*?)\\end\{decisiontree\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Decision Tree"
        los_id = match.group(2)  # None if not present
        body = match.group(3).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="DECISION",
            title=title,
            body=body,
            los_id=los_id,
            seen_ids=seen_ids
        )

        tags = ['type:decisiontree', 'type:framework']
        if los_id:
            for single_los in los_id.split(','):
                tags.append(f'los:{single_los.strip()}')

        cards.append({
            'type': 'decisiontree',
            'id': card_id,
            'front': f"Decision: {title}",
            'back': truncate_at_sentence(body, 800),
            'source': source_file,
            'los_id': los_id.strip() if los_id else None,
            'tags': tags,
        })

    return cards


def extract_interviewtips(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract interview tip cards from Vol 0 content.

    Pattern: \begin{interviewtip}[title]...\end{interviewtip}
    Card type: interviewtip
    Front: "Interview Tip: {title}"
    """
    cards = []
    # Handle both [title] and {title} syntax
    pattern = r'\\begin\{interviewtip\}(?:[\[{]([^\]\}]*)[\]}])?(.*?)\\end\{interviewtip\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Interview Tip"
        body = match.group(2).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="TIP",
            title=title,
            body=body,
            los_id=None,
            seen_ids=seen_ids
        )

        cards.append({
            'type': 'interviewtip',
            'id': card_id,
            'front': f"Interview Tip: {title}",
            'back': truncate_at_sentence(body, 400),
            'source': source_file,
            'tags': ['type:interviewtip', 'type:strategy']
        })

    return cards


def extract_actuarialbridges(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract actuarial bridge cards from LaTeX content.

    Extracts SOA-to-DS concept mappings for separate actuarial deck.

    Pattern: \begin{actuarialbridge}[Title]...\end{actuarialbridge}
    Card type: actuarialbridge
    Front: "SOA Bridge: {title}"
    """
    cards = []
    # Pattern: \begin{actuarialbridge}[title]...
    pattern = r'\\begin\{actuarialbridge\}(?:\[([^\]]*)\])?(.*?)\\end\{actuarialbridge\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "SOA Connection"
        body = match.group(2).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="ACTBRIDGE",
            title=title,
            body=body,
            los_id=None,
            seen_ids=seen_ids
        )

        # Extract interview leverage line if present
        interview_leverage = None
        leverage_match = re.search(r'[Ii]nterview leverage[:\s]+["\']?([^"\']+)["\']?', body)
        if leverage_match:
            interview_leverage = leverage_match.group(1).strip()

        cards.append({
            'type': 'actuarialbridge',
            'id': card_id,
            'front': f"SOA Bridge: {title}",
            'back': truncate_at_sentence(body, 800),
            'interview_leverage': interview_leverage,
            'source': source_file,
            'tags': ['type:actuarialbridge', 'type:soa_mapping', 'actuarial']
        })

    return cards


# =============================================================================
# VOL_META_TECH_SCREEN SPECIFIC EXTRACTORS
# =============================================================================

def extract_clozeterms(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract cloze deletion cards from LaTeX content.

    Pattern: \clozeterm[LOS]{name}{definition with {{c1::cloze}} deletions}
    Card type: cloze
    Front: "name" (with cloze deletions for interactive study)
    """
    cards = []
    # Use brace-balanced extraction since cloze definitions contain deeply nested
    # braces: {{c1::text}} and {{c2::\mathbb{E}_\pi[...]}} = 4 levels deep
    # Regex can't handle arbitrary nesting, so we find the start and manually
    # count braces to find the matching close.
    cloze_start_re = re.compile(r'\\clozeterm(?:\[([^\]]*)\])?\{([^}]+)\}\{')
    # Optional `\clozeback{...}` may immediately follow the closing brace of
    # the cloze front (whitespace/comments allowed between them). Captures
    # an explanatory back for the cloze card without disturbing the existing
    # macro contract. Brace balancing handled like the cloze front below.
    clozeback_start_re = re.compile(r'\A\s*\\clozeback\{')

    for match in cloze_start_re.finditer(content):
        los_id = match.group(1)
        name = match.group(2).strip()
        # Find matching closing brace by counting
        start = match.end()  # Position right after the opening {
        depth = 1
        pos = start
        while pos < len(content) and depth > 0:
            if content[pos] == '{':
                depth += 1
            elif content[pos] == '}':
                depth -= 1
            pos += 1
        if depth != 0:
            continue  # Unbalanced braces, skip
        definition = content[start:pos - 1].strip()
        definition = clean_latex(definition)

        # Optional `\clozeback{...}` immediately following — extract back text.
        back_text = ''
        tail = content[pos:]
        bm = clozeback_start_re.search(tail)
        if bm:
            bstart = pos + bm.end()  # position right after `\clozeback{`
            bdepth = 1
            bpos = bstart
            while bpos < len(content) and bdepth > 0:
                if content[bpos] == '{':
                    bdepth += 1
                elif content[bpos] == '}':
                    bdepth -= 1
                bpos += 1
            if bdepth == 0:
                back_text = clean_latex(content[bstart:bpos - 1].strip())

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="CLOZE",
            title=name,
            body=definition,
            los_id=los_id,
            seen_ids=seen_ids
        )

        tags = ['type:cloze', f'cloze:{name.lower().replace(" ", "_")}']
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        cards.append({
            'type': 'cloze',
            'id': card_id,
            'front': f"{name}: {definition}",  # Cloze deletions in definition
            'back': back_text,  # Optional \clozeback{} explanatory body
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_termbi(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract bidirectional term cards from LaTeX content.

    Pattern: \termbi[LOS]{term}{definition}
    Creates TWO cards: term→definition AND definition→term
    Card type: termbi
    """
    cards = []
    # Pattern handles up to 2 levels of brace nesting (same as clozeterm)
    nested_braces = r'(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*'
    pattern = rf'\\termbi(?:\[([^\]]*)\])?\{{([^}}]+)\}}\{{({nested_braces})\}}'

    for match in re.finditer(pattern, content, re.DOTALL):
        los_id = match.group(1)  # Optional LOS
        term = match.group(2).strip()
        definition = match.group(3).strip()
        definition = clean_latex(definition)

        # Build tags
        tags_base = ['type:termbi', 'type:term', f'term:{term.lower().replace(" ", "_")}']
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags_base.append(f'los:{single_los.replace(" ", "_")}')

        # Card 1: Term → Definition
        card_id_1 = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="TERMBI",
            title=term,
            body=definition,
            los_id=los_id,
            seen_ids=seen_ids
        )
        cards.append({
            'type': 'termbi',
            'id': card_id_1,
            'front': f"Define: {term}",
            'back': truncate_at_sentence(definition, 400),
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags_base + ['direction:forward']
        })

        # Card 2: Definition → Term (reverse lookup)
        # Use different body to generate distinct hash for reverse card
        card_id_2 = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="TERMBI",
            title=f"{term}-REV",
            body=definition,
            los_id=los_id,
            seen_ids=seen_ids
        )
        # Create a short hint from definition (first 80 chars)
        hint = definition[:80] + "..." if len(definition) > 80 else definition
        # For reverse back: if term is short (<15 chars), add parenthetical
        # Extract first phrase (up to period or comma) for context
        first_phrase = definition.split('.')[0].split(',')[0].strip()
        if len(first_phrase) > 40:
            first_phrase = first_phrase[:37] + "..."
        # Build descriptive back: "Term (context)" if term is short
        if len(term) < 15 and first_phrase and first_phrase.lower() != term.lower():
            reverse_back = f"{term} ({first_phrase})"
        else:
            reverse_back = term
        cards.append({
            'type': 'termbi',
            'id': card_id_2,
            'front': f"What term describes: {hint}",
            'back': reverse_back,
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags_base + ['direction:reverse']
        })

    return cards


def extract_levelcards(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract level comparison cards (IC4 vs IC5) from LaTeX content.

    Pattern: \begin{levelcard}{title}[LOS-ID]...\end{levelcard}
    Card type: levelcard
    Front: "IC4 vs IC5: {title}"

    Handles \levelrow{Dimension}{IC4 expectation}{IC5 expectation} commands
    by converting them to a markdown table.
    """
    cards = []
    # Pattern: \begin{levelcard}{Title}[optional-LOS]...
    # Title is in braces, LOS is optional in brackets
    pattern = r'\\begin\{levelcard\}\{([^}]+)\}(?:\[([^\]]*)\])?(.*?)\\end\{levelcard\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1).strip()
        los_id = match.group(2)  # Optional LOS bracket
        body = match.group(3).strip()

        # Process \levelrow commands into markdown table
        levelrows = re.findall(r'\\levelrow\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}', body)

        if levelrows:
            # Build markdown table for IC4 vs IC5 comparison
            table_lines = [
                "| Dimension | IC4 | IC5 |",
                "|-----------|-----|-----|"
            ]
            for dim, ic4, ic5 in levelrows:
                # Clean LaTeX from cell contents
                dim_clean = clean_latex(dim.strip())
                ic4_clean = clean_latex(ic4.strip())
                ic5_clean = clean_latex(ic5.strip())
                table_lines.append(f"| {dim_clean} | {ic4_clean} | {ic5_clean} |")

            body = "\n".join(table_lines)
        else:
            # Fallback: clean LaTeX normally
            body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="LEVEL",
            title=title,
            body=body,
            los_id=los_id,
            seen_ids=seen_ids
        )

        # Build tags
        tags = ['type:levelcard', 'type:level_comparison', 'meta:ic4', 'meta:ic5']
        if los_id:
            tags.append(f'los:{los_id.strip().replace(" ", "_")}')

        cards.append({
            'type': 'levelcard',
            'id': card_id,
            'front': f"IC4 vs IC5: {title}",
            'back': body,  # Already formatted as table, don't truncate
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_comparisoncards(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract 2-column comparison cards from LaTeX content.

    Pattern: \begin{comparisoncard}{title}{col1}{col2}[LOS-ID]...\end{comparisoncard}
    Card type: comparison
    Front: "Compare: {title}"

    Handles \comprow{Dimension}{Value1}{Value2} commands
    by converting them to a markdown table with custom headers.
    """
    cards = []
    # Pattern: \begin{comparisoncard}{Title}{Col1}{Col2}[optional-LOS]...
    pattern = r'\\begin\{comparisoncard\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}(?:\[([^\]]*)\])?(.*?)\\end\{comparisoncard\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1).strip()
        col1 = match.group(2).strip()
        col2 = match.group(3).strip()
        los_id = match.group(4)  # Optional LOS bracket
        body = match.group(5).strip()

        # Process \comprow commands into markdown table
        comprows = re.findall(r'\\comprow\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}', body)

        if comprows:
            # Build markdown table with custom column headers
            table_lines = [
                f"| Dimension | {col1} | {col2} |",
                "|-----------|--------|--------|"
            ]
            for dim, val1, val2 in comprows:
                dim_clean = clean_latex(dim.strip())
                val1_clean = clean_latex(val1.strip())
                val2_clean = clean_latex(val2.strip())
                table_lines.append(f"| {dim_clean} | {val1_clean} | {val2_clean} |")

            body = "\n".join(table_lines)
        else:
            body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="COMP",
            title=title,
            body=body,
            los_id=los_id,
            seen_ids=seen_ids
        )

        tags = ['type:comparison', 'type:compare_table']
        if los_id:
            tags.append(f'los:{los_id.strip().replace(" ", "_")}')

        cards.append({
            'type': 'comparison',
            'id': card_id,
            'front': f"Compare: {title}",
            'back': body,
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags,
        })

        # Bidirectional: generate reverse card (col2 vs col1)
        # Research: Kornell & Bjork (2008) — bidirectional comparison → 43% better transfer
        if comprows:
            reverse_table_lines = [
                f"| Dimension | {col2} | {col1} |",
                "|-----------|--------|--------|"
            ]
            for dim, val1, val2 in comprows:
                dim_clean = clean_latex(dim.strip())
                val1_clean = clean_latex(val1.strip())
                val2_clean = clean_latex(val2.strip())
                reverse_table_lines.append(f"| {dim_clean} | {val2_clean} | {val1_clean} |")

            reverse_body = "\n".join(reverse_table_lines)
            reverse_id = generate_card_id(
                volume=volume,
                chapter=chapter,
                card_type="COMP_REV",
                title=f"{title} (reverse)",
                body=reverse_body,
                los_id=los_id,
                seen_ids=seen_ids,
            )
            reverse_tags = ['type:comparison', 'type:compare_table', 'bidirectional']
            if los_id:
                reverse_tags.append(f'los:{los_id.strip().replace(" ", "_")}')

            cards.append({
                'type': 'comparison',
                'id': reverse_id,
                'front': f"Compare: {col2} vs {col1} ({title})",
                'back': reverse_body,
                'los_id': los_id.strip() if los_id else None,
                'source': source_file,
                'tags': reverse_tags,
            })

    return cards


def extract_comparisoncards3(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract 3-column comparison cards from LaTeX content.

    Pattern: \begin{comparisoncard3}{title}{col1}{col2}{col3}[LOS-ID]...\end{comparisoncard3}
    Card type: comparison3
    Front: "Compare: {title}"

    Handles \comprowiii{Dimension}{Val1}{Val2}{Val3} commands
    by converting them to a markdown table with custom headers.
    """
    cards = []
    # Pattern: \begin{comparisoncard3}{Title}{Col1}{Col2}{Col3}[optional-LOS]...
    pattern = r'\\begin\{comparisoncard3\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}(?:\[([^\]]*)\])?(.*?)\\end\{comparisoncard3\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1).strip()
        col1 = match.group(2).strip()
        col2 = match.group(3).strip()
        col3 = match.group(4).strip()
        los_id = match.group(5)  # Optional LOS bracket
        body = match.group(6).strip()

        # Process \comprowiii commands into markdown table
        comprows = re.findall(r'\\comprowiii\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}', body)

        if comprows:
            # Build markdown table with 3 custom column headers
            table_lines = [
                f"| Dimension | {col1} | {col2} | {col3} |",
                "|-----------|--------|--------|--------|"
            ]
            for dim, val1, val2, val3 in comprows:
                dim_clean = clean_latex(dim.strip())
                val1_clean = clean_latex(val1.strip())
                val2_clean = clean_latex(val2.strip())
                val3_clean = clean_latex(val3.strip())
                table_lines.append(f"| {dim_clean} | {val1_clean} | {val2_clean} | {val3_clean} |")

            body = "\n".join(table_lines)
        else:
            body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="COMP3",
            title=title,
            body=body,
            los_id=los_id,
            seen_ids=seen_ids
        )

        tags = ['type:comparison3', 'type:compare_table']
        if los_id:
            tags.append(f'los:{los_id.strip().replace(" ", "_")}')

        cards.append({
            'type': 'comparison3',
            'id': card_id,
            'front': f"Compare: {title}",
            'back': body,
            'los_id': los_id.strip() if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_starstories(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract STAR story framework cards from LaTeX content.

    Pattern: \begin{starstory}[title]...\end{starstory}
    Card type: starstory
    Front: "STAR Story: {title}"
    """
    cards = []
    pattern = r'\\begin\{starstory\}(?:\[([^\]]*)\])?(.*?)\\end\{starstory\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Behavioral Example"
        body = match.group(2).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="STAR",
            title=title,
            body=body,
            los_id=None,
            seen_ids=seen_ids
        )

        cards.append({
            'type': 'starstory',
            'id': card_id,
            'front': f"STAR Story: {title}",
            'back': truncate_at_sentence(body, 800),
            'source': source_file,
            'tags': ['type:starstory', 'type:behavioral', 'framework:star']
        })

    return cards


def extract_paradoxes(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract paradox/tension cards from LaTeX content.

    Pattern: \begin{paradox}[title]...\end{paradox}
    Card type: paradox
    Front: "Paradox: {title}"
    """
    cards = []
    pattern = r'\\begin\{paradox\}(?:\[([^\]]*)\])?(.*?)\\end\{paradox\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = match.group(1) or "Product Tension"
        body = match.group(2).strip()
        body = clean_latex(body)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="PARADOX",
            title=title,
            body=body,
            los_id=None,
            seen_ids=seen_ids
        )

        cards.append({
            'type': 'paradox',
            'id': card_id,
            'front': f"Paradox: {title}",
            'back': truncate_at_sentence(body, 600),
            'source': source_file,
            'tags': ['type:paradox', 'type:tension', 'product:tradeoff']
        })

    return cards


_GENERATEANSWER_RE = re.compile(r'\\generateanswer\s*\{')


def _strip_trailing_generateanswer(body: str) -> tuple[str, str | None]:
    r"""Split ``body`` into ``(prompt, answer_or_None)``.

    Mirrors ``_strip_trailing_checkpointanswer`` but for ``\generateanswer``
    inside a ``generatefirst`` environment. Uses balanced-brace scanning so
    multi-line answers with nested ``{...}`` (e.g. math) survive intact.
    """
    m = _GENERATEANSWER_RE.search(body)
    if not m:
        return body, None
    brace_open = m.end() - 1
    span = _extract_balanced_braces(body, brace_open)
    if span is None:
        return body, None
    start, end = span
    answer = body[start:end].strip()
    prompt = body[: m.start()].rstrip()
    return prompt, answer


def extract_generatefirst(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract generation-before-reading prompt cards.

    Pattern: \begin{generatefirst}[Optional Title]
               Question text...
               \generateanswer{Optional model answer — shown on Anki back,
                               invisible in PDF.}
             \end{generatefirst}

    Card type: generatefirst
    Research: Slamecka & Graf (1978) generation effect — generating an answer
    (even incorrectly) produces stronger memory traces than reading.

    If a trailing ``\generateanswer{...}`` is present, its content becomes the
    Anki back; otherwise the back falls back to the retrieval-hint placeholder.
    """
    cards = []
    pattern = r'\\begin\{generatefirst\}(?:\[([^\]]*)\])?(.*?)\\end\{generatefirst\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        title = (match.group(1) or "Predict Before Reading").strip()
        body = match.group(2).strip()
        prompt_raw, inline_answer = _strip_trailing_generateanswer(body)
        question = clean_latex(prompt_raw.strip())

        if not question or len(question) < 15:
            continue

        if inline_answer is not None:
            back = clean_latex(inline_answer)
        else:
            back = "(Answer from memory, then read the section to check.)"

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="GENERATE",
            title=title,
            body=question,
            los_id=None,
            seen_ids=seen_ids,
        )

        cards.append({
            'type': 'generatefirst',
            'id': card_id,
            'front': f"Before reading: {question}",
            'back': back,
            'los_id': None,
            'source': source_file,
            'tags': ['type:generatefirst', 'generation_effect'],
        })

    return cards


def _extract_balanced_braces(text: str, open_idx: int) -> tuple[int, int] | None:
    """Return ``(start, end)`` of the content inside braces beginning at ``open_idx``.

    ``open_idx`` must point at the opening ``{``. Returns ``None`` if unbalanced.
    The returned slice ``text[start:end]`` is the body; ``end`` is the index of
    the matching closing ``}``.
    """
    if open_idx >= len(text) or text[open_idx] != '{':
        return None
    depth = 1
    i = open_idx + 1
    start = i
    while i < len(text):
        ch = text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return start, i
        i += 1
    return None


_CHECKPOINTANSWER_RE = re.compile(r'\\checkpointanswer\s*\{')


def _strip_trailing_checkpointanswer(item_text: str) -> tuple[str, str | None]:
    r"""Split ``item_text`` into ``(question, answer_or_None)``.

    Looks for a trailing ``\checkpointanswer{...}`` with balanced braces. If
    present, returns the question (with the macro removed) and the answer body.
    Otherwise returns ``(item_text, None)``.
    """
    m = _CHECKPOINTANSWER_RE.search(item_text)
    if not m:
        return item_text, None
    brace_open = m.end() - 1
    span = _extract_balanced_braces(item_text, brace_open)
    if span is None:
        return item_text, None
    start, end = span
    answer = item_text[start:end].strip()
    question = item_text[: m.start()].rstrip()
    return question, answer


def _parse_item_list(body: str) -> tuple[list[str], list[str | None]]:
    r"""Return ``(item_bodies, los_brackets)`` parsed from an enumerate/itemize body.

    Nesting-aware: only ``\item`` markers at the OUTER list depth begin a new item;
    an ``\item`` inside a nested environment (e.g. a sub-list inside a checkpoint
    answer) stays part of its enclosing item. Tracks ``\begin{...}``/``\end{...}``
    depth to tell outer items from nested ones. For bodies with no nested
    environments this is identical to the previous flat regex parse — the only
    caller is ``extract_checkpoints``.
    """
    token_re = re.compile(r'\\begin\{[^}]*\}|\\end\{[^}]*\}|\\item(?![a-zA-Z])')
    recs: list[tuple[str, int, int, int]] = []  # (kind, start, end, depth_before)
    depth = 0
    for m in token_re.finditer(body):
        tok = m.group()
        if tok.startswith('\\begin'):
            recs.append(('begin', m.start(), m.end(), depth)); depth += 1
        elif tok.startswith('\\end'):
            recs.append(('end', m.start(), m.end(), depth)); depth -= 1
        else:  # \item
            recs.append(('item', m.start(), m.end(), depth))
    item_depths = [d for (k, _s, _e, d) in recs if k == 'item']
    if not item_depths:
        return [], []
    base = min(item_depths)
    tops = [(s, e) for (k, s, e, d) in recs if k == 'item' and d == base]
    first_start = tops[0][0]
    # The outer list closes at the first \end whose pre-decrement depth == base,
    # after the first top-level item. Content past it (a trailing \medskip, the
    # \rule before "Answers:") is not part of any item — mirrors the old lookahead
    # that stopped at the first \end{enumerate|itemize}.
    close = len(body)
    for (k, s, _e, d) in recs:
        if k == 'end' and d == base and s > first_start:
            close = s
            break
    items: list[str] = []
    los_brackets: list[str | None] = []
    for idx, (_ts, tend) in enumerate(tops):
        seg_end = tops[idx + 1][0] if idx + 1 < len(tops) else close
        seg = body[tend:min(seg_end, close)]
        # Mirror the old `\item\s*(?:[..]\s*)?` consumption: optional LOS bracket.
        lead = re.match(r'\s*(\[[^\]]*\])?\s*', seg)
        bracket = lead.group(1) if (lead and lead.group(1)) else None
        if lead:
            seg = seg[lead.end():]
        los_brackets.append(bracket)
        items.append(seg.strip())
    return items, los_brackets


def extract_checkpoints(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract checkpoint/self-check questions from tcolorbox environments.

    Two authoring patterns are supported, in priority order:

    1. **Inline per-item answer** — a trailing ``\checkpointanswer{A}`` macro
       following each ``\item Q`` body. Preferred for new content.
    2. **Paired Q/A enumerate blocks** — a question ``enumerate`` followed by
       ``\textbf{Answers:}`` and an answer ``enumerate`` (questions and
       answers paired positionally). Used by manning_llm_from_scratch.
    3. **Fallback placeholder** — when no answer is present, inject the
       legacy "Answer from memory, then verify" hint.

    Card type: checkpoint. Tags: retrieval_practice.

    Research basis: Roediger & Karpicke (2006) — single retrieval attempt
    produces 50% more long-term retention vs re-reading.
    """
    cards = []
    pattern = (
        r'(?:'
        r'\\begin\{tcolorbox\}\[checkpointbox.*?title\s*=\s*\{?([^}\]]+)\}?\](.*?)\\end\{tcolorbox\}'
        r'|'
        r'\\begin\{checkpointbox\}(.*?)\\end\{checkpointbox\}'
        r')'
    )

    for match in re.finditer(pattern, content, re.DOTALL):
        if match.group(1):
            title = match.group(1).strip().rstrip('}')
            body = match.group(2).strip()
        else:
            title = f"{chapter} Checkpoint"
            body = match.group(3).strip()

        # Split on "Answers:" marker if present; questions come from the first
        # half only, answers from the second half (pair by position).
        answers_split = re.split(
            r'\\textbf\s*\{\s*Answers?:\s*\}|\\paragraph\s*\{\s*Answers?:?\s*\}|\\subparagraph\s*\{\s*Answers?:?\s*\}',
            body,
            maxsplit=1,
        )
        question_body = answers_split[0]
        answer_body = answers_split[1] if len(answers_split) == 2 else None

        question_items, los_brackets = _parse_item_list(question_body)
        answer_items: list[str] = []
        if answer_body is not None:
            answer_items, _ = _parse_item_list(answer_body)

        for i, item_text in enumerate(question_items, 1):
            item_text = item_text.strip()
            question_raw, inline_answer = _strip_trailing_checkpointanswer(item_text)
            question = clean_latex(question_raw.strip())
            if not question or len(question) < 10:
                continue

            # Priority: inline \checkpointanswer > paired enumerate > placeholder
            if inline_answer:
                back = clean_latex(inline_answer)
            elif i - 1 < len(answer_items):
                paired = answer_items[i - 1].strip()
                paired = clean_latex(paired) if paired else ""
                back = paired or (
                    f"Self-check from: {title}\n\n"
                    "(Answer from memory, then verify against the chapter text.)"
                )
            else:
                back = (
                    f"Self-check from: {title}\n\n"
                    "(Answer from memory, then verify against the chapter text.)"
                )

            los_id = None
            if i - 1 < len(los_brackets):
                bracket_content = los_brackets[i - 1]
                if bracket_content:
                    los_match = re.match(r'\[([A-Z0-9]+-[\d.]+)\]', bracket_content)
                    if los_match:
                        los_id = los_match.group(1)
            if not los_id:
                hfill_match = re.search(r'\\hfill\\textit\{[^}]*?([A-Z0-9]+-[\d.]+)', item_text)
                if hfill_match:
                    los_id = hfill_match.group(1)

            card_id = generate_card_id(
                volume=volume,
                chapter=chapter,
                card_type="CHECKPOINT",
                title=f"{title} Q{i}",
                body=question,
                los_id=los_id,
                seen_ids=seen_ids,
            )

            tags = ['type:checkpoint', 'retrieval_practice']
            if los_id:
                tags.append(f'los:{los_id}')

            cards.append({
                'type': 'checkpoint',
                'id': card_id,
                'front': question,
                'back': back,
                'los_id': los_id,
                'source': source_file,
                'tags': tags,
            })

    return cards


def extract_orderings(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract ordering (put-in-order) questions from LaTeX content.

    Pattern: \begin{ordering}[LOS-ID]
             prompt text
             \orderstep{step1}
             \orderstep{step2}
             \begin{solution}...\end{solution}
             \end{ordering}

    Solution block is INSIDE the environment.
    Only extracts orderings that have a solution block.
    """
    cards = []

    # Match entire ordering environment including optional [LOS-ID]
    env_pattern = r'\\begin\{ordering\}(?:\[([^\]]*)\])?(.*?)\\end\{ordering\}'

    for match in re.finditer(env_pattern, content, re.DOTALL):
        los_id = (match.group(1) or "").strip()
        body = match.group(2).strip()

        # Extract solution from inside the environment
        sol_match = re.search(r'\\begin\{solution\}(.*?)\\end\{solution\}', body, re.DOTALL)
        if not sol_match:
            continue
        solution_text = sol_match.group(1).strip()

        # Remove solution block from body to get prompt + steps
        body_no_sol = body[:sol_match.start()].strip()

        # Extract individual ordersteps
        step_pattern = r'\\orderstep\{([^}]+)\}'
        steps = [m.group(1).strip() for m in re.finditer(step_pattern, body_no_sol)]
        if not steps:
            continue

        # Prompt text is everything before the first \orderstep
        first_step_pos = re.search(r'\\orderstep\{', body_no_sol)
        prompt = body_no_sol[:first_step_pos.start()].strip() if first_step_pos else ""
        prompt_clean = clean_latex(prompt) if prompt else "Put these in the correct order:"

        # Build front: prompt + shuffled steps (as-written order IS the shuffled order)
        steps_clean = [clean_latex(s) for s in steps]
        front_lines = [prompt_clean, ""] + [f"- {s}" for s in steps_clean]
        front = "\n".join(front_lines)

        # Build back from solution
        back = clean_latex(solution_text)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="ORDERING",
            title="",
            body=front,
            los_id=los_id,
            seen_ids=seen_ids
        )

        tags = ['type:ordering']
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        cards.append({
            'type': 'ordering',
            'id': card_id,
            'front': truncate_at_sentence(front, 800),
            'back': truncate_at_sentence(back, 1000),
            'los_id': los_id if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def extract_matchings(content: str, source_file: str, volume: str, chapter: str, seen_ids: set) -> list[dict[str, Any]]:
    r"""Extract matching (map items to categories) questions from LaTeX content.

    Pattern: \begin{matching}[LOS-ID]
             prompt text
             \matchpair{item}{category}
             \matchpair{item}{category}
             \begin{solution}...\end{solution}
             \end{matching}

    Solution block is INSIDE the environment.
    Only extracts matchings that have a solution block.
    """
    cards = []

    env_pattern = r'\\begin\{matching\}(?:\[([^\]]*)\])?(.*?)\\end\{matching\}'

    for match in re.finditer(env_pattern, content, re.DOTALL):
        los_id = (match.group(1) or "").strip()
        body = match.group(2).strip()

        # Extract solution from inside the environment
        sol_match = re.search(r'\\begin\{solution\}(.*?)\\end\{solution\}', body, re.DOTALL)
        if not sol_match:
            continue
        solution_text = sol_match.group(1).strip()

        # Remove solution block from body to get prompt + pairs
        body_no_sol = body[:sol_match.start()].strip()

        # Extract matchpairs
        pair_pattern = r'\\matchpair\{([^}]+)\}\{([^}]+)\}'
        pairs = [(m.group(1).strip(), m.group(2).strip())
                 for m in re.finditer(pair_pattern, body_no_sol)]
        if not pairs:
            continue

        # Prompt text is everything before the first \matchpair
        first_pair_pos = re.search(r'\\matchpair\{', body_no_sol)
        prompt = body_no_sol[:first_pair_pos.start()].strip() if first_pair_pos else ""
        prompt_clean = clean_latex(prompt) if prompt else "Match each item to its category:"

        # Build front: prompt + items with their targets
        items_clean = [(clean_latex(item), clean_latex(cat)) for item, cat in pairs]
        front_lines = [prompt_clean, ""]
        for item, cat in items_clean:
            front_lines.append(f"- {item} -> ???")
        front_lines.append("")
        front_lines.append("**Categories:** " + " | ".join(cat for _, cat in items_clean))
        front = "\n".join(front_lines)

        # Build back from solution
        back = clean_latex(solution_text)

        card_id = generate_card_id(
            volume=volume,
            chapter=chapter,
            card_type="MATCHING",
            title="",
            body=front,
            los_id=los_id,
            seen_ids=seen_ids
        )

        tags = ['type:matching']
        if los_id:
            for single_los in los_id.split(','):
                single_los = single_los.strip()
                if single_los:
                    tags.append(f'los:{single_los.replace(" ", "_")}')

        cards.append({
            'type': 'matching',
            'id': card_id,
            'front': truncate_at_sentence(front, 800),
            'back': truncate_at_sentence(back, 1000),
            'los_id': los_id if los_id else None,
            'source': source_file,
            'tags': tags
        })

    return cards


def deduplicate_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate cards within a volume (keep first occurrence)."""
    seen_ids = set()
    unique_cards = []
    duplicates_removed = 0

    for card in cards:
        card_id = card.get('id', '')
        if card_id not in seen_ids:
            seen_ids.add(card_id)
            unique_cards.append(card)
        else:
            duplicates_removed += 1

    if duplicates_removed > 0:
        print(f"  Removed {duplicates_removed} duplicate cards", file=sys.stderr)

    return unique_cards


def process_file(filepath: Path, seen_ids: set) -> dict[str, Any]:
    """Process a single LaTeX file and extract all card types.

    Args:
        filepath: Path to LaTeX file
        seen_ids: Set of already-used card IDs (for collision detection across files)
    """
    content = filepath.read_text(encoding='utf-8')

    # Strip LaTeX comments before regex extraction so that scaffold-template
    # examples (e.g. ``% \term[DFS-G]{Term Name}{Definition}``) inside
    # ``C_glossary.tex`` placeholders are not extracted as real cards.
    # Protect escaped ``\%`` first so percentages survive intact.
    content = content.replace(r'\%', '\x00PERCENT\x00')
    content = re.sub(r'(?m)^\s*%.*$', '', content)
    content = content.replace('\x00PERCENT\x00', r'\%')

    # Extract volume and chapter from filepath
    volume, chapter = extract_volume_chapter(filepath)

    # Source includes volume prefix for clarity (e.g., "vol1/04_sample_size.tex")
    source = f"{volume}/{filepath.name}"

    cards = []
    cards.extend(extract_terms(content, source, volume, chapter, seen_ids))
    cards.extend(extract_redflags(content, source, volume, chapter, seen_ids))
    cards.extend(extract_problems(content, source, volume, chapter, seen_ids))
    cards.extend(extract_vignettes(content, source, volume, chapter, seen_ids))
    cards.extend(extract_interview_contexts(content, source, volume, chapter, seen_ids))

    # Vol 0 Quick Reference environments (also useful in cheat sheets)
    cards.extend(extract_formulacards(content, source, volume, chapter, seen_ids))
    # Math-reference environments: definition/proposition/theorem
    cards.extend(extract_mathdefs(content, source, volume, chapter, seen_ids))
    cards.extend(extract_propositions(content, source, volume, chapter, seen_ids))
    cards.extend(extract_theorems(content, source, volume, chapter, seen_ids))
    cards.extend(extract_sixtysec(content, source, volume, chapter, seen_ids))
    cards.extend(extract_keyconcepts(content, source, volume, chapter, seen_ids))
    cards.extend(extract_pitfalls(content, source, volume, chapter, seen_ids))
    cards.extend(extract_decisiontrees(content, source, volume, chapter, seen_ids))
    cards.extend(extract_interviewtips(content, source, volume, chapter, seen_ids))

    # Drill environments (speed drill Q&A)
    cards.extend(extract_drills(content, source, volume, chapter, seen_ids))

    # Actuarial bridge environments (SOA-to-DS mappings)
    cards.extend(extract_actuarialbridges(content, source, volume, chapter, seen_ids))

    # Vol_meta_tech_screen specific environments
    cards.extend(extract_clozeterms(content, source, volume, chapter, seen_ids))
    cards.extend(extract_termbi(content, source, volume, chapter, seen_ids))
    cards.extend(extract_levelcards(content, source, volume, chapter, seen_ids))
    cards.extend(extract_comparisoncards(content, source, volume, chapter, seen_ids))
    cards.extend(extract_comparisoncards3(content, source, volume, chapter, seen_ids))
    cards.extend(extract_starstories(content, source, volume, chapter, seen_ids))
    cards.extend(extract_paradoxes(content, source, volume, chapter, seen_ids))

    # Generation-before-reading prompts (generation effect)
    cards.extend(extract_generatefirst(content, source, volume, chapter, seen_ids))

    # Checkpoint / self-check questions (retrieval practice)
    cards.extend(extract_checkpoints(content, source, volume, chapter, seen_ids))

    # Cert-prep environments (ordering, matching)
    cards.extend(extract_orderings(content, source, volume, chapter, seen_ids))
    cards.extend(extract_matchings(content, source, volume, chapter, seen_ids))

    # Get company tags for this file
    company_tags = extract_company_tags(content)

    # Add company tags, actuarial notes, scaffolding level, and check quality
    for card in cards:
        card['company_tags'] = company_tags
        card['tags'].extend([f'company:{tag}' for tag in company_tags])
        check_generic_front(card)  # Warn on generic fronts

        # Default scaffolding_level from card type (honors pre-existing overrides)
        apply_scaffolding_level(card)

        # Add actuarial embedded note if matching mapping exists
        # (skip actuarialbridge cards - they're already actuarial content)
        if card.get('type') != 'actuarialbridge':
            add_actuarial_note_to_card(card, volume)

    return {
        'source': str(filepath),
        'volume': volume,
        'chapter': chapter,
        'cards': cards,
        'company_tags': company_tags
    }


def _resolve_tikz_setting(cli_choice: str, output_dir: Path) -> bool:
    """Resolve the --render-tikz CLI choice to True/False.

    "on"/"off" are explicit. "auto" reads `guide_qa.yaml.cards.render_tikz`
    from the guide's root directory (two levels up from `cards/`). Absent
    file or absent key -> False (backward compat for all existing guides).
    """
    if cli_choice == 'on':
        return True
    if cli_choice == 'off':
        return False
    # auto: look for guide_qa.yaml at <guide>/guide_qa.yaml
    # output_dir is typically <guide>/notes/notebook/cards, so the guide dir
    # is three levels up.
    guide_root = output_dir.resolve()
    for _ in range(4):
        candidate = guide_root / 'guide_qa.yaml'
        if candidate.exists():
            try:
                with open(candidate, encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                return bool((data.get('cards') or {}).get('render_tikz', False))
            except Exception:
                return False
        if guide_root.parent == guide_root:
            break
        guide_root = guide_root.parent
    return False


def main():
    parser = argparse.ArgumentParser(
        description='Extract card definitions from LaTeX chapters'
    )
    parser.add_argument(
        'files',
        nargs='+',
        help='LaTeX files to process (glob patterns supported)'
    )
    parser.add_argument(
        '-o', '--output',
        required=True,
        help='Output directory for YAML files'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed extraction info'
    )
    parser.add_argument(
        '--guide-slug',
        help='Guide identifier for cross-guide ID uniqueness. '
             'Auto-detected from output path if not provided '
             '(e.g., manning_rlhf_book/notes/... -> manning_rlhf_book)'
    )
    parser.add_argument(
        '--render-tikz',
        choices=['auto', 'on', 'off'],
        default='auto',
        help='Render tikzpicture blocks in card content to PNGs. '
             '"auto" (default) reads guide_qa.yaml.cards.render_tikz '
             '(off if absent). "on"/"off" force the behavior.'
    )

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Configure TikZ rendering (opt-in per guide) ------------------------
    # `render_tikz: true` in the guide's guide_qa.yaml enables; everything else
    # uses the placeholder fallback (current fleet-wide behavior).
    tikz_enabled = _resolve_tikz_setting(args.render_tikz, output_dir)
    if tikz_enabled:
        figures_dir = output_dir / 'figures'
        configure_tikz_rendering(enabled=True, output_dir=figures_dir)
        if args.verbose:
            print(f"TikZ rendering: ENABLED (figures -> {figures_dir})")
    else:
        configure_tikz_rendering(enabled=False)

    # Set module-level guide slug for ID generation
    global _guide_slug_default
    if args.guide_slug:
        _guide_slug_default = args.guide_slug
    else:
        # Auto-detect from first input file path:
        # manning_rlhf_book/notes/notebook/chapters/01_*.tex -> manning_rlhf_book
        first_file = args.files[0]
        # Resolve globs to get actual path
        if '*' in first_file:
            matches = list(Path('.').glob(first_file))
            first_file = str(matches[0]) if matches else first_file
        input_parts = Path(first_file).parts
        if input_parts:
            candidate = input_parts[0]
            # Skip if not a real guide directory
            if candidate not in ('.', '..', 'shared', 'scripts', 'output', '/', 'cards'):
                _guide_slug_default = candidate
    if args.verbose and _guide_slug_default:
        print(f"Guide slug: {_guide_slug_default}")

    all_cards = []
    total_terms = 0
    total_redflags = 0
    total_problems = 0
    total_vignettes = 0
    total_interviews = 0
    total_actuarial_notes = 0  # Cards with embedded actuarial notes

    # Track seen IDs across all files for collision detection
    seen_ids: set[str] = set()

    for file_pattern in args.files:
        for filepath in Path('.').glob(file_pattern) if '*' in file_pattern else [Path(file_pattern)]:
            if not filepath.exists():
                print(f"Warning: File not found: {filepath}", file=sys.stderr)
                continue

            if args.verbose:
                print(f"Processing: {filepath}")

            result = process_file(filepath, seen_ids)

            if result['cards']:
                # Compute output file path for los_id preservation
                output_file = output_dir / f"{filepath.stem}_cards.yml"

                # Preserve existing los_id values from previous extraction
                # This prevents los_id assigned via fix_vol*.py from being lost
                # IMPORTANT: Must happen BEFORE adding to all_cards for consistency
                existing_los_ids = load_existing_los_ids(output_file)
                los_preserved_count = 0
                for card in result['cards']:
                    if not card.get('los_id') and card['id'] in existing_los_ids:
                        card['los_id'] = existing_los_ids[card['id']]
                        los_preserved_count += 1
                        # Also update tags to include the preserved los_id
                        los_tag = f"los:{card['los_id'].replace(' ', '_')}"
                        if los_tag not in card.get('tags', []):
                            card['tags'].append(los_tag)

                if args.verbose and los_preserved_count > 0:
                    print(f"  Preserved {los_preserved_count} existing los_id values")

                # Populate `figures:` from rendered <img src="..."> tags, if any.
                # Only sets the key when figures exist → backward-compat: cards
                # without TikZ produce byte-identical YAML.
                if tikz_enabled:
                    for card in result['cards']:
                        back = card.get('back', '')
                        if back:
                            figs = extract_figures_from_back(back)
                            if figs:
                                card['figures'] = figs

                # Now add to combined list (with preserved los_id)
                all_cards.extend(result['cards'])

                # Count by type
                for card in result['cards']:
                    if card['type'] == 'term':
                        total_terms += 1
                    elif card['type'] == 'redflag':
                        total_redflags += 1
                    elif card['type'] == 'problem':
                        total_problems += 1
                    elif card['type'] == 'vignette':
                        total_vignettes += 1
                    elif card['type'] == 'interview':
                        total_interviews += 1
                    # Count cards with actuarial notes
                    if card.get('actuarial_mapping'):
                        total_actuarial_notes += 1

                # Write per-file YAML
                with open(output_file, 'w', encoding='utf-8') as f:
                    yaml.dump(result, f, Dumper=CardDumper, default_flow_style=False, allow_unicode=True, width=1000)

                if args.verbose:
                    print(f"  Extracted: {len(result['cards'])} cards")

    # Deduplicate cards within volume
    original_count = len(all_cards)
    all_cards = deduplicate_cards(all_cards)
    dedup_count = original_count - len(all_cards)

    # Count all card types dynamically (including Vol 0 types)
    type_counts: dict[str, int] = {}
    for card in all_cards:
        card_type = card['type']
        type_counts[card_type] = type_counts.get(card_type, 0) + 1

    # Write combined YAML
    combined_file = output_dir / "all_cards.yml"
    with open(combined_file, 'w', encoding='utf-8') as f:
        yaml.dump({
            'total': len(all_cards),
            'by_type': type_counts,
            'cards': all_cards
        }, f, Dumper=CardDumper, default_flow_style=False, allow_unicode=True, width=1000)

    print(f"Extracted {len(all_cards)} cards total:")
    for card_type, count in sorted(type_counts.items()):
        print(f"  - {card_type}: {count}")
    if dedup_count > 0:
        print(f"  - Duplicates removed: {dedup_count}")
    if total_actuarial_notes > 0:
        print(f"  📊 Actuarial notes embedded: {total_actuarial_notes}")
    print(f"Output: {combined_file}")

    # Report quality warnings
    has_warnings = False
    if _id_collision_warnings:
        has_warnings = True
        print(f"\n⚠️  ID Collisions ({len(_id_collision_warnings)}):", file=sys.stderr)
        for warning in _id_collision_warnings[:10]:
            print(f"  {warning}", file=sys.stderr)
        if len(_id_collision_warnings) > 10:
            print(f"  ... and {len(_id_collision_warnings) - 10} more", file=sys.stderr)

    if _generic_front_warnings:
        has_warnings = True
        print(f"\n⚠️  Generic Fronts ({len(_generic_front_warnings)}):", file=sys.stderr)
        for warning in _generic_front_warnings[:10]:
            print(f"  {warning}", file=sys.stderr)
        if len(_generic_front_warnings) > 10:
            print(f"  ... and {len(_generic_front_warnings) - 10} more", file=sys.stderr)
        print("\nRun: python scripts/fix_generic_fronts.py --apply", file=sys.stderr)

    if has_warnings:
        print("\n⚠️  Quality issues found. Review warnings above.", file=sys.stderr)


if __name__ == '__main__':
    main()
