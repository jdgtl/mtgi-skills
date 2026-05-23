# Condition Mapping

Mirror of `src/lib/intake/normalize-condition.ts` in the MTGI app, **plus** the
BrokerBin API v2 condition codes (since enrichment via Tier 2 sees these).

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

## BrokerBin API v2 condition codes

When Tier 2 enrichment hits BrokerBin's `/api/v2/part/search`, conditions come
back as short codes (per the OpenAPI spec). Translate before storing:

| BrokerBin code | MTGI canonical |
|---|---|
| `NEW`    | `new` |
| `F/S`    | `new` (factory sealed) |
| `NOB`    | `new` (open box) |
| `REF`    | `refurbished` |
| `OEMREF` | `refurbished` (OEM refurbished) |
| `EXC`    | `used_like_new` (excellent) |
| `USED`   | `used_good` |
| `ASIS`   | `used_fair` (sold as-is, no warranty) |
| `REP`    | `for_parts` (repair / non-working) |

## Note on enrichment

If the vendor's source description suggests a condition (e.g., "factory sealed", "tested working", "pulled from production server"), it's safer to leave the column blank and let the operator decide than to guess. Conditions can have legal/warranty implications.
