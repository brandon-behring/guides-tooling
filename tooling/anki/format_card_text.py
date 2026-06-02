#!/usr/bin/env python3
"""
Auto-format flashcard text to fix inline numbered/bulleted lists.

Transforms inline lists like "1) First, 2) Second, 3) Third" into properly
formatted lists with newlines: "1) First\n2) Second\n3) Third".

Used by yaml_to_apkg.py to automatically fix formatting during export.

Copied from cfa_learning/scripts/format_card_text.py — the formatter is
generic and works on any text content.
"""

import os
import re
from typing import Tuple, Optional


# Feature flag for disabling auto-formatting if needed
ENABLE_AUTO_FORMATTING = os.getenv('AUTO_FORMAT_CARDS', 'true').lower() == 'true'


def has_existing_newlines(text: str) -> bool:
    """Check if text already has newline-separated numbered items."""
    pattern = r'\n\s*\d+[.):]\s'
    return bool(re.search(pattern, text))


def is_sequential(numbers: list) -> bool:
    """Check if numbers are sequential (1,2,3 or close enough)."""
    if len(numbers) < 2:
        return False

    try:
        nums = [int(n) for n in numbers]
    except ValueError:
        return False

    # Allow 1-2 gaps between consecutive numbers
    gaps = [nums[i+1] - nums[i] for i in range(len(nums)-1)]
    return all(g >= 1 and g <= 2 for g in gaps)


def extract_list_items(text: str, delimiter: str) -> Tuple[Optional[str], list]:
    """Extract list items from text based on delimiter pattern.

    Args:
        text: Text containing potential list.
        delimiter: ')' or '.' or ':'.

    Returns:
        (prefix, items, suffix) where prefix is text before list,
        items is list of (number, text) tuples, suffix is text after.
    """
    if delimiter == ')':
        pattern = r'(\d+)\)\s*([^,]+?)(?=,\s*\d+\)|$)'
    elif delimiter == '.':
        pattern = r'(\d+)\.\s*([^,]+?)(?=,\s*\d+\.|$)'
    elif delimiter == ':':
        pattern = r'(\d+):\s*([^,]+?)(?=,\s*\d+:|$)'
    else:
        return None, []

    matches = list(re.finditer(pattern, text))

    if len(matches) < 3:  # Need at least 3 items to be a list
        return None, []

    # Extract numbers and check if sequential
    numbers = [m.group(1) for m in matches]
    if not is_sequential(numbers):
        return None, []

    # Extract items
    items = []
    for i, match in enumerate(matches):
        num = match.group(1)
        item_text = match.group(2).strip()

        # Check item length — too short might be false positive
        if len(item_text) < 5:
            return None, []

        items.append((num, item_text))

    # Find prefix (text before first match)
    first_match_start = matches[0].start()
    prefix = text[:first_match_start].rstrip()

    # Check if there's text after the last item
    last_match_end = matches[-1].end()
    suffix = text[last_match_end:].lstrip(',').strip()

    return prefix, items, suffix


def is_likely_formula(text: str) -> bool:
    """Check if text looks like a formula with numbered components."""
    formula_keywords = ['calculate', 'compute', 'formula', 'equation', 'npv', 'irr']
    text_lower = text.lower()

    has_formula_keyword = any(kw in text_lower for kw in formula_keywords)

    # Check for parentheses without commas between numbers
    paren_pattern = r'\(\d+\)[^,]*\(\d+\)'
    has_spaced_parens = bool(re.search(paren_pattern, text))

    return has_formula_keyword and has_spaced_parens


def format_numbered_list(text: str, delimiter: str) -> str:
    """Format inline numbered list with proper newlines.

    Args:
        text: Text containing inline numbered list.
        delimiter: ')' or '.' or ':'.

    Returns:
        Formatted text with newlines, or original if not a list.
    """
    result = extract_list_items(text, delimiter)
    if result is None or len(result) != 3:
        return text

    prefix, items, suffix = result

    if not items:
        return text

    parts = []

    if prefix:
        parts.append(prefix)
        parts.append('')  # Blank line before list

    for num, item_text in items:
        parts.append(f"{num}{delimiter} {item_text}")

    if suffix:
        parts.append('')  # Blank line after list
        parts.append(suffix)

    return '\n'.join(parts)


def format_card_text(text: str, field_name: str = 'back') -> str:
    """Auto-format inline numbered/bulleted lists with proper newlines.

    Transforms:
        "1) First, 2) Second, 3) Third"
        -> "1) First\\n2) Second\\n3) Third"

    Safety checks prevent false positives:
    - Skips if already has newline-separated items
    - Requires at least 3 items
    - Requires sequential numbering
    - Requires items > 5 chars
    - Skips formulas with numbered components

    Args:
        text: Raw card text.
        field_name: 'front', 'back', or 'extra' (for context).

    Returns:
        Formatted text with proper newlines.
    """
    if not ENABLE_AUTO_FORMATTING:
        return text

    if not text or len(text) < 20:
        return text

    if has_existing_newlines(text):
        return text

    if is_likely_formula(text):
        return text

    for delimiter in [')', '.', ':']:
        formatted = format_numbered_list(text, delimiter)
        if formatted != text:
            return formatted

    return text


def main():
    """CLI for testing format_card_text."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python format_card_text.py '<text>'")
        print("\nExamples:")
        print("  python format_card_text.py '1) First, 2) Second, 3) Third'")
        print("  python format_card_text.py 'Actions: 1) Do this, 2) Then this, 3) Finally'")
        sys.exit(1)

    text = sys.argv[1]
    formatted = format_card_text(text)

    print("Original:")
    print(repr(text))
    print("\nFormatted:")
    print(repr(formatted))
    print("\nRendered:")
    print(formatted)


if __name__ == '__main__':
    main()
