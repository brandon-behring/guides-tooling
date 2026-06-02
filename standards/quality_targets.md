# Quality Targets

Single canonical metric table. Consolidates and supersedes the Manning gold
spec §7 table and the `.claude/rules/content-quality.md` Quality Metrics
table. Per-guide overrides live in `guide_qa.yaml.metrics`.

## Universal targets

| Dimension | Universal target | Red flag | Notes |
|-----------|-----------------|----------|-------|
| LOS per chapter (normal) | 6-8 | 0 or >12 | Family overlays may calibrate (DLAI 4-6) |
| Total LOS per guide | calibrated per guide | — | Manning 60-90, DLAI 20-50, Coursera 100-150 |
| Retrieval coverage | 100% of defined LOS | <90% | `audit_retrieval_coverage.py` |
| Margin density (per chapter) | content-driven floor, not a cap (theory 8-14+, framework 14-22+, code-heavy 5-10+) | 0, or 30+ theory / 20+ code-heavy | `audit_margin_quality.py` |
| Margin density (per section) | 2-3 typical; **no substantive section left bare** | 5+ | `audit_margin_quality.py` |
| Key concepts per chapter | 2-4 | 0 or 8+ | `audit_content_quality.py` |
| Problems per guide | 15+ | <5 | Plus enough for 100% LOS coverage |
| Vignettes per guide | 3+ where applicable | 0 (when applicable) | Skip if guide has no scenario-design content |
| Glossary terms | 1.5 × chapter count × 8 | calibrated per guide | E.g., 17 chapters × 1.5 × 8 ≈ 200; RLHF target = 170 |
| Bibliography entries | sufficient for cited sources | inadequate citation density | Per-guide judgment |
| Build status | clean PDF, no blocking refs | latex errors, missing refs | `qa-build`, `qa-refs` |
| Visible LaTeX overflow (>=50pt) | 0 | 5+ | `check_latex_warnings.py` |
| Generic content phrases | 0 | any | "important concept", "be careful", etc. |
| Interview contexts per guide | 5+ | 0 | `\begin{interviewcontext}...` boxes |

## Card-level targets

| Metric | Universal target | Notes |
|--------|-----------------|-------|
| LOS traceability | 100% for learning-objective cards | `audit_card_quality.py` |
| Thin cards | <5% | `audit_atomicity.py` |
| Term-card ratio | <60% | Cards should not be dominated by definitions |
| Broken LaTeX | 0 | `audit_card_presentation.py` |
| ID collisions | 0 | `extract_cards.py` `seen_ids` |
| Solution completeness | 100% for problem and vignette cards | `audit_solution_quality.py` |

## Per-family calibration

Family overlays may calibrate the *thresholds* (not the *gates*). For
example:

- **Manning**: page count 150-200, total LOS 60-90.
- **DLAI short course**: page count 60-100, LOS per chapter 4-6, total LOS
  20-50.
- **Coursera multi-course**: page count 300-400, total LOS 100-150.
- **Other** (`99_other/`): per the guide's source manifest; no fixed default.

Calibration is set in `guide_qa.yaml.metrics`, not in the family overlay
text. Overlays document the *shape* of the calibration, not the exact
numbers.

## How to read a per-guide dashboard

`docs/review/dashboard.md` per guide shows traffic-light status against the
guide's `guide_qa.yaml.metrics` thresholds.

- **GREEN**: at or above target.
- **YELLOW**: between yellow and target (if `inverted: false`) or between
  target and yellow (if `inverted: true`).
- **RED**: outside the yellow threshold.

Inverted metrics (e.g., `latex_overflow_visible`) are GREEN when *low* and
RED when *high*.

## When to recalibrate

A per-guide target may be recalibrated when:
- The guide's source has structurally fewer or more chapters than the
  universal default (document the rationale in the source manifest).
- Page count is not comparable to the source page count (e.g., notebook
  formatting differs from book formatting).
- Glossary target is constrained by source vocabulary (some books have very
  few defined terms; calibrate down with rationale).

Recalibration is recorded in `guide_qa.yaml` and explained in the source
manifest. **Avoid silent recalibration** — it makes fleet comparisons
meaningless.

## Reference

- Per-guide config: each `guide_qa.yaml`.
- Template: `shared/templates/guide_qa.yaml.template`.
- Audit scripts: [`audit_catalog.md`](audit_catalog.md).
- Worked examples: `manning_rlhf_book/guide_qa.yaml` (full),
  `manning_llm_from_scratch/guide_qa.yaml` (with optional supplement
  coverage).
