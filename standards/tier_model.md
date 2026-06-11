# Tier Model

Three-tier readiness model for course-learning guides. Replaces the
binary "gold-standard or not" framing of the original single-spec era.

## Tiers

### Bronze — passes the structural baseline

A guide is Bronze when `make audit-all` (i.e.
`python -m tooling.audits.fleet.audit_all_courses --summary`) shows it at
**9/9 GREEN** on the 9-point structural checklist:

1. `guide_qa.yaml` present and valid.
2. Validation modules resolvable via `tooling.validation.{check_refs,check_duplicates,extract_los,check_latex_warnings}`.
3. Makefile QA targets (`qa`, `qa-build`, `qa-refs`, `qa-los`, `qa-cards`, `qa-presentation`).
4. `notebook-extensions.sty` present (at `guide/notebook-extensions.sty`).
5. Cards extracted (at least one `cards/*.yml`).
6. Anki deck (`decks/*.apkg`) present or explicitly documented as absent.
7. `review/dashboard.md` present.
8. Bloom's levels in `guide_qa.yaml.los.valid_levels` match the canonical 10
   in [`learning_outcomes.md`](learning_outcomes.md) (or are a documented subset).
9. No hardcoded paths in audit scripts or Makefile (resolve via the
   `tooling.*` package).

Live as of 2026-06-09: **81 / 81** active guides (across 12 topics; 45
published, 36 MEAP) are Bronze 9/9.

### Silver — verified and contextualized

Bronze plus:

- **Source manifest** scaffolded and verified (`review/source_manifest.md`).
  An existing manifest counts; absence does not block Silver retroactively
  (this is a forward-looking gate).
- **Real Appendix D** — at least 5 conceptual questions with expected-answer
  points, role/level deltas (IC4 vs IC5+/Staff), cross-references to
  chapters via LOS IDs, and — for any guide on the
  [`system_design_allowlist.yaml`](system_design_allowlist.yaml) — at least
  one system/design scenario section. A stub Appendix D fails Silver. See
  [`interview_standard.md`](interview_standard.md).
- **Real `review/interview_connections.md`** — not a stub. Maps to specific
  interview questions or contexts. The auditor blocks:
  - any bracketed scaffold placeholder (`[Fill after…]`,
    `[See deep-research…]`, `[Fill in during…]`, `[TBV…]`, `[TBD]`);
  - any canonical IC.md section whose minimum substantive-word count is
    below **30**. A `IC_STUB_WORD_FLOOR = 15` tripwire remains in the
    code as a hard-stub catch.
  Exemplar: `llms-and-transformers/manning_llm_from_scratch/review/interview_connections.md`
  (4 mapped interview questions with cross-volume references).
- **LOS / chapter refs in Appendix D** — at least one `\cref{ch:...}`,
  `\ref{ch:...}`, or per-guide LOS-prefix token (e.g., `RSP-4.1`) must
  appear in `D_interview_prep.tex`.
- **System-design section body length** — for guides on the
  [`system_design_allowlist.yaml`](system_design_allowlist.yaml), the
  system-design scenario section body must be **≥50 substantive words**.
  Extraction is sibling-level aware: subsections under a
  `\section{System Design: ...}` count toward the body.
- **Non-stub dashboard** — `review/dashboard.md` shows real metrics, not
  "Run make qa-health after content is authored."

Live as of 2026-06-09: **81 / 81** Silver PASS. The role-delta gate
requires either ≥2 distinct level tokens (e.g., `IC4` AND `Senior` in the
same Appendix D) OR an explicit `Role / Level Mapping` section header; a
single `\companytags{Mid-level}` line does not count as role-delta evidence.

Audited by `tooling.audits.fleet.audit_silver`, which is the authoritative
Silver roster. `tooling.audits.fleet.audit_silver_fleet` remains as a fast
heuristic calibration signal but should not be quoted as the roster.
`tooling.audits.fleet.audit_all_courses` agrees with the authoritative
auditor (its `check_silver` requires Bronze 9/9 and delegates the four
content gates to it).

**Informational columns** surfaced by `tooling.audits.fleet.audit_silver`
beyond the four Silver gates --- none are hard gates, to avoid false-failing
guides with legitimate stylistic variation:

- `LOS` --- count of `\cref{ch:*}` / `\ref{ch:*}` / LOS-prefix refs in
  Appendix D; use as a per-guide spot-check, not a gate.
- `ICmn` --- minimum substantive-word count across the 4 canonical
  IC.md sections. Surfaces stub sections without blocking legitimate
  short-template sections.
- `SysD` --- whether Appendix D has a system-design scenario section
  per §9; the "where applicable" allowlist deserves a dedicated design pass.
- `--dashboard-debt` flag ranks guides by RED/YELLOW status markers
  in `review/dashboard.md`, mostly from mis-calibrated glossary /
  bibliography / page-count targets on tutorial-genre guides. Defer to
  post-Silver polish.

### Gold — interview-ready, cross-referenced, audit-clean, current

**Gold = Silver + all seven gates (G1–G7) passing live on the current
checkout.** There is a single Gold tier; the former two-sub-tier split (an
automated tier plus an aspirational reviewer-attestation tier) is retired —
"Gold" means audit-clean on a live run (the consuming repo's `ROADMAP.md`
§Non-goals records the no-manual-attestation-sub-tier decision). Gold is a
**living status**: the gates are
re-checked against the working tree, so a guide can *lapse* — a dashboard RED
regression (G6) or a currency appendix that ages past its velocity SLA (G7)
drops a guide out of Gold until it is refreshed.

The seven gates:

- **G1 — retrieval coverage + no checkpoint stubs.** 100% of `\los{}` have at
  least one retrieval opportunity (problem / vignette / drill / checkpoint /
  interview card per [`card_standards.md`](card_standards.md)), AND no
  `\item[LOS-ID]` entries with <10 words of body.
- **G2 — 11-audit clean.** Zero `FAIL` across all **11 audits** cataloged in
  [`audit_catalog.md`](audit_catalog.md): `atomicity`, `back_content`,
  `card_presentation`, `card_quality`, `content_freshness`, `content_quality`,
  `crossref_quality`, `margin_quality`, `retrieval_coverage`, `solution_quality`,
  `term_consistency`. The ten binary audits must emit no `FAIL`; `back_content`
  (which grades on CRITICAL / HIGH / MEDIUM / INFO severities) gates on **zero
  CRITICAL and zero HIGH** — MEDIUM and INFO are advisory. `audit_catalog.md` is
  authoritative for each audit's semantics; the eleven names here and there must
  match exactly. *Runner status:* there is no in-repo Gold runner yet — the
  legacy `course_learning` runner covers the ten binary audits (G1–G6); the
  `back_content` severity gate and G7 activate with the in-repo runner port
  (roadmap T2 — see `audit_catalog.md`).
- **G3 — per-chapter decks build clean.** `make decks` exits 0 AND emits at least
  `max(2, chapters - 1)` per-chapter `.apkg` files **plus the complete/combined
  deck** AND the guide's `anki.course_map` covers every module. Decks are
  gitignored and rebuilt on demand, so this is a **live build check, not an
  artifact count**. Small guides may waive the per-chapter requirement via
  `gold_exceptions.decks_complete_only` (the complete deck is still required).
- **G4 — size-aware crossref floor.** Guides with ≥10 chapters require ≥6
  `\crossrefmargin` notes spanning ≥4 distinct chapter files; smaller guides
  require ≥ `max(2, min(4, chapters/4))` notes across ≥ `max(2, min(3, chapters/3))`
  files. (The former family-detection branch is dropped; the consuming
  guides-manning fleet is all-Manning.)
- **G5 — source-fidelity doc.** `review/gold_audit_*.md` must contain ≥500
  non-template words and ≥3 source-citation markers (`book §`, `Ch N`, `Figure N`,
  `Table N`, `p. N`); scaffold-signature text and author-"TBV" placeholders fail
  it. It must include a dedicated **"E/F source verification"** section recording
  that each F-appendix debate's cited sources were spot-checked against the live
  web, and that the E appendix's named moving surfaces were confirmed current as of
  its date stamp.
- **G6 — dashboard zero RED.** `review/dashboard.md` carries zero RED status
  markers, OR `gold_exceptions.dashboard_red_waiver: "true"` with a non-empty
  `dashboard_red_waiver_justification`. *Sequencing note:* this gate is enforced
  for promotion waves only **after** the dashboard-floor recalibration (roadmap
  Track G), because many guides currently carry RED markers from
  genre-miscalibrated floors rather than real gaps.
- **G7 — currency & perspectives (the polish gate).** Two **filename-keyed**
  appendices under `guide/appendices/` (the gate matches the exact filenames, not
  appendix *slot* letters):
  - `E_post_course_updates.tex` — **dated** (the literal string `current as of
    YYYY-MM` in the appendix's opening paragraph, so the runner can parse the
    age); a *what-still-holds* source-stability section; and **≥3 substantive
    currency items**, each naming a concrete moving surface (a library/API, a
    model name, a pricing snapshot, or — for MEAP guides — specific chapter/source
    churn). Either the "re-verify these named surfaces" framing *or* a literal
    "book says X → the field now says Y" changelog satisfies the substance bar; a
    stub ("no significant changes identified yet") **fails**. For MEAP guides the
    appendix must name the **covered MEAP version** (the authoritative value is the
    MEAP-version field in `review/source_manifest.md`) and be dated at-or-after it.
    The date must fall **within the guide's velocity SLA** (below); a stale E
    lapses Gold.
    (Once the MEAP-freshness checker lands — roadmap T4 — a STALE freshness status
    also fails G7.)
  - `F_contrasting_opinions_open_debates.tex` — **≥3 open debates**, each with
    dual-sourced positions A and B, an explicit "where the book sits" + chapter
    reference, and a verdict flag (*well-supported* / *contested* / *dated*). F is
    waiverable — for guides whose field has no live debates — via
    `gold_exceptions.debates_waiver: "true"` + justification.

  *Slot-collision note:* `manning_llm_from_scratch` currently uses the `E_` slot
  for an `E_code_snippets.tex` appendix; it must be renamed/normalized to the keyed
  `E_post_course_updates.tex` during its Gold wave.

**Velocity SLA (G7 E-age).** Each guide carries a `gold.velocity` key in
`guide_qa.yaml` (`fast` | `medium` | `slow`) setting how long an E appendix stays
fresh before it lapses Gold:

| Velocity | E max age | Default topic shelves |
|----------|:---------:|------------------------|
| `fast`   | 6 months  | ai-agents, ai-engineering-and-llm-apps, llms-and-transformers, rag-and-search, evaluation-alignment-safety |
| `medium` | 12 months | generative-ai-and-diffusion, graphs-and-knowledge-graphs, ml-engineering-and-mlops, deep-learning |
| `slow`   | 18 months | ml-and-data-foundations, reinforcement-learning, software-engineering-and-python |

A guide may override its shelf default by setting `gold.velocity` explicitly. The
`content_freshness` audit reads this same key (roadmap T1).

**Live-truth requirement.** Every audit invocation prints git SHA + dirty status +
UTC timestamp at the top of its report. A saved report is not Gold evidence; the
live audit on the current checkout is. Existing `review/gold_audit_*.md` docs remain
valid across this definition change as long as they meet G5; re-verification is
required only when the source version changes (e.g. a MEAP refresh).

**`gold_exceptions` waiver schema** (in `guide_qa.yaml`; each waiver requires a
non-empty justification to take effect):

```yaml
gold_exceptions:
  # G3 — small guide ships only a complete deck.
  decks_complete_only: "true"
  justification: "<why per-chapter decks add no pedagogical value here>"

  # G6 — dashboard RED markers are calibration debt, not real gaps.
  dashboard_red_waiver: "true"
  dashboard_red_waiver_justification: "<the affected metrics + follow-up link>"

  # G7 — the field has no live contrasting-opinions debates to document.
  debates_waiver: "true"
  debates_waiver_justification: "<why no F appendix is warranted for this guide>"
```

**Exemplars.** `manning_causal_ai` is the **F anchor** — six debates (D1–D6),
each with dual-sourced positions, "where the book sits" + `\cref{ch:Mn}`, a verdict
flag, and T1/T2/T3 evidence tiers, dated "as of June 2026." For **E**,
`manning_learn_ai_data_engineering` (MEAP, version-tied: a what-still-holds
stability box, MEAP-v7 churn to re-sync, named tooling/pricing surfaces, a
frontier-watch section) and `manning_causal_ai` (the published-book variant) are
the structural models; both satisfy G7's E gate once an explicit "current as of
YYYY-MM" stamp is added — the one element they omit. See
[`content_design.md`](content_design.md) §"Currency appendices (E/F)" for the
authoring template.

The baseline fleet run of the ported Gold runner (roadmap G0) establishes the
honest live count; expect broad FAIL/scaffold results until the Track-G waves
author the missing E/F appendices (E is absent or stubbed in most guides; F in
nearly all).

## Failure semantics (per critique overlooked §9)

- **No-code books**: Manning books explicitly marked no-code in their
  `review/source_manifest.md` (`has_code: false`) do NOT need companion-code
  evidence. They may still be Gold.
- **Short-source guides** (<3 hours of source material): may scale LOS and
  chapter targets to 4-6 / 3-5 respectively when documented in their source
  manifest. Still eligible for Gold at the calibrated targets.
- **Unavailable source materials**: figures/tables/listings that cannot be
  reproduced are documented in the source manifest under "Known Source
  Issues". Do not block Bronze or Silver. Block Gold only if the missing
  material is pedagogically central to the guide's purpose.
- **Per-guide exception slots**: `guide_qa.yaml.gold_exceptions` is
  the audit-script-respected waiver schema. Current fields:
  `decks_complete_only` + `justification` (G3 waiver),
  `dashboard_red_waiver` + `dashboard_red_waiver_justification`
  (G6 waiver), and `debates_waiver` + `debates_waiver_justification`
  (G7 F-appendix waiver). All three require a non-empty justification
  to take effect; see the §Gold subsection above for the YAML shape.
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

**Enforcement**: `tooling.audits.fleet.audit_silver` detects the
`Out-of-Interview-Scope Waiver` heading and marks the guide's App-D
gate as PASS with a `waiver` classification in the report. The 2
interviewcontext blocks + role-delta tokens (≥2 distinct OR an
explicit `Role / Level Mapping` header per the tightened gate) are
still required so the file isn't empty.

**Special case — aggregator waiver**: a meta-guide with no chapters of
its own (one that aggregates several sub-courses) uses the same waiver
shape, but the scope-note rationale cites "this guide aggregates N
sub-courses; interview prep for the constituent specializations is
carried by those guides." The 2 questions are "bridge" questions (when
to use the tech stack, career-fit, how sub-courses compose).

## Non-guide artifacts (outside the tier model)

Some directories under the repo root are NOT course guides (curriculum
or reading-list documents, infrastructure dirs) and are therefore out of
scope for Bronze/Silver/Gold tier evaluation.
`tooling.audits.fleet.audit_all_courses` skips them via its `EXCLUDE_DIRS`; the
Silver auditors (`tooling.audits.fleet.audit_silver`, `audit_silver_fleet`)
rely on `guide_qa.yaml` discovery (`tooling.discovery.iter_guide_dirs`) instead.

A directory becomes a tier-tracked guide the moment it gains a
`guide_qa.yaml`. Adding a non-guide dir to `EXCLUDE_DIRS` is a
defensive measure that prevents accidental inclusion if a `guide_qa.yaml`
is ever placed there — the primary filter is the presence of
`guide_qa.yaml` itself.

## How thresholds interact with tiers

Tiers are universal: the same gates apply to every guide. What varies per guide
is the *thresholds* (LOS counts, glossary/bibliography size, page-count targets),
calibrated per guide and topic genre in `guide_qa.yaml` — never the *gates*
(which audits must pass). Every Gold guide passes all 11 audits (see §Gold G2);
guides differ only in scale targets.

## Promotion sequencing

- **Bronze → Silver**: scaffold the source manifest, fill it from the
  catalog and existing knowledge, write a real Appendix D, write a real
  `interview_connections.md`, populate the dashboard. Driven by the
  remediation plan.
- **Silver → Gold**: close LOS retrieval gaps, fix audit failures one by one,
  build per-chapter decks (plus the complete deck), meet the size-aware G4
  crossref floor (§Gold G4), author the **E/F currency appendices** (§Gold G7,
  per [`content_design.md`](content_design.md) §"Currency appendices"), write the
  `review/gold_audit_*.md` fidelity doc, and spot-check source fidelity in
  equation-heavy chapters.

Each promotion is a separate sprint per guide; the Gold waves are sequenced in
the consuming repo's `ROADMAP.md` (Track G).
