# Condition Mapping

Mirror of `src/lib/intake/normalize-condition.ts` in the MTGI app, **plus** the
condition strings the eBay Browse API returns on listings.

## Canonical enum values

```
new
refurbished
used_like_new
used_good
used_fair
for_parts
unknown
```

## Accepted variants (lowercased, trimmed)

| Canonical | Accepted inputs |
|---|---|
| `new` | `new`, `new sealed`, `sealed` |
| `refurbished` | `refurb`, `refurbished`, `recertified`, `cpo` |
| `used_like_new` | `used-a`, `used a`, `used like new` |
| `used_good` | `used`, `pull`, `server pull`, `used good`, `good` |
| `used_fair` | `used fair` |
| `for_parts` | `broken`, `defective`, `for parts`, `for_parts` |

Unknown / blank → leave cell blank (NOT `unknown`). The MTGI wizard treats blank as `unknown`.

## Single-letter grade letters (refurb/lot vendors)

Many vendor inventory files use grade letters instead of words. Translation
lives in `scripts/normalize_grade.py`:

| Grade | MTGI canonical |
|---|---|
| `A+`, `A`, `1`, `1+` | `used_like_new` |
| `B+`, `B`, `2`, `2+` | `used_good` |
| `C+`, `C`, `3`, `3+` | `used_fair` |
| `D`, `D-`, `F`, `4`, `5` | `for_parts` |

If the vendor file has a `Grade` column but no `Condition`, run
`normalize_grade(row.grade)` and put the result in the Condition column.

**Prefer `scripts/normalize_condition.py` as the single entry point.** It handles
bare grade letters, grade-suffix words ("B grade", "Grade B"), *and* the
condition words in the table above — stripping the "grade" token, trying
`normalize_grade`, then falling back to the word map. Returns the canonical enum
or `None` (never guesses). Use it whether the source column is `Grade`,
`Condition`, or `Health / Grade`.

## eBay Browse condition strings

The eBay Browse API returns a `condition` string on each listing. The eBay tier
runs it through `normalize_condition`, which maps the common values:

| eBay condition | MTGI canonical |
|---|---|
| `New` / `New other` / `New with box` | `new` |
| `Seller refurbished` / `Certified - Refurbished` | `refurbished` |
| `Used` | `used_good` |
| `For parts or not working` | (left blank — no confident map) |

Anything not confidently mapped stays blank (never guessed).

> Legacy: BrokerBin's short condition codes (`NEW`, `F/S`, `REF`, `USED`,
> `ASIS`, `REP`, …) are no longer consumed — BrokerBin was sunset in v0.8.0.

## Note on enrichment

If the vendor's source description suggests a condition (e.g., "factory sealed", "tested working", "pulled from production server"), it's safer to leave the column blank and let the operator decide than to guess. Conditions can have legal/warranty implications.
