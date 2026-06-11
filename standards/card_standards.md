# Card Standards

The full catalog of Anki card types, templates, splitting policy, ID
convention, and deck configuration. Consolidates and supersedes
`.claude/rules/card-standards.md`.

## Card type catalog (20+ types)

Supported by `tooling.cards.extract_cards`. Each card type is extracted from
a specific LaTeX macro or environment. All types accept an optional `[LOS-ID]`
parameter linking the card to a learning outcome.

### Common (used across most guides)

| Type | Extracted from | LOS-linked? | Purpose |
|------|---------------|-------------|---------|
| `term` | `\term[LOS]{name}{definition}` | optional | Inline glossary definitions |
| `keyconcept` | `\begin{keyconcept}[Title][LOS]...\end{keyconcept}` | optional | Core-insight boxes |
| `checkpoint` | Chapter-end checkpoint questions (author-defined pattern) | yes | Low-stakes recall checkpoints |
| `problem` | `\begin{problem}[Title][LOS][Difficulty][Scaffolding]...\end{problem}` + solution | required | Exercises with worked solutions |
| `vignette` | `\begin{vignette}[Title][LOS]...` | optional | Case-study judgment questions |
| `drill` | `\begin{drill}[LOS]...\end{drill}` | optional | Quick calculation practice |
| `interview` / `interviewcontext` | `\begin{interviewcontext}[Title][LOS]...` | optional | Interview-focused contexts |

### Specialized (used where pedagogically appropriate)

| Type | Extracted from | Purpose |
|------|---------------|---------|
| `redflag` | `\begin{redflag}...` | Common-mistake boxes |
| `formula` | `\begin{formulacard}...` or `\formula{...}` | Formula cards with LaTeX math |
| `decisiontree` | `\begin{decisiontree}...` | Method-selection decision frameworks |
| `levelcard` | `\levelcard{Title}[LOS]` | IC4 vs IC5+ contrast tables |
| `comparison` | `\comparisoncard{Title}{ColA}{ColB}[LOS]` | 2-column comparisons |
| `comparison3` | `\comparisoncard3{...}` | 3-column comparisons |
| `sixtysec` | `\sixtysec[Title]` | 60-second explanation prompts |
| `interviewtip` | `\interviewtip{...}` | Interview-specific pointers |
| `starstory` | `\starstory{...}` | STAR-method behavioral stories |
| `paradox` | `\paradox{...}` | Counterintuitive result + resolution |
| `actuarialbridge` | `\actuarialbridge{...}` | SOA → DS mapping (actuarial-specific) |
| `cloze` / `clozeterm` | `\clozeterm[LOS]{term}{definition}` | Anki-native cloze deletion |
| `termbi` | Bidirectional `\termbi{...}` | Term + reverse definition |
| `mathdef` / `proposition` / `theorem` | math-reference macros | Math-reference definitions |
| `pitfall` | `\pitfall{...}` | Pitfall boxes |
| `generatefirst` | `\begin{generatefirst}...` | Generation-before-reading prompts |

Machine-readable list: `tooling/config/canonical_values.yaml` (`card_types`
key, split into `common` and `specialized`).

## Card YAML schema

```yaml
- id: trb-m1-1-TERM-cuped       # See Card ID convention below
  type: term                     # One of the types above
  front: "Define: CUPED"
  back: |
    Controlled-experiment Using Pre-Experiment data. A variance-reduction technique...
  source: m1_01_introduction.tex # Relative path under chapters/
  los_id: TRB-1.2                # Optional; required for learning-objective cards
  scaffolding_level: partial     # none | partial | full; assigned per-type by default
  tags:
    - m1
    - term
    - los:TRB-1.2
```

## Card ID convention

Format: `{los_prefix_lower}-{volume}-{chapter}-{TYPE}-{slug}`

Examples:
- `trb-m1-1-TERM-cuped` (RLHF Book, module 1, chapter 1, term card on CUPED)
- `bll-m3-2-PROBLEM-bpe-training` (LLM from Scratch, module 3, chapter 2)

Enforcement: `tooling.cards.extract_cards` maintains a `seen_ids` set and fails
extraction on collision. IDs are deterministic (same LaTeX input → same ID
across rebuilds).

## Card presentation rules

Structured for scannable Anki review.

### Core principles

1. **Scannable structure** — bullets, headers, whitespace.
2. **One concept per visual block** — separate with blank lines.
3. **Bold keywords** — headers like `**Approach:**` guide the eye.
4. **Lists on separate lines** — never run items together.

### Card type templates

**`term`**
```yaml
type: term
front: "Define: [Term]"
back: |
  [1-2 sentence definition]

  **Components:**
  - [Component 1]
  - [Component 2]

  **Example:**
  [Concrete example]

  **Interview Context:**
  [When/how this comes up]
```

**`problem`**
```yaml
type: problem
front: "[Problem statement with context]"
back: |
  **Approach:**
  [High-level strategy in 1-2 sentences]

  ---

  **Step 1: [Label]**
  [Calculation or reasoning]

  **Step 2: [Label]**
  [Calculation or reasoning]

  ---

  **Key Insight:**
  [Why this approach works / what the interviewer wants to see]

  ---

  **Answer:**
  [Final answer with units, bold]
```

**`keyconcept`**
```yaml
type: keyconcept
front: "Key Concept: [Title]"
back: |
  **Core Insight:**
  [1-2 sentence central claim]

  **Why It Matters:**
  [When/how to apply]

  **When It Breaks:**
  [Conditions where this fails]
```

**`vignette`**
```yaml
type: vignette
front: "Case Study: [Title]"
back: |
  **Scenario:**
  [Context and setup - 2-3 sentences]

  ---

  **Data:**
  | Metric | Value |
  |--------|-------|
  | ... | ... |

  ---

  **Questions:**

  **Q1:** [First question]

  **Q2:** [Second question]

  **Q3:** [Third question]
```

**`formula`**
```yaml
type: formula
front: "Formula: [Name]"
back: |
  $$[LaTeX formula]$$

  **Variables:**
  - $x$ = [meaning]
  - $y$ = [meaning]

  **When to Use:**
  [Conditions for applicability]

  **Intuition:**
  [Plain English explanation]
```

**`decisiontree`**
```yaml
type: decisiontree
front: "Decision: [Title]"
back: |
  **When to choose A:**
  - [Condition 1]
  - [Condition 2]

  **When to choose B:**
  - [Condition 1]
  - [Condition 2]

  ---

  **Decision Rule:**
  [1-2 sentence heuristic]
```

**`drill`**
```yaml
type: drill
front: "[Drill prompt — concise question]"
back: |
  **Answer:**
  [Direct answer with key values]

  ---

  **Technique:**
  [1-2 sentence strategy/shortcut]
```

## Splitting policy

Long cards degrade spaced-repetition review quality. Thresholds:

| Type | Split when | Structure required |
|------|-----------|-------------------|
| `problem` | back >800 chars | has `**Step N:**` sections |
| `vignette` | >4 questions OR >1000 chars | has `Question N:` markers |
| `keyconcept` | back >700 chars | has 4+ `**Header:**` sections |

**Never split:**

| Type | Why |
|------|-----|
| `formula` | Math must remain complete |
| `decisiontree` | Decision context needs both branches |

Split card format:
- Front: `"Original Front (Part N of M: Description)"`
- ID: `original_id_P1`, `original_id_P2`, ...
- Tags: adds `split_from:{original_id}` for traceability

## Formatting anti-patterns

**Run-on numbered lists**:
```
# BAD
Step 1: Calculate the baseline Step 2: Apply the adjustment

# GOOD
**Step 1:** Calculate the baseline

**Step 2:** Apply the adjustment
```

**Inline section headers**:
```
# BAD
Approach: ... Key Insight: ...

# GOOD
**Approach:**
...

**Key Insight:**
...
```

**Run-on bullets**:
```
# BAD
Key points: - First point - Second point - Third point

# GOOD
Key points:

- First point
- Second point
- Third point
```

## Exclusion patterns

Some blocks are preserved as-is (never reformatted):

- `\begin{minted}` — code blocks
- `\begin{align}` — multi-line math
- `\begin{tabular}` — tables
- `\begin{equation}` — display equations

The card-presentation fix automation skips cards containing these.

## Scaffolding levels

Assigned automatically by `tooling.cards.extract_cards` based on card type:

| Type | Default scaffolding |
|------|---------------------|
| `problem` | `partial` |
| `vignette` | `full` |
| `drill` | `none` |
| others | `none` |

Override via the `\problem[Title][LOS][Difficulty][Scaffolding]` optional
parameter (and similar for other scaffolded types).

## LOS traceability

100% of learning-objective cards (problem, vignette, interview, drill) must
carry a valid `los_id`. Measured by the `audit_card_quality` per-guide audit
(`tooling.audits.guide.*`; see [`audit_catalog.md`](audit_catalog.md)).

## Anki deck configuration

Per-guide `guide_qa.yaml.anki` section configures how cards are grouped into
decks:

```yaml
anki:
  deck_prefix: "The RLHF Book"        # Anki hierarchy root
  separator: "::"                     # nested hierarchy delimiter
  source_pattern: "(m\\d+)_"          # regex to extract module key from card.source
  course_key_prefix: ""               # added to extracted key before lookup
  course_map:
    m1: {name: "Ch01 Introduction",  file_stem: "RLHF_Ch01_Introduction"}
    m2: {name: "Ch02 History",       file_stem: "RLHF_Ch02_History"}
    # ... one entry per module
```

Worked example: `evaluation-alignment-safety/manning_rlhf_book/guide_qa.yaml`.

Large guides should produce per-chapter `.apkg` decks plus a complete deck.
Small guides may produce only a complete deck if documented in
`guide_qa.yaml`.

## Card quality targets

See [`quality_targets.md`](quality_targets.md) for the canonical metric table.
Highlights:

| Metric | Target |
|--------|--------|
| LOS traceability | 100% for learning-objective cards |
| Thin cards | <5% |
| Term-card ratio | <60% |
| Broken LaTeX | 0 |
| ID collisions | 0 |
| Solution completeness | 100% for problem/vignette |

## Back-content quality rules

A card's back must be a **substantive answer**, not a pointer to one.
Anti-patterns include: empty backs, TODO/PLACEHOLDER scaffolds,
truncation with trailing `...`, front-back duplication, and "see
Chapter X" evasive references with no actual content.

Per-card-type minimum back length (enforced by the `audit_back_content`
per-guide audit):

| Type | Min chars | Type | Min chars |
|------|-----------|------|-----------|
| `term` | 40 | `keyconcept` | 100 |
| `problem` | 100 | `vignette` | 200 |
| `checkpoint` | 30 | `drill` | 40 |
| `formula` | 50 | `redflag` | 50 |
| (default) | 30 | | |

Per-type structural requirements (HIGH-severity audit findings):

- **`keyconcept`**: must have either the canonical 3-part form
  (Core Insight + Why It Matters / When It Breaks) OR at least 2
  distinct bold/structured headers (e.g., comparisons, dichotomies).
  "Decision Rule" is accepted as a variant of "Why It Matters".
- **`formula`**: must have math markers (`$..$` or `\[..\]`) AND prose
  sections (Variables / When to Use / Intuition).
- **`drill`**: must have either `\textbf{Answer:}` section OR MCQ
  format (A./B./C./D. options with at least one bolded as the correct
  answer).
- **`comparison`/`comparison3`**: must include pipe-table separator
  (`|---|`).

`cloze`/`clozeterm` cards are exempt from empty-back and
front-back-duplicate checks (the answer lives in the front via
`{{c1::...}}` markers).

The `audit_back_content` per-guide audit ports into `tooling.audits.guide.*` in
roadmap T1; the Gold runner gates on it (CRITICAL+HIGH=0) in T2. Until those land it
is **not** wired into a `make` target here — run the legacy `audit_back_content.py`
from the `course_learning` repo.

Baseline thresholds (per guide, regression-checked):
each guide's `card_quality_baseline.json` — `back_content` section.

## Reference

- Extractor: `tooling.cards.extract_cards` (2800+ lines).
- Deck builder: `tooling.anki.yaml_to_apkg`.
- Audits: `audit_card_quality`, `audit_card_presentation`,
  `audit_atomicity`, `audit_term_consistency`,
  `audit_back_content` (back-content quality) — the per-guide audit
  suite (`tooling.audits.guide.*`), see
  [`audit_catalog.md`](audit_catalog.md).
- Machine-readable card type list: `tooling/config/canonical_values.yaml`.
