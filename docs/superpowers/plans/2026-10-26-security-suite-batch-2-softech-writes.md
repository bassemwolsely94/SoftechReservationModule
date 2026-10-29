# Security Suite — Batch 2 (SOFTECH write safety) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every path that writes to SOFTECH is safe against injection, can't run unless its switch is on, can't post twice, and leaves an audit trail.

**Owner rule (2026-10-26):** every product-code change in this batch is brought to the owner as a small diff and lands only after an explicit OK.

**Spec:** [design](../specs/2026-10-26-full-security-test-suite-design.md) · inputs: [inventory](../../security/2026-10-26-security-inventory.md), `apps/tests/security/softech_write_manifest.py` (59 write sites), `baselines/sql_from_text.txt` (26 write-path blocks), `baselines/raw_softech_connect.txt`, `baselines/write_flags_default_true.txt`.

## How each item runs

1. **Failing test first.** Write it, mark it `@pending('P-<n>')`, and add `- P-<n>: <one line>` to `apps/tests/security/PENDING.md`. The suite stays green and the hole is visible.
2. **Diff to the owner.** Prepare the fix as a patch file in `scratch/batch2/P-<n>.patch` and show it to the owner. The product code is not touched yet.
3. **On approval:**
   - apply the patch;
   - remove the marker and the PENDING line;
   - run the item's tests and the related app suites;
   - update its manifest/baseline lines.
4. **On rejection or deferral:** the pending marker stays, so the hole stays visible.

## Items (order = risk)

| P | Item | Where |
|---|---|---|
| P-1 | POS `claim.examdate` (and any `__dt__` value) pasted unescaped into SOFTECH INSERTs | `pos_orders/writer.py` `_raw_value`, `_claim_dt`; `serializers.py` claim |
| P-2 | Shortage flag/unflag/dismiss/retrieve: any logged-in user writes SOFTECH `items`, and the switch is on in `.env` | `purchasing/shortage_views.py` |
| P-3 | Kill-switch bypass: `diag_appname` opens its own connection and INSERTs on HQ | `invoices/management/commands/diag_appname.py` |
| P-4 | Loyalty points INSERT has no idempotency (a retry writes double points); no size cap; call_center can trigger it | `loyalty/pic_bridge.py`, loyalty adjust view |
| P-5 | Four write switches default ON: pricing, replication repair, loyalty, personal comments | `config/settings.py` (+ `.env.example`) |
| P-6 | Writes with no switch over HTTP: `alignment/tier-create`, invoice `probe`, coupon `batch-probe` | `discount_approvals`, `invoices`, `vouchers` |
| P-7 | Live-writing diagnostic commands with no switch (`investigate_britems*`, `probe_*`, `test_replication_cycle --mode plant`, `test_pic_points`, `capture_save_sql --enable-monitoring`) | `apps/sync/management/commands/` |
| P-8 | Read-only checker holes: `'--'` inside a string literal hides trailing SQL; `stmt.getConnection()` returns the raw connection; `SoftechConnector` ignores the branch-host override | `config/sybase.py` |
| P-9 | Writer functions that check their switch only in the caller (`write_pos_cancel_batch(dry_run=False)`, `recon_writer.fix_due_before`, `supplier_items.inject_mapping`, `probe_reservation`) | as listed |
| P-10 | Manifest completion: every `flag=None` / `dry_run_default` / `idempotency` / `audit` / `trigger` field verified against the code, plus a per-site switch-off test | `softech_write_manifest.py` |

P-5 changes defaults the owner relies on in production: present the options; never flip silently.

## Found by P-10 (manifest verification, 2026-10-26) — same owner-approval rule

| P | Item | Where |
|---|---|---|
| P-11 | **Double post risk:** `_flush_pos_orders` is registered as TWO scheduler jobs (`pos_orders_flush` + `pos_flush_queued`, every 2 min) over the same QUEUED orders; `push_order` has no row lock (vf2 adopt runs outside the txn) | `apps/sync/tasks.py`, `apps/pos_orders/writer.py` |
| P-12 | `probe_ap_writeback --rehearse` is not a rehearsal: `SoftechConnector.begin_transaction/rollback` are no-ops, so its `cheques` / `chequestrans` INSERTs commit (ran once 2026-09-18; SOFTECH's trigger discarded the row) | `apps/sync/management/commands/probe_ap_writeback.py` |
| P-13 | Rehearsals whose restore is not in `finally` (a failure leaves the marker / a real ISR approval): `probe_write`, `probe_coverage_write`, `probe_approve_isr` | purchasing writers |
| P-14 | Investigation commands that leave changes behind: `test_replication_cycle --mode plant` never restores; four leave `usercode='00099'`; `investigate_britems2` / `probe_replication_source` britems restores are broken | `apps/sync/management/commands/` |
| P-15 | Missing locks / idempotency on real writes: `rebalance_run` (double shift), `points_removal` (double debit), `apply_date_edit` (second apply corrupts restore point), `channel_b` promo (new offer each call), `push_isr --commit` (new ISR each run) | insurance, customers, offers, purchasing |
| P-16 | Missing audit: nothing for pricing alignment / tier create / offers A+B; logger only for shortage, supplier mapping, ISR approve, coverage commands; who-pushed not kept for invoices / POS; `executed_by` dropped for rates (needs an `audit` migration — coordinate with the parallel session) | as listed |

## Done when

- `PENDING.md` lists only items the owner deferred.
- `raw_softech_connect.txt` is empty.
- `write_flags_default_true.txt` holds only reviewed non-SOFTECH switches.
- Every manifest field is filled from the code.
- The full suite has no new failures.
