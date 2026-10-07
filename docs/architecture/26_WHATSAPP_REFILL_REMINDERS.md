# 26 — WhatsApp Refill Reminders (B1)

**Status:** ✅ BUILT 2026-10-07 — sending OFF until the Meta template is approved and the owner switches it on.

## What it does
Every day at 10:10 (scheduler job `refill_reminders`) the open refill / chronic follow-up tasks
(`followups.FollowUpTask`, the same source as the portal's «refills») that fall due soon get ONE
WhatsApp template message per customer. The customer answers with a quick-reply button:

| Button | Result |
|---|---|
| جهّزوا طلبي في الفرع | `Reservation` (order_source `cc_whatsapp`, fulfilment `pickup`) at the task / preferred branch + call-center notification |
| توصيل للمنزل | same, fulfilment `delivery` |
| إيقاف التذكيرات | `RefillReminderOptOut` — never reminded again (staff can delete it in admin only on the customer's request) |

A pharmacist confirms the items before anything is prepared (no automatic dispensing or substitution).
The message never names the medicine (health privacy + Meta review). After a tap, a short confirmation is
sent inside the 24-h window the customer just opened.

## Template (submitted by the owner in WhatsApp Manager)
`refill_reminder`, Arabic, category Utility (Meta may reclassify as Marketing). Body variables:
{{1}} first name, {{2}} due date («12 أكتوبر»), {{3}} branch. Footer «صيدليات الرزيقي». Three QUICK_REPLY
buttons in this order: branch / delivery / stop — we send a payload `refill:<reminder id>:<choice>` per button.

## Eligibility (deterministic; every skip has a reason on the review screen)
Task type refill/chronic, status pending/called, due in [today − 2, today + 3]; customer with a usable
Egyptian mobile (WhatsApp phone, else phone), not opted out, not reminded in the last 25 days, branch able to
transact, item not known out of stock at that branch (no stock row = unknown → not skipped); one message per
customer per run; 300 per run; a failed send is retried once on the next run.

## Settings (all optional, getattr defaults)
`REFILL_REMINDER_SEND_ENABLED` (False) · `_TEMPLATE` (refill_reminder) · `_LANGUAGE` (ar) · `_DAYS_AHEAD` (3) ·
`_OVERDUE_DAYS` (2) · `_MIN_GAP_DAYS` (25) · `_DAILY_CAP` (300) · `_MAX_ATTEMPTS` (2).
While OFF nothing is stored or sent; the screen shows a live preview.

## Code
`apps/followups/refill_reminders.py` (rules, send, replies) · models `RefillReminder` / `RefillReminderOptOut`
(migration followups/0015) · API `apps/followups/reminder_views.py` → `/api/followups/refill-reminders/`
(+ `preview/`, `run/` admin/supervisor) · webhook routes `button` taps (`apps/whatsapp/webhook.py`) ·
`WhatsAppSender.send_template(quick_reply_payloads=…)` · screen `/followups/reminders`
(`RefillRemindersPage.jsx`). Tests `apps/tests/test_refill_reminders.py` (11).
