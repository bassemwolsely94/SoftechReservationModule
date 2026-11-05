# Finance 2020 workbooks (credit journal, October, quick bank, KPI, position) — what they tell the ledger

Companion to `2026-11-05-cash-journal-2020-findings.md` (read that first; its five gaps are not repeated). Sources: finance's decrypted 2020 copies, read-only, in a scratch folder on 2026-11-05. **No amounts, person, supplier or customer names, or bank account numbers are copied here** — only structure, account codes, patterns and formulas. The files never enter the repo.

Workbooks: يوميات الاجل 2020 (credit book), يومية اكتوبر 2020 (October), البنك السريع 2020 (quick bank), مؤشر مالى تسع شهور 2020 (nine-month indicator), مركز 30-9-2020 (position, old `.xls`).

## 1. Workbooks at a glance

| Workbook | What it is | Relation |
|---|---|---|
| Credit journal | Book «الاجل», sheet «اليومية الامريكية»: ~35.8k lines, Jan–Oct 2020, ~82 % at HQ (finance branch 1). Plus pivots: «مهم», «متابعة الشيكات», «ايصال ضرائب», «بنوك», «تقارير المراجعة 2020», «Sheet1», «مراجعة 1», and the same master sheets as the cash book (الموردين، العملاء، الموظفين، دليل الحسابات، اكواد الفروع). | Second half of every cross-book entry (see 2354 below). |
| October journal | Sheet «اليومية»: ~8.3k lines, October only, **cash-book** content (1302 tills, shifts, 1303, delivery, coupons, branch→HQ transfers) in a new file. Pivots «1301», «1302», «سلف». | Continues the cash book after 30-9; credit book's own October lines stay in the credit file. |
| Quick bank | Not a ledger. A **daily bank position and post-dated-cheque forecast**: one sheet per bank/facility account (one row per calendar day, extended to 2023–2024), a cheque register «الشيكات», pivot «مجمع الشيكات», consolidated sheets per bank. | Its cheques are the 2343 lines of the credit book; its accounts are 1310–1339. |
| Nine-month indicator | Branch P&L with HQ-cost allocation in three variants + expense pivots. Formulas live (section 4). | Inputs come from the position workbook / trial balance and SOFTECH cost-of-sales ratios. |
| Position 30-9-2020 | 35 pivot/statement sheets: trial balance (9 months), branch trial balance, party balances, trading & P&L (SOFTECH-stock and book-stock variants), H1/Q1/Q2 comparisons, balance sheet, branch P&L with allocation, financial ratios. Many cells are `#N/A`/`#REF!` (broken links); several statements say 1-1…30-6-2020 though the file is named 30-9. | The source the coa_import trial-balance format was taken from. |

## 2. Journal sheet layout (credit book vs cash book vs October)

Same column positions as the cash book (0 account code · 1–3 group/sub-group/account name · 4/5 customer code/name · 6/7 supplier code/name · 8 serial · 9 code · 10/11 invoice nos. · 12 description · 13 shift · 14 debit · 15 credit · 16 balance · 17 condition · 18 date · 19 month · 20–23 payment cheque no./due date/cheque supplier code/name · 26–29 received cheque no./due date/customer code/name · 30 withholding-tax 1 % supplier · 31/32/34 due month/date/year of notes payable · 35–38 returns sound/damaged/discount/tax · 40/41 employee · 55 card settlement batch · 59/60 finance branch code/name · 61 supplier classification · 64/65 parent company). Differences:

- **Credit book has no book column** (header ends at col 68 «رصيد 2018»); the cash book has col 69 «النقدى». Plan 3's importer looks for a book column — for this file the book must come from the file, not a column.
- `condition` also takes **«Nothing»** (zero lines). `serial`/`code` empty (no entry number), as in the cash book.
- Cols 24/25 and 31/32/34 carry placeholder text on every row (filler) — not data.
- October: cols 10/11 renamed **«رقم الوارد» / «رقم الصادر»** (HQ treasury receipt / payment voucher numbers — new, usable as entry refs for 1301); col 56 «البنك»; col 70 «التقفيلات السليمة»; 1302's group/name lookups are broken (empty) because the account was renamed «* بصندوق الإداره»; 1327/1329 now sit under sub-group «النقديه بالبنوك» (credit/cash books: «المقبوضات التجاريه»); 6004 renamed «مبيعات اطلب» (marketplace customer code 75). October uses **no account the 9-month cash book doesn't**.
- **Grouping:** by (date, branch, description) 5,095 of 6,248 groups balance; 278 of 307 dates balance. Purchases group cleanly (description = invoice no.), but **returns and discounts do not**: the 5105/5106/5121/5122 side carries a text description («م تالف»، «م من الفاتورة»، «جبر كسور») while the 2341 side carries the document number, so a (date, book, description) grouping marks them unbalanced. Fallback needed: (date, branch) for those accounts.

## 3. Credit-book posting patterns

Accounts the credit book uses that the cash book never does: 1307, 1310, 1311, 1316, 1323, 1325, 1326, 1331, 1332, 1335, 1336, 1337, 1339, 1343, 1344, 1345, 1354, 1357, 2360, 2361, 2362, 2363, 2364, 2367, 3109, 3124, 3135, 3147, 3153, 3158, 3162, 3175, 3178, 3184, 3190, 3200, 5104–5109, 5120–5122, 6015, 6018, 6020.

| Flow | Pattern | Notes |
|---|---|---|
| Credit purchase, per invoice | Dr 5104 (medicine) or **5120 (accessories)** [+ Dr **2363** input VAT] / Cr 2341 + supplier code; description = invoice no. | ~5.5k invoices; 1 supplier per entry. 2363 = 14 % of the base on fully taxable (accessory/cosmetic) invoices, a small fraction on mixed invoices (only some lines taxable). Supplier class (col 61: اجل/نقدى/مستورد/محلى) on ~8 % of 2341 lines. |
| Purchase returns | Dr 2341 / Cr **5105** (medicine) or **5121** (accessories); description = return type: «م تالف» damaged, «م من الفاتورة» from invoice, «م خارج المطالبة» outside the claim. | 2364 (VAT on returns) used twice, zero value — **finance does not reverse input VAT on returns**. |
| Purchase discounts | Cr **5106** / **5122** vs Dr 2341: mostly «جبر كسور» (rounding on payment), «خصم اضافى %», supplier rebates/offers, bounced-cheque cost differences. | 5107–5109 = small cash purchases kept in the credit book. |
| Supplier payment by cheque | Dr 2341 / Cr **2343** with cheque no., due date, cheque supplier code (cols 20–23) [+ Cr **2361** 1 % withholding]. | Maturity: Dr 2343 / Cr **facility/overdraft account** (1332, 1331, 1337, 1316…) «سداد الشيكات المقدمة للدفع». 2343 also funds HQ cash: Dr 1301 / Cr 2343 «تمويل الخزينة»; and pays rent/operating fees via 2351. |
| Credit sales (companies, insurers, institutions) | **Monthly, per company, at the branch that served it**: Dr 1341 (customer code) / Cr 6003 «مطالبة شهر …». Agreed discount separately Dr **6021** / Cr 1341 «خصم متفق علية». Extra/administrative discount Dr **6023** / Cr 1341. Returns Dr **6018** / Cr 1341 (rare). | **Co-payment reclass «المشاركة»**: Dr 6002 / Cr 1341 — the patient's share already sits in cash sales, so it is moved out of 6002 against the claim. Credit sales are booked at branches 1, 2, 6, 8, 12…, not only HQ. |
| Customer collection | Cheque received: Dr **1343** / Cr 1341 «سداد مطالبة …» (+ Dr **1357** / Cr 1341 for the customer's 1 % withholding «ضرائب 1%»). Sent to bank: Dr **1344** / Cr 1343 «ارسال الشيكات للبنك …». Collected: Dr bank / Cr 1344 «تحصيل شيكات العملاء» + Dr 3128 collection commission. Bounced: **1345**. Some collected in cash at HQ: Dr 1301 / Cr 1343 or 1341. | Cheque no./due date/customer in cols 26–29. |
| Card settlement | Dr bank (1335 for one acquirer, 1310 for the other) / Cr 1327 / 1329 «تحصيل فيزا …», keyed by **settlement batch no. (col 55)**; refunds «رد فيزا»; fees Dr **3124** «مصاريف الفيزا عن شهر …» monthly (Jan–Mar only, later apparently netted). | This is the missing half of cash-note gap 5. |
| Coupons | Credit book: Dr **6020** «خصومات (كوبونات)» / Cr **2354** per coupon number. Cash book: Dr 2354 / Cr 1302. Net: **Dr 6020 / Cr branch till**. | Answers cash-note gap 4. 6020 sits in group «مصروفات بيع وتوزيع» (selling expense), not contra-revenue. |
| **2354 = cross-book clearing** | Every entry split between the two books goes through 2354: coupons, branch utility bills (credit: Dr 3116/3119/3169 / Cr 2354; cash: Dr 2354 / Cr 1302), HQ cash deposits («ايداع ح#»: cash Dr 2354 / Cr 1301; credit Dr 1320 / Cr 2354; then Dr bank / Cr 1320). | Nets to ~0 on the 9-month trial balance. A single ledger doesn't need it; an importer of 2020-style history must not treat it as a real creditor. |
| Banks | HQ cash → bank: Dr 1320 / Cr 1301, Dr 1316 / Cr 1320 «الايداع النقدى». Bank ↔ facility transfers «محول من ح … الى ح …» (1316 ↔ 1332 etc.). Facility interest & fees monthly Dr **3150** «عائد مدين / فائدة مدينة / عمولة اعلى رصيد / الدمغة النسبية»; charges Dr **3128**. Bank loan **1311** with deferred interest. | All from bank statements. |
| VAT | Input: 2363 per purchase invoice. **Output: monthly carve-out from cash sales — Dr 6002 / Cr 2362** «ضرائب القيمة المضافة <month>» (sales are booked VAT-inclusive daily). 2365 payroll tax yearly; 2367 general/annual tax. | 2366 not used in 2020. |
| Withholding tax (supplier side) | Cr **2361** 1 % at source when paying suppliers/service providers; sheet «ايصال ضرائب» prints the receipt (1 % or 3 %) from the supplier master (tax card no., file no., tax office); «بنوك» holds the quarterly register (supplier, address, registration/file no., office, transaction amount, rate, tax). | Supplier master must carry tax registration, file no., office. |
| Social insurance (monthly, per branch) | Dr **3109** company share + Dr **1358** employee share / Cr **2360**; paid Dr 2360 / Cr 2404 (branch) or 1301. 3158 emergency fund monthly. | Salaries themselves are in the cash book (3102 etc.). |
| Rent / operating fee | Dr **3200** «مقابل تشغيل الصيدلية» or 3126 rent / Cr 2351, 2343, 2354 or the sister-company account 24xx; HQ paying a branch's rent: Dr 2406/2417… / Cr 1301. | Fixed monthly amounts per branch — recurring-entry candidates. |
| Prepaid / insurance / accruals | 1370 → 3135 (fire & theft), 3175 (vehicle) «بمعدل … لليوم / شهرى»; 1353 deposits paid; 2132 accrued expenses (utilities, maintenance contracts). | Amortisation schedules. |
| Fixed assets | Dr 1140–1190 / Cr 2351 with invoice no. (no depreciation in this book; depreciation is in the cash book). | |
| Other | 6015 insurance compensation income; 2367/2409 prior-year tax and solidarity contribution (3178) closed to retained earnings; 3166 «فروق القرش» and 3189 e-payment fees on branch utility payments. | |

## 4. Nine-month indicator — every KPI and formula

Sheets «بدون توزيع» (nine months, no allocation), «توزيع بنسبة المبيعات» and «توزيع 50%» (one month, allocated), «اجمالى المصاريف» and «بنود المصاريف» (expense pivots by sub-group × branch). Columns B…N = HQ + 12 branches, O = total, P = % of total sales. Per branch column:

| Row | KPI | Formula |
|---|---|---|
| 1 | نسبة التحقيق (target achievement) | sales ÷ target (row 2) |
| 2 | التارجت الشهرى | input per branch (nine-month sheet: the period target; monthly sheets: monthly) |
| 3 | نسبة مجمل الربح | gross profit ÷ sales |
| 5 | المبيعات | input (net sales per branch) |
| 6 | تكلفة المبيعات بنسبة سوفتيك | input: **SOFTECH cost of sales per branch** (not ledger purchases ± stock) |
| 7 | مجمل الربح | sales − cost |
| 8–11 | المصاريف العمومية / التمويل / البيع والتوزيع / التشغيل | inputs per branch by expense group (`P = O ÷ O5`). Cols Q, R hold two deductions and **S = O − Q − R** (unlabelled — ask finance what Q and R exclude) |
| 12 | توزيع مصاريف الرئيسى | sales-share sheet: branch sales ÷ total sales × HQ expenses (HQ expenses = sum of HQ general + financing + selling); 50 % sheet: **HQ keeps 50 %, the other 50 % is split equally across the 11 branches** (`A24 = A27/2`, `B24 = A24/11`) |
| 13 | توزيع اهلاكات الرئيسى | branch sales ÷ total × HQ depreciation (separate line) |
| 14 | الاهلاكات | nine months: actual per branch; monthly sheets: **estimate = 1 % of sales** |
| 15 | اجمالى المصاريف | sum rows 8–14 |
| 16 | صافى الربح | gross profit − total expenses; `O24 = O16 / 9` average month; monthly sheets compare with the nine-month net (`O24 = O16 − O17`) |
| «بنود المصاريف» | each expense account's share | account ÷ its group total; group ÷ grand total |

## 5. Position 30-9-2020 — statements vs statements.py / coa_import.py

- **Groups:** every group on the 9-month trial balance is in `GROUP_MAP` (incl. «محزون أول المده» 5301, «مجمع الإهلاك», «شركات شقيقة», «الهيئه العامه للتأمينات الاجتماعيه»). Accounts present in 2020 worth checking against the imported chart: 1120–1125 (usufruct / goodwill / premises), 1144, 1161–1165, 1171, 1190, 1296; 1307, 1315/1322/1324/1328/1338 (partner-held bank accounts kept as company bank accounts); 1350, 1359, 1360 «حسابات معلقة», 1362, 1363; 2359 «صندوق الزمالة»; 3121, 3134, 3136, 3141, 3157, 3174, 3177 (FX differences), 3185, 3192, 3194/3195 (marketplace delivery / commission), 5099, 5222/5223, 6014, 6019. `BS_LINE_BY_ACCOUNT` puts 1329 in receivables but not 1327 (group default gives the same line — fine).
- **Trading account in two variants**: «الختامية بسوفتيك» (closing stock = SOFTECH stock at cost) and «الختامية بالدفترى» (book). Plan 3 covers the SOFTECH variant; the book variant + the difference («قد تكون فروق تقيم المخزون») is not a report today.
- **Stock adjustments before closing stock** («الارصدة» / «المخزون»): per-store SOFTECH stock at sale price and cost, margin, monthly sales at cost, stock cover; HQ split into medicines / shortages / expired medicines / accessories / expired accessories; **customer-gift stock excluded**; a check valuation «تسعير المخزون 80%» (stock at 80 % of sale price).
- **Branch P&L**: finance's «الختامية فروع» uses **SOFTECH cost of sales per branch**; `branch_pl` uses ledger trading lines by branch, so with credit purchases booked at HQ every branch's gross profit is wrong. Allocation: sales share (exists) plus the 50 % method and separate HQ-depreciation allocation (section 4) — not in `statements.py`.
- **Comparisons**: half-year vs half-year, quarter vs same quarter last year, with a «التغير» column («مقارنة الدفترى»، «مقارنة سوفتيك»، Sheet1/2/3/5/7). `comparison(years)` is yearly only.
- **Balance-sheet layout** («الميزانية»): fixed assets cost / accumulated depreciation / net per class; current assets (closing stock, customers, sundry debtors, partners' current, deposits with others, cash & banks); current liabilities (creditors, notes payable, suppliers); working capital; total investment; financed by capital, partners' current, P&L. Same lines as `financial_position`, plus explicit **working capital** and **total investment** subtotals.
- **Sales classification** per branch (medicine / accessories / body-building / veterinary / other / customer gifts) — from SOFTECH, not the ledger.
- **Party sheets**: suppliers (2341 by supplier code), creditors (2351), employees (1351 by employee code), customers (1341), notes payable by due year/month/cheque, deposits with others (1353 by description), prepaid (1370), accrued (2132), monthly sales & purchases and expense pivots by month.
- **Financial ratios «المؤشرات»** (all ×100 where a percentage): current ratio = current assets ÷ current liabilities; quick ratio = liquid assets (current assets − stock − hard-to-collect debtors) ÷ current liabilities; cash turnover = period sales ÷ liquid assets; LT loans ÷ equity; total debt ÷ equity; LT loans ÷ total assets; fixed assets ÷ equity; gross margin, net margin, cost-of-sales ratio (÷ sales); ROA = net profit ÷ total assets; ROIC = net profit ÷ invested capital; ROE = net profit ÷ equity; inventory turnover = COGS ÷ ((opening + closing stock) ÷ 2); receivables turnover = credit sales ÷ ((opening + closing debtors) ÷ 2); DSO = debtors ÷ (annual sales ÷ 360); total-asset turnover; invested-capital turnover = sales ÷ invested capital.

## 6. Quick bank file — what the ledger would need

- Per bank / facility account, one row per day: customer cheques, deposits, transfers in/out, certificate coupons, card collections, withdrawals, interest & fees, **running balance**, **facility limit** (changes over time), **remaining facility** (limit + balance), description. Withdrawals are `SUMIF` over the cheque register on (account key + presentation date), so **future rows project the balance from issued post-dated cheques**. Consolidated sheets sum all accounts per bank per day.
- Cheque register «الشيكات»: bank, account, drawing (discount) account, cheque no., supplier code → name (VLOOKUP to the supplier list), amount, cheque date, presentation date, month/year, issue date, branch; statuses in the date columns: **void «لاغى», bounced «مرتد», guarantee cheque without date «ضمان بدون تاريخ», cash «نقدى»**. ~3.8k cheques 2017–2021, ~575 dated 2020.
- «مجمع الشيكات»: cheques by presentation date × drawing account for the month. Credit-book «مهم»: per supplier the latest cheque due date and the latest month paid (paid-through tracking); «متابعة الشيكات»: 2343 open cheques by due year/month — Plan 3 Task 5's notes-payable sub-ledger reproduces this one.
- It is **not** a bank reconciliation (no statement lines are matched). Ledger needs: a cheque register on 2343 (drawing bank account, issue date, due date, status incl. void/bounced/guarantee), facility limits per bank account with effective dates, and a **cash-position forecast** (book balance + scheduled maturities − facility headroom per day). Bank-statement import would only be needed for actual reconciliation (fees, interest, card settlements).

## 7. Gap list against seed.py RULES and Plan 3 (beyond the cash note's five)

Marking: **S** = buildable from SOFTECH · **M** = manual entry / template · **O** = owner (or finance) decision first.

| # | Gap | Mark |
|---|---|---|
| 1 | Accessory purchases on 5120 / 5121 / 5122 — `purchases.hq` posts everything to 5104/5105. Needs item class or supplier class per invoice line. | S (+ O on the classification rule) |
| 2 | Input VAT 2363 on purchase invoices — `purchases.hq` has no VAT line; finance books Dr 5104/5120 net + Dr 2363. Touches the VAT-inclusive cost question already flagged on purchasing. | S, stop-and-confirm |
| 3 | VAT on purchase returns (2364): finance doesn't reverse it; a SOFTECH-driven rule would. | O |
| 4 | Purchase discounts 5106/5122 (rounding on payment, extra %, rebates) — no rule. | S for invoice-level discounts, M for rebates |
| 5 | Return type (damaged / from invoice / outside claim) is kept in the description; finance's review pivots use it. | S (doc type) + O (tag or sub-account) |
| 6 | Output VAT: finance carves VAT out of 6002 monthly (Dr 6002 / Cr 2362); rules post daily sales — decide VAT-exclusive daily vs monthly carve-out, and which SOFTECH tax field reproduces it. | O, then S |
| 7 | Credit-sales rule granularity and branch: finance books per company **per month per branch**; `sales.credit` is party-day at HQ. | O (granularity), S |
| 8 | Co-payment reclass «المشاركة» (Dr 6002 / Cr 1341) — no rule; double-counts sales if claims are drafted gross. | S if SOFTECH splits patient/company share, else O |
| 9 | 6023 administrative / contract-difference discounts and 6018 credit returns. | M |
| 10 | Customer withholding 1357 at collection — `customer.collection` credits 1341 with the bank amount only. | M (or S if the receipt carries it) |
| 11 | Received-cheque lifecycle 1343 → 1344 → bank, bounced 1345, collection commission 3128 — `customer.collection` debits the bank directly. | S for receipt, M for status steps |
| 12 | Supplier withholding 2361 (1 %/3 %) on payments, receipts and the quarterly register — no rule; GLParty has no tax-registration fields. | O (rates per supplier), then S |
| 13 | Cheque maturity paid from the **facility account the cheque was drawn on** (1332/1331/1337/1336); `cheque.maturity` uses the treasury bankcode map. Needs drawing account per cheque. | S if SOFTECH cheque has the account, else M |
| 14 | Cheque register statuses (void, bounced, guarantee, cash) and facility limits / cash-position forecast (quick bank). | M (+ O on scope) |
| 15 | 2343 used outside supplier payments: treasury funding Dr 1301 / Cr 2343, rent and operating-fee cheques via 2351. | M |
| 16 | Card settlement per batch with fees 3124 and refunds — refines cash gap 5: credit side is 1327/1329 keyed by batch no. | M or bank-statement import (O) |
| 17 | Coupons — refines cash gap 4: one rule Dr 6020 / Cr till per branch-day is enough in a single ledger. | S (source confirmation) |
| 18 | 2354 cross-book clearing: Plan 3's importer must expect it, net it per pair, and not flag it as a creditor; decide whether imported history keeps it. | O |
| 19 | Importer format: credit book has **no book column**, returns/discounts don't balance by description (needs (date, branch) fallback), `condition` = «Nothing» rows, filler text in cols 24/25/31/32/34, October file renames cols 10/11 and loses 1302's lookups. | build into Plan 3 Task 8 |
| 20 | Bank interest/fees 3150/3128, bank↔facility transfers, loan 1311 — no rules. | M (or bank-statement import, O) |
| 21 | Monthly recurring entries: social insurance (3109/1358/2360, 3158), rent/operating fee 3200 per branch, prepaid amortisation (1370 → 3135/3175), accruals 2132. Ledger has no recurring-template feature. | M + O (templates) |
| 22 | Fixed-asset additions via 2351 and no asset register (depreciation stays manual per class). | M |
| 23 | Branch P&L COGS: finance uses SOFTECH cost of sales per branch; `branch_pl` uses ledger lines. | S |
| 24 | Allocation variants: 50 % HQ / 50 % equal split across branches; HQ depreciation allocated as its own line; monthly depreciation estimate 1 % of sales. | O, then code |
| 25 | Target achievement per branch (needs branch targets; doc 16 forecasting has them). | S/O |
| 26 | Quarter / half-year comparisons with change column; book-stock vs SOFTECH-stock trading variants; working-capital / total-investment subtotals; ratio sheet (section 5). | code only |
| 27 | Stock adjustments behind closing stock: exclude customer-gift stock, show expired/shortage stores separately, 80 %-of-price check. | S + O |
| 28 | KPI sheet's unexplained Q/R deduction columns. | O (ask finance) |
| 29 | Partner-held bank accounts (1315, 1322, 1324, 1328, 1338) inside the company's cash. | O |
