#!/usr/bin/env python3
"""
Check for duplicate card IDs across all volumes.

Detects:
- Exact ID collisions (same ID, potentially different content)
- Near-duplicate IDs (IDs that are too similar)

Usage:
    python check_duplicates.py vol*/cards/all_cards.yml
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml


def load_cards(filepath: Path) -> list[dict]:
    """Load cards from a YAML file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if isinstance(data, dict) and 'cards' in data:
        return data['cards']
    elif isinstance(data, list):
        return data
    return []


def check_id_collisions(all_cards: list[tuple[str, dict]]) -> list[str]:
    """Check for exact ID collisions across all cards."""
    id_to_sources = defaultdict(list)

    for source_file, card in all_cards:
        card_id = card.get('id', '')
        if card_id:
            id_to_sources[card_id].append((source_file, card))

    errors = []
    for card_id, occurrences in id_to_sources.items():
        if len(occurrences) > 1:
            sources = [f"  - {src}: {card.get('front', '')[:50]}" for src, card in occurrences]
            errors.append(f"DUPLICATE ID: {card_id}\n" + "\n".join(sources))

    return errors


def check_near_duplicates(all_cards: list[tuple[str, dict]], threshold: float = 0.9) -> list[str]:
    """Check for near-duplicate card fronts (content similarity)."""
    from difflib import SequenceMatcher

    warnings = []
    seen_fronts = []

    for source_file, card in all_cards:
        front = card.get('front', '').lower().strip()
        if len(front) < 20:  # Skip very short fronts
            continue

        for prev_source, prev_front, prev_id in seen_fronts:
            ratio = SequenceMatcher(None, front, prev_front).ratio()
            if ratio > threshold and front != prev_front:
                warnings.append(
                    f"NEAR-DUPLICATE ({ratio:.0%} similar):\n"
                    f"  - {source_file}: {card.get('id', 'no-id')}: {front[:60]}...\n"
                    f"  - {prev_source}: {prev_id}: {prev_front[:60]}..."
                )

        seen_fronts.append((source_file, front, card.get('id', '')))

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description='Check for duplicate card IDs'
    )
    parser.add_argument(
        'files',
        nargs='+',
        help='YAML files to check'
    )
    parser.add_argument(
        '--near-duplicates',
        action='store_true',
        help='Also check for near-duplicate content (slower)'
    )

    args = parser.parse_args()

    all_cards = []

    # Collect all cards with their source files
    for file_pattern in args.files:
        for filepath in Path('.').glob(file_pattern) if '*' in file_pattern else [Path(file_pattern)]:
            if not filepath.exists():
                print(f"Warning: File not found: {filepath}", file=sys.stderr)
                continue

            cards = load_cards(filepath)
            for card in cards:
                all_cards.append((str(filepath), card))

    print(f"Checking {len(all_cards)} cards from {len(args.files)} files...\n")

    # Check for ID collisions
    id_errors = check_id_collisions(all_cards)

    if id_errors:
        print("=" * 60)
        print("ID COLLISIONS FOUND:")
        print("=" * 60)
        for error in id_errors:
            print(f"\n{error}")
        print()

    # Check for near-duplicates if requested
    near_dup_warnings = []
    if args.near_duplicates:
        near_dup_warnings = check_near_duplicates(all_cards)
        if near_dup_warnings:
            print("=" * 60)
            print("NEAR-DUPLICATE CONTENT:")
            print("=" * 60)
            for warning in near_dup_warnings[:20]:  # Limit output
                print(f"\n{warning}")
            if len(near_dup_warnings) > 20:
                print(f"\n... and {len(near_dup_warnings) - 20} more")
            print()

    # Summary
    print("=" * 60)
    print("SUMMARY:")
    print("=" * 60)
    print(f"Total cards checked: {len(all_cards)}")
    print(f"ID collisions: {len(id_errors)}")
    if args.near_duplicates:
        print(f"Near-duplicates: {len(near_dup_warnings)}")

    if id_errors:
        print("\n❌ FAILED: ID collisions must be fixed")
        sys.exit(1)
    else:
        print("\n✓ PASSED: No ID collisions found")
        sys.exit(0)


if __name__ == '__main__':
    main()
