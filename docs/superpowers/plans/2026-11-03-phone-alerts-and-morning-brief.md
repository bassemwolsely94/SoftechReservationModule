# Phone Alerts + Branch Morning Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Urgent reservation/transfer/task events reach the right phones over WhatsApp (tap «استلمت», optional remark, reminders, escalation), and every branch gets a 09:00 WhatsApp morning brief.

**Architecture:** A `phone_alerts` package inside `apps/notifications` sits *after* the existing `Notification.send_to_*` calls: workflows call one hook `phone_alerts.dispatch.fire(event, source, actor)`; it resolves the policy and the phones, writes `PhoneAlert` rows, and a sender delivers them from a configurable staff WhatsApp `ChannelAccount`. Inbound taps come back through a payload-prefix registry in the WhatsApp webhook. An every-minute job reminds/escalates/expires. The brief reuses `InsightEngine`, `KpiResolver` and an extracted KPI-board MTD function.

**Tech Stack:** Django 4.2 + DRF, APScheduler (`apps/sync/tasks.py`), WhatsApp Cloud API via `apps/whatsapp/sender.py`, React 18 + TanStack Query + Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-03-phone-alerts-and-morning-brief-design.md`

## Global Constraints

- Sending is OFF by default: env `PHONE_ALERTS_SEND_ENABLED=False`, `MORNING_BRIEF_SEND_ENABLED=False` (read with `decouple config` in `config/settings.py`). Off ⇒ every step still runs and records `PhoneAlertAttempt(result='dry_run')`.
- No staff-alerts `ChannelAccount` configured (SystemSetting `phone_alerts_channel_account` empty) ⇒ dry-run too. The number is changeable from the admin screen; never hard-code it.
- Templates: `staff_alert` (variables: title, branch, subject, reference; one quick-reply button «استلمت», payload `alert:<token>:ack`) and `morning_brief` (variables: branch, yesterday net sales, MTD %; button «التفاصيل», payload `brief:<token>`). No new-lines in template variables.
- Defaults: remind after 15 min, escalate after 30 min, max 2 reminders, clock runs 24 h. Brief at 09:00 Africa/Cairo.
- No SOFTECH reads/writes added. No pricing/discount/checkout change.
- Every new endpoint: server-side permission (admin/supervisor for settings; record permissions unchanged for toggles); every policy/owner/branch-mobile/channel change writes `AuditLog` with before/after.
- Every new screen/tab/status: help entry in `apps/help/content/general.py` (AR + EN, `updated` = date of change); tabbed page calls `useHelpTab(tab)` (see `docs/architecture/28_IN_APP_HELP.md`).
- Arabic UI copy, RTL. No new modal for common actions.
- Tests: `TEST_DB_NAME=test_phone_alerts python manage.py test apps.tests.test_phone_alerts -v 2` (unique TEST_DB_NAME per run). Frontend: `cd frontend && npm run build`.
- Phone numbers stored as international digits via `core.sms.sms_number()`; masked (`…1234`) in API output for non-admins.

## Review Focus

1. **Same phone, many roles** — a person who is both owner and on-shift (or a branch mobile equal to a staff phone) gets ONE alert per event, not two. → Task 2 `test_dedup_by_phone_across_groups`.
2. **Tap from the wrong phone or a stale/forwarded button** — must not acknowledge; double tap is idempotent. → Task 4 `test_tap_from_other_phone_ignored`, `test_second_tap_noop`.
3. **Record finishes before anyone taps** — reminders stop immediately (no "please act" on a fulfilled reservation). → Task 5 `test_closed_source_expires_alert`.
4. **Free text from a staff phone with two open acknowledged alerts** — never guess; leave it unattached. → Task 4 `test_remark_ambiguous_not_attached`.
5. **Requester ticks «نبّه على الموبايل» on an event whose policy is `never`** — server ignores it (no alert); `always` sends even if unticked. → Task 6 `test_toggle_ignored_when_policy_never`, `test_always_sends_without_toggle`.

## File Structure

```
apps/notifications/phone_alerts/__init__.py
apps/notifications/phone_alerts/models.py      # imported by apps/notifications/models.py
apps/notifications/phone_alerts/events.py      # EVENT registry: key → recipients kind, open/closed test
apps/notifications/phone_alerts/recipients.py  # who + which phone
apps/notifications/phone_alerts/dispatch.py    # fire(): policy → PhoneAlert rows
apps/notifications/phone_alerts/sender.py      # deliver one alert over whatsapp/sms, attempts
apps/notifications/phone_alerts/inbound.py     # alert:/brief: payloads, remarks
apps/notifications/phone_alerts/jobs.py        # remind / escalate / expire tick
apps/notifications/phone_alerts/views.py + serializers.py + urls.py  # admin API under /api/notifications/phone-alerts/
apps/whatsapp/button_registry.py               # prefix → handler
apps/insights/brief.py                         # morning brief composer + sender
apps/forecasting/kpi_board.py                  # extracted MTD calculation
frontend/src/pages/PhoneAlertsPage.jsx
frontend/src/components/PhoneAlertToggle.jsx
frontend/src/components/PhoneAlertStatusChip.jsx
apps/tests/test_phone_alerts.py, test_morning_brief.py, test_kpi_board_extract.py
```

Deviation from spec noted for the owner: the policy is keyed by **event** (the 7 events of spec §6.9), not by all 46 notification types — each event needs its own recipient and close rule in code, so "enable another type" is a small code change, not a setting.

---

### Task 1: Data model, settings, seed

**Files:**
- Create: `apps/notifications/phone_alerts/{__init__,models,events}.py`
- Modify: `apps/notifications/models.py` (import phone_alerts models at bottom), `apps/branches/models.py` (BranchSettings), `apps/users/models.py` (StaffProfile), `apps/reservations/models.py`, `apps/transfers/models.py`, `apps/tasks/models.py`, `apps/insights/models.py` (InsightRecipient), `config/settings.py`
- Migrations: notifications 0038 (+ data migration seeding policies), branches 0011, users 0045, reservations 0022, transfers 0011, tasks 0003, insights 0004
- Test: `apps/tests/test_phone_alerts.py`

**Interfaces — Produces:**
- `events.EVENTS: dict[str, Event]`, keys exactly: `reservation_sourcing`, `transfer_hq_submitted`, `transfer_status`, `reservation_status_urgent`, `task_assigned`, `task_status`, `escalation`. `Event(key, label_ar, source_model: str, recipients: 'owner'|'person'|'branch'|'escalation', owner_kind: str|None, is_open: Callable[[obj], bool])`.
  - is_open: reservation_sourcing → `status == 'pending'`; transfer_* → status not in `{'sent_to_erp','completed','rejected','cancelled'}`; reservation_status_urgent → `obj.is_active` (existing property, line ~184); task_* → task not done/cancelled (use OperationalTask's terminal statuses).
- `PhoneAlertPolicy(event unique choices=EVENTS, mode never|optional|always, remind_after_min=15, escalate_after_min=30, max_reminders=2, escalate_to M2M StaffProfile, updated_by, updated_at)`; classmethod `for_event(key) -> PhoneAlertPolicy|None`.
- `WorkOwner(kind choices reservation_sourcing|hq_transfer_dispatch, staff FK, branch FK null, is_escalation bool, active bool)`.
- `PhoneAlert(event, kind alert|brief, notification FK null, source_ct/source_id GenericFK, recipient_staff FK null, phone, status queued|sent|delivered|read|acknowledged|escalated|expired|failed, token unique (secrets.token_urlsafe(16)), wa_message_id, ack_at, remark, reminders_sent int, last_sent_at, escalated_at, escalation_of FK self null, created_at)`; index (status, last_sent_at), (source_ct, source_id).
- `PhoneAlertAttempt(alert FK, channel whatsapp|sms, result sent|dry_run|failed|delivered|read, provider_message_id, error, created_at)`.
- `BranchSettings.alert_mobile` CharField(20, blank); `StaffProfile.alerts_only` bool False, `StaffProfile.phone_alerts_enabled` bool True; `phone_alert` BooleanField(default=False) on Reservation, TransferRequest, OperationalTask; `InsightRecipient.morning_brief` bool False.
- settings: `PHONE_ALERTS_SEND_ENABLED`, `MORNING_BRIEF_SEND_ENABLED` (both `config(..., default=False, cast=bool)`).

- [ ] **Step 1: Write failing tests** `test_policy_seeded_for_v1_events` (7 rows; `escalation` = always, others = optional, remind 15 / escalate 30 / max 2), `test_policy_absent_means_never` (`PhoneAlertPolicy.for_event('x') is None`), `test_switches_default_off` (`settings.PHONE_ALERTS_SEND_ENABLED is False` with no env).
- [ ] **Step 2: Run, expect FAIL** (import errors).
- [ ] **Step 3: Implement models/fields/settings + migrations** (`makemigrations` per app; hand-write the seed data migration).
- [ ] **Step 4: Run, expect PASS**; also `python manage.py makemigrations --check` prints "No changes detected".
- [ ] **Step 5: Commit** `feat(phone-alerts): models, settings switches, v1 policy seed`

### Task 2: Recipient resolution + "on shift"

**Files:** Create `apps/notifications/phone_alerts/recipients.py`; Test `apps/tests/test_phone_alerts.py`

**Interfaces — Produces:**
- `Recipient = NamedTuple(staff: StaffProfile|None, phone: str)`
- `on_shift_staff(branch, now=None) -> list[StaffProfile]`: active staff of the branch with `access.Device(branch=branch, last_seen >= now-4h)` joined through `DeviceUser.user`, union `ShiftAssignment` covering `now`; excludes `phone_alerts_enabled=False` and blank phones.
- `resolve(event: Event, source, actor=None) -> list[Recipient]`:
  - owner → active `WorkOwner(kind=event.owner_kind)` with `branch = source's branch` if any exist, else `branch=None`; non-escalation rows only.
  - person → reservation `assigned_to`; task `assigned_to` + `TaskAssignment` assignees.
  - branch → `on_shift_staff(branch)` + `Recipient(None, branch.settings.alert_mobile)` when set. Branch = reservation.branch; transfer.requesting_branch; task creator's branch.
  - escalation → `policy.escalate_to` else `WorkOwner(kind, is_escalation=True)`.
  - Always: drop the actor, normalise with `sms_number`, dedup by phone (first staff wins).

- [ ] **Step 1: Failing tests**: `test_owner_branch_specific_beats_global`, `test_branch_group_includes_branch_mobile`, `test_on_shift_uses_device_last_seen_4h` (5h-old device excluded), `test_dedup_by_phone_across_groups` (owner phone == branch mobile ⇒ 1 recipient), `test_actor_not_alerted`, `test_opted_out_staff_skipped`.
- [ ] **Step 2: Run, FAIL.**  - [ ] **Step 3: Implement.**  - [ ] **Step 4: Run, PASS.**
- [ ] **Step 5: Commit** `feat(phone-alerts): recipient resolution and on-shift`

### Task 3: Dispatch + sender

**Files:** Create `phone_alerts/dispatch.py`, `phone_alerts/sender.py`; Modify `apps/whatsapp/sender.py` only if `send_template` lacks a way to pass an explicit `ChannelAccount` (it takes `account=` in `WhatsAppSender(account)`; reuse). Test: same file.

**Interfaces:**
- Consumes: Task 1 models/EVENTS, Task 2 `resolve`.
- Produces: `fire(event_key: str, source, *, actor=None, notification=None, requested: bool|None=None) -> list[PhoneAlert]` — `requested=None` means "use `source.phone_alert`". Sends when policy `always`, or `optional` and requested. Skips recipients that already have an open alert for the same (event, source, phone). Calls `transaction.on_commit(lambda: deliver_many(ids))`.
- `deliver(alert: PhoneAlert, *, reminder=False) -> PhoneAlertAttempt` — staff account = `ChannelAccount` id from SystemSetting `phone_alerts_channel_account`; if switch off or account unset → attempt `dry_run`, alert status `sent` (so the clock still runs and the log shows it). WhatsApp error → try `core.sms.SmsSender` if configured, else status `failed`. Reminder text prefix «تذكير:».
- `staff_account() -> ChannelAccount|None`.

- [ ] **Step 1: Failing tests** (fake provider via `mock.patch('apps.whatsapp.sender.WhatsAppSender.send_template')`): `test_optional_needs_request`, `test_always_sends_without_request`, `test_dry_run_when_switch_off` (attempt.result == 'dry_run', send_template not called), `test_dry_run_when_no_account`, `test_sends_payload_with_token` (`quick_reply_payloads == [f'alert:{a.token}:ack']`), `test_no_duplicate_open_alert`, `test_whatsapp_failure_falls_back_to_sms_when_configured`.
- [ ] **Step 2–4: FAIL → implement → PASS.**
- [ ] **Step 5: Commit** `feat(phone-alerts): dispatch and delivery with dry-run`

### Task 4: Inbound taps, remarks, staff inbox separation

**Files:** Create `apps/whatsapp/button_registry.py`, `phone_alerts/inbound.py`; Modify `apps/whatsapp/webhook.py:150-201`, `apps/followups/refill_reminders.py` (register only). Test: same file + existing refill tests must still pass.

**Interfaces:**
- `button_registry.register(prefix: str, handler)`; `button_registry.dispatch(*, wa_id, payload, context_wamid, account) -> str` (returns `'not_ours'` when no prefix matches). Refill registers `refill:`; phone alerts register `alert:` and `brief:` in `NotificationsConfig.ready()`.
- `inbound.handle_alert_tap(...) -> str`: lock `PhoneAlert` by token, require `sms_number(wa_id) == alert.phone`, first tap wins → `acknowledged`, `ack_at`; post a chatter line on the source («استلم <name> عبر الموبايل»); reply text «تم التسجيل ✓ لو عندك ملاحظة اكتبها هنا وهتوصل للفرع».
- `inbound.handle_free_text(*, wa_id, text, context_wamid, account) -> str`: attach as `remark` when the message quotes the alert's `wa_message_id`, or when exactly one alert from that phone was acknowledged in the last 30 min and has no remark; post it to the source's chatter so the branch is notified normally. Else `'unmatched'`.
- Webhook status callbacks (`delivered`/`read`/`failed` for a `wa_message_id` that belongs to a `PhoneAlert`) update the alert status (never downgrade `acknowledged`/`escalated`/`expired`) and append a `PhoneAlertAttempt`.
- Webhook: when the receiving account is the staff account (Task 3 `staff_account()`), route `button` → registry, text → `handle_free_text`, and **do not** create/update customer `WAConversation` unread state; customer accounts unchanged except `button` goes through the registry.

- [ ] **Step 1: Failing tests**: `test_status_callback_updates_alert_not_downgrade`, `test_tap_acknowledges_and_posts_chatter`, `test_tap_from_other_phone_ignored`, `test_second_tap_noop`, `test_remark_attached_by_quote`, `test_remark_attached_single_recent_ack`, `test_remark_ambiguous_not_attached` (two acked alerts ⇒ 'unmatched'), `test_staff_account_message_not_in_customer_inbox`, `test_refill_payload_still_routed`.
- [ ] **Step 2–4: FAIL → implement → PASS**; run `python manage.py test apps.tests` filtered to refill reminder tests too (`-k refill` equivalent: `apps.tests.test_refill_reminders` if present, else grep for the test module).
- [ ] **Step 5: Commit** `feat(phone-alerts): inbound taps, remarks, staff inbox separation`

### Task 5: Reminder / escalation / expiry tick

**Files:** Create `phone_alerts/jobs.py`; Modify `apps/sync/tasks.py` (call from `_process_reminders_and_snoozes`, or register `_run_phone_alerts_tick` every 1 min with `max_instances=1`, `id='phone_alerts_tick'`). Test: same file.

**Interfaces:** `tick(now=None) -> dict` with counts `{'reminded','escalated','expired'}`. Per open alert (status sent/delivered/read): source closed (`event.is_open` False) → `expired`; else `now - last_sent_at >= remind_after_min` and `reminders_sent < max_reminders` → `deliver(reminder=True)`; `now - created_at >= escalate_after_min` and not escalated → `escalated` + `fire('escalation', alert, notification=None, requested=True)` where the escalation text names the recipient, event and source reference. Escalation alerts never escalate again.

- [ ] **Step 1: Failing tests** (freezegun or explicit `now`): `test_reminder_after_15_min`, `test_max_two_reminders`, `test_escalates_after_30_min_once`, `test_closed_source_expires_alert`, `test_acknowledged_not_reminded`, `test_night_time_still_reminds` (now = 03:00).
- [ ] **Step 2–4: FAIL → implement → PASS.**
- [ ] **Step 5: Commit** `feat(phone-alerts): reminders, escalation, expiry job`

### Task 6: Hook the workflows

**Files:** Modify `apps/reservations/views.py` / `signals.py` (creation + status change), `apps/transfers/views.py` (`_notify` sites at :248/:297/:337) and `apps/transfers/notifications.py`, `apps/tasks/views.py:93,116`, and the three serializers (accept `phone_alert` write-only on create/assign). Test: same file.

**Interfaces:** Consumes `fire`. Mapping:
- Reservation created with status `pending` → `fire('reservation_sourcing', r)`.
- Reservation status change while `priority == 'urgent'` → `fire('reservation_status_urgent', r)`.
- Transfer submitted (→ `pending`) with `supplying_branch.is_hq` → `fire('transfer_hq_submitted', t)`; any later status change → `fire('transfer_status', t)`.
- Task created/assigned → `fire('task_assigned', task)`; status change → `fire('task_status', task)`.
- Serializer: `phone_alert` stored only when policy mode is `optional` or `always`; `always` forces True; `never` forces False. Add read-only `phone_alert_status` = latest alert status for that source (`acknowledged` beats others), plus `phone_alert_remark`.

- [ ] **Step 1: Failing API tests**: `test_reservation_pending_alerts_sourcing_owner`, `test_transfer_from_hq_alerts_dispatcher`, `test_transfer_from_branch_not_dispatcher`, `test_task_assign_alerts_assignee`, `test_toggle_ignored_when_policy_never`, `test_always_sends_without_toggle`, `test_detail_exposes_phone_alert_status`.
- [ ] **Step 2–4: FAIL → implement → PASS**; then run existing `apps.tests.test_reservations`, `test_transfers`, tasks tests — all PASS.
- [ ] **Step 5: Commit** `feat(phone-alerts): reservation, transfer and task hooks`

### Task 7: Admin API

**Files:** Create `phone_alerts/views.py`, `serializers.py`, `urls.py`; Modify `apps/notifications/urls.py` (include under `phone-alerts/`), the RBAC/route sweep classification (`apps/tests/security/` baselines + module access map) for the new prefix. Test: same file.

**Endpoints (admin + supervisor; others 403):**
- `GET/PATCH policies/` (`{event, mode, remind_after_min, escalate_after_min, max_reminders, escalate_to}`)
- `GET/POST/PATCH/DELETE owners/`
- `GET/PATCH branch-mobiles/` (`{branch_id, alert_mobile}`), `POST branch-mobiles/{id}/test/` (dry-run unless switch on)
- `GET/PUT channel/` (`{channel_account_id}` from `ChannelAccount` whatsapp list)
- `GET log/` (filters `status, event, branch, staff, date`; cursor pagination; masked phones for non-admin) and `GET log/{id}/` with attempts
- `GET switches/` → `{send_enabled, brief_enabled, account_set}` (read-only)
- Every write → `AuditLog` with before/after.
- Alerts-only staff (spec §9): the existing users create/edit API accepts `alerts_only`; when True the server sets `user.is_active=False` + `set_unusable_password()` and requires `phone`. Alerts-only profiles are excluded from the default users list (filter `?alerts_only=1` shows them), from device enrolment and from login.

- [ ] **Step 1: Failing tests**: `test_non_admin_forbidden`, `test_policy_patch_audited`, `test_owner_crud`, `test_log_masks_phone_for_supervisor`, `test_test_send_dry_run`, `test_alerts_only_cannot_log_in`, `test_alerts_only_hidden_from_users_list`.
- [ ] **Step 2–4: FAIL → implement → PASS**; run `apps.tests.test_endpoint_sweep` and `apps.tests.security` — PASS.
- [ ] **Step 5: Commit** `feat(phone-alerts): admin API`

### Task 8: Frontend — admin page, toggles, status chips, profile, help

**Files:** Create `frontend/src/pages/PhoneAlertsPage.jsx` (route `/phone-alerts`, admin/supervisor; tabs `policy|owners|branches|log`, `useHelpTab(tab)`), `components/PhoneAlertToggle.jsx`, `components/PhoneAlertStatusChip.jsx`; Modify `App.jsx`, sidebar nav, `NewReservationPage.jsx`, `mobile/MobileNewReservationPage.jsx`, `NewTransferPage.jsx`, `mobile/MobileNewTransferPage.jsx`, `TasksPage.jsx` (create/assign), `ReservationDetailPage.jsx`, `TransferDetailPage.jsx`, `TaskDetailPage.jsx`, mobile detail pages, the user edit form (phone, alerts-only, opt-out); `apps/help/content/general.py` (screen `general.phone_alerts` + statuses أُرسل/وصل/قُرئ/استلم/صُعّد/انتهى), and the reservations/transfers/tasks help screens for the toggle.

**Interfaces:** `<PhoneAlertToggle event="reservation_sourcing" value onChange />` — fetches `policies/` once (TanStack Query key `['phone-alert-policies']`); hidden for `never`, locked-on for `always`. `<PhoneAlertStatusChip status remark />`. Branch tab has the channel-account picker and the «إرسال تجريبي» button; a banner shows «وضع تجريبي — لا يتم الإرسال» when `switches.send_enabled` is false or no account.

- [ ] **Step 1:** Build components + page; wire toggles and chips.
- [ ] **Step 2:** `TEST_DB_NAME=test_phone_alerts_help python manage.py test apps.tests.test_help` → PASS (route has help, AR+EN).
- [ ] **Step 3:** `cd frontend && npm run build` → succeeds with no new warnings.
- [ ] **Step 4:** Preview: open `/phone-alerts`, change a policy, create a reservation with the toggle, confirm the log row (dry_run) and the chip on the reservation; screenshot.
- [ ] **Step 5: Commit** `feat(phone-alerts): admin page, form toggles, status chips, help`

### Task 9: Morning brief

**Files:** Create `apps/forecasting/kpi_board.py`, `apps/insights/brief.py`; Modify `apps/forecasting/views.py:209-~340` (`KpiBoardView.get` calls the extracted function), `apps/sync/tasks.py` (09:00 cron job `id='morning_brief'`; remove branch-manager recipients from the 07:30 insights WhatsApp send: skip `InsightRecipient` rows with `morning_brief=True` there), insights admin/serializer to edit `morning_brief`. Tests: `apps/tests/test_kpi_board_extract.py`, `apps/tests/test_morning_brief.py`.

**Interfaces:**
- `kpi_board.branch_mtd(branch_ids: list[int], year: int, month: int) -> dict[int, {'actual': Decimal, 'target': Decimal|None, 'pct': Decimal|None, 'daily_needed': Decimal|None, 'as_of': date}]` — exactly the numbers the KPI board shows today.
- `brief.compose(branch, day: date) -> BriefContent(headline_vars: list[str], text: str)`; sections in order: أمس (net sales, invoices, avg basket, Δ% vs same weekday last week via `KpiResolver.resolve`), الشهر حتى الآن (from `branch_mtd`), أهم 3 تراجعات (from `InsightEngine.render_for_branch` on today's day run — top 3 negative findings), متابعة اليوم (≤5 overdue/stuck reservations, ≤5 stuck transfers, each "رقم — صنف", plus «+N أخرى»). No numbers produced outside these engines.
- `brief.send_all(day=None) -> int`: per branch with ≥1 active `InsightRecipient(morning_brief=True, branch=b)` plus that branch's `alert_mobile`: create `PhoneAlert(kind='brief', event='morning_brief', phone=…)` and send template `morning_brief` with `brief:<token>` (dry-run rules of Task 3, switch `MORNING_BRIEF_SEND_ENABLED`). `inbound.handle_brief_tap` (Task 4 registry) sends `text` as free text in the opened window; second tap re-sends.

- [ ] **Step 1: Failing tests**: `test_branch_mtd_matches_view` (fixture rollups/targets; view JSON == function), `test_compose_sections_order_and_values`, `test_compose_caps_followups_at_5`, `test_send_all_targets_manager_and_branch_mobile`, `test_brief_dry_run_when_switch_off`, `test_brief_tap_sends_full_text`, `test_insights_0730_skips_brief_recipients`.
- [ ] **Step 2–4: FAIL → implement → PASS**; run `apps.tests.test_insights` and forecasting tests — PASS.
- [ ] **Step 5: Commit** `feat(brief): 09:00 branch morning brief over WhatsApp`

### Task 10: Expiry worklist fix + docs + full verification

**Files:** Modify `apps/batches/expiry_audit.py:1182-1209` (`sender.is_configured` property; send through `phone_alerts.sender` with a `PhoneAlert(kind='brief', event='expiry_worklist')` + template so it reaches people outside the 24 h window; requires both `expiry_worklist_whatsapp_enabled` and `PHONE_ALERTS_SEND_ENABLED`); docs: `docs/architecture/11_ERP_INDEX.md` (module/API/screen rows), `02_MODULE_REGISTRY.md`, `04_API_REGISTRY.md`, `05_UI_REGISTRY.md`, spec status → BUILT. Test: `apps/tests/test_expiry_worklist_whatsapp.py`.

- [ ] **Step 1: Failing tests**: `test_worklist_whatsapp_no_typeerror` (configured fake sender ⇒ one attempt recorded), `test_worklist_needs_both_switches`.
- [ ] **Step 2–4: FAIL → fix → PASS.**
- [ ] **Step 5:** Full suite `TEST_DB_NAME=test_phone_alerts_full python manage.py test apps.tests -v 1` → all PASS (report any pre-existing failures separately); `npm run build` → OK.
- [ ] **Step 6: Commit** `fix(expiry): worklist WhatsApp actually sends; docs for phone alerts`

---

## Owner actions outside the code (not blocking the build)

1. Choose the staff WhatsApp number and register it in Meta; add it as a `ChannelAccount` and pick it on `/phone-alerts`.
2. Submit templates `staff_alert` and `morning_brief` (utility) to Meta.
3. Fill owners (Gerges → `reservation_sourcing`, Youssef William → `hq_transfer_dispatch`), escalation people, branch mobiles, manager `InsightRecipient` rows with «ملخص الصباح».
4. Flip `PHONE_ALERTS_SEND_ENABLED` / `MORNING_BRIEF_SEND_ENABLED` in production `.env` after a dry-run week.
