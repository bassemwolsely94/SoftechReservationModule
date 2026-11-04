# 35 — Finance General Ledger (دفتر الأستاذ العام) — Plan 1: ledger foundation

Status: ✅ BUILT (2026-11-04) — Plan 1 of 3. Plan 2 (drafting from SOFTECH) and Plan 3 (close &
reconcile) are planned in `docs/superpowers/plans/2026-11-04-finance-gl-{drafting,close}.md`.
Spec: `docs/superpowers/specs/2026-11-04-finance-general-ledger-design.md`.

Finance keeps its own double-entry ledger on its own 4-digit chart of accounts, so its Excel journal
can be replaced by entries keyed, reviewed and approved here. **No SOFTECH reads or writes** in this
plan: `apps/finance/gl/` never imports `config.sybase`.

## Code

| File | Responsibility |
|---|---|
| `apps/finance/gl/models.py` | `GLAccountGroup`, `GLAccount`, `LedgerEntry`, `LedgerLine`, `GLSequence` (app label `finance`, re-exported from `apps/finance/models.py`); `FinancialPeriod.status` open/closing/closed |
| `apps/finance/gl/ledger.py` | the only code that changes entry state: `save_draft`, `approve`, `reverse`, `LedgerError(code, message)`; fatal audit rows |
| `apps/finance/gl/coa_import.py`, `names.py` | parse finance's trial-balance pivot → groups / accounts (`GROUP_MAP`, `BS_LINE_BY_ACCOUNT`, party types, system accounts 1390 / 5302) |
| `apps/finance/gl/opening.py` | the 1-1-2026 opening entry from the 31-12-2025 trial balance (source key `opening:2026`) |
| `apps/finance/gl/balances.py` | `trial_balance`, `account_statement` (approved + reversed lines; drafts never count) |
| `apps/finance/gl/statements.py` | `trading_and_pl`, `financial_position`, `branch_pl` (report-time HQ allocation), `comparison` |
| `apps/finance/gl/views.py`, `urls.py`, `exports.py` | REST API under `/api/finance/gl/` and Excel exports |
| `frontend/src/pages/finance/gl/*` | screens (below) |
| `apps/tests/test_gl_*.py` | tests per layer |

## Rules (deterministic)

- Money is `Decimal(18,2)`; more than 2 decimals or a negative amount is **rejected**, never rounded.
- One side per line; a draft may be unbalanced, approval needs Σdebit = Σcredit > 0.
- Approval: open period, `entry_date ≥ 2026-01-01`, active posting accounts, party / branch when the
  account demands it; number `JV-<year>-<6 digits>` from a locked `GLSequence` row (concurrent approves →
  exactly one wins, the other gets `not_draft` → HTTP 409).
- Approved entries are immutable. Corrections are reversing entries (`reverse`): an approved mirror with
  debit↔credit; the original becomes `reversed`. A reversal cannot be reversed; an entry is reversed once.
- A source key belongs to one live (draft/approved) entry (`gl_live_source_key_unique`).
- Any user with `ledger.approve` may approve, including their own entry; creator and approver are stored.
- Every save / approve / reverse / delete / account edit / import is audited (who, when, before/after).

Entry statuses (help workflow `gl_entry`): `draft` → `approved` → `reversed`.

## RBAC

Module `ledger` (الحسابات العامة). Role `accountant` (all-branch): `ledger` view, create, approve, export;
`finance` view/export, `cheques` view, `dashboard` view. `ledger.edit` (chart edits, import) and
`ledger.finalize` (period close, Plan 3) are granted by the owner in «الصلاحيات». Every GL endpoint also
refuses users who are not all-branch (`core.branch_scope.sees_everything`, security batch 5 decision B-1).

## API — `/api/finance/gl/`

| Method · path | Action | Notes |
|---|---|---|
| `GET groups/` | view | `[{id, name, section, order}]` |
| `GET accounts/?q=&group=&active=` | view | list, `group` nested; `q` uses the shared wildcard search |
| `PATCH accounts/{code}/` | edit | name, statement_line, is_active, requires_branch, party_type |
| `POST accounts/import/` (multipart `file`, `dry_run`) | edit | `{created, updated, unknown_groups, rows}` |
| `GET entries/?status=&book=&date_from=&date_to=&branch=&account=&q=` | view | cursor pages `{next, previous, results}`; row has `total_debit`, `created_by_name` |
| `GET entries/{id}/` | view | with `lines` |
| `POST entries/` · `PUT entries/{id}/` | create | manual books general/cash/credit; PUT on non-draft → 409 |
| `DELETE entries/{id}/` | create | drafts only (409 otherwise); audited |
| `POST entries/{id}/approve/` · `POST entries/approve/ {ids}` | approve | bulk → `{results:[{id, ok, number | code, detail}]}` |
| `POST entries/{id}/reverse/ {reason, entry_date?}` | approve | returns the reversal |
| `GET reports/trial-balance/?from&to&branch&by` | view | list + `is_total` row |
| `GET reports/account-statement/?code&from&to&party&branch` | view | opening, lines with running balance, closing |
| `GET reports/statements/?from&to` · `position/?as_of` · `branch-pl/?from&to` · `comparison/?years=` | view | `branch-pl` → `{columns}`; `comparison` → `[{year, empty, values, pct_of_sales}]` |

Errors: `LedgerError` → 400 `{code, detail (Arabic, with «السطر n»), extra}`; `not_draft` /
`already_reversed` → 409. Decimals are strings; ratios are fractions. Any report with `?format=xlsx`
needs `ledger.export` and returns finance's layout (RTL, Arabic headers, `#,##0.00`, branch "code · name").
`URL_FORMAT_OVERRIDE` is off, so `format` is an ordinary query parameter here.

## Screens (hub `/finance`, tabs shown only with `ledger.view`)

| Route | Page | Notes |
|---|---|---|
| `/finance/coa` | `GLAccountsPage` | tree ↔ list, search, balance to date (from the trial balance), import preview → confirm and inline edit with `ledger.edit` |
| `/finance/journal` | `JournalPage` + `EntryEditor` | drafts first, review keyboard (↑↓ Space Enter Ctrl+A), bulk approve with per-row refusals, side-panel editor, reverse with reason |
| `/finance/trial-balance` | `TrialBalancePage` | month / quarter / year / custom, branch, by account or group, Excel |
| `/finance/ledger` | `AccountStatementPage` | account + party + period, row → entry panel |
| `/finance/statements?tab=` | `StatementsPage` | trading · position (check in red when ≠ 0) · branches · comparison; print + Excel; server warnings shown |

The SOFTECH freshness bar is hidden on these routes (the ledger is not a SOFTECH mirror).

## Commands and cutover

```
python manage.py import_gl_coa <xlsx> [--sheet NAME] [--dry-run]
python manage.py import_gl_opening <xlsx> --closing-stock <confirmed figure> [--sheet NAME] [--dry-run]
python manage.py gl_reproduce_workbook <xlsx> --year 2025 --closing-stock <figure>   # rolled back; exit 1 on any difference
```

1. Finance confirms the opening-stock figure (spec §13).
2. On production: `import_gl_coa` on the 2026 trial-balance sheet → review accounts in `/finance/coa` →
   `import_gl_opening --closing-stock <confirmed>`.
3. Grant `accountant` to finance staff; grant `ledger.edit` / `ledger.finalize` to the finance manager.
