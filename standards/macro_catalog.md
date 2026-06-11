# Macro Catalog

Reference list of LaTeX macros available to chapter authors. Defined in
`tooling/latex/los-macros.sty` (universal, 942 lines) and per-guide
`guide/notebook-extensions.sty` (guide-specific extensions).

This catalog is hand-curated and may lag the source; when in doubt, grep
`tooling/latex/los-macros.sty` for the authoritative signatures.

## Chapter headers

| Macro | Signature | Purpose |
|-------|-----------|---------|
| `\moduleheader` | `\moduleheader{ID}{Title}{Summary}` | Preferred chapter opener; creates a numbered module with summary block |
| `\companytags` | `\companytags{meta, tags, role/company/level}` | Metadata tag (no visual output; extracted for filtering) |

Non-modular guides may use `\chapter{}` directly, but `\companytags` and the
learning-outcomes block must follow immediately.

## Learning outcomes

```latex
\begin{learningoutcomes}
  \los{TRB-1.1}{explain}{Articulate why RLHF is needed in the LLM training pipeline}
  \los{TRB-1.2}{define}{Define reward model, policy, and reference model}
  % ...
\end{learningoutcomes}
```

| Macro | Signature | Validation |
|-------|-----------|-----------|
| `\begin{learningoutcomes}...\end{learningoutcomes}` | — | At least one `\los{}` inside |
| `\los` | `\los{ID}{level}{statement}` | ID unique per guide; level ∈ 10 canonical levels ([`learning_outcomes.md`](learning_outcomes.md)) |

## Vocabulary

| Macro | Signature | Purpose |
|-------|-----------|---------|
| `\term` | `\term[LOS]{name}{definition}` | Inline glossary definition; extracted as `term` card |
| `\clozeterm` | `\clozeterm[LOS]{term}{definition}` | Anki-native cloze deletion |
| `\termbi` | `\termbi{term}{definition}` | Bidirectional term lookup |

## Boxes

| Environment | Signature | Card type |
|-------------|-----------|-----------|
| `keyconcept` | `\begin{keyconcept}[Title][LOS]...\end{keyconcept}` | `keyconcept` |
| `interviewcontext` | `\begin{interviewcontext}[Title][LOS]...\end{interviewcontext}` | `interview` / `interviewcontext` |
| `narrativebox` | `\begin{narrativebox}...\end{narrativebox}` | not extracted (prose) |

## Margins (convenience macros)

All expand to `\marginnote[<Category>]{<text>}`. Never use raw `\marginnote[...]{...}`.

| Macro | Category | Purpose |
|-------|----------|---------|
| `\interviewmargin{text}` | Interview | Company signal |
| `\patternmargin{text}` | Pattern | Recitable procedure / mnemonic |
| `\formulamargin{text}` | Formula | Instantiated formula |
| `\warningmargin{text}` | Warning | Common mistake + direction |
| `\practicemargin{text}` | Practice | Time target + technique |
| `\crossrefmargin{text}` | Cross-Ref | Pointer to another guide |

See [`content_design.md`](content_design.md) for craft rules per category.

Note: `\warningmargin` expands to `\marginnote[Warning]{text}` (the old
`content-quality.md` had a typo that said `\marginwarning[Warning]{text}`;
retired 2026-04-19).

## Exercises

| Environment | Signature | Card type |
|-------------|-----------|-----------|
| `problem` | `\begin{problem}[Title][LOS][Difficulty][Scaffolding]...\end{problem}` | `problem` |
| `vignette` | `\begin{vignette}[Title][LOS]...\end{vignette}` | `vignette` |
| `drill` | `\begin{drill}[LOS]...\end{drill}` | `drill` |

| Macro | Signature | Purpose |
|-------|-----------|---------|
| `\substep` | `\substep{label}{content}` | Auto-numbered step within a solution |

## Specialized (used where pedagogically appropriate)

| Macro / Environment | Signature | Card type |
|---------------------|-----------|-----------|
| `\levelcard` | `\levelcard{Title}[LOS]` | `levelcard` — IC4 vs IC5 comparison |
| `\comparisoncard` | `\comparisoncard{Title}{ColA}{ColB}[LOS]` | `comparison` — 2-column |
| `\comparisoncard3` | (3-column variant) | `comparison3` |
| `\sixtysec` | `\sixtysec[Title]{content}` | `sixtysec` — 60-second explanation |
| `\interviewtip` | `\interviewtip{content}` | `interviewtip` |
| `\starstory` | `\starstory{situation}{task}{action}{result}` | `starstory` — STAR behavioral |
| `\paradox` | `\paradox{situation}{resolution}` | `paradox` |
| `\actuarialbridge` | `\actuarialbridge{soa}{ds}` | `actuarialbridge` — SOA → DS mapping |
| `\redflag` / `redflag` env | `\begin{redflag}...\end{redflag}` | `redflag` — common-mistake box |
| `\generatefirst` / env | `\begin{generatefirst}...\end{generatefirst}` | `generatefirst` — generation-before-reading |
| `\formula` / `formulacard` env | `\begin{formulacard}...\end{formulacard}` | `formula` |
| `decisiontree` env | `\begin{decisiontree}...\end{decisiontree}` | `decisiontree` |
| `\mathdef` | `\mathdef{name}{def}` | `mathdef` — math-reference definition |
| `\proposition` | `\proposition{stmt}{proof}` | `proposition` |
| `\theorem` | `\theorem{stmt}{proof}` | `theorem` |
| `\pitfall` | `\pitfall{description}` | `pitfall` |

## Per-guide extensions

Each guide's `guide/notebook-extensions.sty` may define guide-local
macros. These are not fleet-wide and should not be assumed portable. If ≥3
guides share an extension, consider promoting it to
`tooling/latex/los-macros.sty` (discussed in the remediation plan).

## Reference

- Universal macros: `tooling/latex/los-macros.sty` (942 lines).
- Per-guide extensions: each guide's `guide/notebook-extensions.sty`.
- Card extractor (reads these macros): `tooling.cards.extract_cards`.
- Machine-readable margin category list: `tooling/config/canonical_values.yaml`.

## Known overfitting risk

The canonical macro list above was verified against `tooling/latex/` and
`evaluation-alignment-safety/manning_rlhf_book/guide/notebook-extensions.sty` during the
2026-04-19 consolidation. A fleet-wide scan of every guide's
`notebook-extensions.sty` to classify macros as
**fleet-shared / family / guide-local / deprecated** is a deferred
follow-up. Until that lands, this catalog may overfit to the Manning
pattern. If you need a macro that's in your guide's extensions but absent
here, the extensions file is authoritative.
