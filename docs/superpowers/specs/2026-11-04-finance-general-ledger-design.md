# Finance General Ledger (الحسابات العامة) — Design

**Status:** design complete, awaiting owner approval · **Date:** 2026-11-04 · **App:** extends `apps/finance` (no new app)

## 1. Intent

The finance & accounting department keeps the company's real double-entry ledger by hand in
Excel (American-style accrual accounting, «المحاسبة الأمريكية»). Two books — the cash journal
(يومية النقدى) and the credit journal (يوميات الاجل) — are combined (اليوميات) and every report
is an Excel pivot over that combined journal: trial balance, trading account and P&L, statement
of financial position, branch P&L, multi-year comparison and sub-ledgers. Most of the data they
key in already exists in SOFTECH (sales, purchases, supplier payments, cheques, expenses, stock
at cost), so the work is mostly re-typing and re-pivoting.

This module gives finance a real ledger on **their own chart of accounts**, drafts the journal
entries **automatically from SOFTECH** with deterministic posting rules, lets an accountant
review and approve them, and produces every statement they produce today. **It replaces the
Excel journal** (owner decision 2026-11-04) — it does not run beside it permanently.

## 2. Goals

1. Finance's chart of accounts (≈150 posting accounts, 4-digit codes, ~30 groups) is the master
   COA, mapped to the SOFTECH data that feeds or verifies each account.
2. SOFTECH activity becomes **draft** journal entries through finance-editable posting rules.
3. Any accountant reviews, corrects and approves drafts; manual entries use the same screen.
4. All statements they produce today come from approved entries, Egyptian layout, Arabic first.
5. Ledger-vs-SOFTECH comparison per account and month replaces the manual «مقارنة سوفتيك» sheet.
6. Period close locks a month and posts closing stock from SOFTECH cost valuation.

## 3. Non-goals

- No writes to SOFTECH. SOFTECH stays read-only for this module (its `acctrans*` tables are empty
  and its `accitems` chart is an unused template).
- No change to the existing A/P matching engine, cheques, receivables, supplier terms or cash
  view logic — they are linked, not rebuilt.
- No payroll engine, no fixed-asset register beyond what depreciation entries need (phase 2 at most).
- No e-invoice / tax-authority filing.

## 4. Anti-goals (would make it a failure even if it "works")

- A total, balance or posting decided by fuzzy matching or an LLM. Rules are explicit tables.
- An approved entry that can be edited or deleted. Corrections are reversing entries.
- The same SOFTECH document producing two entries (double counting = the GL equivalent of
  double posting).
- Finance needing Excel to finish a month after cutover.
- A second, parallel copy of supplier/customer/cheque logic that disagrees with A/P reconciliation.

## 5. What exists today (findings 2026-11-03)

| Existing | Reality | Plan |
|---|---|---|
| `finance.Account` (149 rows) | mirror of SOFTECH `accitems` template — not finance's COA | keep table, re-seed with finance COA; old rows archived (`is_active=False`, `source='softech_template'`) |
| `finance.JournalEntry/Line` (~359k / 937k) | synthesized from `branchesales`, `dailyexpenses`, `cheques` — not a ledger | do not reuse as ledger; new ledger models (§7). Old rows stay for the analytics screens that read them until those screens move to the GL |
| `finance.AccountBalance`, P&L, trial balance views | built on the synthesized journal | rebuilt on the GL |
| A/P reconciliation, receivables (P-41), supplier terms (P-42), cash view (P-40), `apps/cheques` | real, working | sub-ledger screens link to / reuse them |
| `apps/audit`, RBAC module `finance`, branch scoping, FreshnessBar, sortable grids, in-app help | platform | reused as-is |

## 6. Source material (finance's own files)

- `المركز 31-12-2025.xlsx` — 2025 trial balance (balances exactly), inventory at SOFTECH cost per
  branch/store, trading + P&L, statement of position, branch P&L with HQ allocation, 2017–2025
  comparison, sub-ledgers.
- `المركز المالى 31-08-2026.xlsx` — 2026 YTD trial balance total and per branch, monthly sales &
  purchases by account, sub-ledgers with dated lines.
- 2020 cash/credit/combined journals — the raw journal layout (9 of 10 files password-protected;
  needed only to learn posting patterns, not for import).

Pivot fields reveal the journal row: date, account code (رقم العملية), account name
(Trans. Name), group (Sub account name), SOFTECH branch name (اسم الفرع), description, debit or
credit (condition) and amount (balanc), book (نقدى/اجل), and party fields — supplier code,
customer code, employee code, cheque number, due date. **Party codes are finance's own**
(e.g. their 29 = Pharma Overseas, SOFTECH personcode 565).

## 7. Data model (all in `apps/finance`, new migration)

- **GLAccountGroup** — finance group (e.g. «المصروفات العموميه»), statement section
  (balance sheet / trading / P&L), statement line, order.
- **GLAccount** — code (unique), name, group FK, nature (debit/credit), type
  (asset/liability/equity/revenue/expense/cogs), posting flag, active flag, branch-dimension
  required flag, party-type required (supplier/customer/employee/partner/none).
  *Builder's call:* either extend `finance.Account` with these fields or add `GLAccount`; prefer
  extending if no screen relies on the template rows' semantics.
- **GLParty** — finance party code + type + name, optional FK/personcode to SOFTECH
  (`personsdata.personcode`), employee link where it exists. Mapping proposed by name match,
  confirmed by an accountant; unconfirmed parties block auto-posting for that party only.
- **PostingRule** — source type (§8) + conditions (branch, tender, doccode, expense code,
  supplier class…) → debit account / credit account / amount expression from a fixed whitelist
  of fields (net, VAT, discount, gross…), branch dimension source, party source. Versioned with
  effective-from date; edits audited; never deleted.
- **LedgerEntry** — date, period, book (cash / credit / general / opening / closing), branch,
  description, status (draft → approved → reversed), source type + **source key (UNIQUE)**,
  rule version used, created_by (system or user), approved_by/at, reverses FK.
- **LedgerLine** — entry FK, account, branch, party, debit, credit, description,
  cheque no., due date. DB constraint: per approved entry Σdebit = Σcredit.
- **Period** — reuse the existing `finance.FinancialPeriod` (already has `is_closed`); add
  status (open / closing / closed), closed_by/at, closing-stock snapshot reference. Posting into
  a closed period is refused server-side. Do not add a second period model.
- **SourceException** — SOFTECH rows no rule matched, or matched a rule needing an unmapped
  party/account; shown in the review inbox, resolved by adding a rule or a manual entry.

Money: `Decimal(18,2)` (piastres), ROUND_HALF_UP, matching finance's spreadsheets. Line
amounts stored, never recomputed after approval.

## 8. Drafting from SOFTECH

A scheduled job (and a manual "draft now" button with a FreshnessBar) reads the existing
mirrors / read-only queries and creates draft entries, **one entry per source document or per
branch-day aggregate** (rule decides granularity), idempotent on source key.

Source types (initial set, all already readable in the codebase):

| Source | SOFTECH data | Typical entry (finance accounts) |
|---|---|---|
| Branch daily sales | `branchesales` tenders × branch × day | cash box / card clearing (PAYMOB, CIB) / customers ↔ cash sales, card sales, credit (company) sales, output VAT |
| Sales returns & discounts | sales return doc types, discount fields | returns / discounts accounts ↔ cash / customers |
| HQ store sales | main-store sales docs | «مبيعات مخزن رئيسى» |
| Purchases & returns | `stktransm` doccode 10/120 and returns, FOC lines | purchases (cash/credit) + input VAT ↔ suppliers / cash; returns and purchase discounts |
| Supplier payments | `cheques` + `chequestrans` (A/P recon mirror) | suppliers ↔ notes payable (with due date) ↔ bank |
| Cheque maturity | cheque due/clear dates | notes payable ↔ bank |
| Customer collections | custpayments / receivables mirror | bank / notes receivable ↔ customers |
| Daily expenses | `dailyexpenses` × expense code | expense account (per expense-code map) + VAT ↔ cash box / creditors |
| Bank movements & transfers | `bankstrans`, branch cash transfers | bank ↔ cash / transfers clearing |

Manual-only entries (same review screen, typed by accountants): depreciation, accruals and
prepayments, salaries and insurance, partners' current accounts, inter-company (شركات شقيقة),
taxes, loans and interest, opening entry, adjustments.

The builder must confirm each source's exact SOFTECH fields with read-only queries against
2026 data before writing its rule, the same "verify against real documents" discipline used for
POS and A/P writers — but no write probes are needed since nothing is written to SOFTECH.

## 9. Screens (under `/finance`, desktop, Arabic RTL, calm, keyboard-friendly)

1. **دليل الحسابات** — tree of groups/accounts; per account: nature, statement line, feeding
   rules, SOFTECH check source, balance. Import from finance's trial-balance sheet.
2. **قواعد الترحيل** — posting-rule table with test-run ("what would this rule post for
   date X") before saving.
3. **مراجعة القيود** — inbox of drafts + exceptions, filters (date, branch, source, book,
   amount), side panel showing the SOFTECH source rows, change account/party on a line, approve
   one or many (`useGridKeyboard`). Manual entry form on the same screen.
4. **دفتر اليومية / كشف حساب** — approved entries; account statement with running balance,
   party filter; export to Excel in finance's layout.
5. **ميزان المراجعة** — by period, by branch, by group, with opening / movement / closing.
6. **القوائم المالية** — trading account, P&L, statement of financial position in the layout
   finance uses today; branch P&L with HQ cost allocation by sales share (allocation basis a
   setting); multi-year comparison. Excel + print.
7. **الأستاذ المساعد** — suppliers, creditors, notes payable by due month, customers, employee
   debtors, partners; links to A/P reconciliation / receivables for matching detail.
8. **مقارنة سوفتيك** — per account & month: ledger vs SOFTECH (sales, purchases, stock at cost,
   supplier balances), with drill-down to the difference.
9. **إقفال الفترة** — checklist (no open drafts/exceptions, SOFTECH comparison reviewed), post
   closing stock from SOFTECH cost valuation (excluding quarantine stores per existing rules),
   lock period.

Every screen gets in-app help (Arabic + English) per doc 28, sortable grids, and a refresh button
for SOFTECH-fed data.

## 10. Rules & controls

- Permissions server-side via RBAC module `finance` (+ new actions as needed): view, create
  (manual entries), approve, edit rules, close period. **Any accountant can approve, including
  a manual entry they typed themselves** (owner decisions 2026-11-04); the audit trail records
  creator and approver separately so self-approved entries can be filtered and reviewed. *My call, for owner to confirm:* editing posting rules and closing/
  reopening a period are limited to a finance-manager grant.
- Every create/approve/reverse/rule edit/period close goes to `apps/audit` with before/after.
- Approved entries immutable; reversal creates a mirrored entry linked to the original.
- Unique source key → a SOFTECH document can only ever produce one live entry; re-drafting a
  changed source reverses the old draft/entry and creates a new one.
- Finance-wide data: all-branch access only (consistent with security batch 5 decision B-1).

## 11. Cutover & validation (owner decision 2026-11-04)

1. Import finance COA and groups from the 2025 trial-balance sheet; finance confirms.
2. Opening entry dated 1-1-2026 from the 31-12-2025 trial balance (balanced).
3. Draft Jan–Aug 2026 from SOFTECH; manual entries for that period entered or imported from
   finance's 2026 journal.
4. Compare to the 31-08-2026 workbook account × branch (and the monthly sales/purchases sheet);
   every difference fixed in a rule or explained in writing.
5. Finance stops keying in Excel; the module is the book of record from the next open month.

## 11a. Settled during design review (designer's calls unless marked owner)

- **Cost of sales / closing stock (designer's call).** Periodic method, as finance does today:
  purchases post to purchases accounts (5100–5106); every month close posts a closing-stock
  entry at SOFTECH cost (closing stock Dr / stock-change Cr) dated month-end and auto-reversed on
  the 1st of the next month. Monthly trial balance and P&L are therefore meaningful, and
  Jan–Aug 2026 can be validated month by month as well as YTD. Year-end keeps the last
  closing-stock entry unreversed as next year's opening stock (account 5301).
- **SOFTECH document changed after approval or after close (designer's call).** The source key
  is unique among *live* entries (entry + version). A changed source in an open month: the
  approved entry is reversed and a new draft is created. In a closed month: nothing is posted
  into it — an exception is raised and, once approved, the correction is dated the first day of
  the current open month with a reference to the original. Reopening a month is a separate
  manager-only action.
- **Sep–Oct 2026 (designer's call).** Drafted from SOFTECH like Jan–Aug. Go-live = the first open
  month after Jan–Aug validation is signed off.
- **Importing finance's 2026 manual entries (designer's call).** Only lines on manual-only
  accounts (depreciation, accruals/prepayments, salaries & insurance, partners, inter-company,
  taxes, loans/interest, adjustments) are imported; lines on SOFTECH-fed accounts are dropped
  because the drafts replace them. The account list that decides this is shown to finance
  before import.
- **Suppliers/customers vs A/P reconciliation (designer's call).** The GL posts per document
  (purchase invoice, return, payment, cheque) with the party, so the GL supplier balance can be
  compared with the A/P reconciliation balance per supplier. The difference is shown on the
  period-close checklist and must be explained, but does not block close. A/P reconciliation
  remains the place for invoice↔payment matching; the GL sub-ledger screens link to it.
- **Year-end close (designer's call).** Automatic closing entry: P&L accounts → retained
  earnings (2409 «ارباح مرحله من سنوات سابقه»), consistent with finance's statements;
  partners' current accounts untouched. Next-year opening balances carry forward automatically.
- **HQ cost allocation (from finance's files).** Report-time calculation only (allocation basis
  = sales share, a setting). Finance's 2026 branch trial balance has no allocation entries, so
  nothing is posted.

## 12. Open items for the builder (not blocking design)

- Exact SOFTECH field and doccode per source type (§8) — verify on 2026 data.
- Granularity per source (per document vs per branch-day) — pick what reproduces finance's
  2026 trial balance with the fewest lines.
- Whether to extend `finance.Account` or add `GLAccount` (§7).
- Expense-code → account map: seed from SOFTECH `expenses` + finance's expense analysis sheet.
- Unprotected copies of the 2020 journals, to confirm posting patterns.

## 13. Waiting on finance (does not change the design)

- Finance's actual 2026 journal file, unprotected — source of the manual-only entries (§11a).
- Opening stock: the 2026 workbook opens 5301 at 8,739,116.86, while the 2025 workbook closes
  stock at 6,392,683.40 (5,786,789.81 after excluding expired/wash-out). Finance must confirm the
  figure for the 1-1-2026 opening entry before step 2 of §11.
