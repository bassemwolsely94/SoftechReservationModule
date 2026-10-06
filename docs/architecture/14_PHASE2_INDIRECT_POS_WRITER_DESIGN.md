# 14 — Phase 2 Design: Indirect-POS Pending-Order Writer

**Status:** DESIGN ONLY (no code, no migrations, no DB writes). Build gated on a **test SOFTECH instance**.
**Source of truth for behavior:** [SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md](SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md) (§6a–§6i, fully reverse-engineered & empirically validated).
**Models the existing controlled-writeback pattern:** `apps/discount_approvals/replication.py` + `services.py`, `apps/loyalty/pic_bridge.py` (INSERT + verify-readback), and the read-back reconciler `apps/delivery/management/commands/sync_crm_orders.py`.

---

## 1. Goal & scope

Let our extended system **create pending sales orders for any channel** (cash / home-delivery / contract /
…) and **send them to a branch cashier**, byte-for-byte as the native SOFTECH Indirect-POS screen does —
allocating the exact `م صرف` serial and writing the same three tables — while storing **richer data on
our side** (referral doctor, prescription image, originating call/customer, sales channel, audit).

**In scope (our write surface — the PENDING side only):**
- `stktransm5` (header) + `stktrans5` (lines) + `branchesales5` (payment tenders) [+ optional `stktransmcomm5`/`stktransmclassif5`]
- doccode **115** (sale) and **30** (return), at the **target branch DB**, using the **`'000'` / ver_branch=0** counters

**Explicitly OUT of scope (SOFTECH owns it — fires on the cashier's settlement):**
final `stktransm`/`stktrans`/`branchesales`, `stkbal` stock deduction, points (`picpoints`), accounting,
e-invoice, deletion of the pending rows. We never write those, never compute final serials, never touch points.

---

## 2. Where it lives

New app **`apps/pos_orders`** (keeps the SOFTECH-writing concern isolated, like `discount_approvals`).
Depends on: `catalog` (Item), `customers` (Customer), `branches` (Branch + `db_host`), `callcenter`
(CallLog/CallItem), `referral` (doctors), `users` (StaffProfile). Reuses `config.sybase`.

```
apps/pos_orders/
  models.py        # SoftechSalesOrder, ...Line, ...Payment  (PG mirror + our extras + audit)
  pricing.py       # pure functions: line/header computation (the §6d formulas)
  writer.py        # transactional writer (serial alloc + INSERTs + verify-readback)  ← the core
  reconcile.py     # read-back: detect cashier settlement, sync status (sync_crm_orders pattern)
  serializers.py / views.py / urls.py
  management/commands/reconcile_pos_orders.py    # scheduled status sync
  migrations/
```

---

## 3. PostgreSQL data model (mirror + extras + audit)

Three tables mirroring what we push, plus our value-add fields and an immutable execution audit. **PG is
the system of record for *our* metadata; SOFTECH remains authoritative for the order once pushed.**

### 3.1 `SoftechSalesOrder` (header)
```
# identity / lifecycle
status            CharField  draft|ready|pushing|pushed|push_failed|settled|cancelled  (db_index)
channel           CharField  cash|delivery|contract|insurance|employee|vip|permanent   (→ ptclassifcode)
doc_kind          CharField  sale|return                                                (→ doccode 115/30)

# target
branch            FK branches.Branch        # determines the branch DB (db_host) we write to
softech_branchcode  CharField               # e.g. '130' (= storecode here)
store_code        CharField                  # storecode on the rows

# customer
customer          FK customers.Customer (null)   # our record
softech_pic       CharField                      # phcode written to SOFTECH (e.g. '130HD9668')
cust_branch_code  CharField                      # personcode used on lines (from localcustomers)

# SOFTECH refs (filled by the writer / reconciler)
softech_docnumber       DecimalField null   # the م صرف pending serial we allocated ('000'.lastdocnumberout_cust)
softech_docdate         DateField null
softech_final_docnumber DecimalField null   # final invoice # (read back after cashier settles, ver_branch=1)
return_of_invoice       DecimalField null   # for returns: original invoice → r_docnumber / ref_docnumber

# money (computed by pricing.py, mirrors the header)
doc_value         Decimal   # net payable (Σ line transprice_total)   → docvalue
doc_value_gross   Decimal   # pre-discount list (Σ itemsaleprice·qty) → docvalue1
doc_value_cogs    Decimal   # Σ newcostprice·qty                      → docvalue2
doc_value_tax     Decimal   # Σ itemsalestax                          → docvalue3
doc_value_pay     Decimal   # Σ non-credit tenders                    → docvaluepay
patient_payment   Decimal   # cash down-payment on credit (0 for pure cash) → patientpayment

# OUR EXTRAS (not in SOFTECH header, or richer than it)
referral_doctor   FK referral.<Doctor> (null)   # also mapped to stktransm5.refdoctorcode
prescription_image ImageField (null)            # reuse callcenter pattern; SOFTECH has no field → PG only
source_call       FK callcenter.CallLog (null)  # originating call
source_call_item  FK callcenter.CallItem (null)
notes             TextField

# people
created_by        FK users.StaffProfile
seller_usercode   CharField   # → usercode on rows
cashier_usercode  CharField   # → cashiercode (default = seller until cashier settles)

# immutable execution audit (mirrors ItemPriceChangeRequest)
erp_executed_at   DateTimeField null
erp_payload       JSONField    # exact column→value map we sent (header+lines+payments)
erp_readback      JSONField    # what we read back immediately after insert
erp_error         TextField
created_at / updated_at
```

### 3.2 `SoftechSalesOrderLine`
```
order        FK SoftechSalesOrder (related_name='lines')
item         FK catalog.Item
softech_itemcode CharField
qty          Decimal                  → transqty
item_sale_price  Decimal              → itemsaleprice  (copied from items, per branch)
cust_discp   Decimal (default 0)      → custdiscp  (effective discount %; INPUT)
trans_price  Decimal (computed)       → transprice = round(item_sale_price*(1-cust_discp/100),2)
trans_price_total Decimal (computed)  → transprice_total = trans_price*qty
item_sale_tax     Decimal (computed)  → itemsalestax
item_sale_price_tax Decimal (computed)→ itemsaleprice_tax (from items)
new_cost_price    Decimal             → newcostprice (READ from stkbal.nowcostprice at push time)
item_expiry  DateField null           → itemexpirydate
return_of_invoice DecimalField null   → r_docnumber (returns only)
```

### 3.3 `SoftechSalesOrderPayment`
```
order        FK SoftechSalesOrder (related_name='payments')
pay_type     CharField cash|credit|card   → paymenttype 30|10|40
amount       Decimal                      → paymentvalue
softech_paymentsno DecimalField null      # allocated from '000'.paymentsno at push
card_brand   tinyint null                 → creditcardtype (cards)
cheque_date  DateField null               → cheqdate
ref_invoice  DecimalField null            → ref_docnumber (= order docnumber, or original invoice for returns)
```

> **Immutability:** once `status='pushed'`, the order/lines/payments are read-only in our API (like
> `VoucherRedemption`/`IncentiveTransaction`). Corrections are made by pushing a **return** (doc_kind=return),
> never by editing. Enforce in `save()` + serializer.

---

## 4. Connector change — real Sybase transactions (the one required infra change)

`config/sybase.py` currently has **no-op** `begin_transaction/commit/rollback` (read-only assumption). Add a
**real, opt-in** transactional path used ONLY by the writer (reads stay unchanged):

```python
class SoftechConnector:
    def begin(self):    self._conn._conn.setAutoCommit(False)
    def commit(self):   self._conn._conn.commit();   self._conn._conn.setAutoCommit(True)
    def rollback(self): self._conn._conn.rollback();  self._conn._conn.setAutoCommit(True)
    # context manager: `with conn.transaction(): ...`  → commit on success, rollback on exception
```
- Default remains autocommit + read-only; the transactional API is explicit and only the writer calls it.
- Add an `execute(sql, params)` (non-SELECT) helper on the connector that returns affected-rows (the cursor
  wrapper already supports `stmt.execute()`; expose it cleanly for INSERT/UPDATE).
- Writer connects to the **branch DB** via `get_branch_connection(branch.db_host, branch.db_port, branch.db_name)`.

---

## 5. Pricing module (`pricing.py`) — pure functions, the §6d formulas

No DB writes; deterministic; unit-testable in PG-only tests.
```
compute_line(item_sale_price, item_sale_price_tax, sale_tax_pct, qty, cust_discp,
             new_cost_price) -> dict(trans_price, trans_price_total, item_sale_tax, ...)
    trans_price       = round(item_sale_price * (1 - cust_discp/100), 2)
    trans_price_total = round(trans_price * qty, 2)
    item_sale_tax     = trans_price_total - trans_price_total/(1 + sale_tax_pct/100)

compute_header(lines) -> dict(doc_value=Σtrans_price_total, doc_value_gross=Σ item_sale_price·qty,
                              doc_value_cogs=Σ new_cost_price·qty, doc_value_tax=Σ item_sale_tax)

split_payment(channel, doc_value, tenders) -> (doc_value_pay, patient_payment, payment_rows)
    # cash/delivery: single non-credit tender = doc_value; patient_payment=0
    # contract:      partial non-credit tender + remainder as paymenttype=10 (credit); patient_payment=cash part
```
`item_sale_price`, `item_sale_price_tax`, `sale_tax_pct` are read **from the branch `items` row** (per-branch
price); `new_cost_price` from **`stkbal.nowcostprice`** (branch, store, item) — both read inside the push txn.

---

## 6. The writer (`writer.py`) — transactional, modeled on `replication.py`

One method per public op; the core is `push_order`. **Serial allocation is the critical, collision-safe step.**

```python
def push_order(order: SoftechSalesOrder, *, dry_run=False) -> SoftechSalesOrder:
    assert order.status == 'ready'
    conn = SoftechConnector_for_branch(order.branch)        # get_branch_connection(...)
    with conn.transaction():                                # BEGIN TRAN
        # 0. read per-branch item prices + stkbal cost for each line; build computed values (pricing.py)
        # 1. ALLOCATE serial — NATIVE pattern (proven via rollback probe §6m): READ current + insert
        #    current+1; the INSERT trigger bumps the counter. Do NOT pre-UPDATE the counter (that makes
        #    the header insert silently not persist). HOLDLOCK serializes against the live POS.
        col = 'lastdocnumberout_cust' if order.doc_kind=='sale' else 'lastdocnumberin_cust'
        docnumber = conn.execute_one(f"SELECT {col} FROM lastdocnumbers HOLDLOCK WHERE branchcode='000'")[0] + 1
        # 2. INSERT stktransm5 (header) — INLINE literals (param INSERTs don't land), one stmt per cursor.
        #    → tr_stktransm5 stamps trans_time + sets {col}=docnumber
        # 3. INSERT stktrans5 (one row per line)  — computed price/tax/cost; r_docnumber for returns
        # 4. (optional) INSERT stktransmcomm5 / stktransmclassif5
        # 5. paymentsno per tender = READ lastdocnumbers.paymentsno + 1 (tr_branchesales5_insert bumps it)
        # 6. VERIFY-READBACK: re-SELECT the header+lines+payments we just wrote; assert they match
        if dry_run:
            conn.rollback(); return order        # prove the exact SQL with zero residue
    # commit happened on context exit
    order.softech_docnumber = docnumber
    order.status = 'pushed'; order.erp_executed_at = now()
    order.erp_payload = payload; order.erp_readback = readback
    order.save(...)
    return order
```

Design rules (lifted from the proven patterns):
- **Mimic the native client exactly** — same columns, same trigger chain fires (`tr_stktransm5` stamps
  `trans_time` + re-stamps the counter; `branchesales5` → `tr_branchesales5_insert`). Set every NOT-NULL
  column using the §6h golden-template sentinels.
- **Collision-safe serials:** the `UPDATE … SET col=col+1` acquires the row lock *before* read, exactly the
  contention point the live POS also serializes on. The whole allocation+insert is one transaction.
- **Verify-readback** before commit (pic_bridge pattern): if the readback doesn't match, **rollback** and
  set `push_failed` with `erp_error`.
- **`--dry_run`** rolls back after building+executing the full statement set → proves the SQL on a real
  connection with zero residue. **Default for all test-instance runs.**
- **Idempotency:** a `client_token` (UUID) on the order; if a push is retried, the writer checks whether a
  row with our token marker (e.g. stashed in `vf2`/`comments`) already exists before allocating a new serial.

---

## 7. Lifecycle, reconciliation & returns

**State machine:** `draft → ready → pushing → pushed → settled` (terminal) / `push_failed` / `cancelled`.
- `pushed` = pending row exists in `stktransm5`, awaiting the cashier.
- `settled` = the cashier finalized it. We **never write the final tables**; instead `reconcile.py`
  (scheduled, read-only, the `sync_crm_orders` pattern) detects settlement by: our pending `stktransm5`
  docnumber **disappeared** AND a matching final `stktransm` row exists for the PIC → record
  `softech_final_docnumber` + flip to `settled`.
- `cancelled` = if still pending and the user cancels, DELETE our pending `stktransm5`/`stktrans5`/
  `branchesales5` rows (reverse of create). **CONFIRMED safe & side-effect-free (spec §6k):** the native
  cashier "Delete" is exactly a `DELETE … WHERE branchcode,doccode,docnumber` on the three tables — no
  trigger, no archive, no counter rollback, no stock/points impact. `writer.cancel_order(order)` issues the
  same three DELETEs in one transaction. **Only valid while unsettled** (once settled, reverse via a return).

### Error recovery (push half-fails)
Because create is one transaction with verify-readback, a failed push rolls back atomically. But if a
process dies mid-push (partial rows committed), `writer.cleanup_failed(order)` issues the same `cancel`
DELETEs by the allocated `softech_docnumber` to remove any orphan pending rows — then the order can be
re-pushed (new serial). Same mechanism the operator's "Delete" button uses.

**Returns:** create a `SoftechSalesOrder` with `doc_kind='return'`, `return_of_invoice=<original final
docnumber>`; writer uses the `_in_cust` counter and sets `r_docnumber`/`ref_docnumber` to the original
invoice (per §6i). Same three-table write.

---

## 8. Safety / guardrails (non-negotiable)

1. **Test instance first.** Nothing runs against prod until validated on `SOFTECH_TEST_HOST`. Add a setting
   `POS_WRITER_ENABLED` (default False) + `POS_WRITER_PROFILE` (default 'test'); prod requires an explicit flip.
2. **`--dry_run` default** on every test run (build+execute+rollback). Promote to commit only after readback diffs are clean.
3. **One transaction per order**; any error → full rollback (no orphan header without lines/payments).
4. **Branch-scoped:** only write to a branch whose `db_host` is set and reachable; bound the login/query timeout (existing connector behavior).
5. **RBAC:** new permission `pos_orders.push`; only authorized roles (e.g. call_center supervisor) can push.
6. **Immutable after push;** corrections via return only.
7. **Reconcile, don't assume:** never mark `settled` from our side — only when read-back confirms.
8. **Points/stock untouched** — assert the writer issues NO INSERT/UPDATE to `picpoints`, `stkbal`, final tables.

---

## 9. API & frontend (thin; reuse existing UI patterns)

```
POST   /api/pos-orders/                 create draft (+lines, +payments, +channel, +referral doctor, +Rx image)
POST   /api/pos-orders/{id}/ready/      validate + compute (pricing.py); lock for push
POST   /api/pos-orders/{id}/push/       writer.push_order  (RBAC: pos_orders.push)
POST   /api/pos-orders/{id}/push-dry/   dry-run (returns the exact SQL + computed values)
POST   /api/pos-orders/{id}/cancel/     delete pending rows if unsettled
GET    /api/pos-orders/ , /{id}/        list/detail (status, serials, settlement)
```
Frontend: extend the call-center / mobile order flow (CallItem → "send to cashier"); a status board mirroring
the existing Delivery/cashier views. Reuse `CustomerPicker`, item search, the prescription-upload component.

---

## 10. Config / env additions
```
POS_WRITER_ENABLED=False            # master kill-switch
POS_WRITER_PROFILE=test             # test|prod
SOFTECH_TEST_HOST= / _PORT=         # required before any test write
POS_DEFAULT_SELLER_USERCODE=        # fallback usercode
```

---

## 11. Test-instance validation checklist (the few things still unproven)

Before enabling commit on prod, confirm on `SOFTECH_TEST_HOST` via `--dry_run` then a real settle:
- [ ] A pending order we INSERT appears correctly on the **Cashier** screen (all channels).
- [ ] `tr_branchesales5_insert` (hidden) side-effects on a pending credit tender (does it pre-post to the account?).
- [ ] Exact NOT-NULL sentinels for every `stktransm5`/`stktrans5`/`branchesales5` column the client sets (cross-check §6h golden template).
- [ ] Cashier finalizes our order → final doc, stock −, points (for an `itempointsys`-relevant item) — all by SOFTECH, confirming we needn't compute them.
- [ ] Serial-collision behavior under concurrent native POS activity (the `UPDATE+1` lock).
- [ ] `dblitemflag` / `bonusqty` / `vf2` semantics (set to match the golden template or leave to SOFTECH).
- [ ] Cancel path: deleting an unsettled pending order is clean.

---

## 12. Build order (when greenlit)
1. PG models + migration (`pos_orders`) — no SOFTECH contact. Unit-test `pricing.py`.
2. Connector transaction support + non-SELECT execute.
3. `writer.py` with `--dry_run`; validate against `SOFTECH_TEST_HOST`.
4. `reconcile.py` + scheduled command (read-only) — wire to the existing APScheduler.
5. API + RBAC + immutability.
6. Frontend (create → ready → push → track), prescription upload, referral-doctor picker.
7. Returns path.
8. Controlled prod pilot (one branch, kill-switch, dry-run-first), then ramp.

---

## 13. Out of scope / explicitly NOT built
- Any write to final `stktransm`/`stktrans`/`branchesales`, `stkbal`, `picpoints`, accounting, e-invoice.
- Computing final serials / points / stock (SOFTECH's cashier owns these).
- The home-delivery `piccrmorders` path (separate; documented but not this writer's target).
- Insurance company-claim (motalba) postings — `apps/insurance` territory.
