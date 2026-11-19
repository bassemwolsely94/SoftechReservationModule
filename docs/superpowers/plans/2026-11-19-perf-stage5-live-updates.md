# Performance Stage 5 — fewer, cheaper polls; changes pushed over the WebSocket

**Design:** `docs/superpowers/specs/2026-11-19-performance-boost-design.md` §4 (polled ≤ 300 ms),
§6 Stage 5, §9 (a) ("as of HH:MM" labels pre-approved). **Audit:** `07_PERFORMANCE_AUDIT.md` PERF-10.
**Branch:** `claude/perf-s5-live-updates-23e41b`. No migration. No SOFTECH access. No export code touched
(Stage 4 runs in parallel).

## 1. Goal

Every open tab used to poll the bell, the sync status, the freshness bar and the dashboard summary on
short timers, whether anything changed or not. Stage 5 makes the server say when something changed,
over the notification WebSocket every staff tab already holds, and turns the timers into slow
fallbacks that run only while that socket is down (or as a long safety net).

## 2. Inventory — every `refetchInterval` / `setInterval` in `frontend/src` (2026-11-19)

154 matches. Grouped by who pays for them. "Every tab" rows are the ones Stage 5 changes.

### 2.1 Every tab, every user (the steady load)

| Source | Endpoint | Before | After |
|---|---|---|---|
| `hooks/useNotificationSocket` reconcile | `notifications/` + `notifications/category-counts/` | 30 s, **even with the socket up**, and **in hidden tabs** (plain `setInterval`) | removed; counts pushed (`category_counts`), list pushed (`new_notification`) |
| `hooks/useNotificationSocket` fallback | `notifications/` | 8 s while socket down/reconnecting (only after 4001/4403) | 120 s list + counts while down (any close), skipped in hidden tabs; one catch-up on reconnect |
| `components/Layout` | `sync/status/` | 60 s | on `freshness_changed` (main lanes) + 15 min safety (5 min while socket down) |
| `components/DataFreshnessBar` (domains mode; most module screens) | `sync/freshness/?domains=…` | 60 s; 4 s while a forced refresh runs | on `freshness_changed` for its domains + 5 min; forced refresh unchanged (4 s × 8); ages tick on the client each minute |
| `pages/DashboardPage` summary | `dashboard/summary/` | 90 s | on `freshness_changed` (main lanes) + window focus + 5 min; header shows «آخر تحديث HH:MM» |
| `pages/DashboardPage` sync/status | `sync/status/` | 30 s | already removed in Stage 3 (confirmed) |
| `components/CallPopBanner` (users with an extension) | `pbx/live/?fresh=1` | **6 s** | on PBX socket `incoming_call` / `call_answered` / `call_ended` (+ one re-read 2.5 s later); 60 s safety while the PBX socket is open, 15 s while down; skipped in hidden tabs |
| `components/MobileLayout` (/m only) | approvals count ×3, `unread-count` | 60 s | unchanged (phones, few users; react-query pauses hidden tabs) |
| `components/GamificationCard` | gamification | 5 min | unchanged |

### 2.2 Live work someone watches — kept fast on purpose

| Source | Interval | Why kept |
|---|---|---|
| `hooks/usePosOrder` queue status | 20 s | cashier watches the offline queue; now skipped while the tab is hidden |
| `pages/DeliveryDashboard` / `DispatchBoard` / `DriverDeliveryApp` | 15–30 s | dispatch board |
| `pages/PbxLivePage` | 15 s / 30 s (+ its own PBX socket) | wallboard |
| `pages/OmniWallboardPage` | 5 s | wallboard |
| `pages/OmniInboxPage`, `WhatsAppInboxPage` | 10–15 s | live chat inbox |
| `pages/CallCenterPage`, `CallbackQueuePage`, `ExceptionCenterPage`, `TransfersPage`, `PaymentTracking`, `ReferralPage`, `PricingApprovalsPage`, `pricing/SlaPanel`, `marketplace/OrdersTab`, `callcenter/CustomerWhatsAppPanel`, `pbx/*`, `rpa/*`, `OmniAccountsPage`, `ImageEnrichmentPage` | 15–60 s | open only on their screen, by the people who work it; react-query already pauses them in hidden tabs |

### 2.3 Periodic, screen-only (60 s – 5 min)

`AuditPage`, `CallCenterAnalyticsPage`, `ChequePlanningPage`, `DemandDashboardPage`, `DemandDetailPage`,
`DemandPage`, `DemandRecoveryPage`, `FollowUpsPage`, `followups/CallListsPanel`, `InTransitTab`,
`ReservationDetailPage`, `ReservationsKanban`, `TransferDetailPage`, `SyncPage`, `PurchasingPage`,
`PurchasingDashboard`, `SupplierPortalsPage`, `finance/gl/JournalPage`, `pricing/InsightsPanel`,
`mobile/*`, `NotificationPanel` reminders, `ModuleNotificationBell` (only while open),
`pos/platform/PlatformDraftsButton`, `hr-attendance/DevicesTab`. Unchanged: only their own screen
pays, and the global default pauses them in hidden tabs.

### 2.4 Job-progress polls — run only while a job runs

`BatchesPage`, `cash/DeadStockTab`, `CatalogIntelligencePage`, `dataHealth/ProblemsTab`,
`DataHealthPage`, `DeliveryTrackPage`, `finance/gl/PeriodClosePage`, `finance/gl/SoftechComparePage`,
`ForecastingPage`, `InsightsPage`, `InvoicePage`, `invoices/BundleWorkbench`, `MarketShortagePage`,
`PicAnalyticsPage`, `ProductCatalogPage`, `PurchasingDashboard` (runs), `StockAuditPage`,
`SupplierTermsPage`, `supply/AvailabilityControls`, `taxinvoicing/*`, `WhatsAppCampaignPage`,
`DataFreshnessBar` KPI mode, `DataFreshnessBar` forced refresh. Unchanged (they stop by themselves).

### 2.5 Not network (clocks, keep-alive, animations)

`SoftPhone`, `ProgressBar`, `VoiceNoteRecorder`, `help/Tour`, `useSoftPhone` ring, `PbxLivePage` tick,
`PurchasingDashboard` tick, `DemandDetailPage` clock, `InsuranceClaimDetailPage` countdown,
`VouchersPage`, `RecommendationsPage`, `ShortagePage` ticker, `ReservationDetailPage` /
`TransferDetailPage` cooldowns, `hr-attendance/DevicesTab` re-render, WebSocket pings
(`useNotificationSocket`, `useChatterSocket` — a frame, not an HTTP request).

## 3. Design

### 3.1 Bell counts (`apps/notifications/live.py`, `consumers.py`)

- `request_counts_push(profile_id)` sends `{'type': 'notification.counts'}` — **no data** — to
  `notifications_user_{id}` **after commit**.
- Called from: `post_save` on `Notification` (create, snooze, un-snooze worker), and after the
  queryset `.update()` / `.delete()` paths (REST read, bulk read/delete/snooze, mark-all-read, delete,
  clear-all; socket `mark_read` / `mark_all_read` fan out to every tab of the user).
- `NotificationConsumer.notification_counts` computes `unread_category_counts(profile)` (the same
  helper the REST `category-counts/` route now uses) and sends `{'event': 'category_counts', …}`.
  Debounced 0.5 s per socket, so a job that sends 50 notifications costs one count per open tab, and
  users with no open tab cost nothing.
- Client: `category_counts` updates the bell number and the quiet-feed counts; if the bell number
  differs from what the tab shows (read elsewhere) it reloads the list once.

### 3.2 Freshness (`apps/sync/live.py`)

- `post_save` receivers on `SyncRun` and on every custom-source run log that
  `apps/sync/freshness.py` reads (`StockExpirySyncRun`, `PurchaseExpiryAuditRun`,
  `ProcurementEngineRun`, `StockLedgerSyncRun`, `CollectionRun`, `GLDraftRun`, `CdrSyncRun`,
  `FinanceSyncRun`, `ReconciliationRun`). When a row reaches `success` / `partial` / `failed` they
  broadcast `{'type': 'live.freshness', 'domains': […], 'at': iso}` to group `live_staff` after commit.
  `SyncRun` lane → domains: fast → stock/sales/branches, slow → catalog/customers/users,
  items → catalog, retention → nothing, full/blank/other → all six.
- Connected at the top of `SyncConfig.ready()` so the scheduler process (where runs finish) has them.
- Every `NotificationConsumer` joins `live_staff` after the existing login + zone (N5) checks and
  leaves it on disconnect. The client frame is rebuilt from known fields only
  (`freshness_message`): `{'event': 'freshness_changed', 'domains': [...], 'at': '...'}`.
- Client: `store/liveStore.js` — `socketUp`, `freshnessChanged(domains)`, `useOnFreshnessChange(cb,
  domains)`. Each tab waits a random 0–4 s before refetching, so 40 tabs do not hit the server in the
  same instant.

### 3.3 Global defaults

`api/queryDefaults.js`: `staleTime 30 s`, `retry 1`, `refetchIntervalInBackground: false`
(explicit; `liveStore.test.js` fails if any file sets it to `true`). Plain `setInterval` polls that
stay (bell fallback, POS queue, call pop-up) skip their tick while `document.hidden`.

### 3.4 Security

- Counts frame: integers + the visible category keys the REST route already returns, sent only to
  the user's own group. Freshness frame: domain keys + ISO time. No customer data, no phone numbers,
  no record content (test: extra fields on the channel message never reach the browser).
- No new endpoint, no new socket route. WebSocket auth, zone (N5) admission and Origin checks are
  unchanged. The call pop-up uses the existing `/ws/pbx/agent/` socket (same D1 gate) and still reads
  the caller from `/pbx/live/` as before.

## 4. Before / after (requests per minute, estimated from the intervals)

Assumptions: fast lane every 5 min, slow lane every 60 min (≈ 0.22 main-lane events/min); a tab on
the dashboard (which carries a `sales,stock` freshness bar, the gamification card and, for purchasing,
the supply block); events cost one request per listening query.

| Idle open tab | Before | After |
|---|---|---|
| Dashboard, socket up | bell 4 + sync/status 1 + summary 0.67 + freshness 1 + gamification 0.2 + supply 0.2 = **7.1** | bell 0 + sync/status 0.29 + summary 0.42 + freshness 0.4 + 0.4 = **1.5** |
| Dashboard, socket down | 7.5 + 7.1 = **14.6** | bell 1 + 0.2 + 0.2 + 0.2 + 0.4 = **2.0** |
| Any tab, hidden | bell timers kept running: **4** | **0** |
| POS tab of an agent with an extension (call pop-up + queue + compact freshness chip + bell) | 10 + 3 + 1 + 4 = **18** | 1 + 3 + 0.4 + 0 = **4.4** (+ 2 per call event) |

| 40 users | Before | After |
|---|---|---|
| 40 dashboard tabs, socket up | ≈ **283 req/min** | ≈ **60 req/min** |
| 40 dashboard tabs, socket down | ≈ **584 req/min** | ≈ **80 req/min** |
| 10 call agents on POS + 30 on dashboard | 180 + 213 = **393 req/min** | 44 + 45 = **89 req/min** |

## 5. Tasks (TDD)

1. Backend tests `apps/tests/test_perf_stage5_live.py` (counts push after commit, every read path,
   debounce, freshness per lane/source, frame contents, group join/leave) → implement `live.py`,
   consumer handlers, `sync/live.py`, view hooks.
2. Frontend tests `store/liveStore.test.js` (fallback intervals, domain matching, subscription,
   applyCounts, polling guard) → implement `liveStore`, bell hook, Layout, DataFreshnessBar,
   Dashboard, CallPopBanner, `useScreenPop` exports, `queryDefaults`.
3. Help (`apps/help/content/general.py`): dashboard «آخر تحديث», live bell; bump `updated`.
4. `npm run lint`, `npm run build`, CI.

## 6. Not in this stage

- `MobileLayout` approvals badge (3 requests/min/phone): could ride the same counts event once
  approvals send notifications; left as is.
- The load test (§7 of the design) runs after Stages 3–5 are all merged.
