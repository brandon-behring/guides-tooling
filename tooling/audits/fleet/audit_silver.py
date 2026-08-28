#!/usr/bin/env python3
r"""audit_silver.py -- Semantic Silver audit for the course-learning fleet.

Stricter than `audit_silver_fleet.py`, which warns its own output is
"a fast calibration signal, not the authoritative Silver roster." This
script applies section-presence and role-delta semantic checks that
the heuristic auditor intentionally skips.

Per `docs/standards/00_universal/tier_model.md`, Silver = Bronze 10/10 +
4 content gates (manifest, Appendix D, IC.md, dashboard). This script
evaluates the 4 content gates semantically; Bronze 10/10 is a separate
pre-requisite tracked by `audit_all_courses.py`.

Gate semantics
--------------
1. Manifest: reuse `audit_source_manifest.audit_guide` (30% TODO
   threshold; no change from existing heuristic).

2. Appendix D semantic:
   - At least 5 `\section{}` blocks (one per question section + system
     design + tips) for Manning/Coursera guides; 3 blocks for short
     DLAI courses (<3h of source material).
   - Role-delta markers present: any of `Level:`, `\textbf{Expected}`,
     `IC3`, `IC4`, `IC5`, `Staff`, `Junior`, `Mid`, `Senior` in the
     text.
   - A System Design / Scenario section present (by section title
     regex).

3. IC.md section-presence (stub = missing 2+ of the four canonical
   sections):
   - Question Mapping (`Question Mapping`, `Interview Question`)
   - Cross-References (`Cross-References`, `Cross-Refs`, `Vol`)
   - Gaps Addressed (`Gaps Addressed`, `RED/YELLOW`, `Gap`)
   - Talking Points (`Talking Points`, `Key Talking`)

4. Dashboard: reuse the existing heuristic check from
   `audit_silver_fleet.check_dashboard` (already robust: `| Status |`
   table present + no scaffold phrases).

Classification per guide
------------------------
- `hand_audited`: touched by a silver-sweep commit
  (`git log --grep='silver-sweep' --name-only` ∩ guide path).
- `heuristic_only`: passes `audit_silver_fleet.py` gates but no
  silver-sweep commit touched it.
- `needs_authoring`: fails any of the 4 semantic gates above.

TBV-PREFIX-N tokens used by Gold exemplars (e.g., `TBV-RLHF-1`) are
NOT stub markers. Only bare `TODO` / `TBD` count as stubs, per the
existing IC.md gate in `audit_silver_fleet.py:118`.

Usage
-----
    scripts/audit_silver.py                 # per-guide table + report
    scripts/audit_silver.py --summary       # counts only
    scripts/audit_silver.py --needs-authoring
    scripts/audit_silver.py --guide SLUG
    scripts/audit_silver.py --output PATH   # custom report path

Exit code: 0 if all guides PASS honest Silver, 1 otherwise.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from tooling import discovery, layout, paths
from tooling.audits.fleet.audit_silver_fleet import (
    check_dashboard as check_dashboard_heuristic,
    check_manifest as check_manifest_heuristic,
    find_appendix_d,
)
from tooling.audits.fleet.audit_source_manifest import family_of

REPORTS_DIR = paths.host_root() / "reports"

THIN_DECK_CARD_FLOOR = 20

MANNING_COURSERA_APPD_MIN_QUESTIONS = 5
DLAI_SHORT_APPD_MIN_QUESTIONS = 3
DLAI_SHORT_HOURS_THRESHOLD = 3.0

# A "question" in Appendix D is any of:
#   - \item \textbf{...} inside enumerate (RLHF / Manning exemplar pattern)
#   - \subsection{Q<N>: ...} or \subsection*{Q<N>: ...} (DLAI depth-ladder pattern)
#   - \textbf{Q<N>:} or \textbf{Question <N>:} (inline variant)
QUESTION_MARKER_PATTERNS = [
    re.compile(r"^\s*\\item\s+\\textbf\{", re.MULTILINE),
    re.compile(r"\\subsection\*?\{Q\d+", re.IGNORECASE),
    re.compile(r"\\textbf\{Q\d+[\s:.]", re.IGNORECASE),
    re.compile(r"\\textbf\{Question\s+\d+", re.IGNORECASE),
    re.compile(r"\\begin\{interviewcontext\}"),
]

# Role/level differentiation tightened 2026-04-24 per
# reports/tier_spec_effectiveness_audit_20260424.md item 7.
#
# Old behavior: 18-pattern OR-list — a guide whose only role expression
# was a single `\companytags{Mid-level}` line passed the gate.
#
# New behavior: a guide passes when EITHER
#   (a) >=2 distinct level tokens appear in the text (e.g., both
#       `IC4` and `Senior`, signaling actual role-vs-role contrast), OR
#   (b) an explicit "Role / Level Mapping" section header is present
#       (the spec-blessed phrasing from tier_model.md §39).
ROLE_LEVEL_TOKEN_PATTERNS = [
    re.compile(r"\bIC[3-6]\b"),
    re.compile(r"\bL[4-7]/"),
    re.compile(r"\bStaff\+?\b"),
    re.compile(r"\bSenior\b", re.IGNORECASE),
    re.compile(r"\bMid-?level\b", re.IGNORECASE),
    re.compile(r"\bJunior\b", re.IGNORECASE),
]
ROLE_LEVEL_HEADER_PATTERNS = [
    re.compile(
        r"\\(section|subsection)\*?\{[^}]*Role\s*/\s*Level\s*Mapping",
        re.IGNORECASE,
    ),
    re.compile(r"^###?\s+Role\s*/\s*Level\s*Mapping", re.MULTILINE | re.IGNORECASE),
]
ROLE_DELTA_MIN_DISTINCT_TOKENS = 2

# Deprecated alias kept for the brief deprecation period in case any
# external tooling imported the old name. Remove on next sweep.
ROLE_DELTA_PATTERNS = ROLE_LEVEL_TOKEN_PATTERNS


def evaluate_role_delta(text: str) -> tuple[bool, str]:
    """Return (passes, reason). Tightened per audit memo item 7.

    Passes when text contains either >=2 distinct level tokens OR an
    explicit "Role / Level Mapping" section header. The reason string
    is suitable for embedding in a gate-failure detail message.
    """
    distinct_tokens = sum(1 for p in ROLE_LEVEL_TOKEN_PATTERNS if p.search(text))
    if distinct_tokens >= ROLE_DELTA_MIN_DISTINCT_TOKENS:
        return True, f"{distinct_tokens} distinct level tokens"
    for p in ROLE_LEVEL_HEADER_PATTERNS:
        if p.search(text):
            return True, "explicit Role/Level Mapping section"
    return False, (
        f"only {distinct_tokens} distinct level token(s); "
        "need >=2 OR an explicit Role/Level Mapping section header"
    )

# System design section. Required for guides on the allowlist per
# tier_model.md "where applicable" language. Presence-of-title (regex
# below) is the weak check; body-length (SYSTEM_DESIGN_MIN_WORDS) is the
# hardened check added 2026-04-22 so a 1-sentence stub can't pass.
SYSTEM_DESIGN_SECTION_PATTERN = re.compile(
    r"\\(section|subsection)\*?\{[^}]*"
    r"(System\s+Design|Scenario|Design\s+Round|Design\s+Question|"
    r"Build\s+an?|Design\s+an?|End-to-End|Scope\s+a)",
    re.IGNORECASE,
)
SYSTEM_DESIGN_MIN_WORDS = 50


def system_design_body_words(text: str) -> int:
    """Count substantive words in the first system-design section body.

    Extraction heuristic: from the first System-Design-pattern section
    marker (matched by `\\section{}`) to the next *sibling-level* section
    — i.e., the next `\\section`, not the next `\\subsection`. This is
    because a system-design scenario commonly structures its body as
    subsections ("Step 1: Requirements", "Step 2: Architecture", ...)
    that belong to the scenario, not sibling sections. If the match is a
    `\\subsection`, the next `\\section` OR `\\subsection` terminates
    the body.

    LaTeX noise (backslash commands, braces, comments) is stripped
    before word-counting. Returns 0 if no section found.
    """
    match = SYSTEM_DESIGN_SECTION_PATTERN.search(text)
    if match is None:
        return 0
    # group(1) is 'section' or 'subsection' from the pattern.
    matched_level = match.group(1).lower()
    start = match.end()
    # Sibling-level terminator: section-level matches stop only at the
    # next section; subsection-level matches stop at either.
    if matched_level == "section":
        terminator = r"\\section\*?\{"
    else:
        terminator = r"\\(section|subsection)\*?\{"
    next_heading = re.search(terminator, text[start:], re.MULTILINE)
    body = text[start:start + next_heading.start()] if next_heading else text[start:]
    # Strip LaTeX commands and comment lines, then count word-like tokens.
    body = re.sub(r"%.*$", "", body, flags=re.MULTILINE)
    body = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", body)
    body = re.sub(r"[{}\\]", " ", body)
    return len(IC_WORD_RE.findall(body))

IC_SECTIONS = {
    "question_mapping": re.compile(
        r"^#+\s.*(Question\s+Mapping|Interview\s+Question|Interview.*Mapping|"
        r"Canonical\s+Interview)",
        re.MULTILINE | re.IGNORECASE,
    ),
    "cross_references": re.compile(
        r"^#+\s.*(Cross-Reference|Cross-Ref|Cross-Course|Cross-Chapter|"
        r"Vol\s+Chapter|Vol Chapter)",
        re.MULTILINE | re.IGNORECASE,
    ),
    "gaps_addressed": re.compile(
        r"^#+\s.*(Gaps?\s+Addressed|RED/YELLOW|Gap\s+Addressed|Skills?\s+Gap)",
        re.MULTILINE | re.IGNORECASE,
    ),
    "talking_points": re.compile(
        r"^#+\s.*(Talking\s+Points|Key\s+Talking|Signal\s+Phrases?|"
        r"Key\s+Phrases?)",
        re.MULTILINE | re.IGNORECASE,
    ),
}
IC_STUB_MISSING_THRESHOLD = 2
IC_TODO_PATTERN = re.compile(r"\b(TODO|TBD)\b")

# Bracketed scaffold placeholders. These slipped past the canonical-section
# gate because the noise stripper removes them before word-count and headings
# are present with only placeholder bodies. Any occurrence fails IC.md.
IC_STUB_PLACEHOLDER_PATTERNS = [
    re.compile(r"\[Fill after[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[See deep-research[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[Fill in during[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[TBV(?:-[A-Za-z0-9-]+)?\]"),
    re.compile(r"\[TBD\]"),
]

# Minimum substantive-word count across the 4 canonical IC.md sections.
# Set from the deep-dive calibration: placeholders strip to 3-9 words; real
# content has 15+. After the 2026-04-22 Phase A sweep cleared all
# sections below 30 words, the floor was raised from 15 to 30 to prevent
# regression into thin-content territory. The 15w floor is retained as
# a "hard stub" tripwire; 30w is the real Silver minimum.
IC_MIN_SECTION_WORDS = 30
IC_STUB_WORD_FLOOR = 15

# Out-of-interview-scope waiver marker (per tier_model.md §9).
# When present in Appendix D, 2 interview-context blocks + role-delta is
# sufficient (instead of the 5/3 question floor).
WAIVER_MARKER_PATTERN = re.compile(
    r"\\section\*?\{[^}]*(Out-of-Interview-Scope\s+Waiver|"
    r"Aggregator\s+Waiver)",
    re.IGNORECASE,
)
WAIVER_MIN_QUESTIONS = 2

DLAI_DURATION_PATTERN = re.compile(
    r"\*\*Duration\*\*:\s*~?\s*([\d.]+)\s*(?:h|hr|hour)", re.IGNORECASE
)

# System-design allowlist: guides where tier_model.md:39 "where applicable"
# kicks in. Loaded from a reviewable YAML so the boundary is editable.
SYSTEM_DESIGN_ALLOWLIST_PATH = paths.system_design_allowlist()


def load_system_design_allowlist() -> set[str]:
    """Load the allowlist, warning loudly on every degradation path.

    A missing or malformed allowlist exempts EVERY guide from the
    system-design gate, so each fallback announces itself on stderr instead
    of silently returning an empty set.
    """
    path = SYSTEM_DESIGN_ALLOWLIST_PATH

    def _degraded(why: str) -> set[str]:
        print(
            f"[audit-error] audit_silver: system_design_allowlist {why} ({path})"
            " — no guide will require system-design coverage",
            file=sys.stderr,
        )
        return set()

    if not path.exists():
        return _degraded("missing")
    try:
        data = yaml.safe_load(path.read_text(errors="replace"))
    except yaml.YAMLError as exc:
        return _degraded(f"unparseable: {type(exc).__name__}")
    if not isinstance(data, dict):
        return _degraded("not a mapping")
    required = data.get("required")
    if not isinstance(required, list):
        return _degraded("'required' key missing or not a list")
    return {s for s in required if isinstance(s, str)}


SYSTEM_DESIGN_ALLOWLIST = load_system_design_allowlist()


def discover_guides() -> list[Path]:
    return discovery.iter_guide_dirs()


def silver_sweep_touched_guides() -> set[str]:
    """Guides touched by any `silver-sweep` commit (hand-authored cohort)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(paths.host_root()), "log", "--grep=silver-sweep",
             "--name-only", "--pretty=format:"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    touched: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        slug = line.split("/", 1)[0]
        touched.add(slug)
    return touched


def is_short_dlai(guide: Path) -> bool:
    """Short DLAI (<3h) gets calibrated thresholds per tier_model.md §9."""
    if family_of(guide.name) != "dlai":
        return False
    claude_md = guide / "CLAUDE.md"
    if not claude_md.exists():
        return False
    match = DLAI_DURATION_PATTERN.search(claude_md.read_text(errors="replace"))
    if not match:
        return False
    try:
        return float(match.group(1)) < DLAI_SHORT_HOURS_THRESHOLD
    except ValueError:
        return False


def count_questions(text: str) -> int:
    """Count question markers across all Appendix D conventions."""
    total = 0
    for pat in QUESTION_MARKER_PATTERNS:
        total += len(pat.findall(text))
    return total


def check_appendix_d_semantic(guide: Path) -> tuple[bool, str, dict]:
    """Returns (pass, reason, metadata).

    Metadata includes 'has_system_design', 'question_count', and
    'is_waiver' (True when the guide carries the Out-of-Interview-Scope
    Waiver per tier_model.md §9).
    """
    path = find_appendix_d(guide)
    if path is None:
        return False, "appendix_d_missing", {
            "has_system_design": False,
            "question_count": 0,
            "is_waiver": False,
        }
    text = path.read_text(errors="replace")
    is_waiver = bool(WAIVER_MARKER_PATTERN.search(text))
    question_count = count_questions(text)
    if is_waiver:
        min_questions = WAIVER_MIN_QUESTIONS
    else:
        min_questions = (
            DLAI_SHORT_APPD_MIN_QUESTIONS
            if is_short_dlai(guide)
            else MANNING_COURSERA_APPD_MIN_QUESTIONS
        )
    has_role_delta, role_delta_reason = evaluate_role_delta(text)
    has_system_design = bool(SYSTEM_DESIGN_SECTION_PATTERN.search(text))
    on_sysd_allowlist = guide.name in SYSTEM_DESIGN_ALLOWLIST
    los_ref_count = count_los_refs(guide)
    reasons: list[str] = []
    if question_count < min_questions:
        reasons.append(f"question_count<{min_questions} ({question_count})")
    if not has_role_delta:
        reasons.append(f"no_role_delta ({role_delta_reason})")
    if on_sysd_allowlist and not has_system_design and not is_waiver:
        reasons.append("no_system_design (allowlisted)")
    # Gate promoted from advisory 2026-04-22: Appendix D must cite at least
    # one chapter via \cref{ch:...}, \ref{ch:...}, or a per-guide LOS-prefix
    # token (e.g., RSP-4.1). Phase A sweep confirmed all 118 guides pass.
    if los_ref_count == 0:
        reasons.append("no_los_refs (appendix_d cites no chapters)")
    # Gate promoted from advisory: allowlisted guides must have a
    # system-design section whose body is >=50 substantive words (catches
    # 1-sentence stub sections that pass the title regex).
    if on_sysd_allowlist and has_system_design and not is_waiver:
        sysd_words = system_design_body_words(text)
        if sysd_words < SYSTEM_DESIGN_MIN_WORDS:
            reasons.append(
                f"system_design_thin ({sysd_words}w<{SYSTEM_DESIGN_MIN_WORDS})"
            )
    meta = {
        "has_system_design": has_system_design,
        "question_count": question_count,
        "is_waiver": is_waiver,
        "on_sysd_allowlist": on_sysd_allowlist,
    }
    if reasons:
        return False, ";".join(reasons), meta
    return True, "", meta


def check_ic_md_semantic(guide: Path) -> tuple[bool, str]:
    path = layout.ic_md(guide)
    if not path.exists():
        return False, "ic_missing"
    text = path.read_text(errors="replace")
    if IC_TODO_PATTERN.search(text):
        return False, "ic_has_todo_or_tbd"
    for pat in IC_STUB_PLACEHOLDER_PATTERNS:
        if pat.search(text):
            return False, "ic_has_stub_placeholder"
    present = {name: bool(pat.search(text)) for name, pat in IC_SECTIONS.items()}
    missing = [name for name, ok in present.items() if not ok]
    if len(missing) >= IC_STUB_MISSING_THRESHOLD:
        return False, f"missing_sections:{','.join(missing)}"
    min_words = ic_section_min_words(guide)
    if min_words is not None and min_words < IC_MIN_SECTION_WORDS:
        return False, f"ic_section_thin({min_words}w<{IC_MIN_SECTION_WORDS})"
    return True, ""


def count_cards(guide: Path) -> int:
    cards_yaml = layout.cards_yaml(guide)
    if not cards_yaml.exists():
        return 0
    try:
        data = yaml.safe_load(cards_yaml.read_text(errors="replace"))
    except yaml.YAMLError:
        return 0
    if not isinstance(data, dict):
        return 0
    cards = data.get("cards")
    return len(cards) if isinstance(cards, list) else 0


# -------- B1 / B2 / B3 informational helpers (not gating) ---------------------
#
# These surface signal the existing Silver gates don't enforce. See
# tier_model.md §9 and plans/i-want-you-to-expressive-sutton.md (2026-04-21
# deep-dive) for why they are informational rather than blocking:
# - B1 (LOS-ref count): simulation showed 29/118 guides would false-fail a
#   hard gate because of naming-convention differences (ch:L*, ch:C*W*),
#   so this is advisory only until a safer threshold is agreed.
# - B2 (IC.md section word count): calibration sweep showed 34/118 guides
#   would false-fail at threshold 30 words because some IC.md templates
#   legitimately use short "Gaps Addressed" sections; informational only.
# - B3 (system-design section presence): tier_model.md:39 says "where
#   applicable"; an allowlist of system-design-heavy slugs deserves a
#   separate design pass, so surface as a column without gating.

LOS_REF_PATTERNS = [
    re.compile(r"\\cref\{ch:[^}]+\}", re.IGNORECASE),
    re.compile(r"\\ref\{ch:[^}]+\}", re.IGNORECASE),
]

IC_HEADING_PATTERN = re.compile(r"^#+\s", re.MULTILINE)
IC_BODY_NOISE_RE = re.compile(
    r"(\[[A-Za-z /]+\]|\b(TODO|TBD|TBV-?[A-Za-z0-9-]*)\b|[|`_*~#>])"
)
IC_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9-]+\b")

DASHBOARD_STATUS_RE = re.compile(r"\[\s*([RYG])\s*\]")


def load_los_prefix(guide: Path) -> str | None:
    """Read guide_qa.yaml to extract the LOS prefix, if defined."""
    qa = guide / "guide_qa.yaml"
    if not qa.exists():
        return None
    try:
        data = yaml.safe_load(qa.read_text(errors="replace"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    los = data.get("los")
    if isinstance(los, dict):
        prefix = los.get("prefix")
        if isinstance(prefix, str) and prefix:
            return prefix
    return None


def count_los_refs(guide: Path) -> int:
    """Count LOS/chapter cross-references in the guide's Appendix D.

    Broadened regex per the deep-dive simulation: matches any `ch:*` label,
    both `\\cref{}` and `\\ref{}` forms, plus per-guide LOS-prefix patterns
    (e.g., RSP-4.1, TRB-5.2). Informational only; not a gate.
    """
    appd = find_appendix_d(guide)
    if appd is None:
        return 0
    text = appd.read_text(errors="replace")
    count = 0
    for pat in LOS_REF_PATTERNS:
        count += len(pat.findall(text))
    prefix = load_los_prefix(guide)
    if prefix:
        los_pat = re.compile(rf"\b{re.escape(prefix)}-\d+\.\d+\b")
        count += len(los_pat.findall(text))
    return count


def _extract_ic_section_body(text: str, section_pattern: re.Pattern) -> str | None:
    match = section_pattern.search(text)
    if match is None:
        return None
    start = match.end()
    next_heading = IC_HEADING_PATTERN.search(text, start)
    return text[start:next_heading.start()] if next_heading else text[start:]


def _count_substantive_words(body: str) -> int:
    stripped_body = re.sub(r"^\s*[-*+]\s*", "", body, flags=re.MULTILINE)
    cleaned = IC_BODY_NOISE_RE.sub(" ", stripped_body)
    return len(IC_WORD_RE.findall(cleaned))


def ic_section_min_words(guide: Path) -> int | None:
    """Return the minimum substantive-word count across the 4 canonical IC sections.

    None if the IC.md file is missing entirely. Sections not found are
    skipped (reported via the existing IC.md gate); this helper measures
    body thinness only for sections that DO exist.
    """
    ic_path = layout.ic_md(guide)
    if not ic_path.exists():
        return None
    text = ic_path.read_text(errors="replace")
    counts: list[int] = []
    for pattern in IC_SECTIONS.values():
        body = _extract_ic_section_body(text, pattern)
        if body is not None:
            counts.append(_count_substantive_words(body))
    return min(counts) if counts else None


def dashboard_status_counts(guide: Path) -> tuple[int, int, int]:
    """Return (red, yellow, green) status-marker counts from dashboard.md.

    All zeros if the dashboard doesn't exist. Parses `[R]`/`[Y]`/`[G]`
    markers in the status column of the metrics table.
    """
    dashboard = layout.dashboard(guide)
    if not dashboard.exists():
        return (0, 0, 0)
    text = dashboard.read_text(errors="replace")
    red = sum(1 for m in DASHBOARD_STATUS_RE.finditer(text) if m.group(1).upper() == "R")
    yellow = sum(1 for m in DASHBOARD_STATUS_RE.finditer(text) if m.group(1).upper() == "Y")
    green = sum(1 for m in DASHBOARD_STATUS_RE.finditer(text) if m.group(1).upper() == "G")
    return (red, yellow, green)


def classify(guide: Path, sweep_touched: set[str], silver_pass: bool,
             is_waiver: bool) -> str:
    if not silver_pass:
        return "needs_authoring"
    if is_waiver:
        return "waiver"
    if guide.name in sweep_touched:
        return "hand_audited"
    return "heuristic_only"


def audit_guide(guide: Path) -> dict:
    manifest_ok, manifest_reason = check_manifest_heuristic(guide)
    appd_ok, appd_reason, appd_meta = check_appendix_d_semantic(guide)
    ic_ok, ic_reason = check_ic_md_semantic(guide)
    dash_ok, dash_reason = check_dashboard_heuristic(guide)
    silver_pass = manifest_ok and appd_ok and ic_ok and dash_ok
    dash_red, dash_yellow, _dash_green = dashboard_status_counts(guide)
    return {
        "guide": guide.name,
        "family": family_of(guide.name),
        "short_dlai": is_short_dlai(guide),
        "gates": {
            "Manifest": {"pass": manifest_ok, "reason": manifest_reason},
            "App-D": {"pass": appd_ok, "reason": appd_reason},
            "IC.md": {"pass": ic_ok, "reason": ic_reason},
            "Dashboard": {"pass": dash_ok, "reason": dash_reason},
        },
        "appd_meta": appd_meta,
        "silver_pass": silver_pass,
        "card_count": count_cards(guide),
        # Informational-only signals (not gates). See helper docstrings.
        "los_ref_count": count_los_refs(guide),
        "ic_min_words": ic_section_min_words(guide),
        "has_system_design": appd_meta.get("has_system_design", False),
        "dashboard_red": dash_red,
        "dashboard_yellow": dash_yellow,
    }


def format_row(result: dict, width: int) -> str:
    cells = [
        "PASS" if result["gates"][g]["pass"] else "FAIL"
        for g in ("Manifest", "App-D", "IC.md", "Dashboard")
    ]
    silver = "PASS" if result["silver_pass"] else "FAIL"
    thin = "THIN" if result["card_count"] < THIN_DECK_CARD_FLOOR else "    "
    cls_short = {
        "hand_audited": "HAND",
        "heuristic_only": "HEUR",
        "needs_authoring": "NEED",
        "waiver": "WAIV",
    }[result["classification"]]
    los_ref = result.get("los_ref_count", 0)
    ic_min = result.get("ic_min_words")
    ic_min_str = "-" if ic_min is None else str(ic_min)
    sysd = "Y" if result.get("has_system_design") else "-"
    return (
        f"  {result['guide']:<{width}}  "
        f"{cells[0]:<8}  {cells[1]:<6}  {cells[2]:<6}  {cells[3]:<10}  "
        f"{silver:<6}  {cls_short:<4}  {thin}  {result['card_count']:>4}  "
        f"{los_ref:>3}  {ic_min_str:>4}  {sysd:<3}"
    )


def build_report(results: list[dict], sweep_touched: set[str]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(results)
    silver_pass = sum(1 for r in results if r["silver_pass"])
    cohort = Counter(r["classification"] for r in results)
    thin = sum(1 for r in results if r["card_count"] < THIN_DECK_CARD_FLOOR)

    gate_fail: Counter[str] = Counter()
    for r in results:
        for gate, res in r["gates"].items():
            if not res["pass"]:
                gate_fail[gate] += 1

    lines = [
        "# Silver Fleet Honest Audit",
        "",
        f"Generated: {now}",
        f"Guides audited: {total}",
        f"Silver-sweep-touched (hand-audited cohort): {len(sweep_touched)}",
        "",
        "## Executive summary",
        "",
        f"- Honest Silver PASS: **{silver_pass}/{total}**",
        f"- Hand-authored (silver-sweep touched + all 4 gates pass): "
        f"**{cohort['hand_audited']}**",
        f"- Heuristic-only PASS (passes this script's gates but no "
        f"silver-sweep commit): **{cohort['heuristic_only']}**",
        f"- Waiver (out-of-interview-scope or aggregator waiver per "
        f"tier_model.md §9): **{cohort['waiver']}**",
        f"- Needs authoring (fails at least one semantic gate): "
        f"**{cohort['needs_authoring']}**",
        f"- Thin-deck flag (<{THIN_DECK_CARD_FLOOR} cards in all_cards.yml): "
        f"**{thin}**",
        "",
        "Per-gate FAIL counts:",
        "",
    ]
    for gate in ("Manifest", "App-D", "IC.md", "Dashboard"):
        lines.append(f"- **{gate}**: {gate_fail[gate]} fails")
    lines.extend([
        "",
        "## Per-guide results",
        "",
        "Columns:",
        "- `M/A/I/D` = Manifest / App-D / IC.md / Dashboard gate status",
        "- `Silver` = honest Silver PASS (all 4 gates)",
        "- `Class` = HAND (hand-authored) / HEUR (heuristic-only) / "
        "NEED (needs authoring)",
        "- `Thin` = THIN if card count < 20; cards column shows the count",
        "",
        "| Guide | M | A | I | D | Silver | Class | Thin | Cards |",
        "|-------|---|---|---|---|--------|-------|------|------:|",
    ])
    for r in sorted(results, key=lambda x: (not x["silver_pass"],
                                            x["classification"] != "hand_audited",
                                            x["guide"])):
        gates = r["gates"]
        silver = "PASS" if r["silver_pass"] else "FAIL"
        cls_short = {
            "hand_audited": "HAND",
            "heuristic_only": "HEUR",
            "needs_authoring": "NEED",
            "waiver": "WAIV",
        }[r["classification"]]
        thin = "THIN" if r["card_count"] < THIN_DECK_CARD_FLOOR else "-"
        lines.append(
            f"| {r['guide']} | "
            f"{'G' if gates['Manifest']['pass'] else 'R'} | "
            f"{'G' if gates['App-D']['pass'] else 'R'} | "
            f"{'G' if gates['IC.md']['pass'] else 'R'} | "
            f"{'G' if gates['Dashboard']['pass'] else 'R'} | "
            f"{silver} | {cls_short} | {thin} | {r['card_count']} |"
        )

    needs = [r for r in results if r["classification"] == "needs_authoring"]
    if needs:
        lines.extend([
            "",
            "## Ranked authoring queue (Phase 2 input)",
            "",
            "Guides failing at least one semantic gate, grouped by failing "
            "gate. Highest-leverage fixes first.",
            "",
        ])
        by_gate: dict[str, list[dict]] = {}
        for r in needs:
            for gate, res in r["gates"].items():
                if not res["pass"]:
                    by_gate.setdefault(gate, []).append(r)
                    break
        for gate in ("Manifest", "App-D", "IC.md", "Dashboard"):
            guides_for_gate = by_gate.get(gate, [])
            if not guides_for_gate:
                continue
            lines.append(f"### Fails `{gate}` first ({len(guides_for_gate)})")
            lines.append("")
            for r in sorted(guides_for_gate, key=lambda x: x["guide"]):
                reason = r["gates"][gate]["reason"]
                lines.append(f"- `{r['guide']}` — {reason}")
            lines.append("")

    heur = [r for r in results if r["classification"] == "heuristic_only"]
    if heur:
        lines.extend([
            "## Heuristic-only Silver PASS (spot-check required)",
            "",
            "These guides pass all 4 semantic gates but no silver-sweep "
            "commit touched them. They may be genuine pre-existing Silver "
            "or pre-sweep templated content. Sample 10 randomly and "
            "confirm IC.md + App-D read as source-engaged, not filler.",
            "",
        ])
        for r in sorted(heur, key=lambda x: x["guide"]):
            lines.append(f"- `{r['guide']}`")
        lines.append("")

    thin_list = [r for r in results if r["card_count"] < THIN_DECK_CARD_FLOOR]
    if thin_list:
        lines.extend([
            "## Thin-deck flag",
            "",
            f"Guides with fewer than {THIN_DECK_CARD_FLOOR} cards in "
            "`notes/notebook/cards/all_cards.yml`. Bronze-compliant but "
            "pedagogically limited; schedule card authoring.",
            "",
        ])
        for r in sorted(thin_list, key=lambda x: (x["card_count"], x["guide"])):
            lines.append(f"- `{r['guide']}` — {r['card_count']} cards")
        lines.append("")

    return "\n".join(lines) + "\n"


def _print_dashboard_debt() -> int:
    """Parse every guide's docs/review/dashboard.md, rank by RED count, print.

    Informational only. RED-metric count is content-composition debt, not
    Silver quality debt: per the 2026-04-21 deep-dive, 61 of 118 guides
    carried >=3 RED metrics at time of writing, and the causes are
    mis-calibrated glossary/bibliography/page-count thresholds for
    tutorial-genre guides, plus deliberate deferral of metadata curation
    in favour of interview-content authoring. Surface it here so a
    post-Silver polish sprint can target the worst offenders.
    """
    guides = discover_guides()
    if not guides:
        print("No guides found.", file=sys.stderr)
        return 1
    rows: list[tuple[str, int, int, int]] = []
    for g in guides:
        red, yellow, green = dashboard_status_counts(g)
        rows.append((g.name, red, yellow, green))
    # Rank by RED desc then YELLOW desc then slug.
    rows.sort(key=lambda r: (-r[1], -r[2], r[0]))
    width = max(len(r[0]) for r in rows)
    print(f"  {'Guide':<{width}}  {'RED':>4}  {'YEL':>4}  {'GRN':>4}")
    print("  " + "-" * (width + 22))
    for name, r, y, g in rows:
        print(f"  {name:<{width}}  {r:>4}  {y:>4}  {g:>4}")
    total = len(rows)
    heavy = sum(1 for r in rows if r[1] >= 3)
    any_red = sum(1 for r in rows if r[1] >= 1)
    print()
    print(f"Total guides:             {total}")
    print(f"Guides with >=1 RED:      {any_red}")
    print(f"Guides with >=3 RED:      {heavy}  (heavy content-composition debt)")
    print("Note: dashboard-RED is informational content-composition debt, NOT")
    print("a Silver gate. See plans/i-want-you-to-expressive-sutton.md (2026-04-21).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--summary", action="store_true",
                        help="Counts only, no per-guide rows")
    parser.add_argument("--needs-authoring", action="store_true",
                        help="Print only guides that fail semantic gates")
    parser.add_argument("--guide", help="Single guide slug")
    parser.add_argument("--output", type=Path,
                        default=REPORTS_DIR / "silver_honest_audit_2026-04-21.md",
                        help="Report path")
    parser.add_argument("--no-report", action="store_true",
                        help="Skip writing the markdown report")
    parser.add_argument(
        "--dashboard-debt", action="store_true",
        help="Print a table of guides ranked by dashboard RED/YELLOW counts "
        "(content-composition debt, informational only; does not affect "
        "Silver PASS).",
    )
    args = parser.parse_args()

    if args.dashboard_debt:
        return _print_dashboard_debt()

    if args.guide:
        target = paths.host_root() / args.guide
        if not (target / "guide_qa.yaml").exists():
            print(f"Guide not found or has no guide_qa.yaml: {target}",
                  file=sys.stderr)
            return 1
        guides = [target]
    else:
        guides = discover_guides()

    if not guides:
        print("No guides found.", file=sys.stderr)
        return 1

    sweep_touched = silver_sweep_touched_guides()

    results: list[dict] = []
    for g in guides:
        r = audit_guide(g)
        r["classification"] = classify(
            g, sweep_touched, r["silver_pass"],
            r["appd_meta"].get("is_waiver", False),
        )
        results.append(r)

    width = max(len(r["guide"]) for r in results)

    if not args.summary and not args.needs_authoring:
        header = (
            f"  {'Guide':<{width}}  {'Manifest':<8}  {'App-D':<6}  "
            f"{'IC.md':<6}  {'Dashboard':<10}  {'Silver':<6}  "
            f"{'Class':<4}  Thin  Cards  LOS  ICmn  SysD"
        )
        print(header)
        print("  " + "-" * (width + 75))
        for r in sorted(results, key=lambda x: x["guide"]):
            if args.needs_authoring and r["silver_pass"]:
                continue
            print(format_row(r, width))

    if args.needs_authoring:
        needs = [r for r in results if not r["silver_pass"]]
        for r in sorted(needs, key=lambda x: x["guide"]):
            print(format_row(r, width))

    total = len(results)
    silver = sum(1 for r in results if r["silver_pass"])
    cohort = Counter(r["classification"] for r in results)
    thin = sum(1 for r in results if r["card_count"] < THIN_DECK_CARD_FLOOR)
    print()
    print(f"Silver PASS (honest): {silver}/{total}")
    print(f"  hand_audited:       {cohort['hand_audited']}")
    print(f"  heuristic_only:     {cohort['heuristic_only']}")
    print(f"  waiver:             {cohort['waiver']}")
    print(f"  needs_authoring:    {cohort['needs_authoring']}")
    print(f"  thin_deck_flag:     {thin}")

    # Informational signals (not Silver gates) -- see plan 2026-04-21 deep-dive.
    zero_los_ref = sum(1 for r in results if r.get("los_ref_count", 0) == 0)
    thin_ic_30 = sum(
        1 for r in results
        if r.get("ic_min_words") is not None and r["ic_min_words"] < 30
    )
    thin_ic_15 = sum(
        1 for r in results
        if r.get("ic_min_words") is not None and r["ic_min_words"] < 15
    )
    missing_sysd = sum(1 for r in results if not r.get("has_system_design"))
    heavy_dash_debt = sum(
        1 for r in results if r.get("dashboard_red", 0) >= 3
    )
    print()
    print("Informational signals (post-2026-04-22 hardening):")
    print(f"  LOS/chapter refs == 0:     {zero_los_ref}/{total}  (GATED: App-D fails)")
    print(f"  IC.md min-section < 15w:   {thin_ic_15}/{total}  (GATED: IC.md fails, hard-stub tripwire)")
    print(f"  IC.md min-section < 30w:   {thin_ic_30}/{total}  (GATED: IC.md fails, Silver floor)")
    print(f"  No system-design section:  {missing_sysd}/{total}  (GATED for allowlist guides only; advisory otherwise)")
    print(f"  Dashboard red >= 3:        {heavy_dash_debt}/{total}  (advisory; content-composition debt, post-Silver polish)")

    if not args.no_report and not args.guide:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        args.output.write_text(build_report(results, sweep_touched))
        print(f"\nReport: {args.output}")

    return 0 if silver == total else 1


if __name__ == "__main__":
    sys.exit(main())
