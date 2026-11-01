# 03 — SOFTECH / Data Opportunity Map

Availability classes:
- **A** — available and verified.
- **B** — available, but needs mapping or quality validation.
- **C** — requires new data capture.
- **D** — currently unavailable.

Only mappings already verified in code, prior investigations, or project memory are marked A. **No new SOFTECH
queries were run for this review.**

## Analytical cautions (apply to every proposal)
- **Sales understate demand.** Sales are capped by availability. Use `pos_cancel` (selected-not-sold), demand records
  and shortage observations as separate demand evidence.
- **Transfers (125/25) are not sales.** The ISR legs A→HQ→B also reach SOFTECH.
- **Returns and reversals must net out.** Doc 30 = sales return. Gift-coupon and replacement legs have their own
  semantics (doc 25).
- **Cost.** `PurchaseHistoryLine.cost_at_sale` is the historical cost. `Item.cost_price` is the current cost, and its
  label is inconsistent: buy vs cost price (`catalog/models.py:76` vs `sync/tasks.py:727`).
- **Free quantity.** Real FOC is a separate `stktrans` line with `pharmacydiscp=100` (memory: procurement
  intelligence). Bonus quantity is **not stored** on sales lines.
- **VAT.** Sale prices are VAT-inclusive; cost is pre-VAT on 14%-VAT items (memory: purchasing OCR column engine;
  stock audit). Any margin must align the two.
- **Mirror vs physical.** The mirror (`stkbal`) can differ from physical stock. Stock count and stock audit exist
  because of this.
- **Docnumbers are per (branch, doctype).** Never join on a bare docnumber (memory: SOFTECH docnumber collisions).

## Data needed by Batch-1 proposals

| Need | Business meaning | Source (verified) | Keys | Freshness | Coverage | Quality issues | Class |
|---|---|---|---|---|---|---|---|
| Customer sales lines | Did this customer buy this item after the request? | `customers.PurchaseHistory` + `PurchaseHistoryLine` (doc_code 115 sale, 30 return) | customer (PIC→`softech_pic`, else `ACCT-<personcode>` placeholder), item, branch, invoice_date | Fast sales sync; [M] latest 2026-10-27 | 2024-07-31 → now; 585k sale docs | Walk-in sales go to placeholder accounts, so matching works only for identified customers. Customer link was repaired 2026-10 (memory: sales customer link fix) | **A** for named customers; **B** for phone-only requests |
| Request records | What was promised to whom | `demand.DemandItem`, `reservations.Reservation(+Line)`, `followups.FollowUpTask` | customer FK / phone, item FK | Real-time | Small volumes [M] | Reservation stock check uses the header item only; the request phone may differ from the SOFTECH customer phone | **A** |
| Legacy ERP mirror | (to be retired) | `erp.ERPTransaction` | — | **Stale since 2026-04-30 [M]** | Jan–Apr 2026 | Sync unscheduled | **D** (do not use) |
| In-transit transfers | Which 125 issues lack a 25 receipt | `transits.InTransitTransfer` (125↔25 via `docnumber2`) | branch + doctype + docnumber + date | 15 min | 6,380 docs | 1,021 still in transit, 776 ≥14 days [M]. Real delay vs linking failure is **unverified** | **B** |
| Notifications | Alert volume / read | `notifications.Notification` | recipient, type, dedup_key | Real-time | 2026-05 → now | 0% read in 30d. Mark-read APIs exist (`notifications/views.py:285,316,458`), so this is behaviour, not a missing feature | **A** |
| Screen usage | Who uses which screen | none | — | — | — | No page-view telemetry. `last_login` not updated by JWT | **C** |
| Item safety class | Rx/OTC, sensitive classes for exclusions | `catalog/safety.py` flags (stop-sale, return-only, no-sale class, fridge, archived); enrichment `rx_otc` | item | Hourly item sync | All items | **No reliable controlled-substance column**. `rx_otc` partly AI-derived (S4). `name_scientific` dirty | **B** — needs a pharmacist-maintained class list |
| Customer allergies / conditions | Per-customer safety filter | `customers` health profile + `_get_unsafe_items_for_customer` (`recommendations/engine.py:386`) | customer, ingredient → item map (`chronic.ItemIngredientMap` 337 rows) | Staff-entered | Sparse | Ingredient-to-item map covers few items; composition index 18.5k is pharmacist-approved only | **B** |
| Marketing consent | Lawful basis + channel + opt-out | none at customer level; only `DemandItem.contact_opt_out` and `RefillReminderOptOut` | customer | — | — | Must be captured | **C** |

## Verified during Batch 2 (2026-10-30, read-only)
- **Branch batches are trustworthy.** `StockExpiryBalance` batch qty equals the `ItemStock` qty for 87–95% of items
  per branch (130: 3,943/4,192; 170: 3,608/4,369).
- **HQ store 110** has 1.61M EGP of batches (all more than 2 years expired). It has **no movement in the 12-month
  stock ledger**, is **absent from `ItemStock`**, and every one of its items shows zero `stkbal` stock in the mirrored
  stores. Class B: meaning unconfirmed; likely book residue.
- **Quarantine 102/103/105** is active: doc 120 (≈206k), 25, 40 and 140 movements in 12 months.
- Chain-wide doc 120 (purchase return) is ≈1.95M EGP in 12 months; doc 150 ≈245k; doc 50 ≈283k. Ledger =
  `stock_audit.StockLedgerLine`, HQ mirror, 2025-10-28 → 2026-10-28.
- `ItemDemandMetrics.last_sale_date` is null for 7,947 stocked item×branch rows (2.58M). It means "no sale in the
  engine's window", not proven "never". Stock age needs `stkbal.opendate` or the ledger (class B).
- `catalog.Item.strategic_hold` exists; 0 items are flagged.

## Verified during Batch 3 (2026-10-30, read-only)
- **The stock ledger covers all branches** (`branchcode` 100/130/140/150/160/170). Lines per branch per year:
  97k–319k. `newqty` (balance after each transaction) makes **measured stockout periods** possible.
  - Class B: verify whether `newqty` is per store or per branch, on samples.
  - At branch 160, 412 of 712 moving A items hit 0 within 90 days.
- **Engine lost sales are inferred** ("expected − actual sale days", `lost_sales_engine.py`), not observed.
- **`pos_cancel`** (`PosCancelDaily.lost_value` ≈3.4–5.2M EGP/month) is mostly cashier corrections. It is **not**
  lost sales without reason codes. Class B/C.
- **`invoices.PurchaseOrder` = 0 rows.** SOFTECH `stockordersm/stockorders` (`suppcode`, `poclosed`) exist; whether
  they are used for supplier orders is unknown (probe needed; class B).
- **Supplier codes:** Pharma Overseas = 565 (≈40.5M EGP/yr), Ramco = 30 (≈16.9M), Ibn Sina = 260 (≈4.8M),
  Egy Drug Sherif = 786 (≈3.2M). Source: `procurement.SupplierProfile.value_365d`.

## Data for later batches (initial classification)

| Need | Source | Class | Note |
|---|---|---|---|
| Expiry exposure by batch × branch | `batches.StockExpiryBalance` (`stkbalexpiry`, all nodes, daily 05:30) | A | Single expiry truth candidate |
| Realised disposal / supplier return | `stock_audit.StockLedgerLine` (HQ `stktrans` mirror, all doccodes, 2-hourly) — doc 120 purchase return; 150 adjustment-out per stockcount code | B | Doccode semantics for disposal vs return need confirming |
| Lost sales at POS | `pos_orders.PosCancelDaily` (62.7k rows) from `pos_cancel` (selected-not-sold log) | B | Memory: lost-sale/cashier audit source. Reasons not coded |
| Effective acquisition cost incl. FOC | `procurement.PurchaseLine` (doc 10/120) + FOC lines `pharmacydiscp=100` | A/B | Verified formula: cost = itemsaleprice_tax×(1−d1)×(1−d2) (memory) |
| Supplier A/P, payments, allocations | `finance` recon mirror (`cheques`, `chequestrans`, `stktransm.docvaluepay`) | A | 97.8% shadow match (memory) |
| Margin at sale | `PurchaseHistoryLine.cost_at_sale` | B | VAT alignment to confirm |
| Delivery time order→delivered | `delivery.DeliveryOrder` (from `piccrmorders`) + status logs | B | `sla_due_at` never written. Order-created timestamp semantics to confirm |
| Refill adherence (PDC) | PurchaseHistoryLine for chronic items × pack days | B | Days-per-pack not in SOFTECH; needs a pharmacist-maintained assumption table |
| Cold-chain readings | none (QA template has a "fridge" yes/no) | C | |
| Staff competency / training | `help.HelpQuizAttempt` (system-usage quizzes only) | C for pharmacy knowledge | |
| Track-and-trace pack IDs (EDA 475/2025) | none | D | Depends on EDA guideline + SOFTECH vendor roadmap |
