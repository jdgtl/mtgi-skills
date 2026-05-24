#!/usr/bin/env python3
"""Extract a clean manufacturer part number from a messy vendor Model string.

Vendor "Model" columns mix brand words, marketing/family names, OEM spare
numbers, and the real MPN — e.g. `Savvio 10K.3 (ST9300603SS)`,
`MM1000FBFVR 605832-002 (ST91000640SS)`. This picks the manufacturer part
number, preferring a token that matches a known manufacturer prefix over a
generic OEM/spare number.

Hard rule: the MPN column is required, so we never blank it. When no token
scores as a real MPN, we keep a cleaned best-effort string and flag the row
for review (`is_real_mpn=False`). The full original string is always returned
so the caller can preserve it in Description for audit.

    extract_mpn("Savvio 10K.3 (ST9300603SS)")
    -> {"mpn": "ST9300603SS", "is_real_mpn": True,
        "original": "Savvio 10K.3 (ST9300603SS)", "candidates": [...]}
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from mpn_patterns import score_mpn

# Brand words (single tokens) to drop — they're never the MPN itself.
_BRAND_WORDS = {
    "seagate", "intel", "solidigm", "samsung", "toshiba", "kioxia", "micron",
    "sandisk", "hgst", "hitachi", "wd", "wdc", "western", "digital",
    "dell", "emc", "hp", "hpe", "compaq", "ibm", "lenovo", "cisco", "kingston",
    "nvidia", "mellanox", "oracle", "sun", "broadcom", "brocade", "hynix",
}

# Marketing / product-family words that aren't part numbers.
_FAMILY_WORDS = {
    "series", "family", "enterprise", "storage", "datacenter", "dc",
    "savvio", "exos", "barracuda", "ironwolf", "constellation", "cheetah",
    "ultrastar", "deskstar", "megascale", "skyhawk",
}

_STOPWORDS = _BRAND_WORDS | _FAMILY_WORDS

# A token is a run starting with alphanumeric, allowing . _ / - inside.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

# Real-MPN score floor (mpn_patterns: 0.50 generic, 0.92 known prefix).
_REAL_MPN_FLOOR = 0.50


def _tokens(model: str) -> list[str]:
    out = []
    for tok in _TOKEN_RE.findall(model):
        t = tok.strip("._/-")
        if t:
            out.append(t)
    return out


def _cleaned_string(model: str) -> str:
    """Best-effort MPN when no token is a real part number: drop brand/family
    words, keep the rest in original order."""
    kept = [t for t in _tokens(model) if t.lower() not in _STOPWORDS]
    return " ".join(kept).strip()


def extract_mpn(model: str | None) -> dict:
    original = model if isinstance(model, str) else ""
    candidates: list[tuple[str, object]] = []
    for t in _tokens(original):
        if t.lower() in _STOPWORDS:
            continue
        candidates.append((t, score_mpn(t)))

    real = [(t, sc) for t, sc in candidates if sc.score >= _REAL_MPN_FLOOR]
    if real:
        # Highest score wins; a known manufacturer prefix breaks ties over a
        # generic OEM/spare token.
        token, _ = max(real, key=lambda ts: (ts[1].has_known_prefix, ts[1].score))
        return {
            "mpn": token,
            "is_real_mpn": True,
            "original": original,
            "candidates": [t for t, _ in real],
        }

    cleaned = _cleaned_string(original) or original.strip()
    return {
        "mpn": cleaned,
        "is_real_mpn": False,
        "original": original,
        "candidates": [t for t, _ in candidates],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", help="vendor Model / part string")
    args = ap.parse_args()
    json.dump(extract_mpn(args.model), sys.stdout, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
