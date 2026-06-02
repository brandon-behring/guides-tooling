#!/usr/bin/env python3
"""Combine per-chapter YAML card files into all_cards.yml.

Safe recombination utility: reads existing *_cards.yml files and writes
a combined all_cards.yml WITHOUT re-extracting from LaTeX. This preserves
any manual presentation fixes applied to the YAML files.

Usage:
    python shared/cards/combine_all_cards.py dlai_advanced_rag/notes/notebook/cards/
    python shared/cards/combine_all_cards.py dlai_advanced_rag/notes/notebook/cards/ --dry-run
    python shared/cards/combine_all_cards.py --all  # All guides
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

from tooling import paths


# ---------------------------------------------------------------------------
# YAML dumper (mirrors extract_cards.py CardDumper for round-trip fidelity)
# ---------------------------------------------------------------------------

class CardDumper(yaml.SafeDumper):
    """YAML dumper that uses literal block style for multi-line strings."""
    pass


def _str_representer(dumper: yaml.Dumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


CardDumper.add_representer(str, _str_representer)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

EXCLUDE_FILES = {"all_cards.yml"}


def find_card_files(cards_dir: Path) -> list[Path]:
    """Find per-chapter YAML files, excluding the combined output file."""
    files = sorted(cards_dir.glob("*_cards.yml"))
    return [f for f in files if f.name not in EXCLUDE_FILES]


def load_cards(path: Path) -> list[dict]:
    """Load cards list from a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    if isinstance(data, dict) and "cards" in data:
        return data["cards"] or []
    if isinstance(data, list):
        return data
    return []


def combine(cards_dir: Path, dry_run: bool = False) -> int:
    """Combine per-chapter card files into all_cards.yml.

    Args:
        cards_dir: Directory containing *_cards.yml files.
        dry_run: If True, print summary without writing.

    Returns:
        Total number of cards combined.
    """
    if not cards_dir.is_dir():
        print(f"Error: {cards_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    card_files = find_card_files(cards_dir)
    if not card_files:
        print(f"Error: No *_cards.yml files found in {cards_dir}", file=sys.stderr)
        sys.exit(1)

    all_cards: list[dict] = []
    type_counts: Counter = Counter()

    for path in card_files:
        cards = load_cards(path)
        for card in cards:
            card_type = card.get("type", "unknown")
            type_counts[card_type] += 1
        all_cards.extend(cards)
        print(f"  {path.name}: {len(cards)} cards")

    output_path = cards_dir / "all_cards.yml"

    if dry_run:
        print(
            f"\n[DRY RUN] Would write {len(all_cards)} cards from "
            f"{len(card_files)} files -> {output_path}"
        )
    else:
        result = {
            "total": len(all_cards),
            "by_type": dict(sorted(type_counts.items())),
            "cards": all_cards,
        }
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(
                result, f, Dumper=CardDumper,
                default_flow_style=False, allow_unicode=True, width=1000,
            )
        print(
            f"\nCombined {len(all_cards)} cards from "
            f"{len(card_files)} files -> {output_path}"
        )

    # Summary by type
    print("\nBy type:")
    for card_type, count in sorted(type_counts.items()):
        print(f"  {card_type}: {count}")

    return len(all_cards)


def find_all_card_dirs() -> list[Path]:
    """Discover all card directories across guides (guide/ layout)."""
    dirs: list[Path] = []
    for cards_dir in sorted(paths.host_root().glob("*/guide/cards")):
        if find_card_files(cards_dir):
            dirs.append(cards_dir)
    return sorted(dirs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Combine per-chapter YAML card files into all_cards.yml",
    )
    parser.add_argument(
        "cards_dir", nargs="?", type=Path, default=None,
        help="Directory containing *_cards.yml files",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Process all guides with card files",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print summary without writing all_cards.yml",
    )
    args = parser.parse_args()

    if args.all:
        card_dirs = find_all_card_dirs()
        if not card_dirs:
            print("No card directories found.", file=sys.stderr)
            sys.exit(1)
        total = 0
        for cards_dir in card_dirs:
            guide_name = cards_dir.parts[-4]
            print(f"\n--- {guide_name} ---")
            total += combine(cards_dir, dry_run=args.dry_run)
        print(f"\n{'=' * 40}")
        print(f"Total across all guides: {total} cards")
    elif args.cards_dir:
        combine(args.cards_dir, dry_run=args.dry_run)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
