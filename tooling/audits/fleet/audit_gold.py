#!/usr/bin/env python3
# ruff: noqa: W605
r"""audit_gold.py -- live Gold-tier runner for the guides-manning fleet (roadmap T2).

Ported from ``course_learning/scripts/audit_gold.py`` and rewired onto the
``tooling.*`` package + the T1 per-guide audit suite
(``tooling.audits.guide.*``). The proven machinery is carried over verbatim
(the ``HonestReport`` PASS / GOLD-ELIGIBLE / SCAFFOLD-ONLY / FAIL
classification, the live-truth ``git_metadata`` header, ``gold_exceptions``
waiver parsing, and the G5 scaffold/TBV/word/citation checks); the gate logic
is brought up to the 7-gate Gold definition in
``tooling/standards/tier_model.md``:

  G1  retrieval coverage (100%) + zero checkpoint stubs.
  G2  **11**-audit clean: the ten binary audits emit no failure, AND
      ``back_content`` reports zero CRITICAL and zero HIGH (MEDIUM/INFO advisory).
  G3  built per-chapter decks (>= max(2, chapters-1)) + a complete deck + an
      ``anki.course_map`` covering every module; waiver ``decks_complete_only``.
      (Built-artifact check -- run ``make decks`` first; see check_gate3_decks.)
  G4  size-aware crossref floor (no family detection -- the fleet is all-Manning).
  G5  source-fidelity doc: >=500 non-template words, >=3 citation markers, a
      dedicated "E/F source verification" section; scaffold/TBV text fails.
  G6  dashboard zero RED; waiver ``dashboard_red_waiver``.
  G7  filename-keyed currency appendices E/F: a dated, non-stub
      ``E_post_course_updates.tex`` within the guide's velocity SLA (+ MEAP
      version tie), and a >=3-debate ``F_contrasting_opinions_open_debates.tex``;
      F waiver ``debates_waiver``.

Classification (G5 is the soft gate -- a guide that clears every *other* gate
but lacks a hand-authored fidelity doc is structurally Gold-eligible):

  PASS           -- all 7 gates pass.
  GOLD-ELIGIBLE  -- every non-G5 gate passes; G5 doc is MISSING.
  SCAFFOLD-ONLY  -- every non-G5 gate passes; G5 doc EXISTS but is scaffold/thin.
  FAIL           -- any non-G5 gate fails.

The G2 binary audits do not share a failure convention: some exit non-zero only
under ``--strict``/``--check``, some print a leading ``FAIL`` line but exit 0,
and ``margin_quality`` / ``term_consistency`` signal neither (advisory-only in
their CLI form). G2 therefore detects a failure as ``exit_code != 0`` (running
each audit with its strict/check flag) OR a ``^FAIL`` line in the output.

Known limitations (documented T2 scope -- see the PR thread):
- **G2 binary-gates 9 of the 11 audits.** ``margin_quality`` and
  ``term_consistency`` expose no pass/fail gate in their current CLI, so a bad
  margin density or a cross-guide term conflict is advisory, not a G2 failure.
  Making them gate (a ``--strict`` mode on those two T1 audits) is a tracked
  follow-up, not part of this runner port.
- **G3 is a built-artifact check, not a live ``make decks`` build.** Run
  ``make decks`` / ``make decks-all`` before auditing; a clean checkout with no
  built ``.apkg`` fails "decks/ missing". Gold is locally-verified, not CI-wired.
- **G7's E/F checks are structural** (date stamp, item/debate counts, the
  per-debate anchor, the velocity SLA) -- they do not semantically verify that
  each currency item names a concrete moving surface or that each debate carries
  dual-sourced positions A/B. Deeper validation tightens during the Track-G
  promotion waves.
- **The MEAP version<->date "at-or-after" tie is deferred to T4** (the
  MEAP-freshness checker, which carries clean version+date data); here G7 only
  checks that a pinned ``vN`` version is named in E.

Usage:
    python -m tooling.audits.fleet.audit_gold                 # all Silver-PASS
    python -m tooling.audits.fleet.audit_gold --guide <slug>  # single guide
    python -m tooling.audits.fleet.audit_gold --verbose
    python -m tooling.audits.fleet.audit_gold --report        # write markdown
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tooling import discovery, layout, paths

REPORTS_DIR = paths.host_root() / "reports"

# ---------------------------------------------------------------------------
# G2 -- the eleven gated audits.
# ---------------------------------------------------------------------------
# The ten binary audits, each mapped to the flag that makes it exit non-zero on
# its OWN failure condition (empty = no strict flag needed). check_gate2 treats
# a failure as any non-zero exit OR a leading "FAIL" line, so all ten run
# uniformly: crossref_quality exits 1 on broken refs; card_presentation prints
# "FAIL" and exits 0; the --strict/--check audits exit non-zero on failure.
#
# T2b: margin_quality and term_consistency now EXPOSE a --strict gate (margin =
# density/quality RED; term = within-guide duplicate definitions). They are
# deliberately still run WITHOUT --strict here -- activating the gate today would
# regress 4 of the 5 live Gold guides (ai_model_evaluation + docker_in_action_2e
# are margin-RED; nlp_in_action + llms_in_production carry within-guide term
# dupes), which is a content-remediation / threshold-calibration decision, not a
# tooling toggle. Flip these two to ["--strict"] once that pass lands. They are
# still invoked (flagless) so a future leading "FAIL" line is caught, not skipped.
TEN_AUDITS: dict[str, list[str]] = {
    "audit_atomicity": ["--check"],
    "audit_card_presentation": [],          # FAIL via ^FAIL line; exits 0
    "audit_card_quality": ["--strict"],
    "audit_content_freshness": ["--strict"],
    "audit_content_quality": ["--strict"],
    "audit_crossref_quality": [],           # exits 1 on broken refs
    "audit_margin_quality": [],             # --strict exists (T2b); not gated yet
    "audit_retrieval_coverage": ["--strict"],
    "audit_solution_quality": ["--strict"],
    "audit_term_consistency": [],           # --strict exists (T2b); not gated yet
}

RETRIEVAL_RE = re.compile(r"coverage\s+([\d.]+)%", re.IGNORECASE)
FAIL_RE = re.compile(r"^FAIL\b", re.MULTILINE)
# Out-of-scope markers only. "No card files found" is intentionally NOT here:
# for a card-bearing audit it is a real Gold-blocking failure (the audit exits
# non-zero), not a scope skip.
NOT_FOUND_RE = re.compile(r"Error: guide.*not found|No guides found")
CROSSREF_RE = re.compile(r"\\crossrefmargin\{")
CHECKPOINT_ITEM_RE = re.compile(
    r"\\item\[([A-Z][A-Z0-9-]*-[\d.]+)\](.*?)(?=\\item\[|\\end\{)", re.DOTALL
)

# ---------------------------------------------------------------------------
# G5 -- source-fidelity doc thresholds (carried over verbatim).
# ---------------------------------------------------------------------------
SCAFFOLD_SIGNATURES = [
    "aggressive-pace promotion",
    "deep spot-check would be scoped as a separate content-QA pass",
    "Subsequent revisions may deepen",
    "scaffolded by `scripts/scaffold_gold_audit.py`",
]
AUTHOR_RE = re.compile(r"\*\*Guide\*\*:\s*`[^`]+`\s*\([^,]*,\s*([^)]+)\)")
FIDELITY_CITATION_RE = re.compile(
    r"(?i)(book\s*§|Ch\.?\s*\d+|Chapter\s*\d+|Figure\s*\d+|Table\s*\d+|p\.\s*\d+)"
)
FIDELITY_MIN_CITATIONS = 3
FIDELITY_MIN_WORDS = 500
# T0 addition: G5 must record that the E/F appendices were source-verified.
EF_VERIFICATION_RE = re.compile(r"(?i)E/F\s+source\s+verification")

# ---------------------------------------------------------------------------
# G4 size-aware crossref floor.
# ---------------------------------------------------------------------------
G4_LARGE_MIN_CHAPTERS = 10
G4_LARGE_MIN_TOTAL = 6
G4_LARGE_MIN_FILES = 4

# ---------------------------------------------------------------------------
# G6 dashboard.
# ---------------------------------------------------------------------------
G6_DASHBOARD_RED_THRESHOLD = 1

# ---------------------------------------------------------------------------
# G7 -- currency appendices + velocity SLA.
# ---------------------------------------------------------------------------
E_FILENAME = "E_post_course_updates.tex"
F_FILENAME = "F_contrasting_opinions_open_debates.tex"
G7_MIN_CURRENCY_ITEMS = 3
G7_MIN_DEBATES = 3
# F citation floor: a contested debate is only honest if its Positions are cited.
# Enforce max(G7_F_CITE_FLOOR, 2 x debates) resolvable citation markers across the
# (comment-stripped) appendix, so verdict flags alone cannot pass an uncited F.
G7_F_CITE_FLOOR = 6
# A stub E: "No significant {breaking changes / best-practice shifts / ...}
# identified yet" and the like. Substantive change items still naming a surface
# do not match because of the trailing "yet".
E_STUB_RE = re.compile(r"(?i)no\s+(?:significant|notable|major)\b.{0,50}?\byet\b")
WHAT_HOLDS_RE = re.compile(r"(?i)(still\s+hold|what\s+still|source[-\s]stability|stability)")
# E date stamp: "current as of 2026-06" or "as of June 2026".
E_DATE_ISO_RE = re.compile(r"(?i)(?:current\s+)?as\s+of\s+(\d{4})-(\d{2})")
E_DATE_WORD_RE = re.compile(r"(?i)(?:current\s+)?as\s+of\s+([A-Z][a-z]+)\.?\s+(\d{4})")
_MONTHS = {
    m: i + 1 for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"]
    )
}
# Common 3-letter abbreviations ("as of Jun 2026" / "Sept 2026").
_MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
                "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
# Currency-item / debate structural markers. E currency items are item-level
# (itemize \item or per-update \subsection); top-level \section headers are
# category/framing groupings ("Library & API Changes"), NOT individual items.
ITEM_RE = re.compile(r"^\s*\\item\b", re.MULTILINE)
SUBSECTION_RE = re.compile(r"^\s*\\(?:subsection|paragraph)\*?\{", re.MULTILINE)
# Anchored to the per-debate bold marker (\textbf{Where the book sits.}), NOT the
# loose phrase: every F template's intro prose also says "...names where the book
# sits..." once, which would otherwise inflate the debate count by 1.
WHERE_BOOK_RE = re.compile(r"(?i)\\textbf\{[^}]*?where\s+(?:this|the)\s+book\s+sits")
VERDICT_RE = re.compile(r"(?i)(well[-\s]supported|contested|dated)")
# Resolvable citation markers (same family as the epilogue gate): a biblatex cite
# command, an arXiv id, a DOI, or an http(s) permalink. Counted on comment-stripped
# text so a fresh scaffold's commented example-cites do not satisfy the floor.
F_CITE_RES = (
    re.compile(r"\\(?:parencite|cite|footcite|textcite|autocite|href)\b"),
    re.compile(r"\b\d{4}\.\d{4,5}\b"),       # arXiv id
    re.compile(r"10\.\d{4,}/\S+"),            # DOI
    re.compile(r"https?://"),                 # permalink
)


def _strip_tex_comments(text: str) -> str:
    """Drop full-line and trailing TeX comments (ignoring escaped ``\\%``)."""
    out = []
    for line in text.splitlines():
        m = re.search(r"(?<!\\)%", line)
        out.append(line[: m.start()] if m else line)
    return "\n".join(out)

VELOCITY_MAX_AGE_MONTHS = {"fast": 6, "medium": 12, "slow": 18}
SHELF_VELOCITY = {
    "ai-agents": "fast",
    "ai-engineering-and-llm-apps": "fast",
    "llms-and-transformers": "fast",
    "rag-and-search": "fast",
    "evaluation-alignment-safety": "fast",
    "generative-ai-and-diffusion": "medium",
    "graphs-and-knowledge-graphs": "medium",
    "ml-engineering-and-mlops": "medium",
    "deep-learning": "medium",
    "ml-and-data-foundations": "slow",
    "reinforcement-learning": "slow",
    "software-engineering-and-python": "slow",
}
DEFAULT_VELOCITY = "medium"


# ---------------------------------------------------------------------------
# guide_qa.yaml + source_manifest readers.
# ---------------------------------------------------------------------------

def load_guide_qa(guide_dir: Path) -> dict:
    """Parse guide_qa.yaml (sibling of guide/); empty dict on any error."""
    qa = guide_dir / "guide_qa.yaml"
    if not qa.exists():
        return {}
    try:
        data = yaml.safe_load(qa.read_text(errors="replace"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_true(value) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def get_gold_exceptions(qa: dict) -> dict:
    exc = qa.get("gold_exceptions")
    return exc if isinstance(exc, dict) else {}


def get_velocity(guide_dir: Path, qa: dict) -> str:
    """gold.velocity from guide_qa.yaml, else the topic-shelf default."""
    gold = qa.get("gold")
    if isinstance(gold, dict):
        v = gold.get("velocity")
        if isinstance(v, str) and v.strip().lower() in VELOCITY_MAX_AGE_MONTHS:
            return v.strip().lower()
    shelf = guide_dir.parent.name
    return SHELF_VELOCITY.get(shelf, DEFAULT_VELOCITY)


def meap_version(guide_dir: Path) -> str | None:
    """The covered MEAP version from review/source_manifest.md, or None.

    Returns the value of the ``**MEAP version**: <v>`` line (the authoritative
    field per tier_model.md G7). A literal ``TBV`` is returned as-is so the
    caller can treat it as "MEAP but version unpinned".
    """
    manifest = layout.source_manifest(guide_dir)
    if not manifest.exists():
        return None
    text = manifest.read_text(errors="replace")
    m = re.search(r"(?im)^\s*[-*]?\s*\*\*MEAP version\*\*:\s*(.+)$", text)
    if m:
        return m.group(1).strip()
    # Fall back to a publication-status check so non-MEAP guides return None.
    if re.search(r"(?im)^\s*[-*]?\s*\*\*Publication status\*\*:\s*meap", text):
        return "unspecified"
    return None


# ---------------------------------------------------------------------------
# Subprocess helpers.
# ---------------------------------------------------------------------------

def git_metadata() -> dict[str, str]:
    """git SHA + dirty status + UTC timestamp for the live-truth header."""
    root = str(paths.host_root())
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"sha": "unknown", "dirty": "unknown",
                "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {
        "sha": sha,
        "dirty": "true" if porcelain.strip() else "false",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _audit_env() -> dict[str, str]:
    """Ensure the tooling mount is importable in the audit subprocess."""
    env = dict(os.environ)
    mount = str(paths.package_root())
    existing = env.get("PYTHONPATH", "")
    if mount not in existing.split(os.pathsep):
        env["PYTHONPATH"] = mount + (os.pathsep + existing if existing else "")
    return env


def run_guide_audit(module: str, slug: str, extra: list[str] | None = None) -> tuple[int, str]:
    """Run one per-guide audit as ``python -m tooling.audits.guide.<module>``."""
    cmd = [sys.executable, "-m", f"tooling.audits.guide.{module}", "--guide", slug]
    if extra:
        cmd += extra
    result = subprocess.run(
        cmd, cwd=str(paths.host_root()), env=_audit_env(),
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout + result.stderr


def run_back_content(slug: str) -> dict[str, int] | None:
    """Run audit_back_content --guides <slug> --json; return by_severity or None."""
    # --report-only suppresses the per-guide review/back_content_audit_*.json
    # side-writes; --json still prints the by_severity totals to stdout.
    cmd = [sys.executable, "-m", "tooling.audits.guide.audit_back_content",
           "--guides", slug, "--json", "--report-only"]
    result = subprocess.run(
        cmd, cwd=str(paths.host_root()), env=_audit_env(),
        capture_output=True, text=True,
    )
    for raw in (result.stdout, result.stderr):
        # Try the whole stream, then the {...} substring (defensive against any
        # stray prefix line); --json makes stdout pure JSON in the normal case.
        candidates = [raw]
        if "{" in raw and "}" in raw:
            candidates.append(raw[raw.index("{"):raw.rindex("}") + 1])
        for chunk in candidates:
            try:
                data = json.loads(chunk)
            except (json.JSONDecodeError, ValueError):
                continue
            sev = data.get("by_severity")
            if isinstance(sev, dict):
                return {k: int(v) for k, v in sev.items()}
    return None


# ---------------------------------------------------------------------------
# Report dataclasses + classification.
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class HonestReport:
    slug: str
    gates: list[GateResult] = field(default_factory=list)
    g5_reason: str = ""  # missing | scaffold | short | thin_citations | no_ef_section | pass

    @property
    def auto_gates_pass(self) -> bool:
        """Every gate EXCEPT G5 passes (keyed by name, robust to gate order)."""
        return all(g.passed for g in self.gates if not g.name.startswith("G5"))

    @property
    def classification(self) -> str:
        if all(g.passed for g in self.gates):
            return "PASS"
        if self.auto_gates_pass:
            return "GOLD-ELIGIBLE" if self.g5_reason == "missing" else "SCAFFOLD-ONLY"
        return "FAIL"


# ---------------------------------------------------------------------------
# Gate 1 -- retrieval coverage + checkpoint stubs.
# ---------------------------------------------------------------------------

def count_stub_checkpoint_items(chapters_dir: Path) -> tuple[int, int]:
    """(total, stubs) where a stub is a \\item[LOS-ID] with <10 words of body."""
    total = stubs = 0
    if not chapters_dir.exists():
        return 0, 0
    for tex in chapters_dir.glob("*.tex"):
        try:
            content = tex.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in CHECKPOINT_ITEM_RE.finditer(content):
            total += 1
            body = match.group(2).strip()
            # Strip macro NAMES + optional [..] args but keep {...} arg contents
            # (so prose inside \textbf{...}/\emph{...} still counts); the next
            # pass removes the braces, leaving the words.
            stripped = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", body)
            stripped = re.sub(r"[{}]", " ", stripped)
            words = [w for w in stripped.split() if len(w) > 1]
            if len(words) < 10:
                stubs += 1
    return total, stubs


def check_gate1_retrieval(slug: str, guide_dir: Path) -> GateResult:
    _code, out = run_guide_audit("audit_retrieval_coverage", slug)
    match = RETRIEVAL_RE.search(out)
    pct = float(match.group(1)) if match else 0.0
    coverage_ok = pct >= 100.0

    total, stubs = count_stub_checkpoint_items(layout.chapters_dir(guide_dir))
    stubs_ok = stubs == 0

    parts = [f"coverage {pct:.1f}%" if match else "coverage unknown"]
    if total:
        parts.append(f"stubs {stubs}/{total} ({stubs / total * 100:.0f}%)")
    else:
        parts.append("stubs 0/0 (no checkpoint items)")
    if not coverage_ok:
        parts.append("< 100%")
    if not stubs_ok:
        parts.append(">0 stubs (Gold requires 0)")
    return GateResult("G1: 100% retrieval + zero checkpoint stubs",
                      coverage_ok and stubs_ok, "; ".join(parts))


# ---------------------------------------------------------------------------
# Gate 2 -- 11-audit clean.
# ---------------------------------------------------------------------------

def check_gate2_audits(slug: str) -> GateResult:
    failures: list[str] = []
    for module, flags in TEN_AUDITS.items():
        code, out = run_guide_audit(module, slug, flags)
        if NOT_FOUND_RE.search(out):
            failures.append(f"{module}: not in audit scope")
            continue
        if code != 0 or FAIL_RE.search(out):
            snippet = ""
            for line in out.splitlines():
                if line.startswith("FAIL"):
                    snippet = ": " + line.strip()[:60]
                    break
            failures.append(f"{module}{snippet}")

    # 11th audit: back_content gates on CRITICAL + HIGH == 0.
    sev = run_back_content(slug)
    if sev is None:
        failures.append("back_content: no JSON output")
    else:
        crit, high = sev.get("critical", 0), sev.get("high", 0)
        if crit or high:
            failures.append(f"back_content: {crit} CRITICAL / {high} HIGH")

    if not failures:
        return GateResult("G2: 11-audit clean (zero FAIL)", True, "all 11 clean")
    return GateResult("G2: 11-audit clean (zero FAIL)", False,
                      f"{len(failures)} failing: " + "; ".join(failures[:3]))


# ---------------------------------------------------------------------------
# Gate 3 -- per-chapter decks + complete deck + course_map.
# ---------------------------------------------------------------------------

def count_chapters(chapters_dir: Path) -> int:
    """Count authored content chapters.

    Excludes appendices (A_-F_ prefixes) and front-matter whose leading number
    is 0 (``00_how_to_use.tex``, present in ~80/81 guides) -- counting it would
    inflate the chapter count by 1 fleet-wide and mis-size G3 (required decks)
    and G4 (the >=10-chapter crossref branch).
    """
    if not chapters_dir.exists():
        return 0
    seen = set()
    for tex in chapters_dir.glob("*.tex"):
        name = tex.stem
        if name.startswith(("A_", "B_", "C_", "D_", "E_", "F_")):
            continue
        num = re.match(r"^(\d+)", name)
        if num:
            if int(num.group(1)) != 0:
                seen.add(name)  # skip 00_ front-matter
        elif re.match(r"^ch\d", name):
            seen.add(name)
    return len(seen)


def _course_map_covers_modules(course_map, chapters_dir: Path) -> tuple[bool, str]:
    """course_map must be a non-empty dict covering every ``mN`` module token in
    the chapter filenames (``NN_mN_slug.tex``). Guides without the mN convention
    fall back to the non-empty check."""
    if not isinstance(course_map, dict) or not course_map:
        return False, "empty/absent"
    modules = set()
    if chapters_dir.exists():
        for tex in chapters_dir.glob("*.tex"):
            m = re.search(r"_(m\d+)_", tex.stem)
            if m:
                modules.add(m.group(1))
    if not modules:
        return True, f"{len(course_map)} entries"
    missing = sorted(modules - {str(k) for k in course_map}, key=lambda s: int(s[1:]))
    if missing:
        return False, f"missing modules {','.join(missing)}"
    return True, f"covers {len(modules)} modules"


def check_gate3_decks(guide_dir: Path, qa: dict) -> GateResult:
    """G3: per-chapter decks + complete deck + course_map coverage.

    NOTE: this is a built-artifact check, not a live ``make decks`` invocation.
    Decks are gitignored and rebuilt on demand, so run ``make decks`` (or the
    fleet ``make decks-all``) before a Gold audit -- a clean checkout with no
    built ``.apkg`` files will fail G3 with "decks/ missing". A full live build
    per guide is intentionally out of scope for the fleet runner (the spec marks
    Gold as locally-verified, not CI-wired).
    """
    decks_dir = layout.decks_dir(guide_dir)
    chap_count = count_chapters(layout.chapters_dir(guide_dir))
    required = max(2, chap_count - 1)
    exc = get_gold_exceptions(qa)

    if not decks_dir.exists():
        return GateResult("G3: per-chapter decks + complete + course_map", False,
                          "decks/ missing (run make decks)")

    apkgs = list(decks_dir.glob("*.apkg"))
    complete = [p for p in apkgs if "complete" in p.name.lower()]
    per_chapter = [p for p in apkgs
                   if "complete" not in p.name.lower() and "appendices" not in p.name.lower()]

    anki = qa.get("anki") if isinstance(qa.get("anki"), dict) else {}
    course_map_ok, course_map_detail = _course_map_covers_modules(
        anki.get("course_map"), layout.chapters_dir(guide_dir))

    issues = []
    if not complete:
        issues.append("no complete deck")
    if not course_map_ok:
        issues.append(f"course_map {course_map_detail}")

    waived = _is_true(exc.get("decks_complete_only")) and str(exc.get("justification", "")).strip()
    if waived:
        # complete deck + course_map still required even when per-chapter is waived
        passed = not issues
        detail = (f"per-chapter waived ({str(exc.get('justification'))[:40]}); "
                  f"{len(complete)} complete, course_map {course_map_detail}")
        if issues:
            detail += " -- " + "; ".join(issues)
        return GateResult("G3: per-chapter decks + complete + course_map", passed, detail)

    if len(per_chapter) < required:
        issues.append(f"{len(per_chapter)}/{required} per-chapter decks")
    passed = not issues
    detail = (f"{len(per_chapter)} per-chapter (need {required}), {len(complete)} complete, "
              f"course_map {course_map_detail} (chapters={chap_count})")
    if issues:
        detail += " -- " + "; ".join(issues)
    return GateResult("G3: per-chapter decks + complete + course_map", passed, detail)


# ---------------------------------------------------------------------------
# Gate 4 -- size-aware crossref floor (no family detection).
# ---------------------------------------------------------------------------

def check_gate4_crossref(guide_dir: Path) -> GateResult:
    chapters_dir = layout.chapters_dir(guide_dir)
    if not chapters_dir.exists():
        return GateResult("G4: size-aware crossref floor", False, "chapters/ missing")
    chap_count = count_chapters(chapters_dir)
    total = 0
    files_with: set[str] = set()
    for tex in sorted(chapters_dir.glob("*.tex")):
        try:
            text = tex.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = len(CROSSREF_RE.findall(text))
        if found:
            total += found
            files_with.add(tex.name)

    if chap_count >= G4_LARGE_MIN_CHAPTERS:
        min_total, min_files = G4_LARGE_MIN_TOTAL, G4_LARGE_MIN_FILES
    else:
        min_total = max(2, min(4, chap_count // 4))
        min_files = max(2, min(3, chap_count // 3))

    passed = total >= min_total and len(files_with) >= min_files
    detail = (f"{total} crossrefs in {len(files_with)} files "
              f"(need {min_total}/{min_files}; chapters={chap_count})")
    if not passed:
        if total < min_total:
            detail += f" -- total < {min_total}"
        elif len(files_with) < min_files:
            detail += f" -- files < {min_files}"
    return GateResult("G4: size-aware crossref floor", passed, detail)


# ---------------------------------------------------------------------------
# Gate 5 -- source-fidelity doc (+ E/F verification section).
# ---------------------------------------------------------------------------

def strip_template_lines(text: str) -> str:
    return "\n".join(
        line for line in text.split("\n")
        if not any(sig in line for sig in SCAFFOLD_SIGNATURES)
    )


def check_gate5_fidelity(guide_dir: Path) -> tuple[GateResult, str]:
    name = "G5: source-fidelity (citations + word + E/F section)"
    audit_files = sorted(layout.review_dir(guide_dir).glob("gold_audit_*.md"))
    if not audit_files:
        return GateResult(name, False, "file missing"), "missing"
    path = audit_files[-1]
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return GateResult(name, False, "unreadable"), "missing"

    matched = [s for s in SCAFFOLD_SIGNATURES if s in text]
    if matched:
        return GateResult(name, False, f"{path.name}: scaffold-template ({len(matched)} sig)"), "scaffold"
    author = AUTHOR_RE.search(text)
    if author and author.group(1).strip() == "TBV":
        return GateResult(name, False, f"{path.name}: author=TBV"), "scaffold"

    stripped = strip_template_lines(text)
    words = len(re.findall(r"\S+", stripped))
    if words < FIDELITY_MIN_WORDS:
        return GateResult(name, False, f"{path.name}: {words} words (<{FIDELITY_MIN_WORDS})"), "short"
    citations = len(FIDELITY_CITATION_RE.findall(stripped))
    if citations < FIDELITY_MIN_CITATIONS:
        return GateResult(name, False,
                          f"{path.name}: {citations} citation marker(s) (need >={FIDELITY_MIN_CITATIONS})"), "thin_citations"
    if not EF_VERIFICATION_RE.search(text):
        return GateResult(name, False, f"{path.name}: no 'E/F source verification' section"), "no_ef_section"

    return GateResult(name, True, f"{path.name} ({words} words, {citations} citations, E/F section)"), "pass"


# ---------------------------------------------------------------------------
# Gate 6 -- dashboard zero RED.
# ---------------------------------------------------------------------------

DASHBOARD_STATUS_RE = re.compile(r"\[\s*([RYG])\s*\]")


def dashboard_red_count(guide_dir: Path) -> int:
    dash = layout.dashboard(guide_dir)
    if not dash.exists():
        return 0
    text = dash.read_text(errors="replace")
    return sum(1 for m in DASHBOARD_STATUS_RE.finditer(text) if m.group(1).upper() == "R")


def check_gate6_dashboard(guide_dir: Path, qa: dict) -> GateResult:
    if not layout.dashboard(guide_dir).exists():
        # A missing dashboard cannot be "zero RED" -- it is unverifiable. Fail
        # rather than silently pass (reachable on the single-guide --guide path,
        # which bypasses the Silver pre-filter).
        return GateResult("G6: dashboard zero RED", False, "dashboard.md missing")
    red = dashboard_red_count(guide_dir)
    exc = get_gold_exceptions(qa)
    waiver = _is_true(exc.get("dashboard_red_waiver"))
    just = str(exc.get("dashboard_red_waiver_justification", "")).strip()
    if red < G6_DASHBOARD_RED_THRESHOLD:
        return GateResult("G6: dashboard zero RED", True, f"{red} RED markers")
    if waiver and just:
        return GateResult("G6: dashboard zero RED", True, f"{red} RED waived: {just[:50]}")
    detail = f"{red} RED marker(s) (Gold requires 0)"
    if waiver and not just:
        detail += "; waiver flag set but justification empty"
    return GateResult("G6: dashboard zero RED", False, detail)


# ---------------------------------------------------------------------------
# Gate 7 -- currency appendices E/F + velocity SLA.
# ---------------------------------------------------------------------------

def _parse_e_date(text: str) -> tuple[int, int] | None:
    """Return (year, month) from the E appendix date stamp, or None."""
    m = E_DATE_ISO_RE.search(text)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:  # reject malformed stamps like "2026-00"
            return year, month
    m = E_DATE_WORD_RE.search(text)
    if m and m.group(1).lower() in _MONTHS:
        return int(m.group(2)), _MONTHS[m.group(1).lower()]
    return None


def _count_currency_items(text: str) -> int:
    return max(len(ITEM_RE.findall(text)), len(SUBSECTION_RE.findall(text)))


def _count_debates(text: str) -> int:
    """Count debates by the per-debate 'where (this|the) book sits' anchor,
    which the spec requires once per debate. Counting \\section headers instead
    would over-count framing sections (an intro or a "broader landscape"
    wrap-up) and false-PASS; all current F files carry the anchor >=6 times."""
    return len(WHERE_BOOK_RE.findall(text))


def _check_e_appendix(guide_dir: Path, qa: dict, now: datetime) -> list[str]:
    """Return a list of E-appendix failure reasons; empty == pass."""
    path = layout.appendices_dir(guide_dir) / E_FILENAME
    if not path.exists():
        return [f"{E_FILENAME} missing"]
    text = path.read_text(errors="replace")
    body = strip_template_lines(text)
    issues: list[str] = []

    currency_items = _count_currency_items(body)
    if E_STUB_RE.search(body) and currency_items < G7_MIN_CURRENCY_ITEMS:
        issues.append("E is a stub (no-changes-yet placeholder)")

    date = _parse_e_date(text)
    if date is None:
        issues.append("E has no 'current as of YYYY-MM' date")
    else:
        velocity = get_velocity(guide_dir, qa)
        max_age = VELOCITY_MAX_AGE_MONTHS[velocity]
        age = (now.year - date[0]) * 12 + (now.month - date[1])
        if age > max_age:
            issues.append(f"E age {age}mo > {velocity} SLA {max_age}mo")
        elif age < 0:
            issues.append("E date is in the future")

    if currency_items < G7_MIN_CURRENCY_ITEMS:
        issues.append(f"<{G7_MIN_CURRENCY_ITEMS} currency items")
    if not WHAT_HOLDS_RE.search(body):
        issues.append("no 'what still holds' section")

    mv = meap_version(guide_dir)
    if mv is not None:
        ver = mv.split()[0] if mv.split() else ""  # e.g. "v4" from "v4 (CloudFront ...)"
        # Enforce "names the covered version" only for a clean vN token (v1..vN).
        # Unpinned/placeholder values seen in real manifests -- TBV, TODO, n/a,
        # bare numbers, blank -- are NOT reliably enforceable here (an empty token
        # would \b-match everywhere; a bare "6" would match any "6" in prose), so
        # they are skipped. The version<->date tie lands with the MEAP-freshness
        # checker (roadmap T4), which carries clean version data.
        if re.fullmatch(r"v\d+", ver, re.IGNORECASE):
            if not re.search(rf"(?i)\b{re.escape(ver)}\b", body):
                issues.append(f"E does not name MEAP version ({ver})")
    return issues


def _check_f_appendix(guide_dir: Path, qa: dict) -> list[str]:
    exc = get_gold_exceptions(qa)
    if _is_true(exc.get("debates_waiver")) and str(exc.get("debates_waiver_justification", "")).strip():
        return []  # waived
    path = layout.appendices_dir(guide_dir) / F_FILENAME
    if not path.exists():
        return [f"{F_FILENAME} missing"]
    text = strip_template_lines(path.read_text(errors="replace"))
    issues: list[str] = []
    debates = _count_debates(text)
    if debates < G7_MIN_DEBATES:
        issues.append(f"<{G7_MIN_DEBATES} debates ({debates})")
    if len(VERDICT_RE.findall(text)) < G7_MIN_DEBATES:
        issues.append("missing verdict flags (well-supported/contested/dated)")
    # Cited-Contested: every debate's Positions must carry resolvable citations.
    live = _strip_tex_comments(text)
    cites = sum(len(rx.findall(live)) for rx in F_CITE_RES)
    cite_floor = max(G7_F_CITE_FLOOR, 2 * debates)
    if cites < cite_floor:
        issues.append(f"<{cite_floor} resolvable citations ({cites})")
    return issues


def check_gate7_currency(guide_dir: Path, qa: dict, now: datetime) -> GateResult:
    e_issues = _check_e_appendix(guide_dir, qa, now)
    f_issues = _check_f_appendix(guide_dir, qa)
    exc = get_gold_exceptions(qa)
    f_waived = _is_true(exc.get("debates_waiver")) and str(exc.get("debates_waiver_justification", "")).strip()

    passed = not e_issues and not f_issues
    if passed:
        detail = "E ok; F " + ("waived" if f_waived else "ok")
    else:
        parts = []
        parts.append("E: " + ("; ".join(e_issues) if e_issues else "ok"))
        parts.append("F: " + ("; ".join(f_issues) if f_issues else ("waived" if f_waived else "ok")))
        detail = " | ".join(parts)
    return GateResult("G7: currency appendices E/F", passed, detail)


# ---------------------------------------------------------------------------
# Gate B (opt-in) -- a fresh 2-pass build that emits a clean log.
# ---------------------------------------------------------------------------
# audit_gold is otherwise STATIC -- it never compiles the PDF, so a guide with a
# real LaTeX build-breaker (e.g. a raw ``&`` in a bib author field) can still
# clear G1-G7. ``--build`` adds this hard gate: it runs ``make ... digital`` and
# scans ``main_digital.log`` with the shared, file:line:error-aware error regex.

def check_gate_build(guide_dir: Path) -> GateResult:
    """GB: fresh 2-pass ``make digital`` with a clean ``main_digital.log``."""
    from tooling.qa.guide_readiness import _LATEX_ERROR_RE
    guide_sub = guide_dir / "guide"
    name = "GB: clean 2-pass build"
    if not (guide_sub / "Makefile").exists() and not (guide_sub / "main.tex").exists():
        return GateResult(name, False, "no buildable guide/ (Makefile/main.tex missing)")
    proc = subprocess.run(
        ["make", "-C", str(guide_sub), "digital"],
        cwd=str(paths.host_root()), capture_output=True, text=True,
    )
    log = guide_sub / "main_digital.log"
    err_lines = (
        [ln.strip() for ln in log.read_text(errors="replace").splitlines()
         if _LATEX_ERROR_RE.match(ln)]
        if log.exists() else []
    )
    if proc.returncode == 0 and not err_lines:
        return GateResult(name, True, "rc=0; 0 LaTeX errors")
    parts = [f"rc={proc.returncode}"]
    if err_lines:
        parts.append(f"{len(err_lines)} error(s); e.g. {err_lines[0][:70]!r}")
    elif proc.returncode != 0:
        parts.append("build rc!=0 (see main_digital.log)")
    return GateResult(name, False, "; ".join(parts))


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------

def audit_guide_gold(guide_dir: Path, now: datetime, build: bool = False) -> HonestReport:
    slug = guide_dir.name
    qa = load_guide_qa(guide_dir)
    report = HonestReport(slug=slug)
    report.gates.append(check_gate1_retrieval(slug, guide_dir))
    report.gates.append(check_gate2_audits(slug))
    report.gates.append(check_gate3_decks(guide_dir, qa))
    report.gates.append(check_gate4_crossref(guide_dir))
    g5, reason = check_gate5_fidelity(guide_dir)
    report.gates.append(g5)
    report.g5_reason = reason
    report.gates.append(check_gate6_dashboard(guide_dir, qa))
    report.gates.append(check_gate7_currency(guide_dir, qa, now))
    if build:  # opt-in hard gate; audit_gold is static unless --build is passed
        report.gates.append(check_gate_build(guide_dir))
    return report


def filter_silver_pass(guide_dirs: list[Path]) -> list[Path]:
    """Restrict a fleet run to Silver-PASS guides (via the tooling Silver audit)."""
    from tooling.audits.fleet.audit_silver import audit_guide as silver_audit
    out = []
    for gd in guide_dirs:
        try:
            if silver_audit(gd).get("silver_pass"):
                out.append(gd)
        except Exception as exc:  # noqa: BLE001 -- a broken guide must not abort the fleet
            print(f"Warning: Silver audit error for {gd.name}: {exc!r}", file=sys.stderr)
            continue
    return out


# ---------------------------------------------------------------------------
# Reporting.
# ---------------------------------------------------------------------------

_SYMBOL = {"PASS": "GOLD", "SCAFFOLD-ONLY": "SCFLD", "GOLD-ELIGIBLE": "ELIG", "FAIL": "FAIL"}


def print_report(reports: list[HonestReport], meta: dict[str, str], verbose: bool) -> None:
    print("=" * 78)
    print(f"Audit run:  {meta['timestamp_utc']}")
    print(f"Git SHA:    {meta['sha']} (dirty: {meta['dirty']})")
    print(f"Gold audit -- {len(reports)} guide(s) evaluated")
    print("=" * 78)
    counts = {"PASS": 0, "SCAFFOLD-ONLY": 0, "GOLD-ELIGIBLE": 0, "FAIL": 0}
    for r in reports:
        counts[r.classification] += 1
        print(f"  [{_SYMBOL[r.classification]:5}] {r.slug}")
        if verbose or r.classification != "PASS":
            for g in r.gates:
                print(f"            {'PASS' if g.passed else 'FAIL'}  {g.name}: {g.detail}")
    print("=" * 78)
    print(f"Summary: {counts['PASS']} Gold, {counts['SCAFFOLD-ONLY']} scaffold-only, "
          f"{counts['GOLD-ELIGIBLE']} gold-eligible, {counts['FAIL']} fail")
    print("=" * 78)


def write_markdown_report(reports: list[HonestReport], meta: dict[str, str]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    path = REPORTS_DIR / f"qa_gold_{today}.md"
    counts = {"PASS": 0, "SCAFFOLD-ONLY": 0, "GOLD-ELIGIBLE": 0, "FAIL": 0}
    for r in reports:
        counts[r.classification] += 1
    lines = [
        f"# Gold Fleet Audit -- {today}",
        "",
        f"**Audit run**: {meta['timestamp_utc']}",
        f"**Git SHA**: `{meta['sha']}` (dirty: {meta['dirty']})",
        "",
        "Generated by `tooling.audits.fleet.audit_gold` (7-gate Gold; see "
        "`tooling/standards/tier_model.md` §Gold).",
        "",
        f"**Summary**: {counts['PASS']} Gold / {counts['SCAFFOLD-ONLY']} SCAFFOLD-ONLY / "
        f"{counts['GOLD-ELIGIBLE']} GOLD-ELIGIBLE / {counts['FAIL']} FAIL "
        f"(total {sum(counts.values())})",
        "",
        "| Guide | Class | G1 | G2 | G3 | G4 | G5 | G6 | G7 |",
        "|-------|-------|----|----|----|----|----|----|----|",
    ]
    for r in reports:
        # Pad/truncate to 7 gate cells so an error row (a single "G0" gate) still
        # fills the 7-column table rather than producing a ragged 3-cell row.
        cells = [("PASS" if g.passed else "FAIL") for g in r.gates]
        cells = (cells + ["—"] * 7)[:7]
        lines.append("| " + " | ".join([r.slug, r.classification, *cells]) + " |")
    path.write_text("\n".join(lines) + "\n")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--guide", help="Audit a single guide by slug")
    ap.add_argument("--verbose", action="store_true", help="Per-gate detail for all guides")
    ap.add_argument("--report", action="store_true", help="Write markdown report to reports/")
    ap.add_argument("--build", action="store_true",
                    help="Add gate GB: a fresh 2-pass `make digital` with a clean log "
                         "(audit_gold is static without this). Slow; compiles each guide.")
    args = ap.parse_args()

    if args.guide:
        from tooling.audits.guide._guide_scope import guide_dir_for_slug
        gd = guide_dir_for_slug(args.guide)
        if gd is None:
            print(f"Error: guide '{args.guide}' not found", file=sys.stderr)
            sys.exit(1)
        targets = [gd]
    else:
        targets = filter_silver_pass(discovery.iter_guide_dirs())

    now = datetime.now()
    meta = git_metadata()
    reports = []
    for gd in targets:
        try:
            reports.append(audit_guide_gold(gd, now, build=args.build))
        except Exception as exc:  # noqa: BLE001 -- one bad guide must not abort the fleet
            r = HonestReport(slug=gd.name)
            r.gates.append(GateResult("G0: audit error", False, f"{type(exc).__name__}: {exc}"))
            reports.append(r)
    print_report(reports, meta, verbose=args.verbose)

    if args.report:
        print(f"\nReport saved: {write_markdown_report(reports, meta)}")

    if not args.guide and any(
        r.classification in ("FAIL", "SCAFFOLD-ONLY") for r in reports
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
