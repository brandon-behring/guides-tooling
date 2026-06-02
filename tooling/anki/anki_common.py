#!/usr/bin/env python3
"""
Shared constants and utilities for Anki deck generation.

Centralizes GUID generation, model definitions, and CSS
to ensure consistency across all course_learning guides.

Adapted from cfa_learning/scripts/anki_common.py.
"""

import hashlib


# =============================================================================
# Shared Constants
# =============================================================================

# Fixed model ID for stability (don't change — affects existing imported cards)
BASIC_MODEL_ID = 1607392400

# Card fields (5-field model)
CARD_FIELDS = [
    {'name': 'Front'},
    {'name': 'Back'},
    {'name': 'LOS'},
    {'name': 'Source'},
    {'name': 'Topic'},
]

# Shared CSS for consistent styling
CARD_CSS = '''
    .card {
        font-family: 'Segoe UI', Arial, sans-serif;
        font-size: 18px;
        text-align: left;
        color: #333;
        background-color: white;
        padding: 20px;
        max-width: 600px;
        margin: 0 auto;
    }
    .front { font-size: 20px; margin-bottom: 10px; }
    .back { font-size: 18px; white-space: pre-wrap; }
    .meta { font-size: 13px; color: #666; margin-top: 10px; }
    .los { background: #e3f2fd; padding: 2px 6px; border-radius: 3px; margin-right: 8px; }
    .topic { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }
    .source { display: block; margin-top: 5px; font-style: italic; }
    hr { border: none; border-top: 1px solid #ddd; margin: 15px 0; }
'''

# Basic card template (mustache syntax for genanki)
BASIC_TEMPLATE = {
    'name': 'Card 1',
    'qfmt': '''
        <div class="front">{{Front}}</div>
        <div class="meta">
            {{#LOS}}<span class="los">{{LOS}}</span>{{/LOS}}
            {{#Topic}}<span class="topic">{{Topic}}</span>{{/Topic}}
        </div>
    ''',
    'afmt': '''
        <div class="front">{{Front}}</div>
        <hr>
        <div class="back">{{Back}}</div>
        <hr>
        <div class="meta">
            {{#LOS}}<span class="los">LOS: {{LOS}}</span>{{/LOS}}
            {{#Source}}<span class="source">{{Source}}</span>{{/Source}}
        </div>
    ''',
}


# =============================================================================
# Shared Functions
# =============================================================================

def card_guid(deck_name: str, card_id: str) -> int:
    """Generate deterministic GUID from deck_name + card_id.

    Ensures:
    - Same card in same deck always gets same GUID
    - Re-imports update existing cards instead of creating duplicates

    Args:
        deck_name: The source deck name (used as GUID namespace).
        card_id: The unique card identifier (e.g., "vol0-ch01-TERM-KARMED_BANDIT").

    Returns:
        Integer GUID suitable for genanki.
    """
    return int(hashlib.sha256(f"{deck_name}_{card_id}".encode()).hexdigest()[:10], 16)


def deck_id_from_name(deck_name: str) -> int:
    """Generate deterministic deck ID from deck name.

    Args:
        deck_name: The deck name.

    Returns:
        Integer deck ID suitable for genanki.
    """
    return int(hashlib.sha256(deck_name.encode()).hexdigest()[:10], 16)
