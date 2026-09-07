# 05 — UI Registry

All frontend screens and their metadata.  
Framework: React 18 + React Router 6 + TanStack Query 5 + Zustand + Tailwind CSS

---

## Routing Architecture

```
/login                    → LoginPage (public; 2-step when 2FA applies — see Auth note)
/ (protected + Layout)
  /dashboard              → DashboardPage
  /security               → SecurityPage (2FA self-service; all roles)
  /reservations           → ReservationsPage
  /reservations/kanban    → ReservationsKanban
  /reservations/list      → ReservationsPage (table)
  /reservations/new       → NewReservationPage
  /reservations/:id       → ReservationDetailPage
  /demand                 → DemandPage
  /demand/dashboard       → DemandDashboardPage
  /demand/recovery        → DemandRecoveryPage
  /demand/:id             → DemandDetailPage
  /followups              → FollowUpsPage
  /transfers              → TransfersPage
  /transfers/new          → NewTransferPage
  /transfers/:id          → TransferDetailPage
  /customers              → CustomersPage
  /customers/:id          → CustomerDetailPage
  /chronic-classifier     → ChronicClassifierPage
  /callcenter             → CallCenterPage
  /callcenter/cases       → CasesPage
  /callcenter/analytics   → CallCenterAnalyticsPage
  /campaigns              → WhatsAppCampaignPage
  /whatsapp/inbox         → WhatsAppInboxPage
  /omni/inbox             → OmniInboxPage
  /omni/accounts          → OmniAccountsPage
  /omni/wallboard         → OmniWallboardPage
  /omni/automations       → OmniAutomationsPage
  /omni/analytics         → OmniAnalyticsPage
  /pbx/live               → PbxLivePage
  /loyalty                → LoyaltyPage
  /loyalty/branch         → BranchPointsPage
  /referral               → ReferralPage
  /products               → ProductCatalogPage
  /products/:id           → ProductDetailPage
  /products/:id/admin     → ProductContentAdminPage
  /products/:id/intel     → ItemIntelPage
  /catalog-intelligence   → CatalogIntelligencePage
  /image-enrichment       → ImageEnrichmentPage
  /recommendations        → RecommendationsPage
  /inventory              → InventoryDashboard
  /stock-count            → StockCountPage
  /shortage               → ShortagePage
  /pos                    → POSOrderPage (indirect-POS → cashier writeback)
  /pricing-approvals      → PricingApprovalsPage (discount writeback)
  /purchasing             → PurchasingDashboard + PurchasingPage
  /procurement            → ProcurementHubPage (tabbed)
    /procurement/overview
    /procurement/history
    /procurement/segments
    /procurement/foc
    /procurement/suppliers
    /procurement/margins
    /procurement/optimization
    /procurement/mappings
  /invoices               → InvoicePage
  /incentives             → IncentivesPage
  /insurance              → InsuranceClaimsPage
    /insurance/clients            → InsuranceClientsPage
    /insurance/print-profiles     → InsurancePrintProfilesPage
    /insurance/claims/:id         → InsuranceClaimDetailPage
    /insurance/claims/:id/print   → InsurancePrintPage
  /analytics              → AnalyticsHubPage (tabbed)
    /analytics/sales      → SalesDashboard
    /analytics/performance → PerformanceDashboard
    /analytics/reservations → ReservationsAnalyticsPage
    /analytics/transfers  → TransfersAnalyticsPage
  /finance                → FinanceHubPage (tabbed)
    /finance/dashboard    → FinanceDashboardPage
    /finance/coa          → ChartOfAccountsPage
    /finance/pnl          → ProfitLossPage
    /finance/cashflow     → CashFlowPage
    /finance/expenses     → ExpenseAnalyticsPage
    /finance/schema       → FinanceSchemaPage
  /tasks                  → TasksPage
  /tasks/dashboard        → TaskDashboardPage
  /tasks/schedules        → TaskSchedulesPage
  /tasks/:id              → TaskDetailPage
  /delivery               → DeliveryDashboard
  /delivery/dispatch      → DispatchBoard
  /delivery/my            → DriverDeliveryApp
  /delivery/analytics     → DeliveryAnalyticsPage
  /payments               → PaymentTracking
  /payment-audit          → PaymentAuditPage
  /vouchers               → VouchersPage
  /cheques                → ChequePlanningPage
  /batches                → BatchesPage (near-expiry / FEFO)
  /forecasting            → ForecastingPage
  /targets                → TargetsPage
  /announcements          → AnnouncementsPage
  /approvals              → ApprovalsPage (operational + HR)
  /hr                     → HRPage
  /audit                  → AuditPage (admin only)
  /users                  → UserManagementPage (admin only)
  /permissions            → PermissionsMatrixPage (admin only)
  /erp-permissions        → ErpPermissionsPage (admin only)
  /pick-zones             → PickZonesPage (picking/stocking classification)
  /settings               → SettingsPage
  /sync                   → SyncPage (admin only)

/ (protected, NO desktop Layout — standalone mobile web surfaces)
  /rider                  → RiderLayout > DriverDeliveryApp   (delivery riders)
  /m (MobileLayout, bottom-tab shell — tabs role-filtered)
    /m/pos                → MobilePOSOrderPage        (indirect-POS → cashier; نقطة البيع)
    /m/reservations       → MobileReservationsPage   (queue + status chips)
    /m/reservations/new   → MobileNewReservationPage (create + dedup/force)
    /m/reservations/:id   → MobileReservationDetailPage (detail + status progression)
    /m/transfers          → MobileTransfersPage      (queue + status chips)
    /m/transfers/new      → MobileNewTransferPage     (multi-item create)
    /m/transfers/:id      → MobileTransferDetailPage  (detail + workflow actions)
    /m/approvals          → MobileApprovalsPage       (operational inbox; admin/supervisor/purchasing)
    /m/shortage           → MobileShortagePage        (shortage lists queue)
    /m/shortage/new       → MobileNewShortagePage     (create list)
    /m/shortage/:id       → MobileShortageDetailPage  (log items: quick-add + bulk paste + submit)
    /m/delivery           → MobileDeliveryPage        (live order-status board; manager/dispatch roles)
    /m/delivery/:id       → MobileDeliveryDetailPage  (order detail + status timeline; read-focused)
    /m/demand             → MobileDemandPage          (lost-sales / unmet-demand queue)
    /m/demand/new         → MobileNewDemandPage       (counter capture: phone + items + priority/source)
    /m/demand/:id         → MobileDemandDetailPage    (detail + items + notes thread)
    /m/items              → MobileItemsPage           (item/stock lookup: price + stock across branches)
    /m/notifications      → MobileNotificationsPage   (alerts inbox; reached via top-bar 🔔 bell)
    /m/customers          → MobileCustomersPage       (lookup → profile + loyalty + recent reservations)
    /m/my-incentives      → MobileMyIncentivesPage    (own incentive earnings)
    /m/tasks              → MobileTasksPage           (operational tasks queue)
    /m/tasks/:id          → MobileTaskDetailPage      (checklist + complete + chatter)
    /m/vouchers           → MobileVoucherRedeemPage   (voucher OTP redemption flow)
    /m/stock-count        → MobileStockCountPage      (stock-count sessions monitor)
    /m/stock-count/:id    → MobileStockCountDetailPage(live barcode count + variance)
    /m/qa                 → MobileQAPage              (branch QA inspections list/new)
    /m/qa/:id             → MobileQADetailPage        (checklist pass/fail/na + score)
    /m/attendance         → MobileAttendancePage      (geofenced clock in/out)
```

> **Mobile surfaces.** The desktop `Layout` uses a hover-driven sidebar that
> doesn't work on touch, so phone-friendly screens are built as *separate* routes
> with their own lean shell (`MobileLayout`, generalizing `RiderLayout`) — thin,
> task-shaped views over the **existing** APIs, never a port of the desktop page.
> `LoginPage` detects a phone viewport (`max-width: 768px`) and redirects non-rider
> logins to `/m` (riders → `/rider`, desktop → `/dashboard`). Plain mobile web
> (no PWA). Pilot surface: reservations. Security is staged — low-sensitivity
> surfaces ship on existing JWT; 2FA is added before approvals/pricing surfaces.

> **External customer portal (`/portal/*`).** A separate, *customer-facing* PWA —
> NOT staff. Public routes (`/portal/login`, `/portal/auth/:token`) sit outside
> `RequireAuth`; authenticated screens live under a dedicated `PortalLayout`
> (own RTL shell + bottom nav, NOT `MobileLayout`). It uses its own API client
> (`src/portal/portalApi.js`) with the `Authorization: Portal <token>` scheme and
> its own `localStorage` key (`portal_session_token`) — fully isolated from staff
> JWT. Login is a WhatsApp **magic link**; the session is a stateless signed token.
> Installable PWA via `public/manifest.webmanifest` + `public/portal-sw.js`.

---

## Screen Inventory

### Core

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| LoginPage | `/login` | JWT auth + 2-step 2FA challenge/enrollment | `/api/auth/login/`, `/api/auth/2fa/*` | COMPLETE |
| DashboardPage | `/dashboard` | KPI overview | `/api/dashboard/` | PARTIAL |
| SettingsPage | `/settings` | User preferences | `/api/config/` | PARTIAL |
| SecurityPage | `/security` | TOTP 2FA self-service (enroll / disable / backup codes) | `/api/auth/2fa/{status,setup,enable,disable}/` | COMPLETE |

> **Auth / 2FA.** Login is two-step when 2FA applies. `POST /auth/login/` returns
> `{mfa_required, mfa_token}` (enrolled) or `{mfa_setup_required, mfa_token}`
> (approval role — admin/supervisor/purchasing — once the `security.mfa_enforced`
> config flag is on but the user hasn't enrolled). The client exchanges the
> short-lived pre-auth `mfa_token` at `POST /auth/2fa/verify/` (TOTP or backup
> code) for JWTs. `remember_device` returns a 30-day trusted-device token that
> skips the challenge. Enrollment QR/secret comes from `/auth/2fa/setup/`,
> confirmed at `/auth/2fa/enable/`. Shared component: `TwoFactorSetup.jsx`.
> Default is grace period (flag off) — enrollment is opt-in until flipped.

---

### Reservations Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| ReservationsPage | `/reservations` | List view with filters | `/api/reservations/` | COMPLETE |
| ReservationsKanban | `/reservations/kanban` | Kanban board by status | `/api/reservations/kanban/` | COMPLETE |
| NewReservationPage | `/reservations/new` | Create form | `/api/reservations/` POST | COMPLETE |
| ReservationDetailPage | `/reservations/:id` | Full detail + chatter + ERP match | `/api/reservations/{id}/` | COMPLETE |

**Key Components Used:** ChatterBox, ActivityLogPanel, StatusBadge, ItemSearchWidget, CustomerLocationsPanel

---

### Mobile Web Surfaces (standalone — no desktop Layout)

Phone-friendly views over existing APIs, under the `MobileLayout` shell. See the
routing note above. Reuse `CustomerSearchWidget`, `ItemSearchWidget`, `StatusBadge`.

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| DriverDeliveryApp | `/rider` | Rider delivery task screen | `/api/delivery/` | COMPLETE |
| MobileReservationsPage | `/m/reservations` | Phone queue + status filter chips | `/api/reservations/?status__in=` | COMPLETE |
| MobileNewReservationPage | `/m/reservations/new` | Phone create + dedup/force flow | `/api/reservations/` POST | COMPLETE |
| MobileReservationDetailPage | `/m/reservations/:id` | Detail + stock + status progression | `/api/reservations/{id}/`, `change-status/` | COMPLETE |
| MobileTransfersPage | `/m/transfers` | Phone transfer queue + status chips | `/api/transfers/` | COMPLETE |
| MobileNewTransferPage | `/m/transfers/new` | Create (multi-item) + save-draft / save-&-submit | `/api/transfers/` POST, `submit/` | COMPLETE |
| MobileTransferDetailPage | `/m/transfers/:id` | Detail + full workflow actions (gated by can_*) | `/api/transfers/{id}/` + state actions | COMPLETE |
| MobileApprovalsPage | `/m/approvals` | Approvals inbox with تشغيلية/HR toggle — operational (engine + pricing/discount) and HR (leave/overtime/advance/expense) | `/api/approvals/requests/pending/?category=`, `/api/pricing-approvals/?status=pending`, `decide/` | COMPLETE |
| MobileShortagePage | `/m/shortage` | Shortage-lists queue + status chips | `/api/shortage/lists/` | COMPLETE |
| MobileNewShortagePage | `/m/shortage/new` | Create a shortage list | `/api/shortage/lists/` POST | COMPLETE |
| MobileShortageDetailPage | `/m/shortage/:id` | Log items (quick-add + bulk paste + 🎤 voice + 📷 photo OCR), submit | `add-item/`, `bulk-import/`, `voice-import/`, `ocr/`, `submit/` | COMPLETE |
| MobileDeliveryPage | `/m/delivery` | Live delivery order-status board (chips + late flags; auto-refresh) | `/api/delivery/?active=true` | COMPLETE |
| MobileDeliveryDetailPage | `/m/delivery/:id` | Order detail: customer/address (call/map/WhatsApp), items, status timeline | `/api/delivery/{id}/`, `whatsapp/` | COMPLETE |
| MobileItemsPage | `/m/items` | Item/stock lookup — price + stock across all branches | `/api/items/`, `{id}/stock/` | COMPLETE |
| MobileNotificationsPage | `/m/notifications` | Alerts inbox (mark read / mark all); via top-bar bell; Web Push (VAPID) opt-in toggle | `/api/notifications/`, `push/vapid-public-key/`, `push/subscribe/`, `push/unsubscribe/` | COMPLETE |
| MobileCustomersPage | `/m/customers` | Customer lookup → profile + loyalty points + recent reservations | `/api/customers/`, `/api/loyalty/` | COMPLETE |
| MobileMyIncentivesPage | `/m/my-incentives` | Own incentive earnings (earned + projected per program) | `/api/incentives/my-progress/` | COMPLETE |
| MobileTasksPage / DetailPage | `/m/tasks`, `/m/tasks/:id` | Tasks queue + checklist/complete/chatter | `/api/tasks/` | COMPLETE |
| MobileVoucherRedeemPage | `/m/vouchers` | Voucher OTP redemption (pick → phone → OTP → verify) | `/api/vouchers/.../generate-otp/`, `verify-otp/` | COMPLETE |
| MobileStockCountPage / DetailPage | `/m/stock-count`, `/m/stock-count/:id` | Sessions + **live barcode count entry** (scan → qty → instant variance) + variance list | `/api/stockcount/sessions/`, `count-item/` | COMPLETE |
| MobilePOSOrderPage | `/m/pos` | Indirect-POS order capture (نقطة البيع) → ready/push to cashier; offline-queue aware | `/api/pos-orders/`, `reference/`, `{id}/ready\|push/` | COMPLETE |
| MobileQAPage / DetailPage | `/m/qa`, `/m/qa/:id` | Branch QA inspection (template → pass/fail/na per item → score) | `/api/qa/templates/`, `inspections/` | COMPLETE |
| MobileAttendancePage | `/m/attendance` | Geofenced GPS clock in/out vs branch coords | `/api/hr/attendance/` | COMPLETE |
| DeliveryTrackPage (public) | `/track/:token` | Customer-facing live delivery tracking (no login; tokenized) — status stepper, driver, map link | `/api/delivery/track/{token}/` | COMPLETE |
| **Customer Portal** (external PWA — `pages/portal/`) | `/portal/*` | Customer self-service. **Own RTL shell + own API client (`src/portal/portalApi.js`, `Portal` auth scheme), NOT staff `MobileLayout`/JWT.** Magic-link login. Screens: Login (phone → link), Auth (`/portal/auth/:token` auto-exchange), Home (orders + 1-tap track), Refills (chronic due + reorder), Loyalty. PWA: `manifest.webmanifest` + `portal-sw.js`. | `/api/portal/*` | COMPLETE |
| MobileDemandPage | `/m/demand` | Lost-sales / unmet-demand queue (status chips, SLA flags) | `/api/demand/` | COMPLETE |
| MobileNewDemandPage | `/m/demand/new` | Counter capture: phone + multi-item (catalog or free-text) + priority/source | `/api/demand/` POST | COMPLETE |
| MobileDemandDetailPage | `/m/demand/:id` | Detail + items + notes thread | `/api/demand/{id}/`, `logs/` | COMPLETE |

> **Mobile bottom tabs:** الحجوزات / التحويلات / النواقص / التوصيل / الموافقات.
> النواقص is gated to shortage-capable roles; التوصيل to dispatch/manager roles
> (admin/call_center/supervisor/quality_manager/pharmacist); الموافقات to
> admin/supervisor/purchasing (with a live pending-count badge). "New" is reached
> via each list's floating + button. The delivery board is read-focused
> (monitoring) — lifecycle actions stay on the desktop dispatch board + rider app.
> الطلب الضائع (demand intake) is gated to intake roles. When a user's visible
> tabs exceed 5, `MobileLayout` keeps the first 4 inline and moves the rest into a
> **"المزيد" (More) overflow sheet** — a 3-column grid (with badge dots) that
> scales to the full surface set. **Notifications** are reached via a 🔔 bell in
> the top bar (live unread count), not a tab. The top-bar title reflects the
> active section. Full surface set (role-gated): reservations, transfers, demand,
> shortage, delivery, approvals, items, customers, vouchers, tasks, stock-count,
> my-incentives — all standalone `/m` routes over existing APIs; desktop untouched. The operational approvals inbox merges the generic approval engine
> (`ApprovalWorkflowDefinition.category='operational'`) with item price/discount
> change requests. HR approvals live under the same surface via a تشغيلية/HR
> segmented toggle (engine `category='hr'`); the tab badge counts all three
> (operational + pricing + HR) pending for the user.
>
> **Shared mobile UX** (`components/mobileUi.jsx`, `components/MobileChatter.jsx`):
> standardized loading / empty / error-with-retry blocks, an offline banner in
> `MobileLayout` (`useOnline`; TanStack Query auto-refetches on reconnect), and a
> chatter composer on the reservation (`logActivity`) and transfer (`sendMessage`)
> detail screens.
>
> **Offline action queue** (`api/offlineQueue.js`, `useOfflineQueue` in `mobileUi.jsx`):
> a persistent IndexedDB queue (`elrezeiky-offline` DB) for high-value, replay-safe
> **create** flows on flaky phone data. `queuedPost(url, body, {label})` sends
> normally when online; when offline — or on a network-level failure — it persists
> the mutation and resolves optimistically with `{queued:true}`. A sync engine
> replays the queue FIFO on the `online` event and at app load, dropping permanent
> 4xx failures (with a user-visible toast) and keeping 401/5xx/network items for
> retry. `MobileLayout` shows a pending-count in the offline banner, a "syncing…"
> bar when online with a non-empty queue, and success/failure toasts.
> **Wired flows:** reservation create (`/reservations/`), demand create (`/demand/`),
> shortage add-item + bulk-import (`/shortage/lists/{id}/add-item/`, `bulk-import/`),
> stock-count `count-item` (`/stockcount/sessions/{id}/count-item/`). GETs, money,
> and approval actions are **never** queued. ⚠️ No server-side idempotency yet — a
> reply lost after the server wrote the record means a duplicate on retry; accepted
> for these create flows only. Each item sends an `X-Idempotency-Key` header so the
> backend can dedupe later.

---

### Demand Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| DemandPage | `/demand` | Demand list with SLA indicators | `/api/demand/` | COMPLETE |
| DemandDashboardPage | `/demand/dashboard` | KPIs, SLA breach counts | `/api/demand/stats/` | COMPLETE |
| DemandRecoveryPage | `/demand/recovery` | Back-in-stock recovery + ROI loop | `/api/demand/recovery/` | COMPLETE |
| DemandDetailPage | `/demand/:id` | Demand detail + follow-up tasks | `/api/demand/{id}/` | COMPLETE |
| FollowUpsPage | `/followups` | Combined follow-up task list | `/api/followups/` | COMPLETE |

---

### Transfers Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| TransfersPage | `/transfers` | Transfer request list | `/api/transfers/` | COMPLETE |
| NewTransferPage | `/transfers/new` | Create transfer request | `/api/transfers/` POST | COMPLETE |
| TransferDetailPage | `/transfers/:id` | Detail + approval workflow + chatter | `/api/transfers/{id}/` | COMPLETE |

---

### Customers Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| CustomersPage | `/customers` | Customer list with segment filters | `/api/customers/` | COMPLETE |
| CustomerDetailPage | `/customers/:id` | Full customer profile + health + history | `/api/customers/{id}/` | COMPLETE |
| ChronicClassifierPage | `/chronic-classifier` | Chronic medication tagging tool | `/api/chronic/` | COMPLETE |

**Key Components:** CustomerTagsPanel, CustomerLocationsPanel, CustomerHealthProfile section

---

### Call Center Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| CallCenterPage | `/callcenter` | Active cases list | `/api/callcenter/` | PARTIAL |
| CasesPage | `/callcenter/cases` | Case management | `/api/callcenter/cases/` | PARTIAL |
| CallCenterAnalyticsPage | `/callcenter/analytics` | Call metrics | `/api/callcenter/analytics/` | PARTIAL |

---

### Catalog / Inventory Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| ProductCatalogPage | `/products` | Item search + stock overview | `/api/items/` | COMPLETE |
| ProductDetailPage | `/products/:id` | Item detail + stock per branch | `/api/items/{id}/` | COMPLETE |
| ProductContentAdminPage | `/products/:id/admin` | Item content admin (media/content/attributes/SEO) | `/api/products/{softech_id}/…` | COMPLETE |
| ItemIntelPage | `/products/:id/intel` | Per-item intelligence (demand/margin/velocity) | `/api/products/{softech_id}/…`, `/api/analytics/items/` | COMPLETE |
| CatalogIntelligencePage | `/catalog-intelligence` | Item analytics intelligence | `/api/analytics/items/` | PARTIAL |
| ImageEnrichmentPage | `/image-enrichment` | Product image enrichment | `/api/enrichment/` | PARTIAL |
| InventoryDashboard | `/inventory` | Stock overview dashboard | `/api/items/` | PARTIAL |
| StockCountPage | `/stock-count` | Stock count session management | `/api/stockcount/` | COMPLETE |
| ShortagePage | `/shortage` | Shortage list + OCR + matching | `/api/shortage/` | COMPLETE |

---

### Purchasing / Procurement Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| PurchasingDashboard | `/purchasing` | Demand engine dashboard | `/api/purchasing/` | PARTIAL |
| ProcurementHubPage | `/procurement` | Multi-tab procurement hub | `/api/procurement/` | PARTIAL |
| — Overview tab | `/procurement/overview` | KPI overview | `/api/procurement/overview/` | PARTIAL |
| — History tab | `/procurement/history` | Purchase history | `/api/procurement/history/` | PARTIAL |
| — Segments tab | `/procurement/segments` | Supplier segmentation | `/api/procurement/segments/` | PARTIAL |
| — FOC tab | `/procurement/foc` | Free-of-charge analysis | `/api/procurement/foc/` | PARTIAL |
| — Suppliers tab | `/procurement/suppliers` | Supplier performance | `/api/procurement/suppliers/` | PARTIAL |
| — Margins tab | `/procurement/margins` | Margin analysis | `/api/procurement/margins/` | PARTIAL |
| — Mappings tab | `/procurement/mappings` | Vendor item mappings | `/api/procurement/mappings/` | PARTIAL |

---

### Finance & Invoices Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| InvoicePage | `/invoices` | Supplier invoice list + OCR | `/api/invoices/` | PARTIAL |
| IncentivesPage | `/incentives` | Incentive programs + settlements | `/api/incentives/` | COMPLETE |
| ChequePlanningPage | `/cheques` | Cheque planning | `/api/cheques/` | PARTIAL |
| FinanceHubPage | `/finance` | Multi-tab finance hub | `/api/finance/` | PARTIAL |

---

### Vouchers Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| VouchersPage | `/vouchers` | Voucher management + OTP flow | `/api/vouchers/` | COMPLETE |

---

### Analytics Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| AnalyticsHubPage | `/analytics` | Tabbed analytics hub | `/api/analytics/` | PARTIAL |
| SalesDashboard | `/analytics/sales` | Sales performance | `/api/analytics/sales/` | PARTIAL |
| PerformanceDashboard | `/analytics/performance` | Team performance | `/api/analytics/performance/` | PARTIAL |
| ReservationsAnalyticsPage | `/analytics/reservations` | Reservation funnel analytics | `/api/analytics/…` | COMPLETE |
| TransfersAnalyticsPage | `/analytics/transfers` | Transfer flow analytics | `/api/analytics/…` | COMPLETE |

---

### Marketing Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| WhatsAppCampaignPage | `/campaigns` | WhatsApp broadcast campaigns (audience → approval → queue → stats) | `/api/campaigns/` | COMPLETE |
| WhatsAppInboxPage | `/whatsapp/inbox` | WhatsApp 1:1 conversations + send text/template | `/api/whatsapp/conversations/` | COMPLETE |
| RecommendationsPage | `/recommendations` | Product recommendations (FBT + per-customer) | `/api/recommendations/` | PARTIAL |
| LoyaltyPage | `/loyalty` | Loyalty tiers + rewards + point adjust/redeem | `/api/loyalty/` | COMPLETE |
| BranchPointsPage | `/loyalty/branch` | Per-branch points view | `/api/loyalty/` | COMPLETE |
| ReferralPage | `/referral` | Referral codes + leads + validate/invite | `/api/referral/` | COMPLETE |

---

### Operations Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| DeliveryDashboard | `/delivery` | Delivery tracking dashboard | `/api/delivery/dashboard/` | COMPLETE |
| DispatchBoard | `/delivery/dispatch` | Assign/dispatch delivery orders | `/api/delivery/{id}/assign\|dispatch/` | COMPLETE |
| DeliveryAnalyticsPage | `/delivery/analytics` | Driver/area/shift/CSAT analytics | `/api/delivery/*-report/` | COMPLETE |
| PaymentTracking | `/payments` | External payment status + reconcile | `/api/payments/` | PARTIAL |
| PaymentAuditPage | `/payment-audit` | Payment audit trail | `/api/payments/audit/` | PARTIAL |
| TasksPage / TaskDashboardPage / TaskSchedulesPage / TaskDetailPage | `/tasks`, `/tasks/dashboard`, `/tasks/schedules`, `/tasks/:id` | Operational tasks + schedules + dashboard | `/api/tasks/` | COMPLETE |
| BatchesPage | `/batches` | Batch / near-expiry management (FEFO) | `/api/batches/` | COMPLETE |
| ForecastingPage | `/forecasting` | Demand/sales forecast runs + accuracy | `/api/forecasting/` | COMPLETE |
| PbxLivePage | `/pbx/live` | Live call wallboard (Issabel AMI) | `/api/pbx/live/`, `spy/` | COMPLETE |
| TargetsPage | `/targets` | Sales targets | `/api/dashboard/` | COMPLETE |
| AnnouncementsPage | `/announcements` | Internal announcements | `/api/notifications/` | COMPLETE |

---

### Point of Sale (Indirect-POS) Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| POSOrderPage | `/pos` | Create/edit indirect-POS order (customer + items + pricing + payment) → **push pending order to SOFTECH cashier**; discount authority + batch selection + offline retry queue | `/api/pos-orders/` + `reference/`, `batches/`, `discount-suggest/`, `queue-status/`, `flush/`, `{id}/ready\|push\|cancel/` | COMPLETE |

> Also on mobile at `/m/pos` (see Mobile Web Surfaces). This is a **live SOFTECH
> writeback channel** — writes PENDING rows only (`stktransm5`/`stktrans5`/`branchesales5`);
> the cashier settles. See [02_MODULE_REGISTRY.md#pos-orders](02_MODULE_REGISTRY.md)
> and runbooks `POS_OPERATOR_RUNBOOK.md` / `POS_OFFLINE_RESILIENCE.md`.

---

### Insurance Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| InsuranceClaimsPage | `/insurance` | Insurance claims list (motalba) | `/api/insurance/claims/` | COMPLETE |
| InsuranceClientsPage | `/insurance/clients` | Client / contract hierarchy | `/api/insurance/clients/` … | COMPLETE |
| InsurancePrintProfilesPage | `/insurance/print-profiles` | Export/print profiles + pivot templates | `/api/insurance/export-profiles/` | COMPLETE |
| InsuranceClaimDetailPage | `/insurance/claims/:id` | Claim detail (lines, adjustments, exclusions) | `/api/insurance/claims/{id}/` | COMPLETE |
| InsurancePrintPage | `/insurance/claims/:id/print` | Printable claim (motalba layout) | `/api/insurance/claims/{id}/` | COMPLETE |

---

### Communications / CEP Module (Omni)

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| OmniInboxPage | `/omni/inbox` | Unified customer timeline (WA + calls + social) | `/api/omni/conversations/` | PARTIAL (Phase 0) |
| OmniAccountsPage | `/omni/accounts` | Multi-number WhatsApp account health | `/api/omni/accounts/` | PARTIAL (Phase 1) |
| OmniWallboardPage | `/omni/wallboard` | Supervisor live wallboard (spy/whisper) | `/api/omni/wallboard/`, `/api/pbx/live/` | PARTIAL (Phase 2) |
| OmniAutomationsPage | `/omni/automations` | No-code automation rule builder | `/api/omni/automations/` | COMPLETE (Phase 4) |
| OmniAnalyticsPage | `/omni/analytics` | Cross-channel comms BI | `/api/omni/analytics/` | COMPLETE (Phase 5) |

---

### Pricing Approvals Module

| Screen | Route | Purpose | Related APIs | Status |
|--------|-------|---------|-------------|--------|
| PricingApprovalsPage (+ `pages/pricing/`) | `/pricing-approvals` | Item price/discount change requests → approve → **replicate to SOFTECH**; SLA + replication reconciliation + gap repair | `/api/pricing-approvals/` | COMPLETE |

---

### Admin Module

| Screen | Route | Purpose | Related APIs | Status | Access |
|--------|-------|---------|-------------|--------|--------|
| UserManagementPage | `/users` | Staff CRUD | `/api/users/staff/` | COMPLETE | admin |
| PermissionsMatrixPage | `/permissions` | Role-permission matrix | `/api/users/permissions/` | COMPLETE | admin |
| ErpPermissionsPage | `/erp-permissions` | SOFTECH ERP permission model view | `/api/…` | COMPLETE | admin |
| ApprovalsPage | `/approvals` | Operational + HR approval workflows | `/api/approvals/` | COMPLETE | admin/supervisor/pharmacist/quality_manager/purchasing |
| HRPage | `/hr` | HR admin (attendance/leave/shifts/OT/advances/expenses) | `/api/hr/` | COMPLETE | admin/HR |
| PickZonesPage | `/pick-zones` | Picking/stocking zone classification config | `/api/transits/pick-zones/` | COMPLETE | admin/supervisor |
| AuditPage | `/audit` | Audit event log | `/api/audit/` | PARTIAL | admin |
| SyncPage | `/sync` | ERP sync trigger + logs | `/api/sync/` | COMPLETE | admin |

---

## Reusable Components

| Component | Purpose | Used In |
|-----------|---------|---------|
| `Layout.jsx` | Main shell (sidebar, navbar, notifications) | All protected screens |
| `DataTable.jsx` | Sortable/filterable/paginated table | List screens |
| `StatusBadge.jsx` | Colored status pill | All status fields |
| `ItemSearchWidget.jsx` | Debounced item search popup | Reservations, Demand, Transfers |
| `ItemSearchInput.jsx` | Inline item search input | Forms |
| `AdvancedItemSearchModal.jsx` | Full modal item search | New Transfer |
| `ItemOperationalFiltersBar.jsx` | Operational item filters | Catalog |
| `BranchSelect.jsx` | Branch selector dropdown | Global filter |
| `ChatterBox.jsx` | Odoo-style comment + voice note widget | Detail pages |
| `VoiceNoteRecorder.jsx` | Voice note capture | ChatterBox |
| `ActivityLogPanel.jsx` | Activity timeline | Reservation, Transfer detail |
| `NotificationPanel.jsx` | Notification list panel | Layout |
| `NotificationBell.jsx` | Unread count badge | Navbar |
| `CustomerLocationsPanel.jsx` | Customer branch visits map | Customer detail |
| `CustomerTagsPanel.jsx` | Customer condition tags | Customer detail |
| `AnalyticsFilterPanel.jsx` | Date range + branch filter | Analytics |
| `WhatsAppShareButton.jsx` | WhatsApp deep link button | Vouchers, Notifications |
| `ReceiptPrint.jsx` | Thermal receipt print | Vouchers, Reservations |
| `PrintReceiptModal.jsx` | Print confirmation modal | Reservations |
| `RefreshButton.jsx` | Data refresh trigger | Tables |
| `ui.jsx` | Input, Btn, Modal, Badge, etc. | All screens |

## WebSocket Hooks

| Hook | Channel | Purpose |
|------|---------|---------|
| `useNotificationSocket.js` | `notifications_user_{profile_id}` | Real-time notification push |
| `useChatterSocket.js` | `chatter_{model}_{record_id}` | Real-time chatter updates |

## Web Push (VAPID)

| File | Purpose |
|------|---------|
| `public/sw.js` | Service worker: `push` → showNotification, `notificationclick` → focus/open deep link |
| `src/push.js` | Register SW, fetch VAPID key, request permission, subscribe, POST to backend (`initPush`/`enablePush`/`disablePush`) |

`initPush()` runs silently after login (re-syncs only if permission already granted); the opt-in toggle lives on `/m/notifications`. Backend `send_web_push()` fans every persisted notification out to the recipient's subscriptions (best-effort; dead 404/410 endpoints pruned). **iOS delivers Web Push only to an installed PWA (Safari 16.4+).**

## State Management

| Store | Contents |
|-------|----------|
| `authStore.js` | JWT tokens, user profile, role, branch |
| `langStore.js` | Language/locale setting |

## Known UI Issues

1. **Missing loading states** on several analytics tabs
2. **No error boundaries** on detail pages — unhandled API errors crash the screen
3. **Finance module** — charts are scaffolded but data not wired
4. **Procurement hub** — FOC and margins tabs have placeholder charts
5. **Delivery / Payments** — screens are stubs awaiting backend connection
6. **No offline indicator** — WebSocket disconnect is silent
7. **Permission guards** — role-based route guarding exists on route level but not on individual UI actions (buttons visible to unauthorized roles)
