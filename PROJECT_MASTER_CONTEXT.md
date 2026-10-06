# ElRezeiky ERP — PROJECT MASTER CONTEXT
> **Load this first in every new session.** Authoritative single-source summary.  
> Last updated: 2026-06-01 | Branch: `claude/modules-config-stockcount-shortage-vouchers-invoices-incentives`

---

## 1. What This System Is

**ElRezeiky Pharmacy Operations Platform** — full-stack ERP extension for a multi-branch Egyptian pharmacy chain.  
Purpose: CRM, sales follow-up, inventory, demand, transfers, incentives, vouchers, analytics, finance.

| Layer | Tech | Notes |
|-------|------|-------|
| Backend | Django 4.2 + DRF + Channels | ASGI via Daphne |
| Scheduler | APScheduler 3.10 | In-process, not Celery |
| Real-time | Django Channels + Redis | WebSocket notifications |
| Primary DB | PostgreSQL | All platform data |
| ERP DB | SOFTECH (Sybase via pyodbc) | **READ ONLY — NEVER write** |
| Frontend | React 18 + Vite + Tailwind | RTL Arabic-first SPA |
| State | TanStack Query + Zustand | Server state + auth state |
| HTTP | Axios (interceptors add JWT) | Base path `/api/` |
| Auth | JWT (simplejwt) | `Authorization: Bearer <token>` |

**Working directory:** `C:\Users\basse\OneDrive\ElRezeiky Depts\IT Software Development\Claude Development\Reservation Module`

---

## 2. Non-Negotiable Architecture Rules

1. **SOFTECH is read-only.** Mirror via `sync_erp` management command. Django never writes to SOFTECH.
2. **ERP ID spaces differ:** `Customer.softech_pic` = global phcode ≠ `softech_id` (branch-local).
3. **No plain OTP storage.** `VoucherOTP` stores HMAC-SHA256 + salt only.
4. **Immutable audit records.** `VoucherRedemption`, `IncentiveTransaction`, `StockCountSnapshot.expected_qty` — no update endpoints.
5. **No duplicate chatter.** Only extend `ChatterMessage` or the module's own log model.
6. **No duplicate demand intake.** Use `Reservation` or `DemandRecord` — never a new model.
7. **ERP stores 102/103/105 are quarantine** — exclude from all stock calculations.
8. **`softech_pic`** is the unique customer key across branches. `softech_id` is branch-local only.
9. **All APIs paginate.** Default 50, cursor-based. Frontend always uses `results || data`.
10. **Roles control branch access:** `access_all_branches`, `allowed_branches`, `restricted_branches` on `StaffProfile`.

---

## 3. Module Status & App Map

### Complete
| App | Purpose | Key Models |
|-----|---------|-----------|
| `apps/branches` | Branch master + feature flags | `Branch` |
| `apps/catalog` | Item master, stock, barcodes, bundles | `Item`, `ItemStock` |
| `apps/customers` | Customer master, health profiles, CRM segments | `Customer`, `CustomerHealthProfile`, `PurchaseHistory` |
| `apps/reservations` | Reservation workflow + ERP match | `Reservation`, `ReservationActivity` |
| `apps/demand` | Demand records + SLA engine | `DemandRecord`, `DemandItem`, `DemandLog` |
| `apps/transfers` | Inter-branch transfer approval | `TransferRequest`, `TransferRequestItem` |
| `apps/users` | Staff profiles, roles, ERP user cache | `StaffProfile`, `ERPUser` |
| `apps/notifications` | Notifications + WebSocket + chatter | `Notification`, `ChatterMessage` |
| `apps/vouchers` | Voucher platform, OTP, POS redemption | `Voucher`, `VoucherOTP`, `VoucherRedemption` |
| `apps/incentives` | Sales incentive engine + settlements | `IncentiveProgram`, `IncentiveTransaction`, `IncentiveSettlement` |
| `apps/stockcount` | Stock count sessions | `StockCountSession`, `StockCountSnapshot` |
| `apps/shortage` | Shortage lists + OCR | `ShortageList`, `ShortageItem` |
| `apps/chronic` | Chronic medication tagging | `ChronicItem` |
| `apps/config` | System settings + dropdowns | `SystemSetting`, `DropdownOption`, `PharmacyProfile` |
| `apps/sync` | ERP sync management | `SyncLog` |

### Partial / In Progress
| App | Status | What's Missing |
|-----|--------|---------------|
| `apps/followups` | **REBUILT 2026-06-01** | Backend complete; frontend fully rewritten |
| `apps/callcenter` | Partial | Escalation workflow UI |
| `apps/purchasing` | Partial | Transfer recommendations UI |
| `apps/analytics` | Partial | Charts not wired to real data |
| `apps/finance` | Partial | Data source definitions |
| `apps/campaigns` | Stub | Send integration |
| `apps/recommendations` | Partial | FBT engine exists: `get_fbt_for_item(item_id, limit)` |
| `apps/invoices` | Partial | Invoice approval flow |

---

## 4. Follow-Up Module — Complete Spec (apps/followups)

> Primary sales engine for chronic refills and proactive customer outreach.

### 4.1 Models
```
ChronicMedicationProfile (OneToOne with catalog.Item)
  is_chronic, avg_daily_usage, pack_size, expected_duration_days, followup_before_days
  source: manual | erp_infer
  Property: followup_trigger_day = expected_duration_days - followup_before_days

FollowUpTask
  customer (FK → customers.Customer, nullable)
  item     (FK → catalog.Item, nullable)
  branch   (FK → branches.Branch, nullable)
  chronic_profile (FK → ChronicMedicationProfile, nullable)
  assigned_to, created_by, completed_by (FK → users.StaffProfile)
  task_type: refill | chronic | demand | custom
  status: pending | called | done | missed | auto_closed | cancelled
  sales_channel: CharField  →  91=كاش/مشي  90=توصيل  13=عميل دائم  15=تأمين
  due_date, source_sale_date, source_erp_transaction, closing_erp_transaction
  attempts, notes, result_note, reminder_at, reminder_sent
  Properties:
    sales_channel_label, channel_is_favoured, channel_priority (1–4)
    is_overdue, days_until_due, days_overdue
    customer_phone, best_phone, whatsapp_url
    render_whatsapp_message() → pre-filled Arabic string
    whatsapp_url_with_message → wa.me URL + encoded message
```

### 4.2 Sales Channel Priority
| Code | Label | Favoured | Priority |
|------|-------|---------|---------|
| 91 | كاش / مشي | Yes | 1 |
| 90 | توصيل | Yes | 1 |
| 13 | عميل دائم | Yes | 2 |
| 15 | تأمين | No | 4 |

### 4.3 API Endpoints (base: `/api/followups/`)
| Method + Path | Purpose |
|---------------|---------|
| `GET  tasks/` | List (full filters) |
| `GET  tasks/{id}/` | Detail with FBT + call history |
| `GET  tasks/dashboard/` | KPI stats |
| `GET  tasks/filter-meta/` | Dropdown options for UI |
| `POST tasks/{id}/call/` | Mark called |
| `POST tasks/{id}/done/` | Mark done |
| `POST tasks/{id}/missed/` | Mark missed |
| `POST tasks/{id}/whatsapp/` | Mark called + return wa.me URL with message |
| `POST tasks/{id}/log-call/` | Create CallLog + update task |
| `POST tasks/generate/` | Full generation pipeline |
| `POST tasks/auto-close/` | Auto-close ERP-confirmed tasks |
| `POST tasks/escalate/` | Escalate overdue → missed |
| `POST tasks/backfill-channels/` | Backfill sales_channel from customer |
| `GET/POST chronic/` | ChronicMedicationProfile CRUD |
| `POST chronic/infer-from-erp/` | Auto-create profiles from ERP history |

### 4.4 Advanced Filter Params (GET /tasks/)
```
status, task_type
sales_channel  (csv: "91,90,13")
favoured_only  (1 = channels 91, 90, 13 only — excludes insurance)
branch, assigned_to
indication     (text match on effect_name_ar)
effect_code, medicine_type
item_search    (name / scientific / softech_id / active_ingredients)
customer_search (name / phone / whatsapp_phone)
segment, churn_segment
due_after, due_before  (YYYY-MM-DD)
overdue_only   (1)
by_priority    (1 = channel rank first, then due_date)
ordering       (due_date | -due_date | created_at | -created_at | sales_channel)
page_size
```

### 4.5 API Response Shape (tasks list + detail)
```json
{
  "customer": {
    "id": 42, "name": "...", "phone": "...", "whatsapp_phone": "...",
    "phcode": "01HD1425", "channel_code": "91", "channel_label": "كاش / مشي",
    "segment": "loyal", "churn_segment": "low", "churn_score": 12.5,
    "ltv": 8500.0, "days_since_last_visit": 25, "is_linked": true
  },
  "product": {
    "id": 100, "name": "...", "name_scientific": "...", "active_ingredients": "...",
    "indication": "...", "dosage_form": "...", "pack_size_label": "30 قرص",
    "medicine_type": "...", "pack_price": 45.0,
    "avg_daily_usage": 1.0, "expected_duration_days": 30
  },
  "refill": {
    "last_sale_date": "2026-05-01", "due_date": "2026-06-01",
    "days_until_due": 3, "days_overdue": 0, "is_overdue": false,
    "source_transaction": "INV-12345"
  },
  "complementary": [{ "id": 200, "name": "...", "indication": "...", "pack_price": 30.0 }],
  "call_history": [{ "id": 5, "direction": "outbound", "purpose": "refill",
                     "status": "answered", "summary": "...", "created_at": "..." }]
}
```

### 4.6 Frontend Page Structure (FollowUpsPage.jsx)
- **Header**: title + KPI strip + Generate/Backfill buttons (admin only) + status tab strip
- **FilterPanel** (collapsible): channel checkboxes + favoured_only toggle, item/customer search, indication dropdown, medicine type, segment, churn_segment, branch, date range, overdue-only, priority sort
- **TaskCard**: channel color strip, customer name + phone + segment + churn badges, product name + indication + dosage form + pack size + dosing, refill timing, LTV, quick actions (WhatsApp link + "تسجيل النتيجة" button)
- **TaskDrawer** (slide-in, loads `/tasks/{id}/`): 5 tabs:
  - Overview: customer detail, refill timing, quick action buttons
  - Product: full catalog data + dosing schedule
  - WhatsApp: pre-filled Arabic message + send + log-call form
  - Cross-sell: FBT complementary products
  - Call history: recent CallLog entries
- **QuickActionModal**: inline call/done/missed popup (no drawer needed)

---

## 5. Customer / CRM Data Shape

```
Customer
  softech_pic          — GLOBAL unique key (phcode) — use this for lookups
  softech_id           — branch-local ONLY
  softech_ptclassifcode — channel code (91/90/13/15)
  person_classif_label  — channel label
  name, phone, whatsapp_phone, email, address
  segment: vip | loyal | regular | at_risk | dormant | churned
  churn_segment: low | medium | high | critical
  churn_score: 0.0–1.0
  ltv: EGP lifetime value
  days_since_last_visit

PurchaseHistory  (ERP mirror)
  softech_invoice_id, invoice_date, branch, channel_code
  total_amount, net_amount, payment_method

PurchaseHistoryLine
  item, qty, unit_price, line_total
```

---

## 6. Catalog Item Fields (relevant to follow-up)

```
Item
  softech_id, name, name_scientific
  active_ingredients
  effect_code, effect_name_ar, effect_name2_ar   ← indications
  shape_name_ar                                    ← dosage form
  medicine_type, medicine_type_name_ar
  pack_qty, unit_name                              ← pack size
  pack_price, unit_price
  requires_fridge
```

---

## 7. ERP Identity Mapping (CRITICAL — never confuse)

```
SOFTECH stktransm.phcode = localcustomers.phcode   (e.g. "01HD1425")
Django  Customer.softech_id = personsdata.personcode  (e.g. "4827")
```
These are DIFFERENT ID spaces. Correct lookup: `phcode → LocalCustomer → linked_customer → Customer`

---

## 8. Key API Quick Reference

| Need | Endpoint |
|------|----------|
| Login | `POST /api/auth/login/` |
| Item search | `GET /api/items/?q=...` |
| Customer search | `GET /api/customers/?q=name_or_phone` |
| Follow-up task list | `GET /api/followups/tasks/?favoured_only=1&overdue_only=1` |
| Follow-up task detail | `GET /api/followups/tasks/{id}/` |
| Follow-up KPIs | `GET /api/followups/tasks/dashboard/` |
| Filter dropdowns | `GET /api/followups/tasks/filter-meta/` |
| WhatsApp outreach | `POST /api/followups/tasks/{id}/whatsapp/` |
| Log call to call center | `POST /api/followups/tasks/{id}/log-call/` |
| Generate tasks | `POST /api/followups/tasks/generate/` |
| Backfill channels | `POST /api/followups/tasks/backfill-channels/` |
| Create reservation | `POST /api/reservations/` |
| Approve transfer | `POST /api/transfers/{id}/approve/` |
| Voucher flow | `generate-otp/ → verify-otp/ → create-document/ → mark-used/` |

---

## 9. Frontend API Client (followupsApi in client.js)

```js
followupsApi.dashboard()                  // GET KPIs
followupsApi.list(params)                 // GET tasks with filters
followupsApi.detail(id)                   // GET single task (FBT + history)
followupsApi.filterMeta()                 // GET dropdown options
followupsApi.generate(data)               // POST generate pipeline
followupsApi.escalate(data)               // POST escalate overdue
followupsApi.autoClose()                  // POST auto-close
followupsApi.backfillChannels()           // POST backfill sales_channel
followupsApi.call(id, note)              // POST mark called
followupsApi.done(id, note)              // POST mark done
followupsApi.missed(id, note)            // POST mark missed
followupsApi.whatsapp(id)               // POST → returns whatsapp_url_with_message
followupsApi.logCall(id, { status, notes, mark_done }) // POST → creates CallLog
followupsApi.create(data)               // POST create task
followupsApi.update(id, data)           // PATCH update task
followupsApi.listChronic(params)        // GET chronic profiles
followupsApi.inferFromErp()             // POST infer profiles from ERP
```

---

## 10. Staff Roles

| Role | Access |
|------|--------|
| `admin` | Full system + all branches |
| `pharmacist` | Own branch: clinical, reservations, demand |
| `call_center` | All branches read + customer contact + follow-ups |
| `purchasing` | Procurement, transfers, demand engine |
| `cashier` | Voucher redemption, customer lookup |
| `inventory` | Stock count, shortage |
| `branch_manager` | Own branch full access |
| `analyst` | Analytics + reports (read-only) |
| `finance` | Finance module |

Branch staff (non-admin, non-call_center, non-purchasing) see only tasks for their own branch.

---

## 11. Management Commands

| Command | Schedule | Purpose |
|---------|----------|---------|
| `segment_customers` | Daily | CRM segmentation + churn scoring |
| `tag_chronic_items` | Weekly | Detect chronic medications |
| `sync_erp` | Configurable | SOFTECH → PostgreSQL sync |
| `demand_engine_run` | Daily | Demand calculation |
| `generate_followup_tasks` | Daily | Create follow-up tasks from ERP |
| `send_followup_reminders` | Hourly | Notify overdue tasks |
| `seed_config` | One-time | Seed default settings |

---

## 12. Known Issues & Tech Debt

| ID | Severity | Issue |
|----|---------|-------|
| TD-C001 | CRITICAL | No role-based UI action guards |
| TD-C002 | CRITICAL | ERP write operations manual, no verification |
| TD-C003 | CRITICAL | No automated SLA escalation |
| TD-H001 | HIGH | ChatterMessage missing voice note |
| TD-H005 | HIGH | No React error boundaries on detail pages |
| DUP-001 | HIGH | Two demand-intake paths: Reservation vs DemandRecord |
| DUP-004 | MEDIUM | FollowUpTask exists in both demand + followups apps |

---

## 13. File Locations Quick Reference

| What | Path |
|------|------|
| Follow-up models | `apps/followups/models.py` |
| Follow-up views | `apps/followups/views.py` |
| Follow-up serializers | `apps/followups/serializers.py` |
| Follow-up services | `apps/followups/services.py` |
| Follow-up frontend | `frontend/src/pages/FollowUpsPage.jsx` |
| All API methods | `frontend/src/api/client.js` |
| Auth store | `frontend/src/store/authStore.js` |
| Catalog model | `apps/catalog/models.py` |
| Customer model | `apps/customers/models.py` |
| Call center model | `apps/callcenter/models.py` |
| FBT engine | `apps/recommendations/engine.py` |
| ERP models | `apps/erp/models.py` |
| Architecture docs | `docs/architecture/` (12 files) |
| This file | `PROJECT_MASTER_CONTEXT.md` |

---

## 14. Golden Rules for Development

1. **Search before building** — grep + check this doc before creating anything.
2. **ERP is read-only** — zero writes to SOFTECH from Django. Ever.
3. **Use `softech_pic`**, not `softech_id`, for global customer lookups.
4. **`select_related`/`prefetch_related`** on every list queryset — no N+1.
5. **Paginate all lists** — frontend always handles `results || data`.
6. **Test channel filter** with codes 91/90/13/15 — not labels.
7. **`favoured_only=1`** = channels 91, 90, 13 (excludes insurance 15).
8. **WhatsApp phone**: strip spaces/dashes, replace leading `0` with `20`.
9. **FBT**: `from apps.recommendations.engine import get_fbt_for_item(item_id, limit=6)`.
10. **Call logs**: `apps.callcenter.models.CallLog` — fields: direction, purpose, status, handled_by.
11. **Never skip migrations** — add field to model → create migration → migrate.
12. **Update this document** on significant architecture changes.
