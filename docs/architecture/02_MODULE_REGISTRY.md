# 02 — Module Registry

Every module in the platform is registered here with its purpose, status, and dependency map.

---

## BRANCHES

| Field | Value |
|-------|-------|
| App | `apps/branches` |
| Purpose | Physical pharmacy location master + per-branch feature flags |
| Status | **COMPLETE** |
| Migrations | 3 |
| Models | `Branch`, `BranchSettings` |
| Key APIs | `/api/branches/` |
| Related Tables | branch (PK for all scoped entities) |
| Related Screens | BranchSelect component (global) |
| Business Rules | `is_operational` gate on reservation creation; `notifications_enabled` suppresses branch-wide alerts |

---

## CATALOG

| Field | Value |
|-------|-------|
| App | `apps/catalog` |
| Purpose | Item master, stock levels, barcodes, bundles, variant groups |
| Status | **COMPLETE** |
| Migrations | 21 |
| Models | `Item`, `Category`, `ItemStock`, `ItemBarcode`, `ChronicMedication`, `CatalogVariantGroup`, `VariantMember`, `ProductBundle`, `BundleItem` |
| Key APIs | `/api/items/` |
| Related Tables | item (FK in virtually every domain table) |
| Related Screens | ProductCatalogPage, ProductDetailPage, ItemSearchWidget |
| Business Rules | `EXCLUDED_STORE_CODES = {'102','103','105'}` excluded from operational stock; `can_transact` field gates selling/transferring |
| Dependencies | branches (ItemStock per branch) |

---

## CUSTOMERS

| Field | Value |
|-------|-------|
| App | `apps/customers` |
| Purpose | Customer master, health profiling, purchase history, CRM segmentation |
| Status | **COMPLETE** |
| Migrations | 16 |
| Models | `Customer`, `CustomerNote`, `CustomerHealthProfile`, `PurchaseHistory`, `PurchaseHistoryLine` |
| Key APIs | `/api/customers/` |
| Related Tables | customers_customer, customers_purchasehistory, customers_purchasehistoryline |
| Related Screens | CustomersPage, CustomerDetailPage, ChronicClassifierPage |
| Business Rules | 7-segment CRM (vip/loyal/regular/at_risk/dormant/new/churned); churn scoring 0–1; health profile auto-computed via `segment_customers` command |
| Dependencies | branches, catalog |

---

## RESERVATIONS

| Field | Value |
|-------|-------|
| App | `apps/reservations` |
| Purpose | End-to-end reservation workflow for out-of-stock customer requests |
| Status | **COMPLETE** |
| Migrations | 21 |
| Models | `Reservation`, `ReservationDownpayment`, `ReservationStatusLog`, `ReservationImage`, `ReservationActivity` |
| Key APIs | `/api/reservations/` |
| Related Tables | reservations_reservation, reservations_reservationactivity |
| Related Screens | ReservationsPage, ReservationsKanban, NewReservationPage, ReservationDetailPage |
| Business Rules | Status machine: pending→available→contacted→confirmed→fulfilled/cancelled/expired; ERP match post-fulfillment; downpayment tracking; Odoo-style activity chatter |
| Dependencies | catalog, customers, branches, users, notifications |

---

## DEMAND

| Field | Value |
|-------|-------|
| App | `apps/demand` |
| Purpose | Structured demand capture with SLA tracking, follow-up tasks, lost-sale intelligence |
| Status | **COMPLETE** |
| Migrations | 2 |
| Models | `DemandRecord`, `DemandItem`, `FollowUpTask`, `DemandLog`, `ItemDemandStat` |
| Key APIs | `/api/demand/` |
| Related Tables | demand_demandrecord, demand_demanditem, demand_itemdemandstat |
| Related Screens | DemandPage, DemandDashboardPage, DemandDetailPage, FollowUpsPage |
| Business Rules | SLA: 10 min new→assigned, 20 min assigned→contacted; 7 loss reasons; demand stats aggregated daily per item per branch |
| Dependencies | catalog, customers, branches, users, notifications |

---

## TRANSFERS

| Field | Value |
|-------|-------|
| App | `apps/transfers` |
| Purpose | Inter-branch transfer request approval workflow (no stock mutations) |
| Status | **COMPLETE** |
| Migrations | 11 |
| Models | `TransferRequest`, `TransferRequestItem`, `TransferRequestMessage` |
| Key APIs | `/api/transfers/` |
| Related Tables | transfers_transferrequest, transfers_transferrequestitem |
| Related Screens | TransfersPage, NewTransferPage, TransferDetailPage |
| Business Rules | 8-state machine (draft→pending→approved→rejected→needs_revision→sent_to_erp→completed→cancelled); ERP match after completion; Odoo-style chatter with voice notes |
| Dependencies | catalog, branches, users, notifications, purchasing (recommendation FK) |

---

## USERS

| Field | Value |
|-------|-------|
| App | `apps/users` |
| Purpose | Staff profiles, role-based access, ERP user cache |
| Status | **COMPLETE** |
| Migrations | 12 |
| Models | `ERPUser`, `StaffProfile` |
| Key APIs | `/api/users/`, `/api/auth/` |
| Related Screens | UserManagementPage, PermissionsMatrixPage |
| Business Rules | 9 roles (admin/call_center/pharmacist/salesperson/purchasing/delivery/viewer/supervisor/quality_manager); `access_all_branches` flag; `can_see_customer_phone` flag |
| Dependencies | branches |

---

## NOTIFICATIONS

| Field | Value |
|-------|-------|
| App | `apps/notifications` |
| Purpose | Persistent notifications + real-time WebSocket push + Odoo-style chatter |
| Status | **COMPLETE** |
| Migrations | 10 |
| Models | `Notification`, `NotificationLog`, `ChatterMessage` |
| Key APIs | `/api/notifications/` |
| Related Screens | NotificationPanel, NotificationBell |
| Business Rules | 19 notification types; 5-min dedup window by `dedup_key`; BranchSettings gate; real-time via Channels group `notifications_user_{profile_id}` |
| Dependencies | users, branches, channels (Redis) |

---

## PURCHASING

| Field | Value |
|-------|-------|
| App | `apps/purchasing` |
| Purpose | Demand engine, ABC analysis, safety-stock calculations, transfer recommendations |
| Status | **PARTIAL** (engine complete; UI procurement hub partial) |
| Migrations | 14 |
| Models | `EngineConfig`, `SalesTransactionLine`, `DemandCalculationRun`, `ItemDemandMetrics`, `ItemDemandAggregated`, `TransferRecommendation` |
| Key APIs | `/api/purchasing/`, `/api/procurement/` |
| Related Screens | PurchasingDashboard, ProcurementHubPage |
| Business Rules | Weighted avg: 30d×0.5 + 90d×0.3 + 365d×0.2; ABC A=70%/B=90%; safety-stock tiers (high/mid/low/vlow multipliers) |
| Dependencies | catalog, branches, transfers |

---

## INVOICES

| Field | Value |
|-------|-------|
| App | `apps/invoices` |
| Purpose | Supplier invoice capture, OCR extraction, fuzzy item matching |
| Status | **PARTIAL** |
| Migrations | 8 |
| Models | `VendorProfile`, `VendorItemMapping`, `SupplierInvoice`, `InvoiceLine` |
| Key APIs | `/api/invoices/` |
| Related Screens | InvoicePage |
| Business Rules | OCR via Google Gemini; fuzzy matching via rapidfuzz; VendorItemMapping learning table accumulates match confirmations |
| Dependencies | catalog |

---

## VOUCHERS

| Field | Value |
|-------|-------|
| App | `apps/vouchers` |
| Purpose | Production-grade voucher platform with OTP verification and POS redemption document |
| Status | **COMPLETE** |
| Models | `Voucher`, `VoucherAssignment`, `VoucherOTP`, `VoucherRedemptionDocument`, `VoucherRedemption` |
| Key APIs | `/api/vouchers/` |
| Related Screens | VouchersPage |
| Business Rules | 4 categories (public/private/first_time/assigned); 4 discount types; HMAC-SHA256 OTP (never stored plain); 3-min OTP TTL; 15-min redemption document window; per-customer + per-day usage limits |
| Dependencies | catalog, customers, branches, users |

---

## INCENTIVES

| Field | Value |
|-------|-------|
| App | `apps/incentives` |
| Purpose | Sales incentive engine: programs, rules, transactions, settlements |
| Status | **COMPLETE** |
| Models | `IncentiveProgram`, `IncentiveRule`, `IncentiveRuleItem`, `IncentiveTransaction`, `IncentiveSettlement`, `AdjustmentEntry`, `IncentiveCalculationLog` |
| Key APIs | `/api/incentives/` |
| Related Screens | IncentivesPage |
| Business Rules | 5 incentive types (percent/fixed_per_unit/fixed_per_transaction/tiered); slab config JSON; per-person, per-branch, time-window filters; cross-period return reversal |
| Dependencies | users, catalog |

---

## STOCKCOUNT

| Field | Value |
|-------|-------|
| App | `apps/stockcount` |
| Purpose | Transaction-based stock count sessions with immutable snapshots |
| Status | **COMPLETE** |
| Models | `StockCountSession`, `StockCountSnapshot` |
| Key APIs | `/api/stockcount/` |
| Related Screens | StockCountPage |
| Business Rules | 6-stage session lifecycle (draft→snapshot_taken→exported→uploaded→variance_ready→closed); 3 modes (transaction/full/filtered); snapshot is IMMUTABLE after creation |
| Dependencies | branches, users |

---

## SHORTAGE

| Field | Value |
|-------|-------|
| App | `apps/shortage` |
| Purpose | Shortage list management with OCR + fuzzy item matching |
| Status | **COMPLETE** |
| Models | `ShortageList`, `ShortageItem` |
| Key APIs | `/api/shortage/` |
| Related Screens | ShortagePage |
| Business Rules | 3 list statuses (open/submitted/resolved); 4 item input sources (manual/voice/ocr/bulk); rapidfuzz match scoring; confirmed_by audit trail |
| Dependencies | catalog, branches, users |

---

## CALLCENTER

| Field | Value |
|-------|-------|
| App | `apps/callcenter` |
| Purpose | Call center case tracking and analytics |
| Status | **PARTIAL** |
| Migrations | 6 |
| Key APIs | `/api/callcenter/` |
| Related Screens | CallCenterPage, CasesPage, CallCenterAnalyticsPage |
| Dependencies | customers, users |

---

## FOLLOWUPS

| Field | Value |
|-------|-------|
| App | `apps/followups` |
| Purpose | Follow-up task management across reservations and demands |
| Status | **PARTIAL** |
| Migrations | 7 |
| Key APIs | `/api/followups/` |
| Related Screens | FollowUpsPage |
| Dependencies | reservations, demand, users |

---

## CHRONIC

| Field | Value |
|-------|-------|
| App | `apps/chronic` |
| Purpose | Chronic medication detection + customer condition tagging |
| Status | **COMPLETE** |
| Migrations | 3 |
| Key APIs | `/api/chronic/` |
| Related Screens | ChronicClassifierPage |
| Business Rules | `tag_chronic_items` command tags items; CustomerHealthProfile records 16 condition flags |
| Dependencies | catalog, customers |

---

## CONFIG

| Field | Value |
|-------|-------|
| App | `apps/config` |
| Purpose | Global key-value settings, configurable dropdowns, pharmacy profile singleton |
| Status | **COMPLETE** |
| Migrations | 3 |
| Models | `SystemSetting`, `DropdownOption`, `PharmacyProfile` |
| Key APIs | `/api/config/` |
| Business Rules | PharmacyProfile is pk=1 singleton; SystemSetting supports string/integer/decimal/boolean/json types |
| Dependencies | None |

---

## ANALYTICS

| Field | Value |
|-------|-------|
| App | `apps/analytics` |
| Purpose | Sales and performance analytics dashboards |
| Status | **PARTIAL** |
| Key APIs | `/api/analytics/` |
| Related Screens | AnalyticsHubPage, SalesDashboard, PerformanceDashboard |
| Dependencies | customers, catalog, branches |

---

## AUDIT

| Field | Value |
|-------|-------|
| App | `apps/audit` |
| Purpose | Platform-wide immutable audit trail |
| Status | **PARTIAL** |
| Migrations | 2 |
| Key APIs | `/api/audit/` |
| Related Screens | AuditPage |
| Dependencies | users |

---

## SYNC

| Field | Value |
|-------|-------|
| App | `apps/sync` |
| Purpose | ERP synchronization management (items, customers, transactions) |
| Status | **COMPLETE** |
| Key APIs | `/api/sync/` |
| Related Screens | SyncPage |
| Business Rules | One-way: SOFTECH → PostgreSQL; incremental sync (last N days); upsert strategy |
| Dependencies | catalog, customers, branches |

---

## FINANCE

| Field | Value |
|-------|-------|
| App | `apps/finance` |
| Purpose | Financial intelligence (CoA, P&L, cash flow, expense analytics) |
| Status | **PARTIAL** (UI scaffolded; backend reads external data) |
| Key APIs | `/api/finance/` |
| Related Screens | FinanceHubPage (6 tabs) |

---

## POS ORDERS (Indirect-POS Writeback)

| Field | Value |
|-------|-------|
| App | `apps/pos_orders` |
| Purpose | Create **pending indirect-POS sales orders** in our system and push them into SOFTECH for a branch cashier to settle. This is a **live SOFTECH writeback channel** (the Phase-2 writer from doc 14 — now BUILT), modeled on `discount_approvals/replication.py`. |
| Status | **COMPLETE** (desktop + mobile + writer + reconciler + offline queue) |
| Models | `SoftechSalesOrder` (header, 8-status lifecycle), `SoftechSalesOrderLine` (→ `stktrans5`), `SoftechSalesOrderPayment` (→ `branchesales5`, split tenders) |
| Lifecycle | `draft → ready → queued → pushing → pushed → settled` (+ `push_failed`, `cancelled`). Immutable once `pushing`/`pushed`/`settled`/`cancelled` (`is_locked`); corrections are done via a return order. |
| Write surface | **PENDING side only:** `stktransm5` (header) + `stktrans5` (lines) + `branchesales5` (tenders). NEVER writes final `stktransm`/`stktrans`/`branchesales`, `stkbal`, `picpoints`, accounting or e-invoice — the cashier's settlement does that. |
| Idempotency | `client_token` (UUID, UNIQUE, stashed in SOFTECH `vf2`/comments) so a replayed offline create can't duplicate. |
| Key files | `writer.py` (transactional writer: collision-safe serial alloc + verify-readback + dry-run), `pricing.py` (transprice/tax/COGS mirror), `reconcile.py` (read-back reconciler pending→final), `discount_authority.py`, `batch_availability.py`, `reservation.py`, `validators.py`, `permissions.py` |
| Channels | cash / delivery / contract / insurance / employee / vip / permanent → SOFTECH `ptclassifcode`. Contract/insurance clone `companiesitems5` + `branchesalescc5` so the duplicate settles into a RETURNABLE contract sale. |
| Key APIs | `/api/pos-orders/` — list/create, `reference/`, `batches/`, `discount-suggest/`, `queue-status/`, `flush/`, `{id}/` detail, `{id}/ready/`, `{id}/push/`, `{id}/cancel/` |
| Commands | `flush_pos_orders` (drain the offline retry queue), `reconcile_pos_orders` (pending→final readback), `pos_probe` (SOFTECH connectivity/diagnostic) |
| Screens | Desktop `POSOrderPage` (`/pos`), Mobile `MobilePOSOrderPage` (`/m/pos`) |
| Extras beyond SOFTECH | referral doctor, prescription image, originating call/call-item link, notes, immutable `erp_payload`/`erp_readback`/`erp_error` audit |
| Docs | `SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md` (reverse-eng), `14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md` (design), `POS_OFFLINE_RESILIENCE.md`, `POS_OPERATOR_RUNBOOK.md`, `MDA_INSTALL_RUNBOOK.md` |

---

## OTHER APPS (index — see source for detail)

| App | API base | Status | Purpose |
|-----|----------|--------|---------|
| insurance | `/api/insurance/` | COMPLETE | Insurance claims (motalba/SOFTECH), clients, claim detail + print profiles/print; sync commands (`sync_insurance_cache`, `sync_motalbas`, `reimport_all_claims`) |
| loyalty | `/api/loyalty/` | COMPLETE | Loyalty points program + per-branch points (`seed_loyalty`) |
| referral | `/api/referral/` | COMPLETE | Referral doctor / referral program |
| forecasting | `/api/forecasting/` | COMPLETE | Demand/sales forecasting (`run_forecast`) |
| batches | `/api/batches/` | COMPLETE | Batch/expiry tracking + near-expiry scan (`near_expiry_scan`) |
| approvals | `/api/approvals/` | COMPLETE | Generic operational + HR approval workflows (`seed_approval_workflows`); desktop `/approvals` + mobile `/m/approvals` |
| discount_approvals | `/api/pricing-approvals/` | COMPLETE | Approved item-discount changes written back to SOFTECH (`replication.py` — the reference writeback channel) |
| procurement | `/api/procurement/` | COMPLETE | Procurement hub: history, supplier segmentation/performance, FOC, margins, optimization (`run_procurement_engine`) |
| product_experience | `/api/products/` | COMPLETE | Product content admin + item intelligence + catalog intelligence |
| whatsapp | `/api/whatsapp/` | COMPLETE | WhatsApp Cloud API: campaigns + inbox (underpins Omni) |
| pbx | `/api/pbx/` | COMPLETE | Issabel AMI bridge: extensions + live calls (`run_ami_bridge`, `sync_pbx_extensions`) — underpins Omni wallboard |
| hr | `/api/hr/` | COMPLETE (mobile) | Geofenced attendance (GPS clock in/out vs branch coords) |
| qa | `/api/qa/` | COMPLETE (mobile) | Branch QA inspections (templates + pass/fail/na + score) |
| erp | — | INTERNAL | SOFTECH connector helpers + ERP permission model (`/erp-permissions`) |
| dashboard | `/api/dashboard/` | PARTIAL | Home dashboard aggregations |
| enrichment | `/api/enrichment/` | PARTIAL | Product image enrichment |
| images | `/api/images/` | PARTIAL | Image storage + OCR |
| recommendations | `/api/recommendations/` | PARTIAL | Product recommendation engine |
| campaigns | `/api/campaigns/` | PARTIAL | Campaign management (WhatsApp send) |
| cheques | `/api/cheques/` | PARTIAL | Cheque planning |
| delivery | `/api/delivery/` | PARTIAL (backend complete) | Delivery orders + rider app + tracking |
| payments | `/api/payments/` | PARTIAL | Payment tracking + payment audit |
| tasks | `/api/tasks/` | PARTIAL | Operational tasks + schedules + dashboard |
| portal | `/api/portal/` | COMPLETE | External customer PWA (magic-link auth) |
| omni | `/api/omni/` | COMPLETE | Unified inbox / CEP (envelope over whatsapp/pbx/callcenter) |
| social | `/api/social/` | COMPLETE | Social channel webhooks (Messenger/IG/Telegram/TikTok) |
| transits | `/api/transits/` | COMPLETE | In-transit replenishment monitoring + picking/stocking export |
