# 08 — Duplication Report

Analysis of overlapping functionality, duplicate data structures, and redundant workflows.

---

## CRITICAL DUPLICATIONS

---

### DUP-001: Two Parallel Demand-Intake Workflows

**Severity:** HIGH  
**Description:** The platform has two separate systems for capturing customer demand for out-of-stock items.

| Aspect | Reservations | Demand Records |
|--------|-------------|---------------|
| Model | `Reservation` | `DemandRecord` + `DemandItem` |
| Created by | `apps/reservations` | `apps/demand` |
| Customer link | Optional FK | Optional FK + phone mandatory |
| SLA tracking | None | Yes (10/20 min) |
| Follow-up tasks | Via `ReservationActivity` | Via `FollowUpTask` |
| Chatter | `ReservationActivity` | `DemandLog` |
| ERP match | Yes (post-fulfillment) | Partial (erp_invoice_ref) |
| Status machine | 7 statuses | 9 statuses |
| UI screens | 4 dedicated screens | 4 dedicated screens |

**Impact:** Teams and UX are split across two screens that serve the same fundamental purpose: "customer wants item we don't have."

**Recommended Consolidation:**  
- **Short term:** Keep both; add a cross-reference field (`demand_id` on Reservation, `reservation_id` on DemandRecord) so they can be linked
- **Long term:** Merge into one unified "Customer Request" entity that supports both simple (reservation) and structured (demand with SLA) modes
- **Do NOT merge prematurely** — both are deeply embedded in UI, API, and business process

---

### DUP-002: Two Chatter Implementations

**Severity:** MEDIUM  
**Description:** Chatter (Odoo-style comments) is implemented differently across modules.

| Module | Implementation |
|--------|---------------|
| Reservations | `ReservationActivity` — typed activities (call_made, stock_checked, etc.) |
| Transfers | `TransferRequestMessage` — typed messages (message/system/note) |
| Demand | `DemandLog` — typed logs (note/call/whatsapp/sms/system/status) |
| Generic | `ChatterMessage` (in notifications app) — generic model_name + record_id |

**Overlap:** All four support: text content, file attachment, soft delete, created_by, voice notes (some).  
**Divergence:** Activity types and business-specific fields differ per module.

**Recommended Consolidation:**  
- Long term: migrate all to `ChatterMessage` with an `activity_type` extension field
- Short term: do not duplicate further; use `ChatterMessage` for any NEW module that needs chatter
- Add `voice_note` to `ChatterMessage` (currently missing)

---

### DUP-003: ERP Match Logic Duplicated in Reservations and Transfers

**Severity:** MEDIUM  
**Description:** Both `Reservation` and `TransferRequest` have nearly identical ERP match field sets.

**Shared fields pattern:**
```
erp_reference / erp_match_status / erp_matched_at / erp_match_doc_code /
erp_match_date / erp_match_value / erp_user_code / erp_user_id / erp_user_name /
erp_trans_time / erp_store_code / erp_matched_items (JSON) / erp_last_checked /
erp_check_attempts / erp_match_detail
```

**Recommended Consolidation:**  
Create a reusable `ERPMatchMixin` abstract model with these fields, inherited by both.  
No code change needed now; apply on next model refactor.

---

### DUP-004: FollowUpTask Exists in Both demand and followups Apps

**Severity:** MEDIUM — **✅ RESOLVED 2026-06-21 (strategy B: de-collide + clarify)**

**Original concern:** Both `apps/demand` and `apps/followups` defined a model named `FollowUpTask`; the overlap/relationship was unclear.

**Finding on audit:** the two are **not functional duplicates** — they are distinct systems that shared a class name:
- `demand.FollowUpTask` — a per-`DemandRecord`, channel-typed micro-task list (call/whatsapp/sms/visit/stock_check), `due_date` with a time, required CASCADE FK to one demand. Auto-created with each demand; drives the demand detail "المتابعات" tab.
- `followups.FollowUpTask` — the customer-centric chronic-refill engine (priority scoring, multi-assignee, ERP sale anchors, pinning). It *spawns* a `DemandRecord` via `followups.services.create_demand_from_task` (live, one-directional bridge through `demand_record` FK).

**Resolution (no risky data merge):**
- Renamed `demand.FollowUpTask` → **`demand.DemandFollowUp`** to remove the name collision; verbose names changed to "متابعة طلب / متابعات الطلبات". Table pinned to `demand_followuptask` via `Meta.db_table`, so migration `demand/0010` is a **state-only `SeparateDatabaseAndState` rename — zero DDL, no data move**.
- Updated all in-app references (models, serializers `DemandFollowUpSerializer`, views, service, admin). API JSON shape and endpoint paths (`/followups`, `/schedule-followup`) unchanged → no frontend changes.
- Removed dead `catalog.chronic.create_chronic_follow_up_task` (no callers).
- Documented the boundary in both model docstrings.

**Why not a full merge (strategy A):** forcing demand's channel-typed, auto-spawned micro-tasks into the chronic engine would be a lossy migration (DateTime→Date, no home for channel task_types) and would pollute the chronic worklist + nightly priority scoring. The live `followups → demand` bridge already covers the legitimate cross-link.

---

### DUP-005: Two Item Search Components

**Severity:** LOW  
**Description:** Frontend has overlapping item search implementations:
- `ItemSearchWidget.jsx` — popup widget
- `ItemSearchInput.jsx` — inline input
- `AdvancedItemSearchModal.jsx` — full modal

**Recommended Action:** Document the correct component for each use case and standardize. Do not create a fourth.

---

### DUP-006: Stock Level Data Sources

**Severity:** MEDIUM  
**Description:** Stock levels for items can be read from:
1. `catalog_itemstock` (synced from SOFTECH, by branch)
2. SOFTECH direct query (via pyodbc in some views)
3. `purchasing_salestransactionline` (rolling calculation)

**Risk:** Different queries may return different stock numbers. No single source of truth for "current stock."

**Recommended Action:** Enforce that all UI always reads from `catalog_itemstock`; use SOFTECH direct only in sync commands.

---

### DUP-007: Customer Phone Stored in Multiple Places

**Severity:** LOW  
**Description:** Customer phone number is stored in:
- `customers_customer.phone`
- `vouchers_voucherassignment.customer_phone`
- `vouchers_voucherotp.phone`
- `vouchers_voucherredemption.customer_phone`
- `vouchers_voucherredemptiondocument.customer_phone`
- `demand_demandrecord.phone`
- `reservations_reservation.contact_phone`

**Impact:** Denormalization is intentional in some places (audit trail must be immutable), but it means customer phone changes don't propagate.  
**Recommended Action:** Accept denormalization in audit tables (VoucherRedemption); ensure core tables use FK where possible.

---

## LOW-PRIORITY DUPLICATIONS

### DUP-008: `created_by` + `created_at` + `updated_at` on every model
Expected pattern — not a duplication concern. Consistent and correct.

### DUP-009: Status field with `active`/`cancelled`/`expired` on both Voucher and VoucherRedemptionDocument
Intentional — different entities with overlapping status vocabularies. Not a duplication.

### DUP-010: `branch_code` as varchar vs `branch_id` as FK
Some models use `branch_id` (FK), others use `branch_code` (varchar from ERP).  
`StockCountSession` uses `branch_code` (no FK) to allow sessions on branches not yet synced.  
This is intentional but inconsistent — be aware when joining.

---

## DUPLICATION RISK: Things That Must NOT Be Duplicated

Based on the above, future development must never:

1. Create a third demand-intake model (use Reservation or DemandRecord)
2. Create a fourth chatter implementation (use ChatterMessage or extend existing)
3. Create a new ERP-match field set from scratch (use the established pattern)
4. Create a new item search component beyond the existing three
5. Store stock levels outside of `catalog_itemstock`
