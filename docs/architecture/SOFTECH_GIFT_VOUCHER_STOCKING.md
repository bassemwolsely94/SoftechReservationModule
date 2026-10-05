# SOFTECH Gift-Coupon Stocking — Current (RPA) Behaviour & Replication Spec

**Status:** INVESTIGATING (2026-10-06). The RPA inputs are decoded below. The SOFTECH-side storage
(where the serial lands, how coupons leave stock) still needs the read-only probe
`python manage.py investigate_gift_vouchers` to be run on-site.

## 1. Business context
- Paper **purchase coupons** (`قسيمة مشتروات من صيدليات الرزيقى بقيمة 50ج.م`) are printed with a
  unique serial. Each coupon has handwritten fields: client name, phone, **PIC code** (`كود العميل`).
- Stock is held in SOFTECH as two items: **`102230`** and **`118639`**.
- Coupons are bought from the internal supplier **`1268` — هدايا الاداره لخدمة العملاء** (ptcode 20,
  ptclassif 10) as a **supplier purchase (doccode 10)** received at **HQ (branch 100)**. They are
  then dispensed to branches and **deducted against the PIC client** who receives the coupon.
- Document user: **BASSEM** (the owner's SOFTECH usercode).
- **200 coupons per item per invoice.** SOFTECH slows down badly on larger documents.

## 2. Current process (manual + RPA)
Source files: `Coupon_Printing.xlsx` and `Dataload_for_Coupon_Serial_Number.dld` (WorkBench DataLoad).

### 2a. `Coupon_Printing.xlsx`
| Sheet | Content |
|---|---|
| `Serial Database` | The master archive of every serial ever issued: 6,400 rows, serials `17001`→`27300`. Columns: running No., random code, serial number, full serial `NNNNN-AAA999`. A `*` in col E marks the start of each 200-batch, and some rows carry a date (2026-01-31). |
| `Serial Generator` | 250 rows. Random code formula `=CHAR(RANDBETWEEN(65,90))×3 & RANDBETWEEN(100,999)` (e.g. `ZWU704`) + a sequential serial number (`27101`…), giving a full serial `27101-ZWU704`. Values are pasted as static text into `Serial Database`. |
| `Coupon Expiry Dates` | 800 consecutive dates, 2028-01-01 → 2030-03-10. |
| `Printing Sheet` | 100 coupons per print run, 4 per page. The page order is collated: coupon k on page p = generator row `2 + p + 25·k`, so the cut stacks come out in serial order. |

### 2b. DataLoad (RPA) script
The script runs on the native `مشتريات من الموردين` screen. Per coupon line it types:
`itemcode ↵  ⇥ qty=1 ⇥ expiry dd/mm/yyyy ⇥ serial NNNNN-AAA999 F2`

The last loaded batch had 400 lines:
- 200 × `102230` + 200 × `118639`.
- Serials `27101-ZWU704` … `27300-KNQ777`, the **same 200 serials for both items**.
- Expiry dates **23/08/2029 → 10/03/2030**, one day per line, in the same order for both items.

**Key finding:** the expiry date is *not* random. It is a **sequential, unique-per-line date**. Every
coupon therefore becomes its own `(itemcode, expiry)` stock row in `stkbalexpiry`, so it can be
picked individually. The **serial** is the coupon's identity, and the probe will confirm which
column it is saved in (`stktrans.item_partno` / `stkbalexpiry.batchno` suspected).

## 3. Data-quality issues in the manual archive (why it must move into the platform)
- **97 duplicated serial numbers.** `22504–22600` were issued twice with different random codes
  (rows 2104–2200 re-ran a range).
- **100 duplicated random codes.** Serials `17101–17200` reuse the codes of `17201–17300`.
- Number jumps `19000 → 22501` and `25900 → 26301`. These look intentional but are undocumented.
- The expiry-date pool (800 dates) ends 2030-03-10, and the last batch used up to that date. **The
  next batch has no dates left** without extending the list.

## 4. Replication design (to be confirmed after the probe)
1. **Archive:** a platform table of every coupon serial (number, code, item, expiry, purchase doc,
   status). Seeded from `Serial Database` + the SOFTECH purchase history from supplier 1268.
   Uniqueness is enforced on the serial.
2. **Generator:** continue from the last serial (`27301`). Random codes are unique against the
   archive. Expiry dates are the next free consecutive per-item dates, never colliding with an
   existing `(item, expiry)` in `stkbalexpiry`.
3. **Purchase:** one `SupplierInvoice` per item per batch (vendor 1268, 200 lines, qty 1 each),
   pushed through the existing `apps/invoices/writer.py`. This is the established writeback
   channel, which is idempotent and verified after writing. No new write path.
   - Gap to close: the writer omits `item_partno`. If the probe confirms the serial lives there,
     the line row must carry it, and the column set must be confirmed by capturing one RPA save
     (`monSysSQLText`, as in `SOFTECH_PURCHASE_SAVE_DML.md`).
4. **Printing:** regenerate the `Printing Sheet` layout from the archive.

## 5. Open questions (answered by `investigate_gift_vouchers`)
- [ ] Column holding the serial (`item_partno`? `batchno`?).
- [ ] Price / cost / public price on the coupon lines (50 EGP face value?), and `pharmacydiscp`.
- [ ] Difference between items `102230` and `118639` (both carry the same serials).
- [ ] How coupons leave HQ stock (transfer doccode to branches; sale/deduction to the PIC client).
- [ ] Current on-hand per item (the user reports both are out of stock).
