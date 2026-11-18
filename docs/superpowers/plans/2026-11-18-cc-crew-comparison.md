# Call center: old `CC` figures vs the crew «الكول سنتر» — comparison for owner sign-off

Run 2026-11-18 on the office DB (`elrezeiky_db`), months 2024-08 → 2026-11, with
`manage.py compare_call_center_crew --seed-in-transaction --from 2024-08` (seed rolled back; SOFTECH
returns and Issabel CDR read live, nothing written). Crew = `CallCenterConfig` today: seller codes
62/63/64 and extensions 10/12/15, dated from 2024-08-01. Three figures per month × KPI:
**stored** = today's `CC` rollup (what the KPI board, targets and forecasts read),
**old now** = the old rule recomputed today, **crew** = the crew rule.
The full workbook (6 sheets incl. per person) is attached to the PR conversation, not committed
(it holds names with per-person sales).

## What the comparison says

1. **The crew rule reproduces the old rule.** 162 of 168 month × KPI rows have crew = old-now
   to the piastre. Membership caused no difference (no `membership` rows, no linked-employee
   questions: no payroll employee carries codes 62/63/64 or extensions 10/12/15).
2. **6 rows differ only in returns** (`return_before_membership`): the crew rule credits a return
   to the call center only when the original sale was made by a member inside their dates and
   within 400 days; the old rule matched any earlier sale with that document number.
   - 2024-08 / 2024-09: +264 / +1,369 net sales (returns of sales made before the seed start).
   - **2025-12: +5,966 net sales, +2,266 profit**: returns the old rule matched and the crew rule did
     not — most likely an original sale over 400 days old or a reused SOFTECH document number
     (docnumbers repeat per branch); not traced invoice by invoice yet.
     Owner call: which rule is right for incentives.
3. **The stored figures are stale in places** (`drift_since_build`, old-now = crew, stored differs):
   - **2026-10: stored net sales 661,042 vs 813,175 now (+152,133); profit +5,239; orders +21;
     PIC +10; calls +3.** The CC rollup was built 2026-10-31 04:30, before the month closed, and
     the rollup refresh's staleness check excludes the CC row (`rollup_refresh.month_status`), so
     nothing flagged it for a rebuild. The board shows October's CC sales target at **62.4 %**; the true figure is
     **76.7 %** (profit 52.6 % → 54.7 %, orders 82.0 % → 84.5 %).
   - 2024-08 / 2024-09: stored sales, profit, beauty and orders are **0** (built before the mirror held
     that history); recomputed they are 361,044 / 472,506 sales.
   - Beauty 2025-09, 2025-10, 2026-07, 2026-08: +105, +210, +123, +120 (beauty item classification
     changed since the build).
4. **Not computable / no stored value** (5 cells): PIC count 2024-08…10 and call count
   2024-08/09 have no stored row; recomputed values are in the workbook.
5. **Targets:** `SalesTarget.actual_value()` reads **0** for the four CC targets computed by the KPI
   engine (it looks for invoices of the fake branch `CC`); only the board's rollup shows the real
   figure. Nothing here changes it — that is Part B.

## Owner decisions needed before any figure moves (Part B)

- **A. Historical values:** migrate the stored CC rows value-for-value (spec §6.8b — keeps the stale
  October 2026 and the zero Aug/Sep 2024), or rebuild every month from the crew rule (fixes them; moves
  October's attainment from 62.4 % to 76.7 %, and the 2025-12 returns difference above).
- **B. Returns rule:** keep the crew rule (member + dates + 400 days) or the old rule (any earlier sale
  with that document number) — affects 2025-12 by 5,966.
- **C. Extra PBX agent extensions** 11, 13, 14, 16, 17, 18, 201 (typed `agent` in the PBX table but not in
  the call-center settings): add them to the crew? It would change historical call counts.
- **D. Incentive source after the move:** the board's rollup figure (today's practice) — confirm.
- **E. Seed the crew on the office DB now** (`manage.py seed_call_center_crew`) so «الكول سنتر» shows
  on `/crews` — it changes no figure.

---

## Generated summary (`--md` output)

## مقارنة الكول سنتر: الرقم القديم مقابل الطاقم

الفترة 2024-08 → 2026-11

| المؤشر | metric | المخزن | القديم الآن | الطاقم | الطاقم − المخزن |
|---|---|---:|---:|---:|---:|
| المبيعات (صافي) | cash_delivery | 18,599,689.46 | 19,585,373.06 | 19,592,971.86 | 993,282.40 |
| الربحية | gross_profit | 3,502,336.72 | 3,730,593.08 | 3,734,303.75 | 231,967.03 |
| التجميل | beauty | 1,051,184.04 | 1,090,796.76 | 1,090,796.76 | 39,612.72 |
| عدد الطلبات (مجموع شهري / sum of monthly counts) | customer_count | 19,658 | 20,737 | 20,737 | 1,079 |
| عدد العملاء (PIC) (مجموع شهري / sum of monthly counts) | pic_count | 13,350 | 14,496 | 14,496 | 1,146  3 خانة غير محسوب |
| عدد المكالمات (مجموع شهري / sum of monthly counts) | call_count | 31,292 | 32,010 | 32,010 | 718  2 خانة غير محسوب |

### أسباب الفروق (عدد صفوف شهر × مؤشر)

| السبب | code | العدد |
|---|---|---:|
| مطابق | same | 143 |
| تغيّرت بيانات المبيعات/المرتجعات منذ بناء الرقم القديم | drift_since_build | 14 |
| مرتجع لبيع سابق لبداية العضوية أو أقدم من 400 يوم أو برقم مستند قديم مكرر | return_before_membership | 6 |
| لا يوجد رقم مخزن قديم | no_stored_value | 5 |

### المستهدفات (الفرع الوهمي CC)

| # | metric | الفترة | المستهدف | اللوحة | SalesTarget اليوم | الطاقم | % اللوحة | % الطاقم | ملاحظات |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 505 | beauty | 2026-10-01 → 2026-10-31 | 52,500.00 | 67,795.98 | 0.00 | 68,408.37 | 129.1 | 130.3 | — |
| 506 | call_count | 2026-10-01 → 2026-10-31 | 2,200 | 1,973 | 1,973 | 1,976 | 89.7 | 89.8 | — |
| 512 | cash_delivery | 2026-10-01 → 2026-10-31 | 1,060,000.00 | 661,042.24 | 0.00 | 813,175.54 | 62.4 | 76.7 | — |
| 523 | customer_count | 2026-10-01 → 2026-10-31 | 850 | 697 | 0 | 718 | 82.0 | 84.5 | — |
| 529 | gross_profit | 2026-10-01 → 2026-10-31 | 250,000.00 | 131,507.26 | 0.00 | 136,746.03 | 52.6 | 54.7 | — |

### أسئلة للمالك

1. داخليات PBX من نوع «agent» غير مدرجة في إعداد الكول سنتر: 11, 13, 14, 16, 17, 18, 201 — هل تُضم للطاقم؟ ضمّها يغيّر عدد المكالمات التاريخي.
2. الأرقام التاريخية للكول سنتر: تُنقل قيمةً بقيمة كما هي مخزنة (value-for-value، كما في المواصفات) أم يُعاد بناؤها من أرقام الطاقم؟
3. ملاحظة: SalesTarget.actual_value() يقرأ صفراً لمستهدفات الكول سنتر المحسوبة بمحرك المؤشرات (4 في هذا التقرير) لأنه يبحث عن فواتير الفرع الوهمي «CC»، بينما تعرض لوحة المؤشرات رقم الـ rollup. أي رقم يُعتمد للحافز بعد النقل للطاقم؟
