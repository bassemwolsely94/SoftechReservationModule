"""Phase 3: receipts reconciliation, SOFTECH ↔ ETA (spec 2026-11-14-eta-history-mirror-design.md §Phase 3)."""
import datetime as dt
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.tax_invoicing import eta_recon
from apps.tax_invoicing.models import (EtaDeviceBranch, EtaMirrorReceipt, EtaReconLine, EtaReconUncodedItem,
                                       TaxChannelRule, TaxItemProfile)
from apps.tests.test_tax_invoicing import Fixture, api

CAIRO = ZoneInfo('Africa/Cairo')
DAY = dt.date(2026, 11, 5)


def _at(day, hour, minute=0):
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=CAIRO)


def _eta(number, total, *, device='POS-150', kind='s', status='valid', when=None, uuid=None):
    return EtaMirrorReceipt.objects.create(system='production', uuid=uuid or f'U-{kind}-{number}-{device}', receipt_number=str(number),
                                           pos_serial=device, receipt_type=kind, status=status,
                                           issued_at=when or _at(DAY, 10), total_amount=Decimal(str(total)))


class FakeSoftech:
    """Stands in for the HQ stktransm read: (branch, day) -> [(doccode, docnumber, total, channel)]."""
    def __init__(self):
        self.days = {}
        self.calls = []

    def rows(self, branch, day):
        """Each day entry is (doccode, docnumber, total, channel[, [(itemcode, qty, value), ...]])."""
        self.calls.append((branch, day))
        out = []
        for d, n, t, ch, *rest in self.days.get((branch, day), []):
            lines = [{'itemcode': i, 'qty': Decimal(str(q)), 'value': Decimal(str(v))} for i, q, v in (rest[0] if rest else [])]
            out.append({'doccode': d, 'docnumber': str(n), 'total': Decimal(str(t)), 'channel': ch, 'lines': lines})
        return out

    def neighbours(self, branch, day):
        """Headers of the day before and after: (doccode, docnumber) -> {day, total, channel}."""
        out = {}
        for other in (day - dt.timedelta(days=1), day + dt.timedelta(days=1)):
            for d, n, t, ch, *_rest in self.days.get((branch, other), []):
                out[(d, str(n))] = {'day': other, 'total': Decimal(str(t)), 'channel': ch}
        return out

    def find(self, numbers):
        """(doccode, docnumber, day) -> branch, for learning which branch a device belongs to."""
        out = {}
        for (branch, day), rows in self.days.items():
            for d, n, *_rest in rows:
                out[(d, str(n), day)] = branch
        return {k: v for k, v in out.items() if k in numbers}


class ReconTests(TestCase):

    def setUp(self):
        self.softech = FakeSoftech()
        for name, fake in (('_softech_rows', self.softech.rows), ('_softech_find', self.softech.find),
                           ('_softech_neighbours', self.softech.neighbours)):
            p = mock.patch.object(eta_recon, name, fake)
            p.start()
            self.addCleanup(p.stop)
        from apps.branches.models import Branch
        for code, kind in (('150', Branch.KIND_RETAIL), ('130', Branch.KIND_RETAIL), ('160', Branch.KIND_RETAIL),
                           ('110', Branch.KIND_CLOSED)):
            Branch.objects.get_or_create(softech_branch_id=code, defaults={'name': f'B{code}', 'kind': kind})
        EtaDeviceBranch.objects.create(system='production', pos_serial='POS-150', softech_branchcode='150',
                                       first_day=dt.date(2026, 1, 1))
        # 'C' = a cash channel sent as receipts (a channel with no decided rule gets its own reason)
        TaxChannelRule.objects.update_or_create(ptclassifcode='C', defaults={'mode': TaxChannelRule.MODE_RECEIPT, 'label': 'نقدي'})

    def _outcomes(self):
        return {(l.doccode, l.docnumber): l.outcome for l in EtaReconLine.objects.filter(system='production')}

    def test_each_sale_gets_one_outcome(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C'), ('115', 2, 638, 'C'), ('115', 3, 50, 'C'),
                                           ('115', 4, 10, 'C'), ('115', 5, 15, 'C'), ('30', 9, 25, 'C')]
        _eta(1, '20.03')                                  # within 0.05 → matched
        _eta(2, '120.42')                                 # amount differs
        _eta(4, 10, status='cancelled')                   # not valid at ETA
        _eta(5, 15, uuid='A')
        _eta(5, 15, uuid='B')                             # sent twice
        _eta(9, '24.99975', kind='r')                     # a return matches doccode 30
        _eta(77, 5)                                       # at ETA only
        out = eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._outcomes(), {
            ('115', '1'): 'matched', ('115', '2'): 'amount_differs', ('115', '3'): 'missing_at_eta',
            ('115', '4'): 'not_valid', ('115', '5'): 'duplicate', ('30', '9'): 'matched', ('115', '77'): 'eta_only'})
        self.assertEqual(out['missing_at_eta'], 1)
        line = EtaReconLine.objects.get(docnumber='2')
        self.assertEqual((line.softech_total, line.eta_total), (Decimal('638.00'), Decimal('120.42000')))

    def test_the_day_is_the_cairo_date(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C')]
        _eta(1, 20, when=dt.datetime(2026, 11, 4, 22, 30, tzinfo=dt.timezone.utc))      # 00:30 on the 5th in Cairo
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._outcomes(), {('115', '1'): 'matched'})

    def test_sales_by_invoice_are_kept_apart_never_missing(self):
        TaxChannelRule.objects.update_or_create(ptclassifcode='K', defaults={'mode': TaxChannelRule.MODE_INVOICE, 'label': 'تعاقد'})
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'K')]
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._outcomes(), {('115', '1'): 'by_invoice'})

    def test_recomputing_a_day_replaces_its_lines(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C')]
        eta_recon.reconcile_day('production', '150', DAY)
        _eta(1, 20)
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(EtaReconLine.objects.count(), 1)
        self.assertEqual(self._outcomes(), {('115', '1'): 'matched'})

    def test_days_before_the_device_started_are_out_of_scope(self):
        EtaDeviceBranch.objects.filter(pos_serial='POS-150').update(first_day=dt.date(2026, 11, 10))
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C')]
        out = eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((out['skipped'], EtaReconLine.objects.count()), (True, 0))
        self.assertEqual(self.softech.calls, [])

    def test_a_range_covers_open_branches_only(self):
        EtaDeviceBranch.objects.create(system='production', pos_serial='OLD', softech_branchcode='110', first_day=dt.date(2026, 1, 1))
        out = eta_recon.reconcile_range('production', DAY, DAY + dt.timedelta(days=1))
        self.assertEqual(sorted({b for b, _ in self.softech.calls}), ['150'])
        self.assertEqual(out['days'], 2)

    def test_softech_unreachable_stops_and_keeps_old_lines(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C')]
        eta_recon.reconcile_day('production', '150', DAY)
        with mock.patch.object(eta_recon, '_softech_rows', side_effect=OSError('down at 10.0.0.5:5000')):
            out = eta_recon.reconcile_range('production', DAY, DAY)
        self.assertIn('مرجع', out['error'])
        self.assertNotIn('10.0.0.5', out['error'])       # driver text (hosts, SQL) stays in the log
        self.assertEqual(EtaReconLine.objects.count(), 1)

    def test_branches_our_list_classes_as_not_live_are_left_out(self):
        from apps.branches.models import Branch
        Branch.objects.create(softech_branch_id='240', name='pending', kind=Branch.KIND_PENDING)
        EtaDeviceBranch.objects.create(system='production', pos_serial='NEW', softech_branchcode='240', first_day=dt.date(2026, 1, 1))
        EtaDeviceBranch.objects.create(system='production', pos_serial='GONE', softech_branchcode='999', first_day=dt.date(2026, 1, 1))
        self.assertEqual(eta_recon.open_branches('production'), ['150'])     # pending and unknown codes left out

    def test_devices_are_learned_from_a_sample_of_their_receipts(self):
        EtaDeviceBranch.objects.all().delete()
        self.softech.days[('130', DAY)] = [('115', n, 1, 'C') for n in range(100, 105)]
        for n in range(100, 105):
            _eta(n, 1, device='MJV')
        _eta(999, 1, device='MJV', when=_at(dt.date(2026, 3, 5), 9))     # its earliest receipt
        learned = eta_recon.learn_devices('production')
        d = EtaDeviceBranch.objects.get(pos_serial='MJV')
        self.assertEqual((d.softech_branchcode, d.first_day, d.source), ('130', dt.date(2026, 3, 5), 'auto'))
        self.assertEqual(learned['MJV'], '130')

    def test_a_manual_device_branch_is_never_overwritten(self):
        EtaDeviceBranch.objects.filter(pos_serial='POS-150').update(softech_branchcode='160', source='manual')
        self.softech.days[('150', DAY)] = [('115', 1, 1, 'C')]
        _eta(1, 1)
        eta_recon.learn_devices('production')
        self.assertEqual(EtaDeviceBranch.objects.get(pos_serial='POS-150').softech_branchcode, '160')



class ReconReasonTests(ReconTests):
    """Production receipts leave out every line whose item has no ETA code; a sale with no coded line is not sent."""

    def setUp(self):
        super().setUp()
        for code in ('A', 'B'):
            TaxItemProfile.objects.create(softech_itemcode=code, eta_code=f'EG-1-{code}', coding_status='approved',
                                          list_status='white')
        TaxItemProfile.objects.create(softech_itemcode='X', eta_code='')          # a profile without a code
        # 'DLV' and 'CPN' have no profile at all: they count as having no code too

    def _line(self, number):
        return EtaReconLine.objects.get(system='production', docnumber=str(number))

    def test_missing_because_no_item_has_a_code(self):
        self.softech.days[('150', DAY)] = [('115', 1, 35, 'C', [('X', 1, 20), ('DLV', 15, 15)])]
        eta_recon.reconcile_day('production', '150', DAY)
        line = self._line(1)
        self.assertEqual((line.outcome, line.reason, line.uncoded_total), ('missing_at_eta', 'all_uncoded', Decimal('35.00')))

    def test_missing_with_some_coded_items_is_only_partly_explained(self):
        self.softech.days[('150', DAY)] = [('115', 1, 50, 'C', [('A', 1, 30), ('X', 1, 20)])]
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(1).outcome, self._line(1).reason), ('missing_at_eta', 'some_uncoded'))

    def test_amount_gap_equal_to_the_uncoded_lines(self):
        self.softech.days[('150', DAY)] = [('115', 1, 800, 'C', [('A', 1, 500), ('DLV', 300, 300)])]
        _eta(1, 500)
        eta_recon.reconcile_day('production', '150', DAY)
        line = self._line(1)
        self.assertEqual((line.outcome, line.reason, line.uncoded_total), ('amount_differs', 'uncoded_lines', Decimal('300.00')))

    def test_a_coupon_line_left_off_makes_eta_higher(self):
        self.softech.days[('150', DAY)] = [('115', 1, 424, 'C', [('A', 1, 474), ('CPN', 1, -50)])]
        _eta(1, 474)
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(1).outcome, self._line(1).reason), ('amount_differs', 'uncoded_lines'))

    def test_a_gap_the_uncoded_lines_do_not_explain(self):
        self.softech.days[('150', DAY)] = [('115', 1, 205, 'C', [('A', 1, 160), ('X', 1, 45)])]
        _eta(1, 100)
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._line(1).reason, 'some_uncoded')

    def test_matched_and_unexplained_lines_have_no_reason(self):
        self.softech.days[('150', DAY)] = [('115', 1, 30, 'C', [('A', 1, 30)]), ('115', 2, 60, 'C', [('A', 1, 60)])]
        _eta(1, 30)
        _eta(2, 50)
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual([(l.docnumber, l.outcome, l.reason) for l in EtaReconLine.objects.order_by('docnumber')],
                         [('1', 'matched', ''), ('2', 'amount_differs', '')])

    def test_uncoded_items_are_totalled_per_branch_day(self):
        TaxChannelRule.objects.update_or_create(ptclassifcode='K', defaults={'mode': TaxChannelRule.MODE_INVOICE, 'label': 'تعاقد'})
        self.softech.days[('150', DAY)] = [
            ('115', 1, 35, 'C', [('X', 2, 20), ('DLV', 15, 15)]),
            ('115', 2, 10, 'C', [('X', 1, 10)]),
            ('30', 9, 10, 'C', [('X', 1, 10)]),           # a return takes the sale back
            ('115', 3, 99, 'K', [('X', 9, 99)]),          # by invoice: not on a receipt, left out
        ]
        eta_recon.reconcile_day('production', '150', DAY)
        got = {u.itemcode: (u.docs, u.qty, u.value) for u in EtaReconUncodedItem.objects.all()}
        self.assertEqual(got, {'X': (3, Decimal('2.00000'), Decimal('20.00')), 'DLV': (1, Decimal('15.00000'), Decimal('15.00'))})
        eta_recon.reconcile_day('production', '150', DAY)          # recomputing replaces, never doubles
        self.assertEqual(EtaReconUncodedItem.objects.count(), 2)

    def test_an_item_coded_later_stops_counting_on_the_next_recompute(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C', [('X', 1, 20)]), ('115', 2, 30, 'C'), ('115', 3, 40, 'C')]
        _eta(2, 30)
        _eta(3, 40)                                        # a normal day: the tills sent
        eta_recon.reconcile_day('production', '150', DAY)
        TaxItemProfile.objects.filter(softech_itemcode='X').update(eta_code='EG-1-X', list_status='white')
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(1).reason, EtaReconUncodedItem.objects.count()), ('', 0))

    def test_the_ranking_puts_the_biggest_sales_first(self):
        EtaReconUncodedItem.objects.create(system='production', softech_branchcode='150', day=DAY, itemcode='X', docs=2, qty=2, value=40)
        EtaReconUncodedItem.objects.create(system='production', softech_branchcode='130', day=DAY, itemcode='DLV', docs=9, qty=90, value=90)
        EtaReconUncodedItem.objects.create(system='production', softech_branchcode='150', day=DAY + dt.timedelta(days=1), itemcode='X', docs=1, qty=1, value=70)
        rows = eta_recon.uncoded_items('production')
        self.assertEqual([(r['itemcode'], r['value'], r['docs']) for r in rows], [('X', Decimal('110.00'), 3), ('DLV', Decimal('90.00'), 9)])
        self.assertEqual(rows[0]['last_day'], DAY + dt.timedelta(days=1))
        self.assertEqual([r['itemcode'] for r in eta_recon.uncoded_items('production', branch='130')], ['DLV'])


class CodedItemsTests(TestCase):
    """'Coded' for the receipts recon = coded in the owner's bulk EGS sheet (the 13-Nov workbook import)."""

    def test_only_white_sheet_items_with_a_code_and_no_coding_env_count(self):
        TaxItemProfile.objects.create(softech_itemcode='SHEET', eta_code='EG-1-S', list_status='white')
        TaxItemProfile.objects.create(softech_itemcode='PREPROD', eta_code='EG-1-P', coding_status='approved',
                                      list_status='white', coding_env='preprod')
        TaxItemProfile.objects.create(softech_itemcode='PROD', eta_code='EG-1-D', coding_status='approved',
                                      list_status='black', coding_env='production')
        TaxItemProfile.objects.create(softech_itemcode='NOCODE', eta_code='', list_status='white')
        self.assertEqual(eta_recon.coded_items(), {'SHEET'})


class ReconOtherDayAndSilentTests(ReconTests):
    """A sale ETA dated a day off (around midnight) matches; a day the tills barely sent explains what is missing."""

    NEXT = DAY + dt.timedelta(days=1)
    BEFORE = DAY - dt.timedelta(days=1)

    def _line(self, number, day=DAY):
        return EtaReconLine.objects.get(system='production', day=day, docnumber=str(number))

    def test_a_sale_after_midnight_matches_the_receipt_on_the_next_day(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C'), ('115', 2, 70, 'C')]
        _eta(1, 20)
        _eta(2, 70, when=_at(self.NEXT, 0, 7))
        eta_recon.reconcile_day('production', '150', DAY)
        line = self._line(2)
        self.assertEqual((line.outcome, line.reason, line.eta_total), ('matched', 'eta_other_day', Decimal('70')))
        # on its own day the receipt is the sale's, not an «ETA only» receipt
        self.softech.days[('150', self.NEXT)] = [('115', 3, 15, 'C')]
        _eta(3, 15, when=_at(self.NEXT, 9))
        eta_recon.reconcile_day('production', '150', self.NEXT)
        self.assertEqual(set(EtaReconLine.objects.filter(day=self.NEXT).values_list('docnumber', 'outcome')), {('3', 'matched')})

    def test_a_receipt_dated_the_day_before_matches_too(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C'), ('115', 2, 70, 'C')]
        _eta(1, 20)
        _eta(2, 70, when=_at(self.BEFORE, 23, 50))
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(2).outcome, self._line(2).reason), ('matched', 'eta_other_day'))

    def test_another_amount_is_not_claimed(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C'), ('115', 2, 70, 'C')]
        _eta(1, 20)
        _eta(2, 71, when=_at(self.NEXT, 0, 7))
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._line(2).outcome, 'missing_at_eta')
        self.assertNotEqual(self._line(2).reason, 'eta_other_day')
        self.softech.days[('150', self.NEXT)] = [('115', 3, 15, 'C')]
        _eta(3, 15, when=_at(self.NEXT, 9))
        eta_recon.reconcile_day('production', '150', self.NEXT)
        self.assertEqual(self._line(2, self.NEXT).outcome, 'eta_only')

    def test_a_receipt_of_a_sale_on_its_own_day_is_never_taken(self):
        # number 2 is a sale on both days (another sequence wrapped): the next day's receipt belongs to the next day
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C'), ('115', 2, 70, 'C')]
        self.softech.days[('150', self.NEXT)] = [('115', 2, 70, 'C')]
        _eta(1, 20)
        _eta(2, 70, when=_at(self.NEXT, 0, 7))
        eta_recon.reconcile_day('production', '150', DAY)
        eta_recon.reconcile_day('production', '150', self.NEXT)
        self.assertEqual(self._line(2).outcome, 'missing_at_eta')
        self.assertEqual((self._line(2, self.NEXT).outcome, self._line(2, self.NEXT).reason), ('matched', ''))

    def test_two_receipts_on_the_other_day_are_not_guessed_between(self):
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C'), ('115', 2, 70, 'C')]
        _eta(1, 20)
        _eta(2, 70, when=_at(self.NEXT, 0, 7), uuid='A')
        _eta(2, 70, when=_at(self.NEXT, 0, 9), uuid='B')
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._line(2).outcome, 'missing_at_eta')

    def test_a_by_invoice_sale_never_claims_a_receipt(self):
        TaxChannelRule.objects.create(ptclassifcode='11', mode=TaxChannelRule.MODE_INVOICE)
        self.softech.days[('150', DAY)] = [('115', 1, 20, 'C'), ('115', 2, 70, '11')]
        _eta(1, 20)
        _eta(2, 70, when=_at(self.NEXT, 0, 7))
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._line(2).outcome, 'by_invoice')
        eta_recon.reconcile_day('production', '150', self.NEXT)
        self.assertEqual(self._line(2, self.NEXT).outcome, 'eta_only')

    def test_a_day_the_tills_barely_sent_explains_what_is_missing(self):
        self.softech.days[('150', DAY)] = [('115', n, 10, 'C') for n in range(1, 5)]
        _eta(1, 10)                                        # 1 of 4 sent: under half
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual({self._line(n).reason for n in (2, 3, 4)}, {'till_silent'})
        self.assertEqual(self._line(1).reason, '')

    def test_on_a_normal_day_a_missing_sale_stays_unexplained(self):
        self.softech.days[('150', DAY)] = [('115', n, 10, 'C') for n in range(1, 5)]
        for n in (1, 2, 3):
            _eta(n, 10)
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(4).outcome, self._line(4).reason), ('missing_at_eta', ''))

    def test_an_uncoded_sale_keeps_its_own_reason_on_a_silent_day(self):
        self.softech.days[('150', DAY)] = [('115', 1, 10, 'C', [('DLV', 10, 10)]), ('115', 2, 10, 'C')]
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(1).reason, self._line(2).reason), ('all_uncoded', 'till_silent'))

    def test_the_summary_counts_the_new_reasons(self):
        self.softech.days[('150', DAY)] = [('115', n, 10, 'C') for n in range(1, 5)] + [('115', 9, 70, 'C')]
        _eta(9, 70, when=_at(self.NEXT, 0, 7))
        eta_recon.reconcile_day('production', '150', DAY)
        row = eta_recon.summary('production')[0]
        self.assertEqual(row['reasons'], {'till_silent': 4, 'eta_other_day': 1})


class ReconChannelRuleTests(ReconTests):
    """Invoicer sends cash sales only: a sale in a channel with no decided rule is explained by that, not left unknown."""

    def _line(self, number):
        return EtaReconLine.objects.get(system='production', day=DAY, docnumber=str(number))

    def _normal_day(self, extra):
        self.softech.days[('150', DAY)] = [('115', 1, 10, 'C'), ('115', 2, 10, 'C'), ('115', 3, 10, 'C')] + extra
        for n in (1, 2, 3):
            _eta(n, 10)

    def test_a_channel_with_no_rule_is_the_reason_and_the_channel_is_kept(self):
        self._normal_day([('115', 4, 300, '11'), ('115', 5, 40, 'C')])
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(4).reason, self._line(4).channel), ('no_channel_rule', '11'))
        self.assertEqual((self._line(5).reason, self._line(5).channel), ('', 'C'))

    def test_an_undecided_rule_counts_as_no_rule(self):
        TaxChannelRule.objects.update_or_create(ptclassifcode='17', defaults={'mode': TaxChannelRule.MODE_UNDECIDED})
        self._normal_day([('115', 4, 1, '17')])
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._line(4).reason, 'no_channel_rule')

    def test_a_decided_receipt_channel_stays_unexplained(self):
        TaxChannelRule.objects.update_or_create(ptclassifcode='16', defaults={'mode': TaxChannelRule.MODE_RECEIPT})
        self._normal_day([('115', 4, 90, '16')])
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual(self._line(4).reason, '')

    def test_uncoded_items_come_first_and_no_rule_comes_before_a_silent_day(self):
        self.softech.days[('150', DAY)] = [('115', 1, 10, '11', [('DLV', 10, 10)]), ('115', 2, 10, '11'), ('115', 3, 10, 'C')]
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual([self._line(n).reason for n in (1, 2, 3)], ['all_uncoded', 'no_channel_rule', 'till_silent'])

    def test_a_matched_sale_has_no_reason_whatever_its_channel(self):
        self._normal_day([('115', 4, 25, '11')])
        _eta(4, 25)
        eta_recon.reconcile_day('production', '150', DAY)
        self.assertEqual((self._line(4).outcome, self._line(4).reason), ('matched', ''))


class SoftechNeighboursReadTests(TestCase):

    def test_reads_the_day_before_and_after_once(self):
        cur = mock.Mock()
        cur.fetchall.return_value = [('115', 716503.0, 70.0, '91 ', dt.datetime(2026, 11, 6)), ('30 ', '22916', 5.0, None, '2026-11-04')]
        conn = mock.Mock()
        conn.cursor.return_value = cur
        with mock.patch.object(eta_recon, '_connect', return_value=conn):
            got = eta_recon._softech_neighbours('150', DAY)
        conn.close.assert_called_once()
        self.assertEqual(cur.execute.call_args[0][1], ('150', '2026-11-04', '2026-11-06'))
        self.assertEqual(got[('115', '716503')], {'day': dt.date(2026, 11, 6), 'total': Decimal('70.0'), 'channel': '91'})
        self.assertEqual(got[('30', '22916')]['day'], dt.date(2026, 11, 4))


class SoftechLinesReadTests(TestCase):
    """_softech_rows reads the headers and the lines of a branch-day on one connection and groups them."""

    def test_lines_are_grouped_under_their_document(self):
        heads = [('115', 716503.0, 140.0, '91'), ('30 ', '22916', 491.0, None)]
        details = [('115', 716503.0, '128899 ', 1.0, 474.0, 0.0), ('115', 716503.0, '118639', 1.0, -50.0, 0.0),
                   ('115', 716503.0, '200', 2.0, 10.0, 10.0), ('30', 22916.0, '5', 1.0, 491.0, 0.0)]
        cur = mock.Mock()
        cur.fetchall.side_effect = [heads, details]
        conn = mock.Mock()
        conn.cursor.return_value = cur
        with mock.patch.object(eta_recon, '_connect', return_value=conn):
            rows = eta_recon._softech_rows('150', DAY)
        conn.close.assert_called_once()
        sale = rows[0]
        self.assertEqual((sale['doccode'], sale['docnumber'], sale['channel']), ('115', '716503', '91'))
        self.assertEqual([(x['itemcode'], x['value']) for x in sale['lines']],
                         [('128899', Decimal('474.00')), ('118639', Decimal('-50.00')), ('200', Decimal('18.00'))])
        self.assertEqual((rows[1]['doccode'], [x['itemcode'] for x in rows[1]['lines']]), ('30', ['5']))


class ReconViewTests(Fixture, TestCase):

    def setUp(self):
        self.build('rc')
        for n, outcome in ((1, 'matched'), (2, 'matched'), (3, 'missing_at_eta')):
            EtaReconLine.objects.create(system='production', softech_branchcode='150', day=DAY, doccode='115',
                                        docnumber=str(n), softech_total=Decimal('10'), outcome=outcome)

    def test_summary_counts_per_branch_month_and_outcome(self):
        self.assertEqual(api(self.pharmacist).get('/api/tax-invoicing/history/recon/', {'system': 'production'}).status_code, 403)
        body = api(self.accountant).get('/api/tax-invoicing/history/recon/', {'system': 'production'}).json()
        row = body['rows'][0]
        self.assertEqual((row['branch'], row['month'], row['matched'], row['missing_at_eta']), ('150', '2026-11', 2, 1))
        self.assertEqual(row['softech_total'], '30.00')

    def test_lines_drill_down_by_outcome(self):
        body = api(self.accountant).get('/api/tax-invoicing/history/recon/lines/',
                                        {'system': 'production', 'branch': '150', 'month': '2026-11', 'outcome': 'missing_at_eta'}).json()
        self.assertEqual([r['docnumber'] for r in body['rows']], ['3'])

    def test_refresh_needs_edit(self):
        self.assertEqual(api(self.pharmacist).post('/api/tax-invoicing/history/recon/refresh/', {'system': 'production'},
                                                   format='json').status_code, 403)
        with mock.patch('apps.tax_invoicing.history_views.start_thread') as thread:
            r = api(self.accountant).post('/api/tax-invoicing/history/recon/refresh/', {'system': 'production'}, format='json')
        self.assertEqual(r.status_code, 202)
        thread.assert_called_once()


    def test_lines_filter_by_reason(self):
        EtaReconLine.objects.filter(docnumber='3').update(reason='all_uncoded', uncoded_total=Decimal('10'))
        params = {'system': 'production', 'outcome': 'missing_at_eta'}
        body = api(self.accountant).get('/api/tax-invoicing/history/recon/lines/', {**params, 'reason': 'all_uncoded'}).json()
        self.assertEqual([(r['docnumber'], r['reason'], r['uncoded_total']) for r in body['rows']], [('3', 'all_uncoded', '10.00')])
        none = api(self.accountant).get('/api/tax-invoicing/history/recon/lines/', {**params, 'reason': 'none'}).json()
        self.assertEqual(none['count'], 0)
        self.assertEqual(api(self.accountant).get('/api/tax-invoicing/history/recon/lines/', {**params, 'reason': 'x'}).status_code, 400)
        row = api(self.accountant).get('/api/tax-invoicing/history/recon/', {'system': 'production'}).json()['rows'][0]
        self.assertEqual(row['reasons'], {'all_uncoded': 1})

    def test_uncoded_items_list_and_export(self):
        from apps.tax_invoicing.models import TaxAuditEvent
        TaxItemProfile.objects.create(softech_itemcode='CODED', eta_code='EG-1-C', coding_status='approved')
        for code, value in (('DLV', 300), ('X', 900), ('CODED', 50)):
            EtaReconUncodedItem.objects.create(system='production', softech_branchcode='150', day=DAY, itemcode=code, docs=1, qty=1, value=value)
        url = '/api/tax-invoicing/history/recon/uncoded/'
        self.assertEqual(api(self.pharmacist).get(url, {'system': 'production'}).status_code, 403)
        body = api(self.accountant).get(url, {'system': 'production'}).json()
        self.assertEqual([(r['itemcode'], r['value']) for r in body['rows']], [('X', '900.00'), ('DLV', '300.00'), ('CODED', '50.00')])
        self.assertEqual(body['total_value'], '1250.00')
        still = api(self.accountant).get(url, {'system': 'production', 'open': '1', 'ordering': 'itemcode'}).json()
        self.assertEqual([r['itemcode'] for r in still['rows']], ['DLV', 'X'])          # coded since: left out
        self.assertEqual(api(self.accountant).get(url, {'system': 'production', 'ordering': 'name'}).status_code, 400)
        before = TaxAuditEvent.objects.filter(action='eta_recon_uncoded_export').count()
        r = api(self.accountant).get(url + 'export/', {'system': 'production'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        self.assertEqual(TaxAuditEvent.objects.filter(action='eta_recon_uncoded_export').count(), before + 1)


class ReconGapsViewTests(Fixture, TestCase):
    """The list of sales missing with no known cause: all branches, biggest first, with the channel, and its export."""

    URL = '/api/tax-invoicing/history/recon/lines/'

    def setUp(self):
        self.build('gp')
        TaxChannelRule.objects.update_or_create(ptclassifcode='90', defaults={'mode': TaxChannelRule.MODE_RECEIPT, 'label': 'Delivery'})
        for n, (branch, total, channel, reason) in enumerate([('150', '80002', '90', ''), ('160', '95', '77', ''),
                                                               ('160', '5000', '11', 'no_channel_rule'), ('130', '1200', '90', '')], 1):
            EtaReconLine.objects.create(system='production', softech_branchcode=branch, day=DAY, doccode='115', docnumber=str(n),
                                        softech_total=Decimal(total), outcome='missing_at_eta', reason=reason, channel=channel)

    def test_biggest_first_across_branches_with_channel_and_total(self):
        params = {'system': 'production', 'outcome': 'missing_at_eta', 'reason': 'none', 'ordering': '-softech_total'}
        self.assertEqual(api(self.pharmacist).get(self.URL, params).status_code, 403)
        body = api(self.accountant).get(self.URL, params).json()
        self.assertEqual([(r['docnumber'], r['channel'], r['channel_label']) for r in body['rows']],
                         [('1', '90', 'Delivery'), ('4', '90', 'Delivery'), ('2', '77', '')])
        self.assertEqual(Decimal(body['total']), Decimal('81297'))
        only = api(self.accountant).get(self.URL, {**params, 'channel': '90', 'branch': '130'}).json()
        self.assertEqual([r['docnumber'] for r in only['rows']], ['4'])
        self.assertEqual(api(self.accountant).get(self.URL, {**params, 'ordering': 'eta_uuid'}).status_code, 400)

    def test_the_summary_lists_the_channels_and_the_new_reason(self):
        body = api(self.accountant).get('/api/tax-invoicing/history/recon/', {'system': 'production'}).json()
        self.assertIn({'code': '90', 'label': 'Delivery'}, body['channels'])
        self.assertIn('no_channel_rule', body['reasons'])

    def test_export_keeps_the_order_and_names_the_channel(self):
        import io
        import openpyxl
        from apps.tax_invoicing.models import TaxAuditEvent
        before = TaxAuditEvent.objects.filter(action='eta_recon_export').count()
        r = api(self.accountant).get('/api/tax-invoicing/history/recon/export/',
                                     {'system': 'production', 'outcome': 'missing_at_eta', 'reason': 'none', 'ordering': '-softech_total'})
        self.assertEqual(r.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        head = [c.value for c in ws[1]]
        rows = [dict(zip(head, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]
        self.assertEqual([x['الرقم'] for x in rows], ['1', '4', '2'])
        self.assertEqual(rows[0]['القناة'], '90 · Delivery')
        self.assertEqual(rows[2]['القناة'], '77')
        self.assertEqual(TaxAuditEvent.objects.filter(action='eta_recon_export').count(), before + 1)
        self.assertEqual(api(self.accountant).get('/api/tax-invoicing/history/recon/export/',
                                                  {'system': 'production', 'ordering': 'nope'}).status_code, 400)


class ReconJobTests(TestCase):

    def test_the_daily_job_recomputes_recent_days_for_enabled_systems_only(self):
        from django.test import override_settings
        from apps.sync import tasks
        with mock.patch.object(eta_recon, 'learn_devices') as learn, mock.patch.object(eta_recon, 'recent') as recent, \
                override_settings(TAX_ETA_READ_PREPROD_ENABLED=False, TAX_ETA_READ_PRODUCTION_ENABLED=True):
            tasks._run_eta_recon_daily()
        self.assertEqual([c[0][0] for c in recent.call_args_list], ['production'])
        self.assertEqual([c[0][0] for c in learn.call_args_list], ['production'])
