# Stock delta sync — SHADOW mode build plan

**Design:** `docs/architecture/40_SOFTECH_DELTA_SYNC.md` (owner-approved 2026-11-19), doc 40 §5 step 0
+ step 1 up to SHADOW. Owner go for this build and for the watermark migration (S1): 2026-11-20.
**Gates already met:** G1 (morning + afternoon runs), §10.1 rounding fix live (PR 279).

## Scope

- `SyncWatermark` (one row per stream; `stkbal` first) and `DeltaShadowRun` (one row per shadow run)
  in `apps/sync`, one migration (S1).
- `SYNC_DELTA_STOCK` setting, `off | shadow`, **default `off`**. `on` is not built in this PR: it
  needs 7 days of SHADOW with 0 misses and the owner's sign-off (S2). A configured `on` logs an error
  and runs as `shadow`, so nothing writes from a delta by accident.
- `sync_stock` (full read, unchanged) also records the keys that really changed this run (value
  changes, sold-out zeroing, new rows) and the largest `modif_lastupdate` it read.
- `apps/sync/delta.py`: in `shadow`, after the full write, run the delta query
  (`modif_lastupdate >= watermark − 10 min`, **no `nowqty > 0` filter**) and store
  `missed = really-changed keys − delta keys`, with up to 20 sample keys (codes only), timings and
  row counts. The delta result is never written. First run with no watermark: seed only.
  Watermark only moves forward; a SOFTECH max below the stored watermark is logged (S6) and the
  watermark is re-seeded. A delta error never breaks the full sync.
- `GET /api/sync/delta-shadow/?days=7` (admin) + a card on `/sync` + help text (AR/EN), and
  `manage.py delta_shadow_report --days 7`.

## Not in scope

`on` mode and its nightly full / weekly reconcile (§3.3), `SyncLog.mode` and the freshness-bar rule
(§8, S8), other tables, column precision (S10).

## Tests (TDD)

`apps/tests/test_stock_delta_shadow.py`: mode parsing (default off, `on` → shadow, junk → off);
`off` sends no delta query; first shadow run seeds; later run with full coverage → 0 missed;
a changed key absent from the delta → missed 1 with sample; a sold-out (zeroed) key counts;
delta rows are never written; a delta error leaves the full sync intact; a backwards watermark
re-seeds and notes S6; API admin-only; perf budget row for the new endpoint.
