# 11 — Bug fix register

Full audit, 2026-11-15, branch `claude/full-project-audit` (from `main` `56870174`). Merged with Wave 0 in
PR 147 (`851d34d9`); Wave 1 merged 2026-11-16 (PRs 150–154), see below.

Only **verified, low-risk** defects were fixed: each one restores the behaviour the code already intended,
changes no business calculation, writes nothing new to SOFTECH, and has a regression test in
`apps/tests/test_full_audit_fixes.py` (backend) or `frontend/src/utils/escapeHtml.test.js`. Every other
verified finding is listed in reports 03–07 and, where it needs the owner, in
[14_DECISION_REGISTER.md](14_DECISION_REGISTER.md).

## Fixed on the audit branch

| ID | Sev. | Defect | Reproduction (before) | Fix | Test | Commit (tests: `241d2772`) |
|---|---|---|---|---|---|---|
| BE-1 | P1 | A POS order already posted to SOFTECH could be deleted (only PATCH checked the lock) | `DELETE /api/pos-orders/<pushed id>/` → 204; docnumber + `client_token` lost, so a replayed create could post again | `OrderDetailView.destroy` refuses anything but draft/ready with 409 (`push_failed` and `queued` included: outcome unknown / claimable by the flush job). The UI never deletes orders | `PosOrderDeleteLockTests` (2) | `03036378` |
| SEC-2 | P1 | Stored XSS: portal-typed item names/notes written unescaped into the staff receipt print window | A reservation item named `<img src=x onerror=…>` runs script with the staff session when the receipt is printed | `utils/escapeHtml.js` (`escapeDeep`) applied to the data of `printCustomerReceipt`, `printReservationReceipt`, `printTransferReceipt`; templates unchanged | `escapeHtml.test.js` (4) | `26ae3f19` |
| SEC-3 | P2 | Chatter POST had no branch check (GET had one) | A branch pharmacist posts into another branch's reservation thread by changing the id | Shared `_chatter_branch_denied()` used by read and post | `ChatterPostBranchScopeTests` (2) | `c8e02832` |
| BE-5 | P2 | Single-use voucher redeemable twice with two OTPs verified at the same moment | Two concurrent `verify-otp` calls with different OTPs both read `times_used=0` | `verify_otp` locks the voucher row before the eligibility check | `VoucherVerifyLocksVoucherTests` (2) | `e1130689` |
| BE-6 | P2 | Loyalty redemption: status saved as approved before the deduction; double approve deducted twice | Approve with too few points → 400 but request stays `approved`; two approvals → balance −2× | Deduct first under an account lock, then mark approved, in one transaction; the view locks the request row | `LoyaltyRedemptionAndReferralTests` (2) | `c6aac4cf` |
| BE-8 | P2 | A negative referral adjustment **added** points (`add_points` takes `abs()`) | `POST …/adjust/ {points:-50, adjust_type:'referral'}` → +50 | Refused with 400 (deduction lane = owner decision D-14) | `LoyaltyRedemptionAndReferralTests` (1) | `c6aac4cf` |
| FE-6 | P2 | Call-quality score form never loaded the saved score (TanStack v5 ignores `useQuery` `onSuccess`); saving overwrote it with zeros | Open an already-scored call → all zeros → Save | Load the score with a `useEffect` on the query data | Manual reasoning + lint; no component test harness for this page | `8b11cd98` |
| S-10 | P2 | Ints above 2³¹−1 bound with `setInt` → coupon stocking fails on days 22–31 | `ddmmyyyy*100` = 2,211,202,600 on the 22nd | `CursorWrapper._execute` binds out-of-range ints with `setLong` | `SybaseLongParamBindingTests` (fake connection) | `2e2f1a36` |
| S-13 | P3 | `softech_docdate` saved as the UTC date (yesterday for posts 00:00–02:00 Cairo) | Push at 23:30 UTC → date of the previous Cairo day | `timezone.localdate()` in the POS and purchase-invoice writers (post-write bookkeeping only) | `PosPushDocdateIsCairoDateTests` | `1864def7` |
| PERF-5 | P2 | `purchasing/filter-options` DISTINCT widened by `Item.Meta.ordering` → ~one row per item per list (slow log max 309 s) | Families list query selects `catalog_item.name` | `.order_by()` before `.distinct()` in `_codelist` | `PurchasingFilterOptionsDistinctTests` | `7694b905` |

## Wave 0 (2026-11-15, same day, on the owner's "go ahead with Wave 0")

| ID | Sev. | What was done | Verification | Commit |
|---|---|---|---|---|
| SEC-1 | P0 | **Office key replaced** (operation, not code): both office `.env` copies (main checkout + `main-runtime`) backed up as `.env.bak-2026-11-15-prekey`, then new random `SECRET_KEY`, a Fernet `OMNI_CREDENTIALS_KEY` and a new `COUNSEL_PHONE_HASH_KEY` written (no channel credentials were stored — 4 empty accounts — and 0 counselling opt-outs existed, so nothing needed re-keying). Web, scheduler and AMI bridge restarted right after a `pos_orders_flush` completion | health `ok`; scheduler and bridge back; **a JWT signed with the old placeholder key now gets 401** | — |
| SEC-1 | P0 | Settings guard: DEBUG replaces a placeholder key with a throwaway key | `test_debug_never_signs_with_the_public_placeholder` | `eec5a978` |
| SEC-4 | P2 | `WEBHOOK_ALLOW_UNSIGNED` (default off) replaces DEBUG for unsigned webhooks; `DJANGO_ADMIN_ENABLED` defaults to off | `test_debug_alone_no_longer_accepts_unsigned`, `test_explicit_switch_accepts_unsigned`, `test_setting_defaults_to_off` | `eec5a978` |
| SEC-6 | P2 | Voucher-document and shelf-QR print windows escape their data (the incentives receipt copies React-rendered, already-escaped HTML — no change needed) | build + 131/131 Vitest | `48b60a03` |

## Wave 1 (2026-11-16, on the owner's "go ahead with Wave 1"; merged on "merge when green")

One PR per step, each merged by hand after all four CI checks were green on its final commit. **No change to
the SQL sent to SOFTECH** in any of them, except one more column in a read-only duplicate lookup (PR 151).
Common rule: when a write was *sent* but its reply was lost, the record is marked **outcome unknown** and is
never retried automatically; a person checks SOFTECH first. Errors before the send stay plain failures
(SOFTECH rolls back an uncommitted transaction).

| ID | Sev. | What was done | Test | PR (merge) |
|---|---|---|---|---|
| S-1, S-6 | P1/P2 | POS: an error at or after `commit()` marks the order `push_failed` + `outcome-unknown:`; such orders are never claimed by the push button, flush job, `flush_pos_orders` or «include failed». Re-push or cancel only with `confirmed_not_landed` (audited); cancel looks for the pending sale by `vf2` first. Live read-only check on branch 130: a settled sale's final `stktransm` row has an **empty `vf2`**, so after settlement the tag can't be found — hence a person, not a lookup | `OutcomeUnknownTests` (6) | 153 (`4634bf75`) |
| BE-2, BE-3 | P1/P2 | `prepare_order` is one transaction with the order row locked and status + docnumber re-checked; a refused prepare leaves lines and payments unchanged | `PrepareOrderLockTests` (2) | 153 |
| S-2 | P1 | A/P allocation writer (live): two PostgreSQL advisory locks (invoice, voucher; fixed order) around every live write, reverse and half-completion; a second concurrent write is refused before any SOFTECH connection. Dry runs take no lock | `OneWriterPerInvoiceTests` (4) | 150 (`a4b5544a`) |
| S-4 | P1 | Purchase-invoice writer (live): any error after the batch is sent → `timeout-unknown:` (before: only errors with "timeout" in the text, so a connection reset after commit could post a return twice) | `InvoiceOutcomeUnknownTests` | 151 (`676666a6`) |
| S-3 | P1 | After an unknown outcome, a purchase retries automatically only when its supplier number has digits; a purchase found by the same digits is adopted only when its total is within 2 %, else `duplicate-mismatch:` | `InvoiceOutcomeUnknownTests` | 151 |
| S-5 | P2 | ISR writer (live): an error after the INSERTs were sent → draft `failed` + `outcome-unknown:`; a new draft with the same lines on the same route is refused (`outcome_unknown_twin`) unless a written reason is given | `test_isr_guards.py` | 152 (`0c58faa1`) |
| S-14 | P3 | pos_cancel writer: an error at `commit()` keeps the rows claimed with `outcome-unknown:` instead of un-claiming them for a second insert | `test_pos_cancel_writer.py` | 152 |
| PERF-2 | P2 | Expression index `((invoice_date AT TIME ZONE 'Africa/Cairo')::date, doc_code)` on `customers_purchasehistory`, built `CONCURRENTLY` (= the SQL every `invoice_date__date` lookup compiles to). **Office, measured:** one week's sales sum 315 ms / 40,776 buffers (parallel seq scan) → **4.1 ms / 517 buffers** (bitmap index scan); index valid | migration rules | 154 (`91108713`) |
| PERF-1 | P1 | Monitoring alerts (transit critical/overdue/approaching-cancel, delivery SLA, branch connectivity) age out after 14 days in the nightly retention step (~681k of 727k rows) | `test_notification_routing.py` | 154 |
| FE-1 | P2 | Server honours `X-Idempotency-Key` on the six `/m` offline-queue POST endpoints (`IdempotentRequest`, kept 7 days); the queue records the user and replays only the signed-in user's items | `test_idempotency_middleware.py` (5), `offlineQueue.test.js` | 154 |
| PERF-3 | P1 | Opt-in capacity: `deploy/elrezeiky-web-extra@.service` (two more Daphne processes), commented nginx upstream lines, `release.sh` restarts enabled extras, runbook §13.6; read-only Locust plan + runbook §13.7. **Nothing changes on the VPS until the owner installs it** | — | 154 |

**Office after merge (2026-11-16):** runtime on `91108713`; migrations `config 0005` and `customers 0035`
applied (index valid); web, scheduler and AMI bridge restarted after a `pos_orders_flush` completion, one
scheduler.

**Wave 1 left open (not built, reason):**

| Item | Why |
|---|---|
| `INV<pk>` tag in `stktransm.vf2` for purchase invoices (rest of S-3) | Changes the posted document — needs a rollback probe first |
| A/P: a payment entered natively in SOFTECH at the same second as ours (rest of S-2) | Needs `HOLDLOCK` reads inside the SOFTECH transaction — rollback probe first |
| POS: a UI control for `confirmed_not_landed` | The API answers with a clear Arabic message; small follow-up before the POS writer is switched on |
| S-7 (reconcile old `push_failed` orders) | Outcome-unknown orders now wait for a person; a reconcile screen is a follow-up |
| Bell default to action items (rest of PERF-1) | UI behaviour change — owner choice (D-19) |
| Load test (step 1.7) and extra web processes on the VPS | Owner steps, runbook §13.6–§13.7 |

## Verified, not fixed here (reason)

| ID | Why not here |
|---|---|
| ~~S-1, S-2, S-3, S-5, S-6, BE-2/3~~ | Fixed in Wave 1 (above), except the parts listed as left open |
| BE-4, BE-12, BE-13, BE-16, FE-3 | Business rule / checkout (D-11, D-12, D-15, D-18) |
| BE-7, BE-10, BE-11, BE-21 | Touch earn/expire jobs or need a migration / rule (D-13, D-16, D-17) |
| ~~PERF-1, PERF-2, PERF-3~~ | Fixed / made opt-in in Wave 1 (above) |
| FE-4, FE-5, FE-7 | Mechanical but wide (140 + 21 + 82 sites) — Wave 2 batch, needs a browser check per screen |
| BE-15 (other 19 UTC-date sites) | Each changes a report/job day boundary; reviewed one by one in Wave 2 |
