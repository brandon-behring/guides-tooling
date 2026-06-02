# Learning Outcomes (LOS)

Canonical taxonomy of cognitive levels used in `\los{ID}{level}{statement}`
across all guides. Single source of truth (machine-readable mirror at
`shared/config/canonical_values.yaml`).

## The 10 cognitive levels

| Level | Bloom's mapping | Description | Example |
|-------|----------------|-------------|---------|
| `define` | Remember | Recall a definition or term | "Define CUPED variance reduction" |
| `explain` | Understand | Articulate a concept in your own words | "Explain why DPO does not need a separate reward model" |
| `calculate` | Apply | Compute a result from given inputs | "Calculate the required sample size for 80% power, MDE=0.02, baseline=0.1" |
| `compare` | Analyze | Identify similarities and differences | "Compare DPO and PPO in terms of training stability and hyperparameter sensitivity" |
| `analyze` | Analyze | Decompose to identify components and relationships | "Analyze the variance contributions to a CUPED-adjusted treatment effect estimate" |
| `evaluate` | Evaluate | Make a judgment with reasoned criteria | "Evaluate whether a 0.5pp lift in retention justifies the cost of personalization infra" |
| `design` | Create | Construct a plan or system | "Design an A/B test framework for a feature with cross-user spillover risk" |
| `apply` | Apply | Use a method in a new situation | "Apply the SRM debug order to a campaign showing 51%/49% bucket imbalance" |
| `debug` | Apply / Analyze (hybrid) | Locate and fix a defect | "Debug a transformer training loss curve that suddenly diverges at step 10K" |
| `trace` | Apply / Understand (hybrid) | Walk through execution / derivation step by step | "Trace gradient flow through a single attention block during backpropagation" |

These 10 levels are the **canonical valid set** for every guide's
`guide_qa.yaml.los.valid_levels` field. A guide may restrict to a subset, but
should not invent new levels — that breaks fleet audits.

## Per-chapter targets

| Family | LOS per chapter (universal) | Calibration in overlay |
|--------|----------------------------|------------------------|
| Manning | 6-8 | as-is |
| DLAI short course | 4-6 | calibrated down (shorter courses) |
| Coursera multi-course | 6-8 | as-is |
| Other | 6-8 | per `99_other/overlay.md` |

Total LOS per guide is set in `guide_qa.yaml.metrics.los_count.target`. Common
ranges: Manning 60-90, DLAI 20-50, Coursera 100-150. See
[`quality_targets.md`](quality_targets.md) for the full table.

## LOS macro signature

```latex
\los{ID}{level}{Statement of what the learner can do}
```

- `ID`: stable identifier, prefix matches `guide_qa.yaml.los.prefix`
  (e.g., `TRB-3.2` for Manning RLHF Book chapter 3 LOS 2). Must be unique
  per guide.
- `level`: one of the 10 above. Validated by
  `shared/validation/extract_los.py --validate`.
- `Statement`: action verb (matching the level) + object + condition. Avoid
  "understand" / "know" — prefer the explicit cognitive verbs above.

The macro lives in `shared/latex/los-macros.sty` (originally line 45 had a
comment listing only 7 levels; updated 2026-04-19 to enumerate all 10).

## LOS-to-card traceability

Every chapter must include enough retrieval opportunities (problem, vignette,
drill, checkpoint, interview cards) to test every defined LOS. The
`audit_retrieval_coverage.py` script measures this; 100% is the target.
Authors link cards to LOS via the optional `[LOS-ID]` parameter on most card
macros — see [`card_standards.md`](card_standards.md).

## When to restrict the valid set

A guide may set `valid_levels: [define, explain, apply]` (subset of the 10) if:
- The course is reference-style (e.g., a glossary book) and `evaluate`/`design`
  don't apply.
- The author wants stricter Bloom's discipline and chooses to enforce it via
  audit failure on out-of-set levels.

Restricting is fine. Inventing new levels is not.

## Anti-patterns

- "understand X" → not a level. Replace with `explain` or `apply`.
- "know X" → not a level. Replace with `define`.
- "be familiar with X" → not measurable. Reframe as `define` or `explain`.
- LOS without a stable ID → audit failure.
- LOS prefix mismatched to `guide_qa.yaml.los.prefix` → audit failure.

## Reference

- Macro: `shared/latex/los-macros.sty` (line 45 comment lists all 10 as of
  2026-04-19).
- Validation: `shared/validation/extract_los.py --validate`.
- Per-guide config: `guide_qa.yaml.los.{prefix,valid_levels}`.
- Machine-readable: `shared/config/canonical_values.yaml` (`bloom_levels` key).
- Bloom mapping authority: this file is the canonical mapping; if you need
  the full Bloom's taxonomy, consult an external source — this repo only
  cares about the 10 verbs above.
