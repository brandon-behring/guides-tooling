# Content Design

Craft rules for the pedagogical content of every guide: margin notes, key
concepts, problems, vignettes, drills. Consolidates and supersedes
`.claude/rules/margin-notes.md` and `.claude/rules/content-quality.md`.

Grounded in Tufte (information design), Mayer (multimedia learning),
Wozniak (atomicity / spaced repetition), and Matuschak (evergreen notes).

## Margin notes

### Core philosophy

1. Margins are a **standalone review channel**. A reader skimming only the
   margins should reconstruct the key interview-ready insights from the
   chapter.
2. Margins are **cross-guide navigation beacons**. A `\formulamargin{}` anchor
   lets a reader jumping between guides land on the key equation without
   re-reading the section.
3. Every note must pass seven conditions (Tufte/Mayer/Wozniak-grounded):

| Condition | Test | Source |
|-----------|------|--------|
| Supplementary | Main text comprehensible without this note? | Tufte |
| Not redundant | Adds info NOT in the adjacent paragraph? | Redundancy effect |
| Not seductive detail | Directly serves the LOS being tested? | Harp/Mayer 1998 |
| Atomic | Makes exactly one point? | Wozniak Rule 4 |
| Category-tagged | Reader can decide to read it from the tag alone? | Mayer signaling |
| Actionable | Tells the reader to DO or KNOW something specific? | Retrieval practice |
| Density-controlled | Section at 2-3 notes, not 0 or 5+? | Stull/Mayer 2007 |

### The 6 categories (convenience macros)

Always use the convenience macro. Never write raw `\marginnote[Category]{text}`
in authored chapters.

| Macro | Expands to | Purpose | Good example |
|-------|-----------|---------|--------------|
| `\interviewmargin{text}` | `\marginnote[Interview]{text}` | What interviewers look for | "Google asks sample size as a warm-up; target 2 min" |
| `\patternmargin{text}` | `\marginnote[Pattern]{text}` | Framework or mnemonic | "SRM debug order: (1) assignment bug, (2) bot filtering, (3) differential attrition, (4) data pipeline. 80% are #1 or #4." |
| `\formulamargin{text}` | `\marginnote[Formula]{text}` | Quick-reference instantiated formula | "n = 16 sigma^2 / MDE^2 per arm (80% power, alpha=0.05)" |
| `\warningmargin{text}` | `\marginnote[Warning]{text}` | Common mistake + direction | "Spillover: Viral -> underestimate. Competition -> overestimate." |
| `\practicemargin{text}` | `\marginnote[Practice]{text}` | Time target + performance constraint | "Target: 15 min. Bootstrap = Swiss Army knife — CI for ANY statistic." |
| `\crossrefmargin{text}` | `\marginnote[Cross-Ref]{text}` | Pointer to another guide | "Theory: CI Python Ch 8 (CUPED variance reduction proof)" |

**Note on `\warningmargin`**: this expands to `\marginnote[Warning]{text}` (not
`\marginwarning[Warning]{text}` — that was a typo in the old
`content-quality.md`, corrected 2026-04-19).

Canonical macro source: per-guide `notes/notebook/notebook-extensions.sty`.
Machine-readable mirror: `shared/config/canonical_values.yaml`
(`margin_categories` key).

### Quality rules

1. **Max ~25 words** per note.
2. **One idea** per note.
3. **Actionable** — tells the reader what to DO or KNOW.
4. **No fluff** — every word earns its place.
5. **Consistent category** — only the 6 categories above. Don't invent.
6. **Convenience macros only** — no raw `\marginnote[...]{...}`.

### Per-category craft standards

**`[Interview]`** — Name the company + the signal they test.
```
GOOD: "Google asks sample size as a warm-up; target 2 min"
BAD:  "Common interview topic"
```

**`[Pattern]`** — Compress a chapter to a recitable procedure or mnemonic.
```
GOOD: "SRM debug order: (1) assignment bug, (2) bot filtering,
       (3) differential attrition, (4) data pipeline. 80% are #1 or #4."
BAD:  "Important pattern to remember"
```

**`[Formula]`** — Give the instantiated shortcut, not the general form.
```
GOOD: "n = 16 sigma^2 / MDE^2 per arm (80% power, alpha=0.05)"
BAD:  "See formula above"
```

**`[Warning]`** — State what goes wrong AND in which direction.
```
GOOD: "Spillover: Viral -> underestimate. Competition -> overestimate."
BAD:  "Be careful here"
```

**`[Practice]`** — Time target + the key performance constraint.
```
GOOD: "Target: 15 min. Bootstrap = Swiss Army knife — CI for ANY statistic."
BAD:  "Practice this"
```

**`[Cross-Ref]`** — State what the other guide provides that this one does not.
```
GOOD: "Theory: CI Python Ch 8 (CUPED variance reduction proof)"
BAD:  "See other guide"
```

### Density targets

Per-chapter figures are a **content-driven floor and typical range, not a cap** (updated
2026-05-29). The binding over-density signal is **per-section** (5+ → consolidate); per-chapter
counts scale with the chapter's length and section count, so a long multi-section chapter that
follows the per-section guidance will naturally run above the per-chapter "typical" figure — that
is expected, not a violation.

| Chapter type | Notes per chapter (typical floor) | Notes per section |
|-------------|-------------------|-------------------|
| Foundations (heavy theory) | 8-14+ | 1-2 |
| Core methods | 8-14+ | 2-3 |
| Framework / synthesis (many sections) | 14-22+ | 2-3 |
| Problem-focused / drills | 1 per problem + 3-5 strategic at opener | — |
| Interview walkthrough | 12-16+ | favor `[Interview]` and `[Pattern]` |
| **Code-heavy chapter** | **5-10+** | 1-2 |

Rationale: theory/framework chapters can absorb more margin notes without crowding; code
chapters have less text real estate adjacent to code blocks.

> **The failure mode to guard against is *forgetting* margins** — a substantive section left
> bare — not exceeding a count. Do **not** clamp a chapter to the per-chapter ceiling: if a
> section carries a genuine margin-worthy insight, add it (up to the per-section 5+ flag).
> Per-chapter RED applies only at the extremes (0, or 30+ theory / 20+ code-heavy).

### Anti-patterns

| Anti-pattern | Example | Fix |
|-------------|---------|-----|
| Redundancy | Note restates adjacent paragraph | Remove or replace with new angle |
| Seductive detail | Interesting history, not on the test | Remove |
| Bare meta-commentary | "Important concept" / "Be careful" | Add specifics or remove |
| Non-standard category | Category not in the 6 above | Map to standard |
| Under-coverage | Substantive section with 0 margins | Add one margin-worthy note (the primary failure mode to guard against) |
| Over-density | 5+ notes per section | Consolidate to 1 note per problem |
| Vague company signal | "Asked in every round" | Which round? Which concept? What to say? |
| Raw `\marginnote` | `\marginnote[Cat]{text}` directly | Use convenience macro |

### Speed drill special case

For drill-heavy chapters, consolidate per-problem Practice/Pattern/Interview
triplets into a single margin note:

```latex
\practicemargin{3 min | Frequency count | OA stage}
```

Keep strategic Pattern/Interview notes at chapter openers only.

## Key concepts

Wraps the **one insight** that, if the reader remembers nothing else from the
section, should survive.

**Interviewer test**: "Could an interviewer ask about just this box and get a
meaningful answer?" If no, it's a detail, not a keyconcept.

### Structure

```latex
\begin{keyconcept}[Title]
\textbf{Core Insight:} [1-2 sentences]

\textbf{Why It Matters:} [or \textbf{Decision Rule:}]
[When/how to apply]

\textbf{When It Breaks:}
[Conditions where this insight fails]
\end{keyconcept}
```

### Constraints

- Max ~150 words.
- 2-4 per chapter. Zero = gap. 8+ = diluted.

### Anti-pattern

Wrapping an entire subsection inside `keyconcept`. Loses focus. A keyconcept
is a summary, not a section.

## Problems

Test one skill. Every solution must include:

- **Approach**: how to start and frame the problem.
- **Key Insight**: the transferable idea (what separates a correct answer
  from an impressive one).
- **Answer**: the final response or conclusion.

Multi-step reasoning uses `\substep{label}{content}` blocks.

Worked-Faded-Practice progression for procedural/implementation chapters:
1. Worked example with full solution.
2. Scaffolded or partially faded example.
3. Independent practice.

The `\problem[Title][LOS][Difficulty][Scaffolding]` macro signature supports
per-problem scaffolding override. See
[`card_standards.md`](card_standards.md) for how `extract_cards.py` assigns
scaffolding levels automatically.

Solutions must live **outside** the `\end{problem}` block and within 5000
characters for the extractor to pair them correctly.

Long solutions should be split rather than creating compound cards — see
splitting policy in [`card_standards.md`](card_standards.md).

## Vignettes

Test judgment across multiple skills. Structure:

- **Scenario** with genuine tension (metrics that conflict, stakeholders
  that disagree).
- **Data table** (CFA-style) — concrete numbers.
- **3-5 follow-up questions** that build on each other.

Vignettes scale better than problems for senior-level judgment questions.
Target: 3+ per guide where scenario design applies.

## Drills

Quick-calculation practice. Margin macro:

```latex
\practicemargin{3 min | Frequency count | OA stage}
```

Chapter openers carry 3-5 strategic Pattern/Interview notes; per-drill
margin is one `\practicemargin` with time + technique. See density table
above.

## Currency appendices (E/F)

The two appendices that most distinguish a *polished* guide from a merely
correct one: appendix **E** keeps the guide honest about a moving field, and
appendix **F** shows the reader where the book's confident claims are actually
contested. Together they are **Gold gate G7** (see
[`tier_model.md`](tier_model.md) §Gold). Both are **filename-keyed** — the gate
matches the exact filenames below, not the appendix slot letter.

### E — `E_post_course_updates.tex` (post-course updates)

Tracks what has shifted *out from under* the book since it was written: tooling
that versions on its own clock, model names and pricing, and — for a MEAP — the
source text itself. Required elements:

1. **A date stamp** — "current as of YYYY-MM" near the top. The velocity SLA
   (G7) measures the appendix's age from this stamp; an undated E cannot pass.
2. **A "what still holds" section** — name the conceptual spine that is *stable*
   (the discipline, not the API) so the reader knows what *not* to chase. A
   `checkpointbox` titled "What This Guide Covers" works well.
3. **≥3 substantive currency items**, each naming a concrete moving surface — a
   library/API call, a model name, a pricing snapshot, a structured-output mode,
   or (MEAP) chapter churn. Either framing clears the substance bar:
   - *Re-verify* framing (common for settled/discipline books): "the book
     standardizes on `gpt-4o` at ≈\$2.50/M in, \$10/M out — a snapshot; verify
     current model IDs and pricing before costing a batch."
   - *Changelog* framing (for fast-moving tooling books): "book uses X (Ch. N);
     the library now requires Y — migration: …".
4. **MEAP version-tie** (MEAP guides only) — name the covered MEAP version and
   date the appendix at-or-after it; add a "MEAP churn to re-sync" section
   listing what a newer drop could move (chapter count/order, running examples,
   LOS phrasing).

A stub **fails**: "*No significant breaking changes identified yet.*" is a
placeholder, not an E appendix. Worked exemplars:
`manning_learn_ai_data_engineering` (MEAP, version-tied) and `manning_causal_ai`
(published) — both follow the four-section pattern above.

### F — `F_contrasting_opinions_open_debates.tex` (contrasting opinions)

The honest counterweight to an opinionated book: for each major stance the book
takes, lay out the strongest case *against*. Required: **≥3 open debates**, each
structured as:

- **The debate** — one paragraph framing the tension, with chapter refs
  (`\cref{ch:Mn}`) to where the book takes its stance.
- **Position A** and **Position B** — each stated in its strongest form and
  **dual-sourced** (a real citation per side, not a straw man).
- **Where the book sits** — name the book's position explicitly + the chapter,
  and concede what the opposing view gets right.
- **Verdict flag** — *well-supported* / *contested* / *dated* (the book's
  self-assessment, not a claim of absolute truth).
- **Open question** — what would resolve it; what to watch next.

Tier the evidence in prose so the reader can weight it: **T1** peer-reviewed /
preprint / lab report, **T2** institutional or first-party material with a
stake, **T3** practitioner essay or analyst note. Anchor exemplar:
`manning_causal_ai` (six debates D1–D6, dual-sourced positions, verdict flags,
T1/T2/T3 tiers). F is waiverable where a field genuinely has no live debates
(`gold_exceptions.debates_waiver` + justification).

### Source verification (ties to G5)

Both appendices make verifiable claims, so the guide's `review/gold_audit_*.md`
must carry an **"E/F source verification"** section (Gold G5) recording that
each F debate's cited sources were spot-checked against the live web and that
the E appendix's named surfaces (versions, prices, APIs) were confirmed current
as of its date stamp.

## Reference

- Convenience macros: per-guide `notes/notebook/notebook-extensions.sty`.
- Machine-readable enums: `shared/config/canonical_values.yaml`.
- Problem/vignette/drill macros: `shared/latex/los-macros.sty`. See
  [`macro_catalog.md`](macro_catalog.md).
- Quality metrics and targets: [`quality_targets.md`](quality_targets.md).
- Anti-pattern detector: `shared/audits/audit_margin_quality.py`.
