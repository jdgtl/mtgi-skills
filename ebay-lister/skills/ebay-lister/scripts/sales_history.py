#!/usr/bin/env python3
"""MTGI's own realized eBay economics: what actually cleared, net of everything.

eBay's market-wide sold data (Marketplace Insights) is Limited Release and
returns 403 for this app. Your OWN sales are not — and for repeat parts they
are the better comp anyway: same condition grade, same packing, same buyer
pool, real clearing prices instead of asking prices.

Joins three sources by orderId:

  Fulfillment  /sell/fulfillment/v1/order        what sold, qty, title, SKU
  Finances     SALE transactions                 gross + itemized fee types
  Finances     SHIPPING_LABEL transactions       what the label actually cost

The Finances API lives on **apiz.ebay.com**, not api.ebay.com. Calling it on
the normal host returns a bodyless 404 that looks like a permissions problem
and is not.

CLI:
    python sales_history.py orders            # realized net per order
    python sales_history.py shipping          # label cost profile
    python sales_history.py summary           # per-item aggregates
    python sales_history.py summary --json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict

import ebay_api
from ebay_api import EbayApiError

FINANCES_BASE = "https://apiz.ebay.com"
PAGE_LIMIT = 200


def _amt(obj: dict | None, key: str = "value") -> float:
    return float((obj or {}).get(key, 0) or 0)


def fetch_transactions(limit: int = PAGE_LIMIT) -> list[dict]:
    d = ebay_api.request("GET", f"{FINANCES_BASE}/sell/finances/v1/transaction?limit={limit}")
    return (d or {}).get("transactions", [])


def fetch_orders(limit: int = 200) -> list[dict]:
    d = ebay_api.request("GET", f"/sell/fulfillment/v1/order?limit={limit}")
    return (d or {}).get("orders", [])


def build() -> dict:
    """Join orders, sales, and label costs into per-order realized economics."""
    txs = fetch_transactions()
    orders = fetch_orders()

    sales = {t["orderId"]: t for t in txs if t.get("transactionType") == "SALE" and t.get("orderId")}
    labels: dict[str, float] = defaultdict(float)
    refunds: dict[str, float] = defaultdict(float)
    for t in txs:
        oid = t.get("orderId")
        if not oid:
            continue
        if t.get("transactionType") == "SHIPPING_LABEL":
            labels[oid] += _amt(t.get("amount"))
        elif t.get("transactionType") == "REFUND":
            refunds[oid] += _amt(t.get("amount"))

    rows = []
    for o in orders:
        oid = o.get("orderId")
        li = (o.get("lineItems") or [{}])[0]
        qty = sum(int(l.get("quantity", 0) or 0) for l in o.get("lineItems", []))
        gross = _amt((o.get("pricingSummary") or {}).get("total"))
        fee = _amt(o.get("totalMarketplaceFee"))

        # Prefer the Finances fee — it is itemized and authoritative.
        sale = sales.get(oid)
        fee_breakdown: dict[str, float] = {}
        if sale:
            fee = _amt(sale.get("totalFeeAmount")) or fee
            for oli in sale.get("orderLineItems", []) or []:
                for f in oli.get("marketplaceFees", []) or []:
                    fee_breakdown[f.get("feeType", "?")] = round(
                        fee_breakdown.get(f.get("feeType", "?"), 0) + _amt(f.get("amount")), 2
                    )

        ship = labels.get(oid, 0.0)
        refund = refunds.get(oid, 0.0)
        net = gross - fee - ship - refund
        rows.append(
            {
                "orderId": oid,
                "date": (o.get("creationDate") or "")[:10],
                "title": li.get("title", ""),
                "sku": li.get("sku"),
                "qty": qty,
                "gross": round(gross, 2),
                "fee": round(fee, 2),
                "fee_pct": round(fee / gross * 100, 2) if gross else None,
                "shipping": round(ship, 2),
                "refund": round(refund, 2),
                "net": round(net, 2),
                "net_per_unit": round(net / qty, 2) if qty else None,
                "fee_breakdown": fee_breakdown,
                "shipping_known": oid in labels,
            }
        )
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {"orders": rows, "transactions": len(txs), "label_count": len(labels)}


def shipping_profile() -> dict:
    """Label costs, split outbound vs return. Outbound is what free shipping costs."""
    txs = fetch_transactions()
    out, ret = [], []
    for t in txs:
        if t.get("transactionType") != "SHIPPING_LABEL":
            continue
        v = _amt(t.get("amount"))
        memo = (t.get("transactionMemo") or "").lower()
        (ret if "return" in memo else out).append(
            {"date": (t.get("transactionDate") or "")[:10], "cost": round(v, 2), "memo": t.get("transactionMemo")}
        )

    def stats(vals: list[float]) -> dict:
        if not vals:
            return {}
        return {
            "n": len(vals),
            "min": round(min(vals), 2),
            "median": round(statistics.median(vals), 2),
            "mean": round(statistics.mean(vals), 2),
            "max": round(max(vals), 2),
            "mode": round(statistics.mode(vals), 2),
        }

    out.sort(key=lambda r: r["date"])
    ret.sort(key=lambda r: r["date"])
    return {
        "outbound": {"stats": stats([r["cost"] for r in out]), "labels": out},
        "returns": {"stats": stats([r["cost"] for r in ret]), "labels": ret},
    }


def summary() -> dict:
    """Aggregate realized economics per item title."""
    data = build()
    by_item: dict[str, dict] = {}
    for r in data["orders"]:
        key = r["title"][:60] or r["sku"] or r["orderId"]
        e = by_item.setdefault(
            key, {"orders": 0, "units": 0, "gross": 0.0, "fee": 0.0, "shipping": 0.0, "net": 0.0, "unit_prices": []}
        )
        e["orders"] += 1
        e["units"] += r["qty"]
        e["gross"] += r["gross"]
        e["fee"] += r["fee"]
        e["shipping"] += r["shipping"]
        e["net"] += r["net"]
        if r["qty"]:
            e["unit_prices"].append(round(r["gross"] / r["qty"], 2))

    for e in by_item.values():
        for k in ("gross", "fee", "shipping", "net"):
            e[k] = round(e[k], 2)
        e["avg_unit_price"] = round(statistics.mean(e["unit_prices"]), 2) if e["unit_prices"] else None
        e["net_per_unit"] = round(e["net"] / e["units"], 2) if e["units"] else None
        e["fee_pct"] = round(e["fee"] / e["gross"] * 100, 2) if e["gross"] else None
    return by_item


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MTGI realized eBay sales economics")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("orders", "shipping", "summary"):
        s = sub.add_parser(name)
        s.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        if args.cmd == "orders":
            data = build()
            if args.json:
                print(json.dumps(data, indent=2))
                return 0
            print(f"{'date':<11}{'qty':>4}{'gross':>9}{'fee':>8}{'fee%':>7}{'ship':>8}{'refund':>9}{'net':>9}{'net/u':>8}  title")
            for r in data["orders"]:
                ship = f"{r['shipping']:.2f}" if r["shipping_known"] else "  n/a"
                refund = f"{r['refund']:.2f}" if r["refund"] else "-"
                print(
                    f"{r['date']:<11}{r['qty']:>4}{r['gross']:>9.2f}{r['fee']:>8.2f}"
                    f"{(r['fee_pct'] or 0):>6.1f}%{ship:>8}{refund:>9}{r['net']:>9.2f}"
                    f"{(r['net_per_unit'] or 0):>8.2f}  {r['title'][:36]}"
                )
            returned = [r for r in data["orders"] if r["refund"]]
            if returned:
                print(f"\n  {len(returned)} order(s) refunded — negative net is a real loss, "
                      f"not a reporting artifact")
        elif args.cmd == "shipping":
            d = shipping_profile()
            if args.json:
                print(json.dumps(d, indent=2))
                return 0
            for kind in ("outbound", "returns"):
                st = d[kind]["stats"]
                if st:
                    print(f"{kind}: n={st['n']}  min=${st['min']}  mode=${st['mode']}  "
                          f"median=${st['median']}  mean=${st['mean']}  max=${st['max']}")
        else:
            d = summary()
            if args.json:
                print(json.dumps(d, indent=2))
                return 0
            print(f"{'units':>6}{'avg $/u':>10}{'net $/u':>10}{'fee%':>7}  item")
            for title, e in sorted(d.items(), key=lambda x: -x[1]["units"]):
                print(f"{e['units']:>6}{(e['avg_unit_price'] or 0):>10.2f}"
                      f"{(e['net_per_unit'] or 0):>10.2f}{(e['fee_pct'] or 0):>6.1f}%  {title[:46]}")
    except (EbayApiError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
