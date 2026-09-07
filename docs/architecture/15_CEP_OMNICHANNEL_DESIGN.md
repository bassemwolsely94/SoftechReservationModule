# 15 — Omnichannel Communication & Engagement Platform (CEP)

**Status:** 🚧 PHASES 0–1 BUILT (2026-07-04)
- **Phase 0:** `apps/omni` unification core — ChannelAccount / Conversation / TimelineEvent
  + emit facade, WA + CallLog + Reservation signal ingestion, `backfill_omni`,
  `/api/omni/*`, Unified Inbox UI at `/omni/inbox`, migrations omni/0001 + whatsapp/0002,
  tests `test_omni.py` (16).
- **Phase 1 (multi-account WhatsApp):** provider layer `apps/omni/providers/`
  (MetaCloudProvider extracted from sender.py; d360/twilio/android_bridge stubs fail
  loudly), Fernet-encrypted per-account credentials (`OMNI_CREDENTIALS_KEY`, env
  fallback for legacy account), webhook routing by `phone_number_id` with
  auto-registration of unknown numbers + wamid duplicate detection + heartbeats,
  `WAConversation` uniqueness `wa_id` → `(account, wa_id)`, account-aware
  `WhatsAppSender(account=…)` (all 7 legacy call sites unchanged → default account),
  accounts health dashboard `/omni/accounts` (+ `/api/omni/accounts/{id}/health/`
  Graph-API probe), migrations omni/0002 + whatsapp/0003, tests
  `test_omni_accounts.py` (18). **Business decision recorded: official Cloud API
  numbers per branch (no BSP, no Android bridge).**
- **Phase 2 (voice deepening):** supervisor wallboard `/omni/wallboard` +
  `/api/omni/wallboard/` (live calls, per-queue today stats, agent states, WA load,
  backlog; admin/supervisor/quality_manager), ChanSpy listen/whisper via new sync AMI
  action client `apps/pbx/actions.py` + `POST /api/pbx/spy/` (rings supervisor's own
  ext; env `AMI_SPY_CONTEXT`/`AMI_CHANNEL_TECH`), recording playback with tokenized
  URLs `apps/pbx/recordings.py` + `GET /api/pbx/recordings/{id}/?t=` (signed, 1h —
  `<audio>` can't send JWT; env `PBX_RECORDINGS_DIR` local mount or
  `PBX_RECORDINGS_URL_BASE` redirect) surfaced as inline players in the unified
  timeline, and Gemini audio transcription `apps/omni/transcription.py`
  (call recordings → `CallLog.voice_transcript` → chains existing summarizer;
  WA voice notes → timeline `ai_insight`) via `POST /api/omni/events/{id}/transcribe/`.
  Also fixed pre-existing `request.user.staffprofile` bugs (correct related name is
  `staff_profile`) in whatsapp/omni/pbx views. Tests `test_omni_voice.py` (14).
- **Phase 3 (social channels):** new `apps/social` — one `SocialThread`/`SocialMessage`
  pair for all social networks (channel comes from the account). Meta Graph webhook
  `/api/social/webhook/meta/` serves BOTH Messenger (`object=page`) and Instagram
  (`object=instagram`), routed by page id → ChannelAccount (auto-registers unknown
  pages, dedups by mid, echo→outbound). Telegram webhook routed by
  `X-Telegram-Bot-Api-Secret-Token`. New providers `MetaGraphProvider` +
  `TelegramBotProvider`; TikTok webhook stub (501, pending API approval). Social
  messages ingest into the unified timeline (umbrella linked by thread, never phone —
  social identities have no phone). Omni `ReplyView` now routes to the most-recent
  writable thread across WA + social. Tests `test_social.py` (16).
- **Phase 4 (automation + AI assist):** `AutomationRule`/`AutomationRun` (omni/0003);
  engine `apps/omni/automation.py` runs from `add_event` after every TimelineEvent
  (trigger→conditions[channel/text_contains/customer_vip/priority/unassigned/sentiment]
  →actions[set_priority/set_status/add_tag/assign_role/notify_role/add_note/auto_reply]),
  feedback-loop guarded, immutable run log, never breaks ingestion. `seed_omni_automations`
  (4 starter rules). AI assist `apps/omni/ai.py` + `POST /api/omni/conversations/{id}/ai-assist/`
  → Gemini summary + intent + urgency + 3 suggested replies (assists, never sends).
  UI: `/omni/automations` rule builder + AI-assist bar in the inbox (click a suggestion
  to fill the reply box). Tests in `test_omni_automation.py`.
- **Phase 5 (cross-channel BI):** `GET /api/omni/analytics/?days=` — volume by
  channel + by day, avg first-response time, conversation→reservation conversion,
  status split, per-agent reply activity (admin/supervisor/quality_manager). UI
  `/omni/analytics` (pure SVG/CSS bars — no charting dep). Tests in
  `test_omni_automation.py::AnalyticsTests`.

**ALL 6 PHASES (0–5) BUILT.** Full suite 379 green. Remaining future work: TikTok
DM (API approval), revenue attribution needs POS↔conversation linkage (currently
conversion = reservation events), WebSocket live push for inbox/wallboard (currently
polling).
**Goal:** Make communication the "nervous system" of the ERP — one customer-grouped
timeline across WhatsApp, voice (Issabel), social channels, and future channels,
with routing, SLA, supervision, automation, and AI assistance.

**Cardinal rule of this design: EXTEND, DON'T REBUILD.**
A large fraction of the requested platform already exists in this codebase.
The CEP is a *unification layer* over existing channel apps, plus a small number
of genuinely new capabilities.

---

## 1. EXISTING ASSET INVENTORY (verified 2026-07-04)

### 1.1 `apps/whatsapp` — WhatsApp Business Cloud API (WORKING, single-number)

| Asset | Detail |
|-------|--------|
| `WATemplate` | Meta-approved templates (category, header/footer, variable map, meta_template_id) |
| `WAConversation` | Thread per customer phone; **24-h service window tracking**; auto customer match by phone tail; `assigned_to` agent; unread count; status open/pending/resolved/closed |
| `WAMessage` | All types (text/image/document/audio/video/location/template/OTP/sticker/reaction/order); wamid; sent/delivered/read receipts; error + retry fields; `sent_by` staff |
| `WAMediaFile` | Meta media id + local download + **SHA-256 dedup** |
| `WAWebhookLog` | **Immutable** raw webhook audit (stores `phone_number_id`) |
| `WAMessageQueue` | Outbound **priority retry queue** (urgent OTP → campaign) |
| `sender.py` | Cloud API sender (text/template/media) |
| `webhook.py` | Inbound webhook processor |
| UI | `WhatsAppInboxPage` at `/whatsapp/inbox` |

**Limitation:** single number — token + `WHATSAPP_PHONE_NUMBER_ID` come from env;
`WAConversation.wa_id` is globally `unique=True`, so multiple company numbers
cannot hold separate threads with the same customer. No provider abstraction.

### 1.2 `apps/pbx` — Issabel/Asterisk AMI integration (WORKING)

| Asset | Detail |
|-------|--------|
| `ami_bridge.py` + `run_ami_bridge` | Async AMI event consumer (Channels worker) |
| `AgentExtension` | Extension ↔ StaffProfile; types agent/branch/hq/**gateway** (GoIP/Grandstream/SIP trunk) with caller-number prefix/suffix normalization; live registration status |
| `PBXQueue` | Asterisk queue ↔ branch |
| `PBXEvent` | **Immutable** raw AMI audit (Newchannel/Hangup/Bridge/Queue events, DTMF, CDR) |
| `CallSession` | Per-call state machine (ringing/answered/queued/on_hold/transferred/completed/abandoned/no_answer/busy); wait+talk seconds; recording path; auto customer match; **creates `callcenter.CallLog` on hangup** |
| `consumers.py` | **Screen-pop already works**: `AgentCallConsumer` WebSocket pushes `incoming_call` with customer context (purchases, vouchers, open cases) to `pbx_agent_{ext}` and `pbx_all_agents` |
| Commands | `sync_pbx_extensions`, `classify_pbx_extensions`, `assign_pbx_extensions` |
| UI | `PbxLivePage` at `/pbx/live` |

### 1.3 `apps/callcenter` — Case management + call logging + AI (WORKING)

| Asset | Detail |
|-------|--------|
| `CallLog` | Direction (inbound/outbound/**whatsapp**), status, purpose taxonomy, duration, notes, `voice_transcript`, AI summary |
| `CallLogAttachment` | Prescription images / voice notes / documents per call |
| `AddressUpdate` | Address corrections captured on calls → applied to Customer |
| `CustomerCase` + `CaseEvent` | Unified case state machine open→working→escalated→resolved→closed with event chatter |
| `CallQualityScore` | QA scoring (supervisor or AI) |
| `CallItem` | Items discussed on a call |
| `ai.py` | **Gemini summarization**: summary / intent / sentiment / urgency(1-5) / next_action |
| UI | `CallCenterPage`, `CasesPage`, `CallCenterAnalyticsPage` |

### 1.4 Supporting assets

| App | Relevant capability |
|-----|--------------------|
| `apps/campaigns` | `WhatsAppCampaign` + `CampaignMessage` (broadcast) + `WhatsAppCampaignPage` |
| `apps/notifications` | `Notification` (dedup, WebSocket), `ChatterMessage` (generic chatter incl. voice notes), `PushSubscription` (VAPID), `Announcement` |
| `apps/customers` | Customer 360 (`CustomerDetailPage`): profile, purchase history, segmentation, churn score, health profile |
| `apps/loyalty`, `apps/insurance` | Points / insurance data for the 360 panel |
| `apps/portal` | Customer-facing WhatsApp magic-link portal (separate auth surface) |
| `apps/invoices` (OCR), `apps/shortage` (fuzzy match) | **Reusable Gemini OCR + rapidfuzz medicine-name matching** for prescription images |
| `apps/users` | RBAC matrix (1800 rows), `callcenter` module already in matrix |
| Infra | Django Channels + Redis (live), APScheduler (jobs), cursor pagination, Arabic-first UI |

### 1.5 Gap analysis — what does NOT exist

| # | Gap | Severity |
|---|-----|----------|
| G1 | Unified cross-channel conversation/timeline model (WA and calls live in separate silos) | CORE |
| G2 | Multi-account WhatsApp (`ChannelAccount` per number/branch) + per-account credentials | CORE |
| G3 | Messaging **provider abstraction** (Cloud API / 360dialog / Twilio / Android bridge) | CORE |
| G4 | Social channels: FB Messenger, Instagram, Telegram, TikTok | NEW |
| G5 | Conversation routing/queueing + conversation SLA engine (demand SLA exists; conversation SLA doesn't) | NEW |
| G6 | No-code automation engine | NEW |
| G7 | Supervisor center: unified live wallboard, takeover, whisper/monitor (Issabel spy) | PARTIAL (PbxLivePage is voice-only) |
| G8 | Unified inbox UI (WhatsAppInboxPage is WA-only) | NEW UI over existing data |
| G9 | Cross-channel BI (channel→revenue attribution, conversion funnels) | NEW |
| G10 | Voice-note/call transcription pipeline (AI summarize exists but expects transcript text) | PARTIAL |

---

## 2. ARCHITECTURE

### 2.1 Principle: envelope, not duplication

Channel-native models (`WAMessage`, `CallSession`, future `TGMessage`…) remain the
system of record for their channel — they carry channel-specific semantics
(24-h window, wamid receipts, AMI legs). The CEP adds **one new app `apps/omni`**
that provides a thin *envelope layer*:

```
                       ┌──────────────────────────────┐
                       │        apps/omni             │
                       │  Conversation (customer-     │
                       │  grouped, cross-channel)     │
                       │  TimelineEvent (GenericFK)   │
                       │  Routing / SLA / Automation  │
                       └──────┬───────────┬───────────┘
              ┌───────────────┤           ├───────────────┐
        apps/whatsapp     apps/pbx    apps/social     ERP modules
        WAConversation    CallSession  (new: FB/IG/    Reservation,
        WAMessage         CallLog      TG/TikTok)      Delivery, Case,
        (per-account)                                  Invoice, Demand…
```

- `omni.Conversation` = the **customer-grouped umbrella** ("one customer, many
  channels, one timeline"). A customer has at most one *open* omni-conversation
  per context (default: one per customer; branch context optional).
- `omni.TimelineEvent` = append-only envelope with a GenericFK to the native
  record (a `WAMessage`, a `CallSession`, a `Reservation`, an `Invoice`…).
  ERP events enter the timeline through the same mechanism → the requested
  "09:03 Reservation Created / 09:06 Delivery Assigned" timeline is just a query.
- Channel threads (`WAConversation` etc.) get a nullable FK
  `omni_conversation` — linking is additive, zero data migration risk.

### 2.2 New app decomposition

| App | Responsibility | Phase |
|-----|---------------|-------|
| `apps/omni` | Conversation umbrella, TimelineEvent, ChannelAccount registry, routing, SLA, assignment, supervisor actions | 0–1 |
| `apps/omni/providers/` | Provider layer: `BaseProvider` → `MetaCloudProvider` (extract from `whatsapp/sender.py`), `Dialog360Provider`, `TwilioProvider`, `AndroidBridgeProvider` (stubs until contracted) | 1 |
| `apps/social` | FB Messenger + Instagram (one Meta Graph webhook), Telegram Bot API, TikTok Business | 3 |
| `apps/omni/automation.py` | Rule engine (trigger → conditions → actions), JSON-defined, seeded rules | 4 |

Deliberately **not** new apps: voice (extend `apps/pbx`), cases/QA (extend
`apps/callcenter`), broadcasts (extend `apps/campaigns`), AI (extend
`callcenter/ai.py` into a shared `omni/ai.py` facade reusing invoice OCR).

### 2.3 Core schema (apps/omni)

```
ChannelAccount
  id, channel (whatsapp|voice|messenger|instagram|telegram|tiktok|sms|email)
  name, phone_or_handle, branch FK(null), department, provider (meta_cloud|d360|twilio|android_bridge|ami)
  credentials (encrypted JSON via SecretField), is_active
  status (connected|disconnected|degraded|pending_qr), last_heartbeat_at
  health (JSON: battery, device, api_quota, error_rate)
  working_hours (JSON), default_queue FK, supervisor FK
  UNIQUE(channel, phone_or_handle)

Conversation
  id, customer FK(null until identified), status (open|pending|snoozed|resolved|closed)
  priority, branch FK(null), assigned_to FK(null), queue FK(null)
  subject, tags (M2M omni.Tag), language, sentiment_cache
  first_inbound_at, last_activity_at, sla_first_response_due, sla_resolution_due
  sla_breached (bool), created_from_channel
  INDEX(status,last_activity_at), INDEX(customer,status), INDEX(assigned_to,status)

TimelineEvent  (append-only; save() guard like PBXEvent)
  id, conversation FK, event_type
      (message_in|message_out|call|call_missed|note|assignment|status_change|
       erp_reservation|erp_delivery|erp_invoice|erp_case|erp_demand|erp_payment|
       ai_insight|automation_action|sla_breach)
  channel, content_type FK + object_id (GenericFK to native record)
  summary (denormalized preview for list rendering), actor FK(staff, null)
  occurred_at (indexed), payload (JSON snapshot for fast render)

ConversationQueue
  id, name, branch FK(null), channels (JSON list), members M2M(StaffProfile)
  routing (round_robin|least_busy|manual), max_per_agent, sla_policy FK

SLAPolicy
  id, name, first_response_minutes, next_response_minutes, resolution_minutes,
  business_hours (JSON), escalate_to FK(role/staff)

AutomationRule            (Phase 4)
  id, name, trigger (event_type), conditions (JSON), actions (JSON),
  is_active, run_count, last_run_at, created_by
AutomationRun             (immutable log: rule FK, event FK, result, error)
```

`apps/whatsapp` changes (additive migration):
- `WAConversation`: + `account FK(ChannelAccount)`, + `omni_conversation FK`;
  `wa_id` uniqueness → `UNIQUE(account, wa_id)` (data migration backfills the
  single legacy account from env config).
- `sender.py`/`webhook.py`: resolve token/phone-id **per account** through the
  provider layer instead of env singletons (env remains the fallback for the
  default account → zero-downtime migration).

`apps/pbx` changes: `CallSession.complete()` additionally emits a
`TimelineEvent(call)` into the caller's omni-conversation (create if none open).

### 2.4 Event model

Every mutation emits an in-process signal → `omni.events.emit(event_type, obj, conversation)`
which (a) appends `TimelineEvent`, (b) pushes over Channels group
`omni_conversation_{id}` + `omni_inbox_{queue}`, (c) feeds the automation engine.
ERP modules integrate by one-line `emit()` calls in existing signal handlers
(`reservations/signals.py` already exists — pattern is established).
No message broker beyond Redis is introduced now; the emit facade is the seam
where Kafka/NATS could later slot in ("microservice-ready" without the cost).

### 2.5 API surface (v1, all under `/api/omni/`)

```
GET/POST   /api/omni/conversations/            (filters: status, channel, queue, assigned, sla_breached, q)
GET/PATCH  /api/omni/conversations/{id}/       (assign, status, tags, priority)
GET        /api/omni/conversations/{id}/timeline/   (cursor-paginated TimelineEvents)
POST       /api/omni/conversations/{id}/reply/      (routes to native channel send via provider)
POST       /api/omni/conversations/{id}/takeover/   (supervisor)
POST       /api/omni/conversations/{id}/link/       (link ERP record → timeline event)
GET/POST   /api/omni/accounts/                  (ChannelAccount CRUD + health)
GET        /api/omni/accounts/{id}/health/
GET/POST   /api/omni/queues/, /api/omni/sla-policies/, /api/omni/automations/
GET        /api/omni/wallboard/                 (supervisor aggregate: queues, agents, SLA, per-account health)
WS         /ws/omni/inbox/                      (live inbox updates)
WS         /ws/omni/conversation/{id}/          (live thread)
```

Existing endpoints (`/api/whatsapp/*`, `/api/pbx/*`, `/api/callcenter/*`) remain —
the omni API composes them, it does not replace them.

### 2.6 Security

- RBAC: new `omni` module in the permission matrix (view/create/edit/assign/
  approve/export + `takeover`, `monitor` as approve-level actions); reseed via
  `seed_permissions`.
- Branch isolation: `Conversation.branch` + existing `allowed_branches` filter
  pattern (same as reservations).
- `ChannelAccount.credentials` encrypted at rest (Fernet, key in env) — never
  serialized in API responses.
- All raw payload logs (`WAWebhookLog`, `PBXEvent`, `TimelineEvent`,
  `AutomationRun`) are immutable → complete audit trail by construction.
- Masking: phone masking for roles without `customers.view` full grant.

---

## 3. PHASED ROADMAP

| Phase | Scope | Depends on |
|-------|-------|-----------|
| **0 — Unification core** | `apps/omni`: ChannelAccount + Conversation + TimelineEvent + emit facade; link WAConversation & CallSession into timelines; backfill legacy WA account; Unified Inbox UI v1 (WA + calls, one list, split-pane, Customer 360 side panel reusing CustomerDetailPage components) | nothing |
| **1 — WhatsApp Enterprise** | Multi-account: per-account credentials via provider layer (extract MetaCloudProvider); webhook routing by `phone_number_id`; account health dashboard (connected/QR/heartbeat); queues + routing + conversation SLA; template manager UI | 0 |
| **2 — Voice deepening** | Wallboard endpoint + supervisor UI (queue stats from AMI), whisper/monitor via Issabel ChanSpy actions, recording playback in timeline, voice-note + call transcription (Gemini) feeding existing `ai.py` summarizer | 0 |
| **3 — Social channels** | `apps/social`: Meta Graph webhook (Messenger+IG share one), Telegram Bot API, TikTok; each lands as a ChannelAccount + native message model + TimelineEvent | 1 |
| **4 — Automation + AI panel** | AutomationRule engine + seeded rules (VIP escalate, prescription→OCR→availability→suggest reservation, SLA breach→notify, angry→escalate); AI assist panel (reply suggestions, alternatives via catalog + activeingredients, cross-sell) | 1 |
| **5 — BI & attribution** | Channel→reservation/sale/delivery conversion funnels, revenue attribution, exec dashboards; extends `apps/analytics` | 0–4 |

Phase 0 is deliberately small (~1 new app, 2 additive migrations, 1 new page)
and immediately delivers the "one customer, one timeline" experience over the
two channels that already work.

### Known constraints & guards

- **WhatsApp 24-h window** logic stays in `apps/whatsapp` (already correct).
- **Android-bridge provider** (existing branch phones): unofficial WA-web bridges
  violate WhatsApp ToS → ship as a stub; migration path is Cloud API numbers
  per branch or a BSP (360dialog). Decision needed before Phase 1 rollout.
- **`name_scientific` is dirty** — alternatives suggestions must use SOFTECH
  `activeingredients`/`itemsai`, never raw `name_scientific` (see doc 13 guard).
- **No SOFTECH writes** — CEP reads mirrors only; any order creation goes
  through the existing audited writeback channels (doc 14).
- TikTok DM API access is restricted (business approval) — keep last in Phase 3.

---

## 4. UI PLAN (Phase 0–1)

| Screen | Route | Notes |
|--------|-------|-------|
| Unified Inbox | `/omni/inbox` | 3-pane: filterable conversation list / thread timeline (messages + ERP events interleaved) / Customer 360 + ERP context tabs. Replaces `WhatsAppInboxPage` eventually; that page stays until parity. |
| Channel Accounts | `/omni/accounts` | Account grid with live health chips (connected/QR/heartbeat/load) |
| Supervisor Wallboard | `/omni/wallboard` | Live queues, agents, SLA breaches, per-account volume; extends PbxLivePage patterns |
| Automation Studio | `/omni/automations` | Phase 4 — rule list + JSON-schema-driven condition/action builder |

Dark/light, RTL Arabic-first, keyboard shortcuts (j/k navigate, r reply, a assign)
— consistent with existing Tailwind component library (`Input`, `Btn`, etc.).

---

## 5. TESTING & OPS

- Tests: `apps/tests/test_omni.py` — envelope creation from WA webhook + AMI
  hangup, routing, SLA breach job, provider fallback, permission gates.
- Workers: reuse APScheduler (SLA sweep hourly like `check_demand_sla`;
  account heartbeat check every 5 min); WAMessageQueue drain stays as-is.
- HA: AMI bridge and webhook are already restart-safe (immutable logs +
  idempotent processing by wamid/unique_id). Provider layer adds retry with
  the existing `WAMessageQueue` semantics per account.
