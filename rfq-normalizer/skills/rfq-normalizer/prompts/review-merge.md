# Review-Merge Prompt — Ambiguous MPN Pairs

When `consolidate_duplicates.py` returns `ambiguous_pairs`, present each one to the user with this phrasing:

## Template

> I found two MPN strings that look like the same part but aren't an exact match:
>
> - **A:** `{mpn_a}`  ({qty_a} units across {row_count_a} rows)
> - **B:** `{mpn_b}`  ({qty_b} units across {row_count_b} rows)
>
> Difference: {reason}
>
> Options:
> 1. **Merge** → treat as one MPN, sum to {total_qty} units. Pick which spelling to use.
> 2. **Keep separate** → two distinct line items.
> 3. **Skip both** → flag for manual review later.

## Decision rules

- Default: **never auto-merge**, even if the case-or-whitespace-only difference looks obvious.
- If the user picks "merge," ask which spelling they want as the canonical version (typically the more formal/correct one).
- Record the decision in the provenance log: `{"action": "merged", "canonical": "ABC-123", "merged_from": "abc 123"}`.
- If the user picks "skip," include both rows in the output but flag them in the provenance log so they can be reviewed in MTGI after import.

## Edge cases

- **Three+ variants of the same MPN** — present all at once, ask user to pick one canonical form.
- **MPN looks like it might be a vendor SKU not a real MPN** (e.g., contains the vendor's name/codes) — flag to user: "This looks like a vendor SKU. Should I look up the actual manufacturer MPN via BrokerBin?"
