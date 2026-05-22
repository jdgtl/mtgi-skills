#!/usr/bin/env python3
"""Tiered MPN enrichment cascade.

For a given MPN, walk through enrichment sources in cost order and return the
first high-confidence result for each missing field. Always records provenance.

Tiers (each is independently optional; skipped if not configured):
    1. MTGI catalog lookup    — MTGI_API_URL + MTGI_API_TOKEN env vars
    2. BrokerBin API          — credentials via /rfq-setup or BROKERBIN_API_KEY
    3. Brave web search       — credentials via /rfq-setup or BRAVE_SEARCH_API_KEY

Each tier returns: {value, source, confidence (0..1), raw_response}

STATUS:
  Tier 1 (MTGI catalog)  — wired against documented contract; endpoint not yet
                           exposed by the app. Skipped if env unset.
  Tier 2 (BrokerBin)     — IMPLEMENTED via brokerbin_client.py. Returns
                           consensus description from top listings + derived
                           specs.
  Tier 3 (Brave search)  — IMPLEMENTED via brave_client.py. Two queries per
                           MPN, dedupes results by URL, surfaces a
                           candidate_real_mpn when a single ≥8-char token
                           appears alongside the queried MPN in ≥3 titles.

Usage:
    python enrich_mpn.py --mpn UCS-SD16TBKS4-EV [--need size,interface,drive_type,form_factor]
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Any

CONFIDENCE_AUTO_ACCEPT = 0.90


def _build_mpn_assessment(
    mpn: str,
    any_listings: bool,
    candidate_real_mpn: str | None,
) -> dict[str, Any] | None:
    """Compute the pattern_assessment block. Returns None if mpn_patterns
    isn't importable (e.g. test harness shims) — callers should treat None
    as "no assessment available", not as a definite negative.
    """
    try:
        from mpn_patterns import score_mpn, is_likely_vendor_sku
    except ImportError:
        return None
    score = score_mpn(mpn)
    assessment: dict[str, Any] = {
        "score": score.score,
        "matched_pattern": score.matched_pattern,
        "suggested_manufacturer": score.suggested_manufacturer,
        "likely_vendor_sku": is_likely_vendor_sku(score, any_listings),
    }
    if candidate_real_mpn:
        assessment["candidate_real_mpn"] = candidate_real_mpn
    return assessment

# Description-specific floor: we fill descriptions even when confidence is
# below auto-accept, because a low-consensus seller-authored description is
# still more useful than a blank cell. Annotated with a confidence tag so
# the operator knows to verify. Other fields stay gated at AUTO_ACCEPT.
DESCRIPTION_FILL_FLOOR = 0.50

# Web-tier floor — fields from tier_web_search may be filled in the
# 0.60..AUTO_ACCEPT range with an [unverified — web consensus N%] tag.
# Web data is noisier than BrokerBin so we cap individual confidences at
# 0.85 inside tier_web_search and gate the fill here.
WEB_FIELD_FILL_FLOOR = 0.60

# Allow the brokerbin_client module to be imported when enrich_mpn.py is run
# directly from anywhere — keeps Cowork happy with relative invocations.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


def tier_mtgi_catalog(mpn: str) -> dict[str, Any] | None:
    """Tier 1: query MTGI's catalog for a known product with this MPN.

    Endpoint contract (to be implemented on MTGI side):
        GET {MTGI_API_URL}/api/products/lookup?mpn={mpn}
        Headers: Authorization: Bearer {MTGI_API_TOKEN}
        Response 200: {
            "found": true,
            "product": {
                "mpn": "...", "manufacturer": "...", "name": "...",
                "description": "...", "specs": {"size": "...", "interface": "...", ...}
            }
        }
        Response 404: {"found": false}
    """
    api_url = os.environ.get("MTGI_API_URL")
    token = os.environ.get("MTGI_API_TOKEN")
    if not api_url or not token:
        return None  # tier skipped

    try:
        import urllib.request
        import urllib.parse
        req = urllib.request.Request(
            f"{api_url}/api/products/lookup?mpn={urllib.parse.quote(mpn)}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data.get("found"):
            return None
        return {
            "source": "mtgi_catalog",
            "confidence": 1.0,  # trusted internal source
            "fields": data["product"].get("specs", {}) | {
                "description": data["product"].get("description"),
            },
            "raw_response": data,
        }
    except Exception as e:
        return {"source": "mtgi_catalog", "error": str(e), "fields": {}, "confidence": 0}


def tier_brokerbin(mpn: str, vendor_manufacturer: str | None = None) -> dict[str, Any] | None:
    """Tier 2: BrokerBin lookup.

    Strategy:
      1. Search BrokerBin for the MPN (size=10, priced listings only).
      2. For EACH field, compute its own consensus across listings:
         - manufacturer: modal value, confidence = agreement ratio
         - description: longest description from the modal-normalized group
         - size/interface/drive_type/form_factor: run split_description on
           each listing's description, take modal value per field
      3. Each field gets independent confidence — manufacturer at 100% agreement
         shouldn't be dragged down by description variants.
    """
    try:
        from brokerbin_client import BrokerBinClient, BrokerBinAuthError, BrokerBinError
        from split_description import split as split_desc
        from manufacturer_aliases import normalize_manufacturer, manufacturers_match
    except ImportError as e:
        return {"source": "brokerbin", "error": f"import failed: {e}", "fields": {}, "field_confidence": {}}

    client = BrokerBinClient.from_credentials()
    if client is None:
        return None  # tier skipped (no API key)

    try:
        result = client.search(mpn, size=10, priced=True)
    except BrokerBinAuthError as e:
        return {"source": "brokerbin", "error": str(e), "fields": {}, "field_confidence": {}}
    except BrokerBinError as e:
        return {"source": "brokerbin", "error": str(e), "fields": {}, "field_confidence": {}}

    if not result.listings:
        # Retry without priced filter — vendor may not be active right now
        try:
            result = client.search(mpn, size=10, priced=False)
        except BrokerBinError:
            return {"source": "brokerbin", "fields": {}, "field_confidence": {}, "note": "no_listings"}
        if not result.listings:
            return {"source": "brokerbin", "fields": {}, "field_confidence": {}, "note": "no_listings"}

    n = len(result.listings)

    # Manufacturer consensus — normalize aliases (HGST→Hitachi, etc.) BEFORE
    # voting, so a part everyone agrees is HGST/WD doesn't split the vote.
    mfg_counts: Counter[str] = Counter()
    for l in result.listings:
        canonical = normalize_manufacturer(l.manufacturer)
        if canonical:
            mfg_counts[canonical] += 1

    mfg_value, mfg_count = (mfg_counts.most_common(1)[0] if mfg_counts else (None, 0))
    mfg_conf = min(0.95, mfg_count / n) if mfg_count else 0

    # Vendor-corroboration boost: if the original vendor file said "Hitachi"
    # and our (aliased) modal BrokerBin manufacturer is also "Hitachi",
    # that's two independent sources agreeing → boost confidence.
    if vendor_manufacturer and mfg_value and manufacturers_match(vendor_manufacturer, mfg_value):
        # Stronger floor when corroborated. Caps at 0.95 to leave headroom for
        # truly-certain catalog data.
        mfg_conf = max(mfg_conf, 0.93)

    # Description consensus — pick the modal normalized description, but
    # return the longest original variant within that modal group (richer text).
    desc_groups: dict[str, list[str]] = {}
    for l in result.listings:
        if not l.description.strip():
            continue
        norm = " ".join(l.description.lower().split())
        desc_groups.setdefault(norm, []).append(l.description.strip())

    desc_value = None
    desc_conf = 0.0
    if desc_groups:
        modal_norm, modal_originals = max(desc_groups.items(), key=lambda kv: len(kv[1]))
        desc_value = max(modal_originals, key=len)
        desc_conf = min(0.95, 0.5 + (len(modal_originals) / n) * 0.45)

    # Spec fields — split EVERY listing's description, take modal value per field.
    field_votes: dict[str, Counter[str]] = {
        "size": Counter(), "interface": Counter(),
        "drive_type": Counter(), "form_factor": Counter(),
    }
    for l in result.listings:
        if not l.description:
            continue
        split = split_desc(l.description)
        for field in field_votes:
            v = split.get(field)
            if v:
                field_votes[field][v] += 1

    field_values: dict[str, Any] = {"manufacturer": mfg_value, "description": desc_value}
    field_conf: dict[str, float] = {"manufacturer": mfg_conf, "description": desc_conf}
    for field, votes in field_votes.items():
        if not votes:
            field_values[field] = None
            field_conf[field] = 0
            continue
        top_value, top_count = votes.most_common(1)[0]
        field_values[field] = top_value
        # Confidence: agreement ratio over listings that had ANY value extracted
        listings_with_extraction = sum(votes.values())
        # Spec-field confidence stays under 0.90 unless a strong supermajority agrees,
        # since regex against varying seller descriptions is inherently noisy.
        ratio = top_count / max(listings_with_extraction, 1)
        field_conf[field] = min(0.92, 0.5 + ratio * 0.42)

    return {
        "source": "brokerbin",
        "fields": field_values,
        "field_confidence": field_conf,
        "raw_response": {
            "total_results": result.total_results,
            "listing_count": n,
            "manufacturer_agreement": f"{mfg_count}/{n}",
            "sample_descriptions": [l.description for l in result.listings[:3]],
        },
    }


_REAL_MPN_TOKEN_PATTERN = re.compile(r"\b([A-Z0-9][A-Z0-9\-]{7,})\b")
_WEB_MFG_CONF_CAP = 0.85
_WEB_DESC_CONF_CAP = 0.75

# Tokens that look MPN-shaped but are actually interface specs, product
# family names, or common words. Reject them as candidate_real_mpn matches.
_CANDIDATE_REJECT_PATTERNS = (
    re.compile(r"^SAS-\d+", re.I),
    re.compile(r"^SATA-?\d*", re.I),
    re.compile(r"^NVME?", re.I),
    re.compile(r"^PCIE?", re.I),
    re.compile(r"^\d+\s*GBPS", re.I),
    re.compile(r"^\d+\s*GBE", re.I),
    # Intel SSD family names ("D3-S4610", "DC-P4510") look MPN-shaped.
    re.compile(r"^D[0-9]-S[0-9]+$", re.I),
    re.compile(r"^DC-P[0-9]+$", re.I),
)

_CANDIDATE_REJECT_WORDS = {
    "SPECIFICATIONS", "DATASHEET", "DOWNLOAD", "MANUFACTURER",
    "ENTERPRISE", "PERFORMANCE", "COMPATIBLE",
}


def _is_valid_candidate_mpn(token: str) -> bool:
    """Validate a candidate_real_mpn token from web search results.

    Filters out interface specs (SAS-12GBPS), product family names (D3-S4610),
    and common English words that happen to be ≥8 chars and ALL CAPS.
    """
    if not token or len(token) < 8:
        return False
    upper = token.upper()
    # Must contain at least one digit AND one letter
    if not any(c.isdigit() for c in upper) or not any(c.isalpha() for c in upper):
        return False
    if upper in _CANDIDATE_REJECT_WORDS:
        return False
    for pattern in _CANDIDATE_REJECT_PATTERNS:
        if pattern.match(upper):
            return False
    return True


def tier_web_search(mpn: str, vendor_manufacturer: str | None = None) -> dict[str, Any] | None:
    """Tier 3: Brave web search.

    Strategy:
      1. Two queries (rate-limited): "<mpn> specifications" and
         "<vendor_mfg> <mpn>" when a vendor manufacturer is known.
      2. Dedupe results by URL across both queries.
      3. Per spec field (size, interface, drive_type, form_factor), run
         split_description on every title+description; modal vote with
         confidence capped at 0.85.
      4. Description: pick the result whose title contains the MPN and has
         the longest description body; cap confidence at 0.75.
      5. candidate_real_mpn: scan result titles for alphanumeric tokens
         (≥8 chars) co-occurring with the queried MPN. If a single token
         appears in ≥3 distinct titles, surface as candidate_real_mpn.
         This catches PA33N3T8 → MZILS3T8HMLH.
    """
    try:
        from brave_client import BraveSearchClient, BraveAuthError, BraveError
        from split_description import split as split_desc
    except ImportError as e:
        return {"source": "web_search", "error": f"import failed: {e}",
                "fields": {}, "field_confidence": {}}

    client = BraveSearchClient.from_credentials()
    if client is None:
        return None  # tier skipped (no API key)

    queries = [f"{mpn} specifications"]
    if vendor_manufacturer:
        queries.append(f"{vendor_manufacturer} {mpn}")

    seen_urls: set[str] = set()
    all_results: list[Any] = []
    try:
        for q in queries:
            res = client.search(q, count=10)
            for r in res.results:
                if r.url and r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
    except BraveAuthError as e:
        return {"source": "web_search", "error": str(e),
                "fields": {}, "field_confidence": {}}
    except BraveError as e:
        return {"source": "web_search", "error": str(e),
                "fields": {}, "field_confidence": {}}

    if not all_results:
        return {"source": "web_search", "fields": {}, "field_confidence": {},
                "note": "no_results"}

    mpn_upper = mpn.upper()
    n = len(all_results)

    # Description pick: title contains MPN, longest body wins. Cap at 0.75.
    desc_value = None
    desc_conf = 0.0
    mpn_matched_descs = [
        r for r in all_results if mpn_upper in (r.title or "").upper() and r.description
    ]
    if mpn_matched_descs:
        best = max(mpn_matched_descs, key=lambda r: len(r.description))
        desc_value = best.description.strip()
        # Confidence scales with how many results corroborated the MPN.
        match_ratio = len(mpn_matched_descs) / n
        desc_conf = min(_WEB_DESC_CONF_CAP, 0.5 + match_ratio * 0.25)

    # Spec-field consensus across titles + descriptions.
    field_votes: dict[str, Counter[str]] = {
        "size": Counter(), "interface": Counter(),
        "drive_type": Counter(), "form_factor": Counter(),
    }
    for r in all_results:
        text = f"{r.title}\n{r.description}"
        split = split_desc(text)
        for fname in field_votes:
            v = split.get(fname)
            if v:
                field_votes[fname][v] += 1

    field_values: dict[str, Any] = {"description": desc_value}
    field_conf: dict[str, float] = {"description": desc_conf}
    for fname, votes in field_votes.items():
        if not votes:
            field_values[fname] = None
            field_conf[fname] = 0
            continue
        top_value, top_count = votes.most_common(1)[0]
        total_extractions = sum(votes.values())
        ratio = top_count / max(total_extractions, 1)
        field_values[fname] = top_value
        # Web extraction is noisier than BrokerBin seller text; lower cap.
        field_conf[fname] = min(_WEB_MFG_CONF_CAP, 0.5 + ratio * 0.35)

    # Real-MPN detection: tokens ≥8 chars appearing in ≥3 distinct titles
    # alongside the queried MPN are likely the actual manufacturer part
    # number for a vendor-internal SKU. We require ≥1 digit in the token
    # to filter out common English words like "SPECIFICATIONS" — real MPNs
    # in this domain (drives, NICs, controllers) reliably contain digits.
    token_counts: Counter[str] = Counter()
    for r in all_results:
        title_upper = (r.title or "").upper()
        if mpn_upper not in title_upper:
            continue
        for tok in _REAL_MPN_TOKEN_PATTERN.findall(title_upper):
            if tok == mpn_upper or len(tok) < 8:
                continue
            if not any(c.isdigit() for c in tok):
                continue
            token_counts[tok] += 1

    candidate_real_mpn: str | None = None
    if token_counts:
        # Walk the ranking until we find a token that passes validation.
        for top_token, top_count in token_counts.most_common():
            if top_count < 3:
                break
            if _is_valid_candidate_mpn(top_token):
                candidate_real_mpn = top_token
                break

    return {
        "source": "web_search",
        "fields": field_values,
        "field_confidence": field_conf,
        "candidate_real_mpn": candidate_real_mpn,
        "raw_response": {
            "queries": queries,
            "unique_results": n,
            "sample_titles": [r.title for r in all_results[:3]],
        },
    }


TIERS = [
    ("mtgi_catalog", tier_mtgi_catalog),
    ("brokerbin",    tier_brokerbin),
    ("web_search",   tier_web_search),
]


def enrich(
    mpn: str,
    needed_fields: list[str],
    current_values: dict[str, Any] | None = None,
    use_cache: bool = True,
    vendor_manufacturer: str | None = None,
) -> dict[str, Any]:
    """Walk tiers in order. For each missing field, accept the first value
    from any tier that meets CONFIDENCE_AUTO_ACCEPT for that specific field.

    Skips fields the caller already has filled (via `current_values`) — saves
    API calls when the local regex split already extracted the data.

    Cache layer: cached enrichment for this MPN is consulted first. If fresh,
    we never touch the network. Successful tier walks are persisted after.
    """
    current_values = current_values or {}

    # Pre-flight: any field the caller already has is excluded from the tier walk.
    # If all needed fields are already filled, return immediately — zero API cost.
    truly_needed = [f for f in needed_fields if not current_values.get(f)]
    results = {
        f: (current_values.get(f) if current_values.get(f) else None)
        for f in needed_fields
    }
    provenance = {
        f: ({"source": "preflight", "confidence": 1.0} if current_values.get(f)
            else {"source": None, "confidence": 0})
        for f in needed_fields
    }

    if not truly_needed:
        return {
            "mpn": mpn,
            "fields": results,
            "provenance": provenance,
            "tier_log": [{"tier": "preflight", "status": "all_fields_present"}],
            "unfilled": [],
            "candidates": {},
            "cache_status": "skipped",
        }

    # Cache layer
    cache_status = "miss"
    if use_cache:
        try:
            from cache import get as cache_get
            cached = cache_get(mpn)
        except ImportError:
            cached = None
        if cached and not cached.get("is_miss"):
            cache_status = "hit"
            cached_fields = cached.get("fields", {})
            cached_conf = cached.get("field_confidence", {})
            cached_source = cached.get("source", "cache")
            for field in truly_needed:
                v = cached_fields.get(field)
                c = cached_conf.get(field, 0)
                if v and c >= CONFIDENCE_AUTO_ACCEPT:
                    results[field] = v
                    provenance[field] = {
                        "source": f"{cached_source} (cached)",
                        "confidence": round(c, 3),
                    }
            still_unfilled = [f for f in truly_needed if results[f] is None]
            if not still_unfilled:
                cached_extras = cached.get("extras") or {}
                return {
                    "mpn": mpn,
                    "fields": results,
                    "provenance": provenance,
                    "tier_log": [{"tier": "cache", "status": "hit", "source": cached_source}],
                    "unfilled": [],
                    "candidates": {},
                    "cache_status": cache_status,
                    "mpn_assessment": _build_mpn_assessment(
                        mpn, any_listings=True,
                        candidate_real_mpn=cached_extras.get("candidate_real_mpn"),
                    ),
                }
        elif cached and cached.get("is_miss"):
            # Fresh "no listings" miss — don't re-hit upstream tiers for the
            # TTL window. Re-surface any cached candidate_real_mpn so the
            # operator still gets the vendor-SKU hint without us re-querying.
            cached_extras = cached.get("extras") or {}
            return {
                "mpn": mpn,
                "fields": results,
                "provenance": provenance,
                "tier_log": [{"tier": "cache", "status": "miss_cached", "note": "previously returned no listings"}],
                "unfilled": [f for f in needed_fields if results[f] is None],
                "candidates": {},
                "cache_status": "miss_cached",
                "mpn_assessment": _build_mpn_assessment(
                    mpn, any_listings=False,
                    candidate_real_mpn=cached_extras.get("candidate_real_mpn"),
                ),
            }

    raw_log = []

    # Track tier outputs so we can persist the best result to cache afterward.
    accumulated_fields: dict[str, Any] = {}
    accumulated_conf: dict[str, float] = {}
    accumulated_source: dict[str, str] = {}
    candidate_real_mpn: str | None = None

    for name, fn in TIERS:
        if all(results[f] is not None for f in needed_fields):
            break
        # Tiers that take vendor_manufacturer accept it as a kwarg.
        if name in ("brokerbin", "web_search"):
            out = fn(mpn, vendor_manufacturer=vendor_manufacturer)
        else:
            out = fn(mpn)
        if out is None:
            raw_log.append({"tier": name, "status": "skipped"})
            continue

        field_conf = out.get("field_confidence", {})
        ran_entry: dict[str, Any] = {"tier": name, "status": "ran"}
        if out.get("error"):
            ran_entry["error"] = out["error"]
        if out.get("note"):
            ran_entry["note"] = out["note"]
        ran_entry["field_confidence"] = field_conf
        raw_log.append(ran_entry)

        # Surface candidate_real_mpn from web_search up to the assessment block.
        if name == "web_search" and out.get("candidate_real_mpn"):
            candidate_real_mpn = out["candidate_real_mpn"]

        # Accumulate every field this tier returned, even below auto-accept threshold —
        # we cache the highest-confidence value across tiers so future runs can use it.
        for field, value in (out.get("fields") or {}).items():
            if value is None:
                continue
            conf = field_conf.get(field, 0)
            if conf > accumulated_conf.get(field, 0):
                accumulated_fields[field] = value
                accumulated_conf[field] = conf
                accumulated_source[field] = name

        for field in needed_fields:
            if results[field] is not None:
                continue
            value = out.get("fields", {}).get(field)
            conf = field_conf.get(field, 0)
            if value and conf >= CONFIDENCE_AUTO_ACCEPT:
                results[field] = value
                provenance[field] = {"source": name, "confidence": round(conf, 3)}

    # Track low-confidence "candidate" values for fields we couldn't auto-fill.
    # The skill agent surfaces these to the user with "X says Y at Z% — accept?"
    candidates: dict[str, list[dict]] = {}
    for entry in raw_log:
        if entry.get("status") != "ran":
            continue
        for field in needed_fields:
            if results[field] is not None:
                continue
            conf = entry.get("field_confidence", {}).get(field, 0)
            # No persisted value reference here — agent re-queries the tier if needed.
            # We just record that a candidate exists for the field.
            if conf > 0:
                candidates.setdefault(field, []).append(
                    {"source": entry["tier"], "confidence": round(conf, 3)},
                )

    # Low-confidence description backfill. A blank description after the
    # main walk is worse for the operator than a tagged "BrokerBin consensus
    # was only 55%" string — they can verify either way, but the tagged one
    # gives them something concrete to react to.
    if "description" in needed_fields and results.get("description") is None:
        best_desc = accumulated_fields.get("description")
        best_conf = accumulated_conf.get("description", 0)
        if best_desc and best_conf >= DESCRIPTION_FILL_FLOOR:
            tag = f" [unverified — {accumulated_source.get('description', 'source')} consensus {int(best_conf * 100)}%]"
            results["description"] = best_desc + tag
            provenance["description"] = {
                "source": accumulated_source.get("description", "unknown"),
                "confidence": round(best_conf, 3),
                "tagged_low_confidence": True,
            }

    # Web-tier low-confidence fill for spec fields. Unlike descriptions,
    # the tag goes in provenance (not appended to the value) so the spec
    # cell stays clean for downstream consumers. Only triggers for fields
    # whose best value came from web_search and falls in 0.60..AUTO_ACCEPT.
    for fname in needed_fields:
        if results[fname] is not None:
            continue
        if accumulated_source.get(fname) != "web_search":
            continue
        conf = accumulated_conf.get(fname, 0)
        if conf < WEB_FIELD_FILL_FLOOR or conf >= CONFIDENCE_AUTO_ACCEPT:
            continue
        value = accumulated_fields.get(fname)
        if not value:
            continue
        results[fname] = value
        provenance[fname] = {
            "source": "web_search",
            "confidence": round(conf, 3),
            "tagged_low_confidence": True,
            "note": f"[unverified — web consensus {int(conf * 100)}%]",
        }

    # Vendor-SKU heuristic: if no tier found listings AND the MPN doesn't
    # match a known manufacturer prefix, surface that signal so the agent
    # can ask the operator for the real MPN. When web_search returned a
    # candidate_real_mpn, attach it so the agent can offer it explicitly.
    bb_entry = next((e for e in raw_log if e.get("tier") == "brokerbin"), None)
    bb_found_listings = bool(bb_entry) and bb_entry.get("note") != "no_listings"
    ws_entry = next((e for e in raw_log if e.get("tier") == "web_search"), None)
    ws_found_results = bool(ws_entry) and ws_entry.get("note") != "no_results"
    pattern_assessment = _build_mpn_assessment(
        mpn,
        any_listings=bb_found_listings or ws_found_results,
        candidate_real_mpn=candidate_real_mpn,
    )

    # Persist to cache — even partial enrichments are valuable for next time.
    if use_cache:
        try:
            from cache import put as cache_put
            # Determine if this was effectively a miss (no useful data anywhere).
            any_useful = any(accumulated_conf.get(f, 0) > 0 for f in needed_fields)
            cache_put(
                mpn=mpn,
                fields=accumulated_fields,
                field_confidence=accumulated_conf,
                source=next(iter(set(accumulated_source.values())), "unknown") if accumulated_source else "unknown",
                is_miss=not any_useful,
                extras={"candidate_real_mpn": candidate_real_mpn} if candidate_real_mpn else None,
            )
        except ImportError:
            pass  # cache module unavailable, skip persistence silently

    return {
        "mpn": mpn,
        "fields": results,
        "provenance": provenance,
        "tier_log": raw_log,
        "unfilled": [f for f, v in results.items() if v is None],
        "candidates": candidates,
        "cache_status": cache_status,
        "mpn_assessment": pattern_assessment,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--mpn", help="Enrich a single MPN")
    src.add_argument(
        "--batch",
        help="Path to a JSON file with [{mpn, need?, current?}, ...] OR a plain-text file with one MPN per line",
    )
    ap.add_argument(
        "--need",
        default="size,interface,drive_type,form_factor,description,manufacturer",
        help="comma-separated list of fields to fill (when --mpn or items in --batch don't specify)",
    )
    ap.add_argument(
        "--current",
        default=None,
        help='JSON string of fields already filled, e.g. \'{"size":"1.6TB","interface":"SATA"}\' — these skip the tier walk',
    )
    ap.add_argument(
        "--vendor-mfg",
        default=None,
        help="Manufacturer name the vendor file already stated (e.g. 'Hitachi') — used to corroborate BrokerBin's consensus",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the persistent MPN cache (forces fresh API calls)",
    )
    ap.add_argument(
        "--results-jsonl",
        default=None,
        help="Stream one result per line to this JSONL file (resumable). When set, suppresses the aggregated stdout JSON list.",
    )
    ap.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Process N MPNs concurrently via a thread pool (safe up to ~10 per session vs Brave). Default 1.",
    )
    ap.add_argument(
        "--budget-seconds",
        type=float,
        default=None,
        help="Soft wall-time budget. When exceeded, stop submitting work and exit cleanly with whatever has streamed.",
    )
    args = ap.parse_args()

    default_need = [f.strip() for f in args.need.split(",") if f.strip()]
    current = json.loads(args.current) if args.current else None
    use_cache = not args.no_cache

    if args.mpn:
        out = enrich(
            args.mpn,
            default_need,
            current_values=current,
            use_cache=use_cache,
            vendor_manufacturer=args.vendor_mfg,
        )
        json.dump(out, sys.stdout, default=str, indent=2)
        return 0

    # Batch mode: keep a single process so rate limiters in each tier client persist.
    items = _load_batch(args.batch, default_need)

    if args.results_jsonl:
        out_path = args.results_jsonl
        done_mpns = _read_completed_mpns(out_path)
        items = [it for it in items if it["mpn"] not in done_mpns]
        cache_hits = 0
        results_count = len(done_mpns)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        write_lock = threading.Lock()

        def _process(item):
            r = enrich(
                item["mpn"],
                item.get("need", default_need),
                current_values=item.get("current"),
                use_cache=use_cache,
                vendor_manufacturer=item.get("vendor_manufacturer"),
            )
            r["mpn"] = item["mpn"]
            return r

        import time as _time
        deadline = (_time.monotonic() + args.budget_seconds) if args.budget_seconds else None

        with open(out_path, "a") as out_f, \
             ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
            futures = []
            for it in items:
                if deadline is not None and _time.monotonic() >= deadline:
                    break
                futures.append(pool.submit(_process, it))
            for fut in as_completed(futures):
                if deadline is not None and _time.monotonic() >= deadline:
                    # Stop draining — let in-flight tasks finish naturally on pool exit
                    break
                r = fut.result()
                if r.get("cache_status") in ("hit", "skipped", "miss_cached"):
                    cache_hits += 1
                with write_lock:
                    out_f.write(json.dumps(r, default=str) + "\n")
                    out_f.flush()
                results_count += 1
        json.dump(
            {"count": results_count, "cache_hits": cache_hits,
             "api_calls_saved": cache_hits, "output": out_path,
             "resumed_skipped": len(done_mpns)},
            sys.stdout, default=str, indent=2,
        )
        return 0

    # Legacy single-blob output (when --results-jsonl is not set)
    results = []
    cache_hits = 0
    for item in items:
        r = enrich(
            item["mpn"],
            item.get("need", default_need),
            current_values=item.get("current"),
            use_cache=use_cache,
            vendor_manufacturer=item.get("vendor_manufacturer"),
        )
        if r.get("cache_status") in ("hit", "skipped", "miss_cached"):
            cache_hits += 1
        results.append(r)
    json.dump(
        {
            "count": len(results),
            "cache_hits": cache_hits,
            "api_calls_saved": cache_hits,
            "results": results,
        },
        sys.stdout,
        default=str,
        indent=2,
    )
    return 0


def _read_completed_mpns(path: str) -> set[str]:
    """Return MPNs already present in a JSONL results file.

    Reads each line as JSON and pulls the "mpn" field. Malformed lines are
    skipped silently — they'll be overwritten when their MPN is re-enriched.
    """
    try:
        with open(path) as f:
            done: set[str] = set()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                m = obj.get("mpn")
                if m:
                    done.add(m)
            return done
    except FileNotFoundError:
        return set()


def _load_batch(path: str, default_need: list[str]) -> list[dict[str, Any]]:
    with open(path) as f:
        text = f.read().strip()
    # Try JSON first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            out = []
            for item in data:
                if isinstance(item, dict):
                    out.append({
                        "mpn": item["mpn"],
                        "need": item.get("need", default_need),
                        "current": item.get("current"),
                        "vendor_manufacturer": item.get("vendor_manufacturer"),
                    })
                else:
                    out.append({
                        "mpn": str(item),
                        "need": default_need,
                        "current": None,
                        "vendor_manufacturer": None,
                    })
            return out
    except json.JSONDecodeError:
        pass
    # Fall back to one MPN per line
    return [
        {"mpn": line.strip(), "need": default_need, "current": None, "vendor_manufacturer": None}
        for line in text.splitlines() if line.strip()
    ]


if __name__ == "__main__":
    sys.exit(main())
