# Supplier Portal RPA — Stage 1 (Pharma Overseas ordering, dry run first) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Buyers turn a «الاحتياج» pivot, an ISR or an uploaded sheet into a buy list. They pick a
supplier per item. The lines for Pharma Overseas become baskets of 10, and a robot on the buyer's own
PC fills each basket on `shop.pharmaemarket.com`. Along the way it captures supplier codes and stock,
then stops for a person to press Submit. The order number it reads back is recorded through
`commit_order`. Shortages return to the buyer as «الباقي».

**Architecture:**
- **Server.** New models and services live in `apps/rpa/portal/`, inside part 1's `apps/rpa` app,
  sharing its module, devices, agent auth and screenshots.
- **Agent.** A Playwright driver (`rpa_agent/portal_web/`) inside part 1's tray agent runs a step plan
  that the server builds.
- **Records.** Results go into existing records: `supply.AvailabilityBatch` (source `portal`),
  `invoices.VendorItemMapping` via `confirm_line`, and `supply.SupplyDecision` via `commit_order`.

**Tech Stack:**
- Django 4 / DRF and PostgreSQL;
- React + Vite (Tailwind, existing hooks);
- Python 3.12 agent with Playwright (Chromium, persistent context).

**Spec:** `docs/superpowers/specs/2026-11-16-supplier-site-rpa-design.md` (approved by the owner,
2026-11-16). Part 1: `docs/superpowers/specs/2026-11-16-softech-screen-rpa-design.md` and
`docs/superpowers/plans/2026-11-16-softech-rpa-stage1.md` on `claude/softech-rpa`.

## Before you start (branching and the part-1 gate)

- Branch `claude/supplier-portal-rpa` from `claude/softech-rpa`. Today that branch has part 1's Task 1
  (the `rpa` module, permissions and switch) and Task 11 (`rpa_agent/`).
- **Tasks 1–6 need only that.**
- **Tasks 7–9 need part 1's Task 2** (`RpaDevice`, `RpaScreenshot`) **and Task 8**
  (`RpaDeviceAuthentication`, `issue_device`). Before Task 7, run
  `git log claude/softech-rpa --oneline`. If both are there, merge `claude/softech-rpa` into this
  branch. If they are not there yet, stop and say so: do **not** create those models here.
- Re-check migration numbers (`apps/rpa/migrations`, `apps/supply/migrations`, `apps/audit/migrations`)
  after every merge.
- Test command: `venv/Scripts/python.exe manage.py test <labels> --noinput`. Use a unique
  `TEST_DB_NAME` per session, and run security sweeps serially, never with `--parallel`.

## Global Constraints

- Switch `RPA_SUPPLIER_PORTAL_ENABLED` defaults to **False**.
  - It is listed in `config/writers.py` `WRITER_FLAGS` with protects `'روبوت مواقع الموردين (طلبيات ومرتجع صلاحية)'`.
  - The agent claim endpoint serves baskets only when `writer_allowed('RPA_SUPPLIER_PORTAL_ENABLED')`.
- `SupplierPortal.enabled` and `.live` both default to False. While `live` is False, a basket can only
  end `dry_run_ok`. The robot removes the lines it added and never reaches the Submit handover.
- **The robot never presses Submit Order, Submit Return, the Recurring-order radio or Sign Out, and
  never types into a password field.** This is enforced in the driver by a deny-list, whatever the
  server plan says.
- No password, cookie or token is ever stored or logged. `PortalAccount` has no secret field.
- Quantities are **whole packs**. A fractional need is rounded **up** (`math.ceil`), and the buyer may
  edit it.
- Basket size defaults to **10** (`SupplierPortal.basket_size`). Baskets follow the buy-list order.
- Flags are shown, never acted on:
  - `short_expiry` when the supplier's expiry is inside `short_expiry_months` (**12**);
  - `price_jump` when the price is ≥ `price_jump_pct` (**10**) % above our last purchase cost.
- The `commit_order` idempotency key is exactly `f'portal-basket-{basket.pk}'`.
- `portal_ref` is unique per portal (a conditional `UniqueConstraint` where `portal_ref != ''`).
- Pharma Overseas SKU canonical form: digits with the leading zeros stripped (`'000000000000052872'` →
  `'52872'`). Keep the padded form in `PortalLine.supplier_key_padded` for typing.
- Portal jobs are **company level**: they are ordered for HQ, and `branch_id` passed to `commit_order`
  is the HQ branch (`Branch.KIND_HQ`).
- Approval: a person holding `rpa.create` may approve their **own** portal job. When
  `SystemSetting('portal_four_eyes_above')` is set and the job's estimated value exceeds it, the
  approval needs a **different** person holding `rpa.approve`.
- Screen route `/rpa/portals`, Arabic title «مواقع الموردين». Help module key `rpa_portals`, Arabic +
  English, `updated: '2026-11-16'`.
- Nothing in `apps/rpa/portal/` imports `config.sybase` or writes SOFTECH.

## Review Focus

1. **The cart already holds items** from a manual session, or from a previous crashed run of this
   basket. Expect: the robot reports `cart_not_empty`, touches nothing, and the basket goes to
   `needs_person`. Test in Task 9 (driver, against a fixture page) and Task 7 (server outcome).
2. **The agent dies after the handover**, while the person may already have pressed Submit. Expect:
   when the lease expires, the basket goes to `needs_person` (never back to `ready`). A retry is only
   allowed after a person links an order from Order History or confirms that none was placed. Test in
   Task 7.
3. **The order number is reported twice** (an agent retry), or for a basket already `recorded`.
   Expect: one `SupplyDecision` set (`commit_order` replays) and the same `portal_ref`. A *different*
   number for a recorded basket → 409 and needs_person. Test in Task 8.
4. **The person edits the cart between handover and Submit.** Expect: the Order History lines are
   recorded, not the handed-over ones. The differences are listed on the basket and audited. Test in
   Task 8.
5. **"No Enough material Stock" for every quantity down to 1, or a stock message the recipe doesn't
   know.** Expect: the line is `out` in the first case. An unknown banner stops the basket
   (`unknown_message`, screenshot, needs_person); it is never treated as success. Test in Task 9.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/rpa/portal/__init__.py` | package |
| `apps/rpa/portal/models.py` (imported by `apps/rpa/models.py`) | BuyList, BuyListLine, SupplierPortal, PortalAccount, PortalJob, PortalBasket, PortalLine, PortalRun |
| `apps/rpa/portal/buylist.py` | Build a buy list from a pivot / ISR / upload; supplier ranking; pick; remainders |
| `apps/rpa/portal/jobs.py` | Portal job creation from buy-list lines, approval, basket builder |
| `apps/rpa/portal/skus.py` | SKU normalising, known-key lookup, discovery batches and confirmation |
| `apps/rpa/portal/plans.py` | Server-built step plans for the agent (discovery, fill) |
| `apps/rpa/portal/queue.py` | claim, heartbeat, report, lease expiry, resolve |
| `apps/rpa/portal/recording.py` | record_order: Order History lines → commit_order + AvailabilityBatch + remainders |
| `apps/rpa/portal/serializers.py`, `views.py`, `agent_views.py`, `urls.py` | Staff API (`/api/rpa/portal/…`) + agent API (`/api/rpa/agent/portal/…`) |
| `apps/help/content/rpa_portals.py` | In-app help |
| `frontend/src/pages/SupplierPortalsPage.jsx`, `frontend/src/pages/rpa/portals/*.jsx` | `/rpa/portals` |
| `rpa_agent/portal_web/recipe_pharma_overseas.py` | Selectors and known messages, as data |
| `rpa_agent/portal_web/driver.py` | Playwright driver + deny-list |
| `rpa_agent/portal_web/runner.py` | Executes a plan, reports steps |
| `rpa_agent/portal_web/tests/fixtures/*.html` | Static pages that mimic the site for driver tests |
| `apps/tests/test_rpa_portal_*.py` | Backend tests |

---

### Task 1: Wiring (switch, audit actions, supply source, scope text)

**Files:**
- Modify:
  - `config/settings.py`: add `RPA_SUPPLIER_PORTAL_ENABLED = config('RPA_SUPPLIER_PORTAL_ENABLED', default=False, cast=bool)` next to `RPA_SOFTECH_ENTRY_ENABLED`.
  - `config/writers.py`: add the flag to `WRITER_FLAGS`.
  - `.env.example`: add the flag.
  - `apps/audit/models.py` `ACTION_CHOICES`: `rpa_portal_buylist_created`, `rpa_portal_job_created`, `rpa_portal_job_approved`, `rpa_portal_job_cancelled`, `rpa_portal_basket_claimed`, `rpa_portal_basket_filled`, `rpa_portal_submit_seen`, `rpa_portal_basket_recorded`, `rpa_portal_needs_person`, `rpa_portal_resolved`, `rpa_portal_code_learnt`, `rpa_portal_account_changed`.
  - `apps/supply/models.py` `AvailabilityBatch`: add `SOURCE_PORTAL = 'portal'` with label `'روبوت موقع المورد'`. Widen `source` `max_length` only if needed (it is 12, and `'portal'` fits).
  - `apps/tests/security/permission_matrix.py` `BRANCH_SCOPE['rpa']`: append `'; portal jobs (/rpa/portals) are company-level — ordered for HQ, seen by rpa.view holders'`.
- Create migrations for audit and supply (choices only).
- Test: `apps/tests/test_rpa_portal_wiring.py`

- [ ] **Step 1: Write the failing tests**

```python
class PortalWiringTests(TestCase):
    def test_flag_off_and_registered(self):
        from config.writers import WRITER_FLAGS, writer_allowed
        self.assertIn('RPA_SUPPLIER_PORTAL_ENABLED', WRITER_FLAGS)
        self.assertFalse(settings.RPA_SUPPLIER_PORTAL_ENABLED)
        self.assertFalse(writer_allowed('RPA_SUPPLIER_PORTAL_ENABLED'))

    def test_portal_source_choice(self):
        from apps.supply.models import AvailabilityBatch
        self.assertIn('portal', dict(AvailabilityBatch.SOURCE_CHOICES))

    def test_audit_actions(self):
        from apps.audit.models import AuditLog
        acts = dict(AuditLog._meta.get_field('action').choices)
        for a in ('rpa_portal_basket_recorded', 'rpa_portal_needs_person', 'rpa_portal_code_learnt'):
            self.assertIn(a, acts)
```

- [ ] **Step 2:** Run `manage.py test apps.tests.test_rpa_portal_wiring`. Expected: FAIL.
- [ ] **Step 3:** Make the changes. Run `makemigrations audit supply`. Regenerate the matrix: `manage.py shell -c "from apps.tests.security.permission_matrix import write; write()"`.
- [ ] **Step 4:** Run `test apps.tests.test_rpa_portal_wiring apps.tests.security.test_permission_matrix`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-portal): switch (off), audit actions, portal availability source`.

---

### Task 2: Models

**Files:**
- Create: `apps/rpa/portal/__init__.py`, `apps/rpa/portal/models.py`.
- Modify: `apps/rpa/models.py`. Add `from .portal.models import *  # noqa: F401,F403 — portal models live in a sub-module` (the reason is written on the line, as CLAUDE.md asks). If part 1 has not created `apps/rpa/models.py` yet, create it with only this import.
- Create: `apps/rpa/migrations/00NN_portal.py`, including a RunPython seed.
- Modify: `apps/rpa/admin.py` (read-only admin for the portal models).
- Test: `apps/tests/test_rpa_portal_models.py`

**Interfaces (Produces):**
- `SupplierPortal`
  - Fields:
    - `key` unique, choices `pharma_overseas` / `ibn_sina`;
    - `supplier_code` ('565' / '260');
    - `driver` `web` / `android`;
    - `enabled` False, `live` False;
    - `basket_size` PositiveSmallInteger 10;
    - `short_expiry_months` 12;
    - `price_jump_pct` Decimal 10.
  - The seed creates both rows.
- `PortalAccount`
  - Fields: `portal` FK, `label`, `paper_branch` FK Branch null, `identity_text`, `active` True,
    `last_credit` JSON (`{"consumption", "credit", "limit", "at"}`).
  - No secret field.
- `BuyList`
  - Fields:
    - `source_kind` `pivot` / `isr` / `upload`;
    - `source_ref` str (snapshot id, IsrPush id or file sha256);
    - `status` `open` / `closed`;
    - `created_by` FK StaffProfile, `created_at`.
- `BuyListLine`
  - Fields:
    - `buylist` FK (`related_name='lines'`), `seq`;
    - `item` FK catalog.Item;
    - `needed_qty` PositiveInteger, `remaining_qty` PositiveInteger;
    - `chosen_supplier` str (blank);
    - `tried` JSON (list of `{"supplier", "accepted", "at", "basket"}`);
    - `source_key` str (e.g. `'pivot:41:123456'`);
    - `reason` str (an over-need reason, blank by default).
  - Constraint: `UniqueConstraint(source_key, condition=Q(open_guard=True))`, using a boolean
    `open_guard` (True while the buy list is open) so that one source line sits in at most one open
    buy list.
- `PortalJob`
  - Fields:
    - `portal` FK, `account` FK PortalAccount, `buylist` FK;
    - `kind` `order` (Stage 1 only);
    - `status` `draft` / `approved` / `cancelled` / `done`;
    - `dry_run` True;
    - `estimated_value` Decimal null;
    - `created_by`, `approved_by` (FK StaffProfile null), `approved_at`.
- `PortalBasket`
  - Fields:
    - `job` FK (`related_name='baskets'`), `seq`;
    - `status`, choices `pending` / `ready` / `in_progress` / `dry_run_ok` / `awaiting_submit` /
      `submitted` / `recorded` / `needs_person` / `cancelled`;
    - `claimed_by_id` (nullable integer for now; Task 7 turns it into FK RpaDevice), `claimed_at`,
      `lease_until`;
    - `filled_at`, `submitted_seen_at`;
    - `portal_ref` str blank;
    - `order_ref` str blank;
    - `credit_seen` JSON;
    - `needs_person_reason` str;
    - `diff` JSON (handed-over vs recorded).
  - Constraint: `UniqueConstraint(fields=['job', 'seq'])`.
- `PortalLine`
  - Fields:
    - `basket` FK (`related_name='lines'`), `buyline` FK BuyListLine, `item` FK;
    - `wanted_qty` PositiveInteger, `accepted_qty` PositiveInteger null;
    - `status` `pending` / `ok` / `short` / `out` / `not_found` / `removed`;
    - `supplier_key`, `supplier_key_padded`, `supplier_name_seen`;
    - `price`, `discount_pct`, `bonus_text`, `supplier_expiry` (date null);
    - `flags` JSON list;
    - `message` str;
    - `availability_line` FK supply.AvailabilityLine null.
- `PortalRun`
  - Fields:
    - `basket` FK null + `discovery_job` FK PortalJob null (a discovery run belongs to a job, not a
      basket);
    - `kind` `discovery` / `fill` / `history`;
    - `device_id` (nullable integer until Task 7);
    - `mode` `dry_run` / `live`;
    - `started_at`, `finished_at`;
    - `outcome` str;
    - `steps` JSON.
- The `portal_ref` uniqueness rule lives on a denormalised `PortalBasket.portal_key` CharField
  (`'<portal.key>:<portal_ref>'`, blank when there is no ref) with
  `UniqueConstraint(fields=['portal_key'], condition=~Q(portal_key=''))`.

- [ ] **Step 1: Write the failing tests**
  - `test_portals_seeded_off`: two rows; `enabled` and `live` False; `basket_size == 10`.
  - `test_account_has_no_secret_field`: no field name on `PortalAccount` contains `pass`, `secret`, `token` or `cookie`.
  - `test_portal_ref_unique_per_portal`: two baskets with the same `portal_key='pharma_overseas:2104322530'` → `IntegrityError`. Two blank ones are fine.
  - `test_source_line_in_one_open_buylist`: the same `source_key` in two open buy lists → `IntegrityError`. Once the first list is closed (`open_guard=False`), it is allowed.
- [ ] **Step 2:** Run `manage.py test apps.tests.test_rpa_portal_models`. Expected: FAIL.
- [ ] **Step 3:** Write the models, run `makemigrations rpa`, and add the seed RunPython.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-portal): models`.

---

### Task 3: Buy lists (sources, ranking, pick, remainder)

**Files:**
- Create: `apps/rpa/portal/buylist.py`
- Test: `apps/tests/test_rpa_portal_buylist.py`

**Interfaces:**
- Consumes:
  - `purchasing.PivotSheetSnapshot.lines` (`[{item_code, total_gap, supplier_code}]`);
  - `purchasing.IsrPush.lines_snapshot` (`itemcode`, `itemqty`);
  - `apps.supply.comparison.build_board(item_ids=…)`.
- Produces:
  - `create_from_pivot(snapshot, *, staff, supplier_codes=None) -> BuyList`;
  - `create_from_isr(push, *, staff) -> BuyList`;
  - `create_from_rows(rows: list[dict], *, staff, file_sha256) -> BuyList` (rows `{item_code, qty}`);
  - `rank_suppliers(item_ids: list[int]) -> dict[int, list[str]]`;
  - `pick(line: BuyListLine, supplier_code: str, *, staff) -> BuyListLine`;
  - `apply_result(line: BuyListLine, *, supplier_code, accepted: int, basket_id) -> BuyListLine`
    (appends to `tried`, lowers `remaining_qty`, clears `chosen_supplier` when `remaining_qty > 0`);
  - `remainders(*, staff=None) -> QuerySet[BuyListLine]` (open lists, `remaining_qty > 0`, has tried).
  - `send_other(buylist, supplier_code, *, staff, lang='ar') -> dict`: for the open lines whose
    `chosen_supplier` is a supplier **without** a portal.
    - It calls `commit_order(lines=[{item_id, qty: remaining_qty, branch_id: HQ, reason}],
      idempotency_key=f'buylist-{buylist.pk}-{supplier_code}-{n}', supplier=VendorProfile(code))`, where
      `n` counts previous sends of this list to this supplier.
    - It then calls `apply_result(accepted=qty)` per line and returns `commit_order`'s `text`, for
      WhatsApp. Excel goes through the existing `export_order_excel`.
    - Same key → replay.

**Rules:**
- **Quantities.** `needed_qty = ceil(gap)`. Lines with `needed_qty <= 0` are skipped. An unknown item
  code becomes a line error returned to the caller (`{'errors': [...]}` on the list's create result),
  never a guess.
- **Default supplier.** `chosen_supplier` defaults to `rank_suppliers()[item][0]`. When the board has
  nothing for the item, use the first code in `SystemSetting('portal_supplier_order', ['565', '30',
  '260'])` that `ItemSupplierLink` says carries the item. If none does, fall back to the pivot line's
  `supplier_code`.
- **Duplicates.** A `source_key` already in an open list raises `BuyListError('السطر موجود في قائمة شراء
  مفتوحة')`, which names the other list's id.

- [ ] **Step 1: Write the failing tests**
  - `test_pivot_rounds_up_and_skips_zero`: gaps `[2.2, 0, -1, 5]` → needed `[3, 5]`.
  - `test_unknown_item_is_error_not_line`.
  - `test_default_supplier_from_board_then_setting`: mock `build_board` to rank `['30', '565']` → `'30'`. With an empty board and an `ItemSupplierLink` for 565 only → `'565'`.
  - `test_same_pivot_line_twice_refused`.
  - `test_apply_result_short_makes_remainder`: needed 10, accepted 6 → `remaining_qty == 4`, `chosen_supplier == ''`, and `tried[-1] == {'supplier': '565', 'accepted': 6, …}`. The line appears in `remainders()`.
  - `test_apply_result_full_closes_line`: accepted 10 → `remaining_qty == 0`, and the line is not in `remainders()`.
  - `test_send_other_records_and_replays`: send to supplier '30' → `SupplyDecision`s exist with `order_ref` `buylist-<pk>-30-1`, and the lines' `remaining_qty == 0`. A second call with the same key creates no new decisions.
  - `test_send_other_refuses_portal_supplier`: '565' → `BuyListError`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Audit `rpa_portal_buylist_created` on create.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-portal): buy lists from pivot / ISR / upload`.

---

### Task 4: Portal jobs, approval, baskets

**Files:**
- Create: `apps/rpa/portal/jobs.py`
- Test: `apps/tests/test_rpa_portal_jobs.py`

**Interfaces:**
- Consumes: Task 3; `apps.supply.execution.preview_order(lines)`.
- Produces:
  - `create_job(buylist, *, portal, account, staff) -> PortalJob`. It takes the open lines whose
    `chosen_supplier == portal.supplier_code` and `remaining_qty > 0`, and refuses if there are none.
  - `approve_job(job, *, staff, reasons: dict[int, str] | None = None) -> PortalJob`.
  - `build_baskets(job) -> list[PortalBasket]`.
  - `cancel_job(job, *, staff, reason) -> PortalJob` (only while no basket is past `ready`).

**Rules:**
- **The need check.** `approve_job` runs `preview_order([{item_id, qty, branch_id: HQ}])`. Every row
  with `exceeds_need` needs a non-empty `reasons[buyline_id]`. Without one it raises
  `JobError('الكمية أكبر من الاحتياج الحالي — اذكر السبب')`, which lists the items. Reasons are saved
  on `BuyListLine.reason`.
- **Who may approve.** The approver must hold `rpa.create`. When `portal_four_eyes_above` is set and
  `estimated_value` (the sum of `preview_order` line values, None-safe) is above it, the approver must
  also hold `rpa.approve` and must not be `created_by`.
- **Baskets.** `build_baskets` cuts the job's lines into baskets of `portal.basket_size` in `seq`
  order. A line whose item has a known key (Task 5 `known_key`) starts `pending` in a basket marked
  `ready` once **all** its lines have keys. A basket with any keyless line stays `pending` until
  discovery confirms it.
- **Freezing.** Approval freezes the job: a change to a `BuyListLine` qty or supplier after approval
  raises.

- [ ] **Step 1: Write the failing tests**
  - `test_job_takes_only_this_portals_lines`.
  - `test_over_need_without_reason_blocks`. With a reason it approves, and the reason is stored.
  - `test_self_approval_allowed_below_threshold`.
  - `test_four_eyes_above_threshold`: the same person → `PermissionDenied`; a different holder of `rpa.approve` → ok.
  - `test_baskets_of_ten_in_order`: 23 lines → baskets with 10, 10 and 3 lines, `seq` 1..3.
  - `test_basket_ready_only_when_all_keys_known`.
  - `test_cancel_refused_after_claim`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Audit `rpa_portal_job_created` / `_approved` / `_cancelled`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-portal): portal jobs, approval rules, baskets of 10`.

---

### Task 5: Supplier keys and code discovery

**Files:**
- Create: `apps/rpa/portal/skus.py`
- Test: `apps/tests/test_rpa_portal_skus.py`

**Interfaces:**
- Consumes:
  - `apps.supply.availability.resolve_vendor_codes(vendor, codes)`;
  - `confirm_line(line, item, *, staff, vendor_code)`;
  - `invoices.VendorProfile` (`softech_personcode`);
  - `catalog.ItemSupplierLink`.
- Produces:
  - `canonical_sku(raw: str) -> str` (strip spaces and leading zeros; `''` for non-digits);
  - `padded_sku(canonical: str) -> str` (zero-pad to 18);
  - `vendor_for(portal) -> VendorProfile` (raises `PortalSetupError` when 565 has no VendorProfile);
  - `known_key(portal, item) -> str` (canonical SKU from `VendorItemMapping` for this vendor, else the
    `ItemSupplierLink.supp_item_code` canonical form, else `''`);
  - `record_discovery(job, results: list[dict], *, run) -> AvailabilityBatch`. Results are
    `[{buyline_id, candidates: [{name, sku, price, stock_mark}]}]`. It creates one `AvailabilityBatch`
    (source `portal`, supplier = vendor) with one `AvailabilityLine` per candidate:
    - `raw_text` = the name;
    - `supplier_item_code` = canonical SKU;
    - `price`;
    - `signals = ['out_of_stock']` when marked;
    - `match_reason = {'buyline_id': …}`.
  - `confirm_discovery(availability_line, *, staff) -> None`. It calls `confirm_line(line, buyline.item,
    staff=staff, vendor_code=sku)`, writes the key on the job's `PortalLine`s for that item, promotes
    baskets that now have all keys to `ready`, and audits `rpa_portal_code_learnt`.
  - `reject_discovery(buyline, *, staff) -> None`. This is "none of these": the line becomes
    `not_found` and returns to the buyer (via `apply_result(accepted=0)`).

- [ ] **Step 1: Write the failing tests**
  - `test_canonical_sku`: `'000000000000052872'` → `'52872'`; `' 37216 '` → `'37216'`; `'ABC'` → `''`.
  - `test_known_key_prefers_mapping_over_mirror`.
  - `test_discovery_creates_portal_batch`: source `'portal'`, the supplier is VendorProfile 565, one line per candidate.
  - `test_confirm_learns_mapping_and_readies_basket`: afterwards `VendorItemMapping(vendor=565, vendor_item_code='52872', item=…)` exists and the basket is `ready`.
  - `test_confirm_conflict_kept_for_person`: the code is already confirmed for another item → `match_reason['vendor_code_conflict']` is set and the basket is **not** ready.
  - `test_none_of_these_returns_line_to_buyer`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-portal): supplier keys and code discovery`.

---

### Task 6: Step plans

**Files:**
- Create: `apps/rpa/portal/plans.py`
- Test: `apps/tests/test_rpa_portal_plans.py`

**Interfaces (Produces):**
- `discovery_plan(job) -> dict`:
  `{"kind": "discovery", "portal": "pharma_overseas", "account": {"identity_text": …}, "searches":
  [{"buyline_id", "term"}]}`. `term` is the item's English name with pack words trimmed (the builder
  picks the trim rule), and there is at most one search per keyless item.
- `fill_plan(basket) -> dict`:

```json
{"kind": "fill", "basket_id": 7, "portal": "pharma_overseas", "mode": "dry_run",
 "account": {"identity_text": "…"},
 "lines": [{"line_id": 31, "sku_padded": "000000000000052872", "sku": "52872", "qty": 10}],
 "expect_lines": 10, "max_stepdown_tries": 6}
```

  `mode` is `"live"` only when `portal.live and not job.dry_run`, and `"dry_run"` otherwise.
- `history_plan(basket, *, since) -> dict`: `{"kind": "history", "basket_id", "since": iso,
  "order_ref": portal_ref or ""}`. `since` is required (PlanError without it). It is the start of the
  earliest live fill run that may have ordered, minus the safety margin (ruling R9, Task 7).
- Plans never contain a password, a URL taken from the database, or any instruction to press Submit.

- [ ] **Step 1: Write the failing tests**
  - `test_fill_plan_dry_run_unless_portal_live_and_job_live`.
  - `test_fill_plan_lines_in_seq_with_padded_sku`.
  - `test_plan_has_no_submit_or_secret`: the serialised plan doesn't contain `submit`, `password` or `cookie` (case-insensitive).
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-portal): server-built step plans`.

---

### Task 7: Agent queue (claim, heartbeat, report, lease, resolve)

**Gate:** merge `claude/softech-rpa` with part 1's Tasks 2 and 8 first (see "Before you start").

**Files:**
- Modify:
  - `apps/rpa/portal/models.py`: turn `claimed_by_id` / `device_id` into FKs to `rpa.RpaDevice` (a new migration).
  - `RpaScreenshot`: add `portal_run` FK null and `CheckConstraint(Q(run__isnull=False) ^ Q(portal_run__isnull=False))`. Express it as two Q's combined with `|`/`&` if `^` isn't supported by the Django version.
- Create: `apps/rpa/portal/queue.py`, `apps/rpa/portal/agent_views.py`, and routes in `apps/rpa/portal/urls.py` included from `apps/rpa/urls.py` as `portal/` and `agent/portal/`.
- Test: `apps/tests/test_rpa_portal_queue.py`

**Interfaces:**
- Consumes: `RpaDeviceAuthentication`, `RpaDevice.staff`; Task 6 plans.
- Produces:
  - `claim_next(device) -> dict | None`:
    - returns `None` unless `writer_allowed('RPA_SUPPLIER_PORTAL_ENABLED')` and `portal.enabled`;
    - otherwise it takes a `pg_advisory_xact_lock(7302001)` and picks the oldest work for jobs whose
      `created_by == device.staff`: first a job with `pending` baskets that needs discovery, then a
      `ready` basket;
    - it sets `in_progress`, `claimed_by`, `claimed_at`, and `lease_until = now + 10 min`;
    - it creates a `PortalRun` and returns `{"run_id", "plan"}`.
  - `heartbeat(run, device) -> None`: extends the lease by 10 minutes.
  - `report(run, device, payload) -> PortalBasket | PortalJob`. Payload:
    `{"outcome", "steps", "lines": [...], "credit": {...}, "discovery": [...], "order_ref"?}`.
  - `expire_leases(now=None) -> int`: an `in_progress` or `awaiting_submit` basket past its lease →
    `needs_person` (`lease_expired`). Called by the scheduler every 5 minutes, using
    `SCHEDULER_JOB_GUARDS`.
  - `resolve(basket, *, staff, action: 'retry'|'link_order'|'cancel', order_ref: str = '') -> PortalBasket`.
- Agent endpoints (`authentication_classes=[RpaDeviceAuthentication]`, `matrix_permission('rpa', post=('create',))`):
  - `POST /api/rpa/agent/portal/claim/`
  - `POST /api/rpa/agent/portal/runs/<id>/heartbeat/`
  - `POST /api/rpa/agent/portal/runs/<id>/report/`
  - `POST /api/rpa/agent/portal/runs/<id>/screenshot/`

**Outcomes → status:**

| outcome | basket becomes |
|---|---|
| `dry_run_ok` | `dry_run_ok`. The lines' answers are saved, and Task 8's `record_check` runs. |
| `handover` (live) | `awaiting_submit` (`filled_at` set). The lease keeps running while the person decides. |
| `submit_seen` + `order_ref` | `submitted`, then Task 8's `record_order` |
| `cart_not_empty`, `wrong_account`, `cart_mismatch`, `unknown_message`, `login_required_timeout`, `stopped_by_operator`, `timeout`, `error` | `needs_person` with that reason |

**Driver contract (ruling, Task 7 review):** the driver reports `cart_not_empty` and `wrong_account`
**only** from run_plan step 1, before any line is added. These two are the only outcomes treated as
"nothing touched". Any identity mismatch found later (for example on the review page) is reported as
`wrong_account_late`, which counts as "may have ordered". The queue also checks the reported steps and
treats a "pre-cart" outcome that lists an added line as "may have ordered".

- **A report from the wrong device**, or for a run that isn't open → 409.
- **Credit.** Every report carrying `credit` saves it on `PortalAccount.last_credit` (with `at`). Every
  report carrying an account identity that differs from `identity_text` is `wrong_account`.
- **`retry`** is allowed only from `needs_person`, and only when the last reason is **not** one that
  could mean an order was placed. For `lease_expired` after `awaiting_submit`, `retry` requires a
  prior history run that found no matching order, or an explicit `confirm_none=True` from a holder of
  `rpa.edit`, which is audited.
- **`link_order`** sets `portal_ref` and goes through `record_order`.

- [ ] **Step 1: Write the failing tests**
  - `test_claim_off_when_switch_off`.
  - `test_claim_only_own_jobs`.
  - `test_two_claims_never_same_basket`: two threads, using `TransactionTestCase`.
  - `test_lease_expiry_goes_needs_person_not_ready`.
  - `test_retry_blocked_after_awaiting_submit_until_history_or_confirm`.
  - `test_cart_not_empty_outcome_needs_person`.
  - `test_wrong_device_report_409`.
  - `test_screenshot_attaches_to_portal_run_only`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Audit `rpa_portal_basket_claimed` / `_filled` / `_needs_person` / `_resolved` / `_submit_seen`.
- [ ] **Step 4:** Run `manage.py test apps.tests.test_rpa_portal_queue apps.tests.security --noinput`, serially. Expected: PASS. The canary planter must build the new models (they must not be in `skipped`).
- [ ] **Step 5:** Commit `feat(rpa-portal): agent queue, leases, needs-a-person`.

---

### Task 8: Recording (orders, availability, remainders)

**Files:**
- Create: `apps/rpa/portal/recording.py`
- Test: `apps/tests/test_rpa_portal_recording.py`

**Interfaces:**
- Consumes:
  - `commit_order(lines, *, idempotency_key, supplier, supplier_name, staff)`;
  - Task 3 `apply_result`;
  - Task 5 `vendor_for`;
  - `apps.supply.comparison.purchase_history` (last cost, for `price_jump`).
- Produces:
  - `record_check(basket, lines_payload) -> AvailabilityBatch`. It saves each `PortalLine`'s answer
    (`accepted_qty`, `status`, price, discount, bonus, `supplier_expiry`, message), computes `flags`,
    and writes one `AvailabilityBatch` (source `portal`) with one line per checked item:
    - `supplier_qty` = accepted;
    - `signals = ['short']` / `['out_of_stock']`;
    - `expiry` as text;
    - `supplier_item_code`.
  - `record_order(basket, *, order_ref: str, history_lines: list[dict], staff) -> PortalBasket`.
    `history_lines` are `[{sku, qty}]` from Order History.

**Rules for `record_order`:**
- One transaction, under `select_for_update` on the basket.
- **If the basket is already `recorded`:** the same `order_ref` → return it unchanged; a different
  one → `RecordError` (409) and needs_person.
- **The lines.** Map `history_lines` to `PortalLine`s by canonical SKU. The quantities recorded are the
  history quantities. Store `basket.diff = {"added": […], "removed": […], "qty_changed": […]}` against
  the handed-over `accepted_qty`. A history SKU that isn't in the basket is recorded in `diff.added`,
  **not** ordered through `commit_order`, and the basket is flagged for a person.
- **Then:**
  - call `commit_order(lines=[{item_id, qty, branch_id: HQ, reason: buyline.reason}],
    idempotency_key=f'portal-basket-{pk}', supplier=vendor, supplier_name='فارما أوفرسيز', staff=…)`;
  - set `SupplyDecision.result_refs['portal'] = {'account': account.label, 'order_ref': order_ref,
    'basket': pk}` for the returned decisions;
  - call `apply_result` per line (accepted = the history qty; 0 for removed lines);
  - set `portal_ref`, `portal_key`, `order_ref`, status `recorded`;
  - audit `rpa_portal_basket_recorded` with the diff.
- **`commit_order`'s own need check** may raise for an added or raised quantity without a reason. Catch
  `ExecutionError` → needs_person (`need_check`), and keep the `portal_ref`, because the order *was*
  placed.

- [ ] **Step 1: Write the failing tests**
  - `test_record_check_flags_short_expiry_and_price_jump`: expiry in 8 months → `short_expiry`; price 12 % above the last cost → `price_jump`; flags only, and the line status is unchanged.
  - `test_record_check_writes_portal_availability_batch`.
  - `test_record_order_uses_history_quantities_and_diff`: handed over `{A:10, B:5}`, history `{A:8}` → decisions A=8 only; `diff.qty_changed` holds A; `diff.removed` holds B; B's buy line gets its 5 back as a remainder.
  - `test_record_order_replay_same_ref_is_noop`: called twice → one set of `SupplyDecision`.
  - `test_record_order_different_ref_on_recorded_409`.
  - `test_record_order_need_check_failure_keeps_ref_and_needs_person`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests plus `apps.tests.test_supply_execution`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-portal): record orders from Order History, remainders`.

---

### Task 9: Agent driver for Pharma Overseas (Playwright)

**Files:**
- Create:
  - `rpa_agent/portal_web/__init__.py`;
  - `recipe_pharma_overseas.py`, `driver.py`, `runner.py`;
  - `tests/test_portal_driver.py`, `tests/fixtures/{quick_order,cart_not_empty,review,thank_you,order_history,login}.html`.
- Modify:
  - `rpa_agent/main.py`: route a claim whose plan `kind` is discovery / fill / history to `portal_web.runner.run_plan`. Add a menu item «فتح متصفح الموردين» that opens the persistent browser so the operator can log in.
  - `rpa_agent/client.py`: `portal_claim()`, `portal_heartbeat(run_id)`, `portal_report(run_id, payload)`, `portal_screenshot(run_id, step, png)`.
  - `rpa_agent/requirements.txt`: `playwright==1.47.0`.
  - `rpa_agent/README.md`: install the browser once (`python -m playwright install chromium`), the profile path, login, and a dry-run checklist.

**Interfaces:**
- Recipe constants (data only):
  - `BASE_URL = 'https://shop.pharmaemarket.com/pharma/en/EGP/'`;
  - paths `my-account/quick-order`, `my-account/place-order`, the order history path (confirmed by the
    builder);
  - `MESSAGES`: a dict from regex to meaning:

    | Message | Meaning |
    |---|---|
    | `No Enough material Stock` | `short` |
    | `No material Stock` | `out` |
    | `Out Of Stock` | `out` |
    | `already in your cart` | `merged` |
    | `Quick order list has been added to the cart` | `added` |
    | `order number\s*#\s*(\d+)` | `order_ref` |

  - `DENY = ('Submit Order', 'Submit Return', 'Recurring order', 'Sign Out')`.
- `PortalWebDriver(profile_dir)` with these methods:
  - `ensure_logged_in(timeout_s) -> bool`;
  - `account_identity() -> str`;
  - `cart_lines() -> list[dict]`;
  - `add_line(sku_padded, qty) -> str` (returns the banner text);
  - `set_qty(sku, qty) -> str`;
  - `remove_line(sku) -> None`;
  - `read_rows() -> list[dict]`;
  - `go_review() -> dict` (totals);
  - `credit() -> dict`;
  - `search(term) -> list[dict]`;
  - `wait_order_number(timeout_s) -> str | None`;
  - `order_history(since) -> list[dict]`;
  - `screenshot() -> bytes`.

  Every click goes through `_click(locator)`. It reads the element's accessible name and text and
  raises `DeniedControl` when it matches `DENY` (case-insensitive). It also raises `DeniedControl` on
  any `fill` into `input[type=password]`.
- `run_plan(plan, driver, *, stop, on_step, on_shot) -> dict` returns the report payload. The fill
  flow follows spec §6.2 step 5:
  1. Account check, then cart-empty check (non-empty → `cart_not_empty`, nothing touched).
  2. Add each line.
  3. On `short`: step down. Halve between the last refused and 0, up to `max_stepdown_tries`, never
     above `qty`, and keep the largest accepted.
  4. Read back.
  5. Cart equality check (`cart_mismatch`).
  6. `dry_run`: remove only the plan's SKUs, check the cart is empty again → outcome `dry_run_ok`.
  7. `live`: `go_review` → outcome `handover`, and the overlay shows «راجع ثم اضغط Submit Order
     بنفسك». Then `wait_order_number`. Once seen, it runs `order_history(since)` and reports
     `submit_seen` with `order_ref` and `history_lines`.
  8. An unknown banner → `unknown_message`.
  9. A login page → pause for up to 5 minutes with «سجّل الدخول ثم اضغط متابعة», then
     `login_required_timeout`.

The spec's CSV-import fast path (Import Products) is **not** in Stage 1. It is added once the
discovered codes cover most baskets.

- [ ] **Step 1: Write the failing tests.** They use Playwright on the local fixture HTML via `file://`
  pages, with a recipe override of `BASE_URL`.
  - `test_deny_list_blocks_submit`: `_click` on the Submit Order button raises `DeniedControl`.
  - `test_never_types_password`.
  - `test_cart_not_empty_touches_nothing`: the fixture cart has one row → outcome `cart_not_empty`, and the fixture's DOM is unchanged.
  - `test_stepdown_finds_largest_accepted`: the fixture accepts ≤ 7 → accepted 7, status `short`.
  - `test_stepdown_all_refused_is_out`.
  - `test_unknown_banner_stops`.
  - `test_dry_run_leaves_cart_as_found`.
  - `test_reads_order_number_from_thank_you`: `'2104322530'`.
- [ ] **Step 2:** Run `cd rpa_agent && python -m pytest portal_web/tests -q`. Expected: FAIL.
- [ ] **Step 3:** Implement the recipe, driver and runner. Use role / label / text locators only, never
  coordinates.
- [ ] **Step 4:** Run the tests. Expected: PASS. Also run part 1's agent tests (`rpa_agent/tests`). Expected: PASS.
- [ ] **Step 5:** Commit `feat(rpa-agent): Pharma Overseas web driver (deny-list, step-down, dry run)`.

---

### Task 10: Staff API, `/rpa/portals` screen, help

**Files:**
- Create:
  - `apps/rpa/portal/serializers.py`, `views.py`; routes under `/api/rpa/portal/`;
  - `apps/help/content/rpa_portals.py`;
  - `frontend/src/pages/SupplierPortalsPage.jsx`;
  - `frontend/src/pages/rpa/portals/{BuyListTab,DiscoveryTab,BasketsTab,RemaindersTab,AccountsTab}.jsx`.
- Modify:
  - the frontend router and sidebar: the purchasing group gets «مواقع الموردين» → `/rpa/portals`, shown with `rpa.view`;
  - the scheduler: the `expire_leases` job and a daily `history` check for `awaiting_submit` / `needs_person` baskets.
- Test: `apps/tests/test_rpa_portal_api.py`, and the existing `apps/tests/test_help.py` (which must pass).

**Endpoints** (each with `MatrixPermission`, module `rpa`):

| Method | Path | Action |
|---|---|---|
| GET | `buylists/` | view |
| POST | `buylists/from-pivot/` `{snapshot_id}` | create |
| POST | `buylists/from-isr/` `{push_id}` | create |
| POST | `buylists/upload/` (xlsx through `core/upload_safety`) | create |
| GET | `buylists/<id>/` (lines + ranking) | view |
| POST | `buylists/<id>/pick/` `{line_id, supplier}` | create |
| POST | `buylists/<id>/send-other/` `{supplier}` (WhatsApp text; `?format=xlsx` for Excel) | create |
| POST | `jobs/` `{buylist_id, portal, account_id}` | create |
| POST | `jobs/<id>/approve/` `{reasons}` | create (four-eyes rule inside) |
| POST | `jobs/<id>/cancel/` | create |
| GET | `jobs/<id>/` | view |
| GET | `discovery/<job_id>/` | view |
| POST | `discovery/confirm/` `{availability_line_id}` | edit |
| POST | `discovery/none/` `{buyline_id}` | edit |
| GET | `baskets/<id>/` (lines, flags, steps, screenshots, diff) | view |
| POST | `baskets/<id>/resolve/` | edit |
| GET | `remainders/` | view |
| GET/PATCH | `accounts/` | admin (`IsAdminRole` + audit `rpa_portal_account_changed`) |
| PATCH | `portals/<key>/` `{enabled, live, basket_size}` | admin, audited |

**UI:**
- Every grid is sortable (`useSortableRows` / `SortTh`).
- Discovery and remainders use `useGridKeyboard` (↑↓, Enter = confirm / pick, M = none).
- The account pick shows the last credit.
- Lines show their flags as calm badges (no popups).
- Branches show through `useBranchLabels`.
- There is a refresh button for the history check.
- Each tab calls `useHelpTab(tab)`.
- `«live»` can only be switched on from the accounts tab, by an admin.

- [ ] **Step 1: Write the failing tests**
  - `test_endpoints_require_rpa_module`: no rights → 403.
  - `test_non_admin_cannot_change_accounts_or_live`.
  - `test_pick_and_job_flow_happy_path`.
  - `test_discovery_confirm_needs_edit`.
  - `test_buyer_sees_only_own_jobs_unless_approve`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement the API, the page and the help. Help text in AR + EN covers: the buy list,
  picking a supplier, account and credit, approve, discovery, dry run vs live, «راجع ثم اضغط Submit
  بنفسك», «الباقي» and needs-a-person.
- [ ] **Step 4:** Run `manage.py test apps.tests.test_rpa_portal_api apps.tests.test_help apps.tests.security --noinput`, serially; then `cd frontend && npm run lint && npm run build`. Expected: PASS and a clean build.
- [ ] **Step 5:** Commit `feat(rpa-portal): /rpa/portals screen, API, help`.

---

### Task 11: Whole-stage check

- [ ] Run every portal test plus part 1's rpa tests, `apps.tests.test_supply_execution`, `apps.tests.test_supply_availability` and the security sweeps (serially). Expected: all PASS.
- [ ] Run the coverage floor check (`--fail-under=73`, as in CI).
- [ ] Run `npm run build`.
- [ ] Do a manual dry run with the owner on a real PC, with the switch on for that one instance only:
  - pair the device;
  - run «فتح متصفح الموردين» and have the owner log in;
  - take a 3-item buy list from a pivot, through discovery, to a dry-run fill;
  - confirm the cart is left as found and that the availability batch appears in `/supply`.
- [ ] Update `docs/superpowers/specs/2026-11-16-supplier-site-rpa-design.md` §4.1 with what the dry run
  confirmed: SKU forms, the account identity text, the Order History columns.
- [ ] Do not switch `live` on. That is the owner's step after watching dry runs.
