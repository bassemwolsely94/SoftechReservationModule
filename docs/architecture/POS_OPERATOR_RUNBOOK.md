# Indirect-POS Writeback — Operator Runbook

Practical guide for creating SOFTECH indirect-POS pending orders from our system,
validating them, and the duplicate → settle → return cycle. Full reference:
`SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md` + `14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md`.

> ⚠️ Writes are GATED. `POS_WRITER_ENABLED=False` by default — nothing reaches SOFTECH
> unless you explicitly enable it for a command. Run real writes OFF-PEAK (the live POS
> reuses released serials within seconds; the writer briefly locks `lastdocnumbers`).

---

## 0. Golden rules
- **Never let a test order get settled by a real cashier unless you intend a real sale**
  (settlement → stock move + Egyptian e-invoice/FAT = irreversible).
- **Rehearse with the rollback probe first** (zero residue) before any commit.
- **Returns need correct line + claim data** — the writer now sets it; for orders made
  before the fixes, see §5 (manual patch).

---

## 1. Rehearse a create (zero residue) — rollback probe
Duplicates an existing pending order, runs the REAL inserts, then rolls back. Nothing persists.
```
python manage.py pos_probe --clone <pending_docnumber> --host 192.168.30.12
```
Look for `ok: True`, `lines_with_expiry == lines_found`. For a contract order it also captures
`companiesitems5` + `branchesalescc5` ("captured contract claim data: …").

## 2. Rehearse a cancel/delete (zero residue)
```
python manage.py pos_probe --cancel-probe <pending_docnumber> --host 192.168.30.12
```
Confirms the DELETE works and the row is restored on rollback (`still present`).

## 3. Commit a real pending order (OFF-PEAK)
Creates a real pending order on the cashier (leaves it pending).
```
POS_WRITER_ENABLED=True python manage.py pos_probe --clone <pending_docnumber> --host 192.168.30.12 --commit
```
Reports the allocated `softech docnumber` + verifies it persisted. It now appears on the
branch Cashier screen (tagged `vf2=POS<id>`).

## 4. Cancel a committed pending order (cashier-style Delete)
```
POS_WRITER_ENABLED=True python manage.py shell -c "from apps.pos_orders.models import SoftechSalesOrder; from apps.pos_orders import writer; print(writer.cancel_order(SoftechSalesOrder.objects.get(pk=<id>)).status)"
```
Deletes the 3 pending tables for that order — side-effect-free (no stock/points/accounting),
leaves a harmless serial gap. Only valid while UNSETTLED.

## 5. The duplicate → settle → return cycle (what each field needs)
A sale is RETURNABLE only if these match a native sale (the writer now sets them automatically
for cloned orders; this is the checklist if you ever debug a stuck return):

| Layer | Field | Correct value |
|---|---|---|
| `stktrans` line | `itemexpirydate` | the batch expiry (copied from source) |
| `stktrans` line | `retqty` | **0** on an un-returned sale (it = qty ALREADY returned) |
| `stktrans` line | `bonusqty`, `dblitemflag`, `suppliercode` | native values (copied) |
| `stktransm` header | `cust_professional`, `origintaxp`, `cust_branch_store` | from source (contract) |
| `companiesitems` | patient claim row | `patientno`/`membershipno`/`roshettano` (the return keys on these) |
| `branchesalescc` | cost-center row | `paymentsno` = the credit tender |

Reconcile pushed → settled (read-only):
```
python manage.py reconcile_pos_orders        # also scheduled every 5 min
```

## 6. Settings (env)
| Var | Default | Meaning |
|---|---|---|
| `POS_WRITER_ENABLED` | False | master kill-switch for real writes/deletes |
| `POS_WRITER_PROFILE` | test | connection profile |
| `POS_LIVE_PRICING` | False | read branch `items`/`stkbal` live at prepare |
| `POS_WRITE_CHARSET` | cp1256 | charset for the write connection (correct Arabic) |
| `POS_DEFAULT_SELLER_USERCODE` | '' | fallback seller usercode |

## 7. Known limits
- **Batch availability IS readable** — `stkbalexpiry` keyed by **`storecode`** (not
  `branchcode`); reconciles to `stkbal.nowqty`. Exposed at `GET /api/pos-orders/batches/
  ?branch=&item=` (→ batches + `out_of_stock`). No rows ⇒ reservation (حجز 80) pathway.
- **Fresh (non-clone) batch *picking* UI** not yet wired into the POS screen (reader/API
  ready). Clone still copies the source's chosen batch verbatim.
- **Contract claim auto-creation**: implemented + live-validated (clone 468852 probe).
- **Discount authority** check exists behind `POS_DISCOUNT_AUTHORITY` (off) — needs the
  item→category / PIC→personcode / usercode→personcode joins confirmed first.
- The hidden finalization triggers (stock/points/accounting/e-invoice) run on the cashier's
  settle — we never replicate them.
