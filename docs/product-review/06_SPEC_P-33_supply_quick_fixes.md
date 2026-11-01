# 06 · SPEC P-33 — Supply-flow quick fixes

**Status:** **(a), (c), (d), (e) BUILT 2026-10-31** (owner: "P-33 without retry"; IsrPush field + constraint approved, linked ISR legs). **(b) not built** (scheduled SOFTECH write deferred).
Items (a)–(d) are independent and can ship one at a time. Item (e) waits for the VPS cutover.

**Owner input** (ledger P-33, backlog revision)
- Shortage requests come by **both** the screen and WhatsApp, so "create transfer" goes on **both** paths.
- Transfers and faster turnover are a direct cash lever.
- (e) is resolved by the VPS cutover; verify after it.

## 1. Problem (measured, from code)

- **(a) The shortage screen cannot act on what it finds.** `StockCheckPanel` in
  `frontend/src/pages/ShortagePage.jsx` (from `GET /api/shortage/lists/<id>/stock-check/`,
  `apps/shortage/stock_check.py::check_stock_for_list`) lists «يمكن تحويله» items but has no action.
  - Its numbers are raw `ItemStock.quantity_on_hand` at other branches, with no allowance for the donor's own
    cover. So "يمكن تحويل 10 من فرع X" can empty the donor.
  - **The WhatsApp path already has the action** (built 2026-10-04): «إنشاء مقترحات التحويل» in
    `frontend/src/pages/supply/BranchRequestsTab.jsx` (`TransfersBar`) → `POST
    /api/purchasing/isr/branch-requests/<pk>/transfers/` → `apps/purchasing/isr_fulfillment.py::create_request_transfers`.
    It makes two linked PROPOSED `IsrPush` legs per donor (donor → 100 → requesting branch), from the donor's
    excess with the owner's "HQ fills alone when its whole packs cover the request" rule. Its usage is unknown
    (to verify, read-only: count of `IsrPush` with `origin_request` set).
  - A confirmed WhatsApp request also becomes a `ShortageList` (`BranchRequest.shortage_list`). So the same
    need can reach both screens: a second "create transfer" there must not move it twice.
- **(b) Market-shortage flags made while SOFTECH is unreachable are never retried.** `push_item`
  (`apps/purchasing/shortage_writer.py`) leaves `Item.shortage_softech_synced=False` on failure. The retry
  `sync_pending` / `manage.py sync_shortage_softech` exists but **no scheduler job runs it** (no entry in
  `apps/sync/tasks.py`). The POS shortage warning then misses those items. Count of queued items: to verify
  (read-only: `Item.shortage_softech_synced=False`). The write is gated by `SHORTAGE_SOFTECH_WRITE_ENABLED`
  (default False) and the single-writer gate (`config/writers.py::writer_allowed`); its prod value is to verify.
- **(c) Transits can link to the wrong transfer.** `apps/transits/management/commands/sync_in_transit.py` builds
  `tr_map` keyed by `TransferRequest.erp_reference` alone and links a new `InTransitTransfer` with
  `tr_map.get(doc_num)`. Docnumbers repeat per (branch, doctype) (memory: docnumber collisions), so a 125 from
  branch A can link to a request whose staff-typed reference belongs to branch B. Number of mislinks: unknown
  (measured by item (c)'s report).
- **(d) Shortage supplier exports read SOFTECH live.** `apps/shortage/supplier_sourcing.py::build_sourcing` queries
  `itemssuppliers`, `stktrans⋈stktransm` (doc 10 at branch 100 since 2019) and `personsdata` on every export,
  although PG mirrors exist: `catalog.ItemSupplierLink` (nightly `itemssuppliers`) and `procurement.PurchaseLine`
  (doc 10/120). Exports fail or crawl when the link is slow.
- **(e) The procurement refresh stalled at 18-10** because the scheduler PC slept (`apps/procurement/refresh.py`
  docstring). Catch-up logic was added; the root cause goes away with the always-on VPS.

## 2. Scope

### (a) «إنشاء مقترحات التحويل» on the shortage screen — one mechanism for both paths
- **Mechanism (recommended):** the same linked `IsrPush` legs the WhatsApp path makes. One planner
  (`isr_fulfillment.compute`), one review-and-push place (the ISR tab), one set of guards. The alternative —
  DRAFT `TransferRequest` via `apps/supply/execution.py::approve_internal_transfer` — needs a `SupplyCase` per item,
  is keyed into SOFTECH by hand and depends on the docnumber link fixed in (c). Not recommended (owner choice, Q1).
- **Backend**
  1. `pseudo_isr_from_list(shortage_list)` next to `pseudo_isr` in `apps/supply/branch_requests.py`: confirmed,
     matched `ShortageItem`s → the ISR-engine shape (code, qty in packs, cost, price), `isr='SL-<id>'`,
     `kind='shortage'`, no return legs.
  2. New endpoints in `apps/shortage/views.py` (`ShortageListViewSet`):
     - `GET .../transfer-plan/?coverage=` → `isr_fulfillment.collect_requests([pi])` (fresh stock read) +
       `compute` → the same plan payload the WhatsApp tab shows.
     - `POST .../transfers/` → creates the legs.
  3. **Origin and duplicate guard.**
     - If the list came from a WhatsApp request (`shortage_list.branch_requests` exists), both endpoints delegate to
       that request (`create_request_transfers(..., req)`). The existing partial unique constraint
       (`origin_request, origin_donor, kind` while live; purchasing migration 0034) then stops a second move,
       whichever screen is used.
     - Otherwise: new `IsrPush.origin_shortage_list` (FK, null) + the same partial unique constraint on
       (`origin_shortage_list, origin_donor, kind`) while proposed/approved/pushed.
     - `isr_writer._persist_proposal` treats a draft with `origin_shortage_list` as **not general**, so it never
       supersedes the daily route draft (today `general = origin_isr is None and origin_request is None`).
  4. Permission: the same write check as the WhatsApp path (`apps/purchasing/access.py`, server-side). Branch users
     still see the stock check; only purchasing / HQ store staff can create.
- **Frontend:** in `StockCheckPanel`, a «إنشاء مقترحات التحويل» button opens the plan in the existing
  `PlanView` (exported from `frontend/src/pages/supply/IsrFulfilmentTab.jsx`) and creates on confirm. Branch names via `useBranchLabels`.
  The raw «يمكن تحويل» suggestions stay as a quick view, labelled «رصيد متاح (قبل حساب التغطية)».
- **WhatsApp path:** no build. Same button label on both screens; help text cross-references.
- **SOFTECH:** no new writer. Legs are PG-only PROPOSED drafts; SOFTECH is written only by the existing
  approve → push of the ISR writer, with its guards (route rule, branch→HQ leg before HQ→branch leg, 7-day identical
  draft needs a reason). Double-post guard = the DB constraint + the "skip donors with a live leg" check.

### (b) Schedule the market-shortage retry
- APScheduler job `shortage_softech_retry`, hourly, in `apps/sync/tasks.py`, calling `shortage_writer.sync_pending`.
  It does nothing unless `writer_allowed('SHORTAGE_SOFTECH_WRITE_ENABLED')` (already in `sync_pending`).
- **Circuit breaker:** stop the run after 3 failures in a row (same rule as P-55 Part A); log
  `remaining`. One dead connection must not cost 500 timeouts.
- The write is a state-set `UPDATE items` (flag + warning text, own warning only). Re-applying the same state is
  harmless; there is no document number, so no double-post risk.
- Audit: `audit_softech_write` already runs on success; record actor `scheduler` (today `None`).
- Health: add `shortage_unsynced` (count, oldest age) to the sync-health view planned in P-56. Target 0.

### (c) Key the transit → transfer link on more than the docnumber
- In `sync_in_transit.py`, build `tr_map` keyed by `(erp_reference, supplying branch softech id)`, and link only
  when:
  - the receiving branch also matches (`requesting_branch` ↔ `erp_receiving_branch_code`); and
  - when the transfer has `erp_match_doc_date` (from `apps/transfers/erp_matcher.py`), it is within ±3 days of the
    125's `issue_date`, and `erp_match_doc_code` is `'125'` or blank.
- More than one candidate → no link, logged `ambiguous_link` in `InTransitAuditEvent`.
- **Repair report:** new command `audit_transit_links [--commit]` (PG only). It lists existing `linked_request`
  rows whose branches do not match the 125. With `--commit` it unlinks them, with an audit event and a system note
  on both records. The owner runs it once after deploy.

### (d) Shortage exports read the mirrors
- `build_sourcing` reads:
  - suppliers per item and supplier item code from `catalog.ItemSupplierLink`;
  - last purchase per supplier (cost, date) from `procurement.PurchaseLine` (doccode 10, branch 100);
  - names from `invoices.VendorProfile` / `procurement.SupplierProfile`.
- Live SOFTECH is used only as a fallback when a mirror is stale (ItemSupplierLink older than 48 h, or the
  `purchases` freshness domain stale), and the file says which source it used.
- Same output shape, so `export_supplier_matrix` and `export_supplier_po` do not change.

### (e) Post-cutover check (no code)
- Add to the P-54 cutover switch table: for 7 days after cutover, `procurement.refresh.freshness()` shows
  `data_through` ≥ yesterday and the `purchases` freshness domain is green each morning.

### Files
- (a) `apps/supply/branch_requests.py`, `apps/shortage/views.py`, `apps/purchasing/models.py` (`IsrPush`),
  `apps/purchasing/isr_writer.py`, `apps/purchasing/isr_fulfillment.py` (accept `origin_shortage_list`),
  `frontend/src/pages/ShortagePage.jsx`, `frontend/src/api/client.js`. Migration: `purchasing` 0040.
- (b) `apps/sync/tasks.py`, `apps/purchasing/shortage_writer.py` (breaker, actor). No migration.
- (c) `apps/transits/management/commands/sync_in_transit.py`, new `apps/transits/management/commands/audit_transit_links.py`.
  No migration.
- (d) `apps/shortage/supplier_sourcing.py`. No migration.
- Help: `apps/help/content/shortage.py` (`/shortage`: new transfer button, stock-check label) and
  `apps/help/content/purchasing.py` (`/supply` «طلبات واتساب»: cross-reference); `apps/help/content/transfers.py`
  (`/transits`: link rule) for (c). Bump `updated` on each.

## 3. Acceptance criteria

- **(a)** (`apps/tests/test_shortage_transfers.py`, new; `test_branch_requests.py`, `test_isr_writer.py` still pass)
  - A list with one confirmed item and donor excess → 2 linked PROPOSED legs; a second click → 0 new, "exists".
  - A list made from a WhatsApp request → legs carry `origin_request`; creating from the WA tab afterwards → skipped.
  - A shortage-list draft does not cancel the route's general daily draft (test against `isr_guards`).
  - Donor quantity never exceeds the plan's donor excess (not raw on-hand).
  - A branch user without purchasing write rights → 403.
- **(b)** The scheduler registers `shortage_softech_retry` (scheduler test). With the writer off, the job writes
  nothing. With 3 failures in a row the run stops (test with a failing connection). Queued items are pushed when
  the connection is back (test).
- **(c)** (`apps/tests/test_transits_sync.py`) Two transfers with the same `erp_reference` from different
  supplying branches → each 125 links to its own. Branch mismatch → no link. Two candidates → no link +
  `ambiguous_link`. The repair command without `--commit` changes nothing.
- **(d)** (`apps/tests/test_supply_exports.py` or a new shortage export test) With mirrors present, no SOFTECH
  connection is opened (mocked connector asserts no call); with a stale mirror the live path is used. On a 20-item
  dev sample, mirror and live give the same suppliers and supplier codes.
- `test_help.py` passes.

## 4. Measurement

- Transfers created from shortage lists and from WhatsApp requests per week (`IsrPush` by origin). Baseline:
  0 from shortage lists; WhatsApp count to read at build time.
- Unsynced market-shortage flags: target 0, oldest < 1 h.
- Mislinked transits found by the first repair report; then 0 new.
- Shortage supplier export time (p50) before / after (d).

## Out of scope

- Changing the WhatsApp transfer planner or the ISR push.
- Turning on `SHORTAGE_SOFTECH_WRITE_ENABLED` (owner decision, separate).
- Re-linking transfers to transits automatically after the repair (only unlinking a wrong link).

## Open questions

1. (a) Mechanism: linked ISR legs (recommended, same as WhatsApp) or DRAFT TransferRequest?
2. (a) Does the shortage-screen plan use the same coverage default as the WhatsApp tab (the `_coverage` setting)?
3. (b) Is `SHORTAGE_SOFTECH_WRITE_ENABLED` on in production, and how many items are queued? (read-only check)
4. (d) Does `PurchaseLine` reach far enough back for "last bought" (live goes to 2019)? Read-only check of the
   oldest `doc_date` at branch 100. If not, the matrix shows "older than mirror" instead of a cost.

## Stop-and-ask

- **(a)** Adds a field and constraint to `IsrPush`, the staging table of a live SOFTECH writer (ISR). No new write,
  but confirm the schema change before build.
- **(b)** Makes an existing SOFTECH writer run on a schedule without a person clicking. Confirm before enabling,
  even though the write is idempotent and gated.
