# Audit Catalog

The full set of audit and validation tooling — the **11 per-guide audit
scripts** plus all validation, build, and fleet-level commands. (This catalogs
the per-guide suite by name + semantics; the code ports to
`tooling.audits.guide.*` in roadmap T1 and currently lives in the old
`course_learning` repo.)

**Gold G2 gates on all 11 audits.** The eleven `audit_*.py` scripts are
`atomicity`, `back_content`, `card_presentation`, `card_quality`,
`content_freshness`, `content_quality`, `crossref_quality`, `margin_quality`,
`retrieval_coverage`, `solution_quality`, and `term_consistency`. The count
moved from 10 to 11 because `audit_back_content` — which has always existed in
the audits directory but was never wired into Gold — is now gated; it is the one
genuinely new member. (`audit_atomicity` was *already* in the gated set; on
2026-04-24 it was promoted from advisory to Gold-blocking, but it was not newly
added — do not re-wire it.) The eleven names here must match the G2 list in
[`tier_model.md`](tier_model.md) §Gold exactly.

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
| `audit_back_content.py` | Card-back substance: empty / near-empty backs, front↔back duplication (Jaccard ≥0.85), stub answers, structure-less backs. Grades on **CRITICAL / HIGH / MEDIUM / INFO** severities; Gold G2 gates on **zero CRITICAL + zero HIGH** (MEDIUM/INFO advisory). The one severity-graded audit — the other ten are binary `FAIL`/pass. **Runner contract (T2):** it emits severity-tagged findings, **not** `FAIL` lines, so the Gold runner must gate on parsed CRITICAL/HIGH counts (or a `--fail-on high` exit code) — `FAIL_RE` alone would silently always-pass. Its CLI flag is `--guides` (not `--guide`). |
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

## Validation scripts (`tooling.validation`)

Lower-level checks consumed by the Makefile QA targets, each runnable as
`python3 -m tooling.validation.<module>`.

| Script | Purpose | Wired into Makefile target |
|--------|---------|----------------------------|
| `check_refs.py` | Cross-reference validation (internal labels, phantom labels) | `qa-refs` |
| `check_latex_warnings.py` | LaTeX overflow detection (Overfull hbox >=50pt); JSON output for dashboard | `qa-presentation` |
| `extract_los.py` | LOS definition extraction & validation against `valid_levels` | `qa-los` |
| `check_duplicates.py` | Duplicate chapter / card detection | `qa-cards` (part of) |

## Per-guide Makefile QA targets

Standard across guides; defined in each guide's `guide/Makefile`.

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
make audit-all                                       # or:
python3 -m tooling.audits.fleet.audit_all_courses --summary
```

- Discovers courses by walking the repo for `guide_qa.yaml` files (83 today).
- Runs the 10-point structural checklist (see [`tier_model.md`](tier_model.md)
  §Bronze; check 10 = stub-free includes).
- Writes a fresh `reports/qa_fleet_audit_<YYYYMMDD>.md`.
- Per the lifecycle policy ([`document_lifecycle.md`](document_lifecycle.md)),
  only the most recent fleet audit is kept; older ones should be `git rm`'d
  on each new run. (Update to the audit script to do this automatically is
  a follow-up.)

The script supports `--summary`, `--tier {bronze,silver,all}` (default `all`),
and `--strict` (CI gate); there is no `--dry-run` flag.

### Gold fleet audit (separate runner)

Gold classification runs as a separate runner from the Bronze + Silver
fleet audit because it invokes the full 11-audit suite (all eleven
`audit_*.py` scripts per `tier_model.md` §Gold), which is too expensive
to run on every Bronze sweep. **No in-repo Gold runner exists yet** —
Gold cannot be verified live in `guides-manning` today. The runner is
roadmap **T2**, landing as `tooling.audits.fleet.audit_gold` behind a
`make audit-gold` target:

```bash
make audit-gold                                       # all Silver-PASS guides (T2)
python3 -m tooling.audits.fleet.audit_gold --guide <slug>
python3 -m tooling.audits.fleet.audit_gold --verbose  # per-gate detail
python3 -m tooling.audits.fleet.audit_gold --report   # writes reports/qa_gold_<DATE>.md
```

Until T2 lands, the Gold runner source lives in the old `course_learning`
monorepo (as `scripts/audit_gold.py`, covering G1–G6 only) and is not
runnable from this repo. Only Silver-PASS guides are evaluated
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
them is roadmap T2 — until it lands, the legacy `course_learning` runner
covers G1–G6 over the original ten binary audits (and is not runnable here).

The Gold report header now includes git SHA + dirty status + UTC
timestamp so saved reports can be checked against the checkout that
generated them. See
`evaluation-alignment-safety/manning_rlhf_book/review/gold_audit_20260420.md`
for the canonical G5 template (it exemplifies the original G5 sections only;
G5's new "E/F source verification" section is not yet exemplified there).

## guide_qa.yaml schema

Required fields per guide. Authoritative template at
`tooling/templates/guide_qa.yaml.template`.

```yaml
guide:
  name: "Guide Display Name"
  version: "1.0"
  guide_dir: "guide"
  chapters_glob: "guide/chapters/*.tex"
  appendices_glob: "guide/appendices/*.tex"
  review_dir: "review"
  build_cmd: "make -C guide pilot"
  full_build_cmd: "make -C guide digital"

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

1. Drop the script in `tooling/audits/guide/audit_<name>.py` (per-guide) or
   `tooling/audits/fleet/audit_<name>.py` (fleet), following the existing
   pattern (CLI: `--guide <slug>` for single, `--all` for fleet).
2. Add a row to the table above.
3. Add the script name to `tooling/config/canonical_values.yaml`
   (`audit_scripts` key).
4. Wire into a Makefile QA target if it's per-guide.
5. Reference from `tier_model.md` if it gates a tier.

## Reference

- All fleet audits: `ls tooling/audits/fleet/audit_*.py`
  (the per-guide `tooling/audits/guide/` suite lands with roadmap T1)
- All validations: `ls tooling/validation/`
- Fleet audit: `make audit-all` (`tooling.audits.fleet.audit_all_courses`)
- Machine-readable list: `tooling/config/canonical_values.yaml`
  (`audit_scripts` key)
