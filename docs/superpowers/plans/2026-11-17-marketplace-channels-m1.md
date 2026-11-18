# Marketplace Channels M1 — Platform-Agnostic Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `apps/marketplace` that can take orders from any delivery/e-commerce platform (by API webhook or typed in by staff), decide per-branch sellable stock, and turn each accepted order into a DRAFT indirect-POS order on the platform's SOFTECH credit account — with no real platform connected yet and every outward switch OFF.

**Architecture:** One thin app of adapters over what exists. Stock comes from `catalog.ItemStock`; orders become `pos_orders.SoftechSalesOrder` drafts (the existing ready → push → cashier flow posts them; this app never writes SOFTECH). A `PlatformAdapter` interface isolates every platform-specific detail; M1 ships only `manual` (staff typing) and `fake` (tests) adapters, so Talabat/Amazon/Noon later = one adapter file each.

**Tech Stack:** Django 4.2 + DRF, PostgreSQL, React 18 + Vite + Tailwind + TanStack Query.

**Spec:** `docs/architecture/38_MARKETPLACE_CHANNELS_RESEARCH.md` (§4 chain, §5 decisions).

## Global Constraints

- Owner decision (doc 38 §5.1): **every** platform order posts as a credit (آجل) sale to that platform's own SOFTECH customer — `channel='contract'`, `cust_branch_code = MarketplaceChannel.softech_personcode` — including own-rider cash on delivery.
- This app writes **nothing** to SOFTECH and calls **no** writer. It creates `SoftechSalesOrder` in `status='draft'` only; staff push it through the existing POS flow. No entry in `softech_write_manifest.py`.
- Switches (settings, `config('…', default=False, cast=bool)`): `MARKETPLACE_ENABLED` (module visible at all), `MARKETPLACE_PUSH_ENABLED` (any HTTP call to a platform; when OFF, adapters run in dry-run and only log the payload). Both default OFF.
- Nothing is listed by default. An item is sellable on a channel only when a `ChannelListing` exists with `approved=True`, set by a user with `marketplace.approve`, and the item passes `catalog.safety.blocks_sale()` = False, has no `warn` flag, and is not fridge unless `allow_fridge=True`. SOFTECH has no reliable Rx/controlled column (`catalog/safety.py`), so Rx safety = human approval per item.
- Quarantine/closed stores excluded from stock: store codes `102`, `103`, `105`, and branch store `110`.
- Platform price is deterministic: `price_rule` ∈ {`shelf`, `shelf_plus_pct`}; `shelf` = round2(`Item.pack_price` × (1 + (`sale_tax_pct` or 0)/100)), half-up to 0.01 (retail incl. tax; `pack_price_tax` is not used — on some 0%-tax items it is below `pack_price`; final-review ruling 2026-11-18); `shelf_plus_pct` = shelf × (1 + pct/100) rounded half-up to 0.25 EGP. Default `shelf`. The SOFTECH draft always uses the normal POS pricing (`pos_orders/pricing.py`), never the platform price.
- Idempotency: `ExternalOrder` unique on `(channel, external_id)`; POS draft `client_token = uuid5(NAMESPACE_URL, f'marketplace:{channel.code}:{external_id}')`.
- Every status change, acceptance, rejection, listing approval and settlement match → `AuditLog.log(action, user=, obj=, request=, old_data=, new_data=, extra=)`.
- Branch data through `core.branch_scope` (`scope`, `allows`, `require`, `BranchScopedMixin`).
- Arabic-first UI copy; wording rules: «سيرفر» not «خادم»; branch shown via `useBranchLabels`, never a bare code; every grid sortable (`useSortableRows`/`SortTh`).
- Work on a fresh branch `claude/marketplace-m1` from up-to-date `origin/main` (not the current `claude/unified-item-search-s3`). Tests: `python manage.py test apps.tests.test_marketplace --keepdb` with a unique `TEST_DB_NAME`; run security sweeps serially, never `--parallel`.

## Review Focus

1. **The same platform order arrives twice** (webhook retry, or webhook + staff typing it) → one `ExternalOrder`, one POS draft. Test in Task 4 (`test_duplicate_webhook_is_one_order`) and Task 5 (`test_convert_twice_returns_same_draft`).
2. **A line's item is no longer approved / now blocked / out of stock at acceptance** → order cannot be accepted; the line is shown with the reason; nothing reaches POS. Test in Task 4 (`test_accept_refuses_unlisted_or_blocked_line`, `test_accept_refuses_oos_line`).
3. **A staff member of branch A opens or accepts an order of branch B** → 404/403. Test in Task 6 (`test_other_branch_order_hidden`).
4. **The platform's SOFTECH account code is blank** → conversion refuses with a clear message instead of creating a cash draft. Test in Task 5 (`test_convert_without_personcode_refused`).
5. **A settlement file line has no matching order, or an amount that differs** → it lands in the exception list, never auto-"matched". Test in Task 7 (`test_unmatched_and_mismatch_become_exceptions`).

---

## File Structure

```
apps/marketplace/
  __init__.py, apps.py, admin.py
  access.py          — flag + RBAC (pattern: apps/usage_print/access.py)
  models.py          — MarketplaceChannel, ChannelStore, ChannelListing, ExternalOrder,
                       ExternalOrderLine, ExternalOrderEvent, PushLog, SettlementBatch, SettlementLine
  eligibility.py     — can this item be listed / sold on a channel
  availability.py    — per-branch sellable qty + platform price
  adapters/__init__.py — registry get_adapter(code)
  adapters/base.py   — PlatformAdapter interface + dataclasses
  adapters/manual.py — staff-typed orders (no network)
  adapters/fake.py   — test adapter
  intake.py          — ingest / accept / reject / status transitions
  to_pos.py          — ExternalOrder → SoftechSalesOrder draft
  push.py            — stock/price/status push runner (dry-run when switch OFF)
  settlement.py      — CSV import + matching
  serializers.py, views.py, urls.py
  migrations/0001_initial.py
apps/tests/test_marketplace.py
apps/help/content/marketplace.py
frontend/src/pages/MarketplacePage.jsx (+ tabs under frontend/src/pages/marketplace/)
```
Modified: `config/settings.py` (INSTALLED_APPS, 2 flags), `config/urls.py`, `apps/users/models.py` (MODULE_CHOICES + migration), `apps/users/management/commands/seed_permissions.py`, `core/middleware/module_access.py`, `apps/tests/security/canary.py` (if it needs a builder), `apps/tests/new_value_registry.py`, `docs/security/PERMISSION_MATRIX.md` (regenerated), `frontend/src/App.jsx`, `frontend/src/components/navGroups.js`, `frontend/src/api/client.js`, `docs/architecture/11_ERP_INDEX.md`, doc 38 status line.

---

### Task 1: App skeleton, models, access and module registration

**Files:**
- Create: `apps/marketplace/{__init__,apps,admin,access,models}.py`, `apps/marketplace/migrations/0001_initial.py`
- Modify: `config/settings.py`, `apps/users/models.py` (+ users migration), `apps/users/management/commands/seed_permissions.py`, `core/middleware/module_access.py`
- Test: `apps/tests/test_marketplace.py`

**Interfaces:**
- Produces (models, all `verbose_name` Arabic):
  - `MarketplaceChannel`: `code` (slug, unique: e.g. `talabat`, `instashop`, `chefaa`, `amazon_eg`, `noon_eg`, `manual_test`), `name`, `adapter` (choices `manual`/`fake`, later more), `scope` (`per_branch`/`national`), `softech_personcode` (CharField 8, blank), `price_rule` (`shelf`/`shelf_plus_pct`), `price_pct` (Decimal 5,2, default 0), `stock_buffer` (Decimal, default 1), `max_qty_per_item` (int, null), `is_active` (default False), `credentials` (JSONField, default {}, never serialized), timestamps.
  - `ChannelStore`: `channel` FK, `branch` FK `branches.Branch`, `external_store_id` (blank), `delivery_mode` (`platform_rider`/`own_rider`), `is_active` (default False); unique (`channel`, `branch`). National channels have exactly one store (the fulfilling branch).
  - `ChannelListing`: `channel` FK, `item` FK `catalog.Item`, `external_sku` (blank), `approved` bool default False, `approved_by` FK StaffProfile null, `approved_at`, `allow_fridge` bool default False, `note`; unique (`channel`, `item`).
  - `ExternalOrder`: `channel` FK, `store` FK ChannelStore, `branch` FK (denormalised from store), `external_id`, `source` (`api`/`manual`), `status` (see Task 4), `customer_name`, `customer_phone` (stored; masked on output), `delivery_address` (text), `payment_mode` (`platform_paid`/`cash_on_delivery`), `platform_total` Decimal, `raw_payload` JSON, `reject_reason`, `pos_order` OneToOne `pos_orders.SoftechSalesOrder` null, `needs_review` bool, `created_by`, timestamps; unique (`channel`, `external_id`).
  - `ExternalOrderLine`: `order` FK, `listing` FK null, `item` FK null, `external_sku`, `name`, `qty` Decimal(12,3), `platform_unit_price` Decimal, `problem` (CharField: '' / `not_listed` / `blocked` / `out_of_stock`).
  - `ExternalOrderEvent`: `order` FK, `from_status`, `to_status`, `by` FK null, `note`, `at`.
  - `PushLog`: `channel` FK, `store` FK null, `kind` (`stock`/`price`/`status`), `dry_run` bool, `payload` JSON, `response` JSON, `ok` bool, `at`.
  - `SettlementBatch` / `SettlementLine` — see Task 7 (create the tables here in 0001).
- `access.py`: `MODULE = 'marketplace'`; `enabled()`; `class Access(user_or_request)` with `can_view`, `can_create` (manual intake, accept/reject, status), `can_approve` (listing approval), `can_edit` (channels/stores/settlement); `as_dict()`; `can_open(user)`.

- [ ] **Step 1: Write failing tests** `test_flag_off_hides_everything` (with `MARKETPLACE_ENABLED=False`, `Access(admin).can_view is False`), `test_flag_on_admin_sees_all`, `test_pharmacist_has_view_and_create_not_approve` (per seed below), `test_external_order_unique_per_channel` (second create with same channel+external_id raises `IntegrityError`).
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_marketplace --keepdb` → FAIL (module missing).
- [ ] **Step 3: Implement** models + access; add `'apps.marketplace'` to INSTALLED_APPS; flags `MARKETPLACE_ENABLED`, `MARKETPLACE_PUSH_ENABLED` next to `USAGE_PRINT_ENABLED`; `('marketplace', 'المنصات والتطبيقات')` in `MODULE_CHOICES` + users migration; seed rows: admin all; supervisor `{'view','create','approve','edit','export'}`; pharmacist `{'view','create'}`; call_center `{'view','create'}`; quality_manager `{'view','export'}`; purchasing `{'view'}`; viewer none. `core/middleware/module_access.py`: map prefix `marketplace` → module `marketplace`, and add `/api/marketplace/webhooks/` to `EXEMPT_PREFIXES` with comment "own gate: adapter signature check + channel active (apps/marketplace/views.py webhook)". `makemigrations marketplace users`.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** `feat(marketplace): app skeleton, models, access, module registration`.

---

### Task 2: Eligibility and availability (listing safety, per-branch qty, price)

**Files:** Create `apps/marketplace/eligibility.py`, `apps/marketplace/availability.py`; Test `apps/tests/test_marketplace.py`

**Interfaces:**
- Consumes: Task 1 models; `catalog.safety.item_safety_flags(item)`, `blocks_sale(item)`; `catalog.ItemStock`.
- Produces:
  - `listing_problem(listing) -> str` — `''` if sellable, else `'not_approved'` / `'blocked'` / `'restricted'` (any `warn` flag) / `'fridge'` (fridge flag and not `allow_fridge`).
  - `sellable_qty(listing, branch) -> Decimal` — Σ `ItemStock.quantity_on_hand` for the branch excluding store codes `{'102','103','105'}` and branch store `110`, minus Σ `ExternalOrderLine.qty` of that item on orders of that branch in statuses `accepted`/`preparing`/`ready` whose `pos_order` is not yet `settled`, minus `channel.stock_buffer`; floored at 0; capped by `channel.max_qty_per_item` when set; whole units (floor). Returns 0 when `listing_problem(listing)` is not `''`.
  - `platform_price(listing) -> Decimal` — per Global Constraints (rounded half-up to 0.25).
  - `snapshot(channel, store) -> list[dict]` — `[{listing_id, item_id, external_sku, qty, price, problem}]` for all listings of the channel.

- [ ] **Step 1: Failing tests** `test_unapproved_listing_not_sellable` (qty 0, problem `not_approved`); `test_blocked_item_not_sellable` (item `item_archive=True` → `blocked`); `test_fridge_needs_allow_flag`; `test_quarantine_stores_excluded` (stock 5 in store `102` + 3 in normal store, buffer 1 → qty 2); `test_open_orders_reserve_stock` (accepted order of 2 → qty drops by 2); `test_price_plus_pct_rounds_to_quarter` (shelf `pack_price_tax` 10.00, pct 12 → 11.20 → `Decimal('11.25')`); `test_price_shelf_is_pack_price_tax`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the four functions.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(marketplace): listing eligibility and per-branch availability`.

---

### Task 3: Adapter interface, manual + fake adapters, push runner

**Files:** Create `apps/marketplace/adapters/{__init__,base,manual,fake}.py`, `apps/marketplace/push.py`; Test same file.

**Interfaces:**
- Produces in `adapters/base.py`:
  - `@dataclass IncomingLine(external_sku: str, name: str, qty: Decimal, unit_price: Decimal, item_id: int | None = None)`
  - `@dataclass IncomingOrder(external_id: str, external_store_id: str, customer_name: str, customer_phone: str, address: str, payment_mode: str, total: Decimal, lines: list[IncomingLine], raw: dict)`
  - `class PlatformAdapter`: `code: str`; `verify_webhook(request) -> bool`; `parse_order(payload: dict) -> IncomingOrder`; `push_stock(store, rows: list[dict]) -> dict`; `push_prices(store, rows: list[dict]) -> dict`; `send_status(order, status: str) -> dict`. Base implementations of the network methods raise `NotImplementedError`.
- `adapters/__init__.py`: `get_adapter(code: str) -> PlatformAdapter` (registry dict; unknown → `KeyError`).
- `manual.py`: `verify_webhook` → False (never takes webhooks); `parse_order` builds from the manual-intake form dict; network methods return `{'skipped': 'manual'}`.
- `fake.py`: `verify_webhook` checks header `X-Fake-Signature == channel.credentials['secret']`; records calls in a module-level list for tests.
- `push.py`: `push_stock(channel, store=None, *, user=None) -> list[PushLog]` and `push_status(order) -> PushLog` — build rows from `availability.snapshot`, and if `settings.MARKETPLACE_PUSH_ENABLED` is False or `channel.is_active` is False → write `PushLog(dry_run=True, payload=rows, ok=True)` and call nothing; else call the adapter and log the response (errors → `ok=False`, message through `core.errors.public_error`, never raise).

- [ ] **Step 1: Failing tests** `test_push_is_dry_run_when_switch_off` (fake adapter call list stays empty; one PushLog `dry_run=True`); `test_push_calls_adapter_when_on_and_active` (`override_settings(MARKETPLACE_PUSH_ENABLED=True)`, channel active → one call); `test_adapter_error_logged_not_raised`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(marketplace): adapter interface, manual/fake adapters, dry-run push runner`.

---

### Task 4: Order intake and status machine

**Files:** Create `apps/marketplace/intake.py`; Test same file.

**Interfaces:**
- Consumes: Tasks 1–3.
- Statuses (Arabic labels in model choices): `received` «جديد», `accepted` «مقبول», `rejected` «مرفوض», `preparing` «جاري التحضير», `ready` «جاهز للتسليم», `handed_over` «سُلِّم للمندوب», `delivered` «تم التوصيل», `cancelled` «ملغى». Allowed: received→accepted|rejected|cancelled; accepted→preparing|cancelled; preparing→ready|cancelled; ready→handed_over|cancelled; handed_over→delivered. Anything else → `ValueError('انتقال غير مسموح')`.
- Produces:
  - `ingest(channel, incoming: IncomingOrder, *, source: str, user=None) -> tuple[ExternalOrder, bool]` (bool = created). Resolves store by `external_store_id` (per-branch) or the single store (national); maps each line to a listing by `external_sku` or `item_id`; sets `line.problem` via `listing_problem` / `sellable_qty`. Existing `(channel, external_id)` → returns it with `False`, no change. Inside `transaction.atomic` + `IntegrityError` fallback to the existing row.
  - `accept(order, user, request=None) -> ExternalOrder` — recompute problems with `listing_problem` + `sellable_qty` (the live SOFTECH `stkbal` check stays where it is today: the POS push, `pos_orders/stock.py`); any line with a problem → `ValueError` listing them; else status `accepted`, then calls `to_pos.convert(order, user)` (Task 5), then `push.push_status(order)`.
  - `reject(order, user, reason: str, request=None)`; `set_status(order, to_status, user, note='', request=None)`.
  - Every transition writes `ExternalOrderEvent` + `AuditLog.log('marketplace_order_<to_status>', …)`.

- [ ] **Step 1: Failing tests** `test_duplicate_webhook_is_one_order`; `test_accept_refuses_unlisted_or_blocked_line`; `test_accept_refuses_oos_line`; `test_illegal_transition_raises`; `test_every_transition_audited` (AuditLog count + ExternalOrderEvent rows).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (stub `to_pos.convert` import is real in Task 5 — write Task 4 tests with `patch('apps.marketplace.to_pos.convert')`). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(marketplace): order intake, accept/reject and status machine`.

---

### Task 5: Accepted order → POS draft on the platform account

**Files:** Create `apps/marketplace/to_pos.py`; Test same file.

**Interfaces:**
- Consumes: `pos_orders.models.SoftechSalesOrder`, `SoftechSalesOrderLine`. Line prices = the values `/pos` puts on a line: `item_sale_price = item.pack_price`, `item_sale_price_tax = item.pack_price_tax`, `sale_tax_pct = item.sale_tax_pct` (check against what `catalog/pos_search.py` returns to `/pos` and use that source if it differs per branch). Totals are computed by the existing writer at push (`pos_orders/pricing.compute_line/compute_header`) — do not reimplement. Branch codes exactly as `OrderSerializer.create` sets them (`softech_branchcode = branch.softech_branch_id`, `store_code` = first 3 chars).
- Produces: `convert(order, user) -> SoftechSalesOrder`.
  - Refuses with `ValueError('حساب المنصة في SOFTECH غير محدد')` when `channel.softech_personcode` is blank.
  - `client_token` = uuid5 per Global Constraints; if a `SoftechSalesOrder` with that token exists → link and return it (no second draft).
  - Fields: `status='draft'`, `doc_kind='sale'`, `channel='contract'`, `branch`, `softech_branchcode`/`store_code` as above, `cust_branch_code=channel.softech_personcode`, `customer_name=f'{channel.name} — {order.external_id}'`, `notes=f'طلب {channel.name} رقم {order.external_id}'`, `created_by=user`, `seller_usercode` = user's `softech_user_id`.
  - One `SoftechSalesOrderLine` per external line (item, `softech_itemcode`, qty, prices from POS pricing, `cust_discp=0`).
  - Sets `order.pos_order`; audit `marketplace_pos_draft_created` with the draft id.
- Not in M1 (record in the plan's handoff): verifying with a SOFTECH rollback-probe that a contract-channel sale on a platform personcode settles without patient/claim data (memory: POS writer golden-template verify). Until that is done, staff push these drafts only after the owner's go-ahead.

- [ ] **Step 1: Failing tests** `test_convert_creates_contract_draft_on_platform_account` (asserts channel `contract`, `cust_branch_code`, status `draft`, line count, notes contain external id); `test_convert_twice_returns_same_draft`; `test_convert_without_personcode_refused`; `test_convert_never_calls_writer` (`patch('apps.pos_orders.writer.push_order')` or the writer's push entry → `assert_not_called`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS (also re-run Task 4 tests without the patch).
- [ ] **Step 5: Commit** `feat(marketplace): accepted orders become POS drafts on the platform account`.

---

### Task 6: API (channels, stores, listings, orders, manual intake, webhook, push)

**Files:** Create `apps/marketplace/serializers.py`, `views.py`, `urls.py`; Modify `config/urls.py` (`path('api/marketplace/', include('apps.marketplace.urls'))`); Test same file.

**Interfaces (all under `/api/marketplace/`; every view `IsAuthenticated` + `matrix_permission('marketplace', …)` + `Access` flag check → 404 when the flag is off):**
- `GET/POST channels/`, `GET/PATCH channels/<id>/` — edit; `credentials` write-only, never returned.
- `GET/POST stores/`, `PATCH stores/<id>/` — edit; branch-scoped.
- `GET listings/?channel=&q=&approved=` (with `problem` + per-branch `qty` for the user's branch), `POST listings/` (create unapproved), `POST listings/<id>/approve/` + `.../unapprove/` — approve; audited.
- `GET orders/?status=&channel=&branch=` (branch-scoped, `customer_phone` masked through `apps/customers/access.py`), `GET orders/<id>/` (lines, problems, events, linked POS draft id/status).
- `POST orders/manual/` — create via `manual` adapter + `ingest(source='manual')`; body `{channel, branch, external_id, customer_name, customer_phone, address, payment_mode, lines:[{item_id, qty, unit_price}]}`.
- `POST orders/<id>/accept/`, `.../reject/ {reason}`, `.../status/ {to_status, note}`.
- `POST webhooks/<channel_code>/` — `AllowAny`; 404 unless flag on and channel active; `adapter.verify_webhook(request)` False → 403; else `ingest(source='api')`; always 200 on a duplicate.
- `POST channels/<id>/push-stock/` — edit; returns the PushLog rows (dry-run when switch off).
- `GET push-log/?channel=` — view.

- [ ] **Step 1: Failing tests** `test_other_branch_order_hidden`; `test_manual_intake_end_to_end` (create → accept → POS draft exists); `test_webhook_bad_signature_403`; `test_webhook_disabled_channel_404`; `test_credentials_never_returned`; `test_phone_masked_in_list`; `test_pharmacist_cannot_approve_listing` (403).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS, then the security sweeps serially: `python manage.py test apps.tests.security --keepdb` (route classification, role × route sweep, canary). Fix any unclassified route or canary skip (add a builder in `apps/tests/security/canary.py` if `ExternalOrder` is skipped). Regenerate `docs/security/PERMISSION_MATRIX.md` with the project's generator.
- [ ] **Step 5: Commit** `feat(marketplace): API, manual intake, webhook entry, push endpoint`.

---

### Task 7: Settlement import and matching

**Files:** Create `apps/marketplace/settlement.py`; extend views/urls; Test same file.

**Interfaces:**
- Models (tables created in Task 1): `SettlementBatch(channel, period_from, period_to, file_name, uploaded_by, uploaded_at, column_map JSON)`; `SettlementLine(batch, external_id, gross, commission, delivery_fee, net, order FK ExternalOrder null, match_status: 'matched'|'unmatched'|'amount_mismatch'|'not_in_file', note)`.
- `import_csv(channel, file, column_map: dict, user) -> SettlementBatch` — `column_map` keys `external_id, gross, commission, delivery_fee, net` → CSV header names; `.xlsx` read with openpyxl as the project already does. Exports (if any) through `core/export_safety.py`.
- `match(batch) -> dict` — per line: order found and `abs(order.platform_total − gross) ≤ 0.50` → `matched`; found but differs → `amount_mismatch`; not found → `unmatched`; plus a synthetic `not_in_file` line for each delivered order of the channel in the period with no file line. Returns counts. Never edits orders; audit `marketplace_settlement_matched`.
- API: `POST settlements/` (multipart, edit), `GET settlements/`, `GET settlements/<id>/?status=`.

- [ ] **Step 1: Failing tests** `test_unmatched_and_mismatch_become_exceptions`; `test_matched_within_half_pound`; `test_delivered_order_missing_from_file_flagged`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(marketplace): settlement file import and order matching`.

---

### Task 8: Screen `/marketplace`, nav, help, registries

**Files:** Create `frontend/src/pages/MarketplacePage.jsx` + `frontend/src/pages/marketplace/{OrdersTab,ManualIntakeTab,ListingsTab,ChannelsTab,SettlementTab}.jsx`, `apps/help/content/marketplace.py`; Modify `frontend/src/App.jsx`, `frontend/src/components/navGroups.js`, `frontend/src/api/client.js`, `apps/auth me` flag (pattern: `usage_print.access.can_open`), `apps/tests/new_value_registry.py`, `docs/architecture/11_ERP_INDEX.md`, doc 38 status.

**Interfaces:** Tabs (call `useHelpTab(tab)`): `orders` «📦 الطلبات» (list → detail drawer with lines + problems + events + accept/reject/status buttons + link to the POS draft), `manual` «✍️ إدخال طلب» (channel, branch, platform order no., item search via the unified item box, qty, payment mode; keyboard-first, no modal), `listings` «🏷️ الأصناف المعروضة» (add items, approve/unapprove, problem + qty per branch, `useGridKeyboard`), `channels` «🔌 المنصات والفروع» (channel settings, SOFTECH account code, price rule, stores per branch, push-stock button showing «تجريبي — لا يُرسل» when the switch is off, push log), `settlement` «💰 التسويات» (upload, column map, matched/exception counts, exception grid).
- Help entry `key 'marketplace.main'`, `routes ['/marketplace']`, Arabic + English, one tab body per tab, `updated '2026-11-17'`; say plainly: nothing is sent to any platform while the switch is off, orders become drafts on the platform's SOFTECH account and the cashier settles them, Rx items are never listed unless a supervisor approves them.

- [ ] **Step 1:** `python manage.py test apps.tests.test_help --keepdb` after adding the route → FAIL until the help entry exists; add it → PASS.
- [ ] **Step 2:** Build the page; `cd frontend && npm run lint && npm run build` → no errors.
- [ ] **Step 3:** Preview with `MARKETPLACE_ENABLED=True` on a non-8000 port: create a `manual_test` channel + store, approve one OTC listing, enter a manual order, accept it, confirm the POS draft appears in `/pos` drafts; screenshot.
- [ ] **Step 4:** Full backend run `python manage.py test apps.tests --keepdb` (serial) → no new failures vs main.
- [ ] **Step 5: Commit** `feat(marketplace): /marketplace screen, help, registries`; push branch; open PR (do not merge without the owner).

---

## Handoff notes (not in M1)

- **Before any marketplace draft is pushed to a cashier:** rollback-probe a contract-channel sale on a platform personcode (no patient data) on a test branch and diff against a native credit sale — stop-and-ask item (CLAUDE.md: payment / checkout completion).
- Own-rider delivery link (`DeliveryOrder` source `marketplace`) and rider cash booked as a receipt against the platform account — M3 with finance.
- Real adapters (Talabat Q-Commerce API first) — M2, after the owner signs with a platform.
