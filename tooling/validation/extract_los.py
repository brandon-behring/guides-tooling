#!/usr/bin/env python3
"""
Extract and validate Learning Outcome Statements (LOS) from LaTeX chapters.

Validates:
- LOS ID format (PREFIX-CHAPTER.NUMBER)
- Bloom's taxonomy level validity
- LOS coverage by chapter
- Cognitive level distribution

Usage:
    python extract_los.py vol1_experimentation/chapters/*.tex --validate
    python extract_los.py vol*/chapters/*.tex --report
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Valid Bloom's taxonomy levels (extended set for course guides)
# See CLAUDE.md "Verified LOS Verb Set" for the full canonical list
VALID_LEVELS = {
    'define', 'explain', 'calculate', 'compare', 'analyze', 'evaluate', 'design',
    'apply', 'debug', 'trace', 'identify', 'describe', 'prepare', 'derive',
    'configure', 'implement', 'detect', 'conduct', 'build', 'determine',
    'construct', 'enforce', 'operate', 'select',
}

# Expected LOS prefix by volume
VOLUME_PREFIXES = {
    'vol1': 'EXP',
    'vol2': 'CI',
    'vol3': ['PY', 'PR', 'IC', 'T1', 'T2', 'T3', 'T3A', 'T3B', 'DS', 'SYS',
             'DS-PD', 'DS-ST', 'ML', 'PML', 'MLS', 'RAG', 'FRD', 'CO', 'SIM'],
    'vol4': 'SQL',
    'vol5': 'ML',
    'vol6': 'LLM',
    'vol7': 'PRICE',
    'vol8': 'MLOPS',
    'vol9': 'PA',
    'vol10': 'ADS',
    'vol11': 'CR',
    'vol12': 'TS',
    'vol13': 'REC',
    'vol_integrated': 'INT',
}


def extract_los_from_file(filepath: Path) -> list[dict[str, Any]]:
    """Extract all LOS definitions from a LaTeX file."""
    content = filepath.read_text(encoding='utf-8')
    los_list = []

    # Pattern: \los{ID}{level}{statement}
    pattern = r'\\los\{([^}]+)\}\{([^}]+)\}\{([^}]+(?:\{[^}]*\}[^}]*)*)\}'

    for match in re.finditer(pattern, content, re.DOTALL):
        los_id = match.group(1).strip()
        level = match.group(2).strip()
        statement = match.group(3).strip()
        statement = re.sub(r'\s+', ' ', statement)

        los_list.append({
            'id': los_id,
            'level': level,
            'statement': statement,
            'source': str(filepath)
        })

    return los_list


def validate_los_id(los_id: str, volume: str) -> tuple[bool, str]:
    """Validate LOS ID format."""
    # Expected format: PREFIX-CHAPTER.NUMBER or PREFIX-SUB-CHAPTER.NUMBER
    # Examples: PY-1.1, DS-PD-8.1, T3A-6.1
    pattern = r'^([A-Z0-9]+(?:-[A-Z0-9]+)?)-(\d+)\.(\d+)$'
    match = re.match(pattern, los_id)

    if not match:
        return False, f"Invalid format: {los_id} (expected PREFIX-CHAPTER.NUMBER)"

    prefix = match.group(1)
    expected_prefix = VOLUME_PREFIXES.get(volume)

    if expected_prefix:
        if isinstance(expected_prefix, list):
            if prefix not in expected_prefix:
                return False, f"Invalid prefix: {prefix} (expected one of {expected_prefix})"
        elif prefix != expected_prefix:
            return False, f"Invalid prefix: {prefix} (expected {expected_prefix})"

    return True, "OK"


def validate_level(level: str) -> tuple[bool, str]:
    """Validate Bloom's taxonomy level."""
    if level.lower() in VALID_LEVELS:
        return True, "OK"
    return False, f"Invalid level: {level} (valid: {', '.join(sorted(VALID_LEVELS))})"


def get_volume_from_path(filepath: Path) -> str:
    """Extract volume identifier from file path."""
    parts = filepath.parts
    for part in parts:
        if part.startswith('vol') and '_' in part:
            return part.split('_')[0]  # e.g., 'vol1' from 'vol1_experimentation'
    return 'unknown'


def analyze_cognitive_distribution(los_list: list[dict]) -> dict[str, int]:
    """Analyze cognitive level distribution."""
    dist = defaultdict(int)
    for los in los_list:
        level = los['level'].lower()
        dist[level] += 1
    return dict(dist)


def main():
    parser = argparse.ArgumentParser(
        description='Extract and validate LOS from LaTeX chapters'
    )
    parser.add_argument(
        'files',
        nargs='+',
        help='LaTeX files to process'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate LOS format and report errors'
    )
    parser.add_argument(
        '--report',
        action='store_true',
        help='Generate coverage report'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print detailed info'
    )

    args = parser.parse_args()

    all_los = []
    errors = []
    by_volume = defaultdict(list)
    by_chapter = defaultdict(list)

    for file_pattern in args.files:
        for filepath in Path('.').glob(file_pattern) if '*' in file_pattern else [Path(file_pattern)]:
            if not filepath.exists():
                continue

            volume = get_volume_from_path(filepath)
            los_list = extract_los_from_file(filepath)

            for los in los_list:
                all_los.append(los)
                by_volume[volume].append(los)

                # Extract chapter number from ID
                id_match = re.match(r'[A-Z0-9]+-(\d+)\.', los['id'])
                if id_match:
                    chapter = id_match.group(1)
                    by_chapter[f"{volume}-ch{chapter}"].append(los)

                if args.validate:
                    # Validate ID format
                    valid, msg = validate_los_id(los['id'], volume)
                    if not valid:
                        errors.append(f"{filepath}: {msg}")

                    # Validate level
                    valid, msg = validate_level(los['level'])
                    if not valid:
                        errors.append(f"{filepath}: {msg}")

    # Output results
    if args.validate:
        if errors:
            print("Validation errors:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)
        else:
            print(f"Validation passed: {len(all_los)} LOS checked")

    if args.report:
        print("\n=== LOS Coverage Report ===\n")

        print("By Volume:")
        for volume in sorted(by_volume.keys()):
            los_list = by_volume[volume]
            dist = analyze_cognitive_distribution(los_list)
            print(f"  {volume}: {len(los_list)} LOS")
            for level in sorted(VALID_LEVELS):
                count = dist.get(level, 0)
                pct = (count / len(los_list) * 100) if los_list else 0
                if count > 0:
                    print(f"    - {level}: {count} ({pct:.0f}%)")

        print("\nBy Chapter:")
        for chapter_key in sorted(by_chapter.keys()):
            los_list = by_chapter[chapter_key]
            print(f"  {chapter_key}: {len(los_list)} LOS")

    if not args.validate and not args.report:
        # Default: just print summary
        print(f"Total LOS: {len(all_los)}")
        dist = analyze_cognitive_distribution(all_los)
        print("\nCognitive distribution:")
        for level in sorted(VALID_LEVELS):
            count = dist.get(level, 0)
            pct = (count / len(all_los) * 100) if all_los else 0
            print(f"  {level}: {count} ({pct:.0f}%)")


if __name__ == '__main__':
    main()
