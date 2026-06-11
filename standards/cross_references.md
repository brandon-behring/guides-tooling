# Cross References

Standard for how guides cross-reference each other via `\crossrefmargin{}`
and how they participate in the cross-guide learning graph.

This file owns the **standard** for authoring those references. The cross-guide
learning graph itself is emergent — it is the set of `\crossrefmargin{}` edges
across the fleet, not a separate document. (A consolidated study-order map is
roadmap C1, `STUDY_ORDER.md`, not yet in-repo.)

## Cross-reference policy

- Every gold-tier guide must have **at least 2 valid `\crossrefmargin{}`**
  to prerequisite, complementary, or follow-on guides.
- Cross-references must be **directional**: state what the other guide
  provides that this one does not.
- Cross-references must use the **directory names that exist today**.
  Renaming a workspace breaks every `\crossrefmargin{}` pointing at it.

## `\crossrefmargin{}` format

```latex
\crossrefmargin{[Topic]: [Guide] Ch M ([LOS prefix])}
```

Or:

```latex
\crossrefmargin{For [topic], see [Guide] Ch M}
```

Examples:

```latex
\crossrefmargin{For production permutation test code, see CI Python Ch 9.2}
\crossrefmargin{Theory foundation: Experimentation Guide Ch 4 (power analysis)}
\crossrefmargin{For sklearn feature pipelines, see ML Foundations Ch 11}
```

The `\crossrefmargin{}` macro is a thin wrapper around
`\marginnote[Cross-Ref]{...}`. See
[`content_design.md`](content_design.md) for the per-category craft rule.

## When to cross-reference

A `\crossrefmargin{}` is appropriate when:
- Another guide proves a result this guide states (theory).
- Another guide implements a method this guide describes (production code).
- Another guide goes deeper on a topic this guide touches lightly.
- Another guide is a prerequisite the reader should consult first.

A `\crossrefmargin{}` is **not** appropriate for:
- Generic "see other guide" pointers without saying what's there.
- Self-references within the same guide (use `\ref{}` instead).
- External non-guide resources (use `\cite{}` for academic references).

## Cluster examples

The cross-reference standard is especially important for these clusters:

- **NLP path**: NLP basics → transformers → LLM-from-scratch
- **RAG path**: search → RAG → GraphRAG → knowledge graphs
- **DL foundations**: ML / DL foundations → PyTorch / JAX / CUDA
- **Agents**: agents → RAG / memory / tool use / evaluation
- **Fine-tuning**: fine-tuning → RLHF / reasoning / alignment

Within each cluster, every guide should cross-reference at least 1
prerequisite and at least 1 follow-on (where they exist in the fleet).

## Validity

`audit_crossref_quality.py` validates:
- `\crossrefmargin{}` content references a directory or path that exists.
- The pointed-at guide also exists in the fleet.
- No circular hard prerequisites (A → B → A).
- Required directional language (not just "see X").

## The cross-guide graph

The cross-guide learning graph is not a separate document: it is the set of
`\crossrefmargin{}` edges authored across the fleet (each note names what another
guide provides). A consolidated prerequisite map / learning-paths-by-goal view is
roadmap C1 (`STUDY_ORDER.md`), not yet in-repo. This file owns only the
*standard for how to cross-reference*.

## Migration note (2026-04-19)

The MEAP-rename mandate from the old Manning gold spec was dropped. MEAP
guides keep their `manning_<slug>` directory name. Therefore
`\crossrefmargin{}` to `manning_*` paths continues to be correct. There is
no MEAP-related rename remediation to do.

## Reference

- Macro: `\crossrefmargin{...}` in per-guide `guide/notebook-extensions.sty`.
- Audit: the `audit_crossref_quality` per-guide audit (see [`audit_catalog.md`](audit_catalog.md)).
- Graph: emergent from the fleet's `\crossrefmargin{}` edges; consolidated map = roadmap C1 (`STUDY_ORDER.md`).
- Per-category craft for cross-ref notes: `content_design.md` §[Cross-Ref].
