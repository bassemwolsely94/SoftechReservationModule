# SOFTECH In-Direct POS — Field/Dropdown Gaps (from the recorded walkthrough)

Captured from the user's screen recording (2026-07-26) of the real SOFTECH POS. This is
what our module is still missing or does differently. Frames in scratchpad/frames.

## THE BIG ONE — customer is a TWO-LEVEL selection, not a channel + free search

SOFTECH header has **نوع العميل (customer TYPE)** then **إسم العميل (customer NAME)**:

1. **نوع العميل** = a category dropdown. Observed values:
   - `عميل نقدى` (cash / Walk-In)
   - `عميل دائم` (permanent)
   - `تعاقدات / آجل` (contracts / credit)
   - `تأمين صحى` (health insurance)
   - `موظفين شركة الرزيقي` (ElRezeiky employees)
   - `تعويضات الشركات` (company compensations / pharma free-packs)
   - (home-delivery too, via Ctrl+F3) — confirm full list

2. **إسم العميل** = an entity list **filtered by the chosen نوع العميل**:
   - contract → the contract companies, EACH a discount tier:
     `Aghpy Care, D M S 0%/5%/10%/15%/20%/25%/30%/35%/40%/50%, DMS مجمع,
      S7etak PSP Trulicity, Terre Des Hommes (TDH), إبجيكير 15%…50% / بدون تحمل,
      كبرى برازرز, دار الشعب شهرى/يومى, رشدي شاكر, شركة الخدمات الطبية لكهرباء مصر,
      Medmark, صحتك مخزن, …`
   - insurance → submission methods e.g. `إرسال إلكترونى بالبطاقة الشخصية`
   - employees → the employee NAMES (سمير صموئيل, شوقي ظريف, كريستين كمال, موسى فرج الله…)
   - compensations → `AstraZeneca Compensation, FREE PACKS NOVARTIS/BARCOMANT,
      S7etak Trulicity Free, Janssen…`
   - cash → Walk-In Customer

3. Selecting an entity **auto-fills خصم العميل** — BUT the source differs by type (see below).

### CORRECTIONS (user, 2026-07-26) — my first read had two errors
- **Walk-in (نقدى, 91) and Delivery (توصيل, 90) are SEPARATE types**, chosen up front.
- The **D M S 0–40% list is the LOYALTY-points system, NOT a POS discount** — do not treat
  it as a discount on the POS line.
- **Discount by type:**
  - walk-in / delivery / permanent (retail) → discount is capped by the **seller's POS
    discount limit** (`managerdiscount.max_custdiscp`) **AND the item's max POS discount
    (`items.posdiscp`)** — computed, not from a customer entity.
  - contract → from the **B2B `custdiscounts`** table (keyed by the entity's personcode).
- تأمين صحى (insurance) was **not** "إرسال إلكترونى بالبطاقة الشخصية" — mis-read.

### DATA MODEL (verified in SOFTECH)
- **Type catalog** = `persontypesclassif(ptcode, ptclassifcode, ptclassifdescr)`. POS-relevant:
  `91 عميل نقدى · 90 عميل Delivery · 30 عميل دائم · 10 تعاقد · 15 تأمين صحي · employees(ptcode 30) · compensations`.
- **Entities per type** = `personsdata WHERE ptclassifcode=X` → `personname, personcode,
  personglobalcode(PIC)`. Counts: contract(10)=1381, employees(11)=120, permanent(30)=51,
  cash(91)/delivery(90)=1 each.
- **Contract discount** = `custdiscounts` by the entity's `personcode` (+ item category).
- **Branch → stores** = `branchstores(branchcode → storecode, defpos)` joined to
  `stores(storecode → storename)`. e.g. branch 130 → store 130 (defpos=1).

### Our module today (gap)
We have a `channel` dropdown + a generic `CustomerSearchWidget`. We are missing:
- نوع العميل as the primary category driver (it maps to ptclassifcode).
- إسم العميل as an entity list filtered by that category, sourced from our synced
  `Customer` table (has `softech_ptclassifcode` / `person_classif_label`).
- Auto-fill of the customer discount % from the chosen contract entity.

## Other header fields confirmed present in SOFTECH
- خصم فكة (change/rounding discount) — we have it.
- خصم العميل % (customer discount) — NEW: a header-level customer discount field (auto from entity).
- ما يسدده المريض / patient pays — the credit down-payment (we have patient_payment server-side; not surfaced).
- hist button next to PIC (customer history) — not in ours.
- أسلوب السداد: نقدى / أجل (and card) — we have it.

## To confirm with the user / capture next
- Full نوع العميل category list (all options).
- Is إسم العميل a plain dropdown of ALL entities, or typeahead/search?
- The Payment tab dropdowns (currency, card type) — full option lists.
- The Contract Emp. Data tab — any dropdowns (فرع الخدمة, تصنيف…).
- The toolbar buttons (top icon row) — which are needed on our screen.
- Item-search modal filter behaviours.

## Recording pass 2 — the rest of the screens (2026-07-26)

### Item-Search modal (the `...`/advanced item lookup) — richer than ours
Title "Item Search / البحث عن صنف". Features we don't have:
- Wildcard name box (`*AXE*SP`) + **code** column.
- Scope radios: `أصناف غير مؤرشفة فقط` (non-archived only) vs `جميع الأصناف` (all).
- `أصناف لها أرصده` (has-balance) checkbox.
- **Filter dropdowns per column: نوع الصنف (item type), المنشأ (origin/manufacturer),
  المورد (supplier)** + FMI checkbox column.
- Columns: كود · إسم الصنف · FMI · سعر بيع العبوة (pack price) · بيع الوحدة (unit price) ·
  نوع الصنف · المنشأ · المورد · رصيد الفرع (branch balance).
- **Multi-row compound query** (5 filter rows) run with F8 (تنفيذ إستعلام) / F7 (جديد).
- Status bar shows `Balance Qty` **and `On Order Qty`** per item.

### إسم العميل `...` → "Individual Customers Pop-Up"
For نقدى / دائم you pick a specific PERSON via a searchable directory (columns مسلسل, رمز,
PIC, PPIC, اللقب, الإسم, رقم التليفون, نوع الرقم…) with **add/edit** (F7 query, F8 execute,
F2 add, Ctrl+S save, F4 cancel). Our `POSCustomerModal` covers part of this.

### من حساب مخزن (store) — branch-dependent, and it matters
Changed to `مخزن اكسسوارات` (accessories store) during the session; item balances are
per-store. Source = `branchstores` (built).

### hist button (next to PIC) — PIC transaction history
Opens a **PIC transaction history** filtered by date range (From/To) + PIC — a customer
purchase-history viewer. We don't have it on the POS.

### Warning dialogs
SOFTECH pops validation dialogs (stock/change/discount) with OK — we should surface the
equivalent inline errors (mostly already do).

### NOT in this recording (capture later if needed)
- Payment tab (السداد) full layout in SOFTECH.
- Contract Emp. Data tab dropdowns (فرع الخدمة, تصنيف…).

## Sales Setup Options — the CONFIG RULES that govern the POS (2026-07-29 screenshots)

These are SOFTECH's configurable behaviours (Sales tab + POS Receipt tab). Our POS must honour them:

**Miscellaneous / limits**
- Detection of SalesMan User = **"Automatic by System + Blocked"** → seller auto-set & locked (matches our seller lock).
- Initial Default Item Quantity = **ONE Package** → default qty = 1 pack (done).
- Items Quantities AS **One Field** (not Pkg+Unit) → single decimal qty in packs (done).
- **Max amount in L.C for sales FAKKA discount = 0.50** → خصم فكة capped at 0.50 EGP.
- **Max Item Sales Quantity Per POS Line = 10000**.
- **Max Days for Return Invoice = 90**.
- Cost Price Uplift % for "Sales at Cost" Warning = 0.00.
- منع الصرف: **prevent dispensing qty > (available − reserved)** [stock check] = ON.
- Enable "Add Item to ISR" pop-up on reaching Min Stock Level = ON (نواقص / itemsdefrequest flow).
- "Cashed from Customer" pop-up after saving = ON.

**Must-provide-PIC to save** (per channel): Cash = off · **Home Delivery = ON** · Contracts = off.

**Enable/Activate**: PIC Buy-History button ON · Modify sale price (cash & credit) ON · Record cancelled items ON ·
Customer Payment by **Cheques = OFF** · by **Credit Card = OFF** (so only cash + آجل tenders at this install) ·
Cash Drawer OFF.

**Contract Emp. Data — the 12 field titles** (Corp. Customer Std. Emp. Data Titles):
`1 إسم المريض · 2 رقم المريض · 3 الرقم المالي · 4 رقم الملف · 5 رقم الروشتة · 6 رقم العضوية ·
 7 الإدارة/المنطقة · 8 الجنسية · 9 درجة القرابة · 10 ملاحظات/الطبيب · 11 تاريخ الكشف · 12 تصنيف الطبيب`
A specific contract may relabel some (DMS showed: اسم المريض, رقم المريض, تاريخ الروشتة, رقم موافقة DMS,
شركة الموظف, رقم الموبايل, التشخيص, تاريخ المطالبة).

**Contract header extras (from the DMS 10% example)**: selecting a contract entity auto-fills **خصم العميل %**
(D M S 10% → 10%); plus **ما يدفعه المريض %** and **ما يسدده المريض** (patient co-payment amount) — the contract/
insurance split. إجمالي المطلوب shown as the pre-split total.

**POS Receipt tab** — real header/footer for El-Rezeiky:
- Headers: `El-Rezeiky Pharmacies` · `إدارة صيدليات الرزيقي - ش الجلاء - ميدان رمسيس` · `الخط الساخن 0225740408` · `Whatsapp 01014019763`.
- Footers: `تنقى طلباتكم على مدار 24 ساعة على الخط الساخن 0225740408` · `أدوية الثلاجة ومنتجات التجميل لا ترد ولا تستبدل` ·
  `التجميل والاكسسوار والمستلزمات الطبية شاملة 14% ض.ق.م` · `Whatsapp 01014019763`.
- **Print Employee Name of Contract Customer = ON**. Font 8, 40 chars/line. Replace item names by codes = OFF.

## Decisions locked (user, 2026-07-29)
- **Tenders on Indirect-POS = نقدى / آجل only.** Card & cheque details are entered on the
  SOFTECH cashier screen after we send the order — we do NOT duplicate them. (`PAY_METHODS`
  trimmed; card/cheque columns removed from the Payment tab, web + mobile.)
- **خصم العميل % + ما يسدده المريض surfaced in the header.** خصم العميل % is the effective
  discount rate over gross (read-only). ما يسدده المريض is the patient cash co-pay: for
  contract/insurance it's editable and rebuilds the tenders (cash co-pay + credit remainder =
  يتحمله التعاقد), which the server turns into `patient_payment` via `pricing.split_payment`.
- **No stock guard / no returns from our system.** Availability is already handled by the
  reservation + FEFO batch selection we built; ALL returns happen in SOFTECH, so the 90-day
  return window and the (available−reserved) dispense guard are out of scope here.

## Workflow layer (modernization, 2026-07-29)
The POS is no longer a fixed SOFTECH sequence — it's a **reactive, order-independent workflow**:
- **`workflow` engine** (pure `useMemo` in `usePosOrder.js`): derives each step's status
  (`done/active/blocked/todo/skip`) from current state, plus `advisories[]` (reactive
  non-blocking nudges/warnings), `progress`, `next` (suggested action), `ready`. Steps:
  channel · seller · customer(PIC) · items · claim(if contract/insurance) · payment.
- **Order-flexible + cascading**: add items first, then pick channel/customer → contracted
  discounts auto-apply to non-hand-edited lines (existing discount-suggest effect, keyed on
  channel/items/personcode). Switching to نقدى/توصيل auto-converts a leftover آجل tender to cash.
- **`WorkflowBar`** (desktop) / **`MobileWorkflowBar`** — the "story" rail: step chips, gradient
  progress, live "التالى:" suggestion, clickable advisories that jump to the fixing field.
- **Guided focus mode** — optional wizard toggled from the workflow bar, on BOTH surfaces
  (`GuidedMode` desktop overlay + `MobileGuidedMode` full-screen). Walks ONE stage at a time
  (العميل والقناة → الأصناف → بيانات التعاقد → السداد والمراجعة), reusing the same panels + engine
  (no state fork). Power-screen stays the default. Navigation is shared in `hooks/useGuidedFlow.js`,
  which **auto-advances** on the false→true completion edge of the active stage (a stage already
  done on arrival, or one you navigate back to, does not yank you forward).

## Discount source fix + shared item search (2026-08-18)
- **Retail discount was wrong.** `discount_suggest` ran EVERY channel through `custdiscounts`
  (keyed on the walk-in rep customer) → cash/delivery got the contract/point-system rate.
  Fixed, with two distinct behaviours:
  - **Retail (cash/delivery/permanent/employee/vip) = CAP-ONLY, no auto-apply.** The operator
    enters the discount; the per-item ceiling = **min(item `posdiscp`, seller `max_custdiscp`)**
    (new `DiscountAuthorityReader.item_posdiscp`). `discount_suggest` returns `caps[code]`; the
    UI clamps every discount input (grid, numpad) to it, warns on exceed, and `clientValidate`
    + `check_order` block an over-cap discount server-side too.
  - **Contract/insurance = AUTO-APPLY** the `custdiscounts` contracted rate, bounded by the
    seller ceiling (unchanged).
  Point/loyalty stays a separate display, never a line discount. `discount_suggest` returns
  `{suggestions, caps, ceiling, source}`.
- **Cap hint is role-gated.** The faint "≤ X%" ceiling shown in the discount cell (desktop grid,
  mobile line + guided) renders ONLY for manager roles (`DISCOUNT_CAP_VIEWER_ROLES =
  admin/supervisor/pharmacist`, surfaced as `reference.can_see_discount_cap`). Cashiers get the
  silent clamp but not the number — showing everyone the ceiling would just anchor them to max it.
  The clamp + validation apply to ALL users regardless; only the *visibility* of the number is gated.
- **Item entry now uses the shared `ItemSearchWidget`** (same as Reservations / Transfer
  Requests) on desktop + mobile + guided mode: barcode-scanner aware, rich dropdown, and the
  **Ctrl+F1** advanced-search modal. The separate manual barcode box was dropped on desktop
  (the widget already matches all barcodes).

## Item-add fixes + buttons audit (2026-08-18)
Reported: "the item search widget does not apply the selected item." Root causes + fixes:
- **`branch` never defaulted** → `addItem` bailed silently (`اختر الفرع أولاً`). Now: `branch`
  defaults to the seller's own branch (`reference.default_branch`), or the sole branch, or the
  last-used (localStorage `pos_branch`); and `addItem` NEVER drops the item — with no branch it
  still adds the line (availability resolves once a branch is chosen).
- **`_newLine` read only `item.item_id`** but `ItemSearchWidget` sends `item.id` → the catalog
  FK was null. Now reads `item_id || id`.
- **Guided mode was `z-[60]`, above the `z-50` batch/customer/advanced-search modals** → picking
  a stocked item in guided mode opened the batch picker *behind* the wizard (looked like nothing
  happened). Guided is now `z-[45]` (above the `z-40` sidebar, below all modals).
- **Batch modal confirmed with no picks added nothing** → now always commits at least a plain
  line (qty = need), so the item never vanishes.
- **Buttons audit:** every `onClick` on both POS pages was cross-checked against the hook's
  exports — all resolve (no dead handlers). Apply-discount buttons gated to real suggestions
  (contract) and relabeled "المقترح".

## Delivery + batch + reservation + preview fixes (2026-08-18 #2)
Reported: delivery channel, batch/expiry selection, and per-item reservation all broken; dry-run
"pressed but not working." Root causes + fixes:
- **`/batches/` read the wrong store.** `addItem` never passed the selected `storeCode`, so the
  view fell back to the branch code → `stkbalexpiry` returned nothing → EVERY item looked OOS →
  reservation applied to all, batch modal never opened. Now `addItem` passes `store: storeCode`.
- **Delivery blocked on preview.** The Home-Delivery PIC requirement ran on `ready_order` (dry-run
  too). Moved to `for_push`/live only (backend `validators`, frontend `clientValidate(live)`) — a
  delivery order previews freely; PIC is enforced only on the real send.
- **Per-line `is_reservation` was dropped entirely** — not on the line model, serializer, or
  payload. Added the field (mig `0008`) + serializer + payload; the dry-run plan now tags each
  line بيع/حجز and carries a `reservation_note` (OOS lines settle as a separate حجز 80 linked to
  the sale — reservation.py, still gated).
- **The dry-run plan was never rendered.** `setPlan` result had no UI → معاينة تجريبى only showed
  a toast. Added a **plan preview modal** (desktop) + sheet (mobile): lines with بيع/حجز badges,
  expiry, payments, reservation note, collapsible SQL.

## ✅✅ POINTS FULLY REPLICATED END-TO-END (2026-08-19) — our order → SOFTECH → +221 awarded
FINAL verified mechanism (our writer created order → cashier finalized → doc 7009 → customer +221):
- **The authoritative per-line points live in `stktrans.vf4`** (SMALLINT). SOFTECH's finalization
  RECOMPUTES the header `personnewbal` as **Σ line `vf4`** and writes that as the `picpoints` award.
  A correct header `personnewbal` alone is NOT enough — 7007/7008 had `personnewbal=221` but no
  `vf4` → awarded **0**. Setting `vf4` per line → awarded **221**. ⇒ the header personnewbal is a
  preview; **`vf4` is the source of truth.**
- **`vf4[line] = floor( line_net × custdiscounts[rep, items.itemcode_alt3] / 100 )`**, rep =
  CashCust(cash)/HomeDlvry(delivery). Header `personnewbal` = Σ vf4. Returns → negative vf4.
- Also set **`cust_professional='2'`** (VARCHAR) — native sets it on every cash sale; leaving it NULL
  differed from native (belt-and-suspenders; vf4 was the decisive fix).
- Implemented: `points.compute_points` returns signed per-line points; writer `_line_row` sets
  `vf4=int(line_points)`, `_execute_write` zips per-line points by index, header `personnewbal`=Σ.
  `POS_BLOCK_POINTS_SALES` default False. Column types: `vf4` INT, `cust_professional` string.
- ✅ OOS GUARD IMPLEMENTED: `apps/pos_orders/stock.py` `check_order_stock()` (live stkbal.nowqty per
  line); `push_order` REJECTS an OOS sale before writing (push view → 400 `errors.stock`), matching
  native منع الصرف (RAISERROR 21225). Rationale: our writer only writes 115 sale lines (no حجز 80),
  so an OOS line could never finalize on any branch. `POS_ENFORCE_STOCK` (default True). When the
  حجز-80 writeback is built, OOS lines on a reservation-ENABLED branch can route there instead.

## ✅ POINTS FORMULA CRACKED (2026-08-19) — writer now computes personnewbal
After the blocker below, the formula was reverse-engineered + verified live:

  **personnewbal = Σ per line  floor( line_net × custdiscounts[rep, items.itemcode_alt3] / 100 )**
  rep = CashCust (cash) / HomeDlvry (delivery) via personsdata.personglobalcode.

- The item's **تصنيف خصم التعاقدات for POINTS is `items.itemcode_alt3`** (NOT `itemstoreclassif`,
  which drives line discounts). Found by brute-forcing which item column maps through the CashCust
  `custdiscounts` schedule to the observed rate (`itemcode_alt3` = 39/45; nothing else close).
- **Per-line FLOOR then sum.** Verified EXACT on today's live basket: 404(alt3 12→40%)=15,
  101852(10→40%)=28, 122668(15→30%)=88, 4179(14→20%)=90 → **221** = the native personnewbal.
- Historical mismatches (~2× etc.) are **schedule drift** — custdiscounts rates change over time;
  irrelevant to us because the writer reads the CURRENT schedule at write time (same as SOFTECH's POS).
- **Implemented:** `points.compute_points/order_points` (via new `DiscountAuthorityReader.item_alt3`);
  writer `personnewbal` = `order_points()` on both the live header and the preview; dry-run plan carries
  `points{preview,breakdown,note}`. Guard `POS_BLOCK_POINTS_SALES` default flipped to **False** (points
  sales now allowed — we write the correct personnewbal, which finalization copies → customer earns
  correctly). ⏳ Final live round-trip (write corrected order → finalize → confirm award) pending a
  reachable branch (192.168.1.8 timed out at that moment).

## ⛔ POINTS BLOCKER — finalization COPIES personnewbal (LIVE-PROVEN 2026-08-19)
**First live writes of our writer** (branch 100, PIC 01HD10) settled this definitively:
- Native sale 7005 (`personnewbal=221`) → picpoints +221. OUR writer's sale 7006 (`personnewbal=0`)
  → settled as final doc 7006 with `personnewbal=0` and **NO picpoints row → customer earned 0 points.**
- ⇒ **SOFTECH's finalization COPIES the pending `personnewbal`; it does NOT recompute from lines.**
- `personnewbal`'s per-item value is **not reproducible read-only** (MAX(pharmacydiscp,
  custdiscounts[itemclassifcode]) fit ONE basket, failed 31/32 others) and there's **no DB proc** to
  call — the logic lives in SOFTECH's POS client.
- **Consequence:** our writer CANNOT make an enrolled PIC earn correct points on a cash/delivery sale.
  Contract/insurance earn 0 points, so `personnewbal=0` is CORRECT there — the problem is only
  cash/delivery + identified PIC.
- **Guard added:** `validators.validate_order(for_push)` blocks a points-eligible sale with a PIC from
  the LIVE writer (`POS_BLOCK_POINTS_SALES`, default True) → such sales stay on the native cashier.
- **Writer bug fixed:** the live path called `_vf2_tag` (undefined) instead of `softech_token` in the
  crash-recovery read — surfaced on the first commit (before any write; no residue). Fixed.
- **Writer otherwise validated live:** probe (rollback) + commit both produced a byte-faithful pending
  (serial alloc, stktransm5/stktrans5/branchesales5, verify-readback ok) on branch 100.
- Open decision (points strategy for cash/delivery): keep on native cashier / accept gap + batch
  reconcile / hybrid. Writer stays gated meanwhile.

## PIC loyalty points — PER-ITEM, SOFTECH-computed (final finding 2026-08-19)
Reverse-engineered live against branch-130 finalized sales (`verify_pos_points` command):
- **Points earned at the CASHIER's finalization** (hidden `tr_stktrans` writes the authoritative
  `picpoints` row keyed to the FINAL invoice) — NOT our pending write. We NEVER write the ledger.
- **The award is PER ITEM and NOT reproducible read-only.** Empirical: two `itemstoreclassif=10`
  (Med:Local) items on the SAME cash sale earned 40% and 20%; a cream stored as `itemstoreclassif=10`
  earned 15%, not 40%. The rate tracks the item's internal SOFTECH setup through the hidden
  finalization trigger. Neither `itemstoreclassif`, `itemclassifcode`, nor the CashCust/HomeDlvry
  `custdiscounts` schedule reproduces it. (The screenshots' per-classification % and the earlier
  "value/10" each matched some sales by COINCIDENCE.) ⇒ We deliberately compute NO points figure.
- **Eligibility = channel + enrollment**: cash + delivery carry the programme; contract/insurance = 0;
  customer must be enrolled `localcustomers.picpoints=1`. NOT gated by `items.itempointsys` (=0 items
  still earned). `****` default classification = code `0` (Misc Basic Data), but moot given the above.
- ✅ **Returns DO deduct points — LIVE-CONFIRMED (branch 100, PIC 01HD10, 2026-08-19).** Sale of a
  4-item cash basket: pending `personnewbal=+221` → finalize → `picpoints +221` (doccode 115) →
  balance 221. Full return: pending `personnewbal=−221` → finalize → `picpoints −221` (doccode 30,
  lines carry `r_docnumber`=original final invoice) → balance 0. Symmetric, per-item, ledger keeps
  both rows. (This corrects the earlier wrong "returns don't reverse" note.) Also confirms the whole
  points chain works on HQ (branch 100) via `effective_db_host`, and that `personnewbal` == the award.
- **What we ship (the actual guarantee):** the writeback carries the correct **PIC (phcode)** +
  **channel (ptclassifcode)**, so SOFTECH's finalization awards the right customer the right points.
  We surface **enrollment status** only (verifiable) — `points.channel_earns_points` + `points.is_enrolled`,
  `/points-preview/` → {eligible, enrolled}, and a `PointsBadge`/`MPointsBadge` (footer/plan/receipt,
  web+mobile) showing 🎁 مسجّل — نقاط عند الإنهاء / غير مسجّل / لا نقاط لهذه القناة. NO fabricated number.
- `personnewbal` (pending preview) = **0** — SOFTECH recomputes at finalization. ⚠️ OPEN (needs a test
  instance before going live): confirm finalization RECOMPUTES personnewbal (→ 0 is safe) vs COPIES it
  (→ we must compute it exactly first). Writer stays gated until settled. Tool: `verify_pos_points`.

## Discount reconcile — kill stale/point-system leakage (2026-08-18 #6)
Reported: point-system discount still conflicts with item-posdiscp + user-max on delivery.
Audit result: the ONLY `cust_discp` writes are the suggest reconcile effect + manual input; the
loyalty/points account exposes no discount, so the point system never discounts a line in our
code. Real cause: the auto-apply only ever SET a discount, never CLEARED one — so a % applied
under a previous channel/customer (or contract) survived a switch to delivery. Fix: the reconcile
now, on every fetch, sets EVERY non-manual line to the current channel's value (contract rate, or
**0 for retail** — cap-only, points never discount) and re-clamps any hand-set % to the current
per-item cap. Net: retail lines default to 0 and stale discounts are wiped on channel/customer
change. If a % remains on a retail line it is a manual entry (disc_manual), not the point system.

## Delivery PIC-customer flow (2026-08-18 #5)
SOFTECH delivery = نوع العميل «عميل Delivery» → إسم العميل «Home Delivery Customer» (the account)
→ THEN select an individual **PIC customer** (search/retrieve/select, or add new). Implemented:
a separate `picCustomer` state (distinct from the `customer` account). `needsPicCustomer` =
channel in `PIC_REQUIRED` (delivery). The payload's `softech_pic`/`customer`/`customer_name`
prefer the PIC individual; live validation + the workflow "customer" step require it (dry-run
preview does not). New `PicCustomerRow` (desktop) / `MPicCustomerRow` (mobile) open the existing
`POSCustomerModal` (query/add) via `setPicCustomer`; shown in header band, guided customer stage,
and on the receipt. Cleared when the channel changes away from delivery.

## Branch dropdown filtered to retail POS nodes (2026-08-18 #4)
The POS branch list shows only branches you can transact on: `can_transact` (active +
operational). Hides cancelled branches (110/120/180/190/200/210/220) and Call Center (CC).
HQ (100) is KEPT (used for testing) → dropdown = 100/130/140/150/160/170. Filtered in
`usePosOrder` (both surfaces read `P.branches`); a clamp effect drops any stale/HQ value from
localStorage or `reference.default_branch`, and auto-selects a lone eligible branch. The HQ
`effective_db_host` fix below still stands for any non-POS HQ reads elsewhere.

## HQ (branch 100) store/connection fix (2026-08-18 #3)
Reported: selecting HQ (branch 100) shows no selectable stores / can't process an order.
Root cause: **HQ's `Branch.db_host` is empty** — HQ's SOFTECH lives on the central server, which
`apps/sync` reaches via `settings.SYBASE_HOST` (192.168.1.8), but every POS module connected via
`branch.db_host` directly → empty host → `branch_stores`/`batches`/entities/salespeople/discount
all failed silently (empty stores dropdown).
Fix: added `Branch.effective_db_host` / `effective_db_port` (fall back to `SYBASE_HOST/PORT` when
`db_host` is blank — same convention as `apps/sync.network_health`), and routed ALL POS SOFTECH
connections through it (views: batches, branch-stores, customer-entities, salespeople, discount;
writer, reservation, discount_authority). Store effect now surfaces the read error instead of a
silent empty list. HQ resolves to 192.168.1.8; the 5 retail branches keep their own IPs.

## Done this pass
- Config limits enforced (client + `validators.py`): خصم فكة ≤ 0.50, qty/line ≤ 10000,
  Home-Delivery requires PIC.
- Real El-Rezeiky receipt header/footer + "Print Employee Name of Contract Customer" (web + mobile).
- Contract Emp. Data tab rebuilt to the 12 standard titles (`CONTRACT_EMP_FIELDS`) + تاريخ المطالبة.

## Proposed build (remaining)
1. **نوع العميل → إسم العميل two-level selector** backed by the `Customer` table — DONE.
2. Surface خصم العميل % + patient-pays in the header — DONE.
3. Fill any remaining currency options once captured (card/cheque now out of scope).
