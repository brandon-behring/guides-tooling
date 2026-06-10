# Audit Catalog

The full set of audit and validation tooling — the **11 per-guide audit
scripts** plus all validation, build, and fleet-level commands.

**Gold G2 gates on all 11 audits.** The eleven `audit_*.py` scripts are
`atomicity`, `back_content`, `card_presentation`, `card_quality`,
`content_freshness`, `content_quality`, `crossref_quality`, `margin_quality`,
`retrieval_coverage`, `solution_quality`, and `term_consistency`. Two were
historically miscounted as outside the suite: `audit_atomicity` was advisory
until promoted to Gold-blocking on 2026-04-24, and `audit_back_content` has
always existed in the audits directory but was never wired into Gold — both are
now part of the G2 set, so the true count is **11, not 10**. The eleven names
here must match the G2 list in [`tier_model.md`](tier_model.md) §Gold exactly.

### Content & retrieval

| Script | Measures |
|--------|----------|
| `audit_content_quality.py` | Margin density per chapter; keyconcept count; problems / vignettes / drills per chapter |
| `audit_retrieval_coverage.py` | Percentage of `\los{}` with at least one retrieval opportunity (problem / vignette / drill / checkpoint / interview card) |
| `audit_margin_quality.py` | Per-category usage; generic-content detection (e.g., "important concept" / "be careful"); word count per note; density compliance |
| `audit_solution_quality.py` | Solution completeness (Approach / Key Insight / Answer sections present); vignette rubric coverage |

### Cards

| Script | Measures |
|--------|----------|
| `audit_card_quality.py` | Back-length distribution; broken LaTeX; ID collisions; type distribution; LOS traceability |
| `audit_back_content.py` | Card-back substance: empty / near-empty backs, front↔back duplication (Jaccard ≥0.85), stub answers, structure-less backs. Grades on **CRITICAL / HIGH / MEDIUM / INFO** severities; Gold G2 gates on **zero CRITICAL + zero HIGH** (MEDIUM/INFO advisory). The one severity-graded audit — the other ten are binary `FAIL`/pass. |
| `audit_card_presentation.py` | LaTeX rendering correctness; MathJax conversion (`$...$` → `\(...\)`); formatting (run-on lists, inline headers) |
| `audit_atomicity.py` | Card granularity (atomic / borderline / compound); emits `FAIL <guide>: N compound card(s)` when any compound cards present, which Gold G2 catches via `FAIL_RE`. **Gold-blocking** as of 2026-04-24 per `tier_model.md` §Gold. Use `--check` for an exit-code signal in CI. |
| `audit_term_consistency.py` | Duplicate or conflicting term definitions across chapters (e.g., "CUPED" defined twice with different wording) |

### References

| Script | Measures |
|--------|----------|
| `audit_crossref_quality.py` | Internal `\ref{}` validity; external `\crossrefmargin{}` path validity; orphaned guides |
| `audit_content_freshness.py` | Dated content detection; flags references to versions/models that may be stale |

### Suppressing intentional "stale" references

`audit_content_freshness` flags model/version mentions by regex (e.g., `Llama 2`,
`gpt-4-turbo`). In historical/pedagogical guides, some references are
intentional and factually correct — rewriting them to the "current" name
would be wrong (for example, `Llama 2` is the specific model that introduced
the preference-margin loss that `Llama 3` explicitly dropped).

Two mechanisms exist to suppress such findings:

- **Per-line annotation**: append `% freshness-ok` to the offending LaTeX
  source line. The audit skips any line containing that marker. Use this
  for targeted historical references (e.g., `\subsection{Preference Margin
  Loss (Llama 2, 2023)} % freshness-ok`).
- **`\warningmargin{…}` blocks**: lines inside a `\warningmargin` invocation
  are skipped, because the macro's purpose is to explicitly call out a
  deprecated pattern.

Prefer `% freshness-ok` for attribution in body text; prefer `\warningmargin`
when the deprecated name is being used as a cautionary example.

## Validation scripts (`shared/validation/`)

Lower-level checks consumed by the Makefile QA targets.

| Script | Purpose | Wired into Makefile target |
|--------|---------|----------------------------|
| `check_refs.py` | Cross-reference validation (internal labels, phantom labels) | `qa-refs` |
| `check_latex_warnings.py` | LaTeX overflow detection (Overfull hbox >=50pt); JSON output for dashboard | `qa-presentation` |
| `extract_los.py` | LOS definition extraction & validation against `valid_levels` | `qa-los` |
| `check_duplicates.py` | Duplicate chapter / card detection | `qa-cards` (part of) |

## Per-guide Makefile QA targets

Standard across guides; defined in each guide's `notes/notebook/Makefile`.

| Target | Action |
|--------|--------|
| `pilot` | Single-pass `lualatex` build |
| `digital` | Full multi-pass `latexmk` (with index/bib) |
| `print` | Print-mode latexmk variant |
| `cards` | `extract_cards.py` on all chapter `.tex` files |
| `decks` | `yaml_to_apkg.py` with `--config guide_qa.yaml` |
| `clean` | Remove aux/log/index/minted temp files |
| `qa` | Chained: `qa-build`, `qa-refs`, `qa-los`, `qa-cards`, `qa-presentation` |
| `qa-build` | Pilot build to test LaTeX |
| `qa-refs` | `check_refs.py` validation |
| `qa-los` | `extract_los.py --validate` |
| `qa-cards` | Card extraction with `--validate` flag |
| `qa-presentation` | `check_latex_warnings.py` on the build log |
| `qa-health` | `guide_health.py` traffic-light dashboard |
| `qa-ready` | `guide_readiness.py` blocking-failure check |

## Fleet-level audit

```bash
python3 scripts/audit_all_courses.py --summary
```

- Discovers courses by walking the repo for `guide_qa.yaml` files (118 today).
- Runs the 9-point structural checklist (see [`tier_model.md`](tier_model.md)
  §Bronze).
- Writes a fresh `reports/qa_fleet_audit_<YYYYMMDD>.md`.
- Per the lifecycle policy ([`document_lifecycle.md`](document_lifecycle.md)),
  only the most recent fleet audit is kept; older ones should be `git rm`'d
  on each new run. (Update to the audit script to do this automatically is
  a follow-up.)

The script supports `--help` and `--summary` only as of 2026-04-19. There is
no `--dry-run` flag (an old standards doc claimed there was; that was
incorrect and is now corrected).

### Gold fleet audit (separate script)

```bash
python3 scripts/audit_gold.py                # all Silver-PASS guides
python3 scripts/audit_gold.py --guide <slug>
python3 scripts/audit_gold.py --verbose      # per-gate detail
python3 scripts/audit_gold.py --report       # writes reports/qa_gold_<DATE>.md
```

The legacy `scripts/audit_gold_fleet.py` is retained for historical
comparison but its Gate 5 (file-exists) is too permissive; invoking it
prints a runtime stderr deprecation banner. Use `audit_gold.py`.

Gold classification runs in a separate script from the Bronze + Silver
fleet audit because it invokes the full 11-audit suite (all eleven
`audit_*.py` scripts per `tier_model.md` §Gold), which is too expensive
to run on every Bronze sweep. Only Silver-PASS guides are evaluated
(Bronze or Silver-FAIL guides are not Gold-eligible).

Per-guide classification:

- `PASS` — all seven Gold gates (G1–G7) pass on the current checkout.
- `SCAFFOLD-ONLY` — auto gates pass but the G5 source-fidelity doc is a
  template scaffold (scaffold signatures / author-"TBV" placeholders).
- `GOLD-ELIGIBLE` — auto gates pass but the G5 doc is missing entirely.
- `FAIL` — any of G1–G7 fails.

There is a single Gold tier (the former manual-attestation sub-tier is
retired per `tier_model.md` §Gold). **Runner status:** G7 (the E/F
currency appendices) and the `back_content` severity gate are part of the
Gold *standard* as of this definition; the runner port that implements
them is roadmap T2 — until it lands, the live runner checks G1–G6 over the
original ten binary audits.

The Gold report header now includes git SHA + dirty status + UTC
timestamp so saved reports can be checked against the checkout that
generated them. See `manning_rlhf_book/docs/review/gold_audit_20260420.md`
for the canonical G5 template.

## guide_qa.yaml schema

Required fields per guide. Authoritative template at
`shared/templates/guide_qa.yaml.template`.

```yaml
guide:
  name: "Guide Display Name"
  version: "1.0"
  guide_dir: "notes/notebook"
  chapters_glob: "notes/notebook/chapters/*.tex"
  appendices_glob: "notes/notebook/appendices/*.tex"
  review_dir: "docs/review"
  build_cmd: "make -C notes/notebook pilot"
  full_build_cmd: "make -C notes/notebook digital"

los:
  prefix: "TRB"          # Unique per guide
  valid_levels: [define, explain, calculate, compare, analyze, evaluate, design, apply, debug, trace]

metrics:
  los_count:
    description: "Learning Outcomes defined"
    target: 136
    yellow: 102
    check_cmd: "..."
  glossary_count: { ... }
  bib_count: { ... }
  page_count: { ... }
  latex_overflow_visible: { ... }
  # Optional metrics:
  card_count: { ... }
  card_los_traceability_pct: { ... }
  supplement_concept_coverage_pct: { ... }   # If guide has a supplement

anki:                    # See card_standards.md for full schema
  deck_prefix: "..."
  separator: "::"
  source_pattern: "(m\\d+)_"
  course_key_prefix: ""
  course_map: { ... }

readiness_checks:
  - name: "LaTeX Build"
    blocking: true
    cmd: "..."
  # ...
```

A guide is **Bronze** when this schema is present and audit checks pass; see
[`tier_model.md`](tier_model.md).

## Adding a new audit script

1. Drop the script in `shared/audits/audit_<name>.py` following the existing
   pattern (CLI: `--guide <slug>` for single, `--all` for fleet).
2. Add a row to the table above.
3. Add the script name to `shared/config/canonical_values.yaml`
   (`audit_scripts` key).
4. Wire into a Makefile QA target if it's per-guide.
5. Reference from `tier_model.md` if it gates a tier.

## Hub vs local

Validation scripts referenced by per-guide `guide_qa.yaml` paths point at
`~/Claude/lever_of_archimedes/tools/guide_qa/validation/*.py` (the upstream
hub). Local `shared/validation/` mirrors the hub. Sync via
`scripts/sync_from_hub.sh`.

The 4 newer audit scripts (`audit_atomicity`, `audit_card_presentation`,
`audit_term_consistency`, `audit_content_freshness`) may not be in the hub
yet; reconciliation with the hub is a deferred follow-up.

## Reference

- All audits: `ls shared/audits/audit_*.py`
- All validations: `ls shared/validation/`
- Sync script: `scripts/sync_from_hub.sh`
- Fleet audit: `scripts/audit_all_courses.py`
- Machine-readable list: `shared/config/canonical_values.yaml`
  (`audit_scripts` key)
