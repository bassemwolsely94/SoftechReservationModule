# 10 — Feature Inventory

Status of every feature, grouped by module.

Status codes:
- **COMPLETE** — Fully implemented and functional
- **PARTIAL** — Backend or frontend exists, but not fully integrated
- **BROKEN** — Exists but has known critical bugs
- **MISSING** — Designed/planned but not yet built
- **DEPRECATED** — Exists but should be removed

---

## BRANCHES

| Feature | Status | Notes |
|---------|--------|-------|
| Branch list + detail API | COMPLETE | |
| BranchSettings feature flags | COMPLETE | |
| Branch selector component | COMPLETE | Global filter |
| Branch-aware stock display | COMPLETE | |
| Operational branch gate on reservation | COMPLETE | |
| Branch map/visualization | MISSING | No geographic display |

---

## CATALOG

| Feature | Status | Notes |
|---------|--------|-------|
| Item master sync from SOFTECH | COMPLETE | |
| Item search (name, barcode, softech_id) | COMPLETE | |
| Stock levels per branch | COMPLETE | |
| Item detail page | COMPLETE | |
| Category filtering | COMPLETE | |
| Variant groups (virtual) | COMPLETE | |
| Product bundles | COMPLETE | Models + API; UI may be partial |
| Secondary barcodes (EAN-13) | COMPLETE | |
| Chronic medication tagging | COMPLETE | |
| Product content admin (enrichment) | PARTIAL | UI exists, backend partial |
| Product image gallery | PARTIAL | ImageEnrichmentPage partial |
| Advanced item search modal | COMPLETE | |
| Operational filters bar | COMPLETE | |

---

## CUSTOMERS

| Feature | Status | Notes |
|---------|--------|-------|
| Customer list + search | COMPLETE | |
| Customer detail page | COMPLETE | |
| Customer health profile display | COMPLETE | |
| Health profile auto-computation | COMPLETE | Via `segment_customers` command |
| CRM segmentation (7 classes) | COMPLETE | |
| Churn scoring | COMPLETE | |
| Customer purchase history | COMPLETE | |
| Customer notes | COMPLETE | |
| Phone redaction by role | COMPLETE | |
| Customer chronic condition flags | COMPLETE | |
| Customer WhatsApp link | COMPLETE | |
| Customer LTV calculation | COMPLETE | |
| Cross-branch customer visibility control | COMPLETE | |
| Customer export | MISSING | No CSV/Excel export |
| Customer merge (duplicate PIC) | MISSING | No dedup tool |

---

## RESERVATIONS

| Feature | Status | Notes |
|---------|--------|-------|
| Create reservation | COMPLETE | |
| Reservation list with filters | COMPLETE | |
| Kanban board | COMPLETE | |
| Status transitions | COMPLETE | |
| Activity chatter (Odoo-style) | COMPLETE | |
| Downpayment tracking | COMPLETE | |
| ERP match (post-fulfillment) | COMPLETE | |
| Voice notes on activity | COMPLETE | |
| Image attachments | COMPLETE | |
| @mention in activity | COMPLETE | |
| Reservation print receipt | COMPLETE | |
| WhatsApp notification to customer | PARTIAL | URL generated; not auto-sent |
| Automated expiry | MISSING | No scheduled job |
| Bulk status update | MISSING | |
| Reservation export | MISSING | |

---

## DEMAND

| Feature | Status | Notes |
|---------|--------|-------|
| Create demand record | COMPLETE | |
| Demand list with SLA indicators | COMPLETE | |
| Demand detail + timeline | COMPLETE | |
| SLA breach display | COMPLETE | |
| Follow-up task creation | COMPLETE | |
| Follow-up task completion | COMPLETE | |
| Demand log (call/whatsapp/note) | COMPLETE | |
| Item demand stats (30d) | COMPLETE | |
| Lost sale tracking + reason | COMPLETE | |
| Demand dashboard KPIs | COMPLETE | |
| SLA breach notifications | MISSING | No auto-escalation |
| Customer SMS/WhatsApp from demand | PARTIAL | Link only, no automation |
| Demand → Transfer link | PARTIAL | No formal FK |
| Demand export | MISSING | |

---

## TRANSFERS

| Feature | Status | Notes |
|---------|--------|-------|
| Create transfer request | COMPLETE | |
| Transfer list + filters | COMPLETE | |
| Transfer detail + workflow | COMPLETE | |
| Full approval state machine | COMPLETE | |
| Chatter with voice notes | COMPLETE | |
| ERP reference recording | COMPLETE | |
| ERP match (post-completion) | COMPLETE | |
| Transfer recommendations (from engine) | PARTIAL | Backend complete; UI partial |
| ROI score display | PARTIAL | |
| Automated ERP match check | MISSING | Currently manual trigger |
| Transfer export | MISSING | |

---

## USERS / PERMISSIONS

| Feature | Status | Notes |
|---------|--------|-------|
| Staff CRUD | COMPLETE | |
| Role assignment | COMPLETE | |
| Branch access control | COMPLETE | |
| ERP user cache sync | COMPLETE | |
| Permissions matrix UI | COMPLETE | |
| Granular action-level permissions | PARTIAL | Role-based, not action-based |
| Audit log per user action | PARTIAL | Some actions logged |
| Staff activity reports | MISSING | |

---

## NOTIFICATIONS

| Feature | Status | Notes |
|---------|--------|-------|
| Persistent notification storage | COMPLETE | |
| Real-time WebSocket push | COMPLETE | |
| Notification bell + panel | COMPLETE | |
| Mark as read / mark all read | COMPLETE | |
| 5-min dedup window | COMPLETE | |
| 19 notification types | COMPLETE | |
| Branch-level notification gate | COMPLETE | |
| Generic chatter (ChatterMessage) | COMPLETE | |
| @mention in chatter | COMPLETE | |
| Offline catch-up on reconnect | COMPLETE | |
| WebSocket disconnect indicator | MISSING | Silent failure |
| Email notifications | MISSING | WhatsApp only |
| Push notifications (mobile) | MISSING | |

---

## VOUCHERS

| Feature | Status | Notes |
|---------|--------|-------|
| Voucher CRUD | COMPLETE | |
| 4 voucher categories | COMPLETE | |
| 4 discount types | COMPLETE | |
| OTP generation (HMAC-SHA256) | COMPLETE | |
| WhatsApp OTP delivery | COMPLETE | |
| OTP verification | COMPLETE | |
| Redemption document (15-min) | COMPLETE | |
| POS mark-used confirmation | COMPLETE | |
| Redemption audit trail | COMPLETE | |
| Customer phone assignment | COMPLETE | |
| Customer picker (name/phone/PIC search) | COMPLETE | |
| Per-customer usage limits | COMPLETE | |
| Per-day usage limits | COMPLETE | |
| Applicable items restriction | PARTIAL | Stored but not enforced in eligibility check |
| Applicable branches restriction | PARTIAL | Stored but not enforced |
| Voucher analytics dashboard | MISSING | |
| Bulk voucher generation | MISSING | |
| Voucher expiry notifications | MISSING | |

---

## INCENTIVES

| Feature | Status | Notes |
|---------|--------|-------|
| Incentive program CRUD | COMPLETE | |
| Rule creation (5 types) | COMPLETE | |
| Multi-item rules (IncentiveRuleItem) | COMPLETE | |
| CSV rule import | COMPLETE | |
| Slab/tiered incentive type | COMPLETE | |
| Incentive calculation engine | COMPLETE | |
| Simulate mode | COMPLETE | |
| Settlement generation | COMPLETE | |
| Manual adjustments | COMPLETE | |
| Settlement finalization | COMPLETE | |
| Calculation audit log | COMPLETE | |
| Cross-period return handling | COMPLETE | |
| Incentive dashboard by salesperson | PARTIAL | UI exists, may have incomplete charts |
| Scheduled auto-calculation | MISSING | Currently manual trigger |

---

## STOCKCOUNT

| Feature | Status | Notes |
|---------|--------|-------|
| Session creation | COMPLETE | |
| Snapshot (freeze expected qty) | COMPLETE | |
| Excel export of count sheet | COMPLETE | |
| Upload counted quantities | COMPLETE | |
| Variance report (surplus/deficit/ok) | COMPLETE | |
| Session close | COMPLETE | |
| 3 count modes | COMPLETE | |
| Branch + doccode filtering | COMPLETE | |
| Variance submission to ERP | MISSING | Results not written to SOFTECH |

---

## SHORTAGE

| Feature | Status | Notes |
|---------|--------|-------|
| Shortage list creation | COMPLETE | |
| Manual item entry | COMPLETE | |
| Bulk text import | COMPLETE | |
| OCR image upload | COMPLETE | |
| Voice input | COMPLETE | |
| Fuzzy matching (rapidfuzz) | COMPLETE | |
| Match confirmation workflow | COMPLETE | |
| Submit shortage list | COMPLETE | |
| Shortage → Purchase order link | MISSING | |
| Shortage analytics | MISSING | |

---

## PURCHASING / PROCUREMENT

| Feature | Status | Notes |
|---------|--------|-------|
| Demand engine (weighted avg) | COMPLETE | |
| ABC classification | COMPLETE | |
| Safety stock calculation | COMPLETE | |
| Transfer recommendations | COMPLETE | Backend |
| Procurement hub (tabbed UI) | PARTIAL | Some tabs scaffolded |
| Supplier segmentation | PARTIAL | |
| FOC analysis | PARTIAL | |
| Supplier performance | PARTIAL | |
| Margin analysis | PARTIAL | |
| Purchase history analytics | PARTIAL | |
| Vendor item mappings UI | PARTIAL | |
| Automated reorder alerts | MISSING | |
| Purchase order creation | MISSING | Manual ERP entry only |

---

## INVOICES

| Feature | Status | Notes |
|---------|--------|-------|
| Supplier invoice list | PARTIAL | |
| Invoice OCR (Gemini) | PARTIAL | |
| Fuzzy item matching | PARTIAL | |
| Vendor profile management | PARTIAL | |
| VendorItemMapping learning table | PARTIAL | use_count increment TBD |
| Invoice approval workflow | MISSING | |
| Invoice → Purchase reconciliation | MISSING | |

---

## CALL CENTER

| Feature | Status | Notes |
|---------|--------|-------|
| Case list | PARTIAL | |
| Case detail | PARTIAL | |
| Call center analytics | PARTIAL | |
| Call center → Demand link | PARTIAL | |
| Escalation workflow | MISSING | |
| Call recording integration | MISSING | |

---

## ANALYTICS

| Feature | Status | Notes |
|---------|--------|-------|
| Sales dashboard | PARTIAL | Some charts wired |
| Performance dashboard | PARTIAL | |
| Item analytics | PARTIAL | |
| Customer analytics | PARTIAL | |
| Branch comparison | MISSING | |
| Export to Excel | MISSING | |

---

## FINANCE

| Feature | Status | Notes |
|---------|--------|-------|
| Finance hub UI (6 tabs) | PARTIAL | UI scaffolded |
| Chart of accounts display | PARTIAL | |
| P&L report | PARTIAL | Not connected to real data |
| Cash flow report | PARTIAL | Not connected |
| Expense analytics | PARTIAL | Not connected |
| Finance schema explorer | PARTIAL | |

---

## SYSTEM / ADMIN

| Feature | Status | Notes |
|---------|--------|-------|
| System settings CRUD | COMPLETE | |
| Dropdown options management | COMPLETE | |
| Pharmacy profile singleton | COMPLETE | |
| ERP sync management | COMPLETE | |
| Audit trail | PARTIAL | Not all actions logged |
| User activity reports | MISSING | |
| API rate limiting | MISSING | |
| Request logging / APM | MISSING | |
