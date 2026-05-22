# Spec — rfq-normalizer v2 (Cowork-native, grounded in a real run)

**Plugin:** `plugin_015K3Wp89HnMfNcF8QzJ4f2k` (rfq-normalizer)
**Owner:** J/DGTL
**Status:** ready for implementation
**Supersedes (in part):** `rfq-normalizer-plugin-enhancement-spec.md` Change 1 (the macOS-Keychain credential model)
**Target outcome:** the skill runs end-to-end in a Cowork session with no manual fixes — credentials persist, the cache is writable, enrichment finishes in one pass, and the historical record isn't corrupted by consolidation.

---

## Decision

**Do not rebuild from scratch. Rewrite two modules, surgically fix the rest, keep the working core.**

This skill ran end-to-end in Cowork for the first time this session against a real file (AGIS Solutions lot bid, 66 rows) and produced a correct, verified output. The pipeline architecture — `parse → analyze → consolidate → split → score → enrich (tiered, cached) → write` — is sound and composable. Every problem we hit was concentrated in two modules whose *environment assumptions* were wrong, plus a handful of localized bugs and a lossy default. None of it is architectural rot, so a from-scratch rebuild would discard working, tested logic (the BrokerBin/Brave clients, the regex spec library, the template writer, the cache) to fix problems that are individually small.

The one signal that would justify a full rebuild is widespread doc-vs-code drift. We found drift, but it's localized (two phantom fallbacks specced but never implemented — see Change 1). That's a fix, not a teardown.

---

## What we observed this session (evidence)

| Observation | Detail |
|---|---|
| Credential store is dead in Cowork | `keyring` backend resolves to `fail.Keyring`; the sandbox has no OS keychain and is wiped between sessions. `/rfq-setup` would persist nothing. |
| Phantom file fallback | `credentials.py` only implements env-var + keyring. The chmod-600 file fallback promised in the enhancement spec was never built. |
| Cache crashes on first run | `cache.py` `_cache_dir()` defaults to the read-only skill folder (`OSError: Read-only file system`). The `$HOME/.cache` fallback its own docstring lists is not implemented. |
| Enrichment is slow + fragile | Batch mode is serial (~16s/MPN → ~12 min for 56 MPNs), writes its aggregate only at the end, and dies with its parent process. Background runs were killed (`--die-with-parent`). |
| Parallelism is safe but absent | A hand-written driver at P=10 enriched all 56 MPNs across two ~40s passes with zero Brave 429s. The skill has no parallel mode. |
| Confidence policy contradicts reality | SKILL.md says "don't auto-fill < 0.90," but Brave caps at ~0.85, so 100% of fills (141 cells) were "below threshold." Literal compliance = surfacing ~141 cells one by one. |
| BrokerBin added nothing for a used-drive lot | All 56 MPNs returned `no_listings`; Brave web search did 100% of enrichment. ~56 BrokerBin calls spent for zero fills against a 50/day quota. |
| MPN column was blended | Real MPNs, brand-prefixed MPNs (`INTEL SSDSC2BB012T6`), and free text (`Dell Ent NVMe AGN MU U.2 1.6TB`) in one column. Scorer false-flagged 18 real MPNs. |
| `candidate_real_mpn` is unvalidated | Produced good strips (`INTEL SSDSC2BB012T6` → `SSDSC2BB012T6`) and garbage (`ST12000NM006J` → `SAS-12GBPS`, an interface; `SSDSC2KG240G8R` → `D3-S4610`, a family name). |
| Size parsing is buggy + under-mines | `(\d+)\s*GB` reads "120.03 GB" as "3GB"; spec hints in the Size column ("1.2 TB 10K SAS") were ignored because the splitter only reads one description field. |
| Consolidation default is lossy for historical | Default key (MPN + condition) would have merged 5 distinct-price bid events, destroying the pricing history. Correct key for `historical` mode is MPN + Bid + Win. |

Net result this session: 66 rows → 61 (4 true-duplicate merges), 3,564 units conserved exactly, all required fields + Size/Condition/Outcome/Winning Bid populated, Interface/Drive Type 61/61, Form Factor 55/61 — but it took manual workarounds for credentials, cache path, enrichment orchestration, and the consolidation key.

---

## Module disposition

| File | Disposition | Why |
|---|---|---|
| `parse_vendor.py` | **Keep verbatim** | Clean, worked first try. |
| `write_template.py` | **Keep verbatim** | Correct 12-col output, styling, provenance sidecar. |
| `brokerbin_client.py` | **Keep** (only swap credential source) | Auth/retry/consensus logic is fine. |
| `brave_client.py` | **Keep** | Did all the real enrichment. |
| `manufacturer_aliases.py` | **Keep** | Used by consensus; no issues seen. |
| `analyze_columns.py` | **Keep + extend** | Detection is good; feed its `historical` + mode hints into consolidation defaults. |
| `credentials.py` + `check_setup.py` + `/rfq-setup` | **Rewrite (Change 1)** | Built for macOS Keychain; wrong for Cowork. |
| `cache.py` | **Rewrite path logic (Change 1)** + add locking (Change 2) | Default dir crashes; not parallel-safe. |
| `enrich_mpn.py` batch mode | **Rewrite (Change 2)** | Serial, write-at-end, non-resumable, dies with parent. Tier functions themselves stay. |
| `consolidate_duplicates.py` | **Surgical fix (Change 3)** | Add historical key; logic otherwise fine. |
| `split_description.py` | **Surgical fix (Change 6)** | GB regex bug; mine all text columns. |
| `mpn_patterns.py` | **Surgical fix (Change 5)** | Expand prefix DB; validate candidates. |
| SKILL.md | **Update** | Confidence policy, settings form, Cowork pre-flight. |

---

## Change 1 — Rewrite the environment & persistence layer (Cowork-native)

### Goal
Credentials and cache persist across sessions in Cowork with zero manual setup, and never crash on a read-only or keychain-less environment.

### Approach
Replace the Keychain-first model with a **persistent-mounted-file** model, because that is the only storage that survives a Cowork sandbox reset. Resolution order for each credential:

1. Environment variable (dev/CI override) — unchanged, highest priority.
2. A chmod-600 file in the persistent workspace folder (the proven fix from this session: `<workspace>/.rfq-normalizer.env`).
3. OS keyring **only if a real backend exists** (covers genuine local-Mac installs).
4. None → trigger `/rfq-setup`.

Make `/rfq-setup` write directly to the workspace file (the durable layer) instead of the keychain. Detect the workspace folder rather than hardcoding; fall back to `$HOME` if no mount is found. This is what we did by hand this session and it worked — codify it.

For the cache: `_cache_dir()` must try, in order, `$RFQ_CACHE_DIR` → `<workspace>/.rfq-cache` → `$HOME/.cache/rfq-normalizer` → a temp dir, and **never** default to the skill folder. Actually implement the `$HOME` fallback the docstring already promises.

Kill the two phantom fallbacks: either implement the file-credential source (this change) and the `$HOME` cache fallback, or delete the claims from the docs. Don't ship docs that describe code that doesn't exist.

### Acceptance criteria
1. Fresh Cowork session, no env vars: `/rfq-setup` stores keys to `<workspace>/.rfq-normalizer.env` (chmod 600) and they resolve on the next session with no re-entry.
2. `cache.py` never raises on a read-only skill folder; first run creates a writable cache dir automatically.
3. `check_setup.py` reports the real source (`env` / `file` / `keyring`) per credential.
4. On a genuine local Mac with a working keyring, that path still works (regression).
5. No secret ever appears in `ps aux` / process args.

---

## Change 2 — Rewrite batch enrichment: parallel, resumable, streaming

### Goal
Enrich N MPNs in one pass without manual drivers, surviving interruptions and 45s execution windows.

### Approach
Rewrite only the batch loop in `enrich_mpn.py` (keep the per-tier functions):

- **Parallel:** add `--parallel N` (default ~8). Observed safe at P=10 against Brave this session. Use a worker pool over unique MPNs.
- **Cache locking:** the shared cache must be parallel-safe — file lock (or per-write atomic merge that re-reads before writing). Today concurrent writers clobber each other, which is why per-worker cache dirs were needed.
- **Streaming/resumable output:** write each MPN's result to a per-MPN result file (or append to a JSONL) as it completes, not one `json.dump` at the end. Resume = skip MPNs that already have a result or a fresh cache entry.
- **Budget flag:** `--budget-seconds S` to exit cleanly under an execution-window cap, having persisted all completed work.

### Acceptance criteria
1. `enrich_mpn.py --batch f.json --parallel 8` enriches 56 MPNs in roughly `(N/8)·per_mpn` wall time, no 429s at default parallelism.
2. Killing the process mid-run loses no completed MPN; re-running resumes and skips finished ones.
3. Concurrent workers never corrupt or drop entries from the shared cache (stress test: 8 workers, 100 MPNs).
4. `--budget-seconds 40` returns cleanly with partial-but-persisted progress.

---

## Change 3 — Historical consolidation key (surgical)

### Goal
Never merge distinct bid events in a historical import.

### Approach
`analyze_columns.py` already emits `suggested_rfq_mode: historical|live`. When `historical`, `consolidate_duplicates.py` should default its grouping key to `MPN + Bid + Win + Outcome + Condition` (merge only true duplicates, sum quantity). When `live`, keep the current MPN(+condition) key. Make the key configurable but pick the right default from the detected mode so the operator isn't required to know this.

### Acceptance criteria
1. On a historical file where one MPN has two different (Bid, Win) pairs, the output keeps two rows; quantities are summed only within identical-price groups.
2. Total quantity is conserved (sum in == sum out) — assert this in code and surface it in the run summary.
3. A `live` for-bid sourcing list still collapses by MPN as before.

---

## Change 4 — Reconcile the confidence policy (surgical, mostly docs)

### Goal
A policy that matches how the tiers actually behave.

### Approach
Web search caps at ~0.85, so a 0.90 auto-fill gate is unreachable for it. Redefine:

- **Optional spec fields** (Interface, Drive Type, Form Factor, Size): auto-fill at or above a `MEDIUM_FLOOR` (e.g., 0.60) with a provenance flag (`tagged_low_confidence`) and an `[unverified — {source} consensus N%]` note. No per-cell prompting.
- **Required fields and MPN swaps:** always confirm; never auto-apply.

Update SKILL.md to state this plainly, and have the run summary report the confidence mix (e.g., "133 medium, 8 low") rather than blocking.

### Acceptance criteria
1. A run filling 141 medium-confidence optional cells completes without interactive prompts and flags every one in the provenance log.
2. SKILL.md's stated policy matches `enrich_mpn.py` behavior (no contradiction).

---

## Change 5 — MPN scoring + candidate validation (surgical)

### Goal
Stop false-flagging real MPNs and stop suggesting garbage swaps.

### Approach
- Expand `mpn_patterns.py`'s prefix database with common enterprise drive families seen this session: `SSDSC`, `SSDPE`, `MTFDD`, `MZ-`, `MZIL`, `MZWL`, `HUH`, `HUS`, `HUSMR`, `WUH`, `THNSF`, `KPM`, `KXG`, `AL15`, `ST*NM`, `SDLF`, `SDFAM`, `0F` (HGST). These were scored 0.3 ("likely SKU") despite being legitimate.
- Add automatic, safe **brand-prefix stripping**: `INTEL X`, `TOSHIBA X`, `HGST X`, `WDC X`, `SAMSUNG X`, `MICRON X` → `X` as a high-confidence cleanup (original preserved in Description). This was unambiguously correct for all such rows this session.
- **Validate `candidate_real_mpn`** before surfacing: reject candidates that match an interface/spec token (`SAS-12GBPS`), a known product-family name (`D3-S4610`), or that fail an MPN shape test. Only surface candidates that look like real part numbers.

### Acceptance criteria
1. The 18 real MPNs from this file no longer flag as `likely_vendor_sku`.
2. Brand-prefixed MPNs are auto-cleaned with the original retained in Description.
3. `candidate_real_mpn` never proposes an interface string or family name; junk candidates from this session are rejected by tests.

---

## Change 6 — Size parsing + multi-column mining (surgical)

### Goal
Correct capacities and harvest the spec hints vendors hide in the Size column.

### Approach
- Fix the GB regex in `split_description.py` to handle decimals (`(\d+(?:\.\d+)?)\s*GB`) and round raw byte-derived capacities to marketing sizes (`120.03 GB` → `120GB`, `480.1 GB` → `480GB`).
- Run spec extraction over **all text columns** (notably Size), not just a single description field, so `1.2 TB 10K SAS` and `7.68TB SSD NVMe` yield interface/drive-type for free before any API call.

### Acceptance criteria
1. `120.03 GB` → `120GB`, `1.6 TB` → `1.6TB`, `14.0 TB` → `14TB`.
2. Rows whose Size column states `SAS`/`SATA`/`NVMe`/`SSD`/`HDD` get those fields from regex (zero API cost) — measurably fewer MPNs hit the enrichment tiers than this session's 56/56.

---

## Change 7 — One settings form after analyze (UX, surgical)

### Goal
Replace sequential confirmations with a single decision step.

### Approach
After `analyze_columns`, present one elicitation card capturing: default Condition for the whole file (no affordance exists today; we needed "used_good for all"), Outcome Date source (auto-detect from filename — this file's date lived only in `agis-solutions-lot-bid-5-18-2026`), consolidation policy (pre-filled from detected mode, Change 3), and enrichment scope (free-only / top-N / full). This session asked four separate questions that could have been one.

### Acceptance criteria
1. A normal run reaches "building output" after exactly one settings interaction (plus any genuine ambiguous-merge prompts).
2. Filename date detection offers `2026-05-18` for this file without the operator typing it.

---

## Phasing

1. **Phase 1 — Change 1 (environment/persistence).** Highest leverage; unblocks unattended runs. Test: fresh session, `/rfq-setup`, confirm persistence next session and no cache crash.
2. **Phase 2 — Change 2 (parallel/resumable enrichment).** Biggest time saver. Test: kill-and-resume; P=8 stress on the cache.
3. **Phase 3 — Changes 3, 6 (consolidation key + size parsing).** Data-correctness. Test against this AGIS file as a fixture.
4. **Phase 4 — Changes 4, 5, 7 (policy, MPN scoring, settings form).** Polish + UX.

Each phase is independently testable. Use this session's AGIS file (sanitized) as the regression fixture — it exercises blended MPNs, decimal sizes, historical pricing, and a case-collision (`303-276-000B-02` vs `...b-02`).

## Risks / open questions

- **BrokerBin value for used-drive lots.** It returned zero listings for all 56 MPNs here. Consider whether, for ITAD used-drive lots, web search should run *first* or *concurrently* rather than as a fallback — and whether spending 56 quota-limited BrokerBin calls for zero fills is worth it. Possibly add a category hint that reorders tiers. Verify the BrokerBin account/key is returning results at all (smoke test passed, but live batch produced nothing).
- **Workspace-folder detection.** Change 1 assumes the skill can find the persistent mount. Confirm a reliable way to detect it across Cowork sessions; `$RFQ_CACHE_DIR` / an explicit config var is the safe escape hatch.
- **Plaintext credentials.** The mounted env file is plaintext (no encrypted store survives the sandbox). Acceptable for an internal tool, but document it and keep the file out of any synced/shared folder.
- **Brave rate limits at higher parallelism.** P=10 was clean in a small sample; validate the safe ceiling before raising the default.

## Files touched

```
REWRITE:
  scripts/credentials.py        (file-in-workspace store; real file source; keep env override)
  scripts/check_setup.py        (report env/file/keyring source)
  scripts/cache.py              (safe dir resolution + parallel-safe writes/locking)
  commands/rfq-setup.md         (write to workspace env file, not keychain)
  enrich_mpn.py (batch loop only) (parallel + resumable + streaming + budget)

SURGICAL FIX:
  scripts/consolidate_duplicates.py (historical key default from analyze mode)
  scripts/split_description.py      (GB decimal regex; mine all text columns)
  scripts/mpn_patterns.py           (prefix DB; brand-prefix strip; candidate validation)
  SKILL.md                          (confidence policy; one settings form; Cowork pre-flight)

KEEP VERBATIM:
  parse_vendor.py, write_template.py, brokerbin_client.py, brave_client.py,
  manufacturer_aliases.py, analyze_columns.py (extend, don't rewrite)

ADD:
  tests/fixtures/agis-sample.xlsx   (sanitized regression fixture from this session)
  tests/test_consolidate_historical.py
  tests/test_size_parsing.py
  tests/test_candidate_validation.py
```

## Effort estimate

- Phase 1 (environment/persistence): ~4 hours incl. tests
- Phase 2 (parallel/resumable enrichment): ~5 hours incl. cache-locking stress test
- Phase 3 (consolidation + size parsing): ~3 hours incl. AGIS fixture
- Phase 4 (policy + MPN scoring + settings form): ~4 hours

Roughly two focused days. Notably less than a from-scratch rebuild, and it keeps every tested component that already works.
