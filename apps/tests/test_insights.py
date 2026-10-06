"""
apps/tests/test_insights.py  (doc 18)

Exercises the narrative engine end-to-end on synthetic data: a rule fires,
findings persist, and the bilingual narrative renders.
"""
from datetime import datetime, date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.catalog.models import Item, Category
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.models import ChannelBucketMap
from apps.insights.engine import InsightEngine


class InsightsEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='970', code='970', name='Ins Test',
                                      name_ar='فرع الاختبار', is_operational=True)
        cls.cust = Customer.objects.create(name='c', softech_pic='PICI', softech_id='C-I')
        cls.med = Item.objects.create(softech_id='INM', name='دواء', medicine_type='10')
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='cash',
                                        bucket='cash', counts_customer=True, include_in_profit=True, active=True)

        def inv(ref, when, total, user):
            ph = PurchaseHistory.objects.create(customer=cls.cust, softech_invoice_id=ref, branch=cls.b,
                 doc_code='115', total_amount=Decimal(total), invoice_date=when, sales_channel='91',
                 sales_person_type='10', softech_user=user, softech_phcode='PIC-' + ref)
            PurchaseHistoryLine.objects.create(purchase=ph, item=cls.med, quantity=Decimal(1),
                 unit_price=Decimal(total), line_total=Decimal(total), cost_at_sale=Decimal(10), list_price=Decimal(total))
            return ph

        # target day 2026-06-10 (Wed). Daily branch_vs_prev now triggers on the
        # SAME-WEEKDAY-LAST-WEEK comparison → seed 2026-06-03 (Wed) high, target day low.
        inv('LW', timezone.make_aware(datetime(2026, 6, 3, 12)), 100000, '500')   # same weekday last week (baseline)
        inv('P1', timezone.make_aware(datetime(2026, 6, 9, 12)), 100000, '500')   # previous day (shown for context)
        inv('P2', timezone.make_aware(datetime(2026, 6, 10, 12)), 1000, '500')    # big drop
        # a bulk sale on target day
        inv('BULK', timezone.make_aware(datetime(2026, 6, 10, 13)), 30000, '501')

    def test_generate_day_report_bilingual(self):
        run = InsightEngine.run(period_type='day', ref_date=date(2026, 6, 10))
        self.assertEqual(run.period_type, 'day')
        self.assertGreater(run.findings_count, 0)
        # bilingual narratives rendered
        self.assertIn('التقرير السردي', run.narrative_ar)
        self.assertIn('board report', run.narrative_en)
        # branch drop rule fired
        codes = set(run.findings.values_list('rule_code', flat=True))
        self.assertIn('branch_vs_prev', codes)
        # bulk sale detected (30000 ≥ default 20000)
        self.assertIn('bulk_sale', codes)

    def test_no_findings_reads_clean(self):
        # a quiet period (no data) → no findings, clean message
        run = InsightEngine.run(period_type='day', ref_date=date(2020, 1, 1))
        self.assertEqual(run.findings_count, 0)
        self.assertIn('لا توجد ملاحظات', run.narrative_ar)


class InsightsBottomRankingTests(TestCase):
    """Underperformer (bottom-N) rankings: a large-enough salesperson field produces ranked
    laggard boards on the chain report, and each flagged rep sees it in their own report."""
    DAY = date(2026, 6, 17)

    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='971', code='971', name='Bottom Test',
                                      name_ar='فرع الأدنى', is_operational=True)
        cls.med = Item.objects.create(softech_id='BNM', name='دواء ب', medicine_type='10')
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='cash',
                                        bucket='cash', counts_customer=True, include_in_profit=True, active=True)
        when = timezone.make_aware(datetime(2026, 6, 17, 12))
        # 9 reps (> bottom_min_pop=8) with strictly increasing sales so the ordering is
        # deterministic: rep 801 lowest … rep 809 highest. 6 invoices each (> daily min_active=5)
        # so they are 'active' for the per-rep profile too.
        for i in range(1, 10):
            user = f'80{i}'
            per = i * 1000
            for j in range(6):
                ref = f'{user}-{j}'
                cust = Customer.objects.create(name=f'c{ref}', softech_pic=f'PIC{ref}', softech_id=f'C{ref}')
                ph = PurchaseHistory.objects.create(customer=cust, softech_invoice_id=ref, branch=cls.b,
                     doc_code='115', total_amount=Decimal(per), invoice_date=when, sales_channel='91',
                     sales_person_type='10', softech_user=user, softech_phcode=f'PH{ref}')
                PurchaseHistoryLine.objects.create(purchase=ph, item=cls.med, quantity=Decimal(1),
                     unit_price=Decimal(per), line_total=Decimal(per), cost_at_sale=Decimal(10),
                     list_price=Decimal(per))

    def test_bottom_board_emitted_and_ordered(self):
        run = InsightEngine.run(period_type='day', ref_date=self.DAY)
        bottoms = list(run.findings.filter(category='bottom'))
        self.assertTrue(bottoms, 'expected at least one bottom (underperformer) ranking finding')
        # the chain narrative gets its own bottom section
        self.assertIn('الأدنى أداءً', run.narrative_ar)
        self.assertIn('Bottom performers', run.narrative_en)
        # a cash-sales bottom board lists the LOWEST reps (801) and not the top rep (809)
        cash_bottoms = [f for f in bottoms if 'البيع النقدى' in f.message_ar or 'cash' in f.message_en.lower()]
        self.assertTrue(cash_bottoms)
        f = cash_bottoms[0]
        self.assertIn('801', f.message_ar)          # worst rep present
        self.assertNotIn('809', f.message_ar)       # best rep excluded from the bottom board

    def test_bottom_findings_stay_off_the_attention_list(self):
        # underperformer boards render under their own header, never in "Top items to act on"
        run = InsightEngine.run(period_type='day', ref_date=self.DAY)
        ar = run.narrative_ar
        act_idx = ar.find('تحتاج انتباه')
        bot_idx = ar.find('الأدنى أداءً')
        self.assertNotEqual(bot_idx, -1)
        if act_idx != -1:
            # the attention block ends before the bottom section begins
            self.assertLess(act_idx, bot_idx)

    def test_cash_exbulk_rankings_both_thresholds(self):
        run = InsightEngine.run(period_type='day', ref_date=self.DAY)
        fs = list(run.findings.filter(rule_code='cash_exbulk_ranking'))
        self.assertTrue(fs, 'expected ex-bulk cash-sales ranking findings')
        # a SEPARATE remark for each floor (5,000 and 10,000)
        self.assertTrue(any('≥5,000' in f.message_ar for f in fs))
        self.assertTrue(any('≥10,000' in f.message_ar for f in fs))
        # at the 10k floor every rep qualifies → both a top and a bottom salesperson board,
        # ordered by everyday cash value (rep 809 highest … 801 lowest)
        sp10 = [f for f in fs if 'مسئولي البيع' in f.message_ar and '≥10,000' in f.message_ar]
        top = [f for f in sp10 if f.category == 'highlight']
        bot = [f for f in sp10 if f.category == 'bottom']
        self.assertTrue(top and bot)
        self.assertTrue(any('809' in f.message_ar for f in top))
        self.assertTrue(any('801' in f.message_ar for f in bot))

    def test_flagged_rep_sees_it_in_own_report(self):
        run = InsightEngine.run(period_type='day', ref_date=self.DAY)
        # rep 801 has the lowest (distinct) sales → flagged for sales in their personal profile.
        # The flag clause writes 'المبيعات (#…' (parenthesised), distinct from the rank line's
        # 'المبيعات #…' — so this asserts a genuine sales bottom-flag.
        body = InsightEngine.render_for_salesperson(run, '801', 'ar')
        self.assertIsNotNone(body)
        self.assertIn('ضمن الأدنى', body)
        self.assertIn('المبيعات (#', body)
        # rep 809 has the highest (distinct) sales → never flagged for sales
        top = InsightEngine.render_for_salesperson(run, '809', 'ar')
        self.assertIsNotNone(top)
        self.assertNotIn('المبيعات (#', top)


class InsightsPurchasingKpiTests(TestCase):
    """New purchasing KPIs on procurement.PurchaseLine: supplier-category value, invoice count,
    input VAT, expiry returns, and the enriched HQ at-a-glance — chain + HQ + per-branch."""
    DAY = date(2026, 7, 15)

    @classmethod
    def setUpTestData(cls):
        from apps.procurement.models import PurchaseLine
        cls.hq = Branch.objects.create(softech_branch_id='100', code='100', name='HQ',
                                       name_ar='المخزن الرئيسي', is_operational=True)
        cls.br = Branch.objects.create(softech_branch_id='130', code='130', name='Nozha',
                                       name_ar='النزهة', is_operational=True)
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='cash',
                                        bucket='cash', counts_customer=True, include_in_profit=True, active=True)

        def line(branch, supplier, doc, item, cat, net, vat=0, is_return=False, rtype='', buyer=''):
            PurchaseLine.objects.create(
                branch_code=branch, supplier_code=supplier, doc_number=doc, doc_date=cls.DAY,
                item_code=item, doccode=('120' if is_return else '10'), is_return=is_return,
                raw_qty=Decimal(1), raw_value=Decimal(abs(net)), unit_price=Decimal(abs(net)),
                cost_price=Decimal(abs(net)), net_qty=Decimal(-1 if is_return else 1),
                net_value=Decimal(-abs(net) if is_return else net), supplier_category=cat,
                vat_value=Decimal(vat), return_type=rtype, buyer_code=buyer)

        # HQ: 2 suppliers / 2 categories / 2 invoices, VAT, one buyer, plus an expiry return
        line('100', 'S1', 'INV1', 'A', 'OFFICIAL_DISTRIBUTOR', 60000, vat=8400, buyer='B100')
        line('100', 'S2', 'INV2', 'B', 'MANUFACTURER', 40000, vat=5600, buyer='B100')
        line('100', 'S1', 'RET1', 'A', 'OFFICIAL_DISTRIBUTOR', 2000, is_return=True, rtype='expiry')
        # Branch 130: local small-warehouse buying above the 5000 floor
        line('130', 'S3', 'INV3', 'C', 'SMALL_WAREHOUSE', 6000)

    def _run(self):
        # week window (ends on DAY) so the week/month-only rules (e.g. expiry returns) also run
        return InsightEngine.run(period_type='week', ref_date=self.DAY, domain='purchasing')

    def test_hq_at_a_glance(self):
        run = self._run()
        f = run.findings.filter(rule_code='hq_purchase_summary').first()
        self.assertIsNotNone(f)
        self.assertIn('100,000', f.message_ar)       # net HQ value
        self.assertIn('فاتورة', f.message_ar)         # invoice count present
        self.assertIn('مورد', f.message_ar)           # supplier count present

    def test_supplier_category_values_chain_hq_branch(self):
        run = self._run()
        fs = list(run.findings.filter(rule_code='purchase_supplier_category'))
        keys = {(f.scope_type, f.scope_key) for f in fs}
        self.assertIn(('chain', ''), keys)
        self.assertIn(('branch', '100'), keys)       # HQ
        self.assertIn(('branch', '130'), keys)       # retail branch (≥5000 floor)
        chain = next(f for f in fs if f.scope_type == 'chain')
        self.assertIn('موزّع رسمي', chain.message_ar)  # official distributor value shown
        self.assertIn('مصنع', chain.message_ar)         # manufacturer value shown

    def test_invoice_count_and_vat_and_expiry(self):
        run = self._run()
        # invoice count: chain = 3 non-return invoices (INV1/INV2/INV3)
        chain_inv = next(f for f in run.findings.filter(rule_code='purchase_invoice_count')
                         if f.scope_type == 'chain')
        self.assertIn('3 فاتورة', chain_inv.message_ar)
        # input VAT chain = 14,000
        vat = next(f for f in run.findings.filter(rule_code='purchase_input_vat')
                   if f.scope_type == 'chain')
        self.assertIn('14,000', vat.message_ar)
        # expiry returns surfaced
        self.assertTrue(run.findings.filter(rule_code='supplier_expiry_returns').exists())

    def test_hq_label_not_raw_code(self):
        # the label-bug fix: HQ shows its name, never a bare "100"
        run = self._run()
        hq = run.findings.filter(rule_code='purchase_invoice_count', scope_key='100').first()
        self.assertIsNotNone(hq)
        self.assertIn('المخزن الرئيسي', hq.message_ar)

    def test_gift_coupon_supplier_omitted_from_all_values(self):
        # a purchase from the management gift/coupon supplier (1268) must be omitted everywhere
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(branch_code='100', supplier_code='1268', doc_number='GIFT1',
            doc_date=self.DAY, item_code='Z', doccode='10', is_return=False, raw_qty=Decimal(1),
            raw_value=Decimal(50000), net_qty=Decimal(1), net_value=Decimal(50000), supplier_category='')
        run = self._run()
        hq = run.findings.filter(rule_code='hq_purchase_summary', scope_key='100').first()
        self.assertIn('100,000', hq.message_ar)     # gift purchase omitted → HQ net stays 100,000
        self.assertNotIn('150,000', hq.message_ar)  # not 100,000 + 50,000

    def test_excluded_supplier_default(self):
        from apps.insights.rules import _excluded_supplier_codes
        self.assertIn('1268', _excluded_supplier_codes())

    def test_foc_valued_at_free_units_not_paid(self):
        # bonus deal: paid 100 units, 10 free, cost 50/unit → FOC value = 50×10 = 500 (the FREE
        # units at cost), NOT 50×100 = 5,000 (the paid units — the old, inflated calc).
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(branch_code='100', supplier_code='S1', doc_number='BON1',
            doc_date=self.DAY, item_code='F', doccode='10', is_return=False,
            raw_qty=Decimal(100), raw_value=Decimal(5000), net_qty=Decimal(100), net_value=Decimal(5000),
            cost_price=Decimal(50), bonus_qty=Decimal(10), is_foc=True, foc_type='bonus',
            supplier_category='OFFICIAL_DISTRIBUTOR')
        run = self._run()
        foc = run.findings.filter(rule_code='foc_captured').first()
        self.assertIsNotNone(foc)
        self.assertIn('500', foc.message_ar)        # 50 × 10 free units
        self.assertNotIn('5,000', foc.message_ar)   # NOT 50 × 100 paid units
        self.assertIn('10 وحدة', foc.message_ar)    # 10 FREE units (bonus_qty), not 100 paid

    def test_gift_items_excluded_from_stock_set(self):
        from apps.insights.rules import Ctx
        gift_cat = Item.objects.create(softech_id='G1', name='Mug', medicine_type='60')   # client-gifts category
        gift_name = Item.objects.create(softech_id='G2', name='هدية عميل', medicine_type='10')  # keyword
        normal = Item.objects.create(softech_id='N1', name='Panadol', medicine_type='10')
        ctx = Ctx('week', self.DAY - timedelta(days=6), self.DAY)
        self.assertIn(gift_cat.id, ctx.excluded_item_ids)
        self.assertIn(gift_name.id, ctx.excluded_item_ids)
        self.assertNotIn(normal.id, ctx.excluded_item_ids)

    def test_hq_zero_state_keeps_hq_in_scope(self):
        # HQ central buying is lumpy — on a day with branch purchases but NO HQ delivery, HQ must
        # still appear (zero-state note) so it stays selectable in the purchasing branch scope.
        from apps.procurement.models import PurchaseLine
        d2 = date(2026, 7, 22)
        PurchaseLine.objects.create(branch_code='130', supplier_code='S3', doc_number='INVX', doc_date=d2,
            item_code='C', doccode='10', is_return=False, raw_qty=Decimal(1), raw_value=Decimal(6000),
            net_qty=Decimal(1), net_value=Decimal(6000), supplier_category='SMALL_WAREHOUSE')
        run = InsightEngine.run(period_type='day', ref_date=d2, domain='purchasing')
        hq = run.findings.filter(rule_code='hq_purchase_summary', scope_key='100').first()
        self.assertIsNotNone(hq)                          # HQ present → stays in the dropdown
        self.assertIn('لا مشتريات مركزية', hq.message_ar)
        self.assertIn('آخر توريد', hq.message_ar)         # last central delivery date shown


class InsightsPartialDayTests(TestCase):
    """DAILY report sets aside reps whose day wasn't a genuine working day (night-shift tail /
    off / partial) or an extreme drop vs their own average — so they aren't mislabelled at the
    bottom. Totals and weekly/monthly are untouched."""
    DAY = date(2026, 7, 20)

    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='970', code='970', name='PD',
                                      name_ar='فرع', is_operational=True)
        cls.med = Item.objects.create(softech_id='PDM', name='دواء', medicine_type='10')
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='cash',
                                        bucket='cash', counts_customer=True, include_in_profit=True, active=True)

        def inv(user, ref, when_date, hour, total):
            cust = Customer.objects.create(name=f'c{ref}', softech_pic=f'PIC{ref}', softech_id=f'C{ref}')
            ph = PurchaseHistory.objects.create(customer=cust, softech_invoice_id=ref, branch=cls.b,
                 doc_code='115', total_amount=Decimal(total),
                 invoice_date=timezone.make_aware(datetime(when_date.year, when_date.month, when_date.day, 0, 0)),
                 trans_time=timezone.make_aware(datetime(when_date.year, when_date.month, when_date.day, hour, 0)),
                 sales_channel='91', sales_person_type='10', softech_user=user, softech_phcode=f'PH{ref}')
            PurchaseHistoryLine.objects.create(purchase=ph, item=cls.med, quantity=Decimal(1),
                 unit_price=Decimal(total), line_total=Decimal(total), cost_at_sale=Decimal(10), list_price=Decimal(total))

        D = cls.DAY
        # 900 full day: 6 txns across 6 hours → genuine day
        for i, h in enumerate([9, 11, 13, 15, 17, 19]):
            inv('900', f'900-{i}', D, h, 5000)
        # 901 full day, genuinely LOW: 5 txns / 5 hours
        for i, h in enumerate([10, 12, 14, 16, 18]):
            inv('901', f'901-{i}', D, h, 1000)
        # 902 sliver WITH history: 2 txns at hour 0 today (gate fails), but normally sells a lot
        # (20 prior days at 10,000) → set aside, reason 'drop' (likely off)
        for i in range(2):
            inv('902', f'902-{i}', D, 0, 500)
        for k in range(1, 21):
            inv('902', f'902t-{k}', D - timedelta(days=k), 12, 10000)
        # 903 few-hours, no history: 6 txns all at hour 0 → gate fails on active-hours (<3) → 'partial'
        for i in range(6):
            inv('903', f'903-{i}', D, 0, 300)
        # 904 FULL presence but low output: 5 txns / 5 hours today (gate passes) yet far below their
        # own trailing average → this is real underperformance, so 904 must STAY (not set aside)
        for i, h in enumerate([9, 11, 13, 15, 17]):
            inv('904', f'904-{i}', D, h, 200)
        for k in range(1, 21):
            inv('904', f'904t-{k}', D - timedelta(days=k), 12, 10000)

    def test_partial_set_and_reasons(self):
        from apps.insights.rules import Ctx
        ctx = Ctx('day', self.DAY, self.DAY)
        # only the weakly-present reps are set aside; 904 (present all day, low output) stays
        self.assertEqual(ctx.partial_day_reps, {'902', '903'})
        self.assertEqual(ctx.partial_day_reasons.get('902'), 'drop')     # sliver + normally sells a lot
        self.assertEqual(ctx.partial_day_reasons.get('903'), 'partial')  # sliver, no history
        for u in ('900', '901', '904'):
            self.assertNotIn(u, ctx.partial_day_reps)

    def test_present_low_rep_stays_only_slivers_excluded(self):
        run = InsightEngine.run(period_type='day', ref_date=self.DAY, domain='sales')
        rk = ' '.join(run.findings.filter(rule_code='salesperson_rankings').values_list('message_ar', flat=True))
        self.assertIn('900', rk)          # genuine full-day reps ranked
        self.assertIn('901', rk)
        self.assertIn('904', rk)          # present all day but low → STAYS (real underperformer)
        for u in ('902', '903'):          # weakly-present slivers are set aside
            self.assertNotIn(u, rk)

    def test_offday_note_names_them(self):
        run = InsightEngine.run(period_type='day', ref_date=self.DAY, domain='sales')
        note = run.findings.filter(rule_code='daily_offday_note').first()
        self.assertIsNotNone(note)
        self.assertIn('902', note.message_ar)          # drop (likely off)
        self.assertIn('903', note.message_ar)          # partial
        self.assertNotIn('904', note.message_ar)       # present all day → not in the note
        self.assertIn('انخفاض حاد', note.message_ar)   # the 'likely off' segment
        self.assertIn('مستبعدون', run.narrative_ar)    # shows in the board narrative

    def test_weekly_report_unaffected(self):
        # over a week the gate is off → nobody is set aside
        from apps.insights.rules import Ctx
        ctx = Ctx('week', self.DAY - timedelta(days=6), self.DAY)
        self.assertEqual(ctx.partial_day_reps, set())


class InsightsFreshnessTests(TestCase):
    """Data-freshness / completeness — the report tells you whether SOFTECH data is fully
    collected for the period (like the purchasing module's 'data through date')."""

    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='980', code='980', name='F',
                                      name_ar='ف', is_operational=True)
        cls.cust = Customer.objects.create(name='c', softech_pic='PICF', softech_id='CF')
        cls.med = Item.objects.create(softech_id='FRM', name='دواء', medicine_type='10')
        ChannelBucketMap.objects.create(person_type='10', channel='91', label='cash',
                                        bucket='cash', counts_customer=True, include_in_profit=True, active=True)
        for d in (date(2026, 5, 9), date(2026, 5, 10)):   # sales mirrored through 2026-05-10
            ph = PurchaseHistory.objects.create(customer=cls.cust, softech_invoice_id=f'F{d}', branch=cls.b,
                 doc_code='115', total_amount=Decimal(1000),
                 invoice_date=timezone.make_aware(datetime(d.year, d.month, d.day, 12)),
                 sales_channel='91', sales_person_type='10', softech_user='700', softech_phcode=f'PF{d}')
            PurchaseHistoryLine.objects.create(purchase=ph, item=cls.med, quantity=Decimal(1),
                 unit_price=Decimal(1000), line_total=Decimal(1000), cost_at_sale=Decimal(10), list_price=Decimal(1000))

    def test_covered_when_end_within_data(self):
        from apps.insights.rules import data_freshness
        fr = data_freshness(date(2026, 5, 10), date(2026, 5, 10), 'sales')
        self.assertTrue(fr['covered'])
        self.assertTrue(fr['complete'])
        self.assertEqual(fr['gap_days'], 0)
        self.assertEqual(fr['sales_through'], date(2026, 5, 10))

    def test_gap_when_end_beyond_data(self):
        from apps.insights.rules import data_freshness
        fr = data_freshness(date(2026, 5, 13), date(2026, 5, 13), 'sales')
        self.assertFalse(fr['covered'])
        self.assertEqual(fr['gap_days'], 3)

    def test_interior_gap_detected_even_when_tail_current(self):
        # 05-09 & 05-10 have data (tail current) but 05-08 is empty → an interior gap the old
        # 'latest date' check would miss. This is exactly the SOFTECH-vs-mirror discrepancy case.
        from apps.insights.rules import data_freshness
        fr = data_freshness(date(2026, 5, 8), date(2026, 5, 10), 'sales')
        self.assertTrue(fr['covered'])                 # tail reaches the end
        self.assertIn('2026-05-08', fr['empty_days'])  # but a day inside is missing
        self.assertFalse(fr['complete'])

    def test_report_header_shows_complete(self):
        run = InsightEngine.run(period_type='day', ref_date=date(2026, 5, 10), domain='sales')
        self.assertIn('بلا فجوات', run.narrative_ar)

    def test_report_header_warns_when_incomplete(self):
        run = InsightEngine.run(period_type='day', ref_date=date(2026, 5, 13), domain='sales')
        self.assertIn('بيانات غير مكتملة', run.narrative_ar)

    def test_report_header_warns_interior_gap(self):
        # week 05-04..05-10: only 05-09/05-10 populated → 05-04..05-08 empty inside the period
        run = InsightEngine.run(period_type='week', ref_date=date(2026, 5, 10), domain='sales')
        self.assertIn('فجوات', run.narrative_ar)


class InsightsBackfillApiTests(TestCase):
    """The gap-backfill endpoint: admin/supervisor only, and it kicks off a background job
    (returns 202) instead of blocking — like the sync page."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User
        from apps.users.models import StaffProfile
        cls.admin = User.objects.create(username='bf_admin')
        StaffProfile.objects.create(user=cls.admin, role='admin')
        cls.viewer = User.objects.create(username='bf_viewer')
        StaffProfile.objects.create(user=cls.viewer, role='viewer')

    def _post(self, user, data):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.insights.views import InsightRunViewSet
        req = APIRequestFactory().post('/api/insights/reports/backfill/', data, format='json')
        force_authenticate(req, user=user)
        return InsightRunViewSet.as_view({'post': 'backfill'})(req)

    def test_viewer_forbidden(self):
        r = self._post(self.viewer, {'domain': 'sales', 'start': '2026-08-01', 'end': '2026-08-31'})
        self.assertEqual(r.status_code, 403)

    def test_admin_triggers_background_job(self):
        from unittest.mock import patch
        with patch('threading.Thread') as mt:   # don't spawn a real thread / hit SOFTECH
            r = self._post(self.admin, {'domain': 'sales', 'start': '2026-08-01', 'end': '2026-08-31'})
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.data['status'], 'running')
        mt.assert_called_once()

    def test_missing_dates_400(self):
        r = self._post(self.admin, {'domain': 'sales'})
        self.assertEqual(r.status_code, 400)


class BottomFlagFairnessTests(TestCase):
    """The per-member bottom-N flag is VALUE-based and tie-aware — it never mislabels a rep
    who is only placed last by an unstable sort of tied values."""
    class _Ctx:
        bottom_n = 5
        bottom_min_pop = 8

    def _flag(self, my, allv):
        from apps.insights.rules import _bottom_flag
        ar, en = _bottom_flag(self._Ctx(), [('س', 'm', my, allv)])
        return en   # '' when not flagged

    def test_clear_lowest_is_flagged(self):
        self.assertIn('#10/10', self._flag(1, list(range(1, 11))))

    def test_top_value_not_flagged(self):
        self.assertEqual('', self._flag(10, list(range(1, 11))))

    def test_all_tied_never_flagged(self):
        # a whole field on the same value has no underperformer
        self.assertEqual('', self._flag(5, [5] * 10))

    def test_small_field_not_ranked(self):
        # below bottom_min_pop → not enough members to call a bottom
        self.assertEqual('', self._flag(1, [1, 2, 3, 4, 5, 6, 7]))

    def test_boundary_tie_block_not_singled_out(self):
        # six members share the lowest value; a 5-wide band can't hold them → none flagged
        self.assertEqual('', self._flag(0, [0] * 6 + [1, 2, 3, 4]))
