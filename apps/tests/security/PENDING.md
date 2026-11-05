# Pending owner decisions

Tests that expose a hole whose fix needs the owner's OK (SOFTECH writes, auth, pricing,
checkout) are marked `@pending('P-<n>')` and listed here as `- P-<n>: <one line>`. The marker
comes off the day the fix lands; `PendingTests.test_markers_match_pending_md` keeps this list
and the markers in step.

## Batch 5 — decided 2026-10-30 (owner)

B-1 finance: company-wide hub for admin, quality manager and the HQ roles; a branch user sees their
own branch only; supplier A/P reconciliation is company-only. B-2 customers: anyone finds any
customer by full phone; browse / name search / edit / churn list own branch; other branches' numbers
masked; call center and all-branch roles edit anyone (`apps/customers/access.py`). B-3: supervisor
and quality manager are all-branch roles (`core/branch_scope.ALL_BRANCH_ROLES`).
- W-1: voucher generate-otp hands the plain code to the staff member (wa.me text + QR)

## Round 2, R5 — sends (2026-11-05)

- S-1: a counselling card can go to any mobile the till types (or with no customer at all), not only the number on the customer's record. Restricting it changes the Project 4 till flow, so it waits for the owner. Held by `test_send_limits.CounselCardLimitTests.test_card_goes_only_to_the_number_on_the_customer_record`.
- S-2: the supplier-invoice write batch (`apps/invoices/writer.py`) and the supplier-code mapping batch (`apps/invoices/supplier_items.py::inject_mapping`) open a raw jConnect statement, so no query timeout is armed and a stalled HQ link can hold the job. Adding one changes a SOFTECH write path (a timeout mid-batch must roll back cleanly), so it waits for the owner. Held by `test_sybase_deadline.RawStatementSitesTests.test_softech_write_batches_have_a_query_timeout`.
- S-3: `pos_cancel_write` (SOFTECH `pos_cancel` INSERT) claims its events with an unconditional `filter(id__in=ids).update(softech_written_at=now)` — no `softech_written_at__isnull=True` filter and no row-count check — so two scheduler processes that read the same events both INSERT, and a failed run's un-claim can clear the other run's claim. Fix (claim only rows still unclaimed, write only those) changes a SOFTECH write path, so it waits for the owner. Held by `test_pos_cancel_writer.ConcurrentRunTests`.
