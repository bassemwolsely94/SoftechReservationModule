# SOFTECH Purchase/Return Save-Time Validations — Catalog & Replication

**Discovered:** 2026-07-03 (read-only probes + captured client session + master-data schemas).
**PROVEN (2026-07-03, rollback probe):** SofTech's DB does **NOT** enforce these business rules. A purchase
line for item 97873 — `itemtrans3=3` (purchase-blocked) **and** discontinued **and** archived — **inserted
cleanly** (`ok=True`, stock/cost/credit processed) via the real writer path. The `tr_stktrans`/
`sp_expirytrans` triggers only enforce stock/cost integrity (the `newqty` running balance), never
`itemtrans3`/`itemnomoreuse`/`itemarchive`. ⇒ **Our `validations.py` is the ONLY enforcement of the business
rules for the writeback path** — errors block the push with no override, so a blocked item can never be
pushed through our module (whereas a raw insert would let SofTech silently receive it).

**Key finding:** the business-rule validations are enforced **client-side (PowerBuilder app)**, NOT by
DB procedures — no readable proc references `personcredit`/`creditlimit`/price caps. SofTech's encrypted
triggers (`tr_stktrans`→`sp_expirytrans`) only enforce **stock/cost integrity** (newqty vs stkbal, batch
expiry). ⇒ To be a safe drop-in, **our module must replicate the business rules itself** by reading the
same master data the client reads before saving. Implemented in `apps/invoices/validations.py`, run before
every push (errors block; warnings are surfaced/overridable).

## Master-data sources (confirmed columns)
| Concern | Table.column |
|---|---|
| **Supplier transaction permission** (كارت الصنف → التعامل في الصنف → الموردين) | **`items.itemtrans3`**: `0`=شراء+ارتجاع, `1`=شراء فقط, `2`=ارتجاع فقط, `3`=إيقاف كامل. Purchase allowed only for `0/1`; return allowed only for `0/2`. (`itemtrans1`=branches, `itemtrans2`=customers.) 12,905 items are `3` (fully stopped), 2 are `2` (return-only) |
| Item discontinued | `items.itemnomoreuse` (`'1'` = no longer used) — 13,630 items |
| Item archived | `items.itemarchive` (`1` = archived) — 12,807 items |
| Expiry required | `items.itemexpiry` (`'1'` = a batch expiry date is mandatory) |
| Item cost / public price / tax | `items.itemcostprice`, `items.itemsaleprice`, `items.itemsaleprice_tax`, `items.itemsalestaxp` |
| No-sale classification | `items.itemnosaleclassif` |
| Allowed supplier↔item link + per-supplier price/discount | `itemssuppliers(itemcode, suppcode, main_supp, suppitemcode, pharmacydiscp, additionaldiscp, itemcostprice, itemsaleprice)` |
| Supplier balance (A/P we owe) | `personsdata.personcredit` |
| **Supplier credit limit** | `personsdata.personmaxbal` (sentinel ≥ 1e10 = effectively unlimited) |
| Supplier credit terms (days) | `personsdata.personcreditdays` |
| Config toggles / thresholds | `cfarmasetup(cfsetupcode, cfsetupvalue, cfsetuptext)` — numeric codes (client-mapped; exact code→rule map lives in the PB app, so thresholds are exposed as our settings) |

---

## The validation catalog

### ERRORS — block the push
| # | Code | Rule | Source | Applies |
|---|---|---|---|---|
| E1 | `item_unmatched` | line has no catalog item (itemcode unknown) | PG `InvoiceLine.item` | all |
| E2 | `item_discontinued` | `items.itemnomoreuse = '1'` | items | all |
| E2b | `item_purchase_blocked` | `items.itemtrans3 IN (2,3)` — ارتجاع فقط / إيقاف كامل (item not allowed to be purchased from suppliers) | items | purchase |
| E2c | `item_return_blocked` | `items.itemtrans3 IN (1,3)` — شراء فقط / إيقاف كامل (item not allowed to be returned to suppliers) | items | return |
| E3 | `item_archived` | `items.itemarchive = 1` | items | all |
| E4 | `qty_invalid` | `transqty <= 0` | PG | all |
| E5 | `price_invalid` | net cost `transprice <= 0` (or public price 0) | PG/items | all |
| E6 | `expiry_required` | `items.itemexpiry='1'` and the line has no (valid) expiry date | items + PG | all |
| E7 | `supplier_unlinked` | `VendorProfile.softech_personcode` empty (supplier not resolved) | PG | all |
| E8 | `credit_limit_exceeded` | `personcredit + doc_value > personmaxbal` (only when `personmaxbal` is a real limit, i.e. < the unlimited sentinel) | personsdata | purchase |
| E9 | `duplicate_invoice` | supplier already has a purchase with this `docnumber2` (SofTech dup-guard) | stktransm | purchase |
| E10 | `return_exceeds_received` | Σ return qty for an item > qty received on the original purchase (`r_docnumber`), across prior returns | stktrans (doccode 10/120) | return |
| E11 | `original_missing` | the original purchase (`return_of_docnumber`) does not exist in SOFTECH | stktransm | return |

### WARNINGS — allow but flag (require explicit override to push)
| # | Code | Rule | Source |
|---|---|---|---|
| W1 | `cost_gt_public` | net cost `transprice` > `items.itemsaleprice` (public sell price) — you'd sell at a loss | items |
| W2 | `price_spike` | cost > `items.itemcostprice × (1 + INVOICE_MAX_COST_INCREASE_PCT/100)` (default 25%) | items + setting |
| W3 | `price_drop` | cost < `items.itemcostprice × (1 − INVOICE_MAX_COST_DECREASE_PCT/100)` (default 40%) — suspicious | items + setting |
| W4 | `supplier_not_listed` | no `itemssuppliers` row for (itemcode, suppcode) — buying from an unlisted supplier | itemssuppliers |
| W5 | `tax_mismatch` | line `vat_pct` ≠ `items.itemsalestaxp` | items |
| W6 | `discount_high` | effective `pharmacydiscp` > 50% (unusually large) | PG |
| W7 | `total_mismatch` | Σ line totals ≠ OCR `declared_total` (>2%) | PG (already in anomalies.py) |

### Config (settings / .env) — thresholds that map to SofTech's cfarmasetup codes
```
INVOICE_MAX_COST_INCREASE_PCT = 25     # W2 spike threshold
INVOICE_MAX_COST_DECREASE_PCT = 40     # W3 drop threshold
INVOICE_HIGH_DISCOUNT_PCT     = 50     # W6
INVOICE_ENFORCE_CREDIT_LIMIT  = True   # E8 on/off
INVOICE_ENFORCE_SUPPLIER_LINK = False  # make W4 an error instead of a warning
```

---

## How it runs
`validations.validate_invoice(invoice, *, live=True)` opens ONE branch connection, batch-reads `items`
(flags/prices/tax/expiry) for all line itemcodes, the supplier `personsdata` row, and the `itemssuppliers`
links, then returns `{ok, errors:[…], warnings:[…]}` where each entry is `{code, severity, line_id, message}`.
- `push_final` calls it first; **any error → the push is refused** (status stays, `erp_error` set) and the
  errors are returned to the UI.
- **Warnings do not block**, but the UI shows them in the preview and the user must tick "تجاهل التحذيرات"
  (pass `force=true`) to push despite them.
- A read-only `POST /invoices/{id}/validate/` action returns the same structure for the preview modal.
