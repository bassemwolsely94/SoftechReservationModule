# POS Speed Wave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every POS sale faster on desktop `/pos` and mobile `/m/pos`: search results with thumbnails and inline branch stock, contract-sale autocomplete + "last prescription", automatic FEFO split, PIC quick wins + read-only SOFTECH study, and verified alternatives.

**Architecture:** Extend what exists — the one item search endpoint (`/api/items/softech-search/`) and the shared `ItemSearchWidget` (new opt-in `variant="pos"`), the POS hook `usePosOrder.js`, `apps/pos_orders` views, `apps/customers/repeat_order.py`, `apps/composition.ItemMoleculeIndex`. Rules live in pure, tested backend functions; React renders their verdicts. No new search widget, customer model, audit system, or SOFTECH write.

**Tech Stack:** Django 4.2 + DRF, PostgreSQL, React 18 + Vite + Tailwind + TanStack Query, design system `frontend/src/pos/design/`.

**Spec:** `docs/superpowers/specs/2026-10-26-pos-speed-wave-design.md`

## Global Constraints

- No change to pricing, discounts, contract rates, co-pay math, tenders, checkout completion or `apps/pos_orders/writer.py`. Stop and ask the owner if a task seems to need one.
- **No new SOFTECH writes.** No new live SOFTECH reads during a sale; the only live read kept is the existing `/pos-orders/batches/` call, once per item add.
- Search rules stay exactly `apps/catalog/wildcard.py`. Quarantine stores `EXCLUDED_STORE_CODES` (102/103/105) never count as stock.
- Alternatives use only `ItemMoleculeIndex.source == 'approved'` rows; never `Item.name_scientific`. Nothing is auto-substituted; every alternative carries «يتطلب تأكيد الصيدلي».
- A FEFO shortfall is never reserved silently — only via the explicit «حجز الباقي» action.
- Re-used approval number = warning, never a block. This wave adds **no new send-blocking validation** on contract fields.
- Both `POSOrderPage.jsx` and `mobile/MobilePOSOrderPage.jsx` get every UI piece; mobile changes layout only (side panels become bottom sheets).
- Branch names via `useBranchLabels` (never a bare code). Use `pos/design` primitives (`StockBadge`, `BranchStockPill`, `Badge`, `ActionTile`, `Icon`…); Lucide-style icons, not emoji.
- Every task that changes a screen updates `apps/help/content/pos.py` (Arabic + English) and bumps that screen's `updated` to the task date; `apps/tests/test_help.py` must stay green.
- Backend tests: `venv/Scripts/python.exe manage.py test <module> --noinput`. Frontend check: `cd frontend && npm run build` (no JS test runner exists).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Item with no `ItemStock` rows, or a SOFTECH-live search row (`item_id: None`) → row renders with no pills and no crash; next action is `demand`.
2. Stock sync stale (failed for hours) → `stock_as_of` shows the real age and turns amber over 30 minutes; never shows "now".
3. Fractional (strip) quantities in FEFO split → every pick rounded to 5 dp half-up, Σ picks + shortfall == need exactly.
4. Arabic spelling variants in patient names (أ/إ/ا, ى/ي, ة/ه) → autocomplete still matches.
5. Branch server down when adding an item → line still added without a batch (today's behaviour) and later qty edits make no SOFTECH call.

Tests pinning these are in Tasks 1, 4, 5 and 6.

---

### Task 1: Search rows carry thumbnail, strength, network stock, next action, stock age

**Files:**
- Create: `apps/catalog/pos_search.py`
- Modify: `apps/catalog/views.py` (`softech_search`, `_search_rows`)
- Test: `apps/tests/test_pos_search_network.py`

**Interfaces:**
- Produces (pure/DB helpers in `apps/catalog/pos_search.py`):
  - `extract_strength(name: str) -> str` — first `<number>[.<number>] [/<number>] <unit>` with unit in MG, MCG, G, ML, IU, %, (case-insensitive), normalised `"5 MG"`; `""` when none.
  - `network_stock(item_ids: list[int]) -> dict[int, list[dict]]` — `{item_id: [{"branch_id": int, "qty": float}, …]}` sorted qty desc; sums all stores except `EXCLUDED_STORE_CODES`; only `Branch.is_operational=True`; one query.
  - `primary_thumbs(item_ids: list[int]) -> dict[int, str]` — URL of `ProductMedia` with `approved=True`, `media_type='image'`, `is_primary` first then lowest `order`; `thumbnail.url` if set else `file.url`; one query.
  - `next_action(here_qty: float, branch_stock: list[dict], here_branch_id: int|None) -> dict` — `{"kind": "add"}` if here_qty > 0; else `{"kind": "transfer", "from_branch_id": <branch with max qty>}` if any other branch qty > 0; else `{"kind": "demand"}`.
  - `stock_as_of() -> str|None` — ISO timestamp of the `stock` domain from `apps.sync.freshness.get_freshness(['stock'])`.
- Produces (API): `GET /api/items/softech-search/?q=&branch_id=&network=1` — when `network=1`, each row additionally has `thumb`, `strength`, `branch_stock`, `next_action`; response top level adds `stock_as_of`. Without `network=1` the response is byte-for-byte unchanged.

- [ ] **Step 1: Write the failing tests** in `apps/tests/test_pos_search_network.py`:
  - `test_extract_strength`: `"CONCOR 5MG 30 TAB" → "5 MG"`, `"CONCOR AM 5/10MG" → "5/10 MG"`, `"PANADOL EXTRA" → ""`, `"FUCIDIN 2% CREAM" → "2 %"`.
  - `test_network_stock_excludes_quarantine_and_sorts`: item with stock 4 in store 100 + 9 in store 102 at branch A, 7 at branch B → `[{"branch_id": B, "qty": 7.0}, {"branch_id": A, "qty": 4.0}]`.
  - `test_network_stock_skips_non_operational_branch`.
  - `test_next_action`: `(3, …) → add`; `(0, [{A:0},{B:5},{C:2}], A) → transfer from B`; `(0, [], A) → demand`; `(0, [{A:0}], A) → demand`.
  - `test_primary_thumb_prefers_primary_approved`: unapproved primary ignored; approved non-primary used when no approved primary.
  - `test_search_network_flag_adds_fields` (API, authenticated staff): `network=1` rows have the 4 keys and top-level `stock_as_of`; without the flag none of them appear.
  - `test_search_network_live_row_without_item_id` (Review Focus 1): a row with `item_id=None` gets `branch_stock == []`, `thumb is None`, `next_action == {"kind": "demand"}`.
- [ ] **Step 2: Run** `venv/Scripts/python.exe manage.py test apps.tests.test_pos_search_network --noinput` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement `apps/catalog/pos_search.py`** with the five functions above, and in `softech_search` read `network = request.query_params.get('network') == '1'`; after all rows are assembled (including live/expanded rows) enrich them in one pass when `network` is true. Keep `_search_rows` signature unchanged.
- [ ] **Step 4: Run the test module** — Expected: PASS. Also run `apps.tests.test_wildcard_search apps.tests.test_universal_search apps.tests.test_catalog_search_overlay` — Expected: PASS (no regression).
- [ ] **Step 5: Commit** — `feat(pos-search): network stock, thumbnails, strength and next action on item search`.

### Task 2: POS result rows, keyboard and side preview (desktop + mobile)

**Files:**
- Create: `frontend/src/pos/search/PosResultRow.jsx`, `frontend/src/pos/search/PosItemPreview.jsx`, `frontend/src/pos/search/StockAge.jsx`
- Modify: `frontend/src/components/ItemSearchWidget.jsx`, `frontend/src/api/client.js` (`itemsApi.wildcardSearch(q, branchId, { network })`), `frontend/src/pages/POSOrderPage.jsx:757`, `frontend/src/pages/mobile/MobilePOSOrderPage.jsx:104,486`, `apps/help/content/pos.py`

**Interfaces:**
- Consumes: Task 1 API fields.
- Produces:
  - `usePosOrder` export `searchAction(kind, item, extra)` (Step 2).
  - `ItemSearchWidget` new optional props: `variant: 'default'|'pos'` (default `'default'` = today's rendering, untouched for reservations/transfers), `branchId`, `onAction(kind: 'transfer'|'reserve'|'demand', item, extra)`, `onAlternatives(item)` (wired in Task 8), `sheet: boolean` (mobile: preview as bottom sheet).
  - `PosResultRow({ item, hereBranchId, selected, onAdd, onAction })` — Layout A: thumb 38px · name + strength chip (`bg-[#022871] text-white`) + form · badges (cold/batch/offer) · here pill (bold) · up to 4 other-branch `BranchStockPill`s (+N more) · price · when `next_action.kind != 'add'` one prominent `ActionTile` («تحويل من …» / «تسجيل طلب») plus secondary «حجز».
  - `PosItemPreview({ item, hereBranchId, customerId })` — large image, all branch pills, badges; when `customerId` is set, «آخر شراء لهذا العميل: منذ N يوم» from the existing `GET /api/customers/{id}/pos-summary/` purchases (fetched once per customer, cached) if it contains this item, else nothing.
  - `StockAge({ asOf })` — «المخزون منذ N دقيقة»; amber when > 30 min (Review Focus 2); «غير معروف» when null.
- Keys in `variant="pos"`: ↑/↓ move selection · Enter → `onSelect(item)` · physical `ArrowRight` key toggles the preview · Esc closes the preview, then the dropdown. Barcode-scan path unchanged.

- [ ] **Step 1: Implement the three components and the widget variant.** In `variant="pos"` the query calls `wildcardSearch(q, branchId, { network: true })` with key `['item-search-widget', debouncedQ, branchId, 'pos']`.
- [ ] **Step 2: Wire actions in `usePosOrder.js`** as `searchAction(kind, item, extra)`: `reserve` → existing reservation line (`_newLine(item, { is_reservation: true })`); `transfer` → `window.open('/transfers/new?item=<softech_id>&from=<branch_id>')` (new tab, so the sale in progress is not lost); `demand` → `POST /api/demand/` via the existing demand API client with item, branch and current customer, then a success message. If `NewTransferPage` ignores `?item=&from=`, add reading those two query params to prefill it.
- [ ] **Step 3: Use it** in both POS pages: `<ItemSearchWidget variant="pos" branchId={P.branch} onSelect={P.addItem} onAction={P.searchAction} sheet={/* mobile only */ true} …/>`.
- [ ] **Step 4: Help** — update the `pos-order-search` entry (AR+EN): thumbnails, pills meaning (green/amber/red), stock age, keys ↑↓ Enter → Esc, the row action buttons; bump `updated`.
- [ ] **Step 5: Verify** — `npm run build` succeeds; `venv/Scripts/python.exe manage.py test apps.tests.test_help --noinput` PASS; in the browser preview `/pos` and `/m/pos`: type `concor*`, rows show pills + strength chip, → opens preview, Enter adds, a 0-stock row shows its action. Screenshot both.
- [ ] **Step 6: Commit** — `feat(pos): Layout A search rows with branch pills, preview and next action (desktop + mobile)`.

### Task 3: Image search view

**Files:**
- Create: `frontend/src/pos/search/PosImageSearch.jsx`
- Modify: `POSOrderPage.jsx`, `MobilePOSOrderPage.jsx`, `frontend/src/hooks/usePosHotkeys.js`, `apps/help/content/pos.py`

**Interfaces:**
- Consumes: Task 1 API (`network=1`), Task 2 `PosItemPreview`.
- Produces: `PosImageSearch({ open, onClose, branchId, onPick })` — full-screen grid (5 cols desktop, 2 mobile) of tiles: image (or neutral placeholder), name + strength, here pill, best other-branch pill, offer badge; own search box seeded with the current query; Enter/click → `onPick(item)` then close.
- Key: **F6** opens it (my call; register in `usePosHotkeys.js`, verify F6 is free there first; if taken use Ctrl+I). Mobile: a button with an image icon beside the search box.

- [ ] **Step 1: Implement** the component and hotkey; `onPick = P.addItem`.
- [ ] **Step 2: Help** — new entry «بحث بالصور / Image search» (F6), bump `updated`.
- [ ] **Step 3: Verify** — build passes; F6 opens grid in `/pos`, picking a tile adds the line and returns focus to the search box. Screenshot.
- [ ] **Step 4: Commit** — `feat(pos): image search view (F6)`.

### Task 4: Contract history backend — patients, last prescriptions, field values, approval check

**Files:**
- Create: `apps/pos_orders/contract_history.py`
- Modify: `apps/customers/repeat_order.py` (extract `revalidate_lines`), `apps/pos_orders/models.py` (add `ContractEntryConfig`), `apps/pos_orders/admin.py`, `apps/pos_orders/views.py`, `apps/pos_orders/urls.py`
- Create: migration `apps/pos_orders/migrations/00xx_contractentryconfig.py`
- Test: `apps/tests/test_pos_contract_history.py`, existing `apps/tests/test_repeat_order.py`

**Interfaces:**
- Produces:
  - `revalidate_lines(lines: list[dict], *, branch_id: int|None) -> dict` in `apps/customers/repeat_order.py` — input lines `{"item_id"|"softech_itemcode", "qty", "unit_price"?}`; output identical shape to today's `build_repeat_order` result (`{"lines": [...], "summary": {...}}`). `build_repeat_order` becomes a thin caller; `test_repeat_order` must stay green unchanged.
  - Model `ContractEntryConfig(personcode: CharField(20, unique, blank — '' = global default), per_visit_columns: JSONField(list[str]), approval_column: CharField(20, choices = SLOT_COLUMN values), updated_by, updated_at)`. Data migration seeds the global row: `per_visit_columns=["roshettano","examdate"]`, `approval_column="roshettano"`. Columns must be in `contract_fields.SLOT_COLUMN.values()` (model `clean()` enforces). Registered in Django admin (admin-only editing).
  - `entry_config(personcode: str) -> dict` — contract row else global → `{"per_visit_columns": [...], "approval_column": "..."}`.
  - `patient_suggest(personcode: str, q: str, limit: int = 10) -> list[dict]` — union of (a) `SoftechSalesOrder` with `cust_branch_code=personcode` and `source_companies_raw.patientname` matching, (b) `InsuranceClaimPrescription` with `softech_personcode=personcode` and `patient_name` matching; matching uses wildcard rules with Arabic normalisation (reuse `apps.catalog.wildcard.text_matches`); dedupe by normalised name keeping the latest; each `{"patientname", "fields": {stable columns from (a), {} for (b)}, "last_date", "source": "pos"|"insurance"}`; stable = all 12 columns minus `per_visit_columns`.
  - `recent_prescriptions(personcode: str, patientname: str, *, branch_id: int|None, limit: int = 5) -> list[dict]` — newest first, each `{"date", "source", "ref", "total", "revalidated": revalidate_lines(...)}`.
  - `field_values(personcode: str, column: str, q: str, limit: int = 10) -> list[str]` — distinct non-empty values of that column from (a), most used first; `column` must be in `SLOT_COLUMN.values()` else `ValueError`.
  - `approval_reused(personcode: str, value: str, *, exclude_order_id: int|None = None) -> list[dict]` — earlier orders (any branch) with the same approval value: `[{"order_id", "date", "branch_id", "patientname"}]`; `[]` for blank value.
- Produces (API, permission `CanOperatePosOrders`, all read-only, no SOFTECH):
  - `GET /pos-orders/contract-assist/config/?customer=<personcode>`
  - `GET /pos-orders/contract-assist/patients/?customer=&q=`
  - `GET /pos-orders/contract-assist/history/?customer=&patient=&branch=`
  - `GET /pos-orders/contract-assist/field-values/?customer=&column=&q=`
  - `GET /pos-orders/contract-assist/approval-check/?customer=&value=`

- [ ] **Step 1: Write failing tests** in `apps/tests/test_pos_contract_history.py`:
  - `test_entry_config_global_default` → `["roshettano","examdate"]`, `"roshettano"`; `test_entry_config_contract_override`.
  - `test_config_rejects_unknown_column` (`full_clean` raises).
  - `test_patient_suggest_unions_sources_and_dedupes` (one POS order + one insurance rx, same patient → one result, latest date, source of latest).
  - `test_patient_suggest_arabic_variants` (Review Focus 4): stored «أحمد علي» matched by `q="احمد على"`.
  - `test_patient_suggest_excludes_per_visit_fields` → `fields` lacks `roshettano`/`examdate`.
  - `test_patient_suggest_scoped_to_contract` (other personcode never returned).
  - `test_recent_prescriptions_revalidates` → each card's `revalidated.summary` present; out-of-stock line flagged.
  - `test_field_values_rejects_unknown_column`.
  - `test_approval_reused_across_branches` and `test_approval_reused_blank_is_empty`.
  - API: `test_contract_assist_requires_pos_permission` (403 for a role without `pos`).
- [ ] **Step 2: Run** `manage.py test apps.tests.test_pos_contract_history apps.tests.test_repeat_order --noinput` — Expected: new FAIL, repeat_order PASS.
- [ ] **Step 3: Implement** `revalidate_lines` (refactor), the model + migration + admin, `contract_history.py`, five views, urls.
- [ ] **Step 4: Run** the same command plus `apps.tests.test_pos_api apps.tests.test_pos_models` — Expected: PASS. `manage.py makemigrations --check --dry-run` — Expected: no changes.
- [ ] **Step 5: Commit** — `feat(pos-contract): contract history assist API (patients, last prescriptions, field values, approval check)`.

### Task 5: Contract assist UI (desktop + mobile)

**Files:**
- Create: `frontend/src/pos/contract/useContractAssist.js`, `frontend/src/pos/contract/ContractAssist.jsx`
- Modify: `frontend/src/api/client.js` (`posApi.contractAssist.{config,patients,history,fieldValues,approvalCheck}`), `usePosOrder.js` (expose `applyContractPatient(fields)`, `applyPrescriptionLines(revalidated)`), the contract tab in `POSOrderPage.jsx` and `MobilePOSOrderPage.jsx`, `apps/help/content/pos.py`

**Interfaces:**
- Consumes: Task 4 endpoints; existing `claim`/`setClaim`, contract personcode (`customer.cust_branch_code` / current contract account in the hook).
- Produces:
  - `useContractAssist({ personcode, branchId })` → `{ config, suggestPatients(q), history(patient), fieldValues(column, q), checkApproval(value) }` (TanStack Query, 250 ms debounce).
  - `ContractAssist` behaviour: patient-name and membership inputs autocomplete; choosing a patient calls `applyContractPatient(fields)` (fills stable fields) and **clears + highlights** (amber ring + «جديد لهذه الزيارة») every `per_visit_columns` field; a «آخر روشتة» button shows up to 5 compact cards (date · item count · total · source); clicking a card calls `applyPrescriptionLines(card.revalidated)` which adds each available line via the normal add path (so batch logic in Task 6 applies) and lists skipped/out-of-stock/blocked lines in a non-modal note; approval field blur → `checkApproval` → amber inline warning «رقم الموافقة استُخدم من قبل في …» with dates — never blocks; free-text enabled fields (`deptname`, `comment`, …) get `fieldValues` suggestions.
  - Mobile: same component; cards in a horizontal scroller.

- [ ] **Step 1: Implement** hook, component, hook exports; render `ContractAssist` above the existing claim fields only when the channel is a claim channel.
- [ ] **Step 2: Help** — contract tab entry: autocomplete, «آخر روشتة», per-visit highlight, approval warning; bump `updated`.
- [ ] **Step 3: Verify** — build passes; in `/pos` with a contract customer that has prior orders: typing part of a patient name suggests; choosing fills stable fields and highlights روشتة/تاريخ الكشف; «آخر روشتة» adds lines; a re-used approval no. shows the warning and the order can still be sent. Screenshot desktop + mobile.
- [ ] **Step 4: Commit** — `feat(pos-contract): patient autocomplete, last prescription and approval warning (desktop + mobile)`.

### Task 6: Automatic FEFO split

**Files:**
- Modify: `apps/pos_orders/batch_availability.py`, `apps/pos_orders/views.py`, `apps/pos_orders/urls.py`, `frontend/src/hooks/usePosOrder.js`, line rendering in `POSOrderPage.jsx` + `MobilePOSOrderPage.jsx`, `apps/help/content/pos.py`
- Test: `apps/tests/test_pos_batch_availability.py` (add `FefoSplitTests`)

**Interfaces:**
- Produces:
  - `fefo_split(batches: list[dict], need: float) -> dict` in `batch_availability.py` — batches as returned by `_parse_rows` (expiry-ascending); returns `{"picks": [{"expiry", "batchno", "qty", "available"}], "shortfall": float}`; each `qty` = `min(remaining, available)` rounded 5 dp `ROUND_HALF_UP`; zero-qty picks omitted; batches with `qty <= 0` skipped; `need <= 0` → no picks, shortfall 0.
  - `POST /pos-orders/fefo-split/` body `{"batches": [...], "need": n}` → `fefo_split` result. Pure, no SOFTECH, permission `CanOperatePosOrders`; rejects > 50 batches or negative need with 400.
  - Hook: `batchCacheRef` keyed by `softech_itemcode` (filled from the existing `/pos-orders/batches/` response, never refetched on qty edits — Review Focus 5); lines added by auto-split share `fefo_group` (uuid) and carry `fefo_auto: true`; `setFefoQty(group, qty)` → calls `fefo-split` with cached batches → replaces that group's lines; `shortfall > 0` stores `fefo_shortfall` on the group (no reservation line); `reserveRemainder(group)` adds `_newLine(item, { qty: shortfall, is_reservation: true, fefo_group: group })` and clears the shortfall; `openBatchModal(group)` reopens today's modal prefilled with the group's picks (manual change replaces the group).
  - `addItem` change: action `optional` → **no modal**; split `need = 1` and add the picks. `must_select`, `auto_select`, `reserve`, `plain`, `coupon_serial` unchanged. Modal `fefoFill` calls the endpoint instead of computing locally.
  - Line UI for a group: one visual row with «N تشغيلات» chip + expiries in small text, qty input bound to `setFefoQty`, shortfall chip «ناقص X — حجز الباقي» bound to `reserveRemainder`, action «تغيير التشغيلة» → `openBatchModal`.

- [ ] **Step 1: Write failing tests** `FefoSplitTests`: `test_single_batch_covers`; `test_spans_batches_earliest_first` (`[2, 1, 3]`, need 4 → `[2, 1, 1]`, shortfall 0); `test_shortfall` (`[2]`, need 5 → shortfall 3.0); `test_fractional_strips` (Review Focus 3: `[0.33333, 1]`, need 0.66667 → picks `[0.33333, 0.33334]`, Σ == 0.66667); `test_skips_empty_batches`; `test_zero_need`; API `test_fefo_split_endpoint_no_softech` (patch `get_branch_connection` to raise — endpoint still 200).
- [ ] **Step 2: Run** `manage.py test apps.tests.test_pos_batch_availability --noinput` — Expected: FefoSplitTests FAIL, existing PASS.
- [ ] **Step 3: Implement** `fefo_split`, the view and url; then the hook + line UI changes on both pages.
- [ ] **Step 4: Run** the module plus `apps.tests.test_pos_quantity apps.tests.test_pos_validators apps.tests.test_pos_reservation` — Expected: PASS. `npm run build` — Expected: success.
- [ ] **Step 5: Verify in browser** — add a multi-batch non-mandatory item: no modal, one row «1 تشغيلة»; set qty above the first batch → «2 تشغيلات»; set qty above total → shortfall chip, no reservation line until «حجز الباقي» is clicked; Entresto-type mandatory item still opens the modal. Screenshot.
- [ ] **Step 6: Help** — line batch chip, shortfall, «تغيير التشغيلة»; bump `updated`.
- [ ] **Step 7: Commit** — `feat(pos): automatic FEFO split on qty entry; explicit reserve for shortfall`.

### Task 7: New-customer quick wins + read-only SOFTECH PIC study

**Files:**
- Create: `apps/customers/address_suggest.py`, `apps/customers/management/commands/investigate_pic_create.py`, `docs/architecture/PIC_CREATE_INVESTIGATION.md`
- Modify: `apps/customers/views.py` (+ action), `frontend/src/components/POSCustomerModal.jsx` (Add tab), `frontend/src/api/client.js`, `apps/help/content/pos.py`
- Test: `apps/tests/test_address_suggest.py`, `apps/tests/test_pic_create_probe.py`

**Interfaces:**
- Produces:
  - `address_suggest(field: str, q: str, *, area: str = '', limit: int = 10) -> list[str]` — field ∈ `{"area", "district", "landmark"}` (else `ValueError`); distinct non-empty values from `delivery.CustomerLocation` (and the order-level `delivery_area`/`delivery_district`/`delivery_landmark`), wildcard + Arabic-normalised match, most used first; `district`/`landmark` narrowed by `area` when given.
  - `GET /api/customers/address-suggest/?field=&q=&area=` (staff auth, `customers` view permission).
  - Add tab: phone is the first field; at ≥ 8 digits it calls the existing `customersApi.recognize(phone)` and lists matches (name, PIC, branch) with «استخدم هذا العميل» → selects it and closes; name field also shows recognize-by-name matches; area/district/landmark inputs autocomplete via `address-suggest`; only name + phone are required (others optional). Saving still goes to today's customers CRUD (PG only) — no SOFTECH write.
  - `investigate_pic_create` command: **SELECT-only** (runs under `SOFTECH_READ_ONLY`); `--host` (default HQ) `--branch-nodes` flag; writes `scratch/pic_create_probe.txt`: column list + NOT NULL/defaults of `localcustomers` and every table carrying a PIC (via `syscolumns`/`sysobjects`), triggers on those tables (`sp_helptext` names only), the PIC allocation pattern from the 50 newest customers (max PIC per branch prefix, gaps), and for those 50 which branch nodes already hold them (replication lag). No names or phones in the output.
- [ ] **Step 1: Write failing tests**: `test_address_suggest_ranks_by_use`, `test_address_suggest_arabic_variants`, `test_address_suggest_rejects_field`, `test_address_suggest_narrows_by_area`; `test_pic_probe_issues_only_selects` (fake cursor records SQL; every statement starts with `SELECT`/`sp_help`/`SET ROWCOUNT`; none contains INSERT/UPDATE/DELETE) and `test_pic_probe_masks_personal_data`.
- [ ] **Step 2: Run** `manage.py test apps.tests.test_address_suggest apps.tests.test_pic_create_probe --noinput` — Expected: FAIL.
- [ ] **Step 3: Implement** helper, view, command, Add-tab changes. Add `investigate_pic_create` to the SOFTECH read manifest if the static guard in `apps/tests/security/` requires it.
- [ ] **Step 4: Run** the two modules plus `apps.tests.test_customer_recognition apps.tests.security` — Expected: PASS. `npm run build` — success.
- [ ] **Step 5: Write `docs/architecture/PIC_CREATE_INVESTIGATION.md`** — purpose, what the probe reads, how to run it, a "Findings" section left for the run output, and the explicit statement: no trial inserts; writer deferred until a safe SOFTECH test target exists and the owner approves.
- [ ] **Step 6: Help** — Add tab: phone first, «استخدم هذا العميل», address suggestions; bump `updated`.
- [ ] **Step 7: Commit** — `feat(customers): phone-first duplicate check + address autocomplete; read-only PIC creation probe`.

### Task 8: Verified alternatives + DrugEye link

**Files:**
- Create: `apps/composition/alternatives.py`, `frontend/src/pos/search/PosAlternatives.jsx`
- Modify: `apps/composition/views.py` (+ view), `apps/composition/urls.py`, `ItemSearchWidget.jsx` (`onAlternatives`), `usePosHotkeys.js`, both POS pages, `apps/help/content/pos.py`
- Test: `apps/tests/test_pos_alternatives.py`

**Interfaces:**
- Consumes: Task 1 `network_stock`, `primary_thumbs`, `extract_strength`.
- Produces:
  - `alternatives_for(item_id: int, *, branch_id: int|None, limit: int = 20) -> dict` — `{"verified": bool, "same": [...], "other": [...]}`. The item's signature = set of `(molecule, strength_value, strength_unit)` from its `ItemMoleculeIndex` rows; if any of its rows is not `source='approved'` (or it has none) → `{"verified": False, "same": [], "other": []}`. `same` = other active items whose approved signature is identical **and** same `dosage_form`; `other` = items with the identical molecule set but different strength or form. Candidate items with any non-approved row are excluded. Each row: `{item_id, softech_id, name, strength, dosage_form, pack_price, thumb, here_qty, branch_stock}`; sorted here_qty desc then price asc.
  - `GET /api/composition/alternatives/?item=&branch=` (staff auth, `pos` view permission).
  - `PosAlternatives({ item, branchId, onPick, onClose })` — side panel (bottom sheet on mobile): original vs alternatives side by side (image, name, strength, form, price, here pill, branch pills), header banner «يتطلب تأكيد الصيدلي» on every alternative, «غير متاح — بيانات المادة الفعالة غير معتمدة لهذا الصنف» when `verified` is false; pick → `onPick(item)` adds as a normal line (no automatic replacement of an existing line). Button «ابحث في DrugEye» → `window.open` of `https://www.drugeye.pharorg.com/drugeyeapp/android-search/drugeye-android-live-go.aspx` with the name as a query parameter if the site accepts one (check manually once; if not, open the page and `navigator.clipboard.writeText(name)` with a note «تم نسخ الاسم»). No fetching of DrugEye content.
  - Key: **F7** on a selected search row (register in `usePosHotkeys.js`; same free-key check as Task 3).
- [ ] **Step 1: Write failing tests**: `test_unverified_item_returns_not_verified`; `test_same_signature_same_form`; `test_other_strength_goes_to_other`; `test_combo_requires_full_molecule_set` (A+B item never matches A-only item); `test_candidate_with_unapproved_row_excluded`; `test_never_uses_name_scientific` (two items with equal `name_scientific` but no approved rows → no alternatives); API `test_alternatives_requires_auth`.
- [ ] **Step 2: Run** `manage.py test apps.tests.test_pos_alternatives --noinput` — Expected: FAIL.
- [ ] **Step 3: Implement** helper, view, url, panel, hotkey, widget hook-up.
- [ ] **Step 4: Run** module + `apps.tests.test_ingredient_search apps.tests.test_ingredient_composition` — Expected: PASS. `npm run build` — success.
- [ ] **Step 5: Verify** — in `/pos` select a row with approved composition, F7 shows the comparison with the pharmacist banner; an unapproved item shows the "not verified" message; DrugEye button opens a new tab. Screenshot desktop + mobile.
- [ ] **Step 6: Help** — alternatives panel + DrugEye button; bump `updated`.
- [ ] **Step 7: Commit** — `feat(pos): verified alternatives side panel (F7) + DrugEye link-out`.

### Task 9: Whole-wave verification and docs

**Files:**
- Modify: `docs/architecture/20_POS_3.0_COMMERCE_OS.md` (new section «POS Speed Wave»), `docs/architecture/11_ERP_INDEX.md` (API index: new endpoints), `docs/architecture/04_API_REGISTRY.md`

- [ ] **Step 1: Run** the full suite `venv/Scripts/python.exe manage.py test --noinput` — Expected: all PASS (note any pre-existing failures separately; none may be introduced).
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: success, no new warnings about missing imports.
- [ ] **Step 3: Regression click-through** in the browser preview: reservations and transfers item search still render the default (old) dropdown; a cash sale and a contract sale can be built and sent to the cashier exactly as before (dry-run/flag settings unchanged); Exception Center loads.
- [ ] **Step 4: Update the three docs** with what was built, endpoints, keys (F6/F7), and the deferred PIC writer.
- [ ] **Step 5: Commit** — `docs(pos): record POS Speed Wave`.
