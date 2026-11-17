# Unified Item Search — S2 (path B onto the engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the ~20 screens that use the standard item box (`ItemSearchWidget` default
variant) and the Ctrl+F1 modal onto the S1 engine. They get wildcards, Arabic by sound, typos,
synonyms, ingredients, chips, arrow keys and engine ranking. Every caller's `onSelect` keeps
receiving exactly the row shape it gets today.

S2 also closes the S1 parked follow-ups:
- the probe's index lock;
- the `%1%cream` slowdown;
- the warm-start warning.

**Architecture:**
- `GET /api/items/?search=…&rank=engine` (spec §7, opt-in) returns the *existing*
  `ItemSearchSerializer` rows, filtered to `item_search` ids, in engine order, with tier flags
  added.
- The widget's default variant and the advanced modal send `rank=engine`. All other callers of
  `/api/items/` are unchanged.
- **⚙ Plan call, deviating from spec §8.1:** the default variant calls `/items/?rank=engine`
  rather than `softech-search`. That keeps the row shape (`id`, `all_barcodes`, `total_stock`,
  `stock_levels`, …) that ~20 screens' `onSelect` already consume. No adapter is needed, and
  there is no regression risk for callers.

**Tech stack:** Django 5 / DRF, PostgreSQL (pg_trgm), React 18 + Vite + vitest.

**Spec:** `docs/superpowers/specs/2026-11-16-unified-item-search-design.md` (§7 second bullet,
§8.1 keyboard and chips, §9, §10 S2). This builds on S1 (branch `claude/unified-item-search`,
PR 155); this branch is stacked on it.

## Global Constraints

- `*` and `%` are wildcards everywhere. The default widget must stop stripping `*`.
- The rows passed to `onSelect` from the widget's default variant and from the modal are
  byte-identical in keys and value types to today's `ItemSearchSerializer` output. Tier flags
  (`tier`, `learned`, `sound`, `approx`, `ingredient`, `ingredient_name`, `synonym`,
  `code_part`) are added, never renamed or removed.
- `/api/items/` without `rank=engine` behaves exactly as today. That covers its filters, its
  `WildcardSearchFilter`, inactive-item handling and pagination.
- With `rank=engine`:
  - only active items (the queryset is already active-only);
  - the engine's order, unless the client sent `ordering`, in which case that column sort
    applies *within* the engine's id set;
  - pagination works as today over the engine's set, which is capped at 500 ids;
  - `code_prefix=True`, since this is not the POS path.
- POS (`variant="pos"`) is untouched in S2.
- Speed budget:
  - path B (`/api/items/?search=&rank=engine&page_size=10`): p95 ≤ 150 ms on the real catalog;
  - engine (path D): stays ≤ 40 ms p95.
- No price, stock, discount, checkout or SOFTECH-write changes.
- Tests run serially with `TEST_DB_NAME=test_search_s2`. Never `--parallel`. Check RAM first.
- Help is Arabic + English (CLAUDE.md rule 5b).

## Review Focus

1. **A caller that reads a field the engine path forgot** (`total_stock`, `all_barcodes`,
   `stock_levels`, `pack_price`) gets `undefined`. Task 1 test
   `test_engine_rows_have_same_keys_as_plain` compares key sets.
2. **The modal with filters plus a search** (e.g. category = X, search = `vol*50`) must AND
   the filters with the engine set, never ignore them. Task 1 test
   `test_engine_respects_other_filters`.
3. **The modal sorted by a column** (`ordering=pack_price`) must sort within the engine set,
   not fall back to the plain search. Task 1 test `test_engine_with_ordering`.
4. **The keyboard in the default variant:** ↑/↓ wrap safely; Enter on an empty list does
   nothing; Esc closes without clearing a selected card. Task 3 vitest.
5. **A widget showing a selected-item card** keeps its «تغيير» flow, and Ctrl+F1 still opens the
   modal. Task 3 vitest `selected card unchanged`.

---

### Task 1: `/api/items/?search=&rank=engine`

**Files:**
- Modify: `apps/catalog/views.py` (`ItemViewSet.get_queryset`, `list`, or a filter backend: the
  builder's choice, but `WildcardSearchFilter` must not ALSO run when `rank=engine`)
- Modify: `apps/catalog/serializers.py` (`ItemSearchSerializer`: optional tier fields from
  serializer context)
- Test: `apps/tests/test_item_list_engine.py` (new)

**Interfaces:**
- Consumes:
  - `apps.catalog.wildcard.item_search(q, *, limit, active_only=True, code_prefix=True) -> [(id, tier)]`;
  - `wildcard.ingredient_names(q, ids) -> {id: name}` (S1; check its exact name and signature
    in wildcard.py).
- Produces:
  - query param `rank=engine`;
  - rows add `tier: str` plus the boolean flags, and `ingredient_name` on ingredient rows;
  - the constant `ENGINE_LIST_CAP = 500`, in views.py.

- [ ] **Step 1: Write failing tests.** Seed realistic names: VOLTAREN 50MG, DIVOL 500ML,
  CONCOR 5MG / COR 2.5MG, AUGMENTIN 1G 14 TAB, PANADOL EXTRA, plus one ItemIngredientMap for
  `diclofenac`, and categories. Tests:
  - `test_engine_order`: `GET /api/items/?search=vol*50&rank=engine` → VOLTAREN before DIVOL;
    `tier` is present.
  - `test_plain_search_unchanged`: the same query without `rank` gives the same results as on
    `main` (strip `*`; the old alphabetical-within-rank order), with no `tier` key.
  - `test_engine_rows_have_same_keys_as_plain`: for one item found both ways, the engine row's
    keys ⊇ the plain row's keys, and the values are equal for every shared key.
  - `test_engine_respects_other_filters`: `?search=voltaren&rank=engine&category=<id>` returns
    only items in that category.
  - `test_engine_with_ordering`: `?search=concor&rank=engine&ordering=-pack_price` returns the
    engine's set, sorted by price descending.
  - `test_engine_pagination`: with `page_size=2`, page 1 and page 2 differ, and `count` equals
    the engine set size.
  - `test_engine_flags`: `?search=panadool&rank=engine` → first row `approx: true`;
    `?search=diclofenac&rank=engine` → an `ingredient` row with `ingredient_name`.
  - `test_engine_query_count`: ≤ 8 queries for `page_size=10`.

- [ ] **Step 2: Run, expect FAIL.**
  `$env:TEST_DB_NAME='test_search_s2'; .\venv\Scripts\python.exe manage.py test apps.tests.test_item_list_engine`

- [ ] **Step 3: Implement.**
  - When `rank=engine` and `search` has at least 1 non-wildcard character:
    - `tiers = item_search(q, limit=ENGINE_LIST_CAP)`;
    - the queryset is filtered with `id__in` those ids;
    - the other filters apply as today;
    - order with `Case(When(id=…, then=pos))` unless `ordering` was sent;
    - the `WildcardSearchFilter` search is skipped;
    - drop the `.distinct()` barcode-join need, since there is no barcode join on this path.
  - Pass `{id: tier}` and the ingredient names to the serializer through context.
  - `ItemSearchSerializer.to_representation` adds the fields only when the context holds them.
  - If `item_search` with `limit=500` breaks the 150 ms budget on the real catalog, lower the cap.
    Record the measured value in the report.

- [ ] **Step 4: Run, expect PASS.** Run it together with `apps.tests.test_wildcard_search` and
  the existing tests in `apps/tests` that hit `/api/items/` (grep `'/api/items/'`).

- [ ] **Step 5: Commit:** `feat(search): /api/items/?rank=engine — engine-ranked item list, same row shape`

---

### Task 2: probe path B gate + parked S1 follow-ups (server side)

**Files:**
- Modify: `apps/catalog/management/commands/search_probe.py`
- Modify: `apps/catalog/wildcard.py` (`FOLD_SQL` mark set, `fold_query`)
- Create: `apps/catalog/migrations/0047_fold_marks_narrow.py`
- Modify: `apps/shortage/apps.py`, `apps/shortage/phonetic.py` (warm start)
- Test: `apps/tests/test_wildcard_search.py`, `apps/tests/test_search_corpus.py`

**Interfaces:**
- Produces:
  - `search_probe` path B = `/api/items/?search=&rank=engine&page_size=10`, gated: top-1 must
    pass, p95 ≤ 150 ms when the indexes are present;
  - `FOLD_SQL` v2;
  - migration 0047, which rebuilds the 4 fold indexes with the v2 expression.

- [ ] **Step 1: Write failing tests:**
  - `test_probe_path_b_gated`: the probe command's GATED includes `'B'`, with budget 150.
  - `test_fold_marks_set`: the `fold_query` mark set equals exactly U+0640 plus U+064B–U+0652
    (the marks that occur in the catalog). Stored and typed names with those marks still match
    (reuse the existing tashkeel test).
  - `FoldSqlFrozenTests`: now compares `FOLD_SQL` to the literal frozen in **0047** (the latest).
    0044/0045 stay byte-identical (history).
  - `test_temp_indexes_drop_only_differing`: `search_probe`'s helper returns the DROP list only
    for indexes whose `pg_get_indexdef` differs from the migration SQL. Unit-test the comparison
    function with two strings.
  - `test_warm_start_not_during_app_init`: the warm thread waits until the app registry is ready
    before touching the DB (see Step 3). It also closes its DB connection at the end: mock
    `connections.close_all` and assert it is called.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.**
  - **(a)** Narrow the mark set on both sides.
  - **(b)** 0047: RunSQL that drops and recreates the 4 fold indexes (trgm and prefix) with the
    frozen v2 literal. Reverse = the v1 literal from 0045/0044. Catalog only.
  - **(c)** `--with-temp-indexes`: DROP + CREATE only the indexes that are missing or whose
    definition differs; leave correct ones alone (no ACCESS EXCLUSIVE lock when nothing
    differs). Print which.
  - **(d)** Warm start:
    - today the warm thread queries during `ready()` and triggers Django's "Accessing the database
      during app initialization" RuntimeWarning on every command;
    - make the thread wait for `django.apps.apps.ready`, or start it from the first
      `request_started` signal, whichever is simpler and testable;
    - wrap it with `connections.close_all()` in a `finally`.
  - **(e)** Path B in the probe now sends `rank=engine` and is gated.

- [ ] **Step 4: Run, expect PASS.** Then, on the real dev DB (it has no fold indexes now; the
  stale ones were dropped 2026-11-16), run `manage.py search_probe --with-temp-indexes --repeat 3`.
  Expected:
  - A/C/D pass and B top-1 passes;
  - D p95 ≤ 40 ms, B p95 ≤ 150 ms;
  - `%1%cream` is back to about 50 ms or below.

  Paste the table into the report.

- [ ] **Step 5: Commit:** `perf(search): narrower fold marks (0047); probe gates path B, locks only differing indexes; warm start after init`

---

### Task 3: widget default variant on the engine (+ keyboard, chips)

**Files:**
- Modify: `frontend/src/components/ItemSearchWidget.jsx` (default variant only; POS branch
  untouched)
- Create: `frontend/src/components/ItemSearchWidget.test.jsx`

**Interfaces:**
- Consumes:
  - Task 1's `rank=engine` rows (the `ItemSearchSerializer` shape plus `tier` and flags);
  - S1's `SearchTierChip` (`frontend/src/components/SearchTierChip.jsx`, prop `row`);
  - S1's `Highlight` component and `utils/wildcard`.
- Produces: no new props.

- [ ] **Step 1: Write failing vitest tests** (mock `api.get`):
  - `keeps wildcards`: typing `vol*50` calls `/items/` with `search: 'vol*50', rank: 'engine'`.
  - `arrow keys and Enter`:
    - ↓ ↓ Enter selects the 3rd row; ↑ at the top stays at 0;
    - Enter with no results calls nothing;
    - Esc closes the list.
  - `chip`: a row with `approx: true` shows «تقريبي».
  - `selected card unchanged`: with `selected` set, the card renders with «تغيير», and Ctrl+F1
    opens the modal.
  - `onSelect gets the row as returned`: the object passed to `onSelect` is the API row.

- [ ] **Step 2: Run, expect FAIL.** `cd frontend; npx vitest run src/components/ItemSearchWidget.test.jsx`

- [ ] **Step 3: Implement.**
  - In the default variant:
    - stop stripping `*`;
    - send `rank: 'engine'`;
    - keep `page_size: 10`;
    - keyboard: ↑/↓/Enter/Esc with a highlighted row, as POS does, with no F7, preview or
      queued-Enter;
    - the highlighted row scrolls into view;
    - `ResultRow` shows `<SearchTierChip row={item} />` after the name, plus `<Highlight>` on
      the name.
  - Do not change POS code paths. If shared code must change, POS behaviour and its tests must
    stay identical.
  - The minimum length stays 2 characters (non-wildcard). The server applies D7.

- [ ] **Step 4: Run, expect PASS** (full `npx vitest run`, then `npm run build`).

- [ ] **Step 5: Commit:** `feat(search): standard item box uses the engine — wildcards, arrows, chips`

---

### Task 4: Ctrl+F1 modal on the engine + help

**Files:**
- Modify: `frontend/src/components/AdvancedItemSearchModal.jsx`
- Create: `frontend/src/components/AdvancedItemSearchModal.test.jsx`
- Modify: `apps/help/content/general.py` (a new journey `item_search`, desktop)
- Test: `apps.tests.test_help`

**Interfaces:**
- Consumes: Task 1's `rank=engine` behaviour (filters ANDed, ordering within the set,
  pagination).
- Produces: nothing new. `onSelect(item)` still receives one item of the same shape; multi-select
  is S3.

- [ ] **Step 1: Write failing vitest tests:**
  - `sends rank engine when text typed`: with a search text, the `/items/` call includes
    `rank: 'engine'`; with no search text, it doesn't.
  - `chip in results table`: a row with `sound: true` shows «بالنطق» in the name cell.
  - `column sort still sent`: clicking the price header sends `ordering`.

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement.**
  - Add `rank: 'engine'` whenever `search` is non-empty.
  - Add the chip in the name cell.
  - When the user hasn't clicked a column, the default order is the server's (engine). Today the
    modal sends a default `ordering`; check it, and only send `ordering` after a header click.
  - Help: a general journey `item_search` (Arabic + English) explaining:
    - `*`/`%`;
    - starts-with first;
    - whole numbers first;
    - synonyms;
    - Arabic spelling and sound;
    - typos «تقريبي»;
    - «مادة فعالة»;
    - code fragments;
    - Ctrl+F1.

    Follow the existing journey format in `general.py` and keep within the registry length
    limits. Bump nothing else.

- [ ] **Step 4: Run, expect PASS** (vitest, `npm run build`, `apps.tests.test_help`).

- [ ] **Step 5: Commit:** `feat(search): Ctrl+F1 modal uses the engine; item-search help journey`

---

### Task 5: Verification and PR

- [ ] **Step 1:** Run serially (TEST_DB_NAME=test_search_s2, fresh):
  - `apps.tests.test_item_list_engine`
  - `apps.tests.test_wildcard_search`
  - `apps.tests.test_search_corpus`
  - `apps.tests.test_pos_search_network`
  - `apps.tests.test_universal_search`
  - `apps.tests.test_help`
  - `apps.tests.security`

  All must pass. A security run on a reused `--keepdb` DB gives false failures; use a fresh DB.
- [ ] **Step 2:** `cd frontend; npx vitest run; npm run build`. Both pass.
- [ ] **Step 3:** `search_probe --with-temp-indexes --repeat 3` on the dev DB. All gates pass.
- [ ] **Step 4:** Push `claude/unified-item-search-s2` and open a PR. Base it on
  `claude/unified-item-search` while PR 155 is open, and retarget to `main` once it merges. Bind
  the PR. Merge by hand once green, never `--auto`.
