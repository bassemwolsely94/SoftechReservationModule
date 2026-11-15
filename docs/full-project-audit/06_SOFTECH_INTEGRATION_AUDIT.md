# 06 — SOFTECH (Sybase ASE) integration audit

Worktree: `.claude/worktrees/full-audit` (branch `claude/full-project-audit`, at `56870174`). Read-only static audit,
2026-11-15. Nothing was connected to SOFTECH, no command or test was run. Line numbers refer to that worktree.

Method: read `config/sybase.py`, `config/writers.py`, the write manifest, then each writer end to end
(POS, invoices, reservation, pos_cancel, loyalty, pricing, ISR, A/P recon) and the sync lane
(`apps/sync/tasks.py` sales/stock, `reservations/erp_matcher.py`, `pos_orders/reconcile.py`). Findings were
formed first; only afterwards compared with `docs/security/round2/SUMMARY.md`, `R1_write_sites.md`,
`R5_R6.md` and `docs/architecture/POS_OFFLINE_RESILIENCE.md`.

---

## 1. Connection layer (`config/sybase.py`) — summary

| Topic | What the code does | Assessment |
|---|---|---|
| Driver | jConnect 3 via JPype, JVM start serialised by a lock (75–93) | OK |
| Pooling | none — every call opens a fresh connection (`get_sybase_connection` 562, `get_branch_connection` 590) | OK for safety; cost only |
| Connect retry | 3 attempts × `LOGIN_TIMEOUT` 15 s, 1.5 s back-off (528–559); N4 gate consulted once before | OK |
| Query timeout | `setQueryTimeout` 30 s default; re-armed to 600 s once the first result arrives (`_apply_fetch_timeout` 161) | OK |
| Write-batch timeout | 120 s, only for the two raw-batch writers (`apply_write_batch_timeout` 152; invoices + supplier mapping) | POS / ISR / AP commits have no bound on `commit()` (S-18) |
| Kill-switch | `SOFTECH_READ_ONLY` wraps the java connection in `_ReadOnlyJavaConnection` (allow-list on first keyword + deny-list of write words outside literals/comments; statements, result sets, metadata and `unwrap` cannot reach the raw connection) | Solid. `probe_connection` (634) bypasses the proxy but only runs `SELECT 1`. Startup refuses `WRITER_INSTANCE + SOFTECH_READ_ONLY` together (`writers.py` 132) |
| Single writer | every flag read through `writer_allowed()` = `WRITER_INSTANCE and flag` (`writers.py` 68) | Solid |
| Host choice | HQ = `SYBASE_HOST`; branch = `Branch.db_host` (or HQ when blank, `effective_db_host`); `SOFTECH_BRANCH_HOST_OVERRIDE` reroutes every branch (staging). `SoftechConnector` default profile `prod` uses `SOFTECH_PROD_HOST` when set, else `SYBASE_HOST` (1057–1081) | OK; `SoftechConnector` silently prefers `SOFTECH_PROD_HOST` over `SYBASE_HOST` — keep it unset on reader copies |
| Type mapping | numeric/decimal/money → **float** (`_convert_row` 920–924); dates via wall-clock getters, naive Cairo (749–789); prepared `int` → `setInt` (848) | S-10, S-16 |

---

## 2. Writer table

Legend — **Flag** is the switch read through `writer_allowed` (default False for all in `config/settings.py`,
guarded by `test_softech_write_flags_default_false`). **Commit-reply loss** = what happens when SOFTECH committed
but the client saw an error/timeout before PostgreSQL recorded it.

| # | file:function | Tables | Flag / dry-run default | Idempotency | Sybase txn | Commit-reply loss | Retry safe? | Audit | Trigger / permission |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `pos_orders/writer.py:push_order` → `_execute_write` (783, 1428) | stktransm5, stktrans5, branchesales5, companiesitems5, branchesalescc5 (+UPDATE stktrans5.item_partno) | POS_WRITER_ENABLED / dry-run unless `dry_run=False` | PG atomic claim → `pushing` (852); `vf2='POS<pk>'` adopt — **pending table only** (1409) | one chained txn, `begin`/`commit` on the wrapper; serial = `lastdocnumbers HOLDLOCK`+1, triggers bump | status → `push_failed`, docnumber not saved; retry re-reads `stktransm5` by vf2 — **misses it once the cashier settled** (S-1) | Only while the pending row exists | SoftechSalesOrder payload/readback + AuditLog `softech_pos_order_pushed` (view) | `POST pos-orders/<pk>/push/`, `flush/` (CanPushPosOrders, N4 `require_write`); job `pos_orders_flush` (queued only); cmds |
| 2 | `pos_orders/writer.py:_delete_pending_from_softech` (1671) | the 5 pending tables (DELETE) | POS_WRITER_ENABLED / live | header must still exist; cancelled returns early | one txn, verify 0 rows | re-run finds header gone → error, PG not cancelled | yes | status + AuditLog | `POST pos-orders/<pk>/cancel/` |
| 3 | `pos_orders/reservation.py:push_reservation` (133) | stktransm, stktrans (doccode 80) | POS_WRITER_ENABLED + `confirm=True` | **none** | one txn | nothing recorded anywhere | **no** | **none** | no production caller (tests only) — S-15 |
| 4 | `pos_orders/pos_cancel_writer.py:write_pos_cancel_batch` (78) via `writer._exec_insert` | pos_cancel | **POS_CANCEL_WRITE_ENABLED** (manifest lists POS_WRITER_ENABLED) / dry-run default | per-run claim token (S-3 fix) | one txn per branch | un-claim → rows re-inserted next run (S-14) | duplicates possible | logger + PG flags | job `pos_cancel_write` |
| 5 | `invoices/writer.py:push_final` → `_run_write_batch` (1193, 1052) | stktransm, stktrans, lastdocnumbers, personsdata, itemssuppliers | INVOICE_WRITER_ENABLED / dry-run | PG flip → `pushing` (1252); purchases: SOFTECH `cust_branch_code+doccode+docnumber2` (1270) — **skipped when docnumber2=0**; returns: PG status + remaining-qty validation | one unchained batch `begin tran … commit/rollback tran`, 120 s budget | purchase: retry allowed → **dup if docnumber2=0** (S-3); return: blocked only when error text looks like a timeout (S-4) | partly | `erp_payload/readback` + AuditLog `softech_invoice_pushed` | `POST invoices/<pk>/push|push-batch/` (finalize + admin/purchasing/supervisor); coupon push; replacement legs |
| 6 | `invoices/supplier_items.py:inject_mapping` | itemssuppliers | INVOICE_SUPPLIER_ITEM_WRITE_ENABLED / dry-run | no-op when set; guarded UPDATE | single batch, 120 s | absolute target → harmless | yes | AuditLog (timeout = "unknown") | `POST invoices/<pk>/lines/<lid>/learn/` |
| 7 | `loyalty/pic_bridge.py:adjust_softech_points` (235) | picpoints (trigger → localcustomers) | LOYALTY_SOFTECH_WRITE_ENABLED / live | view: `select_for_update` + identical-adjustment window (`LOYALTY_DUPLICATE_WINDOW_SECONDS`) | autocommit single INSERT (prepared) | logged as failed; a retry after the window adds again (additive) | no (window only) | SoftechPointsLog | `POST /api/loyalty/customers/<id>/adjust/` (LOYALTY_ADJUST_ROLES) |
| 8 | `discount_approvals/services.py:execute_price_change` (69) | items | PRICING_SOFTECH_WRITE_ENABLED / live | absolute SET; status pending/failed only, no row lock | autocommit UPDATE + readback | absolute → harmless; status `failed` though written | yes (absolute) | ItemPriceChangeRequest | `POST pricing-approvals/<pk>/approve/` (IsAdminRole) |
| 9 | `discount_approvals/alignment.py` (`_apply_classification_locked`, `create_new_tier`) | items / itemsorigin, custdiscpclassif | PRICING_SOFTECH_WRITE_ENABLED / live | lock 7_301_011 + skip unchanged; tier = code-exists (MAX+1 race) | per manifest | not traced end to end | per manifest | AuditLog | admin views |
| 10 | `discount_approvals/replication.py:_force_replication_locked` | items | REPLICATION_REPAIR_ENABLED / live | lock 7_301_012 + 10-min refusal | — | absolute (re-stamp) | yes | AuditLog every repair | admin + jobs if `auto_repair` |
| 11 | `finance/recon_writer.py:push_allocation` → `_live_write` (220, 448) | chequestrans, stktransm (docvaluepay/fatcurrentstatus) | AP_RECONCILE_WRITER_ENABLED / dry-run | existing chequestrans row → skip/top-up; **no lock, live reads outside the txn** (S-2) | `_atomic`: begin → INSERT + UPDATE + readbacks → commit; failed rollback is *proven* on a fresh connection (313–360) | rollback "proof" fails → `ReconWriteIntegrityError` STOP (correct) | yes (sequential); **not under concurrency** | ReconAuditEvent incl. failures | `POST allocations/<pk>/write-softech/`, `bulk-write-softech/` (admin check in view); cmds with `--actor` |
| 12 | `finance/recon_writer.py` `_reverse_steps`, `_top_up`, `fix_due_before`, `complete_half_*` | chequestrans, stktransm | AP_RECONCILE_WRITER_ENABLED | origin/audit/row checks | `_atomic` | as #11 | as #11 | ReconAuditEvent | admin views / shell |
| 13 | `purchasing/isr_writer.py:push_isr_record` → `_write_isr` (332, 246) | stockisrm, stockisr | ISR_WRITER_ENABLED / live once called | pg lock per draft + status re-read + PG fingerprint guard (PUSHED drafts only) | chained txn on raw java conn; serial `max(isrdocnumber) holdlock`+1 | exception escapes, draft stays `approved`, nothing marks "unknown"; retry writes a 2nd ISR (S-5) | no | IsrPush + AuditLog on success only | `POST isr/pushes/<pk>/push/` (can_supply_write); `generate_isr --auto-approve` |
| 14 | `purchasing/isr_writer.py:approve_isr` | stockisrm.israpp | ISR_WRITER_ENABLED / live | fixed target | autocommit | harmless | yes | AuditLog | cmd only |
| 15 | `purchasing/rate_writer.py:_apply_rate_updates`, `coverage_writer.py` (`_apply_coverage_updates`, `_apply_reset`) | stkbal (monthlyqty / maxnowqtymonths / maxnowqty) | SALES_RATE_WRITER_ENABLED / COVERAGE_WRITER_ENABLED, dry-run | only differing rows; absolute values | per manifest | absolute → harmless | yes | SalesRatePush / CoverageTopUp + AuditLog | `rates/pushes/<pk>/execute/`; job `coverage_topup` (+AUTO_TOPUP flag) |
| 16 | `purchasing/shortage_writer.py:_write_softech` | items flags | SHORTAGE_SOFTECH_WRITE_ENABLED / live | absolute desired state, read→write→verify | one connection | harmless | yes | AuditLog before→after | shortage views; cmd |
| 17 | `insurance/reprice_service.py` (`apply_reprice`, `_rebalance_locked`, `_revert_locked`, `_write_receipt`), `date_service.py` (3 sites), `backfill_bonusqty` | stktrans, stktransm, branchesales, motalba | INSURANCE_SOFTECH_WRITE_ENABLED / plan-preview first | plan previewed→applying atomic flip; locks 7301007/7301008; live re-check | per manifest | PG record before SOFTECH commit (P-15) | per manifest | SoftechWritePlan / Run / Edit + InsuranceAuditEvent | insurance edit + `softech_guard` |
| 18 | `offers/channel_a.py:_write_posdiscp`, `channel_b.py:_insert_specialoffer` | items.posdiscp / specialoffers(+items) | POS_OFFERS_POSDISCP / _PROMO_WRITE_ENABLED, dry-run | mirror-differs / identical-offer reuse + lock 7301010 | one txn (b) | not traced | per manifest | AuditLog | admin |
| 19 | `customers/branch_copy.py`, `merge_write.py`, `points_removal.py` | localcustomers, picpoints | 3 CUSTOMER_* / POINTS_* flags, dry-run | optimistic WHERE, vf1 tag, locks 7301005/7301009 | per manifest | not traced | per manifest | model + AuditLog | CLI `--commit` only |
| 20 | `personal/writeback.py:_write_and_verify` | stktransm, cheques (comments) | PERSONAL_COMMENT_WRITE_ENABLED / live | absolute SET + ownership re-read | — | harmless | yes | DocumentCommentEdit | `can_edit_erp_comments` |
| 21 | probes/rehearsals (`diag_*`, `investigate_*`, `probe_*`, `test_replication_cycle`, `test_sybase_vps --write-test`, `probe_order`, `probe_cancel`, `probe_reservation`) | various | SOFTECH_PROBES_ENABLED (`require_probes`) | rollback or RowGuards restore | rehearsal | — | — | stdout | CLI |

**Writers missing from the manifest:** none found. The AST scanner (`apps/tests/security/static_scan.py` 417–483)
caught every DML string I located, including `reservation.py` and `pos_cancel_writer.py` (both delegate to the
registered `pos_orders/writer.py::_exec_insert`). Gap in the scanner itself: it only flags modules that import
`config.sybase` (or name SOFTECHDB); a helper that receives a `conn` argument and builds DML in a module with no
such import would be missed. Manifest inaccuracies: S-17.

`tax_invoicing` writes nothing to SOFTECH (reads + ETA API only) — not a SOFTECH writer.

---

## 3. Findings

### S-1 · P1 · POS crash-recovery looks for the vf2 tag only in the pending table — a retry after settlement creates a second sale
- **Evidence:** `apps/pos_orders/writer.py:1420` — `"SELECT docnumber FROM stktransm5 WHERE branchcode=? AND doccode=? AND vf2=?"`;
  `push_order` 891–921: an exception after `conn.commit()` (reply lost, `setAutoCommit(True)` failing on a dropped
  link) sets `push_failed` with no `softech_docnumber`; `push_failed` is re-claimable (854–856) via
  `POST …/push/` or `flush_now(include_failed)` (`views.py:1251`).
- **Why it matters:** the pending row is moved out of `stktransm5` when the cashier finalises it. If the commit
  landed, the order sits on the cashier screen, gets settled, and a later retry of the `push_failed` order finds
  no vf2 row, allocates a new serial and writes a second pending sale for the same basket — a double sale /
  double stock deduction once the cashier settles it again (Rule 3). `reconcile.py:72` only looks at `pushed`
  orders, so the landed-but-`push_failed` order is never noticed automatically.
- **Status:** VERIFIED (code path). Whether finalisation keeps `vf2` on `stktransm` is unverified (live).
- **Fix:** on any non-connect exception after `begin()`, mark `push_unknown` (not `push_failed`) and refuse a
  re-push until a read of `stktransm5` **and** the final tables (`stktransm` doccode 115 by vf2, or
  `branchesales.ref_docnumber`) proves nothing landed; extend `_pending_docnumber_by_vf2` to the final tables.
- **Test:** fake connection whose `commit()` raises `JZ0T3` after recording rows; then simulate settlement
  (move rows to final tables); call `push_order` again → must not insert.

### S-2 · P1 · A/P allocation writer has no lock: concurrent writes on one invoice lose the header update or double the link
- **Evidence:** `apps/finance/recon_writer.py:468–503` idempotency check and live `docvaluepay` read happen
  **before** `_atomic` begins (545) and without HOLDLOCK; 534–536 writes an absolute
  `docvaluepay={new_paid}` computed from that earlier read. Callers take no lock: `recon_views.py:641–645`
  (single), `:756–758` (bulk), `push_ap_allocations_bulk.py:94–100` (no `select_for_update`, no `pg_lock`).
- **Why it matters:** two admins (or the bulk endpoint and a single click) writing two allocations to the same
  invoice both read `live_paid=X` and the second UPDATE overwrites the first → header `docvaluepay` short by one
  allocation while both `chequestrans` rows exist (supplier shows unpaid balance that was paid). The same
  allocation clicked twice concurrently passes the "row exists" check in both → two `chequestrans` rows unless
  SOFTECH has a unique index (unknown). The writer is LIVE in the office per project memory.
- **Status:** VERIFIED (code); reachability needs two concurrent requests; unique-index protection SUSPECTED absent.
- **Fix:** `pg_lock` per SOFTECH invoice key (and per allocation) around `push_allocation`/`reverse_allocation`/
  `_top_up`; move the live reads inside the transaction with `HOLDLOCK`; write `docvaluepay = docvaluepay + amount`
  with a WHERE on the expected old value.
- **Test:** two threads with a shared fake SOFTECH store writing allocations A and B on one invoice → final
  `docvaluepay` must equal A+B (currently A or B).

### S-3 · P1 · Purchase idempotency relies on a digits-only `docnumber2`; non-numeric supplier numbers have no guard, and colliding digits adopt the wrong document
- **Evidence:** `apps/invoices/writer.py:126–130` `_docnumber2` returns 0 for a non-numeric number;
  1269–1280 duplicate check runs only `if dn2 and doc_kind == 'purchase'`; 1207–1212 a timeout blocks re-push only
  for non-purchases ("a purchase is safe to retry"); header (661–695) carries no `vf2` — `softech_token`
  (54–56, `INV<pk>`) is defined but never written.
- **Why it matters:** (a) a purchase whose supplier number has no digits (or OCR left it empty on a
  non-paper invoice) that times out after commit is re-posted on retry → duplicate purchase: stock and supplier
  balance doubled. (b) Different printed numbers that reduce to the same digits (`A-123` / `123/…`) for one
  supplier make the second invoice "idempotently" adopt the first one's docnumber and flip to `finalized`
  without being posted — a silently missing purchase.
- **Status:** VERIFIED.
- **Fix:** write `vf2='INV<pk>'` (or another free column) in the header and check it first; treat
  `docnumber2=0` purchases like returns after a timeout (`timeout-unknown` → force only); on a docnumber2 hit,
  compare totals/items (`_score_candidate` already exists) before adopting.
- **Test:** purchase with `invoice_number='ABC'`, batch raises timeout after "commit" → second `push_final`
  must refuse; two invoices `A-123`, `B-123` → second must not become finalized with the first's docnumber.

### S-4 · P2 · Invoice "outcome unknown" detection depends on the error text containing "timeout"
- **Evidence:** `apps/invoices/writer.py:1300–1308` uses `config.sybase.is_timeout_error` (156–158: `jz0t3`,
  `timed out`, `timeout`). A link reset during result streaming (`JZ006 … Connection reset`, `socket closed`)
  after `commit tran` ran is recorded as plain `push_failed`.
- **Why it matters:** for a supplier **return** the "refuse until checked" guard (1207) does not engage; the
  remaining-quantity validation (`validations.py:249–257`) only stops it when the earlier return exhausted the
  quantity → a partial return can post twice.
- **Status:** VERIFIED (code); error strings depend on the driver.
- **Fix:** once the batch statement was sent (`conn is not None` and execution started), any exception =
  outcome unknown; same for `pos_orders` and ISR.
- **Test:** batch raises `"JZ006: Caught IOException: Connection reset"` → `erp_error` must start with `timeout-unknown:`.

### S-5 · P2 · ISR push: an exception after the commit leaves the draft `approved` with nothing recorded; retry writes a second approved ISR
- **Evidence:** `apps/purchasing/isr_writer.py:287–300` (`jconn.commit()` failure → rollback → raise);
  `_push_isr_record` 384–402 never reaches the status update; guard `isr_guards.check_push` compares only with
  PUSHED drafts in PG (`isr_guards.py:174–181`); no tag in SOFTECH to adopt.
- **Why it matters:** a second `israpp=1` supply request on the same route → the branch/HQ can dispense twice.
- **Status:** VERIFIED.
- **Fix:** set `pushing`/`unknown` before writing; on retry look up `stockisrm` by route + date + line
  fingerprint (or stamp a draft id into a free header column) before allocating a new serial.
- **Test:** fake conn whose `commit()` raises → draft must end `unknown`, and a second push must refuse.

### S-6 · P2 · Cancelling a POS order whose write landed but whose number was not saved leaves the pending sale in SOFTECH
- **Evidence:** `apps/pos_orders/writer.py:1783–1797` — `was_pushed` needs `softech_docnumber`; in the S-1 case
  (and when `order.save()` at 936 fails after commit, leaving `pushing` with no number) the order is marked
  `cancelled` in PG only.
- **Why it matters:** the cashier can still settle a sale our system shows as cancelled (stock/points/cash leave
  SOFTECH while the order ledger says nothing happened).
- **Status:** VERIFIED.
- **Fix:** before cancelling a `push_failed`/`pushing` order, search `stktransm5` by vf2 and delete/adopt.
- **Test:** order `push_failed`, no docnumber, fake branch has a vf2 row → cancel must delete it or refuse.

### S-7 · P2 · POS settlement reconcile matches on unverified heuristics
- **Evidence:** `apps/pos_orders/reconcile.py:44–62` ("Both heuristics to be confirmed on the test instance");
  returns match **any** doccode-30 document whose `r_docnumber` = the original invoice (no doccode/date/our
  pending link), so an older native return of the same invoice marks our return `settled`.
- **Why it matters:** wrong `settled` state blocks cancel (`cancel_order` 1778) and hides leakage.
- **Status:** SUSPECTED (needs live data).
- **Fix:** match returns on our pending docnumber/vf2 or on line set + date; add `r_doccode='115'`.
- **Test:** reader returning an older return for the same original → order must stay `pushed` + `needs_review`.

### S-8 · P2 · Bare-docnumber lookups in the reservation and transfer matchers
- **Evidence:** `apps/reservations/erp_matcher.py:278–280` (any branch), `:296–301` (pass 3: any branch, **any
  doccode**), lines via `QUERY_STKTRANS_LINES_ANY`; `apps/sync/sybase_queries.py:432, 441, 454, 481, 890`
  (`WHERE sm.docnumber = ?` / `st.docnumber = ?` with no branch).
- **Why it matters:** docnumbers are per (branch, doctype); a reservation can be confirmed "✅ matched" against
  another branch's sale or a purchase that shares the number (only a text note is added, 169–173), and lines
  from several documents are merged.
- **Status:** VERIFIED (code).
- **Fix:** drop passes 2/3 or require branch + doccode + date window, and never report `matched` when
  `branch_matched` is False.
- **Test:** fake SOFTECH with doc 500 at branches 130 and 150 → matching for 130 must not use 150's lines.

### S-9 · P2 · `sync_sales` can overwrite an invoice with a partial one when its lines straddle a 1000-invoice batch
- **Evidence:** `apps/sync/tasks.py:1449–1456` groups by `(personcode, branchcode, doccode, docnumber, docdate)`;
  1541 merges same `softech_invoice_id` only inside one batch; 1572–1598 upserts `total_amount` and deletes all
  lines of that id before inserting the batch's lines.
- **Why it matters:** an invoice whose rows carry two personcodes (the code comments say this happens) and land
  in two batches ends with the second group's total and lines only — revenue/COGS under-counted until the next run
  happens to order them differently.
- **Status:** SUSPECTED (needs data with multi-personcode invoices).
- **Fix:** group by `softech_invoice_id` before batching.
- **Test:** 1000 single invoices + one invoice split across personcodes at the boundary → mirror total equals the sum.

### S-10 · P2 · Python ints above 2^31−1 are bound with `setInt` — coupon pushes fail on days 22–31
- **Evidence:** `config/sybase.py:848–849`; `apps/vouchers/coupon_push.py:163–167` binds
  `lo = ddmmyyyy*100` (e.g. 22112026×100 = 2,211,202,600) as a parameter.
- **Why it matters:** JPype refuses the conversion → coupon stocking (`assign_docnumber2`) fails on the 22nd–31st of
  every month. Safe failure (no write), but the invoices writer already hit the same bug (comment 1273–1274).
- **Status:** VERIFIED (code); JPype overflow behaviour not exercised here.
- **Fix:** in `CursorWrapper._execute` use `setLong` (or `setBigDecimal`) when the int exceeds the int range.
- **Test:** `CursorWrapper` with a fake prepared statement and param 3_000_000_000 → `setLong` called.

### S-11 · P2 · Approved price change writes derived prices from the PG mirror and overwrites SOFTECH blindly
- **Evidence:** `apps/discount_approvals/services.py:59–64` derives `unit_price` / `pack_price_tax` from
  `item.pack_qty` / `item.sale_tax_pct` (mirror); 112 UPDATE has no expected-old-value condition.
- **Why it matters:** a stale mirror (pack size or VAT changed in SOFTECH since the last sync) writes a wrong
  unit/taxed price chain-wide via SSB replication; a concurrent manual SOFTECH edit is silently overwritten.
- **Status:** VERIFIED.
- **Fix:** read `packqty`/`itemsalestaxp` and the current price from HQ on the write connection; refuse if the
  current value differs from the request's recorded "old" value.
- **Test:** mirror pack_qty 10, SOFTECH 20 → write must refuse or use 20.

### S-12 · P2 · POS points: a failed discount-authority read silently writes 0 points; points use float floor
- **Evidence:** `apps/pos_orders/writer.py:1464–1465` `except Exception: _rate_by_item, _rep = {}, None` → every
  slice 0 points; `_slice_points` 1468–1472 `math.floor(float(q)*float(unit)*rate/100)`.
- **Why it matters:** a customer silently earns no points on a sale (SOFTECH recomputes `personnewbal = Σ vf4`
  at settlement); float products such as 1.15×100 can floor one point low vs SOFTECH.
- **Status:** VERIFIED.
- **Fix:** fail the push (or `push_failed` with a reason) when the rate read fails for a points customer; use Decimal.
- **Test:** authority reader raising → push must not commit; Decimal case where float floors low.

### S-13 · P3 · `softech_docdate` is the UTC date
- **Evidence:** `apps/pos_orders/writer.py:930`, `apps/invoices/writer.py:1319` `timezone.now().date()` with
  `USE_TZ=True`, `TIME_ZONE='Africa/Cairo'` (`config/settings.py:446–448`); SOFTECH stamps `getdate()` (Cairo).
- **Why it matters:** writes between 00:00 and 02:00/03:00 Cairo (the "off-peak" window) record yesterday;
  used by coupon legs (`coupon_push.py:306`) and replacement `purchase_date` (`replacement/legs.py:460–464`).
- **Status:** VERIFIED. **Fix:** `timezone.localdate()` or read `docdate` back. **Test:** freeze time at 23:30 UTC.

### S-14 · P3 · `pos_cancel` rows can be inserted twice after a lost commit reply
- **Evidence:** `apps/pos_orders/pos_cancel_writer.py:147–158` — exception after `commit()` un-claims; next run re-inserts.
  Comment 127 says "a crash can only under-post".
- **Why it matters:** duplicated lost-sale/cashier-audit rows. **Status:** VERIFIED.
- **Fix:** on a commit-phase error keep the claim and mark `unknown`. **Test:** fake commit raising → events stay claimed.

### S-15 · P3 · `push_reservation` commits stock-affecting rows with no idempotency or audit
- **Evidence:** `apps/pos_orders/reservation.py:133–156`; no production caller.
- **Why it matters:** wiring it later as-is gives a double-post path. **Status:** VERIFIED.
- **Fix:** delete it, or add claim + tag + audit before any caller. **Test:** static guard that it has no caller / requires a claim.

### S-16 · P3 · All SOFTECH numeric/decimal/money values are read as float
- **Evidence:** `config/sybase.py:920–924`. Sync converts back with `Decimal(str(float))` (`tasks.py:102–106`),
  writers re-render with `str(float(val))` (`pos_orders/writer.py:1010`, `invoices/writer.py:625`).
- **Why it matters:** exact for today's magnitudes (<15 significant digits), but every money comparison is
  float-based; large numerics would lose digits. **Status:** VERIFIED.
- **Fix:** return `Decimal(str(BigDecimal))` for numeric/decimal/money. **Test:** `_convert_row` on a BigDecimal `12345678901234.5678`.

### S-17 · P3 · Manifest inaccuracies
- `pos_orders/writer.py::_exec_insert` lists flag `POS_WRITER_ENABLED`; the pos_cancel caller is gated by
  `POS_CANCEL_WRITE_ENABLED` (`pos_cancel_writer.py:42–43`).
- `invoices/writer.py::softech_token` (`INV<pk>`, "stashed in stktransm.vf2") is never written — readers of the
  code assume a guard that does not exist (see S-3).
- `loyalty/pic_bridge.py:285–288` leaks the connection when the INSERT raises (no `finally`).
- **Status:** VERIFIED.

### S-18 · P3 · No bound on `commit()` / non-batch writes on a dead link
- **Evidence:** POS (`writer.py:880–890`), ISR (`isr_writer.py:260–288`), A/P (`recon_writer.py:322–325`) use
  per-statement 30 s timeouts only; `commit()` is a connection call with no socket timeout.
- **Why it matters:** a half-open TCP link can hold the request (order stuck `pushing`, scheduler job blocked).
- **Status:** SUSPECTED (driver behaviour). **Fix:** jConnect `SESSION_TIMEOUT`/socket timeout on write
  connections, or send `commit tran` as a timed statement.

### S-19 · P3 · Sync error handling and mirror gaps
- `tasks.py:1564–1565` per-invoice build errors are logged and skipped; 1596–1622 line delete + recreate is not
  in `transaction.atomic` (crash leaves headers without lines); invoices deleted in SOFTECH are never removed
  from the mirror. 138 `except Exception:` blocks in `tasks.py` (most are job wrappers that log and continue).
- **Status:** VERIFIED. **Fix:** wrap each batch in `atomic`; count and surface skipped invoices in `SyncLog`.

### S-20 · P3 · Special stores (110/102/105/103) are mirrored and excluded per consumer
- **Evidence:** `QUERY_STOCK` (`apps/sync/sybase_queries.py:164–168`) takes every store; exclusion logic is
  scattered over 14 modules (`stockcount/engine.py`, `purchasing/engine.py`, `supply/position.py`, …).
- **Why it matters:** a new stock consumer that forgets the filter counts closed store 110 / expired 102 stock.
- **Status:** SUSPECTED. **Fix:** one `store_roles` helper used by a default `ItemStock` manager.

---

## 4. Comparison with existing docs

| Finding | Status vs docs |
|---|---|
| S-1 vf2 only in pending table | **new** — `POS_OFFLINE_RESILIENCE.md` §Idempotency claims the vf2 guard covers the commit-reply window; it does not after settlement |
| S-2 A/P concurrency | **new** — R1 lists the guard as "existing chequestrans row guard"; no doc mentions concurrent writers |
| S-3 docnumber2 = 0 / digit collisions / unwritten INV tag | **new** — R5_R6 S-2 says "a purchase is safe to retry (SOFTECH's supplier + invoice-number check finds it)"; true only for numeric numbers |
| S-4 timeout detection by text | **new** (refines the already-fixed R5_R6 S-2) |
| S-5 ISR commit-unknown | **new**; R1 follow-up 5 only covers `approve_isr` re-stamping |
| S-6 cancel of landed-but-unsaved order | **new** |
| S-7 reconcile heuristics | **already known in code comment** ("to be confirmed on the test instance"), not tracked in round-2 docs |
| S-8 bare docnumber | **already-known rule** (memory + `product-review/03` "never join on a bare docnumber") — these specific sites are **new** |
| S-9 sync_sales batch split | **new** |
| S-10 setInt overflow | **partly known** — fixed in `invoices/writer.py` only (comment 1273); coupon path **new** |
| S-11 price change from mirror / no old-value check | **already known** as "no row lock" weak guard (R1 follow-up 5); the stale-mirror derivation is **new** |
| S-12 points swallow / float | **new** |
| S-13 UTC docdate | **new** |
| S-14 pos_cancel duplicate on lost reply | **new** (R5_R6 S-3 fixed the two-scheduler case only) |
| S-15 push_reservation | **new** |
| S-16 float reads | **new** |
| S-17 manifest | **new** |
| S-18 commit timeout | **partly known** (R5_R6 S-2 covers raw batches only) |
| S-19 / S-20 | **new** |
| Loyalty additive write after the window | **already known** (R1 / manifest: "function itself additive", D5 accepted) |
| Single-scheduler double write, raw batch timeout, pos_cancel two-process claim | **already fixed** (R5_R6 S-2, S-3; SUMMARY "single-scheduler lock") |

---

## 5. What I could not verify (needs a live SOFTECH or test instance)

- Whether cashier finalisation keeps `vf2` on `stktransm` (S-1 fix design) and how fast a pending order is settled.
- Whether `chequestrans` has a unique index on (cheqsno, cheqbranchcode, invoice key) (S-2 duplicate half).
- jConnect's exact error text on a reset after `commit tran` (S-4) and whether `commit()` can block indefinitely (S-18).
- JPype's runtime behaviour for `setInt(3_000_000_000)` (S-10) — expected OverflowError, not executed.
- The reconcile heuristics `branchesales.ref_docnumber` / `r_docnumber` (S-7).
- Whether multi-personcode invoices exist in volume (S-9).
- Insurance reprice/date writers, alignment, offers and customer CLI writers were checked against the manifest
  and call sites only, not traced line by line.
