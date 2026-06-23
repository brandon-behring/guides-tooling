"""Tests for the content-free templated-margin detector (--strict-templates)."""
from __future__ import annotations

from tooling.audits.guide.audit_margin_quality import templated_margin_label

# Confirmed scaffold stubs (from software_design_python / the SE guides).
# Note: the "See related ... chapters" form was intentionally dropped from the
# signatures — a genuine "See related X chapters for Y" is structurally identical
# to the stub and cannot be told apart by pattern (see test below).
TEMPLATED = [
    "Common mistake in template method and strategy patterns.",
    "Key pattern from observer pattern.",
    "Implement a small example applying state pattern.",
]

# Genuine, instantiated margins that must NOT be flagged — they either don't open
# with the template phrase or continue past a colon with real content.
GENUINE = [
    "Threading CPU-bound work gives no speedup: the GIL serializes bytecode.",
    "Common mistake in caching: stale entries served after a missed invalidation.",
    "Reset module-level singletons in fixtures, or tests leak state into each other.",
    "15 min: refactor a long if/elif dispatch into a Strategy dict.",
    "Mutable default arg is evaluated once at def time; use None and create inside.",
    # adversarial-review regressions: genuine notes that open with a template
    # phrase but have NO colon — exempted by the predicate (verb) guard
    "Common mistake in pandas is chained assignment that writes to a temporary frame.",
    "Common mistake in computing the gradient is sign errors that flip the update.",
    "Key pattern from observer is decoupling subjects from listeners via a registry.",
]


def test_templated_stubs_are_flagged():
    for text in TEMPLATED:
        assert templated_margin_label(text) is not None, text


def test_genuine_margins_not_flagged():
    for text in GENUINE:
        assert templated_margin_label(text) is None, text


def test_label_describes_the_template_class():
    assert "mistake" in templated_margin_label(
        "Common mistake in singleton, composite, and decorator patterns.")
    assert "pattern" in templated_margin_label("Key pattern from iterator pattern.")
