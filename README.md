# guides-tooling

Shared QA / build / card tooling for the course-guide family
(`guides-coursera` · `guides-dlai` · `guides-manning`). A clean redesign of the
`shared/` + `scripts/` tooling that grew inside the `course_learning` monorepo.

It is consumed as a **git submodule mounted at `<host>/tooling/`** and serves the
**`guide/` role layout** only.

## Design

- **One package, one namespace.** Everything is `import tooling.*` — no `sys.path`
  manipulation, no dual import idioms.
- **One mount-relative resolver** (`tooling/paths.py`):
  - `package_root()` → `<host>/tooling` — this submodule (the data dirs `latex/`,
    `templates/`, `standards/`, `config/`).
  - `host_root()` → `<host>` — the consuming repo (where `guides.yml` and the
    `*/guide/` guides live). Parent of the mount. Override with `$GUIDES_HOST_ROOT`.
- **guide/-only.** No `notes/notebook/` fallback (that was a migration artifact).

## Layout

```
tooling/            the Python package
  paths.py          host_root() / package_root() + data-dir helpers   ← the resolver
  scope.py          guides.yml registry (GuideInfo + getters)
  layout.py         guide/ artifact paths (chapters, cards, appendices, review/…)
  discovery.py      iter_guide_dirs() over the host repo
  validation/       check_refs, extract_los, check_duplicates, check_latex_warnings
  cards/            extract_cards, render_tikz, generate_anki, combine, validate
  anki/             yaml_to_apkg, anki_common, format_card_text
  qa/               guide_qa_config, guide_health, guide_readiness
  audits/fleet/     audit_all_courses (Bronze/Silver), audit_silver(_fleet), audit_source_manifest
latex/  templates/  standards/ (+ system_design_allowlist.yaml)  config/   ← data
Makefile            host-includable target library
```

## Host contract

A guide's `guide/Makefile`:

```make
MAIN    = main
TOOLING ?= ../../tooling          # relative to the guide/ dir (depth-aware)
include $(TOOLING)/Makefile        # cards / qa-* / decks targets
# ... the guide keeps its own PDF targets (pilot / digital / print / clean)
```

A host-root Makefile (for the fleet targets):

```make
TOOLING ?= tooling
include $(TOOLING)/Makefile         # audit-all / audit-manifests
```

Tools run as `python -m tooling.<group>.<tool>`. The `Makefile` puts the mount on
`PYTHONPATH` (no install needed); `pip install -e tooling/` is an equivalent option.

LaTeX styles: each guide's `guide/shared/*.sty` symlinks point into `…/tooling/latex/`
(re-pointed per guide at carve time, depth-aware).

## First cut

This is the hot-path first cut (a guide builds + per-guide QA + the Bronze/Silver
fleet audit run as a submodule). Deferred to a second cut: the new-workspace
`generate/` engine, the gold/quality/drift auditors, the card/content auditors +
autofixers, scaffolders, and cross-guide tools.
