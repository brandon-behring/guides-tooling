# MEAP Freshness & Auto-Refresh Standard

> Authoritative as of 2026-05-30. Keeps notebook guides built from Manning **MEAPs**
> (early-access, still-being-written books) in sync as chapters are added/revised and as
> Manning occasionally renames or discontinues a title.

## Why this exists

MEAPs are moving targets. A guide captured at v3 / 5 chapters can be v7 / 11 chapters months
later, and Manning sometimes **renames** a book's slug (e.g.
`a-damn-fine-stable-diffusion-book` → `beyond-slop`) or **pulls** one entirely. Without a
process, guides silently rot. This standard defines the artifacts + tooling that detect drift
and drive a refresh.

## Two-file model (never clobber authored content)

Each MEAP-based guide carries two files under `manning_<slug>/docs/review/`:

| File | Author | Role |
|------|--------|------|
| `cache_manifest.yml` | hand / `extract_remaining_manning.py` | **Source-of-truth provenance.** `livebook_slug`, `meap_version`, `extracted`, `planned_chapters`, `available_chapters`, and per-chapter `{n, title, url, sha256, html_bytes, text_chars}`. The sha256 is over the verbatim content-container HTML. Read by the checker; **never overwritten** by it. |
| `freshness_state.yml` | `check_manning_meap_freshness.py` | **Machine state.** `last_checked`, `status`, `signature`, `captured_chapters`, `latest_release_note`, `drift`. Idempotent; safe to delete (regenerated). |

The canonical hand-authored example is `manning_designing_ai_agents/docs/review/cache_manifest.yml`.
Guides lacking a `cache_manifest.yml` get a **minimal** one (marked `_generated_by`) bootstrapped
on first clean check; per-chapter `sha256` is backfilled on the first `--refresh`.

## The checker — `scripts/check_manning_meap_freshness.py`

Detection runs against the **public product page** (`manning.com/books/<slug>`) over plain
HTTP — **no subscription auth**, so it works headless / under cron. It compares a content
signature (TOC chapter titles + latest-release note) against the per-guide baseline.

```bash
make meap-freshness                                   # check all ~27 MEAP guides -> Report B
python3 scripts/check_manning_meap_freshness.py --slug rlhf_book
python3 scripts/check_manning_meap_freshness.py --refresh --slug multi_agent_from_scratch --dry-run
python3 scripts/check_manning_meap_freshness.py --snapshot reports/_scratch/manning_live.json  # offline diff
```

### Status vocabulary

| Status | Meaning | Action |
|--------|---------|--------|
| `OK` | Signature unchanged since last check | none |
| `STALE` | Product page changed (new/revised chapters) | `--refresh` |
| `STALE?` | First-run estimate: book's latest released chapter > what the guide covers | inspect, likely `--refresh` |
| `RENAMED` | Manning changed the slug (detected via redirect). **Persists every run** until fixed | rename guide dir + update `LIVEBOOK_SLUGS`/`SLUG_OVERRIDES`, then `--refresh` |
| `BASELINE` | Baseline recorded this run; drift detection active next run | none |
| `UNRESOLVED` | No livebook slug known | add to `SLUG_OVERRIDES` in the checker |
| `ERROR` | Fetch/parse failure; `404` ⇒ book possibly discontinued | verify slug / confirm pulled |

Slug resolution order: **hand-authored** `cache_manifest.livebook_slug` → `SLUG_OVERRIDES`
→ `extract_livebook.LIVEBOOK_SLUGS`. Tool-bootstrapped manifests are ignored for resolution so a
`RENAMED` keeps re-flagging until a human acts (prevents silent self-heal).

### Version tracking (authenticated — the precise signal)

MEAPs carry an explicit `vN`, but it is **not on the public product page** (which shows only
"MEAP began" / "Publication in" dates — the `v1/v2/v3` there are site-asset versions). The version
+ last-updated date are exposed on the **authenticated dashboard** ("recently updated" feed) as
`version: N, last updated: YYYY-MM-DD`. Capture them via an authenticated Playwright session into
`reports/_scratch/manning_versions_<date>.json`:

```json
{ "versions": { "building-reliable-ai-systems": { "version": 12, "last_updated": "2026-05-27" } } }
```

Dashboard scan (`browser_evaluate` on `https://www.manning.com/dashboard`): for each
`a[href*="/books/"]` card read `version:\s*(\d+)` and `last updated:\s*(\d{4}-\d\d-\d\d)` (keys are
the **live** post-rename slugs). Then enrich detection with `--versions <file>` — the
`make meap-freshness` target auto-uses the newest snapshot if present. A guide goes **STALE** when
the upstream `vN` exceeds the manifest's `meap_version`, **or** when `last_updated` is newer than
the guide's build date (manifest `extracted`, else built-PDF mtime). Coverage = whatever the
dashboard recently-updated feed surfaces (i.e. the books that actually moved); everything else
falls back to the auth-free signature.

## Refresh workflow (`--refresh`)

Steady-state goal: an **auto-refreshed guide**. `--refresh --slug <guide>` orchestrates:

1. **Re-capture** changed/new chapters via `extract_remaining_manning.py --slug <guide>`
   (**authenticated** liveBook — the one auth-sensitive step).
2. **Diff** new per-chapter `sha256` vs `cache_manifest.yml` → identify exactly what changed.
3. **Author** the changed/added chapter sections (scaffold via `/new-course-guide`).
4. **QA**: re-extract Anki cards + `make qa` gate before the PDF is accepted.
5. **Bump** `meap_version` / `extracted`; re-run `--check` (expect `OK`).

**Honest boundary:** steps 1, 2, 4, 5 are mechanical and automatable. Step 3 (net-new chapter
*prose*) is drafted but warrants a human review pass — true silent hands-off authoring is the
target, not a guarantee. The QA gate is what prevents a regression from shipping. `--dry-run`
prints the plan without mutating anything.

## Trigger & cadence

- **Now (manual):** `make meap-freshness` on demand. Detection needs no auth, so it runs anywhere.
- **Promote to scheduled (one step):** wrap `make meap-freshness` in a `/schedule` monthly
  routine that opens Report B / pings on any non-`OK`/`BASELINE` row. Detection is auth-free so
  the **check** runs fine headless; only `--refresh` needs the authenticated browser/persistent
  profile — keep refresh human-triggered (or run it in an authenticated session).
- **Most precise upgrade (event-driven):** watch Gmail for Manning MEAP-update emails and fire
  `--refresh --slug <that book>` on arrival — zero polling, exact targeting. Not wired by default.

## Coverage

All MEAP-based guides (`pub_status: meap` in `scripts/manning_catalog.yaml`, ~27 today). New MEAP
guides are covered automatically once built — they appear in the catalog and the checker picks
them up. New-build candidates are tracked separately in the periodic
`reports/manning_meap_priority_<date>.md`.
