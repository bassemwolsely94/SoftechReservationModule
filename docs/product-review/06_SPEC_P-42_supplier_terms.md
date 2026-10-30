# 06 · SPEC P-42 — Supplier terms by item category + early-pay opportunities

**Status:** specification (approved for spec 2026-10-30). **Build:** not yet authorised.
Read-only toward SOFTECH. Feeds P-40 (13-week cash view).

**Owner input** (ledger row P-42 and the 2026-10-30 answers; overrides the backlog card)
- Credit days vary **per supplier × item category**: **local**, **imported**, **non-discounted** (mostly local items
  without extra discount; a little more credit than local; not handled like imported).
- Cheques are written **per category total**.
- Suppliers are **paid on time**. The "paid early" flag is dropped.
- Early payment earns a discount or bonus, but the cash constraint prevents it now. Show the opportunity so the
  best-return early payments are chosen first when cash allows.
- The residue clean-up list (open items more than 1 year old) stays.
- Finance data is all-branch only (security Batch 5, B-1).

## 1. Problem (measured)

- **No due dates.** 0 of 6,919 supplier invoices in the last 90 days carry `docpaydue`. Credit terms are unknown to
  the system. `finance.APInvoice.due_date` exists but is empty.
- Supplier payments run at ≈4.5–6.5M EGP per month (last 6 months).
- **Open purchase-invoice value (doc 10) by age:** 0–30d 5.59M · 31–60d 2.89M · 61–90d 0.35M · 91–180d 1.33M ·
  181–365d 2.38M · **>1 year 10.60M**. Of the >1-year bucket, 5.36M is service-vendor and ≈1.67M patient-repurchase
  accounts. This looks like reconciliation residue.
- **Most of the 38.3M supplier balance is not real payables:** 1268 gift coupons 12.5M; 3068 general supplier /
  patient buy-back 9.05M; 4470–4472 replacement entitlements ≈4.7M. Real distributors are smaller (Pharma Overseas
  3.28M, Ramco 2.27M).
- **Allocation coverage is thin.** On supplier 4471's full history, 92% of payments were never linked to an invoice
  in SOFTECH (doc 23). Any "paid vs due" measure must show its coverage.

**Code facts that shape the build** (read in the repo)
- Invoice header and open amount: `finance.APInvoice` + `recon_reports.unpaid_invoices()`. That function already nets
  SOFTECH payments, approved allocations and linked open returns.
- Invoice lines: `procurement.PurchaseLine` (`branch_code`, `supplier_code`, `doc_number`, `doc_date`, `doccode`,
  `item_code`, `item` FK, `net_value`, `is_foc`). It has **no discount % columns**.
  `recon_lines.invoice_lines()` reads `pharmacydiscp` live, one invoice at a time only.
- Local vs imported: `catalog.Item.is_imported` (`itemsorigin.importedorigin='1'`). This is the same origin rule the
  insurance classifier uses (`apps/insurance/classifier.py`).
- Excluded accounts already exist in pieces:
  - SystemSetting `analytics_excluded_supplier_codes` (default `1268`);
  - `apps/replacement/config.py` (4469–4472);
  - `apps/purchasing/phantom.py` (3068 and others).

## 2. Scope

**0. Definitions from finance (prerequisite).**
- The rule for **non-discounted** (open question 1).
- Terms for the **top 10 real suppliers by value** first; the rest later.

**1. Terms table (finance entry).** Model `finance.SupplierTerm`:
- `party` (FK `ReconParty`, supplier), `category` (`local` / `imported` / `non_discounted`);
- `credit_days` (int);
- `early_pay_days` (int, nullable), `early_pay_discount_pct` (decimal 5,2, nullable), `early_pay_bonus_note` (text);
- `effective_from` (date), `effective_to` (nullable), `entered_by`, `updated_at`;
- unique (`party`, `category`, `effective_from`).

Every change writes a `ReconAuditEvent` (`action='supplier_terms_changed'`, `party`, before/after,
`performed_by`).

**2. Account class.** New SystemSetting `finance_internal_supplier_codes`, CSV. Default: `1268,3068,4469,4470,4471,4472`
(the internal and virtual accounts in the measured picture); finance confirms. These accounts are shown
separately everywhere and never mixed with real supplier debt.

**3. Category slices per invoice** — new `apps/finance/supplier_terms.py` + model `finance.APInvoiceSlice`:
- Fields: `invoice` FK, `category`, `line_value`, `share`, `open_amount`, `due_date` (nullable), `term` FK
  (nullable), `rules_version`, `computed_at`; unique (`invoice`, `category`).
- Line category:
  - `imported` if `item.is_imported`;
  - `non_discounted` per the confirmed rule (off until defined);
  - otherwise `local`;
  - no catalog item → `unclassified`.
- Lines: `PurchaseLine` with the same (`branch_code`, `supplier_code`, `doc_number`, `doc_date`, `doccode='10'`).
  FOC lines (zero value) carry no weight.
- `share = category line value / Σ line value`. `open_amount = invoice open × share`, rounded to 0.01, with the
  remainder added to the largest slice, so **Σ slices = invoice open exactly**.
- An invoice with no lines gets one `unclassified` slice.
- `due_date = docdate + credit_days` of the term in force on `docdate`. **No term → no due date** (the "no terms"
  bucket). Never guessed.
- Returns (120) are not sliced. They already reduce `open` through `unpaid_invoices()`.
- Recomputed after the nightly supplier step of `_run_ap_reconciliation_sync`, and for one supplier when its terms
  change. The run is idempotent.

**4. Payment calendar** (real suppliers): by week × supplier × category:
- due;
- overdue (due < today, still open);
- no terms;
- unclassified.

Internal accounts get their own table. Excel export.

**5. Paid on time (measured, advisory).**
- Scope: invoices fully settled through native allocations (origin `softech` / `written`).
- Paid date = the latest allocated payment's `voucher_date`. Days vs terms = paid date − slice due date.
- Report per supplier × category: value-weighted days vs terms, and **allocation coverage %** (allocated value ÷
  paid value). Unlinked payments are excluded and the coverage is shown next to every figure.

**6. Early-pay opportunities.** For open slices with `early_pay_discount_pct` and `early_pay_days`:
- `deadline = docdate + early_pay_days`; listed while `deadline ≥ today`;
- `discount_value = open_amount × pct / 100`;
- `days_gained = due_date − deadline` (paying on the deadline instead of the due date; minimum 1). A slice with no
  due date is listed but not ranked;
- `annualised_return = pct / (100 − pct) × 365 / days_gained`;
- ranked by `annualised_return`, then `discount_value`;
- bonus-only terms are listed with their note and **not valued** (open question 3).

Foregone: an opportunity whose deadline passed while the slice was still open → `foregone_value`.

**7. Residue list.**
- Open items more than 365 days old, by account class: real / internal / service-vendor / patient-repurchase
  (open question 5).
- Each item shows the existing match-proposal fields from `unpaid_invoices()`.
- Read-only: finance closes them natively in SOFTECH.

**8. Interface for P-40.**
- `supplier_outflows(as_of, weeks=13)` → per week: `due_real`, `overdue_real`, `no_terms_real`, `internal`, each
  per supplier.
- `early_pay_by_week(as_of, weeks=13)` → per week: `available_value`, `foregone_value`.

**9. API** (`apps/finance/urls.py`, new `supplier_terms_views.py`)

| Endpoint | Method | Permission |
|---|---|---|
| `/api/finance/supplier-terms/` | GET / POST / PATCH | GET `FINANCE`; write `FINANCE_EDIT`; all-branch |
| `/api/finance/supplier-terms/calendar/?from=&weeks=` | GET | `FINANCE` + all-branch |
| `/api/finance/supplier-terms/on-time/` | GET | `FINANCE` + all-branch |
| `/api/finance/supplier-terms/early-pay/` | GET | `FINANCE` + all-branch |
| `/api/finance/supplier-terms/residue/` | GET | `FINANCE` + all-branch |
| `/api/finance/supplier-terms/export/?sheet=` | GET (xlsx) | `FINANCE_EXPORT` + all-branch |
| `/api/finance/supplier-terms/recompute/` | POST (background) | `FINANCE_EDIT` + all-branch; one at a time |

The all-branch check uses `core/branch_scope.py` from security Batch 5 (PR 17, not on this branch yet).

**10. Screen** — new Finance hub tab `/finance/supplier-terms` «شروط الموردين», with inner tabs and `useHelpTab(tab)`:
- **الشروط:** supplier × 3 category columns, inline edit with `useNumberInputGuards`, a "top 10 by value" filter,
  and a coverage KPI (% of open real payables with terms).
- **تقويم السداد**, **فرص الدفع المبكر**, **السداد في الموعد**, **البواقي القديمة**.
- `DataFreshnessBar domains={['ap_reconciliation','purchases']}` (`purchases` = the procurement engine that fills
  `PurchaseLine`), plus a recompute button (ProgressBar).
- Supplier names via the existing labels. No bare branch codes in exports (`BL` / branch labels).

**11. Help.** `apps/help/content/finance.py`: new screen `finance.supplier_terms` (route
`['/finance/supplier-terms']`, one section per inner tab, Arabic + English, `updated`).

**Migration:** `finance/0018_supplier_terms` (`SupplierTerm`, `APInvoiceSlice`; new tables only).

## 3. Acceptance criteria

- Σ slices = invoice open to the piastre for every invoice, including rounding cases (property test over fixtures).
- Effective-dated terms: an invoice dated before a terms change uses the old days (test).
- No term → no due date and the slice is counted in "no terms", never in a week (test).
- Internal accounts never appear in the real calendar totals (test).
- Hand-computed early-pay example: discount value and annualised return match to 0.01 (test).
- Paid-on-time figures always come with a coverage % (API contract test).
- Branch-restricted user and users without the `finance` grant → 403; each terms write → 1 audit event (tests).
- `test_help.py` passes.

**Tests**

| File | Proves |
|---|---|
| `apps/tests/test_supplier_terms.py` | category per line; slice shares and exact rounding; due dates; effective dating; no-term and unclassified buckets; internal split; idempotent recompute; on-time calc with coverage; early-pay maths; foregone; `supplier_outflows` / `early_pay_by_week` week placement |
| `apps/tests/test_supplier_terms_api.py` | permissions, audit, export sheets |
| `apps/tests/test_help.py` | new route and tabs have help |

## 4. Measurement

- Coverage: % of open real payables with terms. Target: top 10 suppliers in week 1 of use.
- Average days paid vs terms, per supplier × category (with coverage %).
- Early-pay opportunity value available and foregone per month. Baseline: unknown until terms are entered.
- Residue value more than 1 year old. Baseline 10.60M; target: down.

## Out of scope

- Writing `docpaydue` or anything else to SOFTECH. Supplier payment write-back is doc 23 Phase G (gated, blocked by
  the encrypted trigger). Stop-and-ask.
- Changing purchase pricing or discount maths (the `pricing.compute_line` issue is a separate stop-and-confirm item).
- Supplier messaging or negotiation tools.
- Auto-choosing which invoices to pay. The list is advisory; finance decides.

## Open questions / owner inputs

1. **Non-discounted rule:** how is a line identified? Candidates to verify read-only: extra discount (`additionaldiscp`)
   = 0 on the purchase line; an item classification; a supplier price list. `PurchaseLine` has no discount column
   today. If a line-level field is needed, adding it to the procurement sync is a separate, small change.
2. **Credit days from what date?** Invoice date (assumed), delivery, or month end?
3. **Early-pay terms:** is the discount on the invoice value with or without VAT? How should a bonus (free goods) be
   valued, if at all?
4. **Internal account list:** confirm `1268, 3068, 4469–4472`. Anything else?
5. **Service-vendor and patient-repurchase accounts:** which `ptclassifcode` (or list) identifies them for the
   residue split? To verify read-only.
6. **Line coverage:** `PurchaseLine` history window, and whether Σ line `net_value` matches `APInvoice.doc_value`
   (VAT). To verify on 20 invoices before trusting shares.

## Stop-and-ask

- Any SOFTECH write (`docpaydue`, `cheques`, `chequestrans`, `stktransm`).
- Any change to the procurement sync that adds columns (the open-question-1 field) — confirm first.
- Using terms to change payment approvals or the reconciliation writer.
