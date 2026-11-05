# Finance cash journal 2020 (يومية النقدى) — what it tells the ledger

Source: finance's unprotected copy `يومية النقدى  2020 Opened Version.xlsx` (OneDrive\Nabil Makram\يوميات عبد القدوس 2020), read-only on the owner's PC 2026-11-05. **No amounts or names from it are copied here** — only structure, account usage and posting patterns. The file itself must never enter the repo.

## 1. Layout

- 18 sheets. The book itself is **«اليومية الامريكية»**: 111,288 lines, Jan–Nov 2020, one line per account side. Every other sheet is a pivot over it (فيزا، بنوك، الشيكات، سلف، مراجعة …) or a master list.
- Columns that matter (0-based): 0 account code (رقم العملية) · 1 main group · 2 sub-account group · 3 account name · 4/5 customer code/name · 6/7 supplier code/name · 10 payment invoice no. · 11 receive invoice no. · 12 description · 13 **shift no.** · 14 debit · 15 credit · 16 balance · 17 condition (Debt/Credit) · 18 date · 19 month · 20–23 payment cheque no., due date, cheque supplier · 35/36 returns sound/damaged · 40/41 employee code/name · 55 **card settlement batch no. (رقم ترحيلة الفيزا)** · 59/60 **finance's own branch code/name (1–13)** · 64/65 parent company · 69 book («النقدى»).
- **There is no entry number.** `serial`/`code` are empty. Lines of one entry are linked only by date + branch + shift + description; 310 of 318 dates balance on their own. Any importer must group by (date, book, branch, description), as the owner already decided for Plan 3.
- Master sheets usable as import sources:
  - «الموردين» — finance supplier code, name, tax registration no., tax file, credit terms → **GLParty (supplier) seed**.
  - «الموظفين» — finance employee code, name, branch → GLParty (employee).
  - «العملاء» — customer code, name, agreed discount %, credit days, claims/cheques owner → GLParty (customer) + terms.
  - «اكواد الفروع» — finance branch codes 1–13 → SOFTECH branch mapping.
  - «دليل الحسابات» — chart with group, branch, balance-sheet/P&L direction (already imported from the trial balances).

## 2. Daily patterns in the cash book (per branch, often per shift)

| Pattern (description) | Lines | Plan 2 seed rule today |
|---|---|---|
| مبيعات نقدية / مبيعات الوردية — Dr 1302 «بصندوق الإداره» / Cr 6002 | ~7,700 | `sales.cash` ✅ (per branch-day; finance books per **shift**) |
| فيزا — Dr 1327 (بنك مصر) or 1329 (CIB) / Cr 6006, with the card settlement batch no. | ~5,500 | `sales.card` ✅ via card_clearing map; **card → bank settlement not drafted** |
| عجز وزيادة الوردية — 1303 per shift, closed monthly («قيد اقفال العجز والزيادة») into 6002 / 1350 / 3102 | ~7,700 | ❌ no rule |
| دليفري — Dr 3173 «اكرامية توصيل منزلى» / Cr 1302 | ~5,800 | ✅ only if the SOFTECH expense code maps to 3173 |
| كوبون # — coupons through 2354 «دائنون حسابات وسيط» | ~1,560 | ❌ no rule |
| Supplier cash purchase in two legs: Dr 5100 / Cr 2341 (supplier code + invoice no.), then Dr 2341 / Cr 1302 | ~10,900 on 2341 | ⚠️ `supplier.cash` posts Dr 5100 / Cr box directly — net is the same, but the **2341 supplier sub-ledger loses every cash supplier** |
| Branch → HQ cash: branch Dr 2404 / Cr 1302 («تحويل من الفرع الي الرئيسي»); HQ Dr 1301 / Cr the branch's own inter-company account 2405–2423 («وارد باب الحديد» …); 1302 ↔ 1301 «تحويل داخلي» | ~6,500 | ❌ only a generic 1320 treasury transfer; the per-branch inter-company accounts are never used |
| Petty expenses, one line per item (سكر، شاي، ادوات نظافة، مواصلات، شنط …) on 3111/3112/3113/5220 … | ~6,000 | `expenses.box` ✅ (aggregated per branch-day; finance keeps the item line) |
| مرتجعات / خصومات مشتريات نقدية — 5101 / 5102 | ~180 | ❌ (memory: 5101 unreproduced) |
| 6004 «مبيعات H D» — online / marketplace (سوق دوت كوم) via customer 1341 | ~80 | ❌ |
| 5099 «عجز الجرد» — stock-count shortages charged to staff (Dr 1351 / Cr 5099) | ~50 | ❌ (manual or from apps/stockcount) |

## 3. Monthly / manual (stay manual, as planned)

Depreciation (3280–3289 / 1230–1296, «اهلاك الفترة من … حتى …», one line per asset class per month); payroll (3102, 3105, 3107, deductions 1350, staff insurance share 1358, phone contribution 1359, payroll tax 2365, staff financing 1362); accruals 2132; prepaid 1370; partners 2401–2412 (incl. bank certificate interest «فوائد شهادات» on 2402/1315); bank charges 3128 / overdraft interest 3150; credit sales **6003 booked once a month per company** («مطالبة شهر …») — finer than finance's practice if drafted per day.

## 4. What should change (proposed, for the owner / Plan 2 + Plan 3 owners)

1. **Branch → HQ cash transfers** with the per-branch inter-company accounts (2404 at the branch, 2405–2423 at HQ), plus 1302 ↔ 1301 internal transfers. Largest gap by value.
2. **Cash purchases through 2341 with the supplier**, so supplier statements match finance's.
3. **Shift over/short (1303)** per shift, with finance's monthly closing.
4. **Coupons (2354)** — confirm the source (apps/vouchers redemptions or a SOFTECH tender) and post them.
5. **Card settlement** (1327/1329 → bank) keyed on the settlement batch no.
6. Optional: shift granularity for cash sales; month granularity for 6003 claims; rules for 5101/5102, 6004 and 5099.
7. **Party import** from «الموردين» / «الموظفين» / «العملاء», and finance branch codes from «اكواد الفروع».
