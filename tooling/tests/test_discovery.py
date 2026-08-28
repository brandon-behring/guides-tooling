"""Discovery cannot be shadowed by machine-local copies; duplicate slugs raise (gt#33, r2 DRIVER-1).

On 2026-08-27, 36 rsync scratch copies under ``reports/_scratch/`` were discovered
as guides and, because slug resolution kept the last duplicate, 16 of 18 ``--guide``
audits read the artifact-less copy. These tests pin the three guards.
"""
from __future__ import annotations

import pytest

from tooling import discovery
from tooling.audits.guide import _guide_scope

REGISTRY = "guides:\n  - slug: g1\n    topic: topic-a\n  - slug: g2\n    topic: topic-b\n"


@pytest.fixture(autouse=True)
def _host(tmp_path, monkeypatch):
    monkeypatch.setenv("GUIDES_HOST_ROOT", str(tmp_path))
    _guide_scope._slug_index.cache_clear()
    yield
    _guide_scope._slug_index.cache_clear()


def _mk(root, *rel):
    for r in rel:
        p = root / r / "guide_qa.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("guide: {}\n")


def _found(root):
    return [d.relative_to(root).as_posix() for d in discovery.iter_guide_dirs()]


def test_scratch_copy_under_reports_is_not_discovered(tmp_path):
    (tmp_path / "guides.yml").write_text(REGISTRY)
    _mk(tmp_path, "topic-a/g1", "reports/_scratch/x/topic-a/g1", "scripts/tmp/g1", "docs/g1")
    assert _found(tmp_path) == ["topic-a/g1"]
    # and slug resolution lands on the real guide, not a copy
    assert _guide_scope.guide_dir_for_slug("g1") == tmp_path / "topic-a" / "g1"


def test_nested_dir_outside_registry_topics_is_ignored(tmp_path):
    (tmp_path / "guides.yml").write_text(REGISTRY)
    _mk(tmp_path, "topic-a/g1", "not-a-topic/g9")
    assert _found(tmp_path) == ["topic-a/g1"]


def test_flat_guide_always_discovered(tmp_path):
    (tmp_path / "guides.yml").write_text(REGISTRY)
    _mk(tmp_path, "topic-a/g1", "flatguide")
    assert _found(tmp_path) == ["flatguide", "topic-a/g1"]


def test_registry_missing_falls_back_to_exclude_set(tmp_path):
    _mk(tmp_path, "anything/g1", "reports/_scratch/g1")  # no guides.yml at all
    assert _found(tmp_path) == ["anything/g1"]


def test_dotdir_and_mount_are_skipped(tmp_path):
    (tmp_path / "guides.yml").write_text(REGISTRY)
    _mk(tmp_path, "topic-a/g1", ".claude/worktrees/topic-a/g1", "tooling/topic-a/g1")
    assert _found(tmp_path) == ["topic-a/g1"]


def test_registered_slug_is_pinned_to_its_own_topic(tmp_path):
    # g1 is registered to topic-a, so a copy under topic-b is not the guide and is
    # skipped; the registry-vs-disk guard then reports nothing missing (review of #35).
    (tmp_path / "guides.yml").write_text(REGISTRY)
    _mk(tmp_path, "topic-a/g1", "topic-b/g1")
    assert _found(tmp_path) == ["topic-a/g1"]


def test_duplicate_unregistered_slug_raises(tmp_path):
    # The registry cannot adjudicate an unregistered slug, so two copies of it are a
    # fleet-level error rather than a tie to break (DRIVER-1).
    (tmp_path / "guides.yml").write_text(REGISTRY)
    _mk(tmp_path, "topic-a/ghost", "topic-b/ghost")
    with pytest.raises(discovery.DuplicateGuideSlug, match=r"topic-a/ghost and topic-b/ghost"):
        discovery.iter_guide_dirs()


def test_duplicate_slug_raises_without_a_registry(tmp_path):
    _mk(tmp_path, "anything/g1", "elsewhere/g1")   # no guides.yml at all
    with pytest.raises(discovery.DuplicateGuideSlug):
        discovery.iter_guide_dirs()
