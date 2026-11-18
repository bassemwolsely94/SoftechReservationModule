# Unified Item Search S3 — Modes, Ctrl+F1 and one item box: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every item picker in the app is `ItemSearchWidget`. It gets a selection `mode` (single / list / multi). One Ctrl+F1 listener serves the whole page, and the Ctrl+F1 modal can return several items. `ItemSearchInput` and `MultiItemPicker` are deleted. A filter set in the modal also narrows the «بالنطق» / «تقريبي» tiers.

**Architecture:** The engine change is in `apps/shortage/phonetic.py` and `apps/catalog/wildcard.py`. The frontend work extends `components/ItemSearchWidget.jsx` and `components/AdvancedItemSearchModal.jsx`, adds `components/ItemSearchHotkeyProvider.jsx` mounted once in `App.jsx`, then moves call sites onto the widget. No new endpoint.

**Tech Stack:** Django/DRF, PostgreSQL (pg_trgm), React 18 + Vite, @tanstack/react-query, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-16-unified-item-search-design.md` (§8.1, §8.2, §9 Frontend, §10 S3). Survey of today's call sites: `.superpowers/sdd/s3-survey.md`.

**Branch:** `claude/unified-item-search-s3`, stacked on `claude/unified-item-search-s2` (PR 160), which is stacked on PR 155.

## Global Constraints

- A non-exact row (sound, typo, ingredient, synonym, code_prefix, code_part) is never auto-selected or auto-added. Only an exact code or barcode scan auto-selects (`isExactCodeRow`).
- Codes stay exact-only on POS (`no_live=1`) and Ctrl+K.
- `*` and `%` are wildcards in every item box. Nothing strips them.
- The POS variant (`variant="pos"`) keeps its behaviour and keyboard map (F-keys in `usePosHotkeys`). Only its Ctrl+F1 moves to the provider.
- Backend owns the rules. React only displays the tier chips and the selection.
- UI stays calm. No new popups for common actions.
- Every changed screen gets its in-app help updated (Arabic + English) and its `updated` date bumped. `apps/tests/test_help.py` caps each step's `text` and `when` at 160 characters.
- Tests: run backend suites serially with a unique `TEST_DB_NAME`, never `--parallel`. Never run `search_probe --with-temp-indexes` on the office or VPS server.
- No change to prices, totals, stock, insurance amounts or SOFTECH writes. Where a screen saves, the save call and its payload stay byte-for-byte the same. Only how the item is found changes.

## Review Focus

1. **Typing a space in a `multi` box.** Space must still type (names have spaces). Ticking uses Ctrl+Space or the row checkbox. Test: in multi mode, typing «vol ren» keeps the space and ticks nothing.
2. **Two widgets on one page + Ctrl+F1** (e.g. reservation detail). Exactly one modal opens, for the last-focused widget, and its pick goes to that widget only. Test in Task 2.
3. **A row shape that differs between endpoints.** Migrated call sites read `item_id`, while `/items/?rank=engine` rows carry `id`. The widget hands every row to `onSelect` with both `id` and `item_id`, equal. Test in Task 3.
4. **`list` mode after a pick.** The box clears, keeps focus and drops the stale results, so a fast second Enter can't re-add the previous row. Test in Task 3.
5. **The filtered sound tier.** In the modal, with a category filter, an Arabic sound match that ranks outside the global top-N but inside the filter is returned. Test in Task 1.

---

### Task 1: Filters narrow the sound and approx tiers

**Files:**
- Modify: `apps/shortage/phonetic.py` (`candidates`, `quick_ids`)
- Modify: `apps/catalog/wildcard.py` (sound tier ≈ line 421; `_approx_ids` ≈ line 513; the `within()` helper ≈ line 356)
- Modify: `apps/help/content/general.py` (journey `item_search`: drop the "can be incomplete with filters" caveat added in S2)
- Test: `apps/tests/test_item_list_engine.py`, `apps/tests/test_wildcard_search.py`

**Interfaces:**
- Produces: `phonetic.candidates(query, *, limit, cutoff=..., ix=None, within=None)` and `phonetic.quick_ids(query, *, limit=8, within=None)`. `within` is a `frozenset[int]` or None. When given, items outside it are dropped before the top-`limit` cut. `None` gives today's behaviour exactly.
- `item_search` computes `within` only when `base` is narrowed (`engine_base()` already tells it so). The unfiltered path runs today's code and queries unchanged.

- [ ] **Step 1: Write the failing tests.** `test_filtered_sound_match_outside_global_top` seeds more than `limit` Arabic sound-alike items, where only a low-ranked one is in a category. `item_search('<arabic query>', base=Item.objects.filter(category=...))` must return it with tier `sound`. Add a matching typo case for `approx`. Add a test that the unfiltered call makes the same number of queries as before (`assertNumQueries` on the S2 count).
- [ ] **Step 2: Run them; they fail** (the item is missing).
- [ ] **Step 3: Implement.** Thread `within` into `candidates` (filter the index candidates before sorting and cutting) and `quick_ids`. In `wildcard.item_search`, build `within = frozenset(base.values_list('id', flat=True))` only when narrowed, and pass it to `quick_ids` and to `_approx_ids` → `phonetic.candidates`. Keep `within()` as a final guard.
- [ ] **Step 4: Run** `apps.tests.test_item_list_engine apps.tests.test_wildcard_search apps.tests.test_search_corpus apps.tests.test_arabic_matching apps.tests.test_matching_learning` — all pass.
- [ ] **Step 5: Update the help line.** Filters now apply to every tier; keep ≤160 characters. Run `apps.tests.test_help`.
- [ ] **Step 6: Run** `manage.py search_probe --repeat 3` (read-only, real catalog). Paths A/B/D stay 55/55. Record the p95 values in the report.
- [ ] **Step 7: Commit** `fix(search): modal filters narrow the sound and typo tiers`.

### Task 2: One Ctrl+F1 owner

**Files:**
- Create: `frontend/src/components/ItemSearchHotkeyProvider.jsx` (+ `ItemSearchHotkeyProvider.test.jsx`)
- Modify: `frontend/src/App.jsx` (mount the provider once, inside `QueryClientProvider`, around `<Routes>`)
- Modify: `frontend/src/components/ItemSearchWidget.jsx` (delete its own window `keydown` Ctrl+F1 listener ≈ line 226; register with the provider)
- Modify: `frontend/src/hooks/usePosHotkeys.js` (comment only: Ctrl+F1 is the provider's)

**Interfaces:**
- Produces: `useItemSearchRegistration({ open: () => void, disabled: boolean, inputRef })` → registers on mount and unregisters on unmount; a focus event on `inputRef` marks this widget "last focused". The provider's single `keydown` listener on Ctrl+F1 calls `open()` of the last-focused registered, enabled widget, or else the first registered enabled widget in DOM order. If no widget is registered, it does nothing and does not `preventDefault` (the help panel's plain F1 / Shift+F1 / Alt+F1 stay untouched).

- [ ] **Step 1: Write the failing tests.** The cases: two widgets mounted, focus the second, Ctrl+F1 → exactly one modal opens, and it belongs to the second; nothing focused → the first opens; disabled widget skipped; no widget → event not prevented; unmount unregisters.
- [ ] **Step 2: Run** `npx vitest run src/components/ItemSearchHotkeyProvider.test.jsx` — fails.
- [ ] **Step 3: Implement** the provider and hook, and wire the widget (both variants).
- [ ] **Step 4: Run** the provider test plus `ItemSearchWidget.test.jsx` — pass.
- [ ] **Step 5: Commit** `feat(search): one Ctrl+F1 owner per page`.

### Task 3: The `mode` prop and modal multi-select

**Files:**
- Modify: `frontend/src/components/ItemSearchWidget.jsx`, `frontend/src/components/AdvancedItemSearchModal.jsx`
- Test: `ItemSearchWidget.test.jsx`, `AdvancedItemSearchModal.test.jsx`

**Interfaces:**
- Produces, on `ItemSearchWidget`:
  - `mode: 'single' | 'list' | 'multi'` (default `'single'` = today's behaviour).
  - `exactCodeOnly: boolean` (default false): Enter with no highlighted move picks only an exact code row; non-exact rows still list for a click.
  - `onSelect(item)` for single and list. `onSelect(items[])` for multi.
  - Every item passed to `onSelect` carries `id` and `item_id` (equal); other fields as the row has them.
- `AdvancedItemSearchModal` gets `multi: boolean`. When true it shows a checkbox column and a «إضافة المحدد (n)» button (Enter when the grid has focus also adds; Space ticks the focused row, following `useGridKeyboard`), and calls `onSelect(items[])`. When false it behaves as today.

Modes:
| Mode | Behaviour |
|---|---|
| `single` | Today: pick one, show the selected card with «تغيير». |
| `list` | Each pick calls `onSelect`, then the box clears, keeps focus and drops the old results (a stale Enter adds nothing). |
| `multi` | Rows get a checkbox. Ctrl+Space ticks the highlighted row; a plain Space types. Enter adds the ticked rows (or the highlighted row when none is ticked) as one array, then clears. The Ctrl+F1 modal opens with `multi`. |

- [ ] **Step 1: Write the failing tests.**
  - single: unchanged (existing tests stay green).
  - list: two picks in a row → two `onSelect` calls; input empty and focused after each; Enter right after a pick adds nothing.
  - multi: type «vol ren» → the value keeps the space, nothing ticked; Ctrl+Space on two rows + Enter → one call with 2 items.
  - Every `onSelect` payload has `item_id === id`.
  - exactCodeOnly: Enter on a `code_prefix` row picks nothing; on an exact `code` row it picks.
  - The modal with `multi`: tick 2 → «إضافة المحدد (2)» → `onSelect` gets an array of 2. Without `multi`: today's single-pick test passes.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** Keep the POS variant's own Enter/add path. `mode` applies to the default variant, and the POS variant is `list` by nature.
- [ ] **Step 4: Run** the widget and modal tests plus `npx vitest run` (whole suite) — pass.
- [ ] **Step 5: Commit** `feat(search): item box modes and multi-select Ctrl+F1`.

### Task 4: Give every existing widget call site its mode

**Files:** the 22 pages that import `ItemSearchWidget` (list in `.superpowers/sdd/s3-survey.md` and `grep -rl ItemSearchWidget frontend/src/pages`); help content for each changed screen under `apps/help/content/`.

- [ ] **Step 1: Assign a mode per spec §8.2.**
  - `list`: POS + mobile POS (POS variant, unchanged), new transfer + mobile, demand + mobile, new reservation + mobile, mobile stock count.
  - `multi`: offers item scope, vouchers eligible items, incentive rules, catalog-intelligence bundle items.
  - `single`: everything else.

  **Rule:** a screen whose pick opens a follow-up input on the same card (a quantity box, a notes field) before the line is added keeps `single`. Name each such screen in the report with the reason. For `multi`, the call site's `onSelect` must accept an array, so adapt it to loop over the existing per-item add.
- [ ] **Step 2: Add or extend a test** for at least one `list` page and one `multi` page (render, pick twice / tick twice → the right number of lines).
- [ ] **Step 3: Update the help** for each screen whose behaviour changed (Ctrl+F1 multi, list clearing), bump `updated`, and run `apps.tests.test_help`.
- [ ] **Step 4: Run** `npx vitest run` and `npm run build` — pass.
- [ ] **Step 5: Commit** `feat(search): item boxes pick one, a list, or several per screen`.

### Task 5: Move `ItemSearchInput` sites and ad-hoc pickers onto the widget; delete dead components

**Files:**
- Modify: `pages/InvoicePage.jsx:281`, `pages/invoices/SoftechGrid.jsx:419`, `pages/PickZonesPage.jsx:850`, `pages/ShortagePage.jsx:608` → `single`; `pages/replacement/WorkflowPanel.jsx:388`, `pages/ReplacementNewCasePage.jsx:212`, `pages/supply/AvailabilityInboxTab.jsx:611` → `multi` (each `onSelect` loops its existing dedup-by-`item_id` add).
- Modify: `pages/CallCenterPage.jsx:1041` (ad-hoc box → widget `list`, `branchId`; `addCatalogItem` unchanged).
- Modify: `pages/InsuranceClaimDetailPage.jsx:527` and `pages/InsuranceItemOverridesPage.jsx:241` → widget `single` + `exactCodeOnly`. On pick, set `item_code = item.softech_id` and call the existing lookup (`lookupNewItem` / `doLookup`). Typing a code by hand + «بحث» keeps working, and `saveLine` / `createItemOverride` are untouched.
- Delete: `components/ItemSearchInput.jsx`, `components/MultiItemPicker.jsx` (and their tests if any).
- Help: each changed screen, `updated` bumped.

**Out of S3, kept as they are** (rulings; S4 handles their wildcards):
- Market-shortage manual add and dismiss-match (`MarketShortagePage.jsx:448`, `:182`). Their endpoint returns the `in_shortage` flag and stockable-only rows the widget doesn't carry, and it already uses `wq`.
- Branch-request line re-match (`supply/BranchRequestsTab.jsx:497`). It is a scored matcher review with its own multi-pick table.
- Insurance batch reprice by item code (`InsuranceClaimDetailPage.jsx:4011`). It lists receipts, not catalog items.
- POS image search F6 (`pos/search/PosImageSearch.jsx`). It is a POS sibling on the same engine.

- [ ] **Step 1: Write the failing tests.**
  - Invoice line match: a pick sends `updateLine(..., {item: <id>, is_confirmed: true})` exactly as before.
  - Replacement extra items: ticking 2 adds 2 basket rows, deduped by `item_id`.
  - Insurance re-code: a pick fills `item_code` and calls the lookup; the save payload is unchanged.
  - `grep` guard (Vitest or a Python test): no file under `frontend/src` imports `ItemSearchInput` or `MultiItemPicker`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Migrate the sites, delete the components, update the help.**
- [ ] **Step 4: Run** `npx vitest run`, `npm run build`, `apps.tests.test_help`, and the insurance + invoices + callcenter backend suites that cover these screens' save endpoints — pass.
- [ ] **Step 5: Commit** `refactor(search): one item box everywhere; drop ItemSearchInput and MultiItemPicker`.

### Task 6: Help topic and verification

**Files:** `apps/help/content/general.py` (journey `item_search`), memory note is the controller's job.

- [ ] **Step 1: Extend the `item_search` journey** with modes (one / list / several) and «Ctrl+F1 opens for the box you were in». Each line ≤160 characters, Arabic + English. Bump `updated`.
- [ ] **Step 2: Run** `apps.tests.test_help apps.tests.test_item_list_engine apps.tests.test_wildcard_search apps.tests.test_search_corpus apps.tests.test_universal_search apps.tests.test_pos_search_network` on a fresh `TEST_DB_NAME`, then `apps.tests.security` serially on a clean DB, then `npx vitest run` and `npm run build`.
- [ ] **Step 3: Commit** `docs(help): item search modes and Ctrl+F1`.
