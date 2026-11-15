"""Phase 3: receipts reconciliation, SOFTECH ↔ ETA (spec 2026-11-14-eta-history-mirror-design.md §Phase 3)."""
import datetime as dt
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.tax_invoicing import eta_recon
from apps.tax_invoicing.models import EtaDeviceBranch, EtaMirrorReceipt, EtaReconLine, TaxChannelRule
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
        self.calls.append((branch, day))
        return [{'doccode': d, 'docnumber': str(n), 'total': Decimal(str(t)), 'channel': ch}
                for d, n, t, ch in self.days.get((branch, day), [])]

    def find(self, numbers):
        """(doccode, docnumber, day) -> branch, for learning which branch a device belongs to."""
        out = {}
        for (branch, day), rows in self.days.items():
            for d, n, _t, _c in rows:
                out[(d, str(n), day)] = branch
        return {k: v for k, v in out.items() if k in numbers}


class ReconTests(TestCase):

    def setUp(self):
        self.softech = FakeSoftech()
        for name in ('_softech_rows', '_softech_find'):
            p = mock.patch.object(eta_recon, name, getattr(self.softech, 'rows' if name == '_softech_rows' else 'find'))
            p.start()
            self.addCleanup(p.stop)
        EtaDeviceBranch.objects.create(system='production', pos_serial='POS-150', softech_branchcode='150',
                                       first_day=dt.date(2026, 1, 1))

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
        with mock.patch.object(eta_recon, '_softech_rows', side_effect=OSError('down')):
            out = eta_recon.reconcile_range('production', DAY, DAY)
        self.assertIn('down', out['error'])
        self.assertEqual(EtaReconLine.objects.count(), 1)

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


class ReconJobTests(TestCase):

    def test_the_daily_job_recomputes_recent_days_for_enabled_systems_only(self):
        from django.test import override_settings
        from apps.sync import tasks
        with mock.patch.object(eta_recon, 'learn_devices') as learn, mock.patch.object(eta_recon, 'recent') as recent, \
                override_settings(TAX_ETA_READ_PREPROD_ENABLED=False, TAX_ETA_READ_PRODUCTION_ENABLED=True):
            tasks._run_eta_recon_daily()
        self.assertEqual([c[0][0] for c in recent.call_args_list], ['production'])
        self.assertEqual([c[0][0] for c in learn.call_args_list], ['production'])
