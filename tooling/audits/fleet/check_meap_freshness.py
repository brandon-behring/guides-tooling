#!/usr/bin/env python3
"""Manning MEAP freshness checker (roadmap T4) -- ``make meap-freshness``.

MEAPs are living documents: chapters get added/revised and books occasionally
get renamed on Manning's side. This keeps the 36 ``status: meap`` guides in sync
by detecting drift between what a guide captured and what the book looks like
*now*.

Ported from ``course_learning/scripts/check_manning_meap_freshness.py`` and
rewired onto ``tooling.*``: guides come from ``guides.yml`` (``status == "meap"``)
instead of a flat catalog; provenance/state live under each guide's nested
``review/`` dir; the livebook-slug map is inlined (no cross-repo import). The
detection logic, status machine, and Report B are carried over unchanged.

Design (runs anywhere, including headless/cron):
  * DETECTION (default) reads each book's PUBLIC product page
    (https://www.manning.com/books/<slug>) over plain HTTP -- no auth needed. It
    compares a content signature + latest-release note against a per-guide
    baseline (``review/freshness_state.yml``).
  * REFRESH (``--refresh``) re-captures changed chapters via the AUTHENTICATED
    livebook extractor -- auth-sensitive; deferred. This runner prints the plan
    (``--dry-run``) but does not execute the capture (the extractor lives in the
    legacy ``course_learning`` repo; see ``meap_freshness.md``).

Staleness semantics (revised 2026-08-24; guides-tooling#20): the auth-free
signature hashes the product page's month fields (``MEAP began`` / ``Last
updated`` / ``Publication in`` / ISBN / pages) -- the old TOC scrape hashed an
empty string on every page. STALE is now STICKY vs the guide's own capture:
whenever the live ``Last updated`` month postdates the manifest's
``extracted``/``captured`` month, the row stays STALE until a re-capture bumps
the manifest. The ``--versions`` overlay (an authenticated dashboard/liveBook
scan: live ``vN``/date) remains the precise signal and also elevates RENAMED
and UNRESOLVED rows.

Source-of-truth split (never clobber hand-authored files):
  * review/cache_manifest.yml  -- hand/extractor-authored MEAP provenance (READ
    only; minimally bootstrapped ONLY if entirely absent).
  * review/freshness_state.yml -- tool-written machine state. Idempotent.

Usage (via ``make meap-freshness`` -- the Makefile maps SLUG=/SNAPSHOT=/etc.):
    python -m tooling.audits.fleet.check_meap_freshness            # all MEAP -> Report B
    python -m tooling.audits.fleet.check_meap_freshness --slug rlhf_book
    python -m tooling.audits.fleet.check_meap_freshness --snapshot reports/_scratch/manning_live.json
    python -m tooling.audits.fleet.check_meap_freshness --refresh --slug multi_agent_from_scratch --dry-run
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import html as _html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import yaml

from tooling import layout, paths, scope
from tooling.audits.guide._guide_scope import guide_dir_for_slug

PRODUCT_URL = "https://www.manning.com/books/{slug}"
UA = "Mozilla/5.0 (guides-tooling meap-freshness checker)"
GUIDE_PREFIX = "manning_"

# Livebook slugs missing from / overriding the inlined map (verified via live
# browse 2026-05-30). Keyed by INTERNAL slug (the guide slug minus "manning_").
SLUG_OVERRIDES = {
    "designing_ai_agents": "designing-ai-agents",
    "vibe_engineering": "vibe-engineering",
    "software_engineering_data_scientists": "software-engineering-for-data-scientists",
    "sutskevers_list": "sutskevers-list",  # the apostrophe slug 404s
    # Live probes 2026-08-24 (ecosystem review; guides-tooling#21): renames + new slugs.
    "rlhf_book": "reinforcement-learning-from-human-feedback",
    "advanced_rag_app": "build-an-advanced-rag-application-from-scratch",
    "stable_diffusion_book": "local-image-generation",  # renamed twice (…beyond-slop→this)
    "ai_applications_made_easy": "grokking-ai-applications",
    "eval_alignment_seminal_papers": "llm-evaluation-and-alignment-the-foundational-ideas",
    "rag_seminal_papers": "retrieval-augmented-generation-the-foundational-ideas",
    "context_engineering": "context-engineering",
    "prompt_engineering_in_practice": "prompt-engineering-in-practice",
    "quantization_fast_inference": "quantization-and-fast-inference",
    "applied_rl": "applied-reinforcement-learning",
    "prompt_engineering_ai_systems": "prompt-engineering-for-ai-systems-cx",  # -cx variant is live
    "crewai_mcp": "building-agentic-applications-with-crewai-and-mcp-cx",  # -cx variant is live
}

# Inlined from course_learning/scripts/extract_livebook.LIVEBOOK_SLUGS (50
# entries) so the checker has no cross-repo import. Internal slug -> Manning
# product-page slug.
LIVEBOOK_SLUGS = {
    "llm_from_scratch": "build-a-large-language-model-from-scratch",
    "transformers_in_action": "transformers-in-action",
    "ai_powered_search": "ai-powered-search",
    "essential_graphrag": "essential-graphrag",
    "kg_llms_in_action": "knowledge-graphs-and-llms-in-action",
    "nlp_in_action": "natural-language-processing-in-action-second-edition",
    "llms_in_production": "llms-in-production",
    "rlhf_book": "the-rlhf-book",
    "deep_learning_pytorch_2e": "deep-learning-with-pytorch-second-edition",
    "grokking_ml_2e": "grokking-machine-learning-second-edition",
    "reasoning_model_from_scratch": "build-a-reasoning-model-from-scratch",
    "advanced_rag_app": "build-an-llm-application-from-scratch",
    "ai_agents_and_apps": "ai-agents-and-applications",
    "hugging_face_in_action": "hugging-face-in-action",
    "ai_engineering_in_practice": "ai-engineering-in-practice",
    "building_reliable_ai_systems": "building-reliable-ai-systems",
    "deepseek_from_scratch": "build-a-deepseek-model-from-scratch",
    "enterprise_rag": "enterprise-rag",
    "ai_agents_in_action_2e": "ai-agents-in-action-second-edition",
    "multi_agent_from_scratch": "build-a-multi-agent-system-from-scratch",
    "ai_agent_from_scratch": "build-an-ai-agent-from-scratch",
    "deep_learning_python_2e": "deep-learning-with-python-second-edition",
    "deep_learning_jax": "deep-learning-with-jax",
    "pandas_workout": "pandas-workout",
    "ai_applications_made_easy": "ai-applications-made-easy",
    "grokking_ai_algorithms_2e": "grokking-ai-algorithms-second-edition",
    "grokking_deep_learning": "grokking-deep-learning",
    "grokking_statistics": "grokking-statistics",
    "grokking_bayes": "grokking-bayes",
    "grokking_deep_rl": "grokking-deep-reinforcement-learning",
    "deep_rl_in_action": "deep-reinforcement-learning-in-action",
    "ml_tabular_data": "machine-learning-for-tabular-data",
    "rearchitecting_llms": "rearchitecting-llms",
    "test_yourself_raschka": "test-yourself-on-sebastian-raschka-s-build-a-llm",
    "rag_seminal_papers": "retrieval-augmented-generation-the-seminal-papers",
    "domain_specific_slms": "domain-specific-small-language-models",
    "text_to_image_from_scratch": "build-a-text-to-image-generator-from-scratch",
    "stable_diffusion_book": "a-damn-fine-stable-diffusion-book",
    "deep_learning_vision_systems": "deep-learning-for-vision-systems",
    "learn_gen_ai_pytorch": "learn-generative-ai-with-pytorch",
    "generative_ai_in_action": "generative-ai-in-action",
    "intro_gen_ai_2e": "introduction-to-generative-ai-second-edition",
    "cuda_deep_learning": "cuda-for-deep-learning",
    "ml_platform_engineering": "machine-learning-platform-engineering",
    "mlops_at_scale": "mlops-engineering-at-scale",
    "ml_engineering_in_action": "machine-learning-engineering-in-action",
    "prompt_engineering_ai_systems": "prompt-engineering-for-ai-systems",
    "ai_governance": "ai-governance",
    "eval_alignment_seminal_papers": "evaluation-and-alignment-the-seminal-papers",
    "sutskevers_list": "sutskever-s-list",
}


def today() -> str:
    return _dt.date.today().isoformat()


# --------------------------------------------------------------------------- guides
def internal_slug(full_slug: str) -> str:
    """The catalog/livebook key for a guide: its slug minus the ``manning_`` prefix."""
    return full_slug[len(GUIDE_PREFIX):] if full_slug.startswith(GUIDE_PREFIX) else full_slug


def meap_guides() -> list[str]:
    """Full slugs of ``status: meap`` guides from guides.yml."""
    return [g.slug for g in scope.get_all_guides() if g.status == "meap"]


def _is_bootstrap(manifest: dict) -> bool:
    """True only for THIS checker's *minimal bootstrap* manifest -- NOT extractor
    provenance like ``_generated_by: 'DSPy build P1 capture ...'``. A hand- or
    extractor-authored manifest's ``livebook_slug`` must still be honored (else a
    well-captured guide false-reports UNRESOLVED)."""
    return "minimal bootstrap" in str(manifest.get("_generated_by", ""))


def resolve_slug(internal: str, manifest: dict | None) -> str | None:
    """Resolution order: a HAND/extractor-authored manifest, then overrides, then the
    inlined map. The checker's own minimal-bootstrap manifests are ignored so a RENAMED
    book keeps re-flagging until a human fixes the slug. None = unresolved."""
    if manifest and manifest.get("livebook_slug") and not _is_bootstrap(manifest):
        return manifest["livebook_slug"]
    return SLUG_OVERRIDES.get(internal) or LIVEBOOK_SLUGS.get(internal)


# --------------------------------------------------------------------------- manifests / state
def read_yaml(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"ERROR: malformed YAML at {path}: {exc}")


def cache_manifest_path(full_slug: str) -> Path:
    return layout.review_dir(_dir(full_slug)) / "cache_manifest.yml"


def freshness_state_path(full_slug: str) -> Path:
    return layout.review_dir(_dir(full_slug)) / "freshness_state.yml"


def _dir(full_slug: str) -> Path:
    d = guide_dir_for_slug(full_slug)
    if d is None:  # well-formed path so callers can still report
        return paths.host_root() / full_slug
    return d


def captured_chapter_count(full_slug: str, manifest: dict | None) -> int | None:
    """Best-effort: what the guide currently covers. Manifest wins; else count sources."""
    if manifest:
        for key in ("available_chapters", "chapters_available"):
            if isinstance(manifest.get(key), int):
                return manifest[key]
        if isinstance(manifest.get("chapters"), list) and manifest["chapters"]:
            return len(manifest["chapters"])
    gdir = _dir(full_slug)
    hits = list(layout.chapters_dir(gdir).glob("*.tex"))
    # Drop a 00_* front-matter file from the count if present.
    hits = [h for h in hits if not re.match(r"^0+(_|$)", h.stem)]
    return len(hits) or None


# --------------------------------------------------------------------------- live product page
def fetch_product(slug: str, timeout: int = 15) -> tuple[str, str]:
    """Return (final_url, html). Raises urllib errors (caller classifies)."""
    req = urllib.request.Request(PRODUCT_URL.format(slug=slug), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        return resp.geturl(), resp.read().decode("utf-8", "replace")


_MONTHS = {m: i for i, m in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), start=1)}


def month_to_iso(month_year: str | None) -> str | None:
    """'April 2026' -> '2026-04' (None/unknown month -> None)."""
    if not month_year:
        return None
    m = re.match(r"([A-Za-z]+) (\d{4})", month_year.strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"


def parse_state(html: str) -> dict:
    """Extract a stable drift signature + maturity hints from a product page.

    The signature hashes the page's *month fields* — the only auth-free values
    that verifiably move when a MEAP updates (probed 2026-08-24; guides-tooling#20):
    ``MEAP began <Month YYYY>`` (present ONLY on MEAP pages), ``Last updated
    <Month YYYY>`` (bumps with each MEAP drop), ``Publication in …``, the ISBN
    and the page count. The old TOC scrape hashed an empty string on every page
    (the TOC is a JS spinner; ``/ajax/getTocHtml`` returns ``{"tocHtml":""}``),
    and ``\bMEAP\b`` matched the nav bar on every page.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    text = _html.unescape(re.sub(r"\s+", " ", text))
    planned = len(set(re.findall(r"chapter-(\d{1,2})", html)))
    note = ""
    m = re.search(r"(Chapter[s]?\s+\d[^.]{0,180}?in\s+[A-Z][A-Za-z0-9 :,&'\-]{3,60})", text)
    if m:
        note = m.group(1).strip()
    latest_ch = max([int(n) for n in re.findall(r"[Cc]hapter[s]?\s+(\d{1,2})", note)] or [0])
    began_m = re.search(r"MEAP began ([A-Z][a-z]+ \d{4})", text)
    meap_began = began_m.group(1) if began_m else ""
    lu_m = re.search(r"Last updated ([A-Z][a-z]+ \d{4})", text)
    last_updated_month = lu_m.group(1) if lu_m else ""
    pub_m = re.search(r"Publication in ([A-Za-z]+ \d{4})", text)
    pub = pub_m.group(1) if pub_m else ""
    isbn_m = re.search(r"ISBN\s*(\d{13})", text)
    isbn = isbn_m.group(1) if isbn_m else ""
    pages_m = re.search(r"(\d+) pages", text)
    pages = int(pages_m.group(1)) if pages_m else 0
    is_meap = bool(meap_began)
    sig_src = "|".join((meap_began, last_updated_month, pub, isbn, str(pages)))
    signature = hashlib.sha256(sig_src.encode("utf-8")).hexdigest()[:16]
    # Canary against the bug class this signature replaced: a page where NONE
    # of the fields parse means the markup changed — never a healthy baseline.
    parse_degraded = not (meap_began or last_updated_month or pub or isbn or pages)
    return {
        "parse_degraded": parse_degraded,
        "planned_chapters": planned,
        "latest_release_note": note,
        "latest_released_chapter": latest_ch,
        "is_meap": is_meap,
        "meap_began": meap_began,
        "last_updated_month": last_updated_month,
        "publication_estimate": pub,
        "isbn": isbn,
        "pages": pages,
        "signature": signature,
    }


# --------------------------------------------------------------------------- version overlay
def guide_build_date(manifest: dict | None) -> str | None:
    """Best-effort ISO date the guide was last built (manifest ``extracted`` or
    ``captured`` — some extractor-authored manifests use the latter key)."""
    for key in ("extracted", "captured"):
        if manifest and manifest.get(key):
            return str(manifest[key])
    return None


def parse_manifest_version(manifest: dict | None) -> int | None:
    """Pull an int MEAP version from a manifest's ``meap_version`` ('v12'/'12'/'unknown')."""
    if not manifest:
        return None
    m = re.search(r"\d+", str(manifest.get("meap_version", "")))
    return int(m.group()) if m else None


def version_overlay(row: dict, manifest: dict | None, vinfo: dict | None) -> dict:
    """Fold authenticated dashboard version/date into a row. An exact vN bump is a
    stronger signal than the auth-free signature, so it elevates to STALE (but never
    overrides RENAMED)."""
    if not vinfo:
        return row
    # Normalize the caller-supplied version to an int ('v12'/'12'/12 -> 12) so the
    # `live_ver > rec_ver` comparison can't raise TypeError on a string and abort
    # the whole sweep (this path is outside run_check's try/except).
    raw_ver, live_date = vinfo.get("version"), vinfo.get("last_updated")
    vm = re.search(r"\d+", str(raw_ver)) if raw_ver is not None else None
    live_ver = int(vm.group()) if vm else None
    row["live_version"], row["live_last_updated"] = live_ver, live_date
    rec_ver = parse_manifest_version(manifest)
    build_date = guide_build_date(manifest)
    drift = None
    if rec_ver is not None and live_ver is not None and live_ver > rec_ver:
        drift = f"v{rec_ver} -> v{live_ver} (upstream updated {live_date})"
    elif build_date and live_date and str(live_date) > str(build_date):
        drift = f"upstream v{live_ver} updated {live_date} > guide captured {build_date}"
    if drift and row["status"] not in ("RENAMED", "UNRESOLVED", "PUBLISHED"):
        row["status"], row["drift"] = "STALE", drift
    elif drift and row["status"] in ("RENAMED", "UNRESOLVED", "PUBLISHED"):
        # Keep the action-bearing status leading (fix the slug / flip the
        # registry first) but surface the version drift too. Review MF-2.
        row["drift"] += f"; also stale: {drift}"
    elif live_ver is not None and row["status"] in ("BASELINE", "OK"):
        row["drift"] = f"upstream at v{live_ver} (updated {live_date}); {row['drift']}"
    return row


# --------------------------------------------------------------------------- classification
def classify(internal: str, recorded_slug: str, final_url: str, live: dict,
             prior: dict | None, captured: int | None,
             build_date: str | None = None) -> dict:
    """Return a row dict: status + human drift note.

    Staleness is STICKY vs the guide's own capture date: if the live page's
    ``Last updated <Month YYYY>`` postdates the manifest's ``extracted``/
    ``captured`` month, the row is STALE on every run until a re-capture bumps
    the manifest — not just on the run where the page changed (fixes the
    ping-not-track semantics the old docstring admitted)."""
    # Strip any ?query / #fragment before deriving the slug, else a tracking
    # param on the redirect (e.g. ?a_aid=...) yields a persistent false RENAMED.
    final_slug = final_url.split("?")[0].split("#")[0].rstrip("/").split("/")[-1]
    renamed = final_slug != recorded_slug
    # A prior state written by the pre-#20 checker carries the blind signature
    # (schema meap_freshness/1): treat it as a migration baseline, never as
    # evidence of change (else the first post-fix run reports a fleet-wide
    # false STALE). Codex review R-1, 2026-08-24.
    prior_schema = (prior or {}).get("schema", "")
    if prior is not None and prior_schema != STATE_SCHEMA:
        prior = None
    prior_sig = (prior or {}).get("signature")
    latest = live["latest_released_chapter"]
    live_month = month_to_iso(live.get("last_updated_month"))
    bm = re.match(r"(\d{4})-(\d{1,2})", str(build_date)) if build_date else None
    build_month = f"{bm.group(1)}-{int(bm.group(2)):02d}" if bm else None

    if renamed:
        status = "RENAMED"
        drift = f"Manning renamed slug: '{recorded_slug}' -> '{final_slug}'"
    elif live.get("is_meap") is False:
        # The terminal update: the book left MEAP. Published pages carry no
        # month fields, so the sticky rule can never fire — make the
        # transition itself sticky instead (review MF-3; the fleet had 8
        # such guides silently reading OK until re-statused by hand).
        status = "PUBLISHED"
        drift = ("book left MEAP (published edition live) — final re-capture + "
                 "guides.yml status flip owed")
    elif live_month and build_month and live_month > build_month:
        status = "STALE"
        drift = (f"upstream 'Last updated {live['last_updated_month']}' postdates the "
                 f"guide's capture ({build_date}) — re-capture owed")
    elif (build_month is None and (prior or {}).get("status") == "STALE"
          and (prior or {}).get("last_updated_month") == live.get("last_updated_month")):
        # No manifest capture date to anchor on (e.g. a minimal-bootstrap
        # manifest): once a month-bump marked the row STALE, keep the debt
        # until a re-capture writes a real extracted/captured date — do not
        # let the recorded signature launder it into OK. Codex review R-2.
        status = "STALE"
        drift = (f"unrefreshed since 'Last updated {live.get('last_updated_month')}' "
                 "(no capture date in the manifest to clear the debt)")
    elif prior_sig is None:
        if captured is not None and latest and latest > captured:
            status = "STALE?"
            drift = f"guide covers ~{captured} ch; book latest release is Chapter {latest}"
        else:
            status = "BASELINE"
            drift = "baseline established; drift detection starts next run"
    elif prior_sig != live["signature"]:
        status = "STALE"
        drift = "product page changed since last check (month fields moved)"
        if live.get("last_updated_month"):
            drift += f": Last updated {live['last_updated_month']}"
    else:
        status = "OK"
        drift = "no change since last check"

    return {
        "internal": internal, "live_slug": final_slug, "status": status,
        "captured_chapters": captured, "latest_released_chapter": latest,
        "planned_chapters": live["planned_chapters"], "signature": live["signature"],
        "is_meap": live.get("is_meap"), "last_updated_month": live.get("last_updated_month"),
        "latest_release_note": live["latest_release_note"], "drift": drift,
    }


STATE_SCHEMA = "meap_freshness/2"  # /1 = the blind-signature era; /2 = month-field signature (#20)


def write_state(full_slug: str, row: dict, recorded_slug: str) -> None:
    state = {
        "schema": STATE_SCHEMA,
        "internal_slug": row["internal"],
        "recorded_slug": recorded_slug,
        "live_slug": row["live_slug"],
        "last_checked": today(),
        "status": row["status"],
        "signature": row["signature"],
        "captured_chapters": row["captured_chapters"],
        "latest_released_chapter": row["latest_released_chapter"],
        "planned_chapters": row["planned_chapters"],
        "live_version": row.get("live_version"),
        "live_last_updated": row.get("live_last_updated"),
        "last_updated_month": row.get("last_updated_month"),
        "is_meap": row.get("is_meap"),
        "latest_release_note": row["latest_release_note"],
        "drift": row["drift"],
    }
    p = freshness_state_path(full_slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(state, sort_keys=False, allow_unicode=True))


def bootstrap_cache_manifest(full_slug: str, slug: str, live: dict) -> None:
    """Create a MINIMAL cache_manifest.yml only when entirely absent (never overwrite)."""
    p = cache_manifest_path(full_slug)
    if p.exists():
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({
        "_generated_by": "tooling.audits.fleet.check_meap_freshness (minimal bootstrap)",
        "livebook_slug": slug,
        "product_url": PRODUCT_URL.format(slug=slug),
        "livebook_url": f"https://livebook.manning.com/book/{slug}",
        "meap_version": "unknown",
        **({"planned_chapters": live["planned_chapters"]} if live.get("planned_chapters", 0) > 1 else {}),
        "note": "Per-chapter sha256 backfilled on first --refresh (authenticated extract).",
    }, sort_keys=False, allow_unicode=True))


# --------------------------------------------------------------------------- commands
def run_check(only: str | None, snapshot: dict | None, versions: dict | None, write: bool) -> list[dict]:
    full_slugs = [s for s in meap_guides() if (only is None or internal_slug(s) == only or s == only)]
    rows: list[dict] = []
    for full_slug in full_slugs:
        internal = internal_slug(full_slug)
        manifest = read_yaml(cache_manifest_path(full_slug))
        recorded_slug = resolve_slug(internal, manifest)
        if not recorded_slug:
            row = {"internal": internal, "full_slug": full_slug, "live_slug": "",
                   "status": "UNRESOLVED", "captured_chapters": None,
                   "latest_released_chapter": 0, "planned_chapters": 0, "signature": "",
                   "latest_release_note": "", "drift": "no livebook slug (add to SLUG_OVERRIDES)"}
            if versions:
                # A supplied versions map can still speak about this guide (keyed by
                # internal slug) even though the product page cannot be fetched.
                row = version_overlay(row, manifest, versions.get(internal))
            rows.append(row)
            continue
        try:
            if snapshot is not None:
                snap = snapshot.get(recorded_slug) or snapshot.get(internal)
                if not snap:
                    raise KeyError("not in snapshot")
                final_url, live = snap["final_url"], snap["state"]
                _need = {"signature", "latest_released_chapter", "planned_chapters",
                         "latest_release_note", "last_updated_month"}
                if not isinstance(live, dict) or not _need.issubset(live):
                    raise ValueError(f"snapshot 'state' missing {_need - set(live or {})}")
            else:
                final_url, html = fetch_product(recorded_slug)
                live = parse_state(html)
                if live.get("parse_degraded"):
                    raise ValueError("parse degraded — no month/ISBN fields on the "
                                     "product page (markup changed?)")
                time.sleep(0.3)  # politeness
        except Exception as exc:  # noqa: BLE001 -- classify, never crash the sweep
            code = getattr(exc, "code", None)
            note = ("product page 404 — book may be discontinued or renamed (verify slug)"
                    if code == 404 else f"{type(exc).__name__}: {str(exc)[:70]}")
            rows.append({"internal": internal, "full_slug": full_slug, "live_slug": recorded_slug,
                         "status": "ERROR", "captured_chapters": None,
                         "latest_released_chapter": 0, "planned_chapters": 0, "signature": "",
                         "latest_release_note": "", "drift": note})
            continue
        prior = read_yaml(freshness_state_path(full_slug))
        captured = captured_chapter_count(full_slug, manifest)
        row = classify(internal, recorded_slug, final_url, live, prior, captured,
                       build_date=guide_build_date(manifest))
        row["full_slug"] = full_slug
        if versions:
            row = version_overlay(row, manifest, versions.get(recorded_slug) or versions.get(row["live_slug"]))
        rows.append(row)
        if write:
            if guide_dir_for_slug(full_slug) is None:
                # No on-disk guide dir (guide_qa.yaml absent, e.g. partially
                # scaffolded) -- never write state to a wrong flat-path fallback.
                print(f"WARN: {full_slug}: no guide dir on disk; skipping state write",
                      file=sys.stderr)
            else:
                write_state(full_slug, row, recorded_slug)
                if not manifest and row["status"] in ("OK", "BASELINE"):
                    bootstrap_cache_manifest(full_slug, row["live_slug"], live)
    return rows


def render_report(rows: list[dict]) -> str:
    order = {"RENAMED": 0, "PUBLISHED": 1, "STALE": 2, "STALE?": 3, "UNRESOLVED": 4,
             "ERROR": 5, "BASELINE": 6, "OK": 7}
    rows = sorted(rows, key=lambda r: (order.get(r["status"], 9), r["internal"]))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = [
        "# Manning MEAP — Freshness Report (Report B)", "",
        f"**Generated:** {today()} · **Checker:** `tooling.audits.fleet.check_meap_freshness`",
        f"**Coverage:** all {len(rows)} MEAP guides · **Detection:** public product-page signature (no auth)",
        "",
        "## Status summary", "",
        "| Status | Count | Meaning |",
        "|--------|------:|---------|",
        f"| RENAMED | {counts.get('RENAMED',0)} | Manning changed the book's slug — guide dir/manifest needs rename |",
        f"| PUBLISHED | {counts.get('PUBLISHED',0)} | Book left MEAP — final re-capture + guides.yml status flip owed |",
        f"| STALE | {counts.get('STALE',0)} | Upstream advanced — version/date ahead of the guide, or product page changed |",
        f"| STALE? | {counts.get('STALE?',0)} | First-run estimate: book's latest chapter > what the guide covers |",
        f"| BASELINE | {counts.get('BASELINE',0)} | Baseline recorded this run; drift detection active next run |",
        f"| UNRESOLVED | {counts.get('UNRESOLVED',0)} | No livebook slug known — add to SLUG_OVERRIDES |",
        f"| ERROR | {counts.get('ERROR',0)} | Fetch/parse failure (see note) |",
        f"| OK | {counts.get('OK',0)} | No change since last check |",
        "",
        "## Per-guide", "",
        "| Guide | Live slug | Status | Guide ch | Live ver | Drift |",
        "|-------|-----------|--------|---------:|:--------:|-------|",
    ]
    for r in rows:
        gc = "" if r["captured_chapters"] is None else r["captured_chapters"]
        lv = f"v{r['live_version']}" if r.get("live_version") else ""
        lines.append(f"| {r['internal']} | `{r['live_slug']}` | **{r['status']}** | {gc} | {lv} | {r['drift']} |")
    lines += ["", "## Next actions", "",
              "- **RENAMED / STALE / STALE?** → `make meap-freshness REFRESH=1 SLUG=<guide> DRY_RUN=1` "
              "(re-capture + re-author + QA; the capture step is deferred — see meap_freshness.md).",
              "- **UNRESOLVED** → add the livebook slug to `SLUG_OVERRIDES` in the checker.",
              "- Re-run `make meap-freshness` after refreshes; a clean fleet is all `OK`/`BASELINE`.", ""]
    return "\n".join(lines)


def run_refresh(slug: str | None, dry_run: bool) -> int:
    if not slug:
        raise SystemExit("ERROR: --refresh requires --slug <guide>")
    slug = internal_slug(slug)  # accept either manning_<x> or the internal <x>
    plan = [
        "1. Re-capture chapters from livebook (AUTHENTICATED) via the legacy "
        "course_learning extractor: scripts/extract_remaining_manning.py --slug " + slug,
        "2. Diff new per-chapter sha256 vs review/cache_manifest.yml -> changed/new chapters.",
        "3. Scaffold/author the changed chapter sections (assisted review pass).",
        "4. Re-extract Anki cards + run guide QA (make qa) — gate before accepting the PDF.",
        "5. Bump meap_version/extracted in review/cache_manifest.yml and re-run the check (expect OK).",
    ]
    print(f"\n=== REFRESH PLAN for {slug} ===")
    for step in plan:
        print("  " + step)
    print("\nNOTE: the capture step (1) is authenticated and lives in course_learning; this runner "
          "does NOT execute it (deferred per meap_freshness.md). Run it manually, then re-check.")
    if dry_run:
        print("\n--dry-run: no changes made.")
    return 0


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Manning MEAP freshness checker (T4)")
    ap.add_argument("--slug", help="limit to one guide (internal slug, e.g. rlhf_book, or full manning_*)")
    ap.add_argument("--snapshot", help="JSON of {slug: {final_url, state}} to diff instead of live fetch")
    ap.add_argument("--versions", help="JSON {versions:{slug:{version,last_updated}}} from an auth'd dashboard scan")
    ap.add_argument("--refresh", action="store_true", help="print the re-capture plan for a stale guide")
    ap.add_argument("--dry-run", action="store_true", help="with --refresh: print plan only")
    ap.add_argument("--no-write", action="store_true", help="do not write freshness_state/manifests")
    ap.add_argument("--report", default=None, help="report path (default reports/manning_meap_freshness_<date>.md)")
    args = ap.parse_args()

    if args.refresh:
        return run_refresh(args.slug, args.dry_run)

    snapshot = json.loads(Path(args.snapshot).read_text()) if args.snapshot else None
    versions = None
    if args.versions:
        vraw = json.loads(Path(args.versions).read_text())
        versions = vraw.get("versions", vraw)

    rows = run_check(args.slug, snapshot, versions, write=not args.no_write)
    report = render_report(rows)
    if not args.slug:
        out = Path(args.report) if args.report else (
            paths.host_root() / "reports" / f"manning_meap_freshness_{today().replace('-', '')}.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report)
        print(f"Wrote {out}")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
