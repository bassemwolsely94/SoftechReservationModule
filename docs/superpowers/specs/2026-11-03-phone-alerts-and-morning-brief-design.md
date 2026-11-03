# Phone alerts («تنبيه على الموبايل») + branch morning brief — design

Status: DRAFT for owner approval (2026-11-03). Project 1 of the "before go-live" set
(order: 1 phone alerts + brief → 2 scanning/counting → 3 usage labels → 4 customer follow-up → 5 drug assistant).

## 1. Why

A branch asked the purchasing specialist (Gerges Shawky) in a WhatsApp group to order an item from a
distributor. He was not notified, did not read it during work hours, and the order was never placed.
Nothing owned the request, nothing reminded him, nothing escalated. Several people who must act on
requests (purchasing, the HQ transfer dispatcher Youssef William, branch staff on shift) are not
watching the system all day, and some have no system login at all.

Success = an urgent request reaches the right phone within a minute, keeps reminding until someone
taps «استلمت», escalates if nobody does, and the requester sees the status and any remark — with a full
log of who was told what, when.

## 2. Goals

1. **Two alert levels per event**: *normal* (today's in-app bell + Web Push) and *phone alert*
   (WhatsApp template with a tap button → reminders → escalation; SMS later as fallback).
2. **Admin decides per event type** whether a phone alert is `never` / `optional` / `always`.
   For `optional`, the **requester or task assigner** ticks «نبّه على الموبايل» on the existing form.
3. **Named owners per kind of work**, configurable (not hard-coded): e.g. distributor orders → Gerges;
   HQ→branch transfers to dispatch → Youssef William.
4. **Branch audience** for branch-directed urgent alerts = **everyone on shift at that branch + the
   branch mobile** (every branch has one).
5. **Acknowledge + optional remark**: one tap «استلمت»; any text he types after it is attached to the
   record and visible to the branch.
6. **Reminder + escalation**: remind after 15 min, escalate after 30 min, **around the clock** — night
   requests keep reminding (owner decision 2026-11-03). Both configurable per event type.
7. **Morning brief** at 09:00, one per branch, to **the branch manager's phone and the branch mobile**:
   yesterday's performance, MTD vs target, top downfalls (from التقارير السردية), and reservations +
   transfer requests needing follow-up.
8. Everything auditable: every send, delivery, read, tap, reminder, escalation, remark, policy change.

## 3. Non-goals / anti-goals

- **No new workflow, no new request form.** Reuse the existing shortage, transfer, task and reservation
  screens and their state machines. This project only adds "who owns it" + "reach their phone".
- No WhatsApp-group scraping.
- No fingerprint-machine integration now (later; it will replace the "on shift" approximation, §6.3).
- No customer-facing messaging (projects 4/8). No SOFTECH reads or writes beyond what the brief's
  existing engines already mirror. No pricing/discount/checkout impact.
- Anti-goal: alert fatigue. If everything is "urgent", nothing is. Default policy for every type is
  `never`; the owner switches on only the few that matter.
- Anti-goal: AI-written numbers. The brief's figures come only from the existing deterministic engines.

## 4. Constraints

- WhatsApp Cloud API: a message the business starts must be a **Meta-approved template**; template
  variables cannot contain new-lines; free text is allowed only within 24 h after the recipient last
  wrote/tapped. Per-message fee applies (same as refill reminders).
- Outbound sending must be **default OFF** behind a kill-switch (security suite rule: default-ON write
  switches fail CI), with a dry-run mode that logs what would be sent.
- Server-side permission checks for every new endpoint (RoleModuleAccess matrix). In-app help for every
  new screen/tab/status (`apps/help/content/…`, AR + EN).
- iPhone Web Push only works when the site is added to the home screen; WhatsApp is the primary channel
  precisely because it needs no login and no install.

## 5. What exists and is reused (verified 2026-11-03)

| Need | Existing piece |
|---|---|
| In-app + Web Push delivery, gates, dedup | `Notification.send_to_user/send_to_branch/send_to_roles` (`apps/notifications/models.py:373-500`), `send_web_push` (:619), `NotificationLog` (:534), 46 types in `NOTIFICATION_TYPES` (:29) |
| Per-type routing setting | SystemSetting `notification_routing` `{type: {mode, roles}}` read by `_routing_allows` (:337) (P-55) |
| WhatsApp template + quick-reply buttons | `WhatsAppSender.send_template(wa_id, name, variables, quick_reply_payloads)` (`apps/whatsapp/sender.py:80`); account via `omni.ChannelAccount` |
| Inbound button taps | `apps/whatsapp/webhook.py:194-201` — currently hard-wired to refill reminders; pattern of `handle_button_reply` (lock row, check phone, first answer wins) in `apps/followups/refill_reminders.py:285` |
| SMS | `core/sms.py` (off until an SMS company is chosen) |
| Staff phone | `StaffProfile.phone` (`apps/users/models.py:150`) |
| Branch working hours | `BranchSettings.working_hours` + `is_24h` (`apps/branches/models.py:161`), helpers `apps/branches/hours.py` |
| "Recently active at branch" | `access.Device.branch/last_seen` (+ `DeviceUser`) (`apps/access/models.py`) |
| Owners of requests | `OperationalTask.assigned_to` + `priority`; `Reservation.assigned_to` + `priority`; transfers have no owner/priority; shortage has neither and sends no notification today |
| Brief data | `InsightEngine.run` + `render_for_branch` (`apps/insights/engine.py:51,161`); recipients `InsightRecipient` (wa_number, branch, period_types) already used by the 07:30 `MORNING_CHAIN` WhatsApp send; KPI board MTD logic inline in `KpiBoardView.get` (`apps/forecasting/views.py:209`); `KpiResolver.resolve` (`apps/forecasting/kpi.py:181`) |
| Scheduler | `apps/sync/tasks.py start_scheduler()`; every-minute `_process_reminders_and_snoozes` job |

Found during research (fix in this project): `apps/batches/expiry_audit.py:1198` calls
`sender.is_configured()` but it is a property → TypeError swallowed → the weekly expiry worklist never
reaches managers' WhatsApp. Also both that send and the insights send use free text, which Meta drops
outside the 24 h window — they move onto the template mechanism below.

## 6. Design

### 6.1 Data (all in `apps/notifications`, new migrations; no SOFTECH schema)

- **`PhoneAlertPolicy`** — one row per notification type that may phone-alert:
  `notification_type` (unique), `mode` never|optional|always, `remind_after_min` (15),
  `escalate_after_min` (30), `max_reminders` (2), `escalate_to` (M2M StaffProfile; empty = the
  owner kind's escalation list, §6.2), `updated_by/at`. Absent row = `never`.
- **`WorkOwner`** — `kind` (choices, start with `reservation_sourcing`, `hq_transfer_dispatch`; extendable),
  `staff` FK, optional `branch` (owner for one branch only; null = all), `is_escalation` (bool: this
  person is the escalation target for the kind), `active`. Admin-edited, audited.
- **`PhoneAlert`** — one per (event × recipient phone): `notification` FK (nullable for brief),
  `recipient_staff` FK nullable, `phone`, `kind` alert|brief, `source` generic FK (the task / transfer /
  shortage / reservation), `status` queued → sent → delivered → read → acknowledged | escalated |
  expired | failed, `ack_at`, `ack_by_phone`, `remark`, `reminders_sent`, `escalated_at`,
  `token` (random, in the button payload), timestamps.
- **`PhoneAlertAttempt`** — `alert` FK, `channel` whatsapp|webpush|sms, `provider_message_id`,
  `result`, `error`, `created_at`. Delivery/read webhooks update the attempt and the alert.
- **`BranchSettings.alert_mobile`** — the branch's WhatsApp mobile (separate from `Branch.phone`, which
  may be a landline).
- **`StaffProfile.phone_alerts_enabled`** (default True) — personal opt-out for non-mandatory alerts.
- A `phone_alert` boolean on `OperationalTask`, `TransferRequest`, `Reservation`
  (the requester's «نبّه على الموبايل» choice, persisted so later status updates follow it).

### 6.2 Who gets it

- **Owner-directed events** — recipients = active `WorkOwner` rows of that kind (branch-specific
  first, else global). Owner decision 2026-11-03, no new request types:
  - **Distributor request = a normal reservation.** A reservation created in `pending` (item not
    available) also goes to the `reservation_sourcing` owners (Gerges) in addition to today's
    recipients. Open while `pending`; closes when it leaves `pending` (available / contacted / … /
    cancelled / expired).
  - **HQ transfer = a normal transfer request** whose `supplying_branch` is HQ. On submit (`pending`)
    it goes to the `hq_transfer_dispatch` owners (Youssef William). Open until `sent_to_erp`,
    `completed`, `rejected` or `cancelled`.
  - Shortage lists are not owner-directed in v1.
- **Person-directed events** (task assigned, reservation assigned): the assignee(s).
- **Branch-directed events** (status updates on that branch's tasks / urgent reservations / urgent
  transfers): **on-shift staff + branch mobile**, deduplicated by phone.
- **People without a login** (my call): they are `StaffProfile` rows with a phone and no login rights
  ("alerts only"), so ownership, escalation and the audit trail use one identity everywhere.

### 6.3 "On shift" (until fingerprint integration)

Staff whose `access.Device` at that branch had `last_seen` within the last 4 h (via `DeviceUser`), or
who are scheduled in `ShiftAssignment` for now, inside branch working hours. The branch mobile always
receives branch-directed alerts, so nothing is lost if this guess misses someone. The fingerprint feed
later replaces this one function.

### 6.4 Flow

1. A workflow calls the existing `Notification.send_to_*` (unchanged gates). After the notification is
   created, `phone_alerts.maybe_dispatch(notification, source)` checks the policy:
   `always`, or `optional` and `source.phone_alert` is true → create `PhoneAlert` rows per recipient.
2. Sender (async, outside the request) sends, from the **staff-alerts WhatsApp account** (§6.8),
   WhatsApp template **`staff_alert`** (utility category):
   variables = short title, branch, item/subject, reference number; one quick-reply button «استلمت»
   with payload `alert:<token>:ack`. Web Push still fires as today. SMS is used only if WhatsApp fails
   and SMS is configured.
3. Webhook gets a **small payload-prefix dispatcher** (`refill:` → existing handler, `alert:` → new,
   `brief:` → §6.6). Tap → lock row, verify the tapping phone matches, first tap wins → `acknowledged`,
   reply «تم التسجيل ✓ اكتب أي ملاحظة وسنرسلها للفرع». The requester sees «استلم» on the record.
4. **Remark**: a free-text WhatsApp message from that phone that quotes the alert (reply context) or
   arrives within 30 min of the tap while exactly one alert from that phone is acknowledged-and-open →
   stored as `remark` and posted to the record's existing chatter (so the branch sees it, notified as
   normal). Otherwise it stays in the inbox untouched.
5. Every-minute job: unacknowledged after `remind_after_min` minutes → resend (≤ `max_reminders`);
   after `escalate_after_min` → status `escalated`, new alert to `escalate_to` (or the kind's
   `is_escalation` owners) saying who did not acknowledge what. The clock runs 24 h (owner decision).
6. When the underlying record moves on (task done, transfer sent/completed, reservation out of pending), open alerts
   for it close as `expired` — no reminders for finished work.

### 6.5 Screens

- **Admin «تنبيهات الموبايل»** (settings area, admin/supervisor): tab *السياسة* (event types × mode /
  minutes / escalation), tab *المسؤولون* (WorkOwner), tab *أرقام الفروع* (alert mobile per branch +
  test-send), tab *السجل* (all PhoneAlerts, filter by status/person/branch, attempts timeline).
- **Existing create/assign forms** (task, transfer, reservation; desktop + mobile): a
  «نبّه على الموبايل» toggle shown only when that type's policy is `optional`; shown as locked-on for
  `always`. No new modal.
- **Existing record detail pages**: a small status chip «أُرسل / وصل / قُرئ / استلم / صُعّد» + remark.
- **Staff profile**: phone + «alerts only» + personal opt-out.

### 6.6 Morning brief

- Runs 09:00 (after the 07:30 `MORNING_CHAIN`), one per branch, gated by its own kill-switch.
- Recipients: the branch manager's phone and the branch alert mobile. Recipient list reuses
  `InsightRecipient` (it already has wa_number + branch); a recipient row marked `morning_brief`.
- Content (deterministic, Arabic):
  1. **Yesterday**: net sales, invoices, average basket, Δ vs same weekday last week (`KpiResolver`).
  2. **MTD**: actual vs target, % achieved, daily pace needed (the KPI-board calculation, extracted
     from `KpiBoardView.get` into a reusable function with tests — the view then calls it).
  3. **Top 3 downfalls**: from the daily `InsightEngine` run for that branch (existing rules).
  4. **Follow-up today**: overdue/stuck reservations and transfer requests (number + item), capped at
     5 each with a "+N more".
- Because a business-started WhatsApp message must be a template and template variables cannot hold
  multi-line text: send template **`morning_brief`** whose variables carry the headline (branch,
  yesterday sales, MTD %), with a button «التفاصيل» (`brief:<token>`). The tap opens the 24 h window;
  the full brief is then sent as text. Logged as `PhoneAlert(kind=brief)`.
- The existing insights WhatsApp send and the expiry worklist move onto the same mechanism (and the
  `is_configured()` bug is fixed).

### 6.7 Switches, audit, safety

- `PHONE_ALERTS_SEND_ENABLED` (env, default False) and `MORNING_BRIEF_SEND_ENABLED` (env, default
  False); with sending off, everything runs and logs as `dry_run` — the log screen shows what would
  have gone out.
- Policy, owner and branch-mobile changes write `AuditLog` (who/what/when/before-after).
- Phone numbers masked in the log for non-admins. Brief content limited to branch numbers the
  recipient's branch already sees.

### 6.8 Sending number (owner decision 2026-11-03)

Staff alerts and the brief go from a **separate WhatsApp number**, not the customer number. The number
is not chosen yet, so it must be changeable without code: an `omni.ChannelAccount` (purpose
`staff_alerts`) picked in the admin «تنبيهات الموبايل» → *أرقام الفروع* tab (SystemSetting
`phone_alerts_channel_account`). Until one is set, everything runs in dry-run. Inbound messages on
that account are tagged as staff traffic and never appear in the customer-service inbox or its unread
counts; the webhook routes them to the alert dispatcher only.

### 6.9 Initial event table (v1)

| Event (existing notification) | Recipients | Source record | Toggle on | Default policy |
|---|---|---|---|---|
| Reservation created `pending` | `reservation_sourcing` owners | Reservation | reservation form | optional |
| Transfer submitted, HQ supplies | `hq_transfer_dispatch` owners | TransferRequest | transfer form | optional |
| Transfer status change | requesting branch (on-shift + branch mobile) | TransferRequest | follows the request's toggle | optional |
| Reservation status change (urgent) | reservation's branch | Reservation | follows toggle | optional |
| Task assigned | assignees | OperationalTask | task form | optional |
| Task status change | task creator's branch | OperationalTask | follows toggle | optional |
| Escalation | escalation targets | PhoneAlert | — | always |

All other notification types are seeded `never`; the owner can enable more later from the policy tab.

## 7. Testing

Unit: policy resolution, recipient resolution (owner/person/branch, dedup by phone), on-shift
function, 24 h reminder clock, reminder/escalation job, expiry on record close,
payload dispatcher (refill untouched), tap verification (wrong phone, double tap), remark matching,
brief composer per section with fixtures, MTD extraction gives identical numbers to the current view.
Integration: send path with a fake provider, switches default OFF, RBAC sweep entries, help coverage.

## 8. Left to the builder

Template wording (to submit to Meta), exact dispatcher registry shape, log-screen layout details,
batching of sends, retry/backoff values, how many event types to seed in the policy table (seed all
46 as `never`).

## 9. Calls I made (owner to check)

- Default reminder 15 min / escalation 30 min / max 2 reminders; brief at 09:00.
- The 09:00 brief replaces the 07:30 insights WhatsApp to branch managers (other insights recipients
  unchanged).
- Alerts-only people: `auth.User` with `is_active=False` + unusable password, `StaffProfile.alerts_only`
  = True, excluded from user lists, device registry and RBAC role counts.
- The expiry worklist WhatsApp sends only when both its own flag and the phone-alerts master switch are on.
- People without a login = "alerts only" StaffProfiles.
- "On shift" = device activity at the branch in the last 4 h or shift schedule; branch mobile always.
- New `alert_mobile` field rather than reusing `Branch.phone`.
- Every event type starts as `never`.
