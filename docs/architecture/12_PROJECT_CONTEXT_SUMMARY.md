# 12 — Project Context Summary

**Purpose:** Minimum context for a new AI session to continue development without re-reading the entire codebase.  
**Use this as the first document loaded in any new conversation.**

---

## What This Project Is

**ElRezeiky Pharmacy Operations Platform** — a full-stack web application for the ElRezeiky pharmacy chain in Egypt.

- **Backend:** Django 4.2 + DRF + Django Channels (ASGI/WebSocket) + APScheduler
- **Frontend:** React 18 SPA (Vite, Tailwind, TanStack Query, Zustand, React Router 6)
- **Primary DB:** PostgreSQL
- **ERP:** SOFTECH (Sybase ASE via **jConnect JDBC / jpype**, see `config/sybase.py`) — **read-only mirror by default.** Writes back to SOFTECH happen *only* through audited, ERP-client-mimicking channels: **(1)** approved item-discount changes in `apps/discount_approvals`, and **(2)** indirect-POS **pending sales orders** in `apps/pos_orders` (BUILT — pushes `stktransm5`/`stktrans5`/`branchesales5` pending rows for a cashier to settle). Never do ad-hoc Sybase writes.
- **Working directory:** `C:\Users\basse\OneDrive\ElRezeiky Depts\IT Software Development\Claude Development\Reservation Module`

---

## Architecture Fundamentals

1. **ERP is authoritative; reads are a one-way mirror.** All SOFTECH data is mirrored into PostgreSQL via sync commands. Django does **not** do ad-hoc writes to SOFTECH — the *only* writes are through explicit, audited writeback channels that replay the exact DML the native ERP client issues and let SOFTECH's own triggers/replication propagate it (see `apps/discount_approvals/replication.py` for item-discounts; `apps/pos_orders/writer.py` for indirect-POS pending orders — both BUILT). Treat any new SOFTECH write as a deliberate, reviewed channel — never a casual `UPDATE`/`INSERT`.
2. **JWT authentication (staff).** All STAFF APIs require `Authorization: Bearer <token>` (simplejwt, bound to `StaffProfile`). **Exception — external customer portal:** `apps/portal` (`/api/portal/*`) is a separate, customer-scoped auth surface. Customers log in via a WhatsApp **magic link** and present a stateless `django.core.signing` session token under a distinct `Authorization: Portal <token>` scheme. The two are mutually exclusive: a portal token is rejected by staff APIs (not a JWT) and a staff JWT is rejected by portal APIs (portal views set `authentication_classes=[PortalSessionAuthentication]` only). Every portal endpoint is hard-scoped to one `Customer.softech_pic`; no customer id is ever accepted from the client.
3. **Real-time via Django Channels + Redis.** WebSocket groups: `notifications_user_{profile_id}` and `chatter_{model}_{record_id}`.
4. **Role-based access.** 9 roles in `StaffProfile.role`. Branch access controlled by `access_all_branches`, `allowed_branches`, `restricted_branches`.
5. **Cursor pagination.** Default 50 items. All list endpoints must paginate.
6. **Arabic-first.** UI is Arabic RTL. All model verbose names are in Arabic.

---

## Module Map (52 Django Apps)

> The tables below highlight the headline modules. The codebase actually contains
> **52 Django apps** under `apps/` (the "32" and "48" figures were stale). Additional
> apps not listed below include: analytics, approvals, audit, batches, campaigns,
> cheques, dashboard, delivery, discount_approvals, enrichment, erp, finance,
> forecasting, hr, images, insurance, loyalty, omni, payments, pbx, **pos_orders**,
> portal, procurement, product_experience, qa, recommendations, referral, social,
> tasks, transits, whatsapp, and tests. **`pos_orders`** (indirect-POS writeback,
> desktop `/pos` + mobile `/m/pos`) is a live SOFTECH pending-order writer — the
> Phase-2 writer from doc 14, now BUILT. See
> [11_ERP_INDEX.md](11_ERP_INDEX.md) for the full module/API/screen indexes and
> [02_MODULE_REGISTRY.md](02_MODULE_REGISTRY.md) for per-app detail.

### Fully Complete Modules
| App | Purpose |
|-----|---------|
| `apps/branches` | Branch master + feature flags |
| `apps/catalog` | Item master, stock, barcodes, bundles |
| `apps/customers` | Customer master, health profiles, CRM |
| `apps/reservations` | Reservation workflow with ERP match |
| `apps/demand` | Demand records with SLA + follow-up tasks |
| `apps/transfers` | Inter-branch transfer approval workflow |
| `apps/users` | Staff profiles, roles, ERP user cache |
| `apps/notifications` | Notifications + WebSocket + generic chatter |
| `apps/vouchers` | Voucher platform with OTP + POS redemption |
| `apps/incentives` | Sales incentive engine + settlements |
| `apps/stockcount` | Transaction-based stock count sessions |
| `apps/shortage` | Shortage lists + OCR + fuzzy matching |
| `apps/chronic` | Chronic medication detection |
| `apps/config` | System settings, dropdowns, pharmacy profile |
| `apps/sync` | ERP sync management |
| `apps/pos_orders` | **Indirect-POS writeback** — pending sales orders pushed to SOFTECH cashier (desktop + mobile) |
| `apps/insurance` | Insurance claims (SOFTECH motalba), clients, print profiles |
| `apps/procurement` | Procurement hub (suppliers, FOC, margins, optimization) |
| `apps/loyalty` | Loyalty points program |
| `apps/referral` | Referral doctor / program |
| `apps/forecasting` | Demand/sales forecasting |
| `apps/batches` | Batch + near-expiry tracking |
| `apps/approvals` | Operational + HR approval workflows |
| `apps/discount_approvals` | Approved item-discount writeback to SOFTECH |
| `apps/whatsapp` / `apps/pbx` / `apps/omni` / `apps/social` | Comms stack (CEP / unified inbox) |
| `apps/hr` / `apps/qa` | Geofenced attendance + branch QA (mobile) |
| `apps/portal` | External customer PWA (magic-link auth) |

### Partially Complete Modules
| App | Missing |
|-----|---------|
| `apps/purchasing` | Transfer recommendations UI |
| `apps/invoices` | Invoice approval flow |
| `apps/callcenter` | Escalation workflow |
| `apps/followups` | Unclear overlap with `demand.FollowUpTask` |
| `apps/campaigns` | Send integration |
| `apps/deliveries` | Stub |
| `apps/payments` | Stub |
| `apps/enrichment` | Partial |
| `apps/recommendations` | Partial |
| `apps/cheques` | Partial |
| `apps/tasks` | Partial |

---

## Key Tables

| Table | Size | Key |
|-------|------|-----|
| `catalog_item` | 37,500 rows | `softech_id` (ERP immutable) |
| `customers_customer` | 40,000 rows | `softech_pic` (globally unique) |
| `customers_purchasehistory` | ~3-4M/month | `softech_invoice_id` |
| `reservations_reservation` | Growing | `status` + `branch_id` |
| `demand_demandrecord` | Growing | `demand_number` (DEM-XXXXXX) |
| `transfers_transferrequest` | Growing | `request_number` (TR-XXXXXX) |
| `vouchers_voucherotp` | Time-limited | Never stores plain OTP |
| `incentives_incentivetransaction` | Audit trail | Immutable |
| `stockcount_stockcountsnapshot` | Per session | `expected_qty` immutable |
| `pos_orders_softechsalesorder` | Growing | 8-status lifecycle; `client_token` UNIQUE (idempotency); locked once pushed |
| `pos_orders_softechsalesorderline` | Per order | → SOFTECH `stktrans5` (pending line) |
| `pos_orders_softechsalesorderpayment` | Per order | → SOFTECH `branchesales5` (split tenders) |
| `insurance_*` (motalba mirror) | Growing | SOFTECH claim mirror |

---

## Key Business Rules (Non-Obvious)

1. **ERP stores `102`, `103`, `105` are quarantine** — excluded from operational stock counts
2. **`softech_pic`** is the globally unique customer identifier (not `softech_id` which is branch-local)
3. **OTP hash** — `VoucherOTP` stores HMAC-SHA256 hash + salt. Plain OTP is NEVER stored or returned in API
4. **Voucher redemption document** expires in 15 minutes; OTP expires in 3 minutes with max 3 retries
5. **IncentiveTransaction is immutable** — only the engine writes it; finalized settlements are locked
6. **StockCountSnapshot.expected_qty is immutable** — frozen at snapshot time
7. **Transfers never mutate stock** — physical movement logged in SOFTECH manually; this system is request/approval only
8. **SLA for demand**: NEW → ASSIGNED = 10 min; ASSIGNED → contacted = 20 min
9. **Customer health profile**: `manually_overridden=True` prevents auto-recomputation
10. **Notification dedup**: same `dedup_key` within 5 minutes = single notification
11. **`catalog_item.name_scientific` is DIRTY — never trust it blindly.** The SOFTECH scientific/generic name is unreliable: many rows are blank, mislabeled, or share a junk placeholder (e.g. ~353 items grouped under "UnDefined Item"). **Any molecule/active-ingredient matching or therapeutic-substitution logic MUST guard against blank/placeholder values** (exclude empty + known placeholders before grouping). See the data-safety guard in [13_DEMAND_EVOLUTION_ROADMAP.md](13_DEMAND_EVOLUTION_ROADMAP.md). For authoritative active ingredients use SOFTECH `activeingredients` + `itemsai` (junction), not `name_scientific`.

---

## Key APIs Quick Reference

| Need | Endpoint |
|------|----------|
| Authenticate | `POST /api/auth/login/` |
| List items | `GET /api/items/?q=...` |
| Item stock per branch | `GET /api/items/{id}/stock/` |
| Customer search | `GET /api/customers/?q=phone_or_name` |
| Create reservation | `POST /api/reservations/` |
| Reservation kanban | `GET /api/reservations/kanban/` |
| Create demand | `POST /api/demand/` |
| SLA breached demands | `GET /api/demand/sla-breached/` |
| Create transfer | `POST /api/transfers/` |
| Approve transfer | `POST /api/transfers/{id}/approve/` |
| Voucher OTP flow | `POST /api/vouchers/generate-otp/` → `verify-otp/` → `create-document/` → `mark-used/` |
| Run incentive calc | `POST /api/incentives/calculate/` |
| Stock count snapshot | `POST /api/stockcount/sessions/{id}/snapshot/` |
| System config | `GET /api/config/settings/` |
| POS order flow | `POST /api/pos-orders/` → `{id}/ready/` → `{id}/push/` (→ SOFTECH cashier); `queue-status/` + `flush/` for offline retry |
| Insurance claims | `GET /api/insurance/claims/` |
| Procurement engine | `GET /api/procurement/...` |

---

## Key Frontend Routes

| Need | Route |
|------|-------|
| Reservations | `/reservations` (list), `/reservations/:id` (detail) |
| Demand | `/demand` (list), `/demand/:id` (detail) |
| Transfers | `/transfers` (list), `/transfers/:id` (detail) |
| Customer profile | `/customers/:id` |
| Vouchers | `/vouchers` |
| Incentives | `/incentives` |
| Stock count | `/stock-count` |
| Shortage | `/shortage` |
| Procurement | `/procurement` |
| Analytics | `/analytics` |
| Finance | `/finance` |
| POS order (indirect-POS) | `/pos` (desktop), `/m/pos` (mobile) |
| Insurance | `/insurance` |
| Loyalty / Referral | `/loyalty`, `/referral` |
| Forecasting / Batches | `/forecasting`, `/batches` |
| Approvals | `/approvals` (desktop), `/m/approvals` (mobile) |
| Admin users | `/users` (admin only) |

---

## Current Branch

`claude/modules-config-stockcount-shortage-vouchers-invoices-incentives`

The branch contains significant uncommitted changes across all major modules. This is a feature branch.

---

## RBAC Permission Matrix (seeded 2026-06-05)

Run `python manage.py seed_permissions` to seed / reseed all 1800 permission rows.
Run `python manage.py seed_permissions --dry-run --role <role>` to preview one role.

| Role | Grants | Key Access |
|------|--------|------------|
| admin | all 200 | Unrestricted (bypasses table) |
| supervisor | 64 | Full CC + approve + export + audit |
| pharmacist | 48 | Branch ops + dispensing + stock count |
| purchasing | 46 | Procurement + invoices + incentives + finance |
| quality_manager | 32 | Read + export across all operational modules |
| call_center | 38 | Intake + demand + campaigns + delivery create |
| viewer | 15 | Read-only across 15 modules |
| salesperson | 19 | Create reservations/demand/shortages |
| delivery | 7 | Update own delivery orders |

Modules: 27 total (reservations, demand, transfers, followups, delivery, customers, chronic, campaigns, vouchers, catalog, stockcount, shortage, purchasing, invoices, incentives, cheques, finance, callcenter, hr, approvals, analytics, dashboard, audit, sync, settings, users, admin)

Actions: view, create, edit, delete, approve, export, assign, finalize

## Development Priorities (Recommended Order)

1. ~~**Fix TD-C001:** Add role-based UI action guards~~ ✅ DONE (2026-06-05)
2. ~~**Fix DUP-004:** Clarify/consolidate `apps/followups` vs `demand.FollowUpTask`~~ ✅ DONE (2026-06-21) — renamed `demand.FollowUpTask`→`DemandFollowUp` (state-only migration demand/0010); two distinct systems, name collision removed
3. ~~**Fix TD-M006:** Enforce `applicable_items` in voucher eligibility check~~ ✅ DONE (2026-06-21) — item + branch eligibility gate in validate/generate/verify; settable in create UI; reject-when-missing (no migration)
4. ~~**Fix TD-H001:** Add `voice_note` to `ChatterMessage` for feature parity~~ ✅ DONE (2026-06-21) — dedicated `voice_note` field (migration notifications/0025); image+voice in one message
5. ~~**Complete analytics:** Wire missing chart queries in AnalyticsHubPage~~ ✅ VERIFIED DONE (2026-06-21) — `apps/analytics` is fully wired to real PurchaseHistory data (sales/customers/performance/inventory/churn/branch-contribution); the "stub" claim was stale. Added `apps/tests/test_analytics.py`.
6. ~~**Complete finance:** Define data source for finance module~~ ✅ VERIFIED DONE (2026-06-21) — `apps/finance` is a complete Finance Intelligence Platform (snapshots, P&L, trial balance, treasury, expenses, sync engine); the "UI stubs" claim was stale. Added `apps/tests/test_finance.py`.
7. **Add automated tests:** ⏳ IN PROGRESS — engine + endpoint coverage now exists for incentives (`test_incentives.py`), analytics, finance, vouchers (+ eligibility/OTP), demand SLA, notifications, reservations, transfers, permissions, auth. Remaining gaps: finance sync engine, demand recovery loops, delivery.
8. ~~**Add SLA escalation:** APScheduler job for demand SLA breach notifications~~ ✅ DONE (2026-06-21) — hourly `demand_sla_escalation` job + `check_demand_sla` command; new `demand_sla_breach` HIGH-alarm notification type (TD-C003)

---

## How to Find Things

| Task | Where to look |
|------|--------------|
| A model's fields | `apps/{app}/models.py` or `03_DATABASE_DICTIONARY.md` |
| An API endpoint | `apps/{app}/urls.py` or `04_API_REGISTRY.md` |
| A screen's components | `frontend/src/pages/` or `05_UI_REGISTRY.md` |
| A business rule | `07_BUSINESS_RULES.md` |
| A workflow's state machine | `06_WORKFLOW_REGISTRY.md` |
| Whether something already exists | `10_FEATURE_INVENTORY.md` then grep |
| A duplicate risk | `08_DUPLICATION_REPORT.md` |
| A known bug | `09_TECHNICAL_DEBT_REPORT.md` |
| All docs | `docs/architecture/11_ERP_INDEX.md` |

---

## Golden Rules

1. **Search before building.** Check `10_FEATURE_INVENTORY.md` before creating anything new.
2. **Never create a new chatter implementation.** Extend `ChatterMessage` or use the module-specific one.
3. **Never create a new demand-intake model.** Use `Reservation` or `DemandRecord`.
4. **Never do ad-hoc SOFTECH writes.** SOFTECH is read-only *except* through explicit, audited writeback channels that replay the exact native-ERP-client DML (`apps/discount_approvals/replication.py` — item discounts; `apps/pos_orders/writer.py` — indirect-POS pending orders). Adding a new write path is a reviewed decision — never a casual `UPDATE`/`INSERT`. Physical stock movements are still done by staff in SOFTECH.
5. **Never store plain OTP.** Always hash with HMAC-SHA256 + random salt.
6. **Always check `Branch.is_operational`** before creating reservations.
7. **Immutable records stay immutable.** Do not add update endpoints for `VoucherRedemption`, `IncentiveTransaction`, `StockCountSnapshot`.
8. **Update this documentation** whenever architecture changes.
