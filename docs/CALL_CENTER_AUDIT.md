# Call Center Operations Platform — System Audit Report
**ElRezeiky Pharmacies — Claude ERP Extension**
**Date:** 2026-05-26 | **Scope:** Customer Interaction + Call Center Upgrade

---

## 0. Executive Summary

The system already has a **strong foundational layer** for call center operations.
The goal is **zero duplication** — extend what exists, fill the gaps, wire up what is isolated.

| Category | Count |
|---|---|
| **Existing models reusable as-is** | 22 |
| **Models requiring field extensions** | 8 |
| **New models required** | 5 |
| **Existing API endpoints reusable** | 47 |
| **New API endpoints required** | 18 |
| **Existing frontend pages reusable** | 8 |
| **Frontend pages to extend** | 3 |
| **New frontend sections/tabs** | 6 |

**SOFTECH remains read-only source of truth. No INSERT/UPDATE/DELETE on Sybase.**

---

## 1. Existing Assets Inventory

### 1.1 Backend Models

| App | Model | Purpose | Quality |
|---|---|---|---|
| `callcenter` | `CallLog` | Inbound/outbound call records with auto-phone→customer match | ★★★★ Good |
| `callcenter` | `AddressUpdate` | Address edits collected during calls → apply to Customer | ★★★★ Good |
| `customers` | `Customer` | Core customer entity (SOFTECH-synced) with phone, chronic_conditions, preferred_branch | ★★★★★ Excellent |
| `customers` | `CustomerNote` | Staff notes per customer | ★★★★ Good |
| `customers` | `PurchaseHistory` | SOFTECH-synced invoice headers | ★★★★★ Excellent |
| `customers` | `PurchaseHistoryLine` | Line items with `cost_at_sale` (authoritative COGS) | ★★★★★ Excellent |
| `demand` | `DemandRecord` | Customer demand/lost-sales tracker with SLA, priorities, sources | ★★★★★ Excellent |
| `demand` | `DemandItem` | Line items per demand (catalog + free-text fallback) | ★★★★★ Excellent |
| `demand` | `FollowUpTask` | Demand-linked follow-up tasks | ★★★★ Good |
| `demand` | `DemandLog` | Chatter/call/system log per demand | ★★★★ Good |
| `demand` | `ItemDemandStat` | Per-item/branch demand intelligence (lost count, suggest_order) | ★★★★ Good |
| `followups` | `ChronicMedicationProfile` | Chronic patient profile (linked to customer via PIC) | ★★★★ Good |
| `followups` | `FollowUpTask` | Chronic-medication follow-up (different from demand's version) | ★★★ Duplicate concern |
| `reservations` | `Reservation` | Item reservation with SLA, channel, ERP match | ★★★★★ Excellent |
| `reservations` | `ReservationActivity` | Chatter per reservation | ★★★★ Good |
| `delivery` | `CustomerLocation` | OneToOne geo location per customer | ★★★★ Good |
| `delivery` | `DeliveryOrder` | Delivery tracking with customer/branch/ETA | ★★★★★ Excellent |
| `notifications` | `Notification` | In-app + WebSocket notifications | ★★★★★ Excellent |
| `notifications` | `ChatterMessage` | Threaded comments on any model | ★★★★ Good |
| `tasks` | `OperationalTask` | Full task management (type, priority, status, chatter, attachments) | ★★★★★ Excellent |
| `vouchers` | `Voucher` | Voucher programs with eligibility check by phone | ★★★★ Good |
| `audit` | `AuditLog` | Immutable audit trail for all domain events | ★★★★★ Excellent |
| `users` | `StaffProfile` | Staff with roles: admin/call_center/pharmacist/salesperson/delivery | ★★★★ Good |

### 1.2 Existing Roles

```
admin         — Full system access
call_center   — All branches + all call logs
pharmacist    — Own branch
salesperson   — Own branch
purchasing    — HQ only
delivery      — Delivery module
viewer        — Read only
```

Missing roles: **supervisor**, **quality_manager** (needed for QA scoring)

### 1.3 Existing API Endpoints (Call Center relevant)

```
GET  /api/callcenter/calls/                      — list call logs
POST /api/callcenter/calls/                      — create call log
GET  /api/callcenter/calls/{id}/                 — call detail
PATCH/api/callcenter/calls/{id}/                 — update
GET  /api/callcenter/calls/lookup/?phone=        — 🔑 CTI lookup (customer + calls + demands + reservations)
GET  /api/callcenter/calls/pending-callbacks/    — pending callbacks
GET  /api/callcenter/calls/dashboard/            — call center KPIs
POST /api/callcenter/calls/{id}/address-updates/ — capture address during call
POST /api/callcenter/address-updates/{id}/apply/ — apply address update

GET  /api/customers/{id}/purchases/              — full purchase history
GET  /api/customers/{id}/reservations/           — customer reservations
GET  /api/customers/{id}/top_items/              — top purchased items
POST /api/customers/{id}/notes/                  — add note
PATCH/api/customers/{id}/update_conditions/      — update chronic conditions

GET  /api/demand/                                — demand list
POST /api/demand/                                — create demand
GET  /api/demand/{id}/                           — demand detail
POST /api/demand/{id}/assign/                    — assign agent
POST /api/demand/{id}/follow-up/                 — schedule follow-up
POST /api/demand/{id}/stock-eta/                 — set ETA
POST /api/demand/{id}/suggest-transfer/          — suggest transfer
POST /api/demand/{id}/flag-purchasing/           — flag for purchasing
POST /api/demand/{id}/fulfill/                   — mark fulfilled
POST /api/demand/{id}/lost/                      — mark as lost sale
POST /api/demand/{id}/cancel/                    — cancel
POST /api/demand/{id}/items/                     — add item to demand
GET  /api/demand/{id}/logs/                      — call/note history
POST /api/demand/{id}/logs/                      — add log
GET  /api/demand/{id}/followups/                 — follow-up tasks
POST /api/demand/{id}/schedule-followup/         — create follow-up
POST /api/demand/{id}/followups/{id}/complete/   — complete follow-up
POST /api/demand/{id}/enrich/                    — ERP enrichment
GET  /api/demand/dashboard/                      — demand KPIs

GET  /api/followups/tasks/                       — chronic follow-ups list
POST /api/followups/tasks/{id}/call/             — mark called
POST /api/followups/tasks/{id}/done/             — mark done
GET  /api/followups/tasks/dashboard/             — follow-up KPIs

GET  /api/delivery/customers/{id}/location/      — customer location
PUT  /api/delivery/customers/{id}/location/      — update location
GET  /api/delivery/                              — delivery orders
```

### 1.4 Frontend Pages (Existing)

| Page | Route | Covers |
|---|---|---|
| `CallCenterPage.jsx` | `/callcenter` | Phone lookup, call log entry, customer context panel |
| `CustomerDetailPage.jsx` | `/customers/:id` | 861-line detail: Timeline, Purchases, Reservations, Top Items |
| `CustomersPage.jsx` | `/customers` | Customer list with search |
| `DemandPage.jsx` | `/demand` | Demand list |
| `DemandDetailPage.jsx` | `/demand/:id` | Demand workflow + chatter |
| `DemandDashboardPage.jsx` | `/demand/dashboard` | Demand KPIs |
| `FollowUpsPage.jsx` | `/followups` | Chronic follow-ups |
| `DeliveryDashboard.jsx` | `/delivery` | Delivery tracking |

---

## 2. Reuse Classification

### 2.1 KEEP (use as-is, no change)

| Asset | Reason |
|---|---|
| `Customer` model | Complete, SOFTECH-synced, solid phone matching |
| `PurchaseHistory` + `PurchaseHistoryLine` | Authoritative sales history from SOFTECH |
| `CustomerLocation` (delivery app) | OneToOne geo already working |
| `DeliveryOrder` + lifecycle | Full delivery tracking with status log |
| `DemandRecord` + `DemandItem` | Covers lost sales / item requests / SLA |
| `DemandLog` (chatter) | Call/WhatsApp/system log per demand |
| `ItemDemandStat` | Demand intelligence → purchasing feed |
| `Reservation` + `ReservationActivity` | Complete reservation with chatter |
| `OperationalTask` | Full task management — use for follow-up tasks |
| `Notification` + `ChatterMessage` | Real-time + threaded comments |
| `AuditLog` | Immutable event trail |
| `Voucher` + eligibility check | Phone-based voucher system |
| `CallLog.lookup()` endpoint | **Core CTI enrichment** — already queries customer, demands, reservations, follow-ups |
| All `customersApi.*` endpoints | Full customer CRUD already exists |
| All `demandApi.*` endpoints | Full demand workflow already exists |
| `CallCenterPage.jsx` | Strong base — extend rather than replace |
| `CustomerDetailPage.jsx` | 861-line foundation — add new tabs |

### 2.2 EXTEND (keep model, add fields/endpoints)

| Asset | Extensions Required |
|---|---|
| `CallLog` | + `recording_url`, `ai_summary`, `ai_intent`, `ai_sentiment`, `ai_urgency`, `voice_transcript`, `prescription_image`, `case` FK, `quality_score` |
| `Customer` | + `segment` (vip/at_risk/dormant/normal), `ltv` (computed), `last_visit_date`, `purchase_frequency`, `complaint_risk_score`, `churn_days` |
| `CallLog.lookup()` endpoint | + include `call_logs`, `cases`, `delivery_orders`, `vouchers`, `lifetime_value`, `segment`, `churn_signal` |
| `CallLog.dashboard()` endpoint | + AHT breakdown, FCR rate, CSAT avg, SLA breach %, by_purpose trends |
| `DemandRecord` | + `call_log` FK (link demand to originating call), `case` FK |
| `AuditLog.ACTION_CHOICES` | + call_center events: `call_quality_scored`, `case_created`, `case_resolved` |
| `Notification.NOTIFICATION_TYPES` | + `case_created`, `case_escalated`, `call_quality_alert`, `csat_submitted` |
| `StaffProfile` | + `call_quality_avg`, `fcr_rate`, `aht_seconds_avg` (computed / cached) |
| `ROLE_CHOICES` | + `supervisor` (manages agents, sees quality scores), `quality_manager` |

### 2.3 MERGE (two overlapping implementations → unify)

| Issue | Resolution |
|---|---|
| **Two `FollowUpTask` models**: `demand.FollowUpTask` and `followups.FollowUpTask` (chronic) | → Both KEEP as-is (different purposes: demand-linked vs. chronic-protocol). Cross-link via `CallLog` only. Do NOT merge — different schemas. |
| **`DemandRecord.source` vs `CallLog.purpose`**: demand has source, call has purpose | → `CallLog` creates `DemandRecord` with `source='call_center'`. Link via FK. |
| **`CustomerLocation` (delivery) vs `AddressUpdate` (callcenter)**: two address systems | → `AddressUpdate.apply()` already writes to `Customer.address`. Keep both — they serve different flows. |
| **`DemandLog` vs `ChatterMessage` vs `ReservationActivity`**: 3 chatter patterns | → Keep all 3 (each domain-scoped). `CustomerCase` will have its own `ChatterMessage` via generic FK. |

### 2.4 REMOVE / DEPRECATE

| Asset | Action | Reason |
|---|---|---|
| `CallLog.local_customer` FK (references `erp.LocalCustomer`) | **Remove field** in extension | Already null/ignored. `Customer.softech_pic` is the ERP link. |
| `CallLogDetailSerializer.local_customer_phcode` | Remove if `local_customer` field removed | Dangling serializer field |
| `CallLog.payment_method` | Keep but move to `CustomerCaseRequest` | Low-value on call log; belongs on structured request |

---

## 3. Gap Analysis — What Must Be Built

### GAP-1: Customer 360 Profile Enrichment
**Status:** Partial — `CustomerDetailPage` exists with 4 tabs, but missing segment signals, LTV display, call history, case history.
**Backend:** Add `segment`, `ltv`, `churn_days`, `last_visit_date` computed properties / cached fields to `Customer`. Add new `customer_360()` view aggregating all dimensions.
**Frontend:** Add tabs to `CustomerDetailPage.jsx`: "المكالمات" (Calls), "الحالات" (Cases), "التسليم" (Deliveries).

### GAP-2: Customer Segmentation + Indicators
**Status:** Missing — no VIP/At Risk/Dormant logic anywhere.
**Backend:** New `segment_customers` management command + `CustomerSegment` cached table OR computed property on `Customer`.
**Frontend:** Show segment badge in `CustomerDetailPage` hero card and `CallCenterPage` lookup panel.

### GAP-3: Customer Case Management
**Status:** Missing — no `CustomerCase` model. Multiple interactions (calls, demands, complaints) are isolated.
**Backend:** New `CustomerCase` model in `callcenter` app.
**Frontend:** New `CasesPage.jsx` + tab in `CustomerDetailPage.jsx`.

### GAP-4: Structured Call Documentation (Call Types + Attachments)
**Status:** Partial — `CallLog` has `purpose` and `notes` but no structured sub-form per reason, no attachments, no voice transcript.
**Backend:** Add `CallLogAttachment`, `VoiceTranscript` to `callcenter` models. Add `recording_url`, `ai_summary` to `CallLog`.
**Frontend:** Extend `CallCenterPage` call-logging form with structured fields per purpose + attachment upload.

### GAP-5: AI Call Summarization
**Status:** Missing. System has `google-genai` installed (used in invoices OCR) but no call AI.
**Backend:** New `ai_summarize_call()` async task. Uses Gemini to: extract intent, urgency, sentiment; generate Arabic summary; suggest next action.
**Frontend:** Show AI summary card in call log detail + confidence indicators.

### GAP-6: Unified Follow-Up from Call
**Status:** Partial — `DemandRecord` has follow-up. But if a call is NOT about a demand, there's no follow-up mechanism.
**Backend:** `CallLog` needs ability to create `OperationalTask` (existing) with `task_type='customer'` — this avoids building a third follow-up model. Wire via API action.
**Frontend:** "أضف متابعة" button on every call log → opens `OperationalTask` create form.

### GAP-7: Customer Request Management
**Status:** Covered by `DemandRecord` for unavailable items. But general "reserve item", "request price", "return", "replacement", "delivery request" are not structured.
**Backend:** `CustomerRequest` model (new) OR extend `DemandRecord.PURPOSE_CHOICES` + add `request_type` field.
**Recommendation:** Extend `DemandRecord` with `request_type` field. Avoid new model.
**Frontend:** "نوع الطلب" field in demand creation form.

### GAP-8: Lost Sales → Purchasing Feed
**Status:** `ItemDemandStat` feeds `DemandRecord.status='lost'` into demand counts. `purchasing/views.py` uses `ItemDemandStat`. The pipeline exists but is NOT automatically triggered.
**Backend:** Signal/task: when `DemandRecord` status → `lost`, update `ItemDemandStat`. Already partially implemented — strengthen.
**Frontend:** Show "طلبات العملاء" column in `PurchasingDashboard.jsx` — link to lost demand items.

### GAP-9: Call Quality Metrics (AHT / FCR / CSAT / SLA)
**Status:** `callcenter/dashboard` has `avg_duration_seconds` only. No CSAT collection, no FCR tracking, no SLA breach tracking.
**Backend:** New `CallQualityScore` model. New `csat_submit` endpoint (customer self-service or agent-entered). AHT/FCR computed in dashboard endpoint.
**Frontend:** Quality tab in Manager Dashboard (new or extend `CallCenterPage`).

### GAP-10: Manager Operations Dashboard
**Status:** `callcenter/dashboard` is basic (30d aggregates). Missing real-time/today view, by-branch comparison, agent leaderboard.
**Backend:** Extend `callcenter/dashboard` with today/week filters, by_branch, by_agent, SLA breach list.
**Frontend:** Extend `CallCenterPage.jsx` with a "المدير" tab, OR create `CallCenterDashboardPage.jsx`.

---

## 4. Schema Extensions Required

### 4.1 Extend `CallLog` (apps/callcenter/models.py)

```python
# Add to CallLog:
case = models.ForeignKey(
    'callcenter.CustomerCase', null=True, blank=True,
    on_delete=models.SET_NULL, related_name='calls',
)
recording_url = models.URLField(blank=True, verbose_name='رابط التسجيل')
voice_transcript = models.TextField(blank=True, verbose_name='النص الصوتي')
prescription_image = models.ImageField(
    upload_to='callcenter/prescriptions/%Y/%m/', null=True, blank=True
)

# AI fields (populated asynchronously)
ai_summary  = models.TextField(blank=True, verbose_name='ملخص الذكاء الاصطناعي')
ai_intent   = models.CharField(max_length=50, blank=True)  # e.g. "purchase", "complaint"
ai_sentiment = models.CharField(
    max_length=15, blank=True,
    choices=[('positive', 'إيجابي'), ('neutral', 'محايد'), ('negative', 'سلبي')],
)
ai_urgency  = models.PositiveSmallIntegerField(null=True, blank=True)  # 1-5 scale
ai_processed_at = models.DateTimeField(null=True, blank=True)

quality_score = models.PositiveSmallIntegerField(
    null=True, blank=True,
    verbose_name='نقاط الجودة',
    help_text='1–5 — من المشرف أو من الذكاء الاصطناعي',
)
```

### 4.2 New Model: `CustomerCase` (apps/callcenter/models.py)

```python
class CustomerCase(models.Model):
    """
    Groups multiple interactions (calls, demands, complaints) per customer
    into a unified case for root-cause tracking and resolution.
    """
    CATEGORY_CHOICES = [
        ('complaint',   'شكوى'),
        ('inquiry',     'استفسار'),
        ('request',     'طلب'),
        ('lost_sale',   'بيعة مفقودة'),
        ('delivery',    'توصيل'),
        ('support',     'دعم'),
        ('other',       'أخرى'),
    ]
    STATUS_CHOICES = [
        ('open',       'مفتوحة'),
        ('working',    'قيد المعالجة'),
        ('waiting',    'انتظار عميل'),
        ('escalated',  'مُصعَّدة'),
        ('resolved',   'محلولة'),
        ('closed',     'مغلقة'),
    ]

    case_number  = models.CharField(max_length=20, unique=True, blank=True)
    customer     = models.ForeignKey('customers.Customer', on_delete=models.CASCADE, related_name='cases')
    category     = models.CharField(max_length=15, choices=CATEGORY_CHOICES, db_index=True)
    status       = models.CharField(max_length=12, choices=STATUS_CHOICES, default='open', db_index=True)
    title        = models.CharField(max_length=255)
    description  = models.TextField(blank=True)
    root_cause   = models.TextField(blank=True)
    resolution   = models.TextField(blank=True)
    branch       = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL, null=True)

    # Linked objects
    demand       = models.ForeignKey('demand.DemandRecord', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='cases')
    reservation  = models.ForeignKey('reservations.Reservation', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='cases')
    delivery     = models.ForeignKey('delivery.DeliveryOrder', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='cases')

    # Ownership
    opened_by    = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                     null=True, related_name='opened_cases')
    assigned_to  = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='assigned_cases')

    # SLA
    sla_due      = models.DateTimeField(null=True, blank=True)
    resolved_at  = models.DateTimeField(null=True, blank=True)
    closed_at    = models.DateTimeField(null=True, blank=True)

    # CSAT
    csat_score   = models.PositiveSmallIntegerField(null=True, blank=True)  # 1–5
    csat_note    = models.TextField(blank=True)

    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes  = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['assigned_to', 'status']),
        ]
```

### 4.3 New Model: `CallQualityScore` (apps/callcenter/models.py)

```python
class CallQualityScore(models.Model):
    """QA scoring of call logs — by supervisor or AI."""
    SOURCE_CHOICES = [('supervisor', 'مشرف'), ('ai', 'ذكاء اصطناعي')]

    call_log     = models.OneToOneField(CallLog, on_delete=models.CASCADE, related_name='quality')
    scored_by    = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                     on_delete=models.SET_NULL)
    source       = models.CharField(max_length=12, choices=SOURCE_CHOICES, default='supervisor')
    total_score  = models.PositiveSmallIntegerField()     # 0–100
    greeting     = models.PositiveSmallIntegerField(default=0)  # 0–20
    resolution   = models.PositiveSmallIntegerField(default=0)  # 0–30
    communication= models.PositiveSmallIntegerField(default=0)  # 0–25
    accuracy     = models.PositiveSmallIntegerField(default=0)  # 0–25
    notes        = models.TextField(blank=True)
    scored_at    = models.DateTimeField(auto_now_add=True)
```

### 4.4 Extend `Customer` (apps/customers/models.py)

```python
# Add cached analytics fields — updated by management command:
segment = models.CharField(
    max_length=15, blank=True, db_index=True,
    choices=[
        ('vip',      'VIP 👑'),
        ('loyal',    'مخلص'),
        ('regular',  'عادي'),
        ('at_risk',  'في خطر ⚠️'),
        ('dormant',  'نائم 💤'),
        ('new',      'جديد 🌱'),
        ('churned',  'مفقود ❌'),
    ],
    verbose_name='شريحة العميل',
)
ltv = models.DecimalField(
    max_digits=12, decimal_places=2, null=True, blank=True,
    verbose_name='القيمة الإجمالية للعميل',
)
last_visit_date   = models.DateField(null=True, blank=True, db_index=True)
purchase_count_90d = models.PositiveIntegerField(default=0)
days_since_last_visit = models.PositiveIntegerField(null=True, blank=True, db_index=True)
complaint_risk_score = models.PositiveSmallIntegerField(
    null=True, blank=True,
    verbose_name='مؤشر خطر الشكوى',
    help_text='0–100 — محسوب من: تكرار الشكاوى، المردودات، أيام الغياب',
)
segment_updated_at = models.DateTimeField(null=True, blank=True)
```

### 4.5 New Management Command: `segment_customers`

```
apps/customers/management/commands/segment_customers.py

Algorithm:
  For each Customer with purchase history:
    ltv = sum(PurchaseHistory.total_amount) WHERE doc_code='115'
    last_visit = max(PurchaseHistory.invoice_date__date)
    days_silent = (today - last_visit).days
    count_90d = PurchaseHistory.filter(last 90 days).count()

    if days_silent < 30 and ltv > P75(ltv): segment = 'vip'
    elif days_silent < 60 and count_90d >= 3: segment = 'loyal'
    elif days_silent < 30: segment = 'regular'
    elif days_silent < 90: segment = 'at_risk'
    elif days_silent < 365: segment = 'dormant'
    elif days_silent >= 365: segment = 'churned'
    elif purchase count == 0: segment = 'new'

Run: daily via APScheduler or management command
```

### 4.6 New Model: `CallLogAttachment` (apps/callcenter/models.py)

```python
class CallLogAttachment(models.Model):
    """Prescription images, voice notes, documents attached to a call."""
    TYPE_CHOICES = [
        ('prescription', 'روشتة'),
        ('image',        'صورة'),
        ('voice',        'مقطع صوتي'),
        ('document',     'مستند'),
    ]
    call_log     = models.ForeignKey(CallLog, on_delete=models.CASCADE, related_name='attachments')
    file         = models.FileField(upload_to='callcenter/attachments/%Y/%m/')
    file_type    = models.CharField(max_length=15, choices=TYPE_CHOICES)
    description  = models.CharField(max_length=255, blank=True)
    uploaded_by  = models.ForeignKey('users.StaffProfile', null=True, on_delete=models.SET_NULL)
    uploaded_at  = models.DateTimeField(auto_now_add=True)
    file_size    = models.PositiveIntegerField(default=0)
```

---

## 5. API Extensions Required

### 5.1 Extend `CallLog` Endpoints

```
POST /api/callcenter/calls/{id}/attachments/           — upload prescription/image/voice
GET  /api/callcenter/calls/{id}/attachments/           — list attachments
DELETE /api/callcenter/calls/{id}/attachments/{att_id}/— delete attachment
POST /api/callcenter/calls/{id}/ai-summarize/          — trigger AI summarization
POST /api/callcenter/calls/{id}/create-case/           — open CustomerCase from call
POST /api/callcenter/calls/{id}/create-followup/       — create OperationalTask from call
POST /api/callcenter/calls/{id}/score/                 — submit quality score
```

### 5.2 New `CustomerCase` Endpoints

```
GET  /api/callcenter/cases/                            — list cases (with filters)
POST /api/callcenter/cases/                            — open case
GET  /api/callcenter/cases/{id}/                       — case detail
PATCH/api/callcenter/cases/{id}/                       — update case
POST /api/callcenter/cases/{id}/assign/                — assign agent
POST /api/callcenter/cases/{id}/escalate/              — escalate
POST /api/callcenter/cases/{id}/resolve/               — mark resolved + capture resolution
POST /api/callcenter/cases/{id}/close/                 — close
POST /api/callcenter/cases/{id}/csat/                  — submit CSAT score
GET  /api/callcenter/cases/dashboard/                  — case KPIs
```

### 5.3 Extend `callcenter/dashboard` Endpoint

```
GET /api/callcenter/calls/dashboard/?period=today|week|month&branch=&agent=

Returns:
{
  "total_calls",
  "answered", "no_answer", "pending_callbacks",
  "today": { total, answered, avg_duration },
  "aht_seconds": <avg handle time — answered calls only>,
  "callback_rate": <pct>,
  "by_purpose": [...],
  "by_agent": [...],
  "sla_breach_count": <demands with breached SLA>,
  "open_cases": <CustomerCase count>,
  "avg_quality_score": <avg CallQualityScore.total_score>,
  "by_branch": [...],
  "callbacks_overdue": [...top 10...],
}
```

### 5.4 Extend `callcenter/lookup` Endpoint

```
GET /api/callcenter/calls/lookup/?phone=...

Add to response:
{
  "customer": {
    ...existing...,
    "segment": "vip",
    "ltv": 12450.00,
    "days_since_last_visit": 14,
    "purchase_count_90d": 7,
    "complaint_risk_score": 12,
    "last_visit_date": "2026-05-10",
  },
  "open_cases": [...],       # CustomerCase list
  "delivery_orders": [...],  # active DeliveryOrders
  "active_vouchers": [...],  # valid Vouchers by phone
  "chronic_profile": {...},  # ChronicMedicationProfile if exists
}
```

### 5.5 New `Customer 360` Summary Endpoint

```
GET /api/customers/{id}/360/

Returns unified profile:
{
  "customer": {...all fields + segment + ltv...},
  "purchase_summary": { ltv, count, avg_basket, last_30d_spend, last_visit },
  "top_categories": [...],
  "recent_calls": [...last 5...],
  "open_demands": [...],
  "open_reservations": [...],
  "active_cases": [...],
  "delivery_history": [...last 3...],
  "chronic_profile": {...},
  "active_vouchers": [...],
  "complaint_risk_score": 12,
  "indicators": {
    "is_vip": bool,
    "is_at_risk": bool,
    "is_dormant": bool,
    "has_open_complaint": bool,
    "has_chronic": bool,
    "delivery_issues": bool,
  }
}
```

### 5.6 Quality Management Endpoints

```
GET  /api/callcenter/quality/                          — list quality scores
POST /api/callcenter/calls/{id}/score/                 — submit score
GET  /api/callcenter/quality/leaderboard/              — agent rankings
```

---

## 6. Workflow Design

### 6.1 Inbound Call Workflow

```
Phone comes in
    ↓
Agent enters phone in CallCenterPage
    ↓
lookup() fires → returns: customer, segment, chronic, demands, reservations, cases, location, vouchers
    ↓
Agent sees Customer 360 panel (identity + signals + open items)
    ↓
Call is handled → agent fills: purpose, notes, status, duration
    ↓
Based on purpose → BRANCH:
  │
  ├─ 'reservation'  → link to open Reservation OR create new
  ├─ 'demand'       → create DemandRecord (source='call_center') linked to CallLog
  ├─ 'complaint'    → create CustomerCase (category='complaint') linked to CallLog
  ├─ 'delivery'     → find DeliveryOrder, add note
  ├─ 'address'      → AddressUpdate form → apply to Customer
  ├─ 'followup'     → find FollowUpTask (chronic or demand), mark called
  ├─ 'refill'       → auto-creates DemandRecord (source='call_center') + schedule follow-up
  └─ 'general'      → CallLog saved with notes
    ↓
Optional: Upload attachments (prescription, voice note, image)
    ↓
Optional: AI summarize → fills ai_summary, ai_intent, ai_sentiment
    ↓
Optional: Schedule callback → CallLog.callback_due
    ↓
CallLog saved → Notification to relevant staff
```

### 6.2 Customer Case Lifecycle

```
OPEN (auto from call OR manual from agent)
    ↓ assign
WORKING (agent taking action)
    ↓ if blocked
WAITING (waiting for customer response / stock / delivery)
    ↓ if serious
ESCALATED (to supervisor / manager)
    ↓ when resolved
RESOLVED (agent enters resolution + root cause)
    ↓ CSAT collected (optional)
CLOSED
```

### 6.3 Lost Sales → Purchasing Pipeline

```
DemandRecord (source='call_center', status='new')
    ↓ no stock found at branch
DemandRecord.status → 'purchasing_flagged'
    ↓
ItemDemandStat.demand_count_30d += 1
ItemDemandStat.suggest_order = True (if count > threshold)
    ↓
ItemDemandMetrics (purchasing engine) reads ItemDemandStat
    ↓
PurchasingDashboard shows demand column
```

### 6.4 AI Summarization Flow

```
CallLog saved with voice_transcript OR notes
    ↓
Agent clicks "ذكاء اصطناعي" button → POST /api/callcenter/calls/{id}/ai-summarize/
    ↓ (async task)
Gemini API:
  prompt: "Analyze this pharmacy call. Extract: intent, urgency (1-5), sentiment,
           summary in Arabic (2 sentences max), suggested next action.
           Call notes: {notes}. Transcript: {transcript}"
    ↓
Response stored: ai_summary, ai_intent, ai_sentiment, ai_urgency
    ↓
Notification to agent: "ملخص الذكاء الاصطناعي جاهز"
```

---

## 7. Frontend Extensions

### 7.1 `CallCenterPage.jsx` Extensions

**Current:** Phone search + lookup panel + call log form.

**Add:**
1. **Customer 360 summary panel** — show segment badge (VIP/At Risk/Dormant), LTV, last visit, chronic flag, complaint risk
2. **Case summary** — show open cases count + quick-open badge
3. **Call Log Form enhancements:**
   - Attachment upload (prescription/image/voice)
   - "إنشاء حالة" button → open `CustomerCase` inline form
   - "متابعة" button → open `OperationalTask` create mini-form
   - "ذكاء اصطناعي" button → trigger AI summarization
4. **Manager tab** — KPI cards: today's calls, avg AHT, pending callbacks, open cases, quality score avg

### 7.2 `CustomerDetailPage.jsx` Extensions

**Current tabs:** Timeline | Purchases | Reservations | Top Items

**Add tabs:**
- **المكالمات** — list of CallLog entries for this customer (with purpose, status, agent, notes)
- **الحالات** — CustomerCase list (status, category, assigned_to, resolution)
- **التوصيل** — DeliveryOrder history with status

**Hero card enrichment:**
- Show `segment` badge (colored: VIP=gold, At Risk=orange, Dormant=gray)
- Show `ltv` formatted
- Show `complaint_risk_score` bar
- Show `days_since_last_visit`

### 7.3 New `CasesPage.jsx` (`/callcenter/cases`)

Kanban or table of CustomerCases:
- Filter: status, category, branch, agent, date range
- Cards: customer name, category, status, age, agent, SLA indicator
- Click → case detail drawer

### 7.4 Manager Dashboard Tab

Either as new page `/callcenter/manager` or tab within `CallCenterPage.jsx`:

```
Cards (top):
  [Total Calls Today]  [Pending Callbacks]  [Open Cases]  [Avg Quality Score]
  [AHT (seconds)]      [Lost Demands]       [CSAT Avg]    [SLA Breaches]

Charts:
  - Calls by Purpose (bar)
  - Calls by Hour (heatmap)
  - Agent Performance (table: calls, avg_duration, quality_score)
  - Branch Comparison (calls, open_cases)
  - Call Outcomes (pie: answered/no_answer/callback)
  - Lost Demand Trend (line: last 30 days)
```

---

## 8. Migration Plan

### Phase 1 — Model Extensions (Week 1)
Priority: Foundation

```
M1-A: Extend CallLog (+recording_url, +ai_*, +case FK, +quality_score)
M1-B: New CustomerCase model
M1-C: New CallLogAttachment model
M1-D: New CallQualityScore model
M1-E: Extend Customer (+segment, +ltv, +last_visit_date, +days_since_last_visit, +complaint_risk_score)
M1-F: New migration: callcenter/migrations/0002_calllog_extensions.py
M1-G: New migration: customers/migrations/0003_customer_segment_fields.py
```

### Phase 2 — Backend APIs (Week 1-2)
Priority: Core workflows

```
M2-A: customer_360() view at GET /api/customers/{id}/360/
M2-B: CustomerCase CRUD + state machine views
M2-C: CallLog attachment upload/delete endpoints
M2-D: Extend callcenter/lookup with segment, cases, delivery, vouchers, chronic_profile
M2-E: Extend callcenter/dashboard with AHT, FCR, quality metrics
M2-F: call_ai_summarize() async view (needs google-genai — already in requirements)
M2-G: call_quality_score() POST endpoint
M2-H: segment_customers management command
```

### Phase 3 — Frontend Extensions (Week 2-3)
Priority: Operator UX

```
M3-A: Extend CallCenterPage with Customer 360 panel, attachment upload, case creation, manager tab
M3-B: Add "المكالمات", "الحالات", "التوصيل" tabs to CustomerDetailPage
M3-C: Add segment + LTV + risk indicators to CustomerDetailPage hero card
M3-D: New CasesPage.jsx (/callcenter/cases)
M3-E: Wire "إنشاء حالة" and "متابعة" buttons in CallCenterPage
```

### Phase 4 — Intelligence Layer (Week 3-4)
Priority: Optimization

```
M4-A: segment_customers APScheduler job (daily at 02:00)
M4-B: AI summarization (ai_summarize_call task via Gemini)
M4-C: complaint_risk_score algorithm + nightly compute
M4-D: Lost demand → purchasing feed (signal on DemandRecord status change)
M4-E: Quality leaderboard + agent scorecards
M4-F: CSAT collection on case close
```

---

## 9. Success KPIs

| KPI | Target | Measurement |
|---|---|---|
| 0 duplicate CRM models | ✅ All existing models reused | `grep -r 'class.*Customer'` shows only 1 |
| 0 new customer tables | ✅ Only segment fields added to existing | Migration diff |
| Call log → case creation rate | > 30% of complaints | `CustomerCase.objects.count() / CallLog.filter(purpose='complaint').count()` |
| Lookup response time | < 300ms | Django Debug Toolbar P95 |
| Customer 360 data coverage | > 90% of customers have segment | `Customer.objects.filter(segment='').count()` |
| Agent AHT visibility | Dashboard shows live AHT | Confirmed in QA |
| Lost demand feed | > 80% of lost demands → `ItemDemandStat.suggest_order` | Reconciliation query |
| AI summary accuracy | Supervisor reviews sample: >75% correct | Monthly QA sample |
| Case resolution time | < 48h avg | `avg(resolved_at - created_at)` |
| CSAT score | > 4.2/5 avg | `avg(CustomerCase.csat_score)` |

---

## 10. Implementation Priority Queue

| ID | Task | Phase | Effort | Impact |
|---|---|---|---|---|
| **P1-A** | Extend `CallLog` + migration | 1 | 2h | Unblocks everything |
| **P1-B** | `CustomerCase` model + CRUD API | 1–2 | 4h | Case management |
| **P1-C** | `customer_360()` view | 2 | 3h | CTI enrichment |
| **P1-D** | Extend `callcenter/lookup` with segment + cases + delivery | 2 | 2h | Operator UX |
| **P1-E** | Customer 360 panel in `CallCenterPage.jsx` | 3 | 3h | Operator UX |
| **P2-A** | Extend `Customer` with segment fields + migration | 1 | 1h | Segmentation |
| **P2-B** | `segment_customers` command | 4 | 3h | Analytics |
| **P2-C** | Add calls + cases + delivery tabs to `CustomerDetailPage.jsx` | 3 | 4h | 360 view |
| **P2-D** | `CallLogAttachment` model + upload endpoints | 1–2 | 2h | Documentation |
| **P2-E** | Manager dashboard tab in `CallCenterPage.jsx` | 3 | 4h | Management |
| **P3-A** | AI call summarization (Gemini) | 4 | 4h | Intelligence |
| **P3-B** | `CallQualityScore` + scoring endpoint + leaderboard | 2–4 | 3h | QA |
| **P3-C** | `CasesPage.jsx` | 3 | 3h | Case management UI |
| **P3-D** | Complaint risk score algorithm | 4 | 2h | Prevention |
| **P4-A** | CSAT collection flow | 4 | 2h | Quality |
| **P4-B** | Add supervisor + quality_manager roles | 1 | 1h | RBAC |

---

## 11. Files to Create / Modify

### Backend

| File | Action | Description |
|---|---|---|
| `apps/callcenter/models.py` | **EXTEND** | Add `CustomerCase`, `CallLogAttachment`, `CallQualityScore`; extend `CallLog` |
| `apps/callcenter/serializers.py` | **EXTEND** | Add serializers for new models |
| `apps/callcenter/views.py` | **EXTEND** | Add case CRUD, attachment upload, AI summarize, quality score, enriched lookup |
| `apps/callcenter/urls.py` | **EXTEND** | Register new routers/paths |
| `apps/callcenter/migrations/0002_calllog_extensions.py` | **NEW** | Schema migration |
| `apps/customers/models.py` | **EXTEND** | Add segment, ltv, last_visit_date, complaint_risk_score |
| `apps/customers/views.py` | **EXTEND** | Add `customer_360()` action |
| `apps/customers/serializers.py` | **EXTEND** | Add 360 response serializer |
| `apps/customers/migrations/0003_customer_segment_fields.py` | **NEW** | Schema migration |
| `apps/customers/management/commands/segment_customers.py` | **NEW** | Daily segmentation |
| `apps/users/models.py` | **EXTEND** | Add `supervisor`, `quality_manager` to ROLE_CHOICES |
| `apps/notifications/models.py` | **EXTEND** | Add `case_created`, `case_escalated`, `csat_submitted` types |

### Frontend

| File | Action | Description |
|---|---|---|
| `frontend/src/pages/CallCenterPage.jsx` | **EXTEND** | 360 panel, attachment upload, case creation, manager tab |
| `frontend/src/pages/CustomerDetailPage.jsx` | **EXTEND** | Add calls/cases/delivery tabs; enrich hero card |
| `frontend/src/pages/CasesPage.jsx` | **NEW** | Case management page |
| `frontend/src/api/client.js` | **EXTEND** | Add case endpoints, 360 endpoint, attachment endpoints |
| `frontend/src/router.jsx` (or equivalent) | **EXTEND** | Register `/callcenter/cases` route |

---

## 12. Absolute Constraints

```
ABSOLUTE RULE: SELECT ONLY on Sybase. Never INSERT/UPDATE/DELETE on any Sybase connection.

✅ All new data is written ONLY to PostgreSQL.
✅ CallLog, CustomerCase, CallLogAttachment, CallQualityScore → PostgreSQL only.
✅ Customer segment/ltv fields → computed from PostgreSQL PurchaseHistory → stored in PostgreSQL.
✅ AI summarization → reads CallLog.notes from PostgreSQL → writes ai_summary to PostgreSQL.
✅ SOFTECH phcode / softech_pic used only for READ matching, never updated in Sybase.
```

---

*End of Audit Report. No implementation has been performed. This document governs all subsequent development.*
