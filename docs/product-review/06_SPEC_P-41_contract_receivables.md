# 06 · SPEC P-41 — Contract receivables: who owes us, since when

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
Read-only toward SOFTECH. Feeds P-40 (13-week cash view).

**Owner input** (ledger row P-41; overrides the backlog card)
- Reuse the **customer side of the existing A/P–A/R reconciliation engine** (Rule 6). No new engine.
- Measured settlement: **4227 ≈44 days, 4288 ≈42 days** (max 60). Pattern: each month's invoices are paid at the end
  of the following month.
- **Agreed payment days per contract are a finance entry.** Each contract has agreed days in writing.
- A **wider read-only check across all 38 contracts** is still needed (step 0 below).
- Insurance claim embedding stays later (P-45). This tracker works from SOFTECH invoices and receipts only.
- Finance data is **all-branch only** (security Batch 5 decision B-1).


**Owner decisions 2026-10-31** (these override anything below that disagrees)
- **Agreed payment days count from the month end** of the invoice month. Expected date = last day of the invoice month + agreed days.
- The read-only pass across all 38 contracts is still needed. It is the step-0 probe in this spec: one SELECT-only pass, per contract, over invoices, receipts and allocations. It gives the measured days to the agreed-days entry and checks that receipts land on the contract account. It is run off-hours with the owner's OK.

**Step 0 run 2026-10-31** (owner «Run it now»; SELECT-only, 12 months, `logs/contract_receivables_probe_2026-10-31.csv`):
- 53 contract accounts (all `ptcode 10 / ptclassif 10`), sales 37.73M in 12 months; top 10 accounts = 84%.
- **Acceptance check met:** 4227 = 44.3 days, 4288 = 42.0 days (probe of 2026-10-30: ≈44 / ≈42).
- Value-weighted collection days across all accounts: **57.8**. Range 18 (4973) to 432 (4465, EGYMED 0%).
- **Link coverage:** 22 accounts have ≥ 70% of their sales linked to receipts in SOFTECH («reliable»), 75.8% of the
  value; 31 accounts are below (24.2% of the value) — open question 1 now needs the owner's answer.
- **Receivable sign confirmed:** Σ SOFTECH balance (owed convention) = −6.24M → contract receivables ≈ **6.24M**
  (estimate was 5.4M). Negative = they owe us.
- Receipts are `cheqtype 10`; 16 accounts also have a few `20` (refunds) — answers question 6.
- **Insurance TPAs are split into one account per co-pay %** (D M S 0/5/10/20/25/30/35%, EGYMED, ايجيكير, عناية مصر,
  Med Sure, كير بلاس) — the registry should group them by company (question 5).
- On-account (receipts not linked to invoices): 2.48M, of which 1.49M on 4227.
- Odd: 5009 has negative days (receipts linked to invoices dated after them — advance payments?); 4 accounts have
  under 1,000 EGP of sales in the year (4222, 4594, 4875, 5117).

## 1. Problem (measured)

- About **46% of sales are contract credit**: channel 10 (تعاقدات/آجل), 11.26M per 90 days, 38 contracts, top 4 =
  62% of contract revenue (backlog Batch 4).
- **Contract receivables are not mirrored.** `finance.APInvoice` / `finance.Payment` hold suppliers only, because the
  daily job `_run_ap_reconciliation_sync` (`apps/sync/tasks.py`) calls `sync_ap_reconciliation` with
  `party_type='supplier'` only.
- **The data is in SOFTECH** (read-only probe, 2026-10-30, 2 contracts × 120–150 days):
  - sales and returns: `stktransm` doccode 115 / 30, party = contract code (`cust_branch_code`);
  - receipts: `cheques`;
  - receipt-to-invoice links: `chequestrans`.

| Contract | Invoices (120d) | Value | Paid so far | Receipts | Collection days (value-weighted) | Max |
|---|---|---|---|---|---|---|
| 4227 | 2,621 | 3.41M | 2.50M | 1 per month, ≈0.70–0.78M | **≈44** | 60 |
| 4288 | 1,176 | 2.35M | 1.67M | 1 per month, ≈0.44–0.54M | **≈42** | 60 |

- **No due date** on any invoice (`docpaydue` empty).
- Money tied up: ≈125k EGP/day of contract sales × ≈43 days ≈ **5.4M**, the largest cash item found.
- The insurance module's collection lifecycle is unused for collection (101 claims in draft, 4 submitted, 0 payments).

**Code facts that shape the build** (read in the repo, not assumed)
- `apps/finance/recon_models.py` is already party-agnostic (`PARTY_TYPE_CHOICES` supplier/customer; doccodes
  115/30 defined). `recon_ingest.py` maps 115/30 → customer, direction `in`.
- `queries/sybase_reconciliation.py`:
  - `get_invoices('customer', …)` with no personcode filter reads **every** doccode-115 sale (all retail sales);
  - `get_vouchers('customer', …)` filters `ptcode <> '20' OR NULL`, i.e. **every non-supplier voucher**.
  Both must be limited to the contract list. Today they accept one `personcode` only.
- `get_party_balances` returns `Σcredit − Σdebit` ("owed" = supplier view). For a customer the receivable is the
  negative of this. **Sign to verify on 4227** against the SOFTECH screen.
- `recon_engine.is_receipt_voucher` treats `cheqtype '10'` (مقبوضات) as "never settles a non-return invoice". That is
  right for suppliers and **wrong for customers**, where a receipt is the normal settlement. `detect_chains` and
  `bind_all` default to `'supplier'`. **So the matching engine is not run for customers** in this spec. The tracker
  uses SOFTECH's own `chequestrans` allocations and `docvaluepay`, which the probe showed are present.
- `recon_writer.py` (gated by `AP_RECONCILE_WRITER_ENABLED`) has no party-type guard.
- `apps/sync/freshness.py` `_source_ap_reconciliation` reads the latest `ReconciliationRun` of any party type. A
  customer run would make supplier data look fresh.

## 2. Scope

**0. Read-only check across all 38 contracts (prerequisite; owner runs it).**
- New command `probe_contract_receivables` (SELECT-only, writes nothing, prints + CSV to `logs/`). It reuses the
  query functions in `sybase_reconciliation.py`.
- Per contract personcode, last 12 months:
  - `ptcode`, `ptclassifcode`;
  - invoice count and value (115), returns (30);
  - receipts count and value, split by `cheqtype`;
  - **% of invoice value covered by `chequestrans` allocations**;
  - value-weighted collection days and max (same definition as item 3);
  - receipt value with no allocation ("on account").
- Output decides, per contract, whether measured days are reliable (allocation coverage) — see open question 1.

**1. Contract registry and agreed days (finance entry).**
- Model `finance.ContractReceivableTerms`:
  - `personcode` (unique), `party` (FK `ReconParty`, nullable until first sync), `name`;
  - `agreed_days` (int, nullable), `days_from` (`invoice_date` default; other basis only if open question 2 says so);
  - `is_tracked` (bool), `source_note` (e.g. contract reference), `entered_by`, `updated_at`.
- Seed: distinct `customers.PurchaseHistory.softech_personcode` where `sales_channel='10'` in the last 365 days
  (`sales_channel` = invoice-level `stktransm.ptclassifcode`). Finance confirms the list (expected ≈38).
- Every change writes a `ReconAuditEvent` (`action='contract_terms_changed'`, `party`, before/after,
  `performed_by`). No new audit table.

**2. Customer-side sync, limited to tracked contracts.**
- `sybase_reconciliation.get_invoices / get_vouchers / get_allocations` gain an optional `personcodes` list,
  batched as bounded `IN` lists (≤400, same pattern as `get_party_balances`). When given, the customer voucher filter
  is `c.personcode IN (…)` instead of the `ptcode` rule. **Supplier calls are unchanged** (regression tests).
- `sync_ap_reconciliation` and `backfill_ap_reconciliation` gain `--contracts` (= tracked registry) and
  `--personcodes`. `--party-type customer` without either is refused (prevents a full retail-sales pull).
- Scheduler: `_run_ap_reconciliation_sync` adds a customer step after the supplier step: tracked contracts,
  120-day window, its own `ReconciliationRun(party_type='customer')`.
- It does **not** call `run_ap_matching`, `scan_ap_anomalies`, `detect_chains`, `bind_all`,
  `backfill_ap_invoice_stubs` or `sync_ap_return_links` for customers.
- One-off history load (owner runs, SELECT-only): `backfill_ap_reconciliation --party-type customer --contracts`
  over 24 months.

**3. Receivables engine** — new `apps/finance/receivables.py`, PostgreSQL only, `Decimal` throughout.
- `open_invoices(personcode=None, as_of)`: per invoice
  `open = doc_value − max(doc_value_pay, Σ native allocations)` (allocations with origin `softech`/`written`).
- Contract-level credits, not forced onto invoices:
  - unallocated customer receipts (`Payment.is_unallocated`) → «على الحساب» (on account);
  - open returns (doccode 30) → credit.
- Aging buckets by invoice age: 0–30, 31–60, 61–90, 91–180, >180 days.
- `expected_date = docdate + agreed_days`. With no agreed days: `docdate + measured_days`, flagged
  «مقاس — غير متفق عليه».
- Overdue: `open > 0.01` and `expected_date < as_of`.
- `measured_collection_days(personcode, window_days=180)`:
  `Σ(alloc.amount × (payment.voucher_date − invoice.docdate)) / Σ alloc.amount` over native allocations whose
  receipt date is in the window. Also returns max, allocation coverage %, and sample size. Rounded to 1 decimal.
- Balance check per contract: `Σopen − on account − open returns` vs the SOFTECH receivable (sign per §1). The
  difference is shown, never hidden (same idea as the حصر equation in `recon_balances.py`).
- **Interface for P-40:** `expected_contract_inflows(as_of, weeks=13)` →
  `[{week_start, personcode, base, late}]`:
  - open invoices placed on `expected_date` (base) and on `docdate + max observed days` (late);
  - overdue amounts in week 1;
  - not-yet-invoiced sales: trailing 8-week average weekly contract sales (customer `APInvoice` 115 − 30) shifted by
    the same lag.

**4. API** (`apps/finance/urls.py`, new `receivables_views.py`)

| Endpoint | Method | Permission |
|---|---|---|
| `/api/finance/receivables/summary/` | GET | `FINANCE` + all-branch |
| `/api/finance/receivables/<personcode>/invoices/?bucket=&overdue=` | GET | `FINANCE` + all-branch |
| `/api/finance/receivables/terms/` | GET / PATCH | GET `FINANCE`; PATCH `FINANCE_EDIT`; both all-branch |
| `/api/finance/receivables/export/` | GET (xlsx) | `FINANCE_EXPORT` + all-branch |
| `/api/finance/receivables/refresh/` | POST (background customer sync) | `FINANCE_EDIT` + all-branch; one at a time |

- `FINANCE*` are the existing `matrix_permission('finance', …)` objects in `recon_views.py`.
- All-branch rule: use the `core/branch_scope.py` helper from security Batch 5. It is on branch
  `claude/security-batch5-branch-scoping` (PR 17) and **not on this branch yet** — build after that merge, or the
  build is blocked on it.

**5. Screen** — new Finance hub tab `/finance/receivables` «مستحقات التعاقدات» (`FinanceHubPage.jsx` TABS).
- KPI tiles: total open, overdue value, value-weighted collection days, on account.
- One row per contract: name, open, aging buckets, agreed days (inline edit, no modal), measured days, overdue,
  SOFTECH balance, difference.
- Row expands to its open invoices and recent receipts.
- `DataFreshnessBar domains={['ar_contracts']}` with the refresh button (permission-checked, background,
  ProgressBar), per the refresh-button convention.
- `/reconciliation` keeps its supplier/customer toggle. Its help gets one line: matching proposals are not run for
  customers.

**6. Freshness** (`apps/sync/freshness.py`)
- New domain `ar_contracts` («مستحقات التعاقدات», `source`, cadence 1440) reading
  `ReconciliationRun(party_type='customer')`.
- `_source_ap_reconciliation` is limited to supplier runs (`party_type__in=['supplier', '']`).

**7. Writer guard.** `recon_writer` refuses any allocation whose party is a customer (`ReconWriteError`), whatever
the flag. Nothing in this spec creates customer allocations, but the guard makes it impossible.

**8. Help.** `apps/help/content/finance.py`:
- new screen `finance.receivables` (routes `['/finance/receivables']`, Arabic + English, `updated`);
- update `finance.reconciliation` (customer toggle note) and bump its `updated`.

**Migration:** `finance/0017_contract_receivable_terms` (new model only; no change to mirror tables).

## 3. Acceptance criteria

- Step 0 report produced for all tracked contracts. The owner has accepted the reliability call per contract.
- For 4227 and 4288 over the probe window, measured days are within ±1 day of the probe (≈44 / ≈42).
- A customer sync never reads untracked personcodes (query-builder test). `--party-type customer` with no contract
  list exits with an error.
- Supplier sync output is identical before and after the query change (regression test on the existing ingest
  fixtures).
- A customer run does not change the `ap_reconciliation` freshness domain; `ar_contracts` reports it (test).
- `recon_writer` raises on a customer-party allocation (test).
- Branch-restricted user → 403 on every receivables endpoint; a user without the `finance` grant → 403 (tests).
- Every terms change writes one `ReconAuditEvent` with before/after and user (test).
- `test_help.py` passes.

**Tests** (new or extended)

| File | Proves |
|---|---|
| `apps/tests/test_receivables.py` | aging buckets; hand-computed value-weighted days; expected date and overdue; measured-days fallback flag; on-account and returns at contract level; balance sign; `expected_contract_inflows` week placement (base/late, overdue → week 1) |
| `apps/tests/test_receivables_api.py` | permissions (finance grant, all-branch, edit), audit on terms change, export |
| `apps/tests/test_reconciliation_ingest.py` (+) | batched `personcodes` IN lists; supplier path unchanged |
| `apps/tests/test_reconciliation_writer.py` (+) | customer allocation refused |
| `apps/tests/test_sync_freshness.py` (+) | `ar_contracts` domain; supplier domain ignores customer runs |
| `apps/tests/test_help.py` | new route has help |

## 4. Measurement

- Collection days per contract. Baseline: 4227 ≈44, 4288 ≈42; the others from step 0; owner estimate 45–75.
- Overdue value (once agreed days are entered).
- Total open contract receivables. Baseline estimate ≈5.4M.
- Share of contracts with agreed days entered (target: all tracked contracts).

## Out of scope

- Any SOFTECH write: `docpaydue`, receipts, `chequestrans` allocations. Stop-and-ask.
- The matching engine on the customer side (proposals, chains, bindings, anomalies).
- Insurance claim embedding, deductions by reason and branch (P-45, deferred).
- Reminders or messages to contract companies; interest on late payment.
- A weekly overdue digest (can be added later through the P-55 routing setting).

## Open questions / owner inputs

1. **Allocation coverage.** If step 0 shows a contract whose receipts are mostly not linked in `chequestrans`,
   what do we use for its measured days? Proposal: oldest-invoice-first (FIFO) by receipt date, clearly labelled.
   Owner decides.
2. **Basis of agreed days:** from invoice date, from the end of the invoice month, or from claim delivery?
3. **Scope of accounts:** contracts only (channel 10), or also insurance accounts (channel 15, `InsuranceContract`
   default `'15,10'`)?
4. **Patient co-pay** (e.g. 4222 at 20%): does the contract invoice's `docvalue` include the co-pay paid at the till?
   To verify read-only on one 4222 invoice. This matters for P-40, so cash sales and contract receivables are not
   counted twice.
5. **Parent / child accounts** (`InsuranceParentClient`): do receipts arrive on the parent personcode while invoices
   sit on children? To verify in step 0. If yes, the registry groups children under the parent.
6. **Receipt type:** are all contract receipts `cheqtype '10'`? Are refunds `'20'`? To verify in step 0.
7. **Who are the four finance users?** They need the `finance` grant and all-branch scope.

## Stop-and-ask

- Any write to SOFTECH, including the gated `recon_writer` or `docpaydue`.
- Any change to the supplier sync's behaviour or output (the query functions are shared).
- Turning on matching proposals for customers.
- Running the step-0 probe or the history backfill on production: owner runs them (SELECT-only).
