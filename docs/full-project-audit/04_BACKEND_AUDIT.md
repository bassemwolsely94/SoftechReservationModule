# 04 — Backend correctness & data-integrity audit

Scope: money and stock first. Read-only static review of the `full-audit` worktree (Grep/Read only;
no tests, no management commands, no SOFTECH). Paths are relative to the worktree root.
The test suite was not run, so every "regression test" below is a proposal.

Severity: **P0** = financial or inventory corruption reachable today · **P1** = corruption reachable
through a realistic race or API call · **P2** = wrong money, points or audit under concurrency or
misuse · **P3** = cent-level, display, or hygiene issue.
Status: **VERIFIED** = the code path was read end to end · **SUSPECTED** = the path is plausible,
but the runtime conditions were not confirmed.

## Counts

| Severity | Count |
|---|---|
| P0 | 0 |
| P1 | 2 |
| P2 | 11 |
| P3 | 8 |

No P0 was found. Several core paths are solid and are listed at the end as checked.

---

## Findings

### BE-1 · P1 · Deleting a POS order that is already posted to SOFTECH (VERIFIED)
- **Evidence:** `apps/pos_orders/views.py:158` declares `OrderDetailView(... generics.RetrieveUpdateDestroyAPIView)`. `update()` (l.164-170) refuses a locked order with `if order.is_locked: ... 409`. There is no `destroy`/`perform_destroy` override, so DELETE has no lock check. `apps/pos_orders/models.py:216,273`: lines and payments are deleted with the order (`on_delete=models.CASCADE`). The frontend never calls DELETE or PATCH on `/pos-orders/<id>/` (checked by grep in `frontend/src`).
- **Failure:** a user holding the `pos`/delete permission sends `DELETE /api/pos-orders/<id>/` for a PUSHED or SETTLED order. The only PostgreSQL record of the SOFTECH posting disappears: `softech_docnumber`, `client_token`, `erp_payload` and the lines. Reconcile can no longer match the order. The offline queue may later replay a create with the same `client_token`; the unique key is now free, so a new order is created, and if that order is pushed again the sale is posted twice.
- **Smallest fix:** add `perform_destroy` that returns 409 unless `status in (DRAFT, READY)` and `softech_docnumber` is empty. Or remove DELETE from the view (`http_method_names`).
- **Test:** DELETE a PUSHED order → 409 and the row still exists. DELETE a DRAFT order → 204.

### BE-2 · P1 · `prepare_order` saves the whole order without a lock and can overwrite PUSHED status and docnumber (SUSPECTED; needs owner approval, because it touches checkout)
- **Evidence:** `apps/pos_orders/writer.py:516-633`. The `is_locked` check reads the in-memory status (l.528). The function then calls `order.save()` with no `update_fields` (l.629), deletes and rebuilds the payments, and has no `transaction.atomic` and no `select_for_update`. QUEUED and PUSH_FAILED orders are not locked (`models.py:208-211`), so `/ready` accepts them. The push claim (`writer.py:852-856`) is a conditional UPDATE. Crash recovery (`_pending_docnumber_by_vf2`, `writer.py:1409-1425`) looks only in `stktransm5`, the pending table.
- **Failure:** an order is QUEUED because the branch was offline. The cashier presses send again; the UI calls `/ready` and then `/push`. At the same moment the `pos_orders_flush` job claims the order, commits it, and saves PUSHED with a docnumber. `prepare_order` had loaded the order before that, so it now writes `status=READY, softech_docnumber=NULL` over it. The UI push then claims READY → PUSHING. If the cashier has already finalized the pending document, the vf2 lookup in `stktransm5` finds nothing and the sale is written a second time. Even without a second write, PostgreSQL has lost the docnumber.
- **Fix:** run `prepare_order` inside `transaction.atomic()`. Re-read the order with `select_for_update()`, re-check `is_locked` and status on the locked row, and set READY with a conditional `filter(pk, status__in=[DRAFT, READY, QUEUED, PUSH_FAILED]).update(...)` instead of a full `save()`. Also consider rejecting `/ready` on QUEUED orders.
- **Test:** load an order, mark it PUSHED with a docnumber through another queryset, then call `prepare_order` on the stale instance → it raises, and the DB still says PUSHED with the docnumber.

### BE-3 · P2 · `prepare_order` writes are not atomic (VERIFIED; same approval as BE-2)
- **Evidence:** `writer.py:553-587`: each line is saved inside the loop (`line.save()`, including a contract `cust_discp` taken from the schedule). Afterwards `raise ValueError` for blocked items (l.589) or for a tender mismatch (l.618) leaves those lines saved, while the header keeps its old `doc_value`. `order.payments.all().delete()` and the re-create loop (l.633-649) are not in a transaction either.
- **Failure:** in a contract order where one item is blocked, the earlier lines keep the new discount and the new `trans_price_total`, but `doc_value` is stale. If a create fails halfway through the payments, the order is left with no payment rows.
- **Fix:** wrap the body in `transaction.atomic()` (together with BE-2).
- **Test:** a contract order with one blocked item → ValueError, and every line field is unchanged.

### BE-4 · P2 · Orders posted from the queue never consume offer uses (VERIFIED; reachable when the offers flag is ON)
- **Evidence:** `consume_offer_uses` has one call site, `apps/pos_orders/views.py:348-357`, and it runs only on an interactive push that returned success. The comment at l.341-343 says uses are consumed "via the flush path", but neither `apps/pos_orders/management/commands/flush_pos_orders.py:37` nor `flush_now` (`views.py:1257`) calls it. The only caller of `consume_offer_uses` outside tests is `views.py:350`.
- **Failure:** an offer has `max_uses_total=100`. Every sale that was queued while a branch was offline and later posted by the flush never sets `OfferApplication.was_applied`. The limit is never reached, so more discounted sales go out than the owner capped.
- **Fix:** after a successful flush push, call `consume_offer_uses(order, customer=resolve_order_customer(order))`, with the same `UsageLimitExceeded` logging, in `flush_pos_orders` and in `flush_now`.
- **Test:** queue an order that carries an offer line, flush it (with a mocked writer returning ok) → `OfferApplication.was_applied=True`.

### BE-5 · P2 · Single-use voucher can be redeemed twice through two OTPs (VERIFIED)
- **Evidence:** `apps/vouchers/views.py:311-410`. `check_full_eligibility` reads `times_used` from an unlocked row (`models.py:141`, `is_exhausted`). Only the OTP row is locked (`.select_for_update()` at l.344-348). Then `times_used = F('times_used') + 1` runs (l.405).
- **Failure:** a voucher has `max_uses=1`, and two OTPs exist (two phones, or one phone after a resend; `create_for_voucher` invalidates only the same phone). Two counters call verify-otp at the same time. Both pass `is_exhausted` (0 < 1), each locks a different OTP row, and both create a redemption document. `times_used` ends at 2, so two discounts are issued.
- **Fix:** at the start of verify-otp, lock the voucher (`Voucher.objects.select_for_update().get(pk=pk)`), then re-check `is_exhausted` and the status after the lock.
- **Test:** a TransactionTestCase with two threads and two OTPs on a voucher with `max_uses=1` → exactly one document.

### BE-6 · P2 · Loyalty redemption approval: a double approve deducts twice, and a failed deduction stays "approved" (VERIFIED)
- **Evidence:** `apps/loyalty/views.py:378-391` reads the request with `RedemptionRequest.objects.get(pk=pk, status='pending')`, with no lock. `apps/loyalty/models.py:418-428` `approve()` saves `status='approved'` first and then calls `redeem_points`, which can raise `ValueError` for an insufficient balance. Nothing is atomic.
- **Failure:** (a) a double click or two managers: both requests read `pending`, and `redeem_points` runs twice, so the account loses `2×points_spent`. (b) The balance dropped after the request was created: the status is persisted as `approved`, the view returns 400, and no points were deducted, so the reward is approved without being paid for.
- **Fix:** run the view in `transaction.atomic()`, `select_for_update()` the request (status pending) and the account, and deduct before marking the request approved.
- **Test:** approve twice → the second call returns 404/409 and the balance dropped once. Approve with an insufficient balance → the status stays `pending`.

### BE-7 · P2 · `LoyaltyAccount` balance updates are read-modify-write (VERIFIED)
- **Evidence:** `apps/loyalty/models.py:125-195`: `self.points_balance += abs(points)` followed by `save(update_fields=[...])` in `add_points`, `redeem_points`, `adjust_points` and `expire_points`. There is no lock and no `F()`. The callers are `loyalty/views.py:142` and `referral/views.py:200`; neither is atomic.
- **Failure:** a referral credit and a redemption arrive at the same moment. Both read balance 500 and one write overwrites the other. The ledger (`PointTransaction`) no longer sums to `points_balance`.
- **Fix:** perform each mutation inside `transaction.atomic()` after `LoyaltyAccount.objects.select_for_update().get(pk=self.pk)`, or with `F()` followed by `refresh_from_db`.
- **Test:** two concurrent `add_points(10)` → the balance rises by 20, and the transaction sum equals the balance.

### BE-8 · P2 · A negative "referral" adjustment adds points (VERIFIED; reachable by API only)
- **Evidence:** `apps/loyalty/views.py:141-147` passes the signed `delta` to `account.add_points(points=delta, ...)`, and `add_points` stores and adds `abs(points)` (`models.py:130,137`). The frontend sends only the purchase lane (`CustomerDetailPage.jsx:1064`, `LoyaltyPage.jsx:148`).
- **Failure:** `POST {"points": -200, "adjust_type": "referral"}` credits +200 points.
- **Fix:** for `adjust_type == 'referral'`, return 400 when `delta < 0`, or route a negative delta through `adjust_points`.
- **Test:** a negative referral delta → 400 and the balance is unchanged.

### BE-9 · P2 · Referral validation: points are uncapped and can be credited twice, and a failed credit is swallowed (VERIFIED)
- **Evidence:** `apps/referral/views.py:188-207`: `points = int(request.data.get('points_reward', 100))` has no cap, and a non-integer value raises a 500. `ReferralLead.objects.get(pk=pk, status='registered')` takes no lock, then `lead.validate()` runs. The credit runs inside `try: ... except Exception: logger.warning(...)`.
- **Failure:** two concurrent validations both credit the referrer. If the loyalty credit fails, the lead stays `validated` and the referrer gets no points, while the API returns 200.
- **Fix:** run the view atomically with `select_for_update()` on the lead, cap `points_reward` with a setting, and return an error (rolling back) when the credit fails.
- **Test:** validate twice → one credit. `points_reward="x"` → 400.

### BE-10 · P2 · Incentive recalculation is a delete followed by an insert, with no transaction (VERIFIED)
- **Evidence:** `apps/incentives/engine.py:1140-1151`: `IncentiveTransaction.objects.filter(...).delete()` and then `bulk_create(...)` run outside any `transaction.atomic`. The finalization guard (l.788-806) is a check and not a lock.
- **Failure:** two "calculate" clicks, or a click overlapping the scheduler: run A deletes, run B deletes, A inserts, B inserts. The period then holds every transaction twice and payout totals double. If `bulk_create` crashes, the period is left with zero transactions.
- **Fix:** wrap the persist block in `transaction.atomic()` and serialize per program and period with `select_for_update()` on the `IncentiveProgram` row or a PostgreSQL advisory lock.
- **Test:** call `calculate` twice for the same period → the transaction count equals one run.

### BE-11 · P2 · Immutable audit records are deleted with their parent (VERIFIED)
- **Evidence:** `apps/vouchers/models.py:528`: `VoucherRedemption.voucher` is `on_delete=models.CASCADE`, and the record is documented as "Immutable once created". `VoucherViewSet` is a full `ModelViewSet` (`vouchers/views.py:101`), so DELETE is enabled behind the VOUCHERS matrix permission. Also `loyalty/models.py:225` (`PointTransaction.account`, CASCADE; documented "NEVER edit or delete") and `loyalty/models.py:460` (`SoftechPointsLog.customer`, CASCADE; documented "never updated or deleted").
- **Failure:** deleting a voucher removes its redemption history, discount amounts and documents. Deleting a customer erases the SOFTECH points-write audit trail.
- **Fix:** change these foreign keys to `on_delete=PROTECT` (a migration, needs owner approval) and disable `destroy` on `VoucherViewSet`; cancel already exists.
- **Test:** DELETE a voucher that has redemptions → 405/409, and the redemptions remain.

### BE-12 · P2 · The discount-authority check passes when the live read fails (VERIFIED; needs owner approval)
- **Evidence:** `apps/pos_orders/views.py:263-266`: `except Exception: disc_errs = []   # live-read failure must never block /ready`.
- **Failure:** with the writer ON and the branch read failing (timeout or schema hiccup), a discount above the user's SOFTECH authority goes through `/ready`, and the push does not re-check it. Rule 2 asks for financial accuracy that is deterministic.
- **Fix (owner decision):** fail closed for non-manager users (block with "تعذر التحقق من صلاحية الخصم"), or at least write an audit flag on the order.
- **Test:** mock `validate_discount_authority` to raise → 400/409 for a cashier.

### BE-13 · P2 · Loyalty points drop silently to zero when the rate lookup fails (VERIFIED; needs owner approval)
- **Evidence:** `apps/pos_orders/writer.py:1446-1464`: on `except Exception:` the code sets `_rate_by_item, _rep = {}, None`. Every slice then earns 0 (`_slice_points`), and the header carries `personnewbal=0.0` (l.1520-1522). The same pattern appears in `points.py:51-52`.
- **Failure:** a points-enrolled PIC customer buys while the `custdiscounts` read hiccups. The sale is posted with `vf4=0` and `personnewbal=0` and the customer permanently loses that sale's points. Nothing is logged.
- **Fix:** log the failure and either refuse the push or queue it for retry (owner choice). At minimum record `erp_error`/an audit flag so the points can be re-credited.
- **Test:** mock `DiscountAuthorityReader` to raise → push refused, or the order is flagged.

### BE-14 · P3 · Price-change approval: approve race, FAILED after the HQ write, and a leaked connection (VERIFIED)
- **Evidence:** `apps/discount_approvals/views.py:108-160` reads the status, then saves APPROVED with no lock. `services.py:122-143`: the UPDATE runs, and a readback mismatch then raises and marks the request FAILED, although HQ may already hold the new values. On an exception the connection is never closed (`conn.close()` is only on the success paths).
- **Failure:** a double approve sends two identical HQ UPDATEs (harmless values, but two audits). A request marked FAILED but actually applied can be "retried" later on top of a newer price, because FAILED is allowed to retry (l.116-118).
- **Fix:** claim the request with a conditional status update, close the connection in `finally`, and write a distinct "unknown — verify" status when the UPDATE ran but the readback failed.
- **Test:** two approvals → one execution.

### BE-15 · P3 · UTC date used as the business day (`timezone.now().date()`) (VERIFIED)
- **Evidence:** `USE_TZ=True` and `TIME_ZONE='Africa/Cairo'` (`config/settings.py:446-448`). `timezone.now()` is UTC, so `.date()` returns the UTC day. There are 21 sites, including:
  - `apps/pos_orders/writer.py:930` and `apps/invoices/writer.py:1319`: the stored `softech_docdate` is one day behind SOFTECH's `getdate()` for anything posted between 00:00 and 02:00/03:00 Cairo time.
  - `apps/vouchers/models.py:137`: a voucher stays valid 2-3 hours past `valid_until`.
  - `apps/vouchers/models.py:204`: the per-day limit compares `redeemed_at__date`, which is Cairo-local, with the UTC date.
  - `apps/loyalty/models.py:340`, `apps/batches/models.py:131,143`, `apps/batches/service.py:216,262,310`, `apps/batches/views.py:1048`: expiry and days-to-expiry.
  - `apps/finance/recon_engine.py:455`, `apps/tax_invoicing/eta_history.py:247`, `apps/procurement/engine.py:288`, `apps/hr/service.py:366`, `apps/commerce/views.py:110`, `apps/commerce/models.py:119`, `apps/discount_approvals/views.py:854`, `apps/sync/tasks.py:3107`, `apps/finance/management/commands/sync_ap_reconciliation.py:53`, `apps/notifications/management/commands/send_followup_reminders.py:69`.

  `date.today()` (133 sites) is fine here, because Django sets the process TZ on POSIX and the Windows host is on Cairo time.
- **Fix:** replace each with `timezone.localdate()`.
- **Test:** freeze time at 2026-11-15 23:30 UTC (= 01:30 Cairo on the 16th); a voucher with `valid_until=2026-11-15` → expired.

### BE-16 · P3 · Insurance cover-page category discounts are rounded as floats and do not match the Decimal totals (VERIFIED; needs owner approval)
- **Evidence:** `apps/insurance/invoice_builder.py:479-487`: `round(cover_local_before * local_disc_pct / 100, 2)` in float, which rounds half to even and inherits binary representation error. The claim totals use Decimal per prescription with `.quantize(Decimal('0.01'))` (`importer.py:1308-1310`), which has the default ROUND_HALF_EVEN mode.
- **Failure:** over typical amounts, about 5% of (base, pct) pairs come out 0.01 different from ROUND_HALF_UP (for example 0.15 × 10% → float gives 0.01, half-up gives 0.02). The three category rows on the printed cover can then miss the cover total discount by a few piasters. The rounding mode also differs from POS `pricing.py`, which uses ROUND_HALF_UP.
- **Fix:** compute the cover rows in Decimal, using the same mode as the claim totals. Which mode to use is an owner decision.
- **Test:** a cover-page fixture whose category rows add up to `final_total_discount` to the piaster.

### BE-17 · P3 · Purchase-invoice pricing uses floats and turns bad input into 0 (VERIFIED; the VAT issue is already known)
- **Evidence:** `apps/invoices/pricing.py:16-20`: `_f()` returns `0.0` on `TypeError`/`ValueError`, so an OCR value such as "12,5" silently becomes 0. When `unit_price` comes back as 0, the net is derived from the public price instead (l.39-40). All the arithmetic is float. Per project memory, `newcostprice = net` over-states cost on 14%-VAT items; that is already known and marked stop-and-confirm.
- **Fix:** raise on unparsable input. Moving to Decimal changes calculations, so it needs owner approval.

### BE-18 · P3 · PATCH is allowed on QUEUED and PUSH_FAILED orders without re-pricing (SUSPECTED)
- **Evidence:** `OrderDetailView.update` blocks only `is_locked` statuses, and QUEUED is not one of them. `push_order` re-prepares only DRAFT orders (`writer.py:803-804`). The frontend does not PATCH orders.
- **Failure:** an API client edits the lines of a queued order. The flush then posts the new lines with the old `doc_value` header. The readback in `_execute_write` may catch the mismatch; this was not confirmed.
- **Fix:** treat QUEUED as locked for PATCH, or reset the status to DRAFT on edit.

### BE-19 · P3 · Insurance manual-prescription sequence is computed outside the transaction (VERIFIED)
- **Evidence:** `apps/insurance/importer.py:1236` computes `next_seq = Max('sequence') + 1` before `with transaction.atomic()` at l.1238.
- **Failure:** two concurrent additions to the same claim get the same sequence, and the export ordering becomes ambiguous.
- **Fix:** lock the claim row (`select_for_update`) inside the atomic block before computing the next sequence.

### BE-20 · P3 · Reservation status change has no row lock (VERIFIED)
- **Evidence:** `apps/reservations/views.py:413-483` reads the status in memory, writes the log and chatter entries, then saves.
- **Failure:** a double click produces duplicate status logs, notifications and phone alerts. There is no stock effect.
- **Fix:** `select_for_update` plus a conditional status update.

### BE-21 · P3 · A forced incentive recalculation silently un-finalizes settlements (SUSPECTED)
- **Evidence:** `apps/incentives/engine.py:806` runs `locked.update(is_finalized=False, finalized_at=None, finalized_by=None)` and only writes a log line. No audit row was seen, against rule 8.
- **Fix:** write an audit record (who, why, before and after) and require a reason.

---

## Checked and found sound (not findings)
- **POS money:** `apps/pos_orders/pricing.py` is Decimal with ROUND_HALF_UP throughout. The push claim is an atomic conditional UPDATE and there is crash recovery through vf2 (`writer.py:850-879`). Create is idempotent on `client_token` with a unique constraint.
- **Points float floor** (`writer.py:1472`, `points.py:52`): brute-force check shows 0 mismatches against Decimal for integer quantities 1-10, prices 0.01-500.00 and rates 1-10%.
- **GL** (`apps/finance/gl/ledger.py`): `select_for_update` on the sequence, period and entry, and a unique `source_key` constraint.
- **Offers consumption** (`apps/offers/usage.py:64-80`): the Offer row is locked.
- **Gamification rewards:** the reward and player rows are locked.
- **Model fields:** no money stored in a model `FloatField`. All 29 purchasing FloatFields are weights and ratios.
- **Pagination:** `DEFAULT_PAGINATION_CLASS` is PageNumberPagination with 50 per page. The 12 opt-outs are small lookups, plus procurement and transits lists that are worth spot-checking.
- **Scheduler:** guards are enforced by `apps/tests/test_scheduler_locks.py`. A new or stale job, or a missing guard, fails CI. The remaining gaps are listed in its `KNOWN_GAPS`.
- **Swallowed exceptions** (`except Exception: pass/return []`): found 34 in pos_orders, 39 in finance, 31 in invoices and 26 in purchasing. Most are `conn.close()` or `SET ROWCOUNT 0` cleanup, or schema probes. The ones that change business numbers are BE-12 and BE-13 (plus `writer.py:612-615`, where the contract co-pay failure falls back to 100% credit; that fallback is documented).

## Comparison with existing docs

| ID | Status vs `docs/security/round2/SUMMARY.md` and `docs/architecture/09_TECHNICAL_DEBT_REPORT.md` |
|---|---|
| BE-1 | **New**. Round 2 tightened PATCH (Z-10a) but not DELETE. |
| BE-2, BE-3 | **New**. P-11 fixed the double push claim; the ready/push race was not covered. |
| BE-4 | **New** (the offers flag is OFF). |
| BE-5 | **New**. TD-M006 fixed item/branch eligibility; W-1 (OTP shown to staff) is separate and owner-held. |
| BE-6 to BE-9 | **New**. Round 2 fixed only the loyalty permission matrix. |
| BE-10 | **New**. TD-L004 "no tests for IncentiveEngine" is broader. |
| BE-11 | **New**. TD-H002-style FK hygiene is related but does not cover audit CASCADE. |
| BE-12, BE-13 | **New** (fail-open by design; the owner should decide). |
| BE-14 | **New**. |
| BE-15 | **New**. |
| BE-16 | **New**. The partial-pack and tarsia memories cover other insurance rounding. |
| BE-17 | VAT cost over-statement **already known** (memory: purchasing OCR column engine). The `_f()` swallow is **new**. |
| TD-H007 (`hmac.new`), voucher mark-used 500 (R7/V-1) | **Fixed**: `select_for_update(of=('self',))` is present. |
| TD-H003 pagination | **Mostly fixed** (default pagination is on). |
| M-1, M-2 offers safety and stacking | **Fixed** per SUMMARY; not re-tested here. |

## Low-risk fixes that are safe to make now (pure bug fixes; intended business outcomes do not change)
1. **BE-15:** replace `timezone.now().date()` with `timezone.localdate()` at `apps/pos_orders/writer.py:930`, `apps/invoices/writer.py:1319`, `apps/vouchers/models.py:137,204`, `apps/loyalty/models.py:340`, `apps/batches/models.py:131,143`, `apps/batches/service.py:216,262,310`, `apps/batches/views.py:1048`, `apps/finance/recon_engine.py:455`, `apps/discount_approvals/views.py:854`, and `apps/commerce/views.py:110` (and the rest of the list in BE-15).
2. **BE-8:** `apps/loyalty/views.py:141`: reject `delta < 0` in the referral lane.
3. **BE-6:** `apps/loyalty/views.py:378-391` and `apps/loyalty/models.py:418-428`: atomic block, `select_for_update()` on the request and the account, deduct before setting `approved`.
4. **BE-5:** `apps/vouchers/views.py:312`: lock the voucher row and re-check `is_exhausted` and status after the lock.
5. **BE-1:** `apps/pos_orders/views.py:158`: add `perform_destroy` that refuses anything other than DRAFT/READY without a `softech_docnumber`.
6. **BE-10:** `apps/incentives/engine.py:1140-1151`: wrap the delete and `bulk_create` in `transaction.atomic()` and lock the program row.
7. **BE-9:** `apps/referral/views.py:188-207`: atomic block, lock the lead, return 400 on a non-integer `points_reward`.
8. **BE-14:** `apps/discount_approvals/services.py:122-143`: close the connection in `finally`. `apps/discount_approvals/views.py:150-154`: claim the request with a conditional status UPDATE.
9. **BE-7:** `apps/loyalty/models.py:125-195`: row lock or `F()` for balance mutations.

These need owner approval, because they touch checkout or payment, change calculations, or need a migration: BE-2/3 (`prepare_order`), BE-4, BE-11 (PROTECT migration), BE-12, BE-13, BE-16, BE-17.
