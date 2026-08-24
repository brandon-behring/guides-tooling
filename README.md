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
  audits/fleet/     audit_all_courses (Bronze/Silver), audit_silver(_fleet), audit_source_manifest,
                    audit_gold (G1–G7/GB), check_meap_freshness
  audits/guide/     the 13 per-guide T1 audits (atomicity, crossref, freshness, …)
  generate/         dashboards, fix_qa_check_cmds, bib_ledger_to_bib
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

## Testing & CI

```sh
python3 -m pytest          # config in pyproject [tool.pytest.ini_options]
```

CI (`.github/workflows/ci.yml`) runs two gates on every push/PR:

1. **Packaging smoke** — a *non-editable* `pip install .` followed by imports
   from outside the source tree. The `[tool.setuptools] packages` list is
   explicit; this is what catches a dropped subpackage (it once silently
   omitted `tooling.generate`).
2. **The test suite** (editable install).

Python floor is **3.10** (PEP-604 unions evaluated at runtime in qa/ and anki/).

Conventions enforced by tests:

- **Check-command vetting** (`tooling/qa/_check_exec.py`): `guide_qa.yaml`
  check/readiness commands run through the shell only after a token-stream vet
  (operator + executable allowlist). The fleet's 21 command shapes are pinned
  verbatim in `tooling/qa/tests/test_check_exec.py` — a vet change that would
  break a live guide fails there first.
- **Fail-loud** (`tooling/_fail_loud.py`): a scan/parse failure never degrades
  silently — it prints a greppable `[audit-error]` line on stderr, and modules
  with a result channel surface it there too (RED row / error field).

## Gold audits are machine-local

G3/G6 (and G7's dashboard reads) check **built artifacts**, which are
gitignored — a fresh checkout scores 0 Gold everywhere. Rebuild first
(~4 min on 16 cores, from the host repo root):

```sh
ls */*/guide/Makefile | xargs -P 16 -I{} make -C "$(dirname {})" pilot
make dashboards && make decks-all
make audit-gold            # then audit
```

Exit codes: `audit_gold` exits 1 when any audited guide classifies
FAIL/SCAFFOLD-ONLY — in fleet mode **and** `--guide` mode (single-guide
exit-0-on-FAIL was a defect, fixed 2026-08). GOLD-ELIGIBLE exits 0.
