# ElRezeiky ERP Extension — System Audit
**Date:** 2026-05-25  
**Scope:** Full codebase inventory, reuse analysis, gap identification, and expansion roadmap  
**Rule:** SOFTECH Sybase = Source of Truth. SELECT ONLY. Never INSERT/UPDATE/DELETE.

---

## 1. SYSTEM INVENTORY

### 1.1 Backend Architecture

| Layer | Technology | Notes |
|-------|-----------|-------|
| Framework | Django 4.2.13 + DRF 3.15.1 | ASGI via Daphne + django-channels |
| Database | PostgreSQL (analytics + operational) | 27 schemas, ~180 tables |
| ERP Source | SOFTECH Sybase ASE | pyodbc via SELECT ONLY |
| Auth | SimpleJWT + token blacklist | RBAC via RoleModuleAccess |
| Scheduler | APScheduler (embedded) | 30-min sync cycle |
| AI/OCR | google-genai (Gemini, optional) | OCR for supplier invoices |
| Search | DRF filters + django-filter | No Elasticsearch |

### 1.2 App Inventory (27 apps)

#### CORE DATA APPS

| App | Key Models | Migrations | Maturity | Purpose |
|-----|-----------|-----------|---------|---------|
| **branches** | Branch, BranchSettings | 3 | ✅ Stable | Branch master + feature flags |
| **catalog** | Item, ItemStock, Category, ChronicMedication | 17 | ✅ Stable | Item master (33 SOFTECH columns synced) |
| **customers** | Customer, PurchaseHistory, PurchaseHistoryLine | 14 | ✅ Stable | CRM + full transaction history |
| **users** | ERPUser, StaffProfile, UserBranchAccess, RoleModuleAccess | 11 | ✅ Stable | Auth, RBAC, branch access |
| **sync** | SyncRun, SyncLog, SoftechPersonType/Classif | 3 | ✅ Stable | SOFTECH→PG ETL engine |
| **config** | SystemSetting, DropdownOption | 1 | ✅ Stable | Platform config + dropdown master |

#### INTELLIGENCE ENGINES

| App | Key Models | Migrations | Maturity | Purpose |
|-----|-----------|-----------|---------|---------|
| **purchasing** | EngineConfig, SalesTransactionLine, DemandCalculationRun, ItemDemandMetrics, ItemDemandAggregated, TransferRecommendationRun, TransferRecommendation, LostSalesRun | 13 | ✅ Stable | 13-module demand + transfer + lost-sales engine |
| **procurement** | PurchaseLine, SupplierProfile, SupplierItemMapping, ProcurementEngineRun, ProcurementSnapshot, BuyerPerformance, ProcurementAlert, SupplierSegmentation | 5 | ✅ Stable | Supplier intelligence + procurement analytics |
| **analytics** | (views only — no models) | — | ✅ Stable | Cross-module analytics: sales, customers, inventory, performance |
| **finance** | Account, FinancialPeriod, JournalEntry, AccountBalance, TreasuryMovement, ExpenseRecord, FinancialSnapshot, FinanceSyncRun | 4 | 🔶 Growing | P&L, trial balance, cash flow, snapshots |

#### OPERATIONS APPS

| App | Key Models | Migrations | Maturity | Purpose |
|-----|-----------|-----------|---------|---------|
| **reservations** | Reservation, ReservationDownpayment, ReservationStatusLog, ReservationImage, ReservationActivity | 20 | ✅ Stable | Medication reservation + fulfillment |
| **transfers** | TransferRequest, TransferRequestItem, TransferRequestMessage | 10 | ✅ Stable | Inter-branch transfer workflow + ERP match |
| **demand** | DemandRecord, DemandItem, FollowUpTask, DemandLog, ItemDemandStat | 2 | ✅ Stable | Medication demand tracking (CRM-linked) |
| **delivery** | CustomerLocation, DeliveryOrder, DeliveryAssignment, DeliveryStatusLog | 1 | 🔶 Growing | Delivery management |
| **shortage** | ShortageList, ShortageItem | 3 | ✅ Stable | Manual shortage tracking |
| **stockcount** | StockCountSession, StockCountSnapshot | 2 | ✅ Stable | Full/partial stock count with variance |
| **tasks** | OperationalTask, TaskAssignment, TaskItem, TaskMessage, TaskSchedule, TaskAuditLog | 2 | ✅ Stable | Operational task management + scheduling |

#### CUSTOMER & ENGAGEMENT APPS

| App | Key Models | Migrations | Maturity | Purpose |
|-----|-----------|-----------|---------|---------|
| **vouchers** | Voucher, VoucherAssignment, VoucherOTP, VoucherRedemptionDocument, VoucherRedemption | 4 | ✅ Stable | Full voucher lifecycle: create→assign→redeem |
| **incentives** | IncentiveProgram, IncentiveRule, IncentiveTransaction, IncentiveSettlement | 5 | ✅ Stable | Supplier/staff incentive programs |
| **chronic** | MedicationTag, ActiveIngredient, ItemIngredientMap, FollowUpProtocol | 2 | ✅ Stable | Chronic medication classifier (INN-based) |
| **followups** | ChronicMedicationProfile, FollowUpTask | 5 | ✅ Stable | Chronic patient follow-up automation |
| **callcenter** | CallLog, AddressUpdate | 2 | ✅ Stable | Call center logs + address verification |
| **notifications** | Notification, NotificationLog, ChatterMessage | 8 | ✅ Stable | In-app notifications + chatter on all objects |

#### SUPPORT APPS

| App | Key Models | Migrations | Maturity | Purpose |
|-----|-----------|-----------|---------|---------|
| **invoices** | VendorProfile, VendorItemMapping, SupplierInvoice, InvoiceLine | 8 | ✅ Stable | Supplier invoice management + OCR |
| **payments** | ExternalPayment, PaymentReconciliationLog | 1 | 🔶 Nascent | External payment tracking |
| **erp** | LocalCustomer, ERPTransaction, ERPTransactionLine | 1 | ✅ Stable | ERP transaction mirror + polling |
| **audit** | AuditLog, AbuseFlag | 2 | ✅ Stable | Platform-wide audit log + abuse detection |
| **product_experience** | ProductMapping, ProductMedia, ProductContent, ProductAttribute, ProductSEO, ProductExperience, ProductRelation, ProductAvailabilityCache, ProductReview | 2 | 🔶 Growing | Product content + experience + recommendations |

### 1.3 ETL / Sync Layer

| Component | File | Trigger | Cycle | Tables Touched |
|-----------|------|---------|-------|----------------|
| **Main SOFTECH Sync** | sync/tasks.py `run_full_sync()` | APScheduler | Every 30 min | branches, items (33 cols), ItemStock, customers, PurchaseHistory+Lines, users |
| **Demand Engine** | purchasing/engine.py `DemandEngine` | Manual trigger / management cmd | On demand | SalesTransactionLine (COPY staging), ItemDemandMetrics, ItemDemandAggregated, TransferRecommendation, LostSalesRun |
| **Transfer Engine** | purchasing/transfer_engine.py | Auto after MODULE 11 | With demand run | TransferRecommendationRun, TransferRecommendation |
| **Lost Sales Engine** | purchasing/lost_sales_engine.py | Auto after MODULE 12 | With demand run | LostSalesRun, ItemDemandMetrics (stockout fields) |
| **Procurement Engine** | procurement/engine.py | Manual trigger | On demand | PurchaseLine, SupplierProfile, SupplierItemMapping, ProcurementSnapshot, BuyerPerformance, ProcurementAlert, SupplierSegmentation |
| **Finance Sync** | finance/management `sync_finance` | Manual trigger | On demand | FinancialSnapshot, Account, AccountBalance |
| **ERP Poller** | sync/tasks.py `_poll_erp_matches()` | APScheduler | Every 30 min | ERPTransaction, transfer/reservation matches |
| **Finance Snapshot** | sync/tasks.py `_sync_finance_snapshots()` | APScheduler | Every 30 min | FinancialSnapshot |

### 1.4 Frontend Pages (56 pages)

#### Dashboards & Analytics
| Page | Route (inferred) | Analytics Source | Status |
|------|-----------------|-----------------|--------|
| DashboardPage | / | dashboard/summary | ✅ |
| SalesDashboard | /sales | analytics/sales + item operational filters | ✅ |
| InventoryDashboard | /inventory | analytics/inventory + item operational filters | ✅ |
| PurchasingDashboard | /purchasing | purchasing/* | ✅ |
| ProcurementDashboard | /procurement | procurement/dashboard | ✅ |
| FinanceDashboardPage | /finance | finance/dashboard | ✅ |
| PerformanceDashboard | /performance | analytics/performance | ✅ |
| DemandDashboardPage | /demand-dashboard | demand/dashboard | ✅ |
| DeliveryDashboard | /delivery | delivery/summary | ✅ |
| AnalyticsHubPage | /analytics | All analytics | ✅ |
| ExpenseAnalyticsPage | /finance/expenses | finance/expenses | ✅ |

#### Operations Pages
| Page | Module | Status |
|------|--------|--------|
| ReservationsPage / Kanban / Detail | reservations | ✅ |
| TransfersPage / Detail / New | transfers | ✅ |
| DemandPage / Detail | demand | ✅ |
| CustomersPage / Detail | customers | ✅ |
| DeliveryDashboard | delivery | ✅ |
| ShortagePage | shortage | ✅ |
| StockCountPage | stockcount | ✅ |
| TasksPage / Dashboard / Detail / Schedules | tasks | ✅ |
| VouchersPage | vouchers | ✅ |
| InvoicePage | invoices | ✅ |
| IncentivesPage | incentives | ✅ |
| FollowUpsPage | followups | ✅ |
| ChronicClassifierPage | chronic | ✅ |
| CallCenterPage | callcenter | ✅ |
| PaymentTracking | payments | ✅ |

#### Procurement / Finance Pages
| Page | Module | Status |
|------|--------|--------|
| ProcurementHubPage / History / Margin / Optimization | procurement | ✅ |
| SupplierPerformancePage / Segmentation | procurement | ✅ |
| FocAnalysisPage | procurement | ✅ |
| FinanceHubPage / ProfitLoss / CashFlow / ChartOfAccounts / Schema | finance | ✅ |
| PurchasingPage | purchasing | ✅ |

#### Admin / Config Pages
| Page | Module | Status |
|------|--------|--------|
| PermissionsMatrixPage | users | ✅ |
| UserManagementPage / UsersPage | users | ✅ |
| SettingsPage | config | ✅ |
| SyncPage | sync | ✅ |
| AuditPage | audit | ✅ |
| ProductCatalogPage / Detail / ContentAdmin | product_experience | ✅ |

### 1.5 Management Commands (39 commands)

| Command | App | Purpose |
|---------|-----|---------|
| run_sync | sync | Manual SOFTECH full sync |
| run_demand_engine | purchasing | Manual demand engine trigger |
| run_procurement_engine | procurement | Manual procurement engine trigger |
| sync_finance | finance | Manual finance schema sync |
| discover_finance_schema | finance | Discover SOFTECH finance tables |
| seed_permissions | users | Seed RBAC defaults (idempotent) |
| tag_chronic_items | catalog | Tag chronic medication items |
| generate_followup_tasks | followups | Generate chronic patient follow-ups |
| send_weekly_summary | notifications | Weekly KPI digest |
| send_monthly_report | notifications | Monthly management report |
| notify_stock_available | notifications | Notify when demanded item available |
| run_abuse_detection | audit | Scan for audit anomalies |
| check_unfulfilled_transfers | transfers | Alert on stale transfers |
| backfill_sales_channels | sync | Backfill sales channel codes |
| run_erp_sync | erp | Sync ERP transaction mirror |
| populate_phcodes | chronic | Populate PH codes for medications |

### 1.6 API Surface Summary

| Prefix | Endpoints | Owner App |
|--------|----------|-----------|
| /api/auth/ | login, refresh, me, change-password | users |
| /api/items/ | CRUD + stock + search + filter-options | catalog |
| /api/customers/ | CRUD + purchases + reservations + top-items | customers |
| /api/analytics/ | filter-options, sales, customers, performance, inventory, customer-search | analytics |
| /api/purchasing/ | runs, metrics, aggregated, export, config, transfer-recs, lost-sales | purchasing |
| /api/procurement/ | dashboard, suppliers, margins, returns, alerts, snapshots, segments, FOC | procurement |
| /api/finance/ | dashboard, P&L, trial-balance, cash-flow, journal, expenses, snapshots | finance |
| /api/transfers/ | CRUD + workflow (submit/approve/reject/dispatch/erp) + chatter | transfers |
| /api/reservations/ | CRUD + workflow + activities + downpayments + receipt | reservations |
| /api/demand/ | CRUD + workflow + dashboard | demand |
| /api/notifications/ | list, read, delete, chatter, preferences | notifications |
| /api/vouchers/ | CRUD + assign + redeem + OTP | vouchers |
| /api/invoices/ | CRUD + OCR + line management + anomalies | invoices |
| /api/incentives/ | programs, rules, transactions, settlements | incentives |
| /api/tasks/ | CRUD + assignments + schedules + dashboard | tasks |
| /api/stockcount/ | sessions + snapshots | stockcount |
| /api/shortage/ | lists | shortage |
| /api/delivery/ | orders + assign/dispatch/complete | delivery |
| /api/payments/ | list + confirm/reconcile | payments |
| /api/sync/ | status + trigger + logs | sync |
| /api/branches/ | CRUD + settings | branches |
| /api/chronic/ | tags + ingredients + protocols + classifiers | chronic |
| /api/followups/ | chronic profiles + tasks | followups |
| /api/callcenter/ | calls + address-updates | callcenter |
| /api/audit/ | logs + flags | audit |
| /api/products/ | content + media + attributes + SEO + recommendations | product_experience |
| /api/erp/ | transactions + local-customers | erp |

---

## 2. REUSE PLAN

### 2.1 Category: KEEP (Stable, No Action)

| Module | Reason |
|--------|--------|
| sync/tasks.py ETL | Comprehensive 8-source sync. DO NOT duplicate. Extend only. |
| purchasing/engine.py (13 modules) | Complete demand→transfer→lost-sales pipeline. Add modules ≥14 here. |
| procurement/engine.py | Full supplier intelligence pipeline. Extend for purchase automation. |
| analytics/views.py | 4 major endpoints with full filter support. Add tabs, not new pages. |
| customers/* | Full CRM + purchase history. Rich data for customer recovery. |
| catalog/Item (33 fields) | Complete SOFTECH mirror. No new item tables needed. |
| notifications/* | Full notification lifecycle + chatter on all objects. Reuse for all alerts. |
| finance/* | Full P&L + cash flow + snapshots. Extend for branch contribution. |
| transfers/* | Full approval workflow + ERP match. Reuse as execution layer for recommendations. |
| tasks/* | Complete operational task engine with scheduling. Reuse for automation workflows. |
| vouchers/* | Full voucher lifecycle. Reuse for markdown/liquidation vouchers. |
| audit/* | Platform-wide audit. Hook shrinkage detection here. |
| stockcount/* | Variance-ready stock count. Extend for shrinkage intelligence. |

### 2.2 Category: EXTEND (Add Capability)

| Module | What to Add | Business Value |
|--------|------------|---------------|
| **purchasing/engine.py** | MODULE 14: Near-Expiry Recovery Engine (use procurement/expiry_return_analysis as input) | Reduce expiry waste |
| **purchasing/engine.py** | MODULE 15: Purchase Draft Generator (from ItemDemandMetrics gap + supplier mapping) | Reduce manual PO work |
| **purchasing/views.py** | Transfer Recommendations frontend tab in PurchasingDashboard | Activate existing MODULE 12 data |
| **purchasing/views.py** | Lost Sales frontend tab in PurchasingDashboard | Activate existing MODULE 13 data |
| **analytics/views.py** | `customer_churn()` endpoint: customers with last_purchase > 30/60/90 days | Customer recovery |
| **analytics/views.py** | `branch_contribution()` endpoint: true margin = revenue − COGS − branch_expenses | Branch profitability |
| **analytics/views.py** | `insurance_analytics()` endpoint: revenue/margin by insurance_type | Insurance optimizer |
| **analytics/views.py** | `inventory_investment()` endpoint: capital tied per ABC class + liquidation candidates | Capital unlock |
| **analytics/views.py** | `assortment_gap()` endpoint: cross-sell opportunities + duplicate INN detection | Assortment optimization |
| **procurement/engine.py** | Add `generate_purchase_draft()` step: create PurchaseDraft from metrics + supplier mapping | Purchase automation |
| **procurement/views.py** | Add `near_expiry_stock()` view: items with low coverage_months from ItemDemandMetrics | Near-expiry recovery |
| **stockcount/views.py** | Add `shrinkage_analysis()`: cross-period variance trend + anomaly scoring | Shrinkage intelligence |
| **finance/views.py** | Extend `finance_dashboard()` with branch contribution section | Branch profitability |
| **product_experience/views.py** | Extend `product_recommend()` to use demand velocity + sales coach logic | Sales coach |
| **notifications system** | Add automated churn recovery notification trigger | Customer recovery |
| **SalesDashboard.jsx** | Add item operational filters (DONE ✅), add cross-sell/assortment gap tab | Commercial intelligence |
| **InventoryDashboard.jsx** | Add item operational filters (DONE ✅), add near-expiry tab, investment tab | Inventory optimization |
| **PurchasingDashboard.jsx** | Add Transfer Recs tab + Lost Sales tab (backend exists, no frontend yet) | Activate engine output |

### 2.3 Category: MERGE (Consolidate Duplicates)

| Issue | Action |
|-------|--------|
| `demand/FollowUpTask` AND `tasks/OperationalTask` — two task systems | Use tasks/OperationalTask as the canonical task. demand/FollowUpTask is specialized but should link to tasks. |
| `sync/tasks.py send_followup_reminders` AND `notifications/management/send_followup_reminders` — DUPLICATE command | Remove sync version, keep notifications version. |
| `purchasing/filter_options` AND `catalog/filter_options` — overlapping item filter options | Already reusing correctly (purchasing imports from catalog). No merge needed. |
| `demand/ItemDemandStat` AND `purchasing/ItemDemandMetrics` — similar demand metrics | ItemDemandStat is customer-demand (shortage requests). ItemDemandMetrics is inventory demand (engine output). Different purposes. Keep both, document clearly. |

### 2.4 Category: DEPRECATE (No Immediate Action, Flag for Review)

| Item | Reason | Action |
|------|--------|--------|
| `erp/ERPTransaction` direct mirror | procurement/PurchaseLine + sync/tasks already cover most cases | Audit usage; consider removal after next cycle |
| `shortage/ShortageList` | Superseded by demand engine's lost sales + ItemDemandMetrics gap | Keep for manual ops, but automate population from demand engine |
| `product_experience/ProductAvailabilityCache` | ItemStock is the source of truth; cache may diverge | Validate sync cadence or remove |

### 2.5 Category: REMOVE (Confirmed Duplicates)

| Item | Reason |
|------|--------|
| `sync/management/commands/send_followup_reminders.py` | EXACT DUPLICATE of `notifications/management/commands/send_followup_reminders.py` |

---

## 3. GAP ANALYSIS — HIGH-ROI MODULES

### Module Status Against Business Brief

| # | Module | Status | Backend | Frontend | Priority |
|---|--------|--------|---------|---------|---------|
| 1 | Commercial Opportunity Engine | 🟡 Partial | procurement/optimization (basic) | None | P1 |
| 2 | Assortment Optimization | 🟡 Partial | chronic/ItemIngredientMap, shortage | None | P2 |
| 3 | Customer Recovery | 🟡 Partial | analytics/customer_analytics (RFM) | None | P1 |
| 4 | Branch Profitability | 🟡 Partial | finance/FinancialSnapshot, analytics/by_branch | ProcurementDashboard (partial) | P1 |
| 5 | Inventory Investment Engine | 🟡 Partial | ItemDemandMetrics (surplus), FinancialSnapshot | InventoryDashboard (no capital tab) | P2 |
| 6 | Transfer Recommendation | 🟢 Backend Complete | MODULE 12 + TransferRecommendation model | ❌ No frontend tab | P1 HIGH |
| 7 | Shrinkage Intelligence | 🔴 Minimal | stockcount/StockCountSnapshot (variance) | StockCountPage (no trend analysis) | P3 |
| 8 | Purchase Automation | 🟡 Partial | ProcurementAlert + metrics available | ProcurementOptimizationPage (manual) | P2 |
| 9 | Sales Coach | 🟡 Partial | product_experience/recommend, analytics/top_items | None | P3 |
| 10 | Insurance Optimizer | 🔴 Minimal | Item.insurance_type field + hi_types sync | Filter only (AdvancedFiltersBar) | P3 |
| 11 | Near Expiry Recovery | 🟡 Partial | procurement/expiry_return_analysis | FocAnalysisPage (partial) | P2 |
| 12 | Management Copilot | 🔴 Minimal | All analytics APIs available | AnalyticsHubPage (navigation only) | P4 |
| 13 | Lost Sales Intelligence | 🟢 Backend Complete | MODULE 13 + LostSalesRun model | ❌ No frontend tab | P1 HIGH |
| 14 | Near-Expiry Stock Alert | 🔴 Missing | ItemDemandMetrics.coverage_months available | None | P2 |
| 15 | Purchase Draft Generation | 🔴 Missing | All data available (metrics + supplier mapping) | None | P2 |

---

## 4. CRITICAL GAPS (Immediately Actionable)

### GAP-1: Transfer Recommendations have NO frontend
- **Backend:** `TransferRecommendationRun` + `TransferRecommendation` (MODULE 12) — COMPLETE
- **API:** `/api/purchasing/transfer-recs/`, `/api/purchasing/transfer-recs/run/`, `/api/purchasing/transfer-recs/summary/` — COMPLETE
- **Frontend:** ZERO — no tab in PurchasingDashboard, no page
- **Fix:** Add "التوصيات التحويلية" tab to PurchasingDashboard showing summary KPIs + filterable DataTable

### GAP-2: Lost Sales Intelligence has NO frontend
- **Backend:** `LostSalesRun` (MODULE 13) with `items_affected`, `total_lost_revenue`, `root_cause_breakdown` — COMPLETE
- **API:** `/api/purchasing/lost-sales/run/`, `/api/purchasing/lost-sales/summary/` — COMPLETE
- **Frontend:** ZERO — no tab in PurchasingDashboard, no visualization
- **Fix:** Add "المبيعات الضائعة" tab to PurchasingDashboard showing lost revenue KPIs + root cause breakdown + item drill-down

### GAP-3: Customer Churn / Recovery — data exists, no detection
- **Available:** PurchaseHistoryLine with `invoice_date`, Customer model, PurchaseHistory aggregations
- **Missing:** Endpoint to identify customers with last purchase > N days
- **Fix:** Add `customer_churn()` to analytics/views.py + "العملاء الغائبين" tab in CustomersDashboard

### GAP-4: Branch True Profitability — scattered, not consolidated
- **Available:** finance/FinancialSnapshot (branch dimension), analytics/sales/by_branch, analytics/inventory/by_branch, procurement/branch_procurement
- **Missing:** Single view combining: net_revenue − COGS − branch_expenses = branch_contribution_margin
- **Fix:** Add `branch_contribution()` endpoint in analytics/views.py + tab in SalesDashboard or FinanceDashboard

### GAP-5: Near-Expiry Stock — coverage_months available, not surfaced
- **Available:** `ItemDemandMetrics.coverage_months` (already computed by demand engine), procurement/expiry_return_analysis (past expiry returns)
- **Missing:** Items with `coverage_months > reasonable_shelf_life` flagged as near-expiry risk
- **Fix:** Extend inventory_analytics() to include near_expiry section + tab in InventoryDashboard

### GAP-6: Capital Tied in Inventory — data available, not computed
- **Available:** ItemDemandMetrics.current_stock × Item.pack_price = capital_tied; surplus already flagged
- **Missing:** Aggregated capital-tied view by ABC class + liquidation priority
- **Fix:** Add `inventory_investment()` endpoint + "رأس المال الراكد" tab in InventoryDashboard

### GAP-7: Duplicate Management Command
- `sync/management/commands/send_followup_reminders.py` is identical to `notifications/management/commands/send_followup_reminders.py`
- **Fix:** Delete the sync version

### GAP-8: Assortment Intelligence — INN data exists, not used for gaps
- **Available:** `chronic/ItemIngredientMap` (INN → items), `catalog/ChronicMedication`, `demand/DemandRecord`
- **Missing:** Items demanded but not in catalog, duplicate-INN brands, gap-vs-competitor assortment
- **Fix:** Add `assortment_gaps()` view using DemandRecord items not in Item catalog + INN duplicates from ItemIngredientMap

---

## 5. DATA FLOW MAP

```
SOFTECH Sybase ASE (SELECT ONLY)
    │
    ├── sync/tasks.py (30 min) ──────────────────────────────────────────┐
    │   branches → Branch                                                  │
    │   items (33 cols) → Item + ItemStock                                │
    │   customers → Customer + PurchaseHistory + PurchaseHistoryLine      │
    │   users → ERPUser                                                    │
    │   (sales already done by Demand Engine via COPY staging)            │
    │                                                                      │
    ├── purchasing/engine.py (on demand) ──────────────────────────────── │
    │   MODULE 2: Sybase stktrans → SalesTransactionLine (COPY)          │
    │   MODULES 3-11: SalesTransactionLine → ItemDemandMetrics           │
    │   MODULE 12: ItemDemandMetrics → TransferRecommendation            │  ←── GAP-1
    │   MODULE 13: ItemDemandMetrics → LostSalesRun                      │  ←── GAP-2
    │                                                                      │
    ├── procurement/engine.py (on demand) ─────────────────────────────── │
    │   Sybase stktransm → PurchaseLine                                   │
    │   PurchaseLine → SupplierProfile → BuyerPerformance                │
    │   → ProcurementSnapshot → ProcurementAlert                          │
    │   → SupplierSegmentation                                            │
    │                                                                      │
    └── finance/sync (on demand) ──────────────────────────────────────── │
        Sybase finance tables → Account + JournalEntry + AccountBalance   │
        → FinancialSnapshot (branch × period)                             │
                                                                           │
PostgreSQL Analytics Layer ◄──────────────────────────────────────────────┘
    │
    ├── analytics/views.py ── sales, customers, performance, inventory
    ├── purchasing/views.py ── demand metrics, transfer recs, lost sales
    ├── procurement/views.py ── supplier analysis, margins, returns
    └── finance/views.py ─── P&L, cash flow, trial balance
    
Notifications ←── All engines + sync → Notification model → Frontend bell
```

---

## 6. MODULE EXTENSION ROADMAP

### Phase 1 — Activate Dormant Backend (2-3 days each, P1)

These modules have complete backends but ZERO frontend. Pure UI work.

#### 6.1 Transfer Recommendations Tab (PurchasingDashboard)
- **Extend:** `PurchasingDashboard.jsx` — add tab "التوصيات التحويلية"
- **API:** Already exists — `purchasingApi.transferRecRun()`, `transferRecSummary()`, `transferRecs()`
- **UI:** Summary KPIs (total recs, pending, total value) + DataTable with approve/reject actions
- **Link to:** `TransferRequest` creation — "تحويل للتنفيذ" button calls `transfersApi.create()`
- **Zero new backend code**

#### 6.2 Lost Sales Intelligence Tab (PurchasingDashboard)
- **Extend:** `PurchasingDashboard.jsx` — add tab "المبيعات الضائعة"
- **API:** Already exists — `purchasingApi.lostSalesRun()`, `purchasingApi.lostSalesSummary()`
- **UI:** KPI cards (total_lost_revenue, items_affected, top root causes pie) + item drill-down table
- **Zero new backend code**

### Phase 2 — Extend Analytics (3-5 days each, P1-P2)

#### 6.3 Customer Churn Detection
- **Extend:** `analytics/views.py` — add `customer_churn()` view
- **Query:** GROUP BY customer from PurchaseHistory, filter last_purchase_date < N days ago
- **Output:** { total_at_risk, by_tier: [30d, 60d, 90d], top_churned_customers }
- **Extend:** `SalesDashboard.jsx` — add "العملاء الغائبون" tab
- **Trigger:** Add scheduled notification for customers > 60 days silent

#### 6.4 Branch True Contribution
- **Extend:** `analytics/views.py` — add `branch_contribution()` view
- **Query:** JOIN analytics/sales/by_branch + finance/ExpenseRecord (by branch) + finance/FinancialSnapshot
- **Output:** { branch, gross_revenue, cogs, gross_margin, branch_expenses, contribution_margin, contribution_pct }
- **Extend:** `SalesDashboard.jsx` or `FinanceDashboard.jsx` — add "ربحية الفروع" tab

#### 6.5 Inventory Investment & Near-Expiry
- **Extend:** `analytics/views.py `— extend `inventory_analytics()` with two new sections:
  1. `capital_tied`: SUM(current_stock × pack_price) grouped by ABC + branch
  2. `near_expiry_risk`: items where coverage_months > 6 (or configurable threshold) — already in ItemDemandMetrics
- **Extend:** `InventoryDashboard.jsx` — add "رأس المال الراكد" tab + "قرب الانتهاء" tab

### Phase 3 — New Engine Modules (5-7 days each, P2)

#### 6.6 MODULE 14: Near-Expiry Recovery Engine (purchasing/engine.py)
- **New class:** `NearExpiryEngine` in `purchasing/near_expiry_engine.py`
- **Input:** ItemDemandMetrics.coverage_months + Item.pack_price
- **Logic:** Flag items where coverage_months > configurable_threshold (default: 6)
- **Output:** New model `NearExpiryRisk` — item, branch, current_stock, coverage_months, capital_at_risk, recommended_action (transfer/markdown/return)
- **Orchestration:** Run after MODULE 13, notify procurement team

#### 6.7 MODULE 15: Purchase Draft Generator (purchasing/engine.py + procurement)
- **New class:** `PurchaseDraftEngine` in `purchasing/purchase_draft_engine.py`
- **Input:** ItemDemandMetrics.gap (where gap > 0) + SupplierItemMapping.preferred_supplier
- **Output:** New model `PurchaseDraft` — item, supplier, recommended_qty, estimated_value, priority, status (draft/submitted/approved/cancelled)
- **Approval flow:** PATCH /api/purchasing/drafts/{id}/approve/ (admin only)
- **Export:** Excel export for ERP data entry

#### 6.8 Assortment Gap Detection
- **Extend:** `analytics/views.py` — add `assortment_gap()` view
- **Logic 1:** Items in DemandRecord that have no match in catalog (Item) = missing assortment
- **Logic 2:** Items sharing same INN via ItemIngredientMap — flag INN clusters with > N brands
- **Logic 3:** High-demand items (top 20% of lost sales) not stocked in all branches
- **Output:** { missing_items, duplicate_inns, branch_assortment_gaps }

### Phase 4 — Intelligence Automation (7-14 days each, P3-P4)

#### 6.9 Insurance Analytics
- **Extend:** `analytics/views.py` — add `insurance_analytics()` view
- **Query:** PurchaseHistoryLine JOIN Item (insurance_type) — revenue/margin/qty by insurance_type
- **Extend:** `SalesDashboard.jsx` — add "التأمين والتعاقدات" tab

#### 6.10 Shrinkage Intelligence
- **Extend:** `stockcount/views.py` — add cross-period variance analysis
- **Query:** Compare StockCountSnapshot(variance_type='deficit') across sessions, flag recurring patterns
- **Link to:** AuditLog for anomaly detection

#### 6.11 Sales Coach Recommendations
- **Extend:** `product_experience/views.py` — upgrade `product_recommend()` to use demand velocity
- **Logic:** Top-margin items with declining sales → push recommendation
- **Output:** Per-branch "push list" based on ABC class + margin + recent velocity

#### 6.12 Management Copilot (Phase 4, P4)
- **Extend:** `AnalyticsHubPage.jsx` — add natural language query interface
- **Backend:** New `analytics/copilot.py` using Gemini API (already in requirements)
- **Input:** Pre-computed KPI deltas from all snapshots
- **Output:** Explanation of drops + recommended actions in Arabic

---

## 7. NEW TABLES REQUIRED

| Table | App | Purpose | New/Extend |
|-------|-----|---------|-----------|
| `NearExpiryRisk` | purchasing | Per-item near-expiry risk + recommended action | NEW |
| `PurchaseDraft` | purchasing | Auto-generated purchase draft from demand gap | NEW |
| `PurchaseDraftLine` | purchasing | Line items for purchase draft | NEW |
| `AssortmentGap` | analytics OR purchasing | Missing/duplicate assortment entries | NEW |
| `CustomerChurnSnapshot` | customers | Periodic churn snapshot per customer tier | NEW |
| `BranchContributionSnapshot` | finance | Pre-computed branch contribution (reuse FinancialSnapshot structure) | EXTEND FinancialSnapshot |

---

## 8. WORKFLOW ORCHESTRATION MAP

```
SOFTECH ERP (source)
    │
    └──► Demand Engine (daily)
              │
              ├──► Transfer Recommendations (MODULE 12)
              │         │
              │         └──► [GAP-1] Frontend tab → User approves → TransferRequest created
              │                                                          │
              │                                                          └──► ERP Dispatch
              │
              ├──► Lost Sales Intelligence (MODULE 13)
              │         │
              │         └──► [GAP-2] Frontend tab → Notification → Demand Record
              │                                                          │
              │                                                          └──► Procurement alert
              │
              ├──► [NEW] Near-Expiry Recovery (MODULE 14)
              │         │
              │         ├──► Transfer recommendation (source → branch with shorter stock)
              │         └──► Markdown voucher → Voucher platform (existing)
              │
              └──► [NEW] Purchase Draft (MODULE 15)
                        │
                        └──► Draft → Approval → Export Excel → ERP entry

Customer Data (sync)
    │
    └──► [GAP-3] Churn Detection
              │
              └──► Notification → WhatsApp/SMS campaign
                        │
                        └──► Voucher assignment (existing vouchers platform)

Procurement Engine (daily)
    │
    ├──► SupplierProfile → ProcurementAlert → Notification
    │
    ├──► [GAP-5] Near-expiry returns → Recovery recommendations
    │
    └──► [NEW] Purchase Automation → PurchaseDraft → Approval workflow

Finance Sync
    │
    └──► [GAP-4] Branch contribution = revenue − COGS − expenses → Dashboard tab
```

---

## 9. SUCCESS KPIs

| KPI | Target | Current State |
|-----|--------|--------------|
| Duplicated code | < 5% | ~2% (1 duplicate cmd found) |
| Duplicated ETL | 0 | ✅ 0 (sync + demand + procurement well-separated) |
| Duplicated pages | 0 | ✅ 0 |
| Backend modules with no frontend | 0 | ❌ 2 (Transfer Recs, Lost Sales) |
| P1 business gaps covered | 100% | ❌ ~40% |
| Engine modules | ≥15 | Current: 13 (need 14, 15) |
| Automated notifications | All critical flows | ❌ Manual triggers only for most |

---

## 10. IMPLEMENTATION PRIORITY QUEUE

| Priority | Module | Effort | Business Value | Dependencies |
|---------|--------|--------|---------------|-------------|
| **P1-A** | Transfer Recs Frontend Tab | 0.5 day | HIGH — activates dormant MODULE 12 | None (API complete) |
| **P1-B** | Lost Sales Frontend Tab | 0.5 day | HIGH — activates dormant MODULE 13 | None (API complete) |
| **P1-C** | Duplicate command removal | 0.1 day | LOW but clean | None |
| **P1-D** | Customer Churn Analytics | 2 days | HIGH — customer retention | analytics/views.py + SalesDashboard |
| **P1-E** | Branch Contribution Tab | 2 days | HIGH — financial clarity | analytics/views.py + finance/views.py |
| **P2-A** | Inventory Investment Tab | 1.5 days | HIGH — capital unlock | analytics/views.py + InventoryDashboard |
| **P2-B** | Near-Expiry Stock Tab | 1.5 days | HIGH — waste reduction | analytics/views.py + InventoryDashboard |
| **P2-C** | MODULE 14: Near-Expiry Engine | 3 days | HIGH — proactive recovery | purchasing/engine.py |
| **P2-D** | MODULE 15: Purchase Draft | 4 days | VERY HIGH — automation | purchasing/ + procurement/ |
| **P2-E** | Assortment Gap Detection | 2 days | MEDIUM — revenue expansion | analytics/views.py |
| **P3-A** | Insurance Analytics Tab | 1.5 days | MEDIUM — contract profitability | analytics/views.py + SalesDashboard |
| **P3-B** | Shrinkage Intelligence | 3 days | MEDIUM — loss reduction | stockcount/ + audit/ |
| **P3-C** | Sales Coach | 3 days | MEDIUM — revenue per visit | product_experience/ |
| **P4-A** | Management Copilot | 7 days | HIGH (strategic) — AI layer | All analytics APIs + Gemini |
