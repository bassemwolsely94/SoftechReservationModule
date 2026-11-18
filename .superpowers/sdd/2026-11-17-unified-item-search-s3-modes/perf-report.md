# S3 perf fix — «متوفر» (in_stock) on the engine list

Date: 2026-11-17. Branch: claude/unified-item-search-s3.
Request: `GET /api/items/?search=<q>&rank=engine&page_size=50&in_stock=true` (the Ctrl+F1 modal).
Budget: p95 ≤ 150 ms.

## Profile (connection.execute_wrapper per SQL + EXPLAIN ANALYZE, office catalog, read-only)

- `catalog_itemstock` holds 46,583 rows. Its heap is 34 MB plus 18 MB of indexes, with about 8.4k dead tuples.
  On this machine a full scan plus the grouped sellable SUM takes 100–250 ms. It takes 80–110 ms even on a
  compact copy.
- The old base was `Item.filter(id__in=<Item ⟕ stock ⟕ branch GROUP BY id HAVING SUM(sellable qty) > 0>)`.
  Every tier query that used it paid for the whole-table aggregate, at 370–710 ms each:
  - the name-rank query,
  - the `within()` and `_approx_ids` name lookups,
  - S3's `sound_within()`, which ran `frozenset(base.values_list('id'))` over every in-stock id.
  SQL per request was about 1.07–1.30 s against about 17 ms without the filter.
- The page query and its count (`id IN (engine ids)` + GROUP BY/HAVING) were cheap at about 3–5 ms. They were not the problem.
- Materialising the in-stock id set once per request (9,861 ids) is also too slow here, at 100–250 ms. That ruled out
  "compute the set once".

## Change

1. `catalog.models.sellable_qty_subquery()` is a correlated Subquery that gives one item's SUM over its
   `exclude_unsellable` stock rows. `engine_base()` filters `_sellable_qty > 0`, which is the same rule as the list's
   `total_stock > 0`: no rows means NULL, and NULL is excluded just as Coalesce(…, 0) > 0 excluded it. Each tier now
   sums only its own candidates through the `item_id` index.
2. On the engine page, when the list is not sorted by stock, `_item_filters` uses the same per-row predicate. It no
   longer runs GROUP BY/HAVING over the page and count. Ordering by `total_stock` and the plain list are unchanged.
3. `phonetic.candidates(within=…)` now also accepts a callable `keep(ids) -> set`.
   - Each lookup runs over the whole pool. The hits at or above the cutoff number a few hundred at most.
   - One `keep` call answers for the union of hits.
   - Each lookup then keeps its best `limit` kept hits.
   - `wildcard.item_search`'s `sound_within()` now returns a memoised `keep` (one `base.filter(id__in=hits)` per new
     id batch). It never lists base's whole id set. The frozenset form still works.
4. No migration and no index were added. A partial covering index on the compact copy saved only about 25 ms, and
   `catalog_itemstock` is SOFTECH-synced. Not needed.

## Equivalence checks

- rapidfuzz 3.14.5: in 312 cases (13 queries × 4 pools × 2 cutoffs × 3 random subsets), `extract(narrowed dict, limit)`
  equalled `[full extract(limit=None) filtered][:limit]`, with zero differences. Both forms order by score, then by position.
- Real catalog, old code (HEAD `engine_base` and `_item_filters`, with the frozenset sound path) against new code. The
  run covered 22 queries × {in_stock, category, both, none} × page_size {50, 10}, 176 cases:
  - 174 cases were identical, and 84 of them were non-empty in_stock cases.
  - The 2 differences were «cream» in_stock. That is the documented NAME_CAP sample (an unordered LIMIT 300 on a
    broad pattern, wildcard.py §Speed), and its pick depends on the plan.
  - With NAME_CAP lifted, 40 cases were checked, including cream/tab/sy*/pan/بان, and there were 0 differences.

## Timings (filtered_probe.py, 8 queries × 3 timed reps, PC at ~90% CPU from other work)

| run | none p95 | category p95 | in_stock p50 | in_stock p95 |
|---|---|---|---|---|
| S3 before (reported) | — | — | 1299 | 1610 |
| main baseline (same moment, main-runtime) | 124.4 | 110.3 | 939.8 | 1518.0 |
| S3 fixed, run 1 | 119.2 | 117.9 | 125.6 | 150.9 |
| S3 fixed, run 2 | 141.5 | 135.2 | 149.6 | 166.9 |
| 2026-11-18, final code (the test suite was running at the same time) | 185.2 | 102.9 | 115.6 | 159.0 |
| 2026-11-18, main baseline at the same moment | 145.7 | 149.6 | 1462.7 | 2127.9 |
| 2026-11-18, final code again | 136.5 | 99.9 | 112.4 | 140.9 |

Note: the page-query change (item 2) went in after these two runs. In profiling it cut about 5–8 ms of SQL per
in_stock request. With the filter on, SQL is now about 30–40 ms per request against about 17–28 ms without it. The
rest is Python and serializer time, the same as the unfiltered path. In_stock now sits about 10–25 ms above "none".
Under this load p95 sits at the gate, around 150 ms ± load noise, and none/category moved with load
(119→141 between back-to-back runs).

## Tests

`apps/tests/test_item_list_engine.py::InStockEngineTests` adds four tests:
- A mixed-stock fixture. It covers sellable, quarantine 102/105, HQ 110 against HQ 101, closed and pending branches,
  zero, negative, net negative/zero/positive, negative + 102, fractional stock, no rows and inactive. The engine rows
  equal both a hard-coded expected set and the old `total_stock` annotation rule. Row order is the unfiltered engine
  order minus the out-of-stock rows.
- The sound tier («بنادول») with in_stock returns only the in-stock sound-alikes.
- The callable and frozenset forms of `phonetic.candidates(within=…)` return the same results.
- A query-count pin: 20 queries, including the middleware network lookup, and no `HAVING` in any of them.

Run: `TEST_DB_NAME=test_s3_perf2 manage.py test apps.tests.test_item_list_engine apps.tests.test_wildcard_search apps.tests.test_search_corpus apps.tests.test_sellable_stock --noinput`. Result: 144 tests, OK, in 92 s, run serially.

An earlier `--keepdb` run on `test_s3_perf` that also included test_pos_batch_availability hung in DB setup for about 15 h. The coordinator saw re-migration statements. That run was killed. The modules above passed on a fresh DB, and test_pos_batch_availability was not re-run.
