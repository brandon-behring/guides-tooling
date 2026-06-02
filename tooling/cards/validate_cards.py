#!/usr/bin/env python3
"""Validate Anki cards across course learning guides.

Checks:
  1. No duplicate card IDs across guides
  2. Required YAML fields present (id, front, back, type)
  3. Basic structural validation
  4. Render fidelity: LaTeX math delimiter balance, \\begin/\\end pairing,
     unescaped < and > characters outside math regions

Audit-only — does not modify any files.

Usage:
    python shared/cards/validate_cards.py
    python shared/cards/validate_cards.py --verbose
    python shared/cards/validate_cards.py --guide dlai_advanced_rag
    python shared/cards/validate_cards.py --render-only
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from tooling import paths

# Required fields every card must have
REQUIRED_FIELDS = {"id", "front", "back", "type"}

# Regex patterns for math regions (used by validate_render_fidelity)
MATH_PAREN_RE = re.compile(r"\\\((.*?)\\\)", re.DOTALL)
MATH_BRACKET_RE = re.compile(r"\\\[(.*?)\\\]", re.DOTALL)
MATH_INLINE_DOLLAR_RE = re.compile(r"(?<!\\)\$([^$\n]+?)\$")
MATH_DISPLAY_DOLLAR_RE = re.compile(r"(?<!\\)\$\$(.*?)\$\$", re.DOTALL)
# Code regions: ```...``` fenced blocks and `inline` backticks
CODE_FENCE_RE = re.compile(r"```[a-zA-Z]*\n.*?\n\s*```", re.DOTALL)
CODE_INLINE_RE = re.compile(r"`[^`]+?`", re.DOTALL)
BEGIN_RE = re.compile(r"\\begin\{([a-zA-Z*]+)\}")
END_RE = re.compile(r"\\end\{([a-zA-Z*]+)\}")
HTML_ESCAPE_LEAKAGE_RE = re.compile(r"&(amp|lt|gt|quot|#\d+);")


def _strip_protected_regions(text: str) -> str:
    """Remove math + code regions so remaining text can be checked for stray
    HTML-unsafe characters. Replaces each region with whitespace of equal
    length to preserve column offsets in error messages. Math regions are
    rendered by MathJax in Anki; code regions (fenced or inline backticks)
    are rendered inside ``<code>`` tags and preserve ``<``/``>`` literally.
    """
    for pattern in (
        CODE_FENCE_RE,
        CODE_INLINE_RE,
        MATH_DISPLAY_DOLLAR_RE,
        MATH_BRACKET_RE,
        MATH_PAREN_RE,
        MATH_INLINE_DOLLAR_RE,
    ):
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def validate_render_fidelity(card: dict[str, Any], filepath: Path) -> list[str]:
    """Check a card for issues that prevent correct rendering in Anki.

    Validates LaTeX math delimiter balance, ``\\begin``/``\\end`` pairing,
    unescaped ``<``/``>`` outside math regions (which genanki HTML-escapes
    silently), and HTML escape leakage (e.g., ``&amp;``).

    Parameters
    ----------
    card : dict
        Single card dictionary loaded from YAML.
    filepath : Path
        Path to the source YAML file (for error context).

    Returns
    -------
    list of str
        Diagnostic messages, one per issue. Empty list when card is clean.
    """
    issues: list[str] = []
    card_id = card.get("id", "<no-id>")

    for field_name in ("front", "back"):
        text = card.get(field_name, "")
        if not isinstance(text, str) or not text:
            continue

        # 1. Math delimiter balance (\( \) and \[ \])
        n_open_paren = len(re.findall(r"\\\(", text))
        n_close_paren = len(re.findall(r"\\\)", text))
        if n_open_paren != n_close_paren:
            issues.append(
                f"{filepath} [{card_id}] {field_name}: math \\( count "
                f"({n_open_paren}) != \\) count ({n_close_paren})"
            )

        n_open_brack = len(re.findall(r"\\\[", text))
        n_close_brack = len(re.findall(r"\\\]", text))
        if n_open_brack != n_close_brack:
            issues.append(
                f"{filepath} [{card_id}] {field_name}: math \\[ count "
                f"({n_open_brack}) != \\] count ({n_close_brack})"
            )

        # 2. \begin / \end environment balance
        begin_envs = sorted(BEGIN_RE.findall(text))
        end_envs = sorted(END_RE.findall(text))
        if begin_envs != end_envs:
            issues.append(
                f"{filepath} [{card_id}] {field_name}: \\begin/\\end mismatch "
                f"begin={begin_envs} end={end_envs}"
            )

        # 3. Stray < and > outside math + code regions (genanki HTML-escapes silently)
        non_math = _strip_protected_regions(text)
        for m in re.finditer(r"<[^/!a-zA-Z\s]|<\s|<$", non_math):
            issues.append(
                f"{filepath} [{card_id}] {field_name}: stray '<' outside math "
                f"at pos {m.start()} (genanki may HTML-escape silently)"
            )
            break  # one report per field is enough
        for m in re.finditer(r"(?<![a-zA-Z/])>(?![a-zA-Z/])", non_math):
            issues.append(
                f"{filepath} [{card_id}] {field_name}: stray '>' outside math "
                f"at pos {m.start()} (genanki may HTML-escape silently)"
            )
            break

        # 4. HTML escape leakage (&amp; &lt; etc. visible to reader)
        leaks = HTML_ESCAPE_LEAKAGE_RE.findall(text)
        if leaks:
            issues.append(
                f"{filepath} [{card_id}] {field_name}: HTML escape leakage "
                f"({len(leaks)} occurrences: {sorted(set(leaks))[:3]})"
            )

    return issues

# Known card types (warnings for unknown, not errors)
KNOWN_TYPES = {
    "term", "problem", "vignette", "redflag", "keyconcept", "formula",
    "drill", "decisiontree", "interview", "interviewcontext", "cloze",
    "comparison", "pitfall", "interviewtip",
}


def load_yaml_cards(filepath: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load cards from a YAML file.

    Returns:
        Tuple of (cards_list, error_message_or_None).
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data is None:
                return [], None
            if isinstance(data, list):
                return data, None
            if isinstance(data, dict) and "cards" in data:
                return data["cards"] or [], None
            return [], None
    except Exception as e:
        return [], str(e)


def find_card_files(guide: str | None = None) -> list[Path]:
    """Discover all card YAML files across course guides.

    Args:
        guide: Optional guide directory name to filter to.

    Returns:
        Sorted list of card YAML file paths.
    """
    base = guide if guide else "*"
    files: list[Path] = []
    files.extend(paths.host_root().glob(f"{base}/guide/cards/*_cards.yml"))

    # If a directory has per-chapter files, use those; otherwise use all_cards.yml
    by_dir: dict[Path, list[Path]] = {}
    for f in files:
        by_dir.setdefault(f.parent, []).append(f)

    result: list[Path] = []
    for dir_path, dir_files in by_dir.items():
        non_all = [f for f in dir_files if f.name != "all_cards.yml"]
        if non_all:
            result.extend(non_all)
        else:
            all_file = dir_path / "all_cards.yml"
            if all_file in dir_files:
                result.append(all_file)

    return sorted(set(result))


def validate_card_fields(card: dict[str, Any], filepath: Path) -> list[str]:
    """Validate required fields on a single card.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    card_id = card.get("id", "<no-id>")

    for field in REQUIRED_FIELDS:
        # Cloze cards use 'front' as the cloze text; 'back' is not required
        if field == "back" and card.get("type") == "cloze":
            continue
        if field not in card or not card[field]:
            errors.append(f"{filepath} [{card_id}]: missing required field '{field}'")

    # Warn on unknown types
    card_type = card.get("type", "")
    if card_type and card_type not in KNOWN_TYPES:
        # Downgrade to warning-level (not blocking)
        pass

    return errors


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate Anki cards across course guides")
    parser.add_argument("--verbose", action="store_true", help="Show per-file details")
    parser.add_argument("--guide", type=str, default=None, help="Validate a single guide")
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Skip structural checks; only run render-fidelity scan",
    )
    parser.add_argument(
        "--by-guide",
        action="store_true",
        help="Print per-guide render-fidelity issue counts (descending)",
    )
    args = parser.parse_args()

    card_files = find_card_files(args.guide)
    if not card_files:
        print("No card files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Validating {len(card_files)} card files...")

    errors: list[str] = []
    warnings: list[str] = []
    render_issues: list[str] = []
    card_ids: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    total_cards = 0
    parse_errors = 0

    for filepath in card_files:
        guide_name = filepath.parts[-5] if len(filepath.parts) >= 5 else "unknown"
        cards, parse_err = load_yaml_cards(filepath)

        if parse_err is not None:
            parse_errors += 1
            errors.append(f"{filepath}: YAML parse error: {parse_err}")
            continue

        for card in cards:
            total_cards += 1
            card_id = card.get("id", "")

            # Track for duplicate detection
            if card_id:
                card_ids[card_id].append((filepath, guide_name))

            # Field validation (skip when --render-only)
            if not args.render_only:
                errors.extend(validate_card_fields(card, filepath))

            # Render fidelity check (always — it's the main quality signal)
            render_issues.extend(validate_render_fidelity(card, filepath))

    # Duplicate detection
    duplicates_within_guide = 0
    duplicates_across_guides = 0

    for card_id, locations in card_ids.items():
        if len(locations) > 1:
            guides = set(loc[1] for loc in locations)
            if len(guides) == 1:
                duplicates_within_guide += 1
                warnings.append(f"Duplicate ID within guide: {card_id} ({guides.pop()})")
            else:
                duplicates_across_guides += 1
                # Cross-guide duplicates are errors (IDs should be globally unique)
                errors.append(
                    f"Duplicate ID across guides: {card_id} "
                    f"({', '.join(sorted(guides))})"
                )

    # Report
    print(f"\n{'=' * 60}")
    print("Card Validation Results")
    print(f"{'=' * 60}")
    print(f"Total card files: {len(card_files)}")
    print(f"Total cards: {total_cards}")
    print(f"Unique card IDs: {len(card_ids)}")

    if duplicates_within_guide > 0:
        print(f"Within-guide duplicates: {duplicates_within_guide} (should fix)")
    if duplicates_across_guides > 0:
        print(f"Cross-guide duplicates: {duplicates_across_guides} (ERROR)")

    if warnings:
        print(f"\n{len(warnings)} Warnings:")
        for w in warnings[:10]:
            print(f"  {w}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more")

    if parse_errors > 0:
        print(f"\n{parse_errors} YAML parse errors detected")

    if render_issues:
        print(f"\n{len(render_issues)} RENDER FIDELITY ISSUES:")
        if args.by_guide:
            # Tally issues per guide and emit a sorted summary
            per_guide_count: dict[str, int] = defaultdict(int)
            for issue in render_issues:
                # Each issue line begins with "<root>/<guide_slug>/guide/cards/...";
                # extract the guide_slug segment.
                guide_slug = "unknown"
                if "/guide/" in issue:
                    guide_slug = issue.split("/guide/", 1)[0].rsplit("/", 1)[-1]
                per_guide_count[guide_slug] += 1
            for guide_slug, count in sorted(
                per_guide_count.items(), key=lambda kv: (-kv[1], kv[0])
            ):
                print(f"  {guide_slug}: {count}")
        else:
            for issue in render_issues[:30]:
                print(f"  {issue}")
            if len(render_issues) > 30:
                print(f"  ... and {len(render_issues) - 30} more")

    if errors:
        print(f"\n{len(errors)} ERRORS:")
        for e in errors[:20]:
            print(f"  {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
        sys.exit(1)
    if render_issues:
        # Render issues are blocking too — they cause silent rendering bugs
        sys.exit(1)
    print("\nAll validations passed!")
    sys.exit(0)


if __name__ == "__main__":
    main()
