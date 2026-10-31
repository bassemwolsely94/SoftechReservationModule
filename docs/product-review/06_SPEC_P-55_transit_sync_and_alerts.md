# 06 · SPEC P-55 — Transit receipt sync fix + alerts people read

**Status:** specification. **Part A (sync fix) BUILT 2026-10-30, owner-authorised "fix it now".** Not committed.
Parts B–C are spec only.

## Part A — receipt-sync fix (BUILT)

**Root cause (measured).**
- When the SOFTECH connection dropped mid-run, `_detect_receipt` swallowed the error and returned "not received".
- Every remaining transfer stayed or flipped to "in transit". **Already-received transfers had their receipt data
  wiped**. Each was alerted daily to every branch user plus all admins.
- Logs: 13,320 failures, 18–28 Oct. A read-only check found **19 of 20 "stuck" transfers have their doc-25 receipt in
  SOFTECH**.

**Change** (`apps/transits/management/commands/sync_in_transit.py`)
1. `_ReconnectingConnection` wraps the jConnect connection. A failed receipt query triggers **one reconnect and a
   retry**. This is the same idiom the transfers ERP matcher already uses.
2. A failed check raises `ReceiptCheckError`, meaning **"unknown"**. The header loop and the wide re-check
   **leave the stored record untouched** and count `receipt_check_failed`.
3. **Circuit breaker:** after 3 failures in a row, SOFTECH is treated as down for the rest of the run. There are no
   further reconnect attempts; each would cost about 22 s on a dead network.
4. **Alerts fire only for transfers verified this run** (`last_synced_at >= run start`). The wide re-check now stamps
   `last_synced_at` when it verifies "still not received".
5. The run summary logs `receipt_check_failed`, and logs an ERROR when it is > 0.

**Tests** (`apps/tests/test_transits_sync.py::ReceiptCheckFailureTests`, all written first and seen failing):

| Test | Proves |
|---|---|
| failed check never un-receives | a received transfer keeps its status and receipt |
| reconnects and retries | a dropped session heals |
| no alert when the check failed | false pings stop |
| alert still fires when verified | real stuck transfers still alert (control) |
| breaker | stops retrying after 3 |
| wide re-check failure | old open transfers follow the same rule |

All 23 transit tests pass.

**One-off clean-up after deploy (owner runs; SOFTECH SELECT-only):**

```
python manage.py sync_in_transit --days 120 --full
```

Expected: most of the 776 "≥14 days" transfers flip to received. Record the before/after counts.

## Part B — alert routing and digest (spec)

1. **Transit alerts become digests.**
   - Instead of one notification per transfer per day per user, send **one digest per receiving branch per day** to:
     - the **branch manager** (role at that branch);
     - the **HQ transfers coordinator** (a new SystemSetting `transit_digest_recipients`: list of staff ids;
       default = admins).
   - Example content: "N transfers awaiting receipt — oldest X days", with a deep link to `/transits?status=in_transit&branch=…`.
   - Per-transfer notifications stay only for `transit_mismatch` (a real discrepancy).
2. **Routing table:** SystemSetting `notification_routing` (JSON) — per notification type: `instant | digest | off`,
   plus target roles. The defaults keep today's behaviour for every non-transit type.
3. **Sync-failure alert:** after 3 consecutive failed runs of the same lane (`SyncRun.status='failed'`), one
   notification to admins, deduped per lane per day.

## Part C — retention (spec; shared with P-56)

- Daily job `notifications_retention`:
  - delete read notifications older than 30 days;
  - delete unread notifications older than 90 days;
  - prune NotificationLog to the same windows.
- Batched deletes (10k per transaction) to avoid long locks.

## Acceptance criteria (B, C)

- **Digest:** a branch with 5 overdue transfers produces **1** notification per recipient per day. Re-running the sync
  the same day produces 0 more (dedup test).
- The routing setting `off` suppresses a type; `instant` keeps the current behaviour (tests).
- **Retention:** only rows past their window are deleted. Announcements (read receipts) are excluded.
- Help text updated for the transits screen (digest) and the notifications page.

## Measurement

- Alerts per user per day: baseline ≈150 for the top recipients.
- % read within 24 h: baseline 0%.
- Count of in-transit transfers ≥14 days: baseline 776; expected to drop sharply after Part A + the clean-up.
