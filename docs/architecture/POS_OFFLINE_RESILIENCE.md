# Indirect-POS — Offline & SOFTECH-Down Resilience

How the POS keeps working when SOFTECH or a branch is unreachable, **without ever
duplicating a sale or a document number** in SOFTECH's real database.

## The core principle: never pre-assign a SOFTECH document number
SOFTECH document numbers are allocated **at write time** by the native read+1 pattern
(read `lastdocnumber*` under a row lock, INSERT with current+1, the trigger bumps the
counter) — all inside one branch transaction. We **never** generate a SOFTECH serial in
our system, online or offline. Therefore:

- Many orders can be created while a branch is down; none of them holds a number.
- When each one is finally written, it gets exactly one fresh number from SOFTECH itself.
- Two terminals/queues can flush concurrently — the row lock serialises allocation.

→ It is **structurally impossible** to send two documents with the same number.

## Two storage layers (decoupled)
1. **Our PostgreSQL** (the new system) — always available. Every order/line/payment lives
   here first (`SoftechSalesOrder…`). The cashier-facing work never depends on SOFTECH.
2. **SOFTECH (branch Sybase)** — only touched by the **push** step.

## Order lifecycle under an outage
```
draft → ready → [push] ─ branch up ──→ pushed → (cashier) → settled
                      └ branch down ─→ queued ──(auto-retry)──┘
```
- `push_order` runs in ONE branch transaction; on success it records `softech_docnumber`
  and goes `pushed`.
- If the connection fails (`_is_unreachable`: timeout / refused / JZ006 / IOException…),
  **no serial was allocated** and nothing was written, so the order is set to **`queued`**
  (HTTP 202 to the UI) instead of failing. Real data/logic errors → `push_failed` (raise).

## Idempotency — retries can't double-write
Two guards:
1. **PG state** — `push_order` returns early if the order already has a `softech_docnumber`
   and is `pushed`/`settled` (`already_pushed`). So a double-click, flush re-run, or client
   retry can never create a second document for the same order.
2. **Crash-recovery by `vf2` tag** — covers the narrow window where SOFTECH *committed* but
   the process died before PG saved the number (PG guard #1 would miss it). Every row we
   write carries a unique marker `vf2 = 'POS<order.pk>'`. Before inserting, the live path
   reads `_pending_docnumber_by_vf2` (a param SELECT, done *outside* the transaction so no
   ResultSet is left open across DML); if a row with our tag already exists it **adopts**
   that docnumber (`idempotent_recovered`) instead of writing a duplicate.

## Automatic recovery
- `flush_pos_orders` management command retries `queued` orders (`--include-failed` also
  retries `push_failed`). Each retry re-attempts the atomic allocate+write.
- Wired into APScheduler (`apps/sync/tasks._flush_pos_orders`) **every 2 minutes**.
- Manual: `POS_WRITER_ENABLED=True python manage.py flush_pos_orders`.

## Front-end offline
- The browser keeps a request queue (`src/api/offlineQueue.js`) for when even *our* API is
  unreachable; calls replay when connectivity returns.
- A `queued` push surfaces in the POS as “الفرع غير متصل — حُفظ الأمر في الطابور وسيُرسل
  تلقائياً” and the form resets, so the operator keeps selling.

## What still needs care
- **Full client-offline create idempotency**: if the browser replays a queued *create*,
  guard against duplicate PG orders via `client_token` (the field exists; add a
  get-or-create on it in the create view if double-creation is ever observed).
- **Settlement** is the irreversible step and is always done by the real cashier in
  SOFTECH — we never settle, so an outage never risks stock/e-invoice side effects.
