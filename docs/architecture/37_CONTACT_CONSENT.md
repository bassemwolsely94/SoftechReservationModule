# 37 — Customer contact consent (P-05)

Status: ✅ BUILT 2026-11-15. Minimal version of backlog P-05, approved by the owner on 2026-11-11.
No SOFTECH read or write.

The PDPL reading in P-05 (prior consent and free opt-out for direct marketing; health data is sensitive)
comes from secondary sources. **Counsel should still confirm it.** The rules below are the conservative
reading, so they can only be relaxed later.

## The rule (one place: `apps/customers/consent.py`)

| Purpose | Needs a recorded "yes"? | Used by |
|---|---|---|
| `service` | No — allowed unless the customer said no | restock WhatsApp ("the item you asked for is back") |
| `refill` | **Yes** (opt-in) | refill reminders; a "no" on `call` also keeps them off outbound call lists |
| `marketing` | **Yes** | WhatsApp campaigns |
| `marketing_health` | **Yes** | campaigns that target a health condition (`chronic_category`, `has_condition(s)`) |

- **Account state comes first (B7):** closed (`'0'`, merged codes included) and deceased codes get nothing.
  Entities get service messages only.
- A "no" always wins over an older "yes".
- The decision is per channel (`whatsapp`, `call`, `sms`). Every sender today is WhatsApp, except staff
  calls, which only honour a "no".
- `ContactConsent` is append-only (migration `customers/0033`). The latest row per
  (customer, purpose, channel) is the decision; older rows are its history (who, when, source).
- Staff changes also go to the AuditLog (`customer_updated`, note `P-05 consent …`).

## Where it is captured

- **POS customer bar** (desktop and mobile), `ConsentChips`: "تذكيرات الصرف" and "العروض". One tap
  records the opposite of the current answer (not asked → yes). It shows ✓ / ✕ / ؟. There is no modal.
- **Customer page**: all four purposes (source `staff`).
- **API**: `GET/POST /api/customers/<id>/consent/` `{purpose, granted, channel?, source?, note?}`.
  POST needs customers **edit** (pharmacist, call center, supervisor, admin; salespeople are read-only).
- **WhatsApp STOP**: a text reply of exactly `stop` / `unsubscribe` / «إيقاف» / «ايقاف» / «الغاء» /
  «إلغاء الاشتراك» / «وقف» / «توقف» withdraws every purpose on WhatsApp, for every customer on that number.
- **Refill reminder "stop" button**: withdraws `refill` on WhatsApp and call.
- **Migration** `customers/0034`: every existing `RefillReminderOptOut` became a `refill` withdrawal on
  WhatsApp and call. The old rows are kept as history and are no longer written.

## Senders rewired

| Sender | Before | Now |
|---|---|---|
| Campaigns: the dispatcher **and** the views' audience builder (preview + queue) | everyone in the segment; account state only in the dispatcher | `consent.filter_allowed(qs, marketing / marketing_health)` |
| Refill reminders | everyone except opt-outs | `refill` "yes" required; skip reasons `opted_out` / `no_consent` |
| Call lists | excluded refill opt-outs | `consent.exclude_withdrawn(qs, refill, call)` |
| Restock WhatsApp | per-request opt-out only | also `can_contact(customer, service)` |

## Effect on switch-on

- **Campaigns** reach only customers with a "yes". Until counters start asking, audiences are
  near-empty; that is intended (P-05 "smallest version").
- **Refill reminders** are still OFF (`REFILL_REMINDER_SEND_ENABLED`). When switched on they go only to
  customers who agreed. The WhatsApp template still needs Meta approval.

## Not in this batch (next)

- Campaign "templates only" switch (Meta rejects free text outside the 24-hour window).
- Measurement screen: % of active customers with a decision, opt-out rate, messages blocked by
  suppression.
- Portal capture (`source='portal'`) and SMS.
- Counter script and training.

Tests: `apps/tests/test_contact_consent.py` (rules, bulk filters, the STOP reply, restock, API +
permission, data migration). Updated: refill reminders, call lists, campaign workflow, account-state
campaign audience.
