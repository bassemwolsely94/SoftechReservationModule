# Project 3 — Missed sales → reservation suggestions · Missed calls → call-back tasks

Status: DRAFT for owner approval (2026-11-03). Ships dark: both flags default OFF. Read-only on SOFTECH.

## Why
Two kinds of demand leak away today without anyone following up:
- a customer asks for an item at the POS and leaves without buying it;
- a customer calls and nobody answers.

We already record both (POS selections, Issabel CDR). What's missing is turning them into a follow-up that someone owns.

## What we found (2026-11-03, read-only probe on 5 SOFTECH nodes)
- SOFTECH `pos_cancel.custcode` is **always the sales account**, never a person. Examples: 1510 Walk-In, 1500 Home Delivery, and contract accounts such as 5006 «كهرباء شمال القاهرة» and 4846 «نقابة المهندسين». The native log cannot name the customer.
- The owner's decision is to use **our POS only**. In our POS the staff member picks the customer, so the customer is known for certain. We do not infer customers from native SOFTECH cancellations.
- Missed calls already have:
  - the CDR mirror (`apps/pbx/CdrCall`, synced every 10 minutes);
  - the "returned" rule (`pic_analytics/queries/calls.returned_map`);
  - the call-back queue (`CallLog status='callback'` + `callback_due`, `/callcenter/callbacks`, done = status→answered);
  - a manual "book call-back" button (PIC analytics «المكالمات الفائتة»).
- What's missing for calls is creating the call-back automatically, and closing it automatically.

## (a) Missed sales → suggested reservations (flag `MISSED_SALES_ENABLED`)

**Source:** `PosSelectionEvent` (our POS add/clear events, keyed by `cart_token` = the order's `client_token`).
- New nullable `customer` FK on the event. The frontend sends the selected customer's id; the server keeps it only if the customer exists.
- Fallback: the customer of the order whose `client_token` = `cart_token`.

**Detector** (scheduler job every 30 min; also a management command):
1. Look at `add` events older than 60 minutes, so the cart is finished, that have a known, real customer. Skip account placeholders, `PicExclusion` PICs and closed/deceased files.
2. Skip the item when it was sold:
   - the cart's order reached SOFTECH (pushing / pushed / settled) and contains the item; **or**
   - SOFTECH sales (`PurchaseHistory` lines) show that customer bought the item at any branch on or after the event.
3. Skip return carts (`doc_kind='return'`).
4. Each remaining (cart, item) becomes one `MissedSaleSuggestion`. It is unique on (cart_token, item_code), so re-runs never duplicate it.
   - If the same customer and item already have an open suggestion or an open reservation, no new suggestion is created.

**Model `MissedSaleSuggestion`** (new, in `apps/pos_orders`):
- Fields: branch, customer, item / item_code / item_name, qty, value (Σ transprice_total), seller_usercode, created_by (the POS user), cart_token, seen_at.
- Status: new → confirmed / rejected / expired.
- Decision fields: decided_by, decided_at, reject_reason (required on reject), and a `reservation` FK (set on confirm).
- Suggestions older than 14 days expire automatically (setting).

**Screen «مبيعات فائتة»** (`/missed-sales`):
- Branch staff see only their branch through `branch_scope`. Call center and management see every branch.
- Each row shows the customer, phone, item, qty, value, seller, time and the items the customer *did* buy in that cart. Every column is sortable.
- Actions:
  - **تأكيد كحجز** (confirm as reservation) opens the normal new-reservation form, prefilled with customer, item, qty and branch. The form's source is «مبيعات فائتة» (new `order_source='pos_missed'`).
    - Saving goes through the **existing** `POST /reservations/` with `missed_sale=<id>`. Inside the same transaction, the server re-checks that the suggestion is still `new` and in the user's scope, creates the reservation with every normal check (duplicate 409, closed file, branch scope), then marks the suggestion confirmed and links it.
    - Nothing is created without a person pressing save.
  - **رفض** (reject) needs a reason, picked from a short list (customer didn't want it / price check only / wrong item / bought elsewhere / other + text).
- Who / when / why is stored on the row and written to `AuditLog`. The reservation chatter notes "created from missed sale #N".

**Permissions:** checked server-side through the RBAC matrix module `reservations` (create) plus `branch_scope`. Viewing needs reservations view.

## (b) Missed calls → automatic call-back (flag `MISSED_CALL_CALLBACKS_ENABLED`)

**Trigger:** runs right after each CDR sync (inside the existing `pbx_cdr_sync` job), but only when the flag is ON.
- Candidates are `CdrCall` rows with direction inbound, status not answered, not a transfer, and from the last 24 h.
- Skip any number that is:
  - labelled staff / supplier / branch / spam in `PhoneLabel`;
  - already returned (`returned_map`);
  - already holding an open call-back.

**Task = the existing call-back:** a `CallLog`:
- Main fields: `status='callback'`, `direction='inbound'`, `source='pbx'`, the number, the matched customer, `purpose='general'`, and the note «مكالمة فائتة — معاودة اتصال تلقائية».
- New fields on CallLog:
  - `missed_cdr` (OneToOne → CdrCall). Its uniqueness makes the job idempotent.
  - `missed_count`. When the same number calls and misses again, the open call-back's count goes up and **no** second task is created.
- **Routing (owner):** the call-center pool. `handled_by` is empty and `branch` is empty. The existing queue already shows unassigned call-backs to call_center, supervisor and admin.

**Due time (owner):** within working hours, due 15 minutes after the call. Outside working hours, due at the next opening.
- Settings: `MISSED_CALL_OPEN_HOUR` = 9, `MISSED_CALL_CLOSE_HOUR` = 23, `MISSED_CALL_DUE_MINUTES` = 15. Both hours are my call; the owner can change them.

**Auto-close:** when the call is returned, the open auto call-back is closed automatically on the next sync.
- "Returned" means an answered call with that number, in either direction, after the missed call. This is the same rule as the analytics tab.
- Closing sets `status='answered'`, `callback_resolution='auto_returned'` and `callback_resolved_at`.
- When staff mark one done by hand, the resolution is `manual` and their name is recorded.

**Queue screen:** the existing `/callcenter/callbacks` page gets two additions:
- a small «تلقائي» badge and the count of missed calls on the row;
- a filter for "missed calls only".

No new page.

**Later (not in this batch):** an urgent phone alert when call-backs are overdue, once phone-alerts is on main.

## Non-goals / anti-goals
- No writes to SOFTECH.
- No customer inference from native SOFTECH `pos_cancel`. The owner chose our POS only.
- No reservation is ever created without a human pressing save.
- No new task system. We use the existing Reservation and CallLog call-back.

## Tests
- Detector:
  - sold-in-cart is excluded;
  - sold later in SOFTECH is excluded;
  - placeholder / excluded customer is excluded;
  - re-runs create nothing new;
  - an open reservation stops a new suggestion;
  - suggestions expire.
- Confirm:
  - creates exactly one reservation;
  - a second confirm gets 409;
  - out-of-scope branch gets 404;
  - no reservations perm gets 403.
- Reject: a reason is required, and the audit row is written.
- Calls:
  - one call-back per missed call;
  - a repeat miss increments the count;
  - labelled numbers are skipped;
  - an already-returned call is skipped;
  - auto-close works;
  - after-hours due time is correct;
  - flag OFF → nothing happens.
- Help: `test_help` covers the new route.

## In-app help
- `apps/help/content/missed_sales.py` (new, AR+EN).
- The callbacks help page is updated for the «تلقائي» call-backs.
