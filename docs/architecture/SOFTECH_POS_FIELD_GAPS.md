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

## Done this pass
- Config limits enforced (client + `validators.py`): خصم فكة ≤ 0.50, qty/line ≤ 10000,
  Home-Delivery requires PIC.
- Real El-Rezeiky receipt header/footer + "Print Employee Name of Contract Customer" (web + mobile).
- Contract Emp. Data tab rebuilt to the 12 standard titles (`CONTRACT_EMP_FIELDS`) + تاريخ المطالبة.

## Proposed build (remaining)
1. **نوع العميل → إسم العميل two-level selector** backed by the `Customer` table — DONE.
2. Surface خصم العميل % + patient-pays in the header — DONE.
3. Fill any remaining currency options once captured (card/cheque now out of scope).
