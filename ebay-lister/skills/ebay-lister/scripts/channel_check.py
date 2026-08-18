#!/usr/bin/env python3
"""Channel check: eBay-only vs BrokerBin-only vs combo, at 3 and 6 months.

Reads the exact-SKU eBay figures from market/<MPN>.json (written by the AI from
the operator's Seller Hub Product Research screenshots), the draft JSON (qty,
ask, package, optional unit_cost / eol_date), and a BrokerBin summary
(brokerbin_api.summarize). Pure math lives in compute(); the CLI renders it and
--apply writes the verdict into the draft. Advice only: always exits 0.

Constants are documented in reference/channel-rules.md and mirrored in RULES.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import brokerbin_api

RULES: dict = {
    "fvf": 0.13,                 # eBay final value fee share of the sale price
    "label_default": 11.0,       # when no package weight and no --label
    "label_by_lb": [(1, 8.0), (3, 11.0), (5, 14.0)],   # <= lb -> $; heavier -> label_heavy
    "label_heavy": 28.0,
    "share_no_competitor": 0.70,
    "share_volume_seller": 0.30,
    "share_at_clearing": 0.50,
    "share_default": 0.40,
    "bb_single_haircut": 0.65,
    "bb_lot_haircut": 0.55,
    "rfq_conversion": 0.25,      # share of 90-day RFQs that become one unit sold
    "salvage": 0.50,             # leftover at horizon, as share of n_b_lot
    "salvage_eol": 0.25,
    "no_asks_salvage_of_ne": 0.25,
    "lot_min_qty": 5,
    "combo_tie_pct": 0.10,
    "thin_solds": 5,
    "horizons": (3, 6),
}

DEFAULT_MARKET_DIR = Path.home() / "Documents/01_Clients/mtgi/work/ebay/market"
DEFAULT_DRAFTS_DIR = Path.home() / "Documents/01_Clients/mtgi/work/ebay/drafts"


# ── rules ───────────────────────────────────────────────────────────────────
def pick_share(market: dict, ask: float, rules: dict = RULES) -> tuple[float, str]:
    """Our expected share of the eBay market pace. First rule that fires wins."""
    e = market["ebay"]
    if int(e.get("active_count") or 0) == 0:
        return rules["share_no_competitor"], "no exact-SKU active competitor"
    vs = e.get("volume_seller")
    vs_price = None
    if isinstance(vs, dict):
        try:
            vs_price = float(vs.get("price_allin")) if vs.get("price_allin") is not None else None
        except (TypeError, ValueError):
            vs_price = None
    if vs_price is not None and vs_price > 0 and vs_price <= ask:
        return rules["share_volume_seller"], "volume seller at/below our ask"
    med = e.get("sold_median_allin")
    if med is not None and ask <= float(med) and int(e.get("watchers_max") or 0) <= 2:
        return rules["share_at_clearing"], "at/below clearing price, watchers <= 2"
    return rules["share_default"], "default"


def label_estimate(pkg: dict | None, rules: dict = RULES) -> float:
    if not pkg or not pkg.get("weight"):
        return rules["label_default"]
    w = float(pkg["weight"].get("value", 0))
    if str(pkg["weight"].get("unit", "POUND")).upper().startswith("OUNCE"):
        w = w / 16.0
    for cap, cost in rules["label_by_lb"]:
        if w <= cap:
            return cost
    return rules["label_heavy"]


def _months_until(eol: str | None, today: date) -> float | None:
    if not eol:
        return None
    d = datetime.strptime(eol, "%Y-%m-%d").date()
    return max(0.0, (d - today).days / 30.4375)


# ── math ────────────────────────────────────────────────────────────────────
def compute(market: dict, draft: dict, bb: dict, rules: dict = RULES,
            today: date | None = None, label: float | None = None) -> dict:
    today = today or date.today()
    e = market["ebay"]
    qty = int(draft.get("quantity", 1))
    ask = float(draft["price"])
    share, share_rule = pick_share(market, ask, rules)
    label = label if label is not None else label_estimate(draft.get("packageWeightAndSize"), rules)
    n_e = ask - rules["fvf"] * ask - label
    p_e = (float(e["sold_units"]) / float(e["window_months"])) * share

    ask_med = bb.get("ask_med")
    n_b_single = round(ask_med * rules["bb_single_haircut"], 2) if ask_med else None
    n_b_lot = round(ask_med * rules["bb_lot_haircut"], 2) if ask_med else None
    rfq90 = int(bb.get("rfq90") or 0)
    p_b = (rfq90 / 3.0) * rules["rfq_conversion"] if rfq90 > 0 else 0.0
    lot_weight = 1.0 if rfq90 > 0 else 0.5

    eol_months = _months_until(draft.get("eol_date"), today)
    salvage_share = rules["salvage_eol"] if eol_months is not None else rules["salvage"]
    salvage = salvage_share * n_b_lot if n_b_lot is not None else rules["no_asks_salvage_of_ne"] * n_e

    flags: list[str] = []
    if int(e["sold_units"]) < rules["thin_solds"]:
        flags.append("thin eBay data (fewer than %d exact-SKU solds)" % rules["thin_solds"])
    if rfq90 == 0:
        flags.append("no BrokerBin demand signal (0 RFQs in 90 d)")
    if ask_med is None:
        flags.append("no BrokerBin asks for this MPN — BrokerBin scenarios n/a")
    if eol_months is not None:
        flags.append("EOL cap active (%s → %.1f months; salvage %.0f%%)" % (draft["eol_date"], eol_months, salvage_share * 100))
    if bb.get("other_brand_rows"):
        flags.append("BrokerBin: %d rows for other manufacturers dropped (keyword match on '%s')" % (bb["other_brand_rows"], market["mpn"]))
    if bb.get("unpriced_listings"):
        flags.append("BrokerBin: %d CALL-priced listings not in the median" % bb["unpriced_listings"])
    if bb.get("ours"):
        flags.append("MTGI already on BrokerBin at $%.0f × %d — sync qty after eBay sales" % (bb["ours"]["price"], bb["ours"]["qty"]))

    def horizon(h: float) -> float:
        return min(h, eol_months) if eol_months is not None else h

    def ebay_net(h: float) -> float:
        sold = min(qty, p_e * h)
        return sold * n_e + (qty - sold) * salvage

    def bb_net(h: float) -> float | None:
        if n_b_single is None:
            return None
        sold = min(qty, p_b * h)
        return sold * n_b_single + (qty - sold) * salvage

    def combo_net(h: float) -> float | None:
        if n_b_lot is None:
            return None
        sold = min(qty, p_e * h)
        return sold * n_e + (qty - sold) * n_b_lot * lot_weight

    scen: dict = {"ebay": {}, "brokerbin": {}, "combo": {}}
    for h in rules["horizons"]:
        hh = horizon(h)
        scen["ebay"][str(h)] = round(ebay_net(hh), 2)
        v = bb_net(hh)
        scen["brokerbin"][str(h)] = None if v is None else round(v, 2)
        v = combo_net(hh)
        scen["combo"][str(h)] = None if v is None else round(v, 2)
    scen["ebay"]["unbounded"] = {"months": round(qty / p_e, 1) if p_e > 0 else None, "net": round(qty * n_e, 2)}
    scen["brokerbin"]["unbounded"] = {"months": round(qty / p_b, 1) if p_b > 0 else None,
                                      "net": None if n_b_single is None else round(qty * n_b_single, 2)}
    scen["brokerbin"]["lot"] = None if (n_b_lot is None or qty < rules["lot_min_qty"]) else \
        {"net": round(qty * n_b_lot * lot_weight, 2), "weight": lot_weight}

    # verdict: highest at 6, tie-break 3, combo if the top two are within tie pct
    def score(name: str, h: str) -> float:
        v = scen[name].get(h)
        return float("-inf") if v is None else v
    ranked = sorted(("ebay", "brokerbin", "combo"), key=lambda n: (score(n, "6"), score(n, "3")), reverse=True)
    verdict = ranked[0]
    top, second = score(ranked[0], "6"), score(ranked[1], "6")
    tie = top > 0 and second > float("-inf") and (top - second) / top <= rules["combo_tie_pct"]
    if tie and score("combo", "6") > float("-inf") and verdict != "combo":
        verdict = "combo"

    parts = ["eBay pace %.1f/mo × %.0f%% share" % (p_e / share if share else 0.0, share * 100)]
    if p_e > 0 and qty / p_e > horizon(6):
        parts.append("cannot clear %d units in %.1f months" % (qty, horizon(6)))
    else:
        parts.append("clears %d units in %.1f months" % (qty, qty / p_e if p_e else 0.0))
    parts.append("BrokerBin %s" % ("%d RFQs/90 d, median ask $%.0f" % (rfq90, ask_med) if ask_med else "no asks"))
    nets = ", ".join("%s $%.0f" % (n, score(n, "6")) for n in ranked if score(n, "6") > float("-inf"))
    rationale = "%s; %s → 6-mo net %s%s." % (
        "; ".join(parts[:2]), parts[2], nets,
        "; within %.0f%% so combo preferred" % (rules["combo_tie_pct"] * 100) if tie else "")

    return {
        "mpn": market["mpn"], "qty": qty, "ask": ask, "share": share, "share_rule": share_rule,
        "n_e": round(n_e, 2), "p_e": round(p_e, 3), "label": label,
        "n_b_single": n_b_single, "n_b_lot": n_b_lot, "p_b": round(p_b, 3),
        "eol_months": None if eol_months is None else round(eol_months, 1),
        "scenarios": scen, "verdict": verdict, "rationale": rationale, "flags": flags,
        "assumptions": {"share": share, "rfq_conversion": rules["rfq_conversion"],
                        "bb_single_haircut": rules["bb_single_haircut"], "bb_lot_haircut": rules["bb_lot_haircut"],
                        "fvf": rules["fvf"], "label": label},
        "brokerbin": bb,
    }


# ── rendering / IO ──────────────────────────────────────────────────────────
def _money(v) -> str:
    return "   n/a" if v is None else "$%6.0f" % v


def render(r: dict) -> str:
    e = r["brokerbin"]
    s = r["scenarios"]
    lines = []
    lines.append("CHANNEL CHECK — %s (%d units, ask $%.2f)   share %.0f%% (rule: %s)" %
                 (r["mpn"], r["qty"], r["ask"], r["share"] * 100, r["share_rule"]))
    lines.append("eBay      net/unit $%.2f · pace %.2f/mo · label $%.0f · fvf %.0f%%" %
                 (r["n_e"], r["p_e"], r["label"], r["assumptions"]["fvf"] * 100))
    ours = e.get("ours")
    lines.append("BrokerBin %d sellers (%d priced) · med ask %s · qty %d · RFQ/90d %d · searches/90d %s · Micro Technologies: %s" %
                 (e.get("sellers", 0), e.get("priced_listings", 0), "n/a" if e.get("ask_med") is None else "$%.0f" % e["ask_med"],
                  e.get("qty_total", 0), e.get("rfq90", 0), e.get("searches_90d", "n/a"),
                  "not listed" if not ours else "$%.0f × %d" % (ours["price"], ours["qty"])))
    lines.append("                       3 mo net     6 mo net     unbounded")
    ub = s["ebay"]["unbounded"]
    lines.append("  eBay only          %s      %s      %d in %s mo → %s" %
                 (_money(s["ebay"]["3"]), _money(s["ebay"]["6"]), r["qty"],
                  "∞" if ub["months"] is None else ub["months"], _money(ub["net"])))
    ub = s["brokerbin"]["unbounded"]
    lines.append("  BrokerBin only     %s      %s      %s" %
                 (_money(s["brokerbin"]["3"]), _money(s["brokerbin"]["6"]),
                  "n/a" if ub["net"] is None else "%d in %s mo → %s" % (
                      r["qty"], "∞" if ub["months"] is None else ub["months"], _money(ub["net"]))))
    if s["brokerbin"].get("lot"):
        lines.append("    lot of %-3d        %s (weight %.1f, ≤60 d)" %
                     (r["qty"], _money(s["brokerbin"]["lot"]["net"]), s["brokerbin"]["lot"]["weight"]))
    lines.append("  Combo              %s      %s      —" % (_money(s["combo"]["3"]), _money(s["combo"]["6"])))
    lines.append("VERDICT %s — %s" % (r["verdict"], r["rationale"]))
    if r["flags"]:
        lines.append("flags: " + "; ".join(r["flags"]))
    a = r["assumptions"]
    lines.append("assumptions: share %.2f · rfq conv %.2f · bb haircut %.2f/%.2f · fvf %.2f · label $%.0f" %
                 (a["share"], a["rfq_conversion"], a["bb_single_haircut"], a["bb_lot_haircut"], a["fvf"], a["label"]))
    return "\n".join(lines)


def load_inputs(target: str, market_dir: Path, drafts_dir: Path) -> tuple[dict, dict, Path]:
    draft_path = drafts_dir / f"{target}.json"
    if not draft_path.exists():
        for p in sorted(drafts_dir.glob("*.json")):
            try:
                d = json.loads(p.read_text())
            except json.JSONDecodeError:
                continue
            if d.get("mpn") == target:
                draft_path = p
                break
    if not draft_path.exists():
        raise FileNotFoundError(f"No draft for {target} in {drafts_dir}")
    draft = json.loads(draft_path.read_text())
    mpn = draft.get("mpn") or target
    market_path = market_dir / f"{mpn}.json"
    if not market_path.exists():
        raise FileNotFoundError(
            f"No eBay market file at {market_dir.name}/{mpn}.json — ask the operator for the Product Research "
            f"Sold + Active screenshots, filter to the exact SKU, and write it (see reference/market-json.md).")
    return json.loads(market_path.read_text()), draft, draft_path


def apply(draft_path: Path, result: dict, today: date | None = None) -> None:
    today = today or date.today()
    d = json.loads(draft_path.read_text())
    s = result["scenarios"]
    d["channel"] = {
        "verdict": result["verdict"],
        "checked_at": today.isoformat(),
        "horizon_months": 6,
        "net": {"ebay": s["ebay"]["6"], "brokerbin": s["brokerbin"]["6"], "combo": s["combo"]["6"]},
        "rationale": result["rationale"],
        "assumptions": result["assumptions"],
    }
    draft_path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="eBay vs BrokerBin vs combo channel check (advice only)")
    p.add_argument("target", help="draft SKU (MTGI-HD223) or MPN (HD223)")
    p.add_argument("--apply", action="store_true", help="write the verdict into the draft JSON")
    p.add_argument("--refresh", action="store_true", help="bypass the BrokerBin cache")
    p.add_argument("--json", action="store_true", help="emit the full computation as JSON")
    p.add_argument("--market-dir", default=str(DEFAULT_MARKET_DIR))
    p.add_argument("--drafts-dir", default=str(DEFAULT_DRAFTS_DIR))
    p.add_argument("--label", type=float, default=None, help="override the per-unit label cost")
    a = p.parse_args(argv)
    market_dir, drafts_dir = Path(a.market_dir).expanduser(), Path(a.drafts_dir).expanduser()
    try:
        market, draft, draft_path = load_inputs(a.target, market_dir, drafts_dir)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 0
    try:
        api = brokerbin_api.BrokerBinAPI.from_credentials(cache_path=market_dir / ".brokerbin-cache.json", refresh=a.refresh)
        mpn = draft.get("mpn") or market["mpn"]
        bb = brokerbin_api.summarize(api.search(mpn), api.rfq(mpn), api.supply_demand(mpn),
                                     brand=draft.get("brand"))
        quota = api.last_quota
    except brokerbin_api.BrokerBinError as e:
        print(f"BrokerBin unavailable: {e}", file=sys.stderr)
        bb = brokerbin_api.summarize({"data": []}, {"data": []}, {"data": []})
        bb["unavailable"] = str(e)
        quota = None
    result = compute(market, draft, bb, label=a.label)
    if bb.get("unavailable"):
        result["flags"].insert(0, "BrokerBin UNAVAILABLE (%s) — BrokerBin cells are NOT real zeros; eBay side only" % bb["unavailable"][:80])
        result["brokerbin_unavailable"] = True
    if a.json:
        print(json.dumps({**result, "quota": quota}, indent=2, default=str))
    else:
        print(render(result))
        print("brokerbin quota: %s" % ("%s/%s today" % (quota.get("count"), quota.get("limit")) if quota else "served from cache"))
    if a.apply:
        if result.get("brokerbin_unavailable"):
            print("not applied: BrokerBin was unavailable, so this verdict is one-sided. Re-run with BrokerBin up.", file=sys.stderr)
        else:
            apply(draft_path, result)
            print(f"applied → {draft_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
