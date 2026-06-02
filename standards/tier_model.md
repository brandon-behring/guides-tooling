# Tier Model

Three-tier readiness model for course-learning guides. Replaces the
binary "gold-standard or not" framing in the previous Manning gold spec.

## Tiers

### Bronze — passes the structural baseline

A guide is Bronze when `python3 scripts/audit_all_courses.py --summary`
shows it at **9/9 GREEN** on the 9-point structural checklist:

1. `guide_qa.yaml` present and valid.
2. Validation symlinks at `scripts/validation/{check_refs,check_duplicates,extract_los,check_latex_warnings}.py`.
3. Makefile QA targets (`qa`, `qa-build`, `qa-refs`, `qa-los`, `qa-cards`, `qa-presentation`).
4. `notebook-extensions.sty` present.
5. Cards extracted (at least one `cards/*.yml`).
6. Anki deck (`decks/*.apkg`) present or explicitly documented as absent.
7. `docs/review/dashboard.md` present.
8. Bloom's levels in `guide_qa.yaml.los.valid_levels` match the canonical 10
   in [`learning_outcomes.md`](learning_outcomes.md) (or are a documented subset).
9. No hardcoded paths in audit scripts or Makefile (use the validation
   symlinks).

Today (2026-04-21): **118 / 118** active guides are Bronze 9/9
(was 115/118 on 2026-04-19; the gap was closed by a fleet-wide
`make decks` run after patching 38 Makefiles that lacked the
`decks:` target).

### Silver — verified and contextualized

Bronze plus:

- **Source manifest** scaffolded and verified (`docs/review/source_manifest.md`).
  Today provisional — `scripts/scaffold_source_manifest.py` is a deferred
  follow-up. Until it lands, an existing manifest counts; absence does not
  block Silver retroactively (this is a forward-looking gate).
- **Real Appendix D** — at least 5 conceptual questions with expected-answer
  points, role/level deltas (IC4 vs IC5+/Staff), cross-references to
  chapters via LOS IDs, and — for any guide on the
  [`system_design_allowlist.yaml`](system_design_allowlist.yaml) — at least
  one system/design scenario section. A stub Appendix D fails Silver. See
  [`interview_standard.md`](interview_standard.md).
- **Real `notes/interview_connections.md`** — not a stub. Maps to specific
  interview questions or contexts. The auditor blocks:
  - any bracketed scaffold placeholder (`[Fill after…]`,
    `[See deep-research…]`, `[Fill in during…]`, `[TBV…]`, `[TBD]`);
  - any canonical IC.md section whose minimum substantive-word count is
    below **30** (raised from 15 on 2026-04-22 after Phase A sweep
    cleared all thin sections). A `IC_STUB_WORD_FLOOR = 15` tripwire
    remains in the code as a hard-stub catch.
  Exemplar: `manning_llm_from_scratch/notes/interview_connections.md`
  (4 mapped interview questions with cross-volume references).
- **LOS / chapter refs in Appendix D** — at least one `\cref{ch:...}`,
  `\ref{ch:...}`, or per-guide LOS-prefix token (e.g., `RSP-4.1`) must
  appear in `D_interview_prep.tex`. Promoted from advisory to gate on
  2026-04-22; Phase A sweep confirmed 118/118 pass.
- **System-design section body length** — for guides on the
  [`system_design_allowlist.yaml`](system_design_allowlist.yaml), the
  system-design scenario section body must be **≥50 substantive words**
  (hardened from presence-only regex on 2026-04-22). Extraction is
  sibling-level aware: subsections under a `\section{System Design:
  ...}` count toward the body.
- **Non-stub dashboard** — `docs/review/dashboard.md` shows real metrics, not
  "Run make qa-health after content is authored."

Today (2026-04-24, post-remediation per
`reports/tier_spec_effectiveness_audit_20260424.md` item 7):
**66 / 118** Silver PASS. The drop from 118/118 (2026-04-22) reflects
tightening the role-delta gate per audit memo item 7: a single
`\companytags{Mid-level}` line no longer counts as role-delta evidence;
the gate now requires either ≥2 distinct level tokens (e.g.,
`IC4` AND `Senior` in the same Appendix D) OR an explicit
`Role / Level Mapping` section header. 52 guides previously passed via
the loose 18-pattern OR-list and now need either richer level
markers or the section header; tracked as a follow-up sweep. The 4
non-role-delta gates are unchanged from the 2026-04-22 hardening.
Remediation timeline:

1. (2026-04-21) Hardened `audit_silver.py`: stub-placeholder
   regex + 15-word minimum per canonical IC.md section +
   allowlist-gated system-design presence.
2. (2026-04-21) Wrote
   [`system_design_allowlist.yaml`](system_design_allowlist.yaml) to
   encode the "where applicable" boundary.
3. (2026-04-21) Authored real IC.md content for 20 DLAI guides against
   the `manning_llm_from_scratch` exemplar.
4. (2026-04-21) Added two-scenario system-design sections to 28
   allowlist guides that had been missing them.
5. (2026-04-22 Phase A) Added chapter `\cref{ch:...}` refs to 8 guides'
   Appendix D (LOS-refs == 0 → 0 guides). Thickened the thinnest IC.md
   section on 29 guides so all 4 canonical sections are ≥30 words.
6. (2026-04-22 Phase B) Promoted IC_MIN_SECTION_WORDS from 15 to 30,
   promoted LOS-ref count to a hard gate (≥1 required), promoted
   system-design presence from title-regex-only to body-length check
   (≥50 words; sibling-level-aware extraction).

Audited by `scripts/audit_silver.py`, which is the authoritative
Silver roster. `scripts/audit_silver_fleet.py` remains as a fast
heuristic calibration signal but should not be quoted as the roster.
`scripts/audit_all_courses.py` agrees with the authoritative auditor
(its `check_silver` requires Bronze 9/9 and delegates the four content
gates to it).

**Informational columns** surfaced by `audit_silver.py` beyond
the four Silver gates --- none are hard gates, to avoid false-failing
guides with legitimate stylistic variation:

- `LOS` --- count of `\cref{ch:*}` / `\ref{ch:*}` / LOS-prefix refs in
  Appendix D. 20 guides have 0 refs (mostly short-DLAI depth-ladder
  format); use as a per-guide spot-check, not a gate.
- `ICmn` --- minimum substantive-word count across the 4 canonical
  IC.md sections. Surfaces stub sections (the `dlai_ragas_docs`
  defect pattern) without blocking legitimate short-template sections.
- `SysD` --- whether Appendix D has a system-design scenario section
  per §9. 63 guides lack one; the "where applicable" allowlist
  deserves a dedicated design pass.
- `--dashboard-debt` flag ranks guides by RED/YELLOW status markers
  in `docs/review/dashboard.md`; 77 guides carry 3+ RED, mostly from
  mis-calibrated glossary / bibliography / page-count targets on
  tutorial-genre guides. Defer to post-Silver polish.

### Gold — interview-ready, cross-referenced, audit-clean

Two sub-tiers per
`reports/tier_spec_effectiveness_audit_20260424.md` item 9:

- **Gold-Audit-Clean** — all six automated gates pass on the current
  checkout. This is the de-facto Gold today.
- **Gold** — Gold-Audit-Clean PLUS a signed reviewer attestation
  (planned schema; aspirational today, see "manual attestation" note
  below).

Silver plus the six automated gates:

- **G1: 100% LOS retrieval coverage + zero checkpoint stubs** — every
  `\los{}` has at least one retrieval opportunity (problem / vignette /
  drill / checkpoint / interview card per
  [`card_standards.md`](card_standards.md)) AND no `\item[LOS-ID]`
  entries with <10 words of body. Tightened from 20% stub tolerance
  per audit memo item 5 (the prior ceiling let
  `manning_ai_agents_and_apps` ship Gold with 18% stubs).
- **G2: 11-audit clean** — all 11 audits in
  [`audit_catalog.md`](audit_catalog.md) pass (no `FAIL`/`RED`),
  including `audit_atomicity` which now emits `FAIL` on any compound
  card and is therefore Gold-gating (memo §A "atomicity as Gold gate").
- **G3: per-chapter Anki decks** — large guides produce per-chapter
  `.apkg` plus a complete deck (count >= max(2, chapters - 1)). Small
  guides may produce only a complete deck via the
  `gold_exceptions.decks_complete_only` waiver below.
- **G4: size-aware crossref floor** — `min(4, chapters/4)` crossrefs
  spanning at least `min(3, chapters/3)` distinct chapter files. Manning
  guides with >=10 chapters require ≥6 crossrefs in ≥4 files. Replaces
  the prior `>=2 / >=2` floor (memo item 6) which let a 17-chapter
  guide pass with 2 crossrefs total.
- **G5: source-fidelity (citations + word floor)** — the
  `docs/review/gold_audit_*.md` doc must contain ≥3 source-citation
  markers (`book §`, `Ch N`, `Figure N`, `Table N`, `p. N`) AND ≥500
  non-template words (raised from 150 per memo item 3 — the 150 floor
  let `dlai_ragas_docs` pass with 273 words of topic bullets). Cohort-
  proportional thresholds (memo item 12) deferred.
- **G6: dashboard zero RED** — `docs/review/dashboard.md` must have
  zero RED status markers, OR the `gold_exceptions.dashboard_red_waiver`
  field is `"true"` with a non-empty `dashboard_red_waiver_justification`.
  Per memo item 8 (77/118 prior-Gold guides carry 3+ RED markers; the
  waiver path lets calibration-debt guides pass while a recalibration
  sprint is filed as follow-up).

**Live-truth requirement** — every audit invocation prints git SHA +
dirty status + UTC timestamp at the top of `print_report()` and
`write_markdown_report()` output (memo item 2). A saved report does
not constitute Gold evidence; the live audit on the current checkout
does.

**`gold_exceptions` waiver schema** (now consumed by `audit_gold.py`;
the prior spec note "future field — currently absent from the schema"
is superseded — see commit `8ce55a9f` and `shared/templates/guide_qa.yaml.template`):

```yaml
gold_exceptions:
  # G3 waiver — small guide ships only a complete deck.
  decks_complete_only: "true"
  justification: "<1-2 sentences explaining why per-chapter decks add no pedagogical value>"

  # G6 waiver — dashboard RED markers are calibration debt.
  dashboard_red_waiver: "true"
  dashboard_red_waiver_justification: "<reason naming the affected metrics + follow-up issue link>"
```

The auditor reads `gold_exceptions` via a regex parser at
`scripts/audit_gold.py:199-215`; both fields require non-empty
justifications to take effect.

**Calibration exemplars** (Gold-Audit-Clean today):
`manning_rlhf_book` (anchor: 0 stubs, 17 citation markers, 19 crossrefs
across 16 files, 0 RED), `transformer_mathematics` (G6 waivered —
TikZ-heavy small guide). `manning_llm_from_scratch` was previously an
exemplar but currently fails G2 atomicity (7 compound cards — surprise
finding under the new gate); promoted to follow-up.
`manning_ai_agents_and_apps` fails G1 (18% stubs).

**Today (2026-04-24, post-tightening live count)**:
- Silver-PASS: 66/118 (per the role-delta tightening above).
- Gold-Audit-Clean: 2/66 Silver-PASS guides (`manning_rlhf_book`,
  `transformer_mathematics`).
- Gold (auto + manual attestation): 0 (sub-tier is aspirational
  pending reviewer-attestation schema).

The Silver and Gold counts are dramatically lower than the
pre-remediation `118/118 / 118/118` claim. This is the intended
behavior: the prior counts reflected loose gates that the
[tier-spec effectiveness audit](../../reports/tier_spec_effectiveness_audit_20260424.md)
shows were not load-bearing. The current count is the live-truth count
the same auditor returns on the current checkout.

See `reports/qa_gold_<DATE>.md` (latest fleet rerun) for the per-guide
table and `reports/gold_independent_analysis_20260424.md` for
standard-calibration analysis. Structural promotion history below:

- **2026-04-20** (Phase 2–4 playbook): 11 Gold — 10 Manning
  exemplars (`manning_rlhf_book`, `manning_llm_from_scratch`,
  `manning_nlp_in_action`, `manning_python_workout_2e`,
  `manning_ai_agents_in_action_2e`, `manning_grokking_deep_rl`,
  `manning_grokking_ml_2e`, `manning_enterprise_rag`,
  `manning_grokking_deep_learning`, `manning_deep_learning_pytorch_2e`)
  plus `transformer_mathematics` (first 99_other Gold; TikZ figures
  via `shared/cards/render_tikz.py`).
- **2026-04-22** (gold-sweep A–E, commits `4bf28694`..`e673a35e`):
  55 additional Manning guides promoted via fleet-wide automation
  (anki config scaffolding, Makefile `--config` fix, crossrefmargin
  authoring, 1566 checkpoint items from LOS definitions, and G5
  doc generation from live audit output). Auxiliary tooling added:
  `scripts/scaffold_anki_config.py`, `scripts/scaffold_checkpoint_items.py`,
  `scripts/scaffold_gold_audit.py`.
- **2026-04-23** (gold-sweep-dlai, phases 0/A/B/D/F/E):
  all 47 DLAI family guides promoted in one session. Key adaptations
  from the Manning playbook: (1) extended the scaffold scripts to
  support four chapter-filename patterns (Manning `NN_mN_slug.tex`
  already; plus DLAI `chNN_slug.tex`, `chNN.tex`, and bare `NN_slug.tex`),
  (2) extended `\moduleheader{}` detection to also accept
  `\lessonheader{}`, (3) extended `scaffold_checkpoint_items.py`
  `CHECKPOINTBOX_RE` to match the bare `\begin{checkpointbox}`
  environment form alongside the tcolorbox form, (4) added
  `% freshness-ok` annotations where the freshness audit flagged
  legitimate deprecation-documentation text (post-course-updates
  appendices and interview-prep answers). Registered
  `dlai_computer_use_anthropic` and `dlai_spec_driven_development`
  in `guides.yml` so `shared/audits/audit_*.py` could cover them
  (they had been reported as "99_other family?" by the gold auditor).
  311 checkpoint items scaffolded for G1 closure; 47 per-chapter
  deck sets built via the Manning-canonical Makefile `decks:` target.
  All DLAI guides promoted via `--family dlai` flags now accepted
  by the three scaffold scripts.

**Last promotion** (`manning_ai_agents_and_apps`, the only Gold-pending
guide after Sprint E): closed by converting inline `(a) X; (b) Y; (c) Z`
scenario enumerations to proper `\begin{itemize}` blocks in seven
vignettes / problems, plus a bulk semicolon-to-period sweep inside
\\begin{solution}/\\begin{vignette}/\\begin{problem} blocks. Dropped
`audit_card_presentation` from 20.9\% to 13.0\%.

Gold reports live at `<guide>/docs/review/gold_audit_YYYYMMDD.md`
(dated per promotion session).

Remaining Silver runway: no non-trivial candidates. The
`deeplearning_ai_pytorch_professional_certificate` guide — previously
characterized as a course-aggregator meta-guide out of scope for Gold
gates — was reclassified on 2026-04-24 after inspection confirmed it
has 14 authored chapters with 86 LOS and 385 extracted cards. It now
passes the auto Gold gates like any other guide.

Run `python3 scripts/audit_gold.py --verbose` for the current
fleet classification under hardened gates. The older
`audit_gold_fleet.py` is retained for historical comparison but its
G5 check (file-exists) is superseded — invoking it now prints a
runtime stderr deprecation banner.

## Failure semantics (per critique overlooked §9)

- **No-code books**: Manning books explicitly marked no-code in
  `manning_catalog.yaml` (`has_code: false`) and in the source manifest do
  NOT need companion-code evidence. They may still be Gold.
- **Short DLAI courses** (<3 hours of source material): may scale LOS and
  chapter targets to 4-6 / 3-5 respectively when documented in their source
  manifest. Still eligible for Gold at the calibrated targets.
- **Unavailable source materials**: figures/tables/listings that cannot be
  reproduced are documented in the source manifest under "Known Source
  Issues". Do not block Bronze or Silver. Block Gold only if the missing
  material is pedagogically central to the guide's purpose.
- **Per-guide exception slots**: `guide_qa.yaml.gold_exceptions` is
  the audit-script-respected waiver schema. Current fields:
  `decks_complete_only` + `justification` (G3 waiver) and
  `dashboard_red_waiver` + `dashboard_red_waiver_justification`
  (G6 waiver). Both require a non-empty justification to take effect;
  see the §Gold subsection above for the YAML shape.
- **Promotion gating**: a guide cannot claim a tier without all gating audits
  passing OR a documented exception in the source manifest.

### Out-of-interview-scope waiver

Some guides cover domains outside AI-engineering interview prep —
Docker internals, API design, Python packaging, DSA drills, pandas
idioms, etc. For these, the standard Silver requirement of "5+
conceptual interview questions with role-delta markers" produces
filler content (generic "what is a container orchestrator" questions
bolted onto a Docker book). The waiver lets such guides pass Silver
honestly.

**Eligibility**: a guide's domain is outside AI-engineering interview
prep — operations, general SE, Python tooling, classical DSA, etc.
If the content domain genuinely comes up in ML interviews
(statistics, Bayesian methods, graph algorithms for ML, etc.), the
guide is NOT eligible; author real AI-relevant questions instead.

**Waiver structure** (Appendix D):

```latex
\chapter{Interview Preparation}
\label{app:interview-prep}

\section*{Out-of-Interview-Scope Waiver}

\begin{narrativebox}[title=Scope note]
This guide covers \textbf{<domain>}, which is not typically tested
in AI-engineering interviews. <1-2 sentence rationale citing the
guide's actual content and why it's peripheral to ML/AI roles.>
Two canonical domain questions are included below for completeness;
full interview prep for this domain is provided by dedicated
resources rather than by expanding this Appendix D.
\end{narrativebox}

\paragraph{Role / Level Mapping.}
<Role-delta paragraph — same 3-rung structure as non-waivered guides,
but framed for the guide's domain. E.g., for Docker: IC3 = command
literacy, IC4 = build + debug production images, IC5+ = multi-host
orchestration + security model.>

\section*{Domain Question 1: <title>}
\begin{interviewcontext}[<tag>]
\companytags{<relevant teams — e.g., SRE / Platform Eng / L4-L5>}
<Real interview question in this domain, source-engaged with the
guide's chapters. Not a 1-line "define X"; a genuine question.>

\textbf{30s answer}: ...
\textbf{2min answer}: ...
\end{interviewcontext}

\section*{Domain Question 2: <title>}
<Same structure.>
```

**Enforcement**: `scripts/audit_silver.py` detects the
`Out-of-Interview-Scope Waiver` heading and marks the guide's App-D
gate as PASS with a `waiver` classification in the report. The 2
interviewcontext blocks + role-delta tokens (≥2 distinct OR an
explicit `Role / Level Mapping` header per the tightened gate) are
still required so the file isn't empty.

**Special case — aggregator waiver**: a guide that is a meta-guide
with no chapters of its own (e.g.,
`deeplearning_ai_pytorch_professional_certificate` aggregating 6
specializations) uses the same waiver shape, but the scope-note
rationale cites "this guide aggregates N sub-courses; interview prep
for the constituent specializations is carried by those guides."
The 2 questions are "bridge" questions (when to use the tech stack,
career-fit, how sub-courses compose).

## Non-guide artifacts (outside the tier model)

Some directories under the course-learning repo root are NOT course
guides and are therefore out of scope for Bronze/Silver/Gold tier
evaluation. They are excluded from `scripts/audit_all_courses.py`,
`scripts/audit_silver_fleet.py`, and
`scripts/audit_silver.py` via `EXCLUDE_DIRS`.

- `manning_curriculum` — a LaTeX document enumerating the Manning
  curriculum and its sequencing; not a guide itself. Has its own
  Makefile and compiles to a standalone PDF.
- `manning_sutskevers_list` — a reading list of canonical papers;
  no chapter structure, no `guide_qa.yaml`.

A directory becomes a tier-tracked guide the moment it gains a
`guide_qa.yaml`. Adding one of these dirs to `EXCLUDE_DIRS`
prevents accidental inclusion if a `guide_qa.yaml` is ever placed
there, which is a defensive measure — the primary filter is the
presence of `guide_qa.yaml` itself.

## How tiers interact with families

Tiers are universal. Per-family overlays calibrate the *thresholds* (e.g.,
LOS counts) but not the *gates* (which audits must pass). A Manning Gold
guide and a DLAI Gold guide both pass all 10 audits; they differ only in
scale targets.

## Promotion sequencing

- **Bronze → Silver**: scaffold the source manifest, fill it from the
  catalog and existing knowledge, write a real Appendix D, write a real
  `interview_connections.md`, populate the dashboard. Driven by the
  remediation plan.
- **Silver → Gold**: close LOS retrieval gaps, fix audit failures one by
  one, build per-chapter decks, add 2+ valid `\crossrefmargin{}`, spot-check
  source fidelity in equation-heavy chapters.

Each promotion is a separate sprint per guide; the
[remediation plan](../../plans/standards_remediation_2026-04-19.md)
sequences them.
