#!/usr/bin/env python3
"""
Load and validate guide_qa.yaml configuration for course guide QA.

Provides a GuideConfig dataclass with resolved paths and validated schema.
Searches upward from cwd for guide_qa.yaml if no explicit path given.

Usage:
    config = load_config("guide_qa.yaml")
    config = load_config()  # auto-search upward from cwd
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MetricDef:
    """A single metric definition from config."""

    name: str
    description: str
    target: int
    yellow: int
    check_cmd: str
    inverted: bool = False  # True means lower is better (e.g., error counts)


@dataclass
class ReadinessCheck:
    """A single readiness check from config."""

    name: str
    cmd: str
    blocking: bool = True


@dataclass
class GuideConfig:
    """Fully resolved guide QA configuration."""

    # Guide identity
    name: str
    version: str
    guide_dir: Path
    config_path: Path

    # File patterns
    chapters_glob: str
    appendices_glob: str
    cards_dir: Path
    review_dir: Path

    # Build commands
    build_cmd: str
    full_build_cmd: str

    # LOS settings
    los_prefix: str
    valid_levels: list[str]

    # Metrics and checks
    metrics: list[MetricDef] = field(default_factory=list)
    readiness_checks: list[ReadinessCheck] = field(default_factory=list)


def find_config(start: Path | None = None) -> Path:
    """Search upward from start (default: cwd) for guide_qa.yaml.

    Raises:
        FileNotFoundError: If no config found in any parent directory.
    """
    current = (start or Path.cwd()).resolve()

    for directory in [current, *current.parents]:
        candidate = directory / "guide_qa.yaml"
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"No guide_qa.yaml found searching upward from {current}. "
        f"Create one with: cp $HUB/tools/guide_template/guide_qa.yaml.template guide_qa.yaml"
    )


def load_config(path: str | Path | None = None) -> GuideConfig:
    """Load and validate a guide_qa.yaml configuration file.

    Args:
        path: Explicit path to config file. If None, searches upward from cwd.

    Returns:
        Validated GuideConfig with resolved paths.

    Raises:
        FileNotFoundError: If config file not found.
        ValueError: If required keys are missing or invalid.
    """
    config_path = Path(path) if path else find_config()
    config_path = config_path.resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config must be a YAML mapping, got {type(raw).__name__}")

    # Validate required top-level keys
    required = {"guide", "los", "metrics", "readiness_checks"}
    missing = required - set(raw.keys())
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(sorted(missing))}")

    guide = raw["guide"]
    los = raw["los"]
    base_dir = config_path.parent

    # Parse metrics
    metrics = []
    for name, mdef in raw["metrics"].items():
        metrics.append(
            MetricDef(
                name=name,
                description=mdef.get("description", name),
                target=int(mdef["target"]),
                yellow=int(mdef["yellow"]),
                check_cmd=mdef["check_cmd"],
                inverted=bool(mdef.get("inverted", False)),
            )
        )

    # Parse readiness checks
    checks = []
    for cdef in raw["readiness_checks"]:
        checks.append(
            ReadinessCheck(
                name=cdef["name"],
                cmd=cdef["cmd"],
                blocking=bool(cdef.get("blocking", True)),
            )
        )

    return GuideConfig(
        name=guide["name"],
        version=guide["version"],
        guide_dir=base_dir / guide["guide_dir"],
        config_path=config_path,
        chapters_glob=guide["chapters_glob"],
        appendices_glob=guide.get("appendices_glob", ""),
        cards_dir=base_dir / guide.get("cards_dir", "cards"),
        review_dir=base_dir / guide.get("review_dir", "docs/review"),
        build_cmd=guide.get("build_cmd", ""),
        full_build_cmd=guide.get("full_build_cmd", ""),
        los_prefix=los["prefix"],
        valid_levels=los.get("valid_levels", ["define", "explain", "calculate", "compare", "analyze", "evaluate", "design"]),
        metrics=metrics,
        readiness_checks=checks,
    )


if __name__ == "__main__":
    # Quick self-test: load config from arg or auto-search
    path = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        cfg = load_config(path)
        print(f"Loaded config: {cfg.name} v{cfg.version}")
        print(f"  Guide dir: {cfg.guide_dir}")
        print(f"  Metrics: {len(cfg.metrics)}")
        print(f"  Readiness checks: {len(cfg.readiness_checks)}")
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
