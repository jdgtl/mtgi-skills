# Conditions

`publish.py` accepts either the MTGI vocabulary (left) or an eBay enum
directly (right). Anything else is rejected at validate time.

| MTGI value | eBay enum | Use when |
|---|---|---|
| `new` | `NEW` | Sealed, unopened, original packaging |
| `new_other` | `NEW_OTHER` | New but open box, or missing original packaging |
| `refurbished` / `seller_refurbished` | `SELLER_REFURBISHED` | Restored by MTGI |
| `certified_refurbished` | `CERTIFIED_REFURBISHED` | Manufacturer-certified only — requires eBay approval |
| `used_like_new` / `used_excellent` | `USED_EXCELLENT` | Indistinguishable from new in use and appearance |
| `used_very_good` | `USED_VERY_GOOD` | Light wear, fully functional |
| `used_good` | `USED_GOOD` | Normal wear, fully functional — the common case |
| `used_fair` / `used_acceptable` | `USED_ACCEPTABLE` | Heavy wear, still functional |
| `for_parts` | `FOR_PARTS_OR_NOT_WORKING` | Untested, faulty, or salvage |

## Notes

- **Not every category allows every condition.** eBay rejects the offer at
  publish if the condition isn't valid for the chosen category. If that
  happens, check the category's allowed conditions and re-select.
- `CERTIFIED_REFURBISHED` requires a separate eBay seller approval. Don't use
  it unless the operator confirms the account has it.
- `conditionDescription` is only shown for used conditions. It is where the
  honest specifics go — scuffs, missing accessories, what was tested.
- Default when genuinely unknown is `used_good`, but **ask** rather than
  defaulting silently. Condition drives both price and return exposure.

## Writing a condition description

Say what was tested and what wasn't. Say what's cosmetically wrong. Say what's
included. Do not write "fully tested" unless the operator said it was.

Good:
> Powers on and passes memtest. Light scuffing on two heat spreaders. Modules
> only — no packaging or documentation.

Bad:
> Great condition! Works perfectly. Fast shipping!
