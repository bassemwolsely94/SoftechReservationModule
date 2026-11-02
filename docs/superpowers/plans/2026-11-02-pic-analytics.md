# PIC Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A PIC-centric customer dashboard + Excel report under العملاء, with sales, frequency, retention, calls, missed/unanswered calls and new-number leads, gated to admin, supervisor and named branch managers.

**Architecture:** A new Django app `apps/pic_analytics` holds pure definition functions (`rules.py`), a nightly-built fact table (`PicDayFact`) plus a per-PIC rollup, an `Access` resolver (copy of `apps/stock_audit/access.py`), query modules per tab, DRF function views and an openpyxl export. Calls come from `pbx.CdrCall` (PR 41). React page `PicAnalyticsPage.jsx` with tabs, built like `ReservationsAnalyticsPage.jsx`.

**Tech Stack:** Django 4.2 + DRF, PostgreSQL, APScheduler (`apps/sync/tasks.py`), openpyxl, React 18 + TanStack Query + Tailwind (no chart library).

**Spec:** `docs/architecture/33_PIC_ANALYTICS.md` (read it first; §4 definitions are the contract).

**Base branch:** build on `claude/pbx-cdr-pic-link` (PR 41, adds `pbx.CdrCall`) until PR 41 is merged, then rebase on `main`. Run tests with a unique `TEST_DB_NAME`.

## Global Constraints

- No SOFTECH writes. The only SOFTECH change is one more column read in `QUERY_CUSTOMERS` (owner-approved 2026-11-02).
- Deterministic rules only; every figure reproducible from the fact table.
- Exclude `Customer.is_account_placeholder=True`, `softech_pic` starting `ACCT-`, and `merged_into_pic != ''` from every PIC count. Sales with no PIC → one "بدون PIC" line in sales totals.
- Sale doc `doc_code='115'`, return `'30'`. Returns count on their own date, reduce net, are never a visit, never change first purchase.
- Visit = (PIC, Cairo local date). History starts 2024-08-01.
- New PIC: first purchase in period AND `softech_created_at >= period_start − 30 days`; when `softech_created_at` is null for every customer (not yet synced) use first purchase only and set `new_reliable_from = 2025-08-01` in the response.
- Reactivated: returning, previous visit ≥ 365 days before the first visit in the period.
- Frequency over the 12 months ending at the report's `to` date: A = distinct months with a visit; B = longest consecutive-month run; C = mean days between consecutive visits (≥ 2 visits), buckets `≤31 → 'm1'`, `≤62 → 'm2'`, `≤93 → 'm3'`, `≤186 → 'm4_6'`, `≤365 → 'm7_12'`, else `'y1plus'`; loyal = A ≥ `pic_loyal_months` (default 10); overdue = days since last visit > `pic_overdue_factor` (default 1.5) × cycle.
- Missed call: `CdrCall.direction='inbound'`, `status != 'answered'`, `is_transfer=False`. Unanswered: outbound, `status != 'answered'`. Returned: answered call (either direction) same `phone_key` within `pic_call_return_hours` (default 24). Call→purchase within `pic_call_purchase_days` (default 7).
- Shared numbers: count on `CdrCall.pic`; show `CdrCall.shared_pics`.
- Branch managers: amounts from their branch's invoices only; labels (new/returning/reactivated/frequency/segment) chain-wide; no cost/GP/margin anywhere in API or Excel; calls only for PICs who bought at their branch in the period; Call-center, Missed and New-numbers tabs → 403.
- Every new/changed screen gets help in `apps/help/content/customers.py` (AR + EN), `useHelpTab(tab)`, a tour; `apps/tests/test_help.py` must pass.
- Branch labels via `useBranchLabels` / `recon_labels.branch_label`, never a bare code. Arabic RTL. No modal for common actions.

## Review Focus

1. A report range that starts before 2024-08-01 or ends in the future → clamp to available data and say so in the response (`data_from`, `data_to`), never 500. → Task 6 test `test_range_clamped_to_history`.
2. A PIC whose only purchase in the period was returned → still a visit on the sale date, net may be ≤ 0, still new if new. → Task 3 test `test_returned_only_purchase_still_new`.
3. A branch manager passing `?branch=<other>` or `?branches=` in the URL or export → their own branch is forced, no error leak. → Task 5 test `test_branch_param_ignored_for_branch_manager`.
4. A phone with 5+ PICs where none ever bought → listed with `shared_pics`, not counted on any PIC, still a missed call in totals. → Task 9 test `test_unresolved_shared_number_counted_once_in_totals`.
5. An empty period (no sales, no calls) → every tab returns zeros/empty lists, the export still produces a workbook with the filters sheet. → Task 12 test `test_empty_period_exports_filters_sheet`.

---

### Task 1: Customer creation date from SOFTECH

**Files:**
- Modify: `apps/customers/models.py` (Customer), `apps/sync/sybase_queries.py:226-241` (QUERY_CUSTOMERS + its index comment), `apps/sync/tasks.py:1240-1290` (row → Customer, `update_fields`)
- Create: migration `apps/customers/migrations/00xx_customer_softech_created_at.py`
- Test: `apps/tests/test_customer_created_at_sync.py`

**Interfaces:**
- Produces: `Customer.softech_created_at = models.DateField(null=True, blank=True, db_index=True)` — SOFTECH `localcustomers.custdate`.

- [ ] **Step 1: Write the failing test** — feed `sync_customers`' row builder a row tuple with index `[19] = datetime(2019, 5, 3)` (follow the existing customer-sync test's fake-cursor pattern; find it with `grep -rln "QUERY_CUSTOMERS\|sync_customers" apps/tests`).

```python
def test_custdate_stored_as_softech_created_at(self):
    ...  # run the sync with one row whose [19] is datetime(2019, 5, 3)
    self.assertEqual(Customer.objects.get(softech_pic='P1').softech_created_at, date(2019, 5, 3))

def test_old_row_layout_without_custdate_leaves_field_null(self):
    ...  # 19-column row
    self.assertIsNone(Customer.objects.get(softech_pic='P1').softech_created_at)
```

- [ ] **Step 2: Run it, expect FAIL** (`no such field`).
- [ ] **Step 3:** add the field + migration; append `lc.custdate` as column `[19]` to `QUERY_CUSTOMERS` and to the index comment; in the row loop `if len(row) > 19: customer.softech_created_at = _to_date(row[19])`; add `'softech_created_at'` to `update_fields`.
- [ ] **Step 4: Run** `TEST_DB_NAME=test_pic_t1 python manage.py test apps.tests.test_customer_created_at_sync` → PASS.
- [ ] **Step 5: Commit** `feat(customers): mirror SOFTECH custdate as softech_created_at`.

### Task 2: App skeleton, models, settings

**Files:**
- Create: `apps/pic_analytics/{__init__,apps,models,admin}.py`, migration `0001_initial.py`
- Modify: `config/settings.py` (INSTALLED_APPS after `'apps.stock_audit'`), `apps/audit/models.py` ACTION_CHOICES, `apps/config/management/commands/seed_config.py` (or wherever SystemSetting defaults are seeded — `grep -rn "SystemSetting.objects.get_or_create\|DEFAULT_SETTINGS" apps/config`)
- Test: `apps/tests/test_pic_models.py`

**Interfaces — Produces:**
- `PicDayFact`: `pic` (Char 30, index), `day` (Date, index), `branch` (FK branches.Branch, null), `salesperson` (Char 20, blank — `softech_user`), `channel_bucket` (Char 20, blank), `invoices` (int), `returns` (int), `net` (Decimal 14,2), `cost` (Decimal 14,2), `units` (Decimal 14,3), `lines` (int), `net_by_category` (JSON `{medicine_type: net}`), `is_first_purchase` (bool). Unique `(pic, day, branch, salesperson, channel_bucket)`; indexes `(day, branch)`, `(pic, day)`. `pic=''` rows hold no-PIC sales.
- `PicRollup`: `pic` (unique), `as_of` (Date), `first_purchase`, `last_purchase`, `prev_visit_before_last` (Dates, null), `visits_12m`, `months_a`, `streak_b` (int), `cycle_days` (Decimal null), `cycle_bucket` (Char 10), `lifetime_net` (Decimal), `home_branch` (FK null — branch of most visits in 12m).
- `PicAnalyticsAccess`: same fields as `stock_audit.StockAuditAccess` (staff, note, granted_by/at, revoked_by/at), related_name `pic_analytics_grants`.
- `PhoneLabel`: `phone_key` (Char 15, unique), `label` (choices `staff, supplier, branch, doctor, spam, other`), `note`, `created_by` (FK StaffProfile), `created_at`.
- Audit actions: `pic_analytics_exported`, `pic_analytics_access_granted`, `pic_analytics_access_revoked`, `pic_phone_labelled`.
- SystemSetting keys (int/float): `pic_loyal_months=10`, `pic_overdue_factor=1.5`, `pic_call_return_hours=24`, `pic_call_purchase_days=7`.

- [ ] **Step 1: Failing test** `test_day_fact_unique_grain` (second insert with same 5-tuple raises `IntegrityError`) and `test_phone_label_unique`.
- [ ] **Step 2:** run → FAIL. **Step 3:** implement models, migration, admin (read-only list), settings seed. **Step 4:** run → PASS; `python manage.py makemigrations --check --dry-run` → "No changes detected".
- [ ] **Step 5: Commit** `feat(pic_analytics): models, settings and audit actions`.

### Task 3: Definitions as pure functions

**Files:** Create `apps/pic_analytics/rules.py`; Test `apps/tests/test_pic_rules.py` (`SimpleTestCase`, no DB).

**Interfaces — Produces** (all take plain Python dates/lists):
- `months_bought(visit_days: list[date], end: date) -> int` — A over the 12 calendar months ending at `end`'s month.
- `longest_streak(visit_days, end) -> int` — B.
- `cycle_days(visit_days) -> float | None` — C mean gap; None if < 2 visits.
- `cycle_bucket(days: float | None) -> str` — buckets from Global Constraints; `''` for None.
- `is_overdue(last_visit: date, cycle: float | None, today: date, factor: float) -> bool`.
- `classify_pic(first_purchase: date, created_at: date | None, prev_visit: date | None, period_start: date, period_end: date, first_visit_in_period: date) -> str` — `'new' | 'reactivated' | 'returning'`.
- `retention(prev_pics: set, cur_pics: set) -> float | None`.

- [ ] **Step 1: Failing tests** (exact values):

```python
D = date
def test_months_bought_counts_distinct_months(self):
    v = [D(2026,1,5), D(2026,1,20), D(2026,2,1), D(2026,6,9), D(2026,10,28)]
    self.assertEqual(rules.months_bought(v, D(2026,10,31)), 4)
def test_months_window_is_12_months(self):
    self.assertEqual(rules.months_bought([D(2025,10,30), D(2026,10,1)], D(2026,10,31)), 1)
def test_longest_streak(self):
    v = [D(2026,1,1), D(2026,2,1), D(2026,3,1), D(2026,6,1), D(2026,8,1)]
    self.assertEqual(rules.longest_streak(v, D(2026,10,31)), 3)
def test_cycle_and_bucket(self):
    self.assertEqual(rules.cycle_days([D(2026,1,1), D(2026,2,15), D(2026,3,1)]), 29.5)
    self.assertEqual(rules.cycle_bucket(29.5), 'm1'); self.assertEqual(rules.cycle_bucket(45), 'm2')
    self.assertEqual(rules.cycle_bucket(400), 'y1plus'); self.assertEqual(rules.cycle_bucket(None), '')
def test_same_day_visits_are_one(self):
    self.assertIsNone(rules.cycle_days([D(2026,1,1), D(2026,1,1)]))
def test_overdue(self):
    self.assertTrue(rules.is_overdue(D(2026,8,1), 30, D(2026,10,1), 1.5))
    self.assertFalse(rules.is_overdue(D(2026,9,10), 30, D(2026,10,1), 1.5))
def test_new_needs_recent_creation(self):
    args = dict(period_start=D(2026,10,1), period_end=D(2026,10,31), first_visit_in_period=D(2026,10,5), prev_visit=None)
    self.assertEqual(rules.classify_pic(first_purchase=D(2026,10,5), created_at=D(2026,10,5), **args), 'new')
    self.assertEqual(rules.classify_pic(first_purchase=D(2026,10,5), created_at=D(2019,1,1), **args), 'returning')
    self.assertEqual(rules.classify_pic(first_purchase=D(2026,10,5), created_at=D(2026,9,2), **args), 'new')  # within 30 d
def test_unknown_creation_falls_back_to_first_purchase(self):
    self.assertEqual(rules.classify_pic(D(2026,10,5), None, None, D(2026,10,1), D(2026,10,31), D(2026,10,5)), 'new')
def test_reactivated_after_365_days(self):
    self.assertEqual(rules.classify_pic(D(2024,9,1), D(2024,9,1), D(2025,9,30), D(2026,10,1), D(2026,10,31), D(2026,10,1)), 'reactivated')
    self.assertEqual(rules.classify_pic(D(2024,9,1), D(2024,9,1), D(2025,10,2), D(2026,10,1), D(2026,10,31), D(2026,10,1)), 'returning')
def test_returned_only_purchase_still_new(self):  # Review Focus 2 — visit days come from sale dates, returns ignored
    self.assertEqual(rules.classify_pic(D(2026,10,5), D(2026,10,5), None, D(2026,10,1), D(2026,10,31), D(2026,10,5)), 'new')
def test_retention(self):
    self.assertEqual(rules.retention({'a','b','c','d'}, {'a','b','x'}), 0.5)
    self.assertIsNone(rules.retention(set(), {'a'}))
```

- [ ] **Step 2:** run → FAIL. **Step 3:** implement. **Step 4:** run → PASS. **Step 5: Commit** `feat(pic_analytics): definition rules (visit, new/returning, frequency A/B/C, retention)`.

### Task 4: Nightly fact build

**Files:** Create `apps/pic_analytics/build.py`, `apps/pic_analytics/management/commands/build_pic_facts.py`; Modify `apps/sync/tasks.py` (job `_run_pic_facts`, cron 04:15, after the 03:55 call re-link); Test `apps/tests/test_pic_build.py`.

**Interfaces:**
- Consumes: `rules.*` (Task 3); `forecasting.ChannelBucketMap` for `(sales_person_type, sales_channel) → bucket` (read how `apps/forecasting/kpi.py` resolves it and call the same helper, do not re-implement).
- Produces: `build_day_facts(start: date, end: date) -> int` (deletes + rebuilds `PicDayFact` rows with `day` in [start, end]; returns rows written); `build_rollups(as_of: date) -> int`; command `build_pic_facts [--since YYYY-MM-DD] [--days N]` (default: last 7 days + rollups as of yesterday; `--since 2024-08-01` backfill).
- Excluded PICs (placeholders, merged) are written with `pic=''`.

- [ ] **Step 1: Failing tests** — fixtures: 2 PICs, 2 branches, invoices on the same day at the same branch (2 invoices), a return (doc 30), a placeholder-customer invoice, lines with `cost_at_sale` and items of medicine_type `10` and `50`.

```python
def test_same_day_invoices_one_fact_row(self):
    build.build_day_facts(D(2026,10,1), D(2026,10,31))
    f = PicDayFact.objects.get(pic='P1', day=D(2026,10,5))
    self.assertEqual((f.invoices, f.net), (2, Decimal('300.00')))
def test_return_reduces_net_on_its_own_day(self): ...  # returns=1, net negative on 10-07, invoices=0
def test_gp_and_categories(self): ...  # cost = Σ cost_at_sale×qty; net_by_category == {'10': ..., '50': ...}
def test_placeholder_sales_go_to_blank_pic(self): ...  # PicDayFact(pic='') net == placeholder invoice total
def test_first_purchase_flag(self): ...  # only the PIC's earliest-ever sale day has is_first_purchase=True
def test_rebuild_is_idempotent(self): ...  # running twice → same row count and sums
def test_rollup_frequency(self): ...  # build_rollups(D(2026,10,31)) → months_a, streak_b, cycle_bucket as rules give
```

- [ ] **Step 2:** FAIL. **Step 3:** implement with one aggregated ORM query per day-chunk (group lines by purchase→pic/day/branch/user/channel; Cairo-local day via `TruncDate('invoice_date', tzinfo=Cairo)`), bulk_create in batches of 2000 inside a transaction per chunk. **Step 4:** PASS; also run `python manage.py build_pic_facts --since 2024-08-01` against the local DB and record the row count and run time in the commit message. **Step 5: Commit** `feat(pic_analytics): nightly PicDayFact + PicRollup build`.

### Task 5: Access, RBAC, grants

**Files:** Create `apps/pic_analytics/access.py`; Modify `apps/users/models.py` (`MODULE_CHOICES` + `('pic_analytics', 'تحليلات العملاء')`), `apps/users/management/commands/seed_permissions.py` (`ALL_MODULES`, supervisor `{'view', 'export'}`), `apps/users/views.py` (`can_pic_analytics` like `can_stock_audit` lines 58/71/84); Test `apps/tests/test_pic_access.py`.

**Interfaces — Produces:** `Access(request)` with `.management`, `.branch_manager`, `.branch_ids: set[int] | None` (Branch pk; None = all), `.can_view`, `.can_export`, `.sees_cost` (= management), `.sees_calls_tabs` (= management), `.can_manage_access` (admin), `.scope_facts(qs)`, `.as_dict()`; `can_open(user) -> bool`. Grant endpoints copied from `stock_audit/views.py access_list / access_revoke / access_candidates` (admin only, AuditLog).

- [ ] **Step 1: Failing tests** `test_admin_and_supervisor_see_all`, `test_pharmacist_without_grant_denied`, `test_named_manager_sees_own_branch_only`, `test_revoked_grant_denies`, `test_branch_manager_never_sees_cost`, `test_branch_manager_no_calls_tabs`, `test_branch_param_ignored_for_branch_manager` (Review Focus 3: `scope_facts` with a request carrying `?branch=<other>` still returns only own-branch facts), `test_grant_and_revoke_audited`.
- [ ] **Step 2–4:** FAIL → implement → PASS; also `python manage.py seed_permissions --dry-run --role supervisor` shows `pic_analytics: view, export`.
- [ ] **Step 5: Commit** `feat(pic_analytics): access (management + named branch managers) and RBAC seed`.

### Task 6: Overview + PIC list queries

**Files:** Create `apps/pic_analytics/queries/__init__.py`, `queries/filters.py`, `queries/overview.py`, `queries/pics.py`; Test `apps/tests/test_pic_queries_overview.py`.

**Interfaces:**
- `Filters.from_request(request, access) -> Filters` — fields `start, end` (required, clamped to `[2024-08-01, today]`), `branch_ids`, `salesperson`, `agent_ext`, `channel_bucket`, `category`, `segment`, `customer_type`, `frequency`; exposes `data_from, data_to, clamped: bool`.
- `overview(f: Filters, access: Access) -> dict` keys: `distinct_pics, new, returning, reactivated, visits, invoices, net, gp, gp_pct, units, basket_net, basket_units, basket_categories, visits_per_pic, retention_pct, calls_in, calls_out, missed_not_returned, no_pic_net, new_reliable_from, by_month[]`. `gp`/`gp_pct` absent when `not access.sees_cost`. The call keys and the PIC list's call columns are added in Task 9 (return them as `None` here).
- `pic_rows(f, access, order: str, page: int, page_size=50) -> {'count', 'rows'[]}`; row keys per spec §6 PIC list. Phones masked with `apps.customers.access.mask_fields` unless `phones_visible`.

- [ ] **Step 1: Failing tests** `test_counts_new_returning_reactivated`, `test_visits_per_pic_and_basket`, `test_no_pic_sales_line_reconciles` (`net + no_pic_net` equals Σ PurchaseHistory net in range), `test_branch_manager_amounts_from_own_branch_only` (PIC buys at A and B; manager of A sees only A's net, label still chain-wide), `test_gp_absent_for_branch_manager`, `test_range_clamped_to_history` (Review Focus 1), `test_pic_list_sort_and_page`.
- [ ] **Step 2–4.** **Step 5: Commit** `feat(pic_analytics): overview and PIC list`.

### Task 7: Branches, salespeople, channels & categories

**Files:** Create `queries/groups.py`; Test `apps/tests/test_pic_queries_groups.py`.

**Interfaces:** `by_branch(f, access) -> list[dict]`, `by_salesperson(f, access)`, `by_channel(f, access)`, `by_category(f, access)`. Each row: `key, label, distinct_pics, new, returning, reactivated, visits, net, gp?, basket_net, units_per_visit`. Plus an `all` total row. New-PIC attribution = branch/salesperson/channel of the PIC's first fact row in the period. Salesperson labels via `analytics.views._build_user_map`. Category labels from `Item.medicine_type_name_ar`.

- [ ] Tests: `test_new_pic_attributed_to_first_invoice_salesperson`, `test_returning_counted_once_per_group`, `test_branch_rows_may_exceed_total_visits` (same day two branches), `test_category_net_split`, `test_cross_category_rate`. Then FAIL → implement → PASS → **Commit** `feat(pic_analytics): branch, salesperson, channel and category breakdowns`.

### Task 8: Retention & frequency

**Files:** Create `queries/retention.py`; Test `apps/tests/test_pic_queries_retention.py`.

**Interfaces:** `frequency(f, access) -> {'a': {1..12: n}, 'b': {...}, 'c': {bucket: n}, 'loyal': n, 'overdue': n}`; `overdue_list(f, access, page) -> rows`; `retention_summary(f, access) -> {'retention_pct', 'prev_period': (start, end)}`; `cohorts(f, access) -> [{'cohort': 'YYYY-MM', 'size', 'months': [pct…12]}]`. Uses `PicRollup` when `f.end == yesterday`, else `rules` over `PicDayFact`.

- [ ] Tests: `test_frequency_classes_match_rules`, `test_rollup_and_on_the_fly_agree` (same answer for `end=yesterday` both ways), `test_overdue_uses_setting_factor`, `test_cohort_table_shape`. FAIL → implement → PASS → **Commit** `feat(pic_analytics): retention, frequency classes and cohorts`.

### Task 9: Calls per PIC and call-center tab

**Files:** Create `queries/calls.py`; Modify `queries/overview.py` and `queries/pics.py` (fill the call keys / columns from `calls_by_pic`; for a branch manager pass only the PICs with facts at their branch in the period); Test `apps/tests/test_pic_queries_calls.py`.

**Interfaces:**
- `calls_by_pic(f, pics: set[str] | None) -> dict[pic, {'in', 'out', 'answered', 'missed', 'last_call', 'avg_days_between', 'talk_seconds', 'call_to_purchase'}]` — `is_transfer=False`; `talk_seconds` = Σ `billable_seconds` of answered calls.
- `call_center(f, access) -> list[{'agent_ext', 'staff_name', 'pbx_name', 'calls_in', 'calls_out', 'answered', 'talk_seconds', 'pics_reached', 'new_pics_sold', 'call_to_purchase_pct', 'unanswered_out', 'avg_attempts_to_reach'}]` — 403 path for branch managers handled in views; `new_pics_sold` from facts whose `salesperson` ∈ `CallCenterConfig.sales_agent_usercodes`.

- [ ] Tests: `test_branch_manager_calls_only_for_own_branch_pics` (PIC who never bought at the manager's branch → no call columns in their PIC list, not in their overview call counts), `test_shared_number_counted_on_latest_buyer_only`, `test_unresolved_shared_number_counted_once_in_totals` (Review Focus 4), `test_transfer_legs_ignored`, `test_call_to_purchase_window` (purchase on day 7 counts, day 8 not), `test_attempts_to_reach` (3 unanswered then answered same number same day → 4). FAIL → implement → PASS → **Commit** `feat(pic_analytics): calls per PIC and call-center tab`.

### Task 10: Missed & unanswered calls

**Files:** Create `queries/missed.py`; Test `apps/tests/test_pic_queries_missed.py`.

**Interfaces:** `missed_summary(f) -> {'missed', 'missed_numbers', 'returned', 'not_returned', 'median_minutes_to_return', 'heatmap': [[weekday, hour, n]], 'by_queue'}`; `missed_rows(f, only_not_returned: bool, page) -> rows` with `call_at, customer_number (masked), pic, shared_pics, customer_name, segment, last_purchase, lifetime_net, bought_within_7d, returned_at, minutes_to_return`, ordered by `lifetime_net` desc then `call_at` desc; `unanswered_summary(f) -> per agent`.

- [ ] Tests: `test_returned_within_window` (answered outbound 23 h later → returned; 25 h → not), `test_returned_by_inbound_answer_too`, `test_window_from_setting`, `test_heatmap_cairo_hours`, `test_rows_sorted_by_value`. FAIL → implement → PASS → **Commit** `feat(pic_analytics): missed and unanswered calls`.

### Task 11: New numbers + labels

**Files:** Create `queries/numbers.py`; Test `apps/tests/test_pic_queries_numbers.py`.

**Interfaces:** `new_numbers(f, page) -> rows` (`phone_key, number (masked), calls_in, calls_out, answered, missed, first_call, last_call, last_agent, talk_seconds, kind: 'mobile'|'landline'`) over `CdrCall.pic_match='none'` excluding `PhoneLabel` keys; `conversions(f) -> {'became_pic', 'became_pic_and_bought', 'rows'}` — a number converted in the period when its PIC (now on `CdrCall.pic`) has `softech_created_at` in the period and the number has at least one call dated before that `softech_created_at`; "and bought" = a `PicDayFact` sale for that PIC on/after `softech_created_at`; `label_number(phone_key, label, note, staff) -> PhoneLabel` (AuditLog `pic_phone_labelled`).

- [ ] Tests: `test_labelled_numbers_excluded`, `test_mobile_vs_landline` (`01xxxxxxxxx` mobile, 8-digit landline), `test_conversion_after_new_pic_relinked` (create Customer with the number + `softech_created_at` after the first call, run `apps.pbx.cdr.relink_all()`, assert it appears in `conversions`), `test_label_audited`. FAIL → implement → PASS → **Commit** `feat(pic_analytics): new numbers, labels and conversion`.

### Task 12: API and Excel export

**Files:** Create `apps/pic_analytics/views.py`, `urls.py`, `export.py`; Modify `config/urls.py` (`path('api/pic-analytics/', include('apps.pic_analytics.urls'))`); Test `apps/tests/test_pic_api.py`.

**Interfaces — Produces (all GET unless noted, all through `Access`):** `access/` (as_dict), `overview/`, `pics/`, `groups/<branch|salesperson|channel|category>/`, `retention/`, `calls/center/`, `calls/missed/`, `calls/missed/rows/`, `calls/unanswered/`, `numbers/`, `numbers/label/` (POST, management), `export/` (xlsx), `grants/`, `grants/candidates/`, `grants/<id>/revoke/` (POST, admin). Calls tabs → 403 for branch managers. `export/` builds one sheet per tab + «الفلاتر والتعريفات» sheet; RTL, frozen header, fill `022871`, `branch_label`; write-only workbook; AuditLog `pic_analytics_exported` with filters and row counts; requires `can_export`.

- [ ] Tests: `test_every_endpoint_requires_access` (anonymous 401, pharmacist 403), `test_branch_manager_calls_tabs_forbidden`, `test_export_has_no_cost_columns_for_branch_manager` (open workbook, assert no header contains «تكلفة»/«ربح»), `test_export_audited`, `test_empty_period_exports_filters_sheet` (Review Focus 5). Add the new prefix to the security route classification if `test_static_guards` / `routes.py` requires it (run `apps.tests.security` and follow its message). FAIL → implement → PASS → **Commit** `feat(pic_analytics): API and Excel export`.

### Task 13: Dashboard page (sales tabs) + menu, route, help

**Files:** Create `frontend/src/pages/PicAnalyticsPage.jsx`, `frontend/src/components/pic-analytics/{Filters,KpiCards,PicTable,GroupTable,RetentionPanel,AccessPanel}.jsx`; Modify `frontend/src/api/client.js` (`picAnalyticsApi`), `frontend/src/App.jsx` (route `customers/pic-analytics`), `frontend/src/components/Layout.jsx` (customers group: `{ to: '/customers/pic-analytics', icon: '📊', label: 'تحليلات العملاء', roles: ['admin','supervisor'], cap: 'can_pic_analytics' }`), `apps/help/content/customers.py` (screen `customers.pic_analytics`, tabs `overview, pics, branches, salespeople, channels, retention, calls, missed, numbers`, tour targets as `data-tour` attributes, `updated: '<build date>'`); Test `apps/tests/test_help.py` (existing) + `npm run build`.

- Tabs: overview, pics, branches, salespeople, channels, retention (spec §6). `useHelpTab(tab)`, `useGridKeyboard` on tables, `useBranchLabels`, `DataFreshnessBar domains={['sales','customers','calls']}`, refresh button, URL `?tab=&from=&to=` so links are shareable. Copy filter/KPI/BarRow layout from `ReservationsAnalyticsPage.jsx`. GP columns render only when the API returns them. AccessPanel (admin) manages grants. Export button calls `export/` and `downloadBlob`.

- [ ] **Steps:** run `apps.tests.test_help` first (expect FAIL: route without help) → implement page + help → `test_help` PASS → `npm run build` succeeds → preview in the browser pane as admin and as a granted pharmacist (screenshot both) → **Commit** `feat(pic_analytics): dashboard page, menu and help`.

### Task 14: Calls tabs in the page

**Files:** Create `frontend/src/components/pic-analytics/{CallCenterTab,MissedTab,NumbersTab,Heatmap}.jsx`; Modify `PicAnalyticsPage.jsx`, `apps/help/content/customers.py` (tab bodies), `apps/help/content/callcenter.py` (a shortcut line on تحليلات التواصل pointing to `/customers/pic-analytics?tab=missed`).

- Missed tab: summary cards, hour × weekday heatmap (CSS grid, no library), rows with «اتصل» → `pbxApi.dial` (existing) and «جدولة معاودة» → the existing call-back create on `/api/callcenter/calls/` with `status='callback'` and `callback_due` (find the request shape in `CallCenterPage`/`callcenter` client calls). Numbers tab: rows with «نسخ الرقم» and a label dropdown (POST `numbers/label/`), conversion cards. Tabs hidden when `access.sees_calls_tabs` is false.

- [ ] **Steps:** `test_help` PASS → `npm run build` → browser check as admin (missed list, dial button present, label a number and see it leave the list) → **Commit** `feat(pic_analytics): call-center, missed calls and new numbers tabs`.

### Task 15: Whole-branch verification

- [ ] `python manage.py makemigrations --check --dry-run` → no changes.
- [ ] `TEST_DB_NAME=test_pic_full python manage.py test apps.tests.test_pic_models apps.tests.test_pic_rules apps.tests.test_pic_build apps.tests.test_pic_access apps.tests.test_pic_queries_overview apps.tests.test_pic_queries_groups apps.tests.test_pic_queries_retention apps.tests.test_pic_queries_calls apps.tests.test_pic_queries_missed apps.tests.test_pic_queries_numbers apps.tests.test_pic_api apps.tests.test_customer_created_at_sync apps.tests.test_help apps.tests.security` → OK.
- [ ] `bandit -r apps/pic_analytics -ll -q` → no new issues.
- [ ] Time each endpoint for October 2026, all branches, on the local DB: every tab < 3 s; record numbers in the PR.
- [ ] Update `docs/architecture/33_PIC_ANALYTICS.md` status line to BUILT and `11_ERP_INDEX.md` (module + screen + command rows).
- [ ] Open the PR; deploy notes: migrate, `seed_permissions`, `build_pic_facts --since 2024-08-01`, restart scheduler.
