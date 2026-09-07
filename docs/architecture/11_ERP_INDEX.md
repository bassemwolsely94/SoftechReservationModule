# 11 — ERP Index (Master Navigation Document)

This is the primary navigation document for the ElRezeiky platform.  
**Start here before every development task.**

---

## DESIGN DOCS & ROADMAPS

| # | Doc | Status | Summary |
|---|-----|--------|---------|
| 13 | [13_DEMAND_EVOLUTION_ROADMAP.md](13_DEMAND_EVOLUTION_ROADMAP.md) | ✅ BUILT (2026-06-12) | `apps/demand` evolved from a passive lost-sales log into an active recovery + intelligence engine: 4 loops shipped (back-in-stock recovery + ROI, confirmed valuation + reconciliation vs purchasing engine, value-weighted buy signal + therapeutic substitution, customer unmet-demand profile + churn). Plus Demand↔Reservation bridge and module-scoped notifications (demand/followups). Migrations demand/0003–0006, notifications/0015. |
| — | [SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md](SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md) | ✅ INVESTIGATED (2026-06-21) | Full read-only reverse-engineering of the SOFTECH Indirect-POS → Cashier pending-order subsystem: tables (`stktransm5`/`stktrans5`/`branchesales5`), dual serial sequences (`lastdocnumbers` `'000'` staging vs branch `ver_branch=1` final), pricing/tax/cost/discount formulas, channels, payments, points, and the full create→settle→refund lifecycle empirically validated on branch 130. |
| 14 | [14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md](14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md) | ✅ BUILT (2026-07-25) | Phase-2 SOFTECH pending-order **writer is shipped** as `apps/pos_orders`: PG mirror `SoftechSalesOrder`+lines+payments (referral-doctor/prescription/multi-channel extras), transactional writer modeled on `discount_approvals/replication.py` (collision-safe serial alloc + verify-readback + dry-run), read-back reconciler, **offline retry queue** (`queue-status`/`flush`), discount authority + batch availability. Live SOFTECH writeback (PENDING side only: `stktransm5`/`stktrans5`/`branchesales5`). Desktop `/pos` + mobile `/m/pos`. Ops: `POS_OFFLINE_RESILIENCE.md`, `POS_OPERATOR_RUNBOOK.md`, `MDA_INSTALL_RUNBOOK.md`. See [02_MODULE_REGISTRY.md#pos-orders-indirect-pos-writeback](02_MODULE_REGISTRY.md). |
| 15 | [15_CEP_OMNICHANNEL_DESIGN.md](15_CEP_OMNICHANNEL_DESIGN.md) | ✅ ALL PHASES 0–5 BUILT (2026-07-05) | Omnichannel Communication & Engagement Platform: thin `apps/omni` envelope layer (ChannelAccount / Conversation / TimelineEvent) unifying the EXISTING `apps/whatsapp` (Cloud API), `apps/pbx` (Issabel AMI), `apps/callcenter` (cases + AI) into one customer-grouped timeline; multi-account WhatsApp + provider abstraction, routing/SLA, supervisor wallboard, automation engine, social channels (FB/IG/TG/TikTok). 6-phase roadmap; extend-don't-rebuild. |
| 16 | [16_BRANCH_KPI_FORECASTING.md](16_BRANCH_KPI_FORECASTING.md) | ✅ PHASES 1–6 BUILT (2026-07-29) | Branch-KPI forecasting + target engine replacing the manual monthly Excel target/achievement workbooks (`تارجت/تحقيق شهر`). **Extends** `incentives.SalesTarget` (widen metrics) + adds a branch-KPI layer to `apps/forecasting` (`ForecastScenario`/`ForecastFactor`/`KpiActualRollup`/`ForecastBacktest` + config-driven `ChannelBucketMap`). All KPIs (cash/credit/delivery/beauty/gross-profit/customers/call-center) derived from the PG mirror; two engines (Model A base×growth÷threshold, Model B LM/PM/YoY blend) + average, backtested to auto-pick the best. Feeds the incentive ÷threshold gate. 6-phase plan; NOT built yet. |

---

## MODULE INDEX

| Module | App | Status | Doc Reference |
|--------|-----|--------|--------------|
| Branches | `apps/branches` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#branches) |
| Catalog / Items | `apps/catalog` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#catalog) |
| Customers / CRM | `apps/customers` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#customers) |
| Reservations | `apps/reservations` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#reservations) |
| Demand Records | `apps/demand` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#demand) |
| Transfer Requests | `apps/transfers` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#transfers) |
| Users / Roles | `apps/users` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#users) |
| Notifications | `apps/notifications` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#notifications) |
| Purchasing / Demand Engine | `apps/purchasing` | PARTIAL | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#purchasing) |
| Supplier Invoices | `apps/invoices` | PARTIAL | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#invoices) |
| Vouchers | `apps/vouchers` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#vouchers) |
| Sales Incentives | `apps/incentives` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#incentives) |
| Stock Count | `apps/stockcount` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#stockcount) |
| Shortage Lists | `apps/shortage` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#shortage) |
| Call Center | `apps/callcenter` | PARTIAL | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#callcenter) |
| Follow-ups | `apps/followups` | PARTIAL | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#followups) |
| Chronic Medications | `apps/chronic` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#chronic) |
| System Config | `apps/config` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#config) |
| Analytics | `apps/analytics` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#analytics) |
| Audit Trail | `apps/audit` | PARTIAL | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#audit) |
| ERP Sync | `apps/sync` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#sync) |
| Finance | `apps/finance` | COMPLETE | [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md#finance) |
| Product Enrichment | `apps/enrichment` | PARTIAL | |
| Recommendations | `apps/recommendations` | PARTIAL | |
| Campaigns | `apps/campaigns` | PARTIAL | |
| Cheques | `apps/cheques` | PARTIAL | |
| Deliveries | `apps/delivery` | PARTIAL (backend complete) | |
| Payments | `apps/payments` | PARTIAL | |
| Tasks | `apps/tasks` | PARTIAL | |
| Customer Portal (external PWA) | `apps/portal` | COMPLETE | Stateless signed-token auth; no models. See note below. |
| Branch QA Inspections | `apps/qa` | COMPLETE (mobile) | Templates + pass/fail/na inspections + score |
| HR Attendance (geofenced) | `apps/hr` | COMPLETE (mobile) | AttendanceRecord; GPS clock in/out vs branch coords |
| Transfers In Transit (replenishment monitoring) | `apps/transits` | COMPLETE | Read-only cache of SOFTECH doccode 125 issues + 125↔25 reconciliation + **picking-sheet export (ورقة التجميع)**: consolidated multi-order pick matrix + per-order revision sheets. Classification fully DB-driven (`PickZone`/`PickZoneRule`/`ItemPickOverride`, managed at `/pick-zones`): reorderable keyword rules, fridge = catalog flag + FRIDGE keyword, price threshold (SystemSetting `replenishment_price_threshold`, 500 EGP), per-item overrides with tags/locations |
| Omni (unified inbox / CEP) | `apps/omni` | COMPLETE (Phases 0–5) | [15_CEP_OMNICHANNEL_DESIGN.md](15_CEP_OMNICHANNEL_DESIGN.md) |
| Social channels (Messenger/IG/Telegram) | `apps/social` | COMPLETE (Phase 3) | [15_CEP_OMNICHANNEL_DESIGN.md](15_CEP_OMNICHANNEL_DESIGN.md) |
| **POS Orders (Indirect-POS writeback)** | `apps/pos_orders` | **COMPLETE** | [02_MODULE_REGISTRY.md#pos-orders](02_MODULE_REGISTRY.md) + [14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md](14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md) — desktop `/pos` + mobile `/m/pos`; live SOFTECH pending-order writer |
| Insurance (motalba claims) | `apps/insurance` | COMPLETE | Claims + clients + print profiles; SOFTECH motalba sync |
| Loyalty | `apps/loyalty` | COMPLETE | Points program + per-branch points |
| Referral | `apps/referral` | COMPLETE | Referral doctor / program |
| Forecasting | `apps/forecasting` | COMPLETE | Demand/sales forecasting engine |
| Batches / Near-Expiry | `apps/batches` | COMPLETE | Batch + expiry tracking, near-expiry scan; **Purchase-Expiry Physical Audit** engine (`PurchaseExpiryEntry` 3-yr mirror of purchase-invoice entered expiries from main suppliers). Report = items **in stock now** whose trusted-supplier **entered expiry falls in a chosen window** (purchase date is NOT constrained), enriched with cost / value-at-risk / imported / origin **and stock-age-in-branch** (FIFO age of the oldest on-hand unit — long-sitting stock ⇒ higher near-expiry risk) for filter+sort → spawns a `stockcount` `expiry_audit` session for the physical shelf-expiry check |
| Operational Approvals | `apps/approvals` | COMPLETE | Generic approval workflows (operational + HR); desktop `/approvals` + mobile `/m/approvals` |
| Pricing Approvals (discount writeback) | `apps/discount_approvals` | COMPLETE | Approved item-discount writeback to SOFTECH (`replication.py` — reference channel) |
| Procurement | `apps/procurement` | COMPLETE | Procurement hub: history, supplier segmentation/performance, FOC, margins, optimization |
| Product Experience | `apps/product_experience` | COMPLETE | Product content admin + item/catalog intelligence |
| WhatsApp (Cloud API) | `apps/whatsapp` | COMPLETE | Campaigns + inbox (underpins Omni) |
| PBX (Issabel AMI) | `apps/pbx` | COMPLETE | Extensions + live calls (underpins Omni wallboard) |
| Enrichment / Images | `apps/enrichment`, `apps/images` | PARTIAL | Product image enrichment + image storage/OCR |
| Recommendations | `apps/recommendations` | PARTIAL | Product recommendation engine |
| Campaigns | `apps/campaigns` | PARTIAL | Campaign management |
| Cheques | `apps/cheques` | PARTIAL | Cheque planning |
| Payments | `apps/payments` | PARTIAL | Payment tracking + audit |
| Tasks | `apps/tasks` | PARTIAL | Operational tasks + schedules + dashboard |
| Dashboard | `apps/dashboard` | PARTIAL | Home dashboard aggregations |
| ERP connector | `apps/erp` | INTERNAL | SOFTECH connector helpers + ERP permission model |

---

## API INDEX

| API Group | Base Path | Module |
|-----------|-----------|--------|
| Authentication | `/api/auth/` | users |
| Two-Factor (TOTP) | `/api/auth/2fa/` | users |
| Users & Staff | `/api/users/` | users |
| Branches | `/api/branches/` | branches |
| Items / Catalog | `/api/items/` | catalog |
| Customers | `/api/customers/` | customers |
| Reservations | `/api/reservations/` | reservations |
| Demand | `/api/demand/` | demand |
| Transfers | `/api/transfers/` | transfers |
| Notifications | `/api/notifications/` | notifications |
| Vouchers | `/api/vouchers/` | vouchers |
| Incentives | `/api/incentives/` | incentives |
| Stock Count | `/api/stockcount/` | stockcount |
| Shortage | `/api/shortage/` | shortage |
| Purchasing | `/api/purchasing/` | purchasing |
| Procurement | `/api/procurement/` | purchasing |
| Invoices | `/api/invoices/` | invoices |
| Analytics | `/api/analytics/` | analytics |
| Dashboard | `/api/dashboard/` | dashboard |
| Config | `/api/config/` | config |
| Call Center | `/api/callcenter/` | callcenter |
| Follow-ups | `/api/followups/` | followups |
| Chronic | `/api/chronic/` | chronic |
| Sync | `/api/sync/` | sync |
| Finance | `/api/finance/` | finance |
| Audit | `/api/audit/` | audit |
| Products | `/api/products/` | enrichment |
| Campaigns | `/api/campaigns/` | campaigns |
| Tasks | `/api/tasks/` | tasks |
| Cheques | `/api/cheques/` | cheques |
| Delivery | `/api/delivery/` | deliveries |
| Payments | `/api/payments/` | payments |
| Recommendations | `/api/recommendations/` | recommendations |
| **POS Orders (indirect-POS writeback)** | `/api/pos-orders/` | pos_orders — list/create + `reference/` + `batches/` + `discount-suggest/` + `queue-status/` + `flush/` + `{id}/ready\|push\|cancel/` |
| Insurance | `/api/insurance/` | insurance |
| Pricing Approvals (discount writeback) | `/api/pricing-approvals/` | discount_approvals |
| Approvals (operational + HR) | `/api/approvals/` | approvals |
| Batches / Near-Expiry | `/api/batches/` | batches — list/detail + `fefo/` + `near-expiry/` + `alerts/` + `{id}/quarantine/` + **`purchase-expiry/`** (`candidates/` report · `runs/` · `sync/` admin-backfill · `spawn-count/` → stockcount) |
| Forecasting | `/api/forecasting/` | forecasting — seasonality/runs/accuracy + `kpi-board/` (doc 16 branch KPI matrix) |
| Loyalty | `/api/loyalty/` | loyalty |
| Referral | `/api/referral/` | referral |
| HR (attendance) | `/api/hr/` | hr |
| QA (inspections) | `/api/qa/` | qa |
| WhatsApp (Cloud API) | `/api/whatsapp/` | whatsapp |
| PBX (Issabel AMI) | `/api/pbx/` | pbx |
| Images | `/api/images/` | images |
| Enrichment | `/api/enrichment/` | enrichment |
| Transits (in-transit + picking/stocking export) | `/api/transits/` | transits — list/detail + mark-received + `export-picking/` (ورقة التجميع — supplying-warehouse walk) + `export-stocking/` (ورقة الترصيص — RECEIVING-branch shelf order), both single GET `{id}/…` + bulk POST `{ids}` |
| Pick zones (picking/stocking classification) | `/api/transits/pick-zones/` + `pick-rules/` + `item-overrides/` | transits — CRUD zones/rules/overrides, all **per (location, purpose)** (`?branch=&purpose=picking\|stocking`; NULL branch = default; `copy-defaults/` clones the currently-applied config). **purpose=picking** = supplying-warehouse walk; **purpose=stocking** = branch shelf order (used by ورقة الترصيص + stock-count sheets; falls back stocking→picking). Rules match name keywords OR item-master columns (`match_field`: shape/medicine_type/family/producer/origin/unit; values via `field-values/`). Plus `settings/` (price threshold), `preview/`, `uncategorized/`, `classify-items/`, `seed-defaults/`. UI: `/pick-zones` (purpose switcher) + zone column in `/products` |
| Omni (unified inbox) | `/api/omni/` | omni — conversations + timeline + reply + accounts + wallboard + automations + analytics + ai-assist |
| Social webhooks | `/api/social/` | social — Meta Graph (Messenger+IG), Telegram, TikTok(stub) inbound webhooks |
| **Customer Portal** (external) | `/api/portal/` | portal — customer self-service; **separate magic-link auth, NOT staff JWT** |

Full endpoint details: [04_API_REGISTRY.md](04_API_REGISTRY.md)

---

## DATABASE INDEX

### Core ERP Mirror Tables
| Table | Source | Key Field |
|-------|--------|-----------|
| `branches_branch` | SOFTECH | `softech_branch_id` |
| `catalog_item` | SOFTECH | `softech_id` |
| `catalog_itemstock` | SOFTECH | `(item_id, branch_id)` |
| `customers_customer` | SOFTECH | `softech_pic` (globally unique) |
| `customers_purchasehistory` | SOFTECH | `softech_invoice_id` |
| `customers_purchasehistoryline` | SOFTECH | `(purchase_id, item_id)` |
| `users_erpuser` | SOFTECH | `username` |
| `purchasing_salestransactionline` | SOFTECH | Rolling 365-day cache |

### Platform-Native Tables
| Table | Purpose |
|-------|---------|
| `reservations_reservation` | Customer reservation workflow |
| `reservations_reservationactivity` | Reservation chatter |
| `demand_demandrecord` | Structured demand with SLA |
| `demand_demanditem` | Items in a demand record |
| `demand_demandlog` | Demand chatter |
| `demand_followuptask` | Scheduled follow-up tasks |
| `demand_itemdemandstat` | Daily per-item demand aggregations |
| `transfers_transferrequest` | Inter-branch transfer requests |
| `transfers_transferrequestitem` | Transfer line items |
| `transfers_transferrequestmessage` | Transfer chatter |
| `vouchers_voucher` | Voucher master |
| `vouchers_voucherotp` | OTP records (hashed) |
| `vouchers_voucherredemptiondocument` | POS redemption documents |
| `vouchers_voucherredemption` | Immutable redemption audit |
| `incentives_incentiveprogram` | Incentive program |
| `incentives_incentiverule` | Per-item/category rules |
| `incentives_incentiveruleitem` | Multi-item rule members |
| `incentives_incentivetransaction` | Immutable incentive audit |
| `incentives_incentivesettlement` | Per-user period settlement |
| `incentives_adjustmententry` | Manual settlement adjustments |
| `stockcount_stockcountsession` | Stock count session |
| `stockcount_stockcountsnapshot` | Immutable per-item expected qty |
| `shortage_shortagelist` | Shortage document |
| `shortage_shortageitem` | Shortage line items |
| `notifications_notification` | Persistent notifications |
| `notifications_chattermessage` | Generic chatter |
| `notifications_pushsubscription` | Web Push (VAPID) browser subscriptions |
| `config_systemsetting` | Global key-value settings |
| `config_dropdownoption` | Configurable dropdown options |
| `config_pharmacyprofile` | Pharmacy singleton (pk=1) |
| `customers_customerhealthprofile` | Customer chronic condition profile |
| `purchasing_engineconfig` | Demand engine singleton (pk=1) |
| `purchasing_itemdemandmetrics` | Per-item calculated metrics |
| `purchasing_transferrecommendation` | ML transfer suggestions |

Full schema: [03_DATABASE_DICTIONARY.md](03_DATABASE_DICTIONARY.md)

---

## WORKFLOW INDEX

| Workflow | Trigger | Key States | Doc |
|----------|---------|-----------|-----|
| Reservation | Customer request | pending→fulfilled | [06_WORKFLOW_REGISTRY.md#1](06_WORKFLOW_REGISTRY.md) |
| Demand Record | Staff intake | new→fulfilled/lost | [06_WORKFLOW_REGISTRY.md#2](06_WORKFLOW_REGISTRY.md) |
| Transfer Request | Branch needs stock | draft→completed | [06_WORKFLOW_REGISTRY.md#3](06_WORKFLOW_REGISTRY.md) |
| Voucher Redemption | Customer at POS | check→OTP→document→used | [06_WORKFLOW_REGISTRY.md#4](06_WORKFLOW_REGISTRY.md) |
| Incentive Calculation | Manual/scheduled | calculate/simulate→settle→finalize | [06_WORKFLOW_REGISTRY.md#5](06_WORKFLOW_REGISTRY.md) |
| Stock Count | Manager initiates | draft→snapshot→export→upload→closed | [06_WORKFLOW_REGISTRY.md#6](06_WORKFLOW_REGISTRY.md) |
| Shortage List | Branch identifies gaps | open→submitted→resolved | [06_WORKFLOW_REGISTRY.md#7](06_WORKFLOW_REGISTRY.md) |
| ERP Sync | Scheduled / manual | incremental upsert | [06_WORKFLOW_REGISTRY.md#8](06_WORKFLOW_REGISTRY.md) |
| Customer Segmentation | Daily command | segment + churn scoring | [06_WORKFLOW_REGISTRY.md#9](06_WORKFLOW_REGISTRY.md) |

---

## SCREEN INDEX

| Screen | Route | Module | Status |
|--------|-------|--------|--------|
| Login | `/login` | Auth | COMPLETE |
| Dashboard | `/dashboard` | Dashboard | PARTIAL |
| Reservations List | `/reservations` | Reservations | COMPLETE |
| Reservations Kanban | `/reservations/kanban` | Reservations | COMPLETE |
| Reservation Detail | `/reservations/:id` | Reservations | COMPLETE |
| Demand List | `/demand` | Demand | COMPLETE |
| Demand Detail | `/demand/:id` | Demand | COMPLETE |
| Follow-ups | `/followups` | Demand | COMPLETE |
| Transfers List (requests) | `/transfers` | Transfers | COMPLETE |
| Transfer Detail | `/transfers/:id` | Transfers | COMPLETE — links to its 125 via `in_transit_docs` |
| Transfers In Transit | `/transits` (`?id=` deep-link) | Transits | COMPLETE — own page (split from the transfers tab 2026-07-25); shared `TransferModuleTabs` switcher; reciprocal links to/from the request |
| Customers List | `/customers` | Customers | COMPLETE |
| Customer Detail | `/customers/:id` | Customers | COMPLETE |
| Product Catalog | `/products` | Catalog | COMPLETE |
| Product Detail | `/products/:id` | Catalog | COMPLETE |
| Stock Count | `/stock-count` | StockCount | COMPLETE |
| Shortage | `/shortage` | Shortage | COMPLETE |
| Vouchers | `/vouchers` | Vouchers | COMPLETE |
| Incentives | `/incentives` | Incentives | COMPLETE |
| Procurement Hub | `/procurement` | Purchasing | PARTIAL |
| Analytics Hub | `/analytics` | Analytics | PARTIAL |
| Finance Hub | `/finance` | Finance | PARTIAL |
| User Management | `/users` | Users | COMPLETE |
| Permissions Matrix | `/permissions` | Users | COMPLETE |
| Sync | `/sync` | Sync | COMPLETE |
| **POS Order (indirect-POS)** | `/pos` | POS Orders | COMPLETE — create/ready/push/cancel pending order to cashier |
| Reservations List (table) | `/reservations/list` | Reservations | COMPLETE |
| Demand Dashboard | `/demand/dashboard` | Demand | COMPLETE |
| Demand Recovery | `/demand/recovery` | Demand | COMPLETE |
| Call Center | `/callcenter` | Call Center | COMPLETE |
| Call Center Cases | `/callcenter/cases` | Call Center | COMPLETE |
| Call Center Analytics | `/callcenter/analytics` | Call Center | COMPLETE |
| Insurance Claims | `/insurance` | Insurance | COMPLETE |
| Insurance Clients | `/insurance/clients` | Insurance | COMPLETE |
| Insurance Print Profiles | `/insurance/print-profiles` | Insurance | COMPLETE |
| Insurance Claim Detail / Print | `/insurance/claims/:id` (`/print`) | Insurance | COMPLETE |
| Loyalty | `/loyalty` | Loyalty | COMPLETE |
| Branch Points | `/loyalty/branch` | Loyalty | COMPLETE |
| Referral | `/referral` | Referral | COMPLETE |
| Forecasting | `/forecasting` | Forecasting | COMPLETE |
| Batches / Near-Expiry | `/batches` | Batches | COMPLETE |
| Cheque Planning | `/cheques` | Cheques | PARTIAL |
| Operational Approvals | `/approvals` | Approvals | COMPLETE |
| Pricing Approvals (discount writeback) | `/pricing-approvals` | Discount Approvals | COMPLETE |
| Procurement Hub | `/procurement` (`overview\|history\|segments\|foc\|suppliers\|margins\|optimization`) | Procurement | COMPLETE |
| Product Content Admin | `/products/:id/admin` | Product Experience | COMPLETE |
| Item Intelligence | `/products/:id/intel` | Product Experience | COMPLETE |
| Catalog Intelligence | `/catalog-intelligence` | Product Experience | COMPLETE |
| Image Enrichment | `/image-enrichment` | Enrichment | COMPLETE |
| WhatsApp Campaigns | `/campaigns` | WhatsApp | COMPLETE |
| WhatsApp Inbox | `/whatsapp/inbox` | WhatsApp | COMPLETE |
| PBX Live | `/pbx/live` | PBX | COMPLETE |
| Delivery Dashboard | `/delivery` (`dispatch\|my\|analytics`) | Delivery | COMPLETE |
| Payments | `/payments` | Payments | PARTIAL |
| Payment Audit | `/payment-audit` | Payments | PARTIAL |
| Tasks | `/tasks` (`dashboard\|schedules\|:id`) | Tasks | PARTIAL |
| Chronic Classifier | `/chronic-classifier` | Chronic | COMPLETE |
| Inventory Dashboard | `/inventory` | Catalog | COMPLETE |
| Recommendations | `/recommendations` | Recommendations | PARTIAL |
| Invoices | `/invoices` | Invoices | PARTIAL |
| HR (attendance admin) | `/hr` | HR | COMPLETE |
| ERP Permissions | `/erp-permissions` | ERP / Users | COMPLETE |
| Targets | `/targets` | Dashboard | COMPLETE |
| Branch KPI Board (تارجت/تحقيق matrix) | `/kpi-board` | Forecasting (doc 16) | COMPLETE |
| Forecast Scenarios (factor-driven targets) | `/forecast-scenarios` | Forecasting (doc 16) | COMPLETE |
| Announcements | `/announcements` | Notifications | COMPLETE |
| Unified Inbox (Omni) | `/omni/inbox` | Omni / CEP | PARTIAL (Phase 0 — WA + calls, one timeline) |
| Channel Accounts (Omni) | `/omni/accounts` | Omni / CEP | PARTIAL (Phase 1 — multi-number WhatsApp health dashboard) |
| Supervisor Wallboard (Omni) | `/omni/wallboard` | Omni / CEP | PARTIAL (Phase 2 — live calls + spy/whisper + queue/agent stats) |
| Automations (Omni) | `/omni/automations` | Omni / CEP | COMPLETE (Phase 4 — no-code rule builder) |
| Comms Analytics (Omni) | `/omni/analytics` | Omni / CEP | COMPLETE (Phase 5 — cross-channel BI) |
| Audit | `/audit` | Audit | PARTIAL |
| Account Security (2FA) | `/security` | Users (all roles) | COMPLETE |
| **Mobile — Rider** | `/rider` | Delivery (standalone) | COMPLETE |
| **Mobile — Reservations** | `/m/reservations` | Reservations (standalone mobile) | COMPLETE |
| **Mobile — New Reservation** | `/m/reservations/new` | Reservations (standalone mobile) | COMPLETE |
| **Mobile — Reservation Detail** | `/m/reservations/:id` | Reservations (standalone mobile) | COMPLETE |
| **Mobile — Transfers** | `/m/transfers` | Transfers (standalone mobile; list/new/detail + workflow) | COMPLETE |
| **Mobile — Approvals Inbox** | `/m/approvals` | Operational + pricing + HR (تشغيلية/HR toggle; admin/supervisor/purchasing) | COMPLETE |
| **Mobile — Shortage** | `/m/shortage` | Shortage logging from the floor (list/new/detail) | COMPLETE |
| **Mobile — Delivery Status** | `/m/delivery` | Live delivery order-status board (monitoring; dispatch/manager roles) | COMPLETE |
| **Mobile — Demand Intake** | `/m/demand` | Lost-sales / unmet-demand capture + queue (list/new/detail) | COMPLETE |
| **Mobile — Item/Stock Lookup** | `/m/items` | Price + stock across branches (floor lookup) | COMPLETE |
| **Mobile — Notifications** | `/m/notifications` | Alerts inbox (via top-bar bell) + Web Push (VAPID) opt-in toggle | COMPLETE |
| **Mobile — Customer Lookup** | `/m/customers` | Profile + loyalty + recent reservations | COMPLETE |
| **Mobile — My Incentives** | `/m/my-incentives` | Own incentive earnings | COMPLETE |
| **Mobile — Tasks** | `/m/tasks` | Operational tasks (list/detail/complete) | COMPLETE |
| **Mobile — Voucher Redeem** | `/m/vouchers` | OTP voucher redemption at POS | COMPLETE |
| **Mobile — Stock Count** | `/m/stock-count` | Sessions + live barcode count entry (instant variance) | COMPLETE |
| **Mobile — POS Order** | `/m/pos` | Indirect-POS order capture → push to cashier (نقطة البيع) | COMPLETE |
| **Mobile — QA Inspection** | `/m/qa` | Branch QA inspections (templates + pass/fail/na + score) | COMPLETE |
| **Mobile — Attendance** | `/m/attendance` | Geofenced GPS clock in/out | COMPLETE |
| **Public — Delivery Tracking** | `/track/:token` | Customer live order tracking (tokenized, no login) | COMPLETE |

> **Mobile web surfaces** live outside the desktop sidebar `Layout` under their own
> lean `MobileLayout` shell (phone-friendly, touch-first, plain mobile web — no PWA).
> Phone logins are redirected to `/m`. Pilot module: reservations. Details:
> [05_UI_REGISTRY.md](05_UI_REGISTRY.md#mobile-web-surfaces-standalone--no-desktop-layout)

Full screen details: [05_UI_REGISTRY.md](05_UI_REGISTRY.md)

---

## BUSINESS RULES INDEX

| Domain | Rule Count | Doc |
|--------|-----------|-----|
| Branch | 3 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Catalog | 5 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Reservation | 6 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Demand | 6 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Transfer | 8 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Customer / CRM | 9 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Voucher | 12 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Incentive | 8 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Stock Count | 5 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Shortage | 4 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Notifications | 6 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Purchasing Engine | 7 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Users / Permissions | 6 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |
| Config | 5 | [07_BUSINESS_RULES.md](07_BUSINESS_RULES.md) |

---

## KNOWN DUPLICATIONS SUMMARY

| ID | Issue | Severity |
|----|-------|----------|
| DUP-001 | Two parallel demand-intake workflows (Reservations vs Demand) | HIGH |
| DUP-002 | Four separate chatter implementations | MEDIUM |
| DUP-003 | ERP match fields duplicated on Reservation and Transfer | MEDIUM |
| DUP-004 | FollowUpTask exists in both demand and followups apps | ✅ RESOLVED (2026-06-21) — renamed demand→DemandFollowUp |
| DUP-005 | Three overlapping item search components | LOW |
| DUP-006 | Multiple stock level data sources | MEDIUM |

Full report: [08_DUPLICATION_REPORT.md](08_DUPLICATION_REPORT.md)

---

## TOP TECHNICAL DEBT

| ID | Issue | Severity |
|----|-------|----------|
| TD-C001 | No role-based UI action guards | CRITICAL |
| TD-C002 | ERP write operations are manual with no verification | CRITICAL |
| TD-C003 | No automated SLA escalation | ✅ RESOLVED (2026-06-21) |
| TD-H001 | ChatterMessage missing voice note | ✅ RESOLVED (2026-06-21) |
| TD-H002 | ERP match uses loose integer refs, not FKs | HIGH |
| TD-H005 | No React error boundaries on detail pages | HIGH |
| TD-L003 | Zero automated tests | ⚠️ OUTDATED — test suite exists (auth, permissions, reservations, transfers, vouchers+eligibility, notifications, demand SLA, analytics, finance, incentives) |

Full report: [09_TECHNICAL_DEBT_REPORT.md](09_TECHNICAL_DEBT_REPORT.md)

---

## MANAGEMENT COMMANDS REFERENCE

| Command | App | Purpose | Schedule |
|---------|-----|---------|----------|
| `segment_customers` | customers | CRM segmentation + churn scoring + health profiles | Daily |
| `tag_chronic_items` | chronic | Detect + tag chronic medications | Weekly |
| `sync_erp` | sync | SOFTECH → PostgreSQL sync | Configurable |
| `demand_engine_run` | purchasing | Run demand calculation | Daily |
| `generate_demand_records` | demand | Update ItemDemandStat | Daily |
| `generate_followup_tasks` | followups | Create scheduled follow-up tasks | Daily |
| `send_followup_reminders` | notifications | Send overdue follow-up reminders | Hourly |
| `check_demand_sla` | demand | Escalate demand-intake SLA breaches (new>10m, assigned>20m) | Hourly |
| `seed_config` | config | Seed default settings + dropdown options (incl. `replenishment_pick_zones` rules) | One-time setup |
| `seed_kpi_config` | forecasting | Seed branch-KPI config: `ChannelBucketMap` (from `SoftechPersonClassif`) + `BeautyClassRule` (doc 16); never overwrites owner edits unless `--reset-defaults` | One-time setup |
| `build_kpi_rollups` | forecasting | Materialise `KpiActualRollup` monthly branch actuals from `PurchaseHistory` (`--year --month` \| `--months N`) (doc 16) | Daily / monthly close |
| `backfill_sales_history` | sync | One-time historical `PurchaseHistory` backfill from SOFTECH month-by-month (`--months N` \| `--start --end`) + rebuild KPI rollups (doc 16 Phase 3.5) | One-time setup |
| `build_call_center_rollups` | forecasting | Call-center KPI overlay → `KpiActualRollup` (sales/profit/beauty/orders from agents `{62,63,64}` + `call_count` from Issabel CDR, `--cdr-csv` or live) (doc 16 Phase 5) | Monthly / on CDR pull |
| `sync_in_transit` | transits | SOFTECH doccode-125 → InTransitTransfer cache (expiry/batch per line; receiver = header `cust_branch_code`; receipt = 25-doc via `docnumber2` link — docnumbers are per-branch sequences, never globally unique). `--doc N --date YYYY-MM-DD` for indexed single-doc debug | Every 15 min |
| `seed_pick_zones` | transits | Bootstrap default pick zones + classification rules (PickZone tables; then managed from `/pick-zones`) | One-time setup |
| `seed_approval_workflows` | approvals | Seed approval workflows (+ HR/operational categories) | One-time setup |
| `set_branch_coords` | branches | Set branch GPS from CSV (geofence) / `--report` coverage | As needed |
| `send_test_push` | notifications | Send a test Web Push to a user's devices (real-device check) | Manual |
| `backfill_omni` | omni | Seed legacy ChannelAccounts + envelope historical WA/call data into unified timelines (idempotent) | One-time setup |
| `seed_omni_automations` | omni | Seed 4 starter automation rules (complaint/VIP/delivery/missed-call) | One-time setup |
| `flush_pos_orders` | pos_orders | Drain the offline retry queue — push `queued`/`push_failed` orders into SOFTECH | Every few min / on reconnect |
| `reconcile_pos_orders` | pos_orders | Read back pending → final SOFTECH docnumber; mark `settled` | Every 15 min |
| `pos_probe` | pos_orders | SOFTECH connectivity/diagnostic probe for the POS writer | Manual |
| `run_forecast` | forecasting | Run demand/sales forecast | Daily |
| `near_expiry_scan` | batches | Scan batches nearing expiry | Daily |
| `sync_purchase_expiry` | batches | Backfill purchase-invoice lines carrying an entered expiry (`stktrans.itemexpirydate`, doccode 10) from **main** suppliers (`SupplierSegmentation` OFFICIAL_DISTRIBUTOR+MANUFACTURER) into `PurchaseExpiryEntry` — the mirror behind the **Purchase-Expiry Physical Audit** report (`/batches` → تدقيق صلاحيات الشراء → spawns a `stockcount` `expiry_audit` session). `--years 3` \| `--from/--to` \| `--branch` \| `--categories`. Idempotent + re-runnable (re-run after re-classifying suppliers as main). Read-only SOFTECH. Needs `run_procurement_engine` run first to classify suppliers | One-time `--years 3` backfill; then **scheduled daily 07:00** (`purchase_expiry_sync` APScheduler job, rolling ~4-month incremental window, additive); re-run `--years 3` when the main-supplier set changes |
| `run_procurement_engine` | procurement | Recompute procurement/supplier metrics | Daily |
| `sync_insurance_cache` / `sync_motalbas` / `reimport_all_claims` | insurance | Sync SOFTECH motalba claims into PG mirror | Configurable |
| `seed_loyalty` | loyalty | Seed loyalty program defaults | One-time setup |
| `seed_approval_workflows` | approvals | Seed operational + HR approval workflows | One-time setup |
| `run_ami_bridge` / `sync_pbx_extensions` | pbx | Issabel AMI live-call bridge + extension sync | Long-running / periodic |

> **Web Push (VAPID):** keys live in env (`WEBPUSH_VAPID_PUBLIC_KEY` /
> `_PRIVATE_KEY` / `_ADMIN_EMAIL`). Generate with `npx web-push generate-vapid-keys`
> (or the EC P-256 → base64url method); dev keys are in `.env`. iOS delivers Web
> Push only to an **installed PWA** (Safari 16.4+).
>
> **Attendance geofence** needs branch coordinates. Fill `branch_coords_template.csv`
> (generated with all branches missing coords) and run
> `python manage.py set_branch_coords branch_coords_template.csv`.

---

## TECHNOLOGY STACK REFERENCE

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend framework | Django | 4.2.13 |
| REST API | Django REST Framework | 3.15.1 |
| Authentication | djangorestframework-simplejwt | 5.3.1 |
| Async server | Daphne (ASGI) | — |
| Real-time | Django Channels | — |
| Message broker | Redis | — |
| Task scheduling | APScheduler | 3.10.4 |
| Primary DB | PostgreSQL | — |
| ERP DB | Sybase (ODBC) | — |
| ERP connector | pyodbc | — |
| OCR | Google Gemini API + pytesseract + EasyOCR | — |
| Fuzzy matching | rapidfuzz | — |
| QR codes | qrcode | — |
| Excel | openpyxl | — |
| Image processing | Pillow + imagehash | — |
| Config | python-decouple | 3.8 |
| Frontend | React | 18.2 |
| Build tool | Vite | 5.0 |
| Routing | React Router | 6.22 |
| State management | Zustand | 4.5 |
| Server state | TanStack Query | 5.17 |
| HTTP client | Axios | 1.6.7 |
| Styling | Tailwind CSS | — |
| Date utilities | date-fns | 3.3 |
| Browser OCR | Tesseract.js | 7.0 |
