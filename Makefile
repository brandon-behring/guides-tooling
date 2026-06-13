# guides-tooling — host-includable target library.
#
# Mounted as a submodule at <host>/tooling/. A consuming guide's Makefile does:
#
#     MAIN    = main
#     TOOLING ?= ../../../tooling       # from <topic>/<slug>/guide/ to <host>/tooling
#     include $(TOOLING)/Makefile
#     # ... plus the guide's own PDF targets (pilot/digital/print/clean)
#
# A host-root Makefile that wants the fleet targets does:
#
#     TOOLING ?= tooling
#     include $(TOOLING)/Makefile
#
# Tools run as `python -m tooling.<group>.<tool>` with the mount on PYTHONPATH
# (no install required; `pip install -e $(TOOLING)` also works if preferred).

PY      ?= python3
TOOLING ?= .
MAIN    ?= main
export PYTHONPATH := $(TOOLING):$(PYTHONPATH)

# ── Per-guide (run from <guide>/guide/) ──────────────────────────────────────
.PHONY: cards qa-refs qa-los qa-presentation qa-health qa-ready decks
cards:
	$(PY) -m tooling.cards.extract_cards chapters/*.tex appendices/*.tex -o cards/
qa-refs:
	$(PY) -m tooling.validation.check_refs chapters/*.tex appendices/*.tex
qa-los:
	$(PY) -m tooling.validation.extract_los chapters/*.tex --validate
qa-presentation:
	$(PY) -m tooling.validation.check_latex_warnings $(MAIN).log
qa-health:
	$(PY) -m tooling.qa.guide_health --config ../guide_qa.yaml
qa-ready:
	$(PY) -m tooling.qa.guide_readiness --config ../guide_qa.yaml
decks:
	$(PY) -m tooling.anki.yaml_to_apkg cards/all_cards.yml -o decks/ --config ../guide_qa.yaml

# ── Fleet (run from the <host> repo root) ────────────────────────────────────
.PHONY: audit-all audit-manifests audit-gold meap-freshness runon dashboards decks-all fix-qa-cmds
audit-all:
	$(PY) -m tooling.audits.fleet.audit_all_courses
audit-gold:
	$(PY) -m tooling.audits.fleet.audit_gold $(if $(GUIDE),--guide $(GUIDE)) $(ARGS)
# DRY_RUN=1 applies only with REFRESH=1; detection always writes freshness_state.yml
# unless NO_WRITE=1.
meap-freshness:
	$(PY) -m tooling.audits.fleet.check_meap_freshness \
	  $(if $(SLUG),--slug $(SLUG)) $(if $(SNAPSHOT),--snapshot $(SNAPSHOT)) \
	  $(if $(VERSIONS),--versions $(VERSIONS)) $(if $(REFRESH),--refresh) \
	  $(if $(DRY_RUN),--dry-run) $(if $(NO_WRITE),--no-write) $(ARGS)
runon:
	$(PY) -m tooling.audits.fleet.audit_runon_lists
audit-manifests:
	$(PY) -m tooling.audits.fleet.audit_source_manifest --all
dashboards:
	$(PY) -m tooling.generate.dashboards
decks-all:
	$(PY) -m tooling.anki.build_all
fix-qa-cmds:
	$(PY) -m tooling.generate.fix_qa_check_cmds $(ARGS)
