# Missed Sales + Missed Calls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn our POS's unsold items for known customers into reservation suggestions that staff confirm or reject, and turn missed inbound calls into automatic call-backs that close themselves.

**Architecture:**
- **Missed sales:**
  - `apps/pos_orders/missed_sales.py` is a detector over `PosSelectionEvent`. It writes `MissedSaleSuggestion` rows.
  - Two new endpoints let staff list and reject them.
  - Confirming is done through the existing `POST /reservations/` with a `missed_sale` id.
- **Missed calls:**
  - `apps/pbx/missed_callbacks.py` runs after each CDR sync.
  - It creates `CallLog(status='callback')` rows, linked one-to-one to the missed `CdrCall`.
  - It also auto-closes them once the number is returned.
- Both features are gated by settings flags that default to OFF.

**Tech Stack:** Django 4.2 / DRF, APScheduler, React 18 + TanStack Query, Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-03-missed-sales-and-missed-calls-design.md`

## Global Constraints
- Flags: `MISSED_SALES_ENABLED` and `MISSED_CALL_CALLBACKS_ENABLED`, both default False.
  - When a flag is OFF, its job does nothing and its endpoints return 503.
- Read-only on SOFTECH. No Sybase calls anywhere in this feature.
- Settings:

  | Setting | Value |
  |---|---|
  | `MISSED_CALL_OPEN_HOUR` | 9 |
  | `MISSED_CALL_CLOSE_HOUR` | 23 |
  | `MISSED_CALL_DUE_MINUTES` | 15 |
  | `MISSED_SALES_MIN_AGE_MINUTES` | 60 |
  | `MISSED_SALES_EXPIRE_DAYS` | 14 |

- Reject reasons: `not_wanted`, `price_check`, `wrong_item`, `bought_elsewhere`, `other`. `other` needs text.
- New reservation `order_source='pos_missed'`, labelled «مبيعات فائتة».
- Audit actions:
  - `missed_sale_confirmed`
  - `missed_sale_rejected`
  - `missed_call_callback_created`
  - `missed_call_callback_auto_closed`
- Arabic RTL. Every new table is sortable. Help content for `/missed-sales` (AR+EN).

## Review Focus
- **Same customer + item seen in two carts:** only one open suggestion is created. → test `test_one_open_suggestion_per_customer_item`.
- **A double-click on confirm or two staff confirming at once:** only one reservation; the second gets 409. → `test_confirm_twice_conflict`.
- **A reservation POST with a `missed_sale` that is in another branch:** 404 and no reservation. → `test_confirm_out_of_scope`.
- **A missed call from a number that already has a manual call-back:** no new auto call-back. → `test_existing_open_callback_blocks`.
- **A missed call at 23:30 or 02:00:** due 09:00 the next opening. A call at 08:00 is due 09:00 the same day. → `test_due_after_hours`.

---

### Task 1: Missed-sale model + detector
**Files:**
- Modify: `apps/pos_orders/models.py`. Add `customer` FK on `PosSelectionEvent`, and add the new `MissedSaleSuggestion`.
- Create: migration, `apps/pos_orders/missed_sales.py`, command `detect_missed_sales`.
- Modify: `apps/pos_orders/views.py`. `selection_events_ingest` takes the `customer` id.
- Test: `apps/tests/test_missed_sales.py`.

**Interfaces:**
- `detect_missed_sales(now=None) -> dict` returns `{'created', 'skipped_sold', 'skipped_open', 'expired'}`.
- `MissedSaleSuggestion` statuses: `new`, `confirmed`, `rejected`, `expired`.

Tests:
- sold in the cart order → skipped;
- bought later in `PurchaseHistory` → skipped;
- placeholder or excluded customer → skipped;
- younger than min age → skipped;
- a rerun creates nothing new;
- an open reservation for the same customer, item and branch → skipped;
- older than 14 days → expired;
- return cart → skipped.

### Task 2: List / reject API + reservation confirm path
**Files:**
- `apps/pos_orders/missed_sales_views.py` with:
  - `GET /api/pos-orders/missed-sales/`, filters `status`, `branch`, sortable;
  - `POST /api/pos-orders/missed-sales/{id}/reject/`.
- `apps/reservations/models.py`: add `pos_missed` to the choices, plus a migration.
- `apps/reservations/views.py`, in `create`:
  - read the optional `missed_sale`;
  - lock the row with `select_for_update`;
  - it must be `new` and inside the user's `branch_scope`, otherwise 404 (scope) or 409 (not new);
  - after `perform_create`, mark the suggestion confirmed and link the reservation;
  - write the chatter note and `AuditLog`;
  - everything runs in one `transaction.atomic`.

**Permissions:**
- List: reservations view in the matrix, plus `branch_scope`.
- Reject: reservations create.

Tests:
- `test_confirm_creates_one_reservation`
- `test_confirm_twice_conflict`
- `test_confirm_out_of_scope`
- `test_reject_requires_reason`
- `test_reject_audit`
- `test_list_scoped_to_branch`
- `test_flag_off_503`

### Task 3: Missed-call auto call-backs
**Files:**
- `apps/callcenter/models.py`: add to `CallLog`:
  - `missed_cdr` (OneToOne → `pbx.CdrCall`, null);
  - `missed_count` (default 0);
  - `callback_resolution` (`''`, `manual`, `auto_returned`);
  - `callback_resolved_at`.
  - Also a migration.
- `apps/pbx/missed_callbacks.py`:
  - `queue_missed_callbacks(now=None) -> dict`;
  - `close_returned_callbacks() -> int`;
  - `due_for(call_at) -> datetime`.
- `apps/sync/tasks.py`: `_run_pbx_cdr_sync` calls both when the flag is on.
- `apps/callcenter/views.py`: `pending_callbacks` accepts `?auto=1`. The serializer exposes `is_auto`, `missed_count` and `callback_resolution`. A manual mark-done (PATCH to answered from callback) sets `callback_resolution='manual'`.

Tests:
- `test_creates_callback_per_missed_call`
- `test_repeat_miss_increments_count`
- `test_labelled_number_skipped`
- `test_already_returned_skipped`
- `test_existing_open_callback_blocks`
- `test_auto_close_on_answered`
- `test_due_after_hours`
- `test_flag_off_noop`

### Task 4: Frontend + help
- New `frontend/src/pages/MissedSalesPage.jsx` at route `/missed-sales`, linked from the nav near reservations.
  - Sortable table; reject inline with a reason select (no modal).
  - Confirm navigates to `/reservations/new?missed_sale=<id>`.
- `NewReservationPage.jsx`: when `missed_sale` is in the query, fetch it and prefill customer, item, qty and branch, set `order_source='pos_missed'`, and send `missed_sale` on create.
- `CallbackQueuePage.jsx`: a «تلقائي» badge, the `missed_count`, and a "missed calls only" toggle.
- `usePosOrder.js`: send `customer` (the id) on selection events.
- Help:
  - new `apps/help/content/missed_sales.py`, registered in `MODULE_FILES`;
  - callbacks help updated;
  - `updated` dates bumped.

### Task 5: Verify
- Backend tests: run `python manage.py test apps.tests.test_missed_sales apps.tests.test_missed_callbacks apps.tests.test_help apps.tests.test_pos_cancel_writer` with a unique `TEST_DB_NAME`.
- Frontend checks: `npm run lint`; `npm run build`.
- Commit on the branch.
