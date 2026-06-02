# Agent Navigation

This is the canonical "where do I find X?" table for AI agents working in this
repo. Each row has **exactly one pointer** in column 2 — when multiple sources
are listed in column 3 ("see also"), the column-2 file is authoritative.

## Quick lookup

| Question | Canonical answer | See also |
|----------|------------------|----------|
| What's the workspace skeleton? | [`00_universal/workspace_structure.md`](workspace_structure.md) | family overlays for per-family deviations |
| What are valid LOS / Bloom's cognitive levels? | [`00_universal/learning_outcomes.md`](learning_outcomes.md) | `shared/config/canonical_values.yaml` (machine-readable) |
| What are the 6 margin categories? | [`00_universal/content_design.md`](content_design.md) | `shared/config/canonical_values.yaml` |
| What card types exist? | [`00_universal/card_standards.md`](card_standards.md) | `shared/cards/extract_cards.py` (the actual extractor) |
| How are card IDs formatted? | [`00_universal/card_standards.md`](card_standards.md) §Card ID convention | `shared/cards/extract_cards.py` (`seen_ids`) |
| What's the Anki deck schema? | [`00_universal/card_standards.md`](card_standards.md) §Anki schema | `manning_rlhf_book/guide_qa.yaml` (worked example) |
| What macros can I use in chapter `.tex`? | [`00_universal/macro_catalog.md`](macro_catalog.md) | `shared/latex/los-macros.sty`; per-guide `notebook-extensions.sty` |
| How dense should margin notes be? | [`00_universal/content_design.md`](content_design.md) §Density | — |
| What should a problem card's solution include? | [`00_universal/content_design.md`](content_design.md) §Problems and `00_universal/card_standards.md` | — |
| How do I scaffold a new guide? | [`.claude/commands/new-course-guide.md`](../../../.claude/commands/new-course-guide.md) | this README and the family overlay matching the new guide |
| What's the Manning provenance contract? | [`10_manning/overlay.md`](../10_manning/overlay.md) | `scripts/manning_catalog.yaml` |
| How does DLAI extract VTT transcripts? | [`20_dlai/overlay.md`](../20_dlai/overlay.md) | `scripts/scrape_workflow.md` |
| How is Coursera multi-course structured? | [`30_coursera/overlay.md`](../30_coursera/overlay.md) | per-spec `course_info.yaml` files |
| Where do nonconforming guides live? | [`99_other/overlay.md`](../99_other/overlay.md) | — |
| Where are audit scripts? | [`00_universal/audit_catalog.md`](audit_catalog.md) | `shared/audits/` directory |
| What's the Makefile QA target list? | [`00_universal/audit_catalog.md`](audit_catalog.md) §Makefile targets | per-guide `notes/notebook/Makefile` |
| What's the validation script list? | [`00_universal/audit_catalog.md`](audit_catalog.md) §Validation scripts | `shared/validation/` directory |
| What's the canonical macro list? | [`00_universal/macro_catalog.md`](macro_catalog.md) | `shared/latex/los-macros.sty` |
| What's a "gold-standard" guide? | [`00_universal/tier_model.md`](tier_model.md) | per-family overlays for tier calibration |
| What blocks Silver tier promotion? | [`00_universal/tier_model.md`](tier_model.md) §Silver | — |
| When do I delete vs archive a doc? | [`00_universal/document_lifecycle.md`](document_lifecycle.md) | — |
| How are stale fleet audit reports handled? | [`00_universal/document_lifecycle.md`](document_lifecycle.md) §Auto-generated artifacts | — |
| Where do I track issues? | [`docs/remediation/README.md`](../../remediation/README.md) | per-priority files in same dir |
| Where's the cross-guide learning graph? | [`docs/architecture.md`](../../architecture.md) | `00_universal/cross_references.md` for the *standard* |
| What's the role-aligned interview prep contract? | [`00_universal/interview_standard.md`](interview_standard.md) | `manning_llm_from_scratch/notes/interview_connections.md` (exemplar) |
| What targets does the dashboard report? | [`00_universal/quality_targets.md`](quality_targets.md) | per-guide `guide_qa.yaml.metrics` |
| Where do per-guide-specific instructions live? | The guide's own `CLAUDE.md` | template at `templates/CLAUDE.guide.md.template` |
| What's the per-guide `guide_qa.yaml` schema? | [`00_universal/audit_catalog.md`](audit_catalog.md) §guide_qa.yaml schema | `shared/templates/guide_qa.yaml.template` |
| How do I migrate a guide's `CLAUDE.md` to the new template? | [`templates/CLAUDE.guide.md.template`](../templates/CLAUDE.guide.md.template) | 3 example migrations: `manning_rlhf_book/`, `dlai_claude_code_assistant/`, `coursera_data_engineering/` |
| How do I write a source manifest? | [`templates/source_manifest.md.template`](../templates/source_manifest.md.template) | per-family overlays for family-specific fields |
| What's the remediation roadmap? | [`docs/plans/standards_remediation_2026-04-19.md`](../../plans/standards_remediation_2026-04-19.md) | latest `reports/qa_fleet_audit_*.md` for fleet baseline |

## Navigation principles

1. **Universal core wins for craft details.** If you need to know how a margin
   note works, read `content_design.md`, not a family overlay.
2. **Family overlays win for source-pipeline and contract details.** If you
   need to know how Manning extracts PDFs vs how DLAI scrapes VTTs, the
   overlay is authoritative.
3. **Per-guide `CLAUDE.md` is for guide-specific deviations only**, not for
   restating universal standards. If a guide's `CLAUDE.md` contradicts the
   standards, the standards win and the `CLAUDE.md` should be migrated.
4. **Auto-generated artifacts are not edited by hand.** Per-guide
   `dashboard.md`, `readiness-*.md`, fleet `qa_fleet_audit_*.md` files are
   regenerated by scripts. To change them, change the script.
5. **When in doubt, run the audit.** `python3 scripts/audit_all_courses.py
   --summary` is the source of truth for current fleet state.

## What is NOT in this index

- **The cross-guide learning graph** itself (which guide leads to which).
  That's in `docs/architecture.md`. This file points you there but does not
  duplicate the graph.
- **Specific guide content.** This file is about *where standards live*, not
  *what any specific guide teaches*.
- **Implementation details of audit scripts.** Read the script source for
  that. This file points at the catalog (`audit_catalog.md`) which describes
  *what each script measures*, not *how it computes the measure*.
