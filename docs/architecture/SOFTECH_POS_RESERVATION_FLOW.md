# SOFTECH Indirect-POS — Reservation / Out-of-Stock Flow (investigation)

Reverse-engineered read-only @br130 2026-06-23, **corrected per operator feedback**.

> ❌ Earlier draft wrongly attributed this to `piccrmorders` — that table is **call-center
> orders dispatched to branches**, unrelated to reservation. The reservation lives in
> **`stktrans`/`stktransm`** as its own doc-type family (codes 80/180/81/181).

## What a reservation is
When a POS item is **out of stock**, an item line is added *before* the sale is saved that
**adds the qty to stock** so the order can be completed. Later, on a separate **reservation
screen**, you browse by reservation number (or the sale) and **pick the now-physically-
present batch** from a modal — that **dispenses** (delivers) the held item. The reservation
can be cancelled, and the sale's return is **gated** on the dispense being returned first.

## Doc-types (each its own serial sequence; `ptclassifcode=-1`, `cust_branch_code=-80`)
| doccode | Arabic | Meaning |
|---|---|---|
| **80** | حجز | the **reservation / hold** — created for the out-of-stock line |
| **180** | تسليم حجز | the **dispense / delivery** of the reserved item (real batch picked) |
| **81** | مرتجع تسليم حجز | **return of a dispense** (reverses an 180) |
| **181** | (return-side) | dispense reversal tied to a **return** document |

Live counts @130: 80 = 5,895 · 180 = 5,727 · 181 = 760 · 81 = 62 (all active, 2026-06).

## The link
- **`stktransm.docnumber2` = the sale's docnumber** on the 80 and 180 docs. The whole
  chain hangs off the sale. Example (verified): sale **452840** (115) ⇄ reservation
  **80#33938** (`docnumber2=452840`) ⇄ dispense **180#26329** (`docnumber2=452840`).
- **81** (return-dispense) carries the link at **line level**: `stktrans.r_doccode=115`,
  `r_docnumber=`<original sale>. **181** uses header `docnumber2`=<return doc, 21xxx>.
- Line-level source/return columns: `s_doccode/s_docnumber/s_docdate` (source) and
  `r_doccode/r_docnumber/r_docdate` (return reference).

## The batch tell (matches the operator description exactly)
- Reservation **80** line: real item, but a **placeholder/dummy expiry** (observed
  `2012-12-11`) — the physical batch isn't known yet; the line just reserves the qty.
- Dispense **180** line: same item with the **real batch expiry** (observed `2028-02-01`)
  — chosen from the modal when stock physically arrives.

## Lifecycle
1. Out-of-stock line → **حجز 80** created (placeholder batch), `docnumber2` = the sale;
   this adds stock so the **sale (115)** can be saved.
2. Stock physically arrives → on the reservation screen, browse by reservation/sale →
   pick the real batch from the modal → **تسليم حجز 180** created (`docnumber2` = the sale).
3. **Return rules (critical, gates the sale return):**
   - If the item **was dispensed** (180 exists): you must **first return the dispense
     (81 مرتجع تسليم حجز)** on the reservation screen; only then can the **sale return (30)**
     proceed. The sale return is **blocked** otherwise.
   - If **not dispensed** (only 80, no 180): the sale can be returned directly and the
     **reservation (80) is cancelled**.

## Implications for our writeback
- Our current writeback handles **in-stock** sales only (no 80/180). Correct for those.
- **To faithfully clone a sale that included a reserved (out-of-stock) item**, we would
  also reproduce the **80** (and, if the source had it, the **180**) linked by
  `docnumber2` = our new sale docnumber — otherwise the duplicate's return behaves
  differently from the original. This is the analogue of the claim-data fix, for the
  reservation chain.
- A returnable check should detect a linked **180** and require the **81** first.

## Qty / stock mechanics (decoded 2026-06-23)
`stktrans` qty columns: `transqty, newqty, bonusqty, retqty`.
- **`transqty`** = the qty moved on the line, stored **unsigned** (magnitude only).
- **`newqty`** = the **on-hand balance AFTER this line** (a running-balance snapshot).
  Verified: item 84307 sold `transqty 0.44444` → `newqty 15.44447` remaining; purchase
  (25) received `1` → `newqty 1`. The doc **direction (+/−) is by doccode**, applied by
  encrypted triggers (no config table — `sp_stores_stkbal_from_stktrans` etc.).
- Reservation chain on HUMALOG 123538 (packqty 5, starts at 0): **حجز 80** is stock-**IN**
  (`transqty 0.4`, `newqty 0.4` → balance 0→0.4); **sale 115** is stock-**OUT** (`newqty 0`
  → 0.4→0); **تسليم حجز 180** is stock-**OUT** of the real batch. Net 0 (stkbal=0 today).
  ⇒ the حجز injects stock so the out-of-stock sale can be saved; the 180 delivers the real
  batch once it physically arrives.

## The batch-pick modal — source (RESOLVED 2026-06-23)
- **The modal reads `stkbalexpiry`, keyed by `storecode`** (the `branchcode` column is an
  unused `'0'` — earlier reads that filtered `branchcode='130'` wrongly came back empty).
  At `storecode='130'` it has **5,471 live rows** `(itemcode, itemexpirydate, itemqty[,
  batchno])`, and the per-item batch sum **reconciles exactly to `stkbal.nowqty`** (item
  100038 → 2.0+1.0+3.0 = 6.0). An item with **no rows = out of stock** (e.g. 123538) ⇒
  reservation pathway.
- Batch identity at br130 is the **expiry date** (`batchno` is usually blank). The
  reservation (80) carried placeholder expiry `2012-12-11`; the dispense (180) the real
  `2028-02-01`.
- The table is **maintained** (not read) by the encrypted procs
  `sp_expirytrans(@storecode,@itemcode,@itemexpirydate,@transqty,@transtype,@batchno,…)`
  (per-line) and `sp_stkbalexpiry_from_stkbal(@date)` (rebuild). We only **read** it.
- **Fresh-order batch selection is therefore unblocked.** Reader + API implemented:
  `apps/pos_orders/batch_availability.py` and `GET /api/pos-orders/batches/?branch=&item=`
  return the available batches + an `out_of_stock` flag (→ reservation).

## Practical consequence
- **Clone path stays reliable** — it copies the source line's chosen `itemexpirydate`.
- **Fresh-order in-stock batch selection is now possible** — read `stkbalexpiry`
  (storecode-keyed) to drive the modal: list batches by expiry/qty, let the operator pick
  one or split across several to make up the quantity.
- **Out-of-stock detection** is a simple check: no `stkbalexpiry` rows (or total ≤ 0) ⇒
  reservation (حجز 80) pathway. The reservation itself uses a placeholder expiry, so it
  needs no batch data; the real batch is chosen at dispense (180) from the same table.

## حجز 80 writeback (built 2026-06-23 — probe-first, gated)
`apps/pos_orders/reservation.py` writes a حجز to `stktransm`/`stktrans`:
- counter = `lastdocnumberin` (branch row, ver_branch=1) via the native read+1 pattern;
- header `doccode='80'`, `docnumber2=<sale>`, `cust_branch_code='-80'`, `ptclassifcode='-1'`,
  `origdoc='5'`; line `newqty=transqty` (stock-IN), placeholder expiry (2012-12-11),
  `r_doccode='115'/r_docnumber=<sale>`, `item_partno='Reservation'`.
- `probe_reservation(order, sale_docnumber)` = real INSERTs then ROLLBACK (zero residue).
- `push_reservation(...)` commits but is gated: `POS_WRITER_ENABLED` **and** `confirm=True`.
- ⚠️ A حجز is **stock-affecting** (adds inventory) — NOT committed yet; validate on a test
  instance first (see open question below).

## Open follow-ups
- **Validate the حجز timing/linkage** before committing: native rows link to the FINAL sale
  and use the branch-own counter (created at/after settlement). Confirm whether our flow
  should reference the pending (`stktransm5`) or final docnumber, and the seller-vs-cashier
  trigger point.
- Confirm 181's exact Arabic label and when it's emitted vs 81.
- Decode `bonusqty` on these lines (carried large values; role unclear).
