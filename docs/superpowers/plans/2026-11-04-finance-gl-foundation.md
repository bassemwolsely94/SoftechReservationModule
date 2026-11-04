# Finance General Ledger — Plan 1 of 3: Ledger Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give finance a working double-entry ledger on their own chart of accounts — import their COA and the 1-1-2026 opening entry, key/approve/reverse entries, and produce the trial balance, account statements and their financial statements — with no SOFTECH reads or writes yet.

**Architecture:** New `apps/finance/gl/` package (models re-exported from `apps/finance/models.py`, same pattern as `recon_models`). A single service module (`gl/ledger.py`) owns every state change (draft → approved → reversed) so business rules live in one place; reports are pure functions over approved lines. REST under `/api/finance/gl/`, RBAC module `ledger`, new role `accountant`. React pages are new tabs in the existing `/finance` hub.

**Tech Stack:** Django 5.2 + DRF, PostgreSQL, openpyxl (import/export), React 18 + Vite + TanStack Query + Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-04-finance-general-ledger-design.md`

**The three plans:**
1. **This plan — ledger foundation** (COA, opening entry, manual entries, approval, reports).
2. **Drafting engine** — parties mapping, posting rules, SOFTECH source readers, review inbox exceptions, drafting job + FreshnessBar (spec §7 GLParty/PostingRule/SourceException, §8, screens 2–3).
3. **Close & reconcile** — month close with closing stock from SOFTECH cost, late-change corrections, year-end close, sub-ledgers linked to A/P recon, ledger-vs-SOFTECH comparison, 2026 manual-entry importer, Jan–Aug validation (spec §9 screens 7–9, §11, §11a).

## Global Constraints

- No SOFTECH reads or writes in this plan. Never import `config.sybase` from `apps/finance/gl/`.
- Money: `DecimalField(max_digits=18, decimal_places=2)`; inputs with more than 2 decimals are rejected (not rounded); arithmetic in `Decimal`, `ROUND_HALF_UP` where rounding is unavoidable (allocation only).
- Approved entries are immutable; corrections are reversing entries (spec §4, §10).
- A source key can belong to only one live (draft/approved) entry (spec §7, §11a).
- Any user with `ledger.approve` may approve, including their own manual entry (owner, 2026-11-04); creator and approver are stored separately.
- Ledger data is all-branch only (security batch 5 decision B-1): every GL view refuses users for whom `core.branch_scope.sees_everything(request.user)` is False.
- Every create/edit/approve/reverse/import goes through `AuditLog.log(...)` (`apps/audit/models.py:250`) with before/after.
- The opening entry is dated 2026-01-01; nothing may be posted before it (owner, 2026-11-04).
- Arabic-first UI; every new screen/tab gets help in `apps/help/content/finance.py` (Arabic + English) with `updated` bumped; tabbed pages call `useHelpTab(tab)`; `apps/tests/test_help.py` must pass.
- Every table is sortable (`useSortableRows` / `SortTh`); approve grids use `useGridKeyboard`.
- Tests run with a unique `TEST_DB_NAME` (working agreement).
- Real finance workbooks are never committed; tests build synthetic workbooks with openpyxl.

## Review Focus

1. **Amounts with 3+ decimals or negative values typed into a line** → rejected with an Arabic message, never silently rounded. (Task 3)
2. **Two accountants approve the same draft at the same moment** → exactly one approval, one entry number, the second gets 409. (Task 3)
3. **An entry dated before 2026-01-01 or in a closed period** → approve refused. (Task 3)
4. **Finance's pivot sheet as exported** — group name only on the first row of each group, `Total` rows, `Grand Total`, trailing spaces, ة/ه and ى/ي spelling variants → parsed into the right groups, totals ignored. (Task 4)
5. **Reversing an already-reversed entry, or reversing a reversal** → refused. (Task 3)

## File Structure

| File | Responsibility |
|---|---|
| `apps/finance/gl/__init__.py` | package marker |
| `apps/finance/gl/models.py` | `GLAccountGroup`, `GLAccount`, `LedgerEntry`, `LedgerLine`, `GLSequence` |
| `apps/finance/gl/ledger.py` | the only code that changes entry state: `save_draft`, `approve`, `reverse`, `LedgerError` |
| `apps/finance/gl/names.py` | Arabic name normalisation shared by importers |
| `apps/finance/gl/coa_import.py` | parse finance trial-balance pivot → groups/accounts; `GROUP_MAP`, `BS_LINE_BY_ACCOUNT` |
| `apps/finance/gl/opening.py` | build/post the 1-1-2026 opening entry from a trial balance |
| `apps/finance/gl/balances.py` | `trial_balance`, `account_statement` |
| `apps/finance/gl/statements.py` | `trading_and_pl`, `financial_position`, `branch_pl`, `comparison` |
| `apps/finance/gl/exports.py` | Excel exports of the reports in finance's layout |
| `apps/finance/gl/serializers.py`, `views.py`, `urls.py` | REST API |
| `apps/finance/management/commands/import_gl_coa.py`, `import_gl_opening.py`, `gl_reproduce_workbook.py` | CLI entry points |
| `apps/finance/migrations/0020_general_ledger.py` | GL tables + `FinancialPeriod.status` fields |
| `apps/users/migrations/00NN_ledger_module_accountant_role.py` | role + RBAC rows |
| `apps/tests/test_gl_*.py` | tests per task |
| `frontend/src/pages/finance/gl/*.jsx` | GL screens |
| `docs/architecture/34_FINANCE_GENERAL_LEDGER.md` | architecture doc |

---

### Task 1: `accountant` role and `ledger` RBAC module

**Files:**
- Modify: `apps/users/models.py:5-15` (ROLE_CHOICES), MODULE_CHOICES (add `('ledger', 'الحسابات العامة')`)
- Modify: `apps/users/management/commands/seed_permissions.py` (roles list, `accountant` grants, `ledger` for every role)
- Create: `apps/users/migrations/00NN_ledger_module_accountant_role.py` (pattern: `0042_tasks_module_incentives_owner.py`)
- Modify: every role-label map that lists `quality_manager` (grep `'quality_manager'` in `frontend/src` and non-migration `apps/` code; add `accountant: 'محاسب'` where roles are labelled)
- Test: `apps/tests/test_gl_permissions.py`

**Interfaces:**
- Produces: role `'accountant'`; module `'ledger'` with actions `view`, `create` (manual drafts), `approve`, `export` granted to `accountant`; `edit` (COA and, in plan 2, rules) and `finalize` (period close, plan 3) granted to nobody but admin (admin bypasses the matrix) — the owner grants them in «الصلاحيات». `accountant` also gets `finance: {view, export}`, `cheques: {view}`, `dashboard: RO`. No other role gets `ledger` rows set to allowed.

- [ ] **Step 1: Write the failing tests** — `test_accountant_has_ledger_view_create_approve_export`, `test_accountant_lacks_ledger_edit_and_finalize`, `test_other_roles_have_no_ledger_access` (loop the 9 existing roles: `matrix_allows(profile, 'ledger', 'view')` is False), `test_admin_bypasses`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_permissions` — Expected: FAIL (`accountant` not a valid role).
- [ ] **Step 3: Implement** the role, module, data migration (`get_or_create` per role × action, `is_allowed` per the grants above; backwards deletes `module='ledger'` rows and sets any `accountant` profile to `viewer`), and the `seed_permissions` entries.
- [ ] **Step 4: Run** the test module and `python manage.py seed_permissions --dry-run --role accountant` — Expected: PASS; dry run lists the grants above.
- [ ] **Step 5: Commit** — `feat(finance-gl): accountant role and ledger RBAC module`

### Task 2: GL models and migration

**Files:**
- Create: `apps/finance/gl/__init__.py`, `apps/finance/gl/models.py`
- Modify: `apps/finance/models.py` (re-export like `recon_models`, line 27), `FinancialPeriod` (add fields below)
- Create: `apps/finance/migrations/0020_general_ledger.py`
- Test: `apps/tests/test_gl_models.py`

**Interfaces:**
- Produces (all `app_label='finance'`):
  - `FinancialPeriod` + `status` (`open|closing|closed`, default `open`), `closed_by` FK StaffProfile null, `closed_at` null. Keep `is_closed` in sync (`status == 'closed'`) in `save()`.
  - `GLAccountGroup(name unique, section, order)`; `section` ∈ `balance_sheet|trading|pl`.
  - `GLAccount(code CharField(10) unique, name, group FK PROTECT, nature debit|credit, account_type asset|contra_asset|liability|equity|revenue|contra_revenue|expense|cogs, statement_line CharField(40), is_posting bool=True, is_active bool=True, is_system bool=False, requires_branch bool=False, party_type none|supplier|customer|employee|partner = none)`.
  - `LedgerEntry(number CharField null unique — set at approval e.g. 'JV-2026-000001', entry_date, period FK FinancialPeriod PROTECT, book cash|credit|general|opening|closing, branch FK null, description, status draft|approved|reversed, source_type CharField(30) blank, source_key CharField(120) blank, created_by FK, created_at, approved_by FK null, approved_at null, reverses FK self null related_name='reversals', notes)`. Constraint `UniqueConstraint(fields=['source_key'], condition=Q(status__in=['draft','approved']) & ~Q(source_key=''), name='gl_live_source_key_unique')`.
  - `LedgerLine(entry FK CASCADE related_name='lines', line_no, account FK GLAccount PROTECT, branch FK null, party_code CharField blank, debit Decimal(18,2)=0, credit Decimal(18,2)=0, description, cheque_no blank, due_date null)`. `CheckConstraint`: `debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0)`.
  - `GLSequence(year unique, last int)`.
  - Index: `LedgerLine(account, entry)`, `LedgerEntry(entry_date, status)`.

- [ ] **Step 1: Write the failing tests** — `test_line_cannot_have_debit_and_credit` (IntegrityError), `test_negative_amount_rejected_by_db`, `test_live_source_key_unique` (second draft with same key → IntegrityError; after first is `reversed`, a new draft with that key is allowed), `test_period_status_syncs_is_closed`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_models` — Expected: FAIL (import error).
- [ ] **Step 3: Implement** the models, `makemigrations finance` → rename to `0020_general_ledger.py`; verbose names in Arabic.
- [ ] **Step 4: Run** tests and `python manage.py makemigrations --check --dry-run` — Expected: PASS, "No changes detected".
- [ ] **Step 5: Commit** — `feat(finance-gl): ledger models`

### Task 3: Ledger service — drafts, approval, reversal

**Files:**
- Create: `apps/finance/gl/ledger.py`
- Test: `apps/tests/test_gl_ledger.py`

**Interfaces:**
- Consumes: Task 2 models.
- Produces:
  - `class LedgerError(Exception)` with `.code` (`unbalanced|empty|bad_amount|closed_period|before_opening|inactive_account|non_posting_account|party_required|branch_required|not_draft|already_reversed|is_reversal|source_conflict`) and Arabic `.message`.
  - `save_draft(*, user, entry_date, description, lines: list[dict], book='general', branch=None, source_type='', source_key='', entry: LedgerEntry | None = None) -> LedgerEntry` — creates or replaces lines of a draft (refuses non-draft). Line dict keys: `account_code, debit, credit, branch_id, party_code, description, cheque_no, due_date`. Validates per line (amount ≥ 0, ≤ 2 decimals, exactly one side > 0, account active & posting); balance is **not** required for a draft. Gets/creates the month `FinancialPeriod`.
  - `approve(entry_id: int, *, user, _allow_before_opening: bool = False) -> LedgerEntry` — the private flag exists only for `gl_reproduce_workbook` (Task 7), which runs inside a rolled-back transaction; no API path may pass it. In `transaction.atomic()`, `select_for_update()` the entry; refuses unless `status=='draft'`; validates balance (Σdebit == Σcredit > 0), period `open`, `entry_date >= OPENING_DATE`, party/branch requirements; assigns number from `GLSequence` (row locked); sets approved_by/at.
  - `reverse(entry_id: int, *, user, reason: str, entry_date: date | None = None) -> LedgerEntry` — refuses unless `approved` and not itself a reversal; creates an approved mirror entry (debit↔credit), `reverses=original`, original → `reversed`; reversal date defaults to original date if its period is open, else refused here (plan 3 adds the open-month correction path).
  - `OPENING_DATE = date(2026, 1, 1)`.
  - Every function writes `AuditLog.log('gl_entry_<draft_saved|approved|reversed>', user=..., obj=entry, old_data=..., new_data=...)`.

- [ ] **Step 1: Write the failing tests** —
  - `test_draft_may_be_unbalanced_but_approve_refuses` → `LedgerError.code == 'unbalanced'`
  - `test_three_decimal_amount_rejected` (`Decimal('10.005')` → `bad_amount`) *(Review Focus 1)*
  - `test_negative_amount_rejected` *(Review Focus 1)*
  - `test_approve_assigns_sequential_numbers` → `'JV-2026-000001'`, `'JV-2026-000002'`
  - `test_concurrent_approve_single_number` — `TransactionTestCase`, two threads call `approve` on the same draft; exactly one succeeds, the other raises `not_draft`; `GLSequence.last == 1` *(Review Focus 2)*
  - `test_before_opening_refused` (2025-12-31 → `before_opening`) and `test_closed_period_refused` *(Review Focus 3)*
  - `test_self_approval_allowed_and_audited` — creator == approver succeeds; AuditLog row has both ids
  - `test_reverse_mirrors_lines_and_marks_original`
  - `test_reverse_twice_refused` (`already_reversed`) and `test_reverse_of_reversal_refused` (`is_reversal`) *(Review Focus 5)*
  - `test_approved_entry_not_editable_via_save_draft` (`not_draft`)
  - `test_party_required_when_account_demands_it`
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_ledger` — Expected: FAIL.
- [ ] **Step 3: Implement** the functions above.
- [ ] **Step 4: Run** the module — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): ledger service with approval and reversal`

### Task 4: Chart-of-accounts importer

**Files:**
- Create: `apps/finance/gl/names.py`, `apps/finance/gl/coa_import.py`, `apps/finance/management/commands/import_gl_coa.py`
- Test: `apps/tests/test_gl_coa_import.py`

**Interfaces:**
- Produces:
  - `normalize_ar(s: str) -> str` — strip, collapse whitespace, `ة→ه`, `ى→ي`, `أ/إ/آ→ا`, drop tatweel.
  - `parse_trial_balance_sheet(path: str, sheet_name: str | None = None) -> list[TBRow]`; `TBRow(group: str, code: str, name: str, debit: Decimal, credit: Decimal, balance: Decimal)`. Finds the header row containing `Sub account name` / `رقم العملية` / `Trans. Name`; carries the group down blank cells; skips rows whose first cell ends with `Total` and `Grand Total`; debit/credit column order is read from the header (the 2025 sheet has `Credit, Debt`, the 2026 sheet `Debt, Credit`); credit values are negative in the sheet and stored positive. `balance = debit − credit`.
  - `import_coa(rows: list[TBRow], *, user, dry_run=False) -> ImportResult(created, updated, unknown_groups: list[str])` — upsert by code; never deletes; group via `GROUP_MAP` lookup on `normalize_ar(group)`; unknown group → reported, account not created.
  - `GROUP_MAP: dict[str, tuple[section, account_type, nature, default_statement_line]]` for every group in finance's sheets: اصول ثابته, مجمع الإهلاك, النقديه بالصندوق, النقديه بالبنوك, التحويلات, المقبوضات التجاريه, المقبوضات غير التجاريه, مصروفات مدفوعه مقدماً, الضرائب, المدفوعات التجاريه, المدفوعات الغير تجاريه, خصوم اخرى, الهيئه العامه للتأمينات الاجتماعيه, شركات شقيقة, جارى الشركاء, حقوق الملكيه, المبيعات, ايرادات, ارباح و خسائر راسمالية, تكلفة المبيعات, محزون أول المده, المصروفات العموميه, مصروفات بيع وتوزيع, مصروفات التشغيل, المصروفات التمويلية, الاهلاكات.
  - `BS_LINE_BY_ACCOUNT: dict[str, str]` — overrides that reproduce finance's 31-12-2025 statement of position exactly (verified against their workbook):
    - `cash` = 1301, 1302, 1303, 1320 and bank accounts 1306–1348 with a debit balance; banks with a credit balance → `overdraft` (sign rule applied at report time, see Task 7)
    - `receivables` = group المقبوضات التجاريه (1321, 1329, 1341, 1343, 1344, 1345)
    - `other_debtors` = 1304, 1351, 1357, 1366, 1368, 1370, 2362, 2363, 2364, 2366, 2367
    - `deposits` = 1353
    - `creditors` = 1369, 2132, 2351, 2354, 2360, 2361, 2365 and group شركات شقيقة
    - `notes_payable` = 2343 · `suppliers` = 2341
    - `capital` = 2400 · `partners` = group جارى الشركاء · `retained` = 2409
    - `fixed_assets` = group اصول ثابته · `accumulated_depreciation` = group مجمع الإهلاك
  - System accounts created by the importer if missing (`is_system=True`, finance may rename): `1390 بضاعة آخر المدة` (asset, line `inventory`) and `5302 مخزون آخر المدة` (cogs, trading, credit nature) — used by closing-stock entries.
  - `party_type`: 2341, 2351 → supplier; 1341 → customer; 1351 → employee; group جارى الشركاء → partner.
  - Command: `python manage.py import_gl_coa <xlsx> [--sheet NAME] [--dry-run]`.

- [ ] **Step 1: Write the failing tests** — build a synthetic workbook in `setUp` with openpyxl reproducing the pivot shape (group only on first row, `X Total` rows, `Grand Total`, trailing spaces, `ة`/`ه` variants, `Credit, Debt` order in one sheet and `Debt, Credit` in another):
  - `test_group_carried_down_and_totals_skipped` *(Review Focus 4)*
  - `test_column_order_detected_from_header`
  - `test_spelling_variants_map_to_same_group` *(Review Focus 4)*
  - `test_unknown_group_reported_not_created`
  - `test_reimport_updates_name_never_deletes`
  - `test_system_closing_stock_accounts_created`
  - `test_bs_line_overrides_applied` (e.g. 1304 → `other_debtors`, 2367 → `other_debtors`, 1369 → `creditors`)
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_coa_import` — Expected: FAIL.
- [ ] **Step 3: Implement** names, parser, importer, command (audited `gl_coa_imported` with counts).
- [ ] **Step 4: Run** the module — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): chart-of-accounts importer from finance trial balance`

### Task 5: Opening entry (1-1-2026)

**Files:**
- Create: `apps/finance/gl/opening.py`, `apps/finance/management/commands/import_gl_opening.py`
- Test: `apps/tests/test_gl_opening.py`

**Interfaces:**
- Consumes: `parse_trial_balance_sheet`, `save_draft`, `approve`.
- Produces: `build_opening_lines(rows: list[TBRow], closing_stock: Decimal) -> list[dict]` and `post_opening(path, *, closing_stock: Decimal, user, sheet_name=None) -> LedgerEntry`.
  - Balance-sheet-section accounts: one line each at their balance (debit if > 0, credit if < 0; zero balances skipped).
  - Trading and P&L accounts are not carried; their net `S = Σ balance` and the year's profit `closing_stock − S` go to 2409 as one line of `S − closing_stock` (debit if positive).
  - Opening stock line: debit 5301 `closing_stock` (finance's practice — their 2026 trial balance opens stock on 5301).
  - Entry: date 2026-01-01, `book='opening'`, `source_type='opening'`, `source_key='opening:2026'`, created as draft then approved by the same user. Refuses (`LedgerError('unbalanced')`) if lines don't balance; a second run hits `source_conflict`.
  - Command: `python manage.py import_gl_opening <xlsx> --closing-stock 6392683.40 [--sheet NAME] [--dry-run]` — `--closing-stock` is required (figure awaits finance confirmation, spec §13); dry run prints lines and totals without posting.

- [ ] **Step 1: Write the failing tests** — synthetic TB (assets, liabilities, equity, sales, purchases, expenses, 5301 opening stock; balanced):
  - `test_bs_accounts_carried_pl_accounts_closed_to_2409`
  - `test_profit_equals_closing_stock_minus_pl_net` (assert 2409 line amount)
  - `test_opening_stock_on_5301`
  - `test_entry_balances_and_is_approved_dated_2026_01_01`
  - `test_second_import_refused`
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_opening` — Expected: FAIL.
- [ ] **Step 3: Implement** `opening.py` and the command.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): opening entry from 31-12-2025 trial balance`

### Task 6: Trial balance and account statement

**Files:**
- Create: `apps/finance/gl/balances.py`
- Test: `apps/tests/test_gl_balances.py`

**Interfaces:**
- Produces:
  - `trial_balance(date_from: date, date_to: date, *, branch_id: int | None = None, by: Literal['account','group'] = 'account') -> list[dict]` — rows `{code, name, group, opening_debit, opening_credit, period_debit, period_credit, closing_debit, closing_credit}` from **approved and reversed** entries (a reversed entry and its reversal both count, netting to zero); opening = everything before `date_from`. Plus a totals row; totals must balance.
  - `account_statement(code: str, date_from, date_to, *, branch_id=None, party_code=None) -> dict` — `{opening_balance, lines: [{date, number, description, debit, credit, running_balance, entry_id}], closing_balance}`, ordered by date, number.
  - Drafts never appear in either.

- [ ] **Step 1: Write the failing tests** — `test_drafts_excluded`, `test_reversal_nets_to_zero`, `test_opening_column_is_before_date_from`, `test_totals_balance`, `test_branch_filter`, `test_group_rollup`, `test_running_balance`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_balances` — Expected: FAIL.
- [ ] **Step 3: Implement** with aggregate queries (one `values().annotate(Sum)` per column group, no per-line Python loops over the year).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): trial balance and account statement`

### Task 7: Financial statements + workbook reproduction check

**Files:**
- Create: `apps/finance/gl/statements.py`, `apps/finance/management/commands/gl_reproduce_workbook.py`
- Test: `apps/tests/test_gl_statements.py`

**Interfaces:**
- Consumes: `trial_balance`, `GLAccount.statement_line`, `GLAccountGroup.section`.
- Produces:
  - `trading_and_pl(date_from, date_to, *, branch_id=None) -> dict` — keys `opening_stock` (5301), `net_purchases` (group تكلفة المبيعات), `closing_stock` (credit balance of 5302 in range), `net_sales` (group المبيعات, positive), `gross_profit = net_sales − (opening_stock + net_purchases − closing_stock)`, then `other_revenue` (ايرادات), `capital_gains`, `general_expenses`, `selling_expenses`, `depreciation`, `operating_expenses`, `financing_expenses`, `net_profit`, and ratios `gross_margin`, `net_margin`, `expense_ratio`, `monthly_avg_sales` (÷ months in range). Same lines/labels as finance's «الختامية» sheet.
  - `financial_position(as_of: date, *, closing_stock_from_entries=True) -> dict` — long-term (`fixed_assets` cost, `accumulated_depreciation`, net), current assets (`inventory`, `receivables`, `other_debtors`, `deposits`, `cash`), current liabilities (`creditors`, `overdraft`, `notes_payable`, `suppliers`), `working_capital`, `total_investment`, equity (`capital`, `partners`, `profit_and_loss = −(2409 + current-year net result)`), `check = total_investment − equity` (must be 0). Bank accounts with a credit balance move from `cash` to `overdraft`.
  - `branch_pl(date_from, date_to, *, allocation_basis='sales') -> list[dict]` — one column per branch + total; HQ (lines with no branch or the HQ branch) expenses and depreciation allocated by `round(branch_sales / total_sales × hq_amount, 2)` with the rounding remainder on the largest branch so totals equal the consolidated P&L. Report-time only — posts nothing (spec §11a).
  - `comparison(years: list[int]) -> list[dict]` — `trading_and_pl` per calendar year, value + % of sales (finance's «الختامية المجمعة»). Years before 2026 are empty unless entries exist.
  - Command `python manage.py gl_reproduce_workbook <xlsx> --year 2025 --closing-stock 6392683.40` — inside `transaction.atomic()` with a forced rollback: imports the COA, posts that year's trial balance as one approved entry dated 31-12 plus a closing-stock entry (Dr 1390 / Cr 5302), runs `trading_and_pl` and `financial_position`, and prints them side by side with the workbook's own cells (sheets «الختامية بسوفتيك» and «الميزانية 31-12-2025», read by label, not position). Exit code 1 on any difference > 0.01. Nothing persists.

- [ ] **Step 1: Write the failing tests** — synthetic ledger:
  - `test_gross_and_net_profit_formula`
  - `test_closing_stock_read_from_5302`
  - `test_financial_position_balances` (`check == 0`)
  - `test_credit_balance_bank_moves_to_overdraft`
  - `test_branch_pl_allocation_sums_to_consolidated` (incl. rounding remainder)
  - `test_comparison_one_row_per_year`
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_statements` — Expected: FAIL.
- [ ] **Step 3: Implement** `statements.py` and the command.
- [ ] **Step 4: Run** tests — Expected: PASS. Then run locally (not in CI) against finance's real file: `python manage.py gl_reproduce_workbook "<OneDrive>\Personal Vault\المركز 31-12-2025.xlsx" --year 2025 --closing-stock 6392683.40` — Expected: exit 0; gross profit, net profit, current assets, current liabilities, working capital and equity match the workbook. Paste the output in the task report.
- [ ] **Step 5: Commit** — `feat(finance-gl): trading, P&L, financial position, branch P&L`

### Task 8: GL REST API and Excel exports

**Files:**
- Create: `apps/finance/gl/serializers.py`, `apps/finance/gl/views.py`, `apps/finance/gl/urls.py`, `apps/finance/gl/exports.py`
- Modify: `apps/finance/urls.py` (`path('gl/', include('apps.finance.gl.urls'))`)
- Test: `apps/tests/test_gl_api.py`

**Interfaces:**
- Consumes: Tasks 3–7.
- Produces (prefix `/api/finance/gl/`; permission `[IsAuthenticated, matrix_permission('ledger', ...)]` + all-branch gate returning 403):

  | Method · path | Action needed | Notes |
  |---|---|---|
  | `GET groups/`, `GET accounts/?q=&group=&active=` | view | tree-ready (`group` nested) |
  | `PATCH accounts/{code}/` | edit | name, statement_line, is_active, requires_branch, party_type; audited |
  | `POST accounts/import/` (multipart xlsx, `dry_run`) | edit | wraps `import_coa` |
  | `GET entries/?status=&book=&date_from=&date_to=&branch=&account=&q=` | view | cursor-paginated |
  | `GET entries/{id}/` | view | with lines |
  | `POST entries/` · `PUT entries/{id}/` | create | `save_draft`; PUT refused on non-draft (409) |
  | `DELETE entries/{id}/` | create | drafts only; audited |
  | `POST entries/{id}/approve/` · `POST entries/approve/ {ids:[]}` | approve | `LedgerError` → 400 with `{code, detail}`; `not_draft` → 409; bulk returns per-id result |
  | `POST entries/{id}/reverse/ {reason}` | approve | |
  | `GET reports/trial-balance/?from&to&branch&by` | view | `?format=xlsx` needs export |
  | `GET reports/account-statement/?code&from&to&party` | view | idem |
  | `GET reports/statements/?from&to` · `reports/position/?as_of` · `reports/branch-pl/?from&to` · `reports/comparison/?years=` | view | idem |

  Decimal amounts serialised as strings. Exports use finance's layout (right-to-left sheet, Arabic headers, number format `#,##0.00`), branch names via the existing branch-label helper, never bare codes.

- [ ] **Step 1: Write the failing tests** — `test_requires_auth`, `test_non_all_branch_user_403`, `test_accountant_can_create_and_approve`, `test_viewer_cannot_approve` (403), `test_put_on_approved_entry_409`, `test_delete_approved_entry_refused`, `test_bulk_approve_reports_each`, `test_ledger_error_shape` (`{code:'unbalanced', detail:<Arabic>}`), `test_trial_balance_xlsx_requires_export`, `test_account_patch_needs_edit`.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_gl_api` — Expected: FAIL.
- [ ] **Step 3: Implement** serializers, views, urls, exports.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `feat(finance-gl): REST API and Excel exports`

### Task 9: Frontend — API client, hub tabs, chart of accounts

**Files:**
- Modify: `frontend/src/api/client.js` (add `glApi` next to `financeApi`, one method per endpoint in Task 8)
- Modify: `frontend/src/pages/FinanceHubPage.jsx:23-30` (tabs), `frontend/src/App.jsx:511-522` (routes)
- Create: `frontend/src/pages/finance/gl/GLAccountsPage.jsx`
- Delete: `frontend/src/pages/ChartOfAccountsPage.jsx` (it showed SOFTECH's unused template; `/finance/coa` now renders `GLAccountsPage`)

**Interfaces:**
- Produces routes: `/finance/coa` (accounts), `/finance/journal`, `/finance/ledger` (account statement), `/finance/trial-balance`, `/finance/statements` (tabs: `trading`, `position`, `branches`, `comparison`). Hub tabs, in order after «لوحة القيادة»: «القيود» 📒, «ميزان المراجعة» ⚖️, «القوائم المالية» 📑, «كشف حساب» 📄, then the existing tabs; «دليل الحسابات» stays. Tabs needing `ledger` hidden when the user lacks it (existing hub pattern).
- `GLAccountsPage`: group tree ↔ flat list toggle, search (wildcard via `WildcardSearchFilter` on the API), per account: code, name, nature, statement line, active, balance to date; import button (dry-run preview then confirm) and inline edit only with `ledger.edit`. `data-tour` targets: `finance-gl-accounts-tree`, `finance-gl-accounts-import`.

- [ ] **Step 1: Implement** client methods, routes, tabs, page.
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: build succeeds (`check-sort` passes).
- [ ] **Step 3: Verify in the app** (preview server): `/finance/coa` lists imported accounts as a tree, import dry-run shows counts; console has no errors. Screenshot in the task report.
- [ ] **Step 4: Commit** — `feat(finance-gl): chart of accounts screen`

### Task 10: Frontend — journal (review, manual entry, approve, reverse)

**Files:**
- Create: `frontend/src/pages/finance/gl/JournalPage.jsx`, `frontend/src/pages/finance/gl/EntryEditor.jsx`

**Interfaces:**
- Consumes: `glApi.entries*`, `glApi.accounts`.
- Produces: `JournalPage` — filters (status default `draft`, book, date range, branch, account, text), sortable grid, multi-select with `useGridKeyboard` (↑↓ Space Enter, Ctrl+A), «اعتماد المحدد» calling bulk approve and showing per-row errors inline (no modal); row opens `EntryEditor` in a side panel. `EntryEditor` — date, book, description, line grid (account picker with code/name search, branch, party, debit, credit, description, cheque no., due date), live Σ debit / Σ credit / difference (display only — the server decides), save draft, approve (if `ledger.approve`), delete draft, reverse with reason (approved entries, read-only lines). Amount inputs use `useNumberInputGuards` with step 0.01. `data-tour` targets: `finance-gl-journal-filters`, `finance-gl-journal-approve`, `finance-gl-entry-lines`, `finance-gl-entry-totals`.

- [ ] **Step 1: Implement** both components.
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: success.
- [ ] **Step 3: Verify in the app**: create a balanced manual entry, approve it (gets `JV-2026-…`), try editing it (refused, read-only), reverse it; an unbalanced entry shows the server's Arabic error on approve. Screenshot.
- [ ] **Step 4: Commit** — `feat(finance-gl): journal review and manual entry screen`

### Task 11: Frontend — trial balance, account statement, financial statements

**Files:**
- Create: `frontend/src/pages/finance/gl/TrialBalancePage.jsx`, `AccountStatementPage.jsx`, `StatementsPage.jsx`

**Interfaces:**
- Consumes: `glApi.reports*`.
- Produces: `TrialBalancePage` — period (month/quarter/year/custom), branch, account vs group toggle, totals row, click account → account statement prefilled; Excel button (`ledger.export`). `AccountStatementPage` — account + party + range, running balance, row → entry side panel. `StatementsPage` — tabs `trading` (trading account + P&L in finance's two-column layout with ratios), `position` (statement of financial position with `check` shown only when ≠ 0, in red), `branches` (branch P&L grid with allocation rows), `comparison` (years × lines, value and %); calls `useHelpTab(tab)`; print-friendly CSS and Excel per tab. `data-tour`: `finance-gl-tb-period`, `finance-gl-statement-filters`, `finance-gl-statements-tabs`, `finance-gl-position-check`.

- [ ] **Step 1: Implement** the three pages.
- [ ] **Step 2: Run** `cd frontend && npm run build` — Expected: success.
- [ ] **Step 3: Verify in the app** on a dev DB loaded with the opening entry: trial balance on 2026-01-01 balances; position as of 2026-01-01 has `check == 0`. Screenshot.
- [ ] **Step 4: Commit** — `feat(finance-gl): trial balance, account statement and statements screens`

### Task 12: Help, docs, full regression

**Files:**
- Modify: `apps/help/content/finance.py` — screens `finance.gl_accounts` (`/finance/coa`, replaces the old COA text), `finance.gl_journal`, `finance.gl_trial_balance`, `finance.gl_account_statement`, `finance.gl_statements` (with per-tab help), each Arabic + English, `updated: '2026-11-04'`, targets matching Tasks 9–11; module summary updated to say the ledger is finance's own and does not write to SOFTECH.
- Create: `docs/architecture/34_FINANCE_GENERAL_LEDGER.md` (models, service rules, API, RBAC, import commands, cutover steps); Modify: `docs/architecture/11_ERP_INDEX.md`, `02_MODULE_REGISTRY.md` (finance), `04_API_REGISTRY.md`, `05_UI_REGISTRY.md`, `03_DATABASE_DICTIONARY.md`.

- [ ] **Step 1: Write** help and docs.
- [ ] **Step 2: Run** `python manage.py test apps.tests.test_help apps.tests.test_finance apps.tests.test_finance_freshness apps.tests.test_permissions apps.tests.test_gl_permissions apps.tests.test_gl_models apps.tests.test_gl_ledger apps.tests.test_gl_coa_import apps.tests.test_gl_opening apps.tests.test_gl_balances apps.tests.test_gl_statements apps.tests.test_gl_api` (unique `TEST_DB_NAME`) — Expected: all PASS.
- [ ] **Step 3: Run** the full suite `python manage.py test apps.tests` and `cd frontend && npm run build` — Expected: no new failures vs main.
- [ ] **Step 4: Commit** — `docs(finance-gl): help, architecture doc 34, registries`

---

## After this plan (owner steps, not code)

1. Finance confirms the opening-stock figure (spec §13), then on production: `import_gl_coa` on the 2026 trial-balance sheet → review accounts → `import_gl_opening --closing-stock <confirmed>`.
2. Grant the `accountant` role to finance staff; grant `ledger.edit` / `ledger.finalize` to the finance manager in «الصلاحيات».
3. Plan 2 (drafting engine) starts once the 2026 journal file is available unprotected.
