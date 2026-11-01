# 06 · SPEC P-58 — EDA track-and-trace foundation (dormant)

**Status:** specification. New proposal from the owner (2026-10-30):

> "Put the foundation in development on both purchasing and sales but leave it not used for now."

EDA track-and-trace is live at supplier level, not yet at pharmacy level. **Build:** foundation authorised in
principle by the owner. Confirm the start with the wave-0 build approval.

## 1. What is known (and what is not)

**Verified** (EDA Decree 475/2025, full text read; register 04 §1)
- A unified national track-and-trace system follows packs to dispensing or destruction.
- **Registered pharmacies must provide readers and software and link to the system (Art. 4).**
- Imported products from 1/2/2026; local products from 1/8/2026; phased by dosage form or group.

**Not verified**
- The pharmacy-level reporting interface, message format, timing and which events must be reported. These are in
  guideline 804/2025, which has not been read.
- SOFTECH's plans.

**Therefore the foundation captures and stores pack identity, and reports nothing.** No EDA API is invented.

**Pack identity standard.** Serialised medicine packs carry a **GS1 DataMatrix** with Application Identifiers:

| AI | Meaning |
|---|---|
| (01) | GTIN |
| (21) | serial |
| (10) | batch/lot |
| (17) | expiry YYMMDD |

The parser must follow the GS1 General Specifications, including the FNC1/GS separator for variable-length fields.
**Confirm against 804/2025 before activation.**

## 2. Scope (dormant)

**1. Setting.** `TRACK_TRACE_ENABLED` (default **False**). When False, nothing changes for any user.

**2. Parser.** `apps/catalog/gs1.py`, `parse_gs1(raw) -> {gtin, serial, batch, expiry, raw}`:
- pure and deterministic;
- validates the GTIN check digit;
- handles both `]d2`-prefixed and plain scans, and the GS (0x1D) separator.

**3. Models** (new app `apps/trace`, to keep it isolated):

`PackCode`
| Field | Type |
|---|---|
| gtin | char 14, indexed |
| serial | char 20 |
| batch | char 20 |
| expiry | date |
| item | FK catalog.Item, nullable; resolved via GTIN ↔ `ItemBarcode.barcode` (an EAN-13 matches GTIN-14 with a leading 0) |
| status | `received | in_stock | sold | returned | destroyed | unknown` |
| first_seen_at | datetime |
| branch | FK |

Unique on (gtin, serial).

`PackEvent`
| Field | Type |
|---|---|
| pack | FK |
| event | `receive | sell | return_in | return_to_supplier | destroy | transfer_out | transfer_in` |
| doc_type | char |
| doc_ref | e.g. invoice id, POS order id, transfer doc |
| branch | FK |
| staff | FK |
| at | datetime |
| source | `scan | manual` |
| raw | the raw scan string |

- Append-only. Rule 8: auditable.
- `reported_to_eda_at` (null) and `eda_response` (JSON, blank) are **reserved for later**.

**4. Purchasing hook.** On the supplier invoice line (`invoices.InvoiceLine`, which already has `batch_number`,
`expiry_date`) and the receiving grid:
- an optional "scan pack codes" field, visible only when `TRACK_TRACE_ENABLED`;
- it records a `PackEvent(receive)` per scanned pack.
- **No effect on SOFTECH posting.**

**5. Sales hook.** On the POS order line (`pos_orders.SoftechSalesOrderLine`, which already has `barcode`,
`item_expiry`):
- when enabled, a scan that parses as GS1 DataMatrix stores a `PackEvent(sell)` linked to the line;
- the item still comes from the GTIN, exactly as the barcode search works today.
- **No effect on totals, pricing or SOFTECH writes** (Rules 2, 3).

**6. Expiry and returns.**
- Disposal (`batches.ExpiryDisposalRecord`) and the return-window flow (P-29) can attach pack events
  (`destroy`, `return_to_supplier`).
- A hook only; dormant.

**7. No UI is shown when disabled.** One admin-only diagnostic: `POST /api/trace/parse/` (paste a scan → parsed
fields + matched item) for testing scanners.

## 3. Acceptance criteria

- `parse_gs1` passes a table of GS1 test vectors:
  - fixed-length AIs;
  - a variable-length (21)/(10) with a GS separator;
  - a bad check digit, which is rejected;
  - an expiry with day 00, meaning end of month per GS1.
- With `TRACK_TRACE_ENABLED=False`:
  - the invoice and POS APIs and screens behave identically;
  - the existing invoice and POS test suites pass unchanged;
  - no PackEvent is created.
- With it enabled (test): scanning on receive and on sale creates one `PackCode` and two events. A duplicate
  (gtin, serial) on a second receive is flagged, not duplicated.
- No SOFTECH write path is touched. Static guard: the existing SOFTECH write manifest test stays green.
- Help text exists (Arabic + English) but is shown only when enabled.

## 4. Before activation (later decision)

- Read EDA guideline 804/2025.
- Confirm the pharmacy obligations, the reporting interface and the deadlines.
- Ask SOFTECH whether it will report directly. If it does, our layer stays as capture and verification only.
- Scanner hardware per branch (2D imagers). Existing 1D scanners cannot read DataMatrix. Verify per branch.
