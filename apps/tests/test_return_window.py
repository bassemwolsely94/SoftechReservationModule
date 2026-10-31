"""
apps/tests/test_return_window.py

P-29 (docs/product-review/06_SPEC_P-29_return_window_calendar.md): supplier return-window calendar.
Window = expiry month −2 … +1 per supplier policy; 565 + 260 seeded. Advisory only — nothing here
writes to SOFTECH. Owner decisions 2026-10-31: returns are owned by the HQ purchasing role; the closed
store 110 is excluded everywhere.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.batches.return_window import window_for

D = dt.date
TODAY = D(2026, 10, 31)


class WindowMathsTests(SimpleTestCase):

    def test_default_window(self):
        w = window_for(D(2026, 12, 15), TODAY)
        self.assertEqual((w['opens'], w['closes']), (D(2026, 10, 1), D(2027, 1, 31)))

    def test_year_roll_over(self):
        w = window_for(D(2027, 1, 10), TODAY)
        self.assertEqual((w['opens'], w['closes']), (D(2026, 11, 1), D(2027, 2, 28)))

    def test_custom_offsets(self):
        w = window_for(D(2026, 12, 15), TODAY, open_offset=-3, close_offset=0)
        self.assertEqual((w['opens'], w['closes']), (D(2026, 9, 1), D(2026, 12, 31)))

    def test_states(self):
        exp = D(2026, 12, 15)          # window 2026-10-01 … 2027-01-31
        cases = {D(2026, 8, 1): 'later', D(2026, 9, 15): 'opens_next_month', D(2026, 10, 31): 'open',
                 D(2027, 1, 5): 'closes_this_month', D(2027, 2, 1): 'missed'}
        for today, state in cases.items():
            with self.subTest(today=today):
                self.assertEqual(window_for(exp, today)['state'], state)


def _stock(item, branch='130', store='101', exp=D(2026, 12, 15), qty='10', batch='L1'):
    from apps.batches.models import StockExpiryBalance
    return StockExpiryBalance.objects.create(branch_code=branch, store_code=store, item_code=item, item_name=item,
                                             batch_no=batch, expiry_date=exp, qty=Decimal(qty))


def _entry(item, supplier, exp, doc='1'):
    from apps.batches.models import PurchaseExpiryEntry
    return PurchaseExpiryEntry.objects.create(branch_code='100', supplier_code=supplier, supplier_name=f'S{supplier}',
                                              doc_number=doc, doc_date=D(2026, 1, 1), item_code=item,
                                              entered_expiry=exp, qty=Decimal('100'))


class Base(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        from apps.tests.factories import make_branch
        self.hq = make_branch('الرئيسي', '100')
        self.b130 = make_branch('فرع 130', '130')
        self.b140 = make_branch('فرع 140', '140')
        for code in ('A', 'B', 'C', 'D', 'E', 'F'):
            Item.objects.create(softech_id=code, name=f'Item {code}', cost_price=Decimal('10'))

    def cal(self, **kw):
        from apps.batches.return_calendar import calendar
        return calendar(today=TODAY, **kw)


class PolicySeedTests(Base):

    def test_565_and_260_seeded_only(self):
        from apps.procurement.models import SupplierReturnPolicy
        rows = {p.supplier_code: p for p in SupplierReturnPolicy.objects.all()}
        self.assertEqual(set(rows), {'565', '260'})
        p = rows['565']
        self.assertTrue(p.accepts_expiry_returns and p.self_entry)
        self.assertEqual((p.open_offset, p.close_offset), (-2, 1))


class AttributionTests(Base):

    def test_confidences(self):
        from apps.batches.return_calendar import attribute
        _entry('A', '565', D(2026, 12, 15))                       # exact
        _entry('B', '565', D(2026, 12, 3))                        # month only
        _entry('C', '565', D(2026, 12, 15)); _entry('C', '260', D(2026, 12, 20), doc='2')   # ambiguous
        match = attribute([('A', D(2026, 12, 15)), ('B', D(2026, 12, 15)), ('C', D(2026, 12, 15)),
                           ('D', D(2026, 12, 15))])
        self.assertEqual(match[('A', D(2026, 12, 15))]['confidence'], 'exact')
        self.assertEqual(match[('A', D(2026, 12, 15))]['suppliers'], ['565'])
        self.assertEqual(match[('B', D(2026, 12, 15))]['confidence'], 'month')
        self.assertEqual(match[('C', D(2026, 12, 15))]['confidence'], 'ambiguous')
        self.assertEqual(match[('C', D(2026, 12, 15))]['suppliers'], ['260', '565'])
        self.assertEqual(match[('D', D(2026, 12, 15))]['confidence'], 'none')


class CalendarTests(Base):

    def setUp(self):
        super().setUp()
        _entry('A', '565', D(2026, 12, 15))
        _entry('B', '260', D(2027, 1, 20))
        _entry('C', '999', D(2026, 12, 15))                      # a supplier without a policy
        _entry('E', '565', D(2026, 10, 10))
        _stock('A')                                             # 565, open → value 100
        _stock('A', '100', '105', qty='5')                      # 105 return candidate, open → 50
        _stock('B', exp=D(2027, 1, 20), qty='2')                # 260, opens 2026-11-01 → next month
        _stock('C', qty='3')                                    # no policy → own section
        _stock('A', '100', '110', qty='999')                    # closed store, never listed
        _stock('A', '100', '102', qty='7')                      # write-off store, not a return line
        _stock('E', exp=D(2026, 10, 10), qty='1')               # window closes 2026-11-30 → open
        _stock('F', exp=D(2027, 6, 1), qty='1')                 # later → not shown

    def test_lines_and_states(self):
        c = self.cal()
        got = {(l['item_code'], l['branch_code'], l['store_code']): l for l in c['lines']}
        self.assertEqual(set(got), {('A', '130', '101'), ('A', '100', '105'), ('B', '130', '101'),
                                    ('C', '130', '101'), ('E', '130', '101')})
        a = got[('A', '130', '101')]
        self.assertEqual((a['state'], a['supplier_code'], a['confidence'], a['value']),
                         ('open', '565', 'exact', 100.0))
        self.assertEqual(a['closes'], '2027-01-31')
        self.assertEqual(got[('B', '130', '101')]['state'], 'opens_next_month')
        self.assertEqual(got[('C', '130', '101')]['confidence'], 'none')

    def test_send_by_for_branch_lines_only(self):
        got = {(l['branch_code'], l['store_code'], l['item_code']): l for l in self.cal()['lines']}
        self.assertEqual(got[('130', '101', 'A')]['send_by'], '2027-01-17')       # closes − 14 days
        self.assertIsNone(got[('100', '105', 'A')]['send_by'])

    def test_summary_and_no_policy_section(self):
        c = self.cal()
        s = c['suppliers']['565']
        self.assertEqual(s['open']['value'], 160.0)            # A shelf 100 + A 105 50 + E 10
        self.assertEqual(c['suppliers']['260']['opens_next_month']['value'], 20.0)
        self.assertEqual(c['no_policy'], [{'supplier_code': '999', 'supplier_name': 'S999', 'value': 30.0}])

    def test_filters(self):
        self.assertEqual({l['item_code'] for l in self.cal(supplier='260')['lines']}, {'B'})
        self.assertEqual({l['store_code'] for l in self.cal(location='105')['lines']}, {'105'})
        self.assertEqual({l['branch_code'] for l in self.cal(branch_codes=['130'])['lines']}, {'130'})


class AmbiguousPickTests(Base):

    def test_picked_supplier_shows_on_the_line(self):
        from apps.batches.return_calendar import calendar, request_returns
        _entry('C', '565', D(2026, 12, 15)); _entry('C', '260', D(2026, 12, 20), doc='2')
        _stock('C')
        line = calendar(today=TODAY)['lines'][0]
        self.assertEqual((line['confidence'], line['supplier_code'], line['record']), ('ambiguous', '', None))
        req = {k: line[k] for k in ('branch_code', 'store_code', 'item_code', 'batch_no', 'expiry_date')}
        self.assertEqual(request_returns([dict(req, supplier_code='999')], None, today=TODAY), 0)   # not a candidate
        self.assertEqual(request_returns([dict(req, supplier_code='260')], None, today=TODAY), 1)
        line = calendar(today=TODAY)['lines'][0]
        self.assertEqual((line['supplier_code'], line['record']['status']), ('260', 'draft'))


class ApiTests(Base):

    URL = '/api/batches/return-window/'

    def setUp(self):
        super().setUp()
        from apps.tests.factories import make_user
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()                       # the owner's real RBAC matrix
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _entry('A', '565', D(2026, 12, 15))
        _stock('A')
        _stock('A', '140', '101', qty='4')
        _, self.buyer_staff, self.buyer = make_user('buyer', role='purchasing')
        _, _, self.ph130 = make_user('ph130', role='pharmacist', branch=self.b130)
        _, _, self.viewer = make_user('view', role='viewer')
        self.line = {'branch_code': '130', 'store_code': '101', 'item_code': 'A', 'batch_no': 'L1',
                     'expiry_date': '2026-12-15', 'supplier_code': '565'}

    def _today(self):
        return mock.patch('apps.batches.return_calendar._today', return_value=TODAY)

    def test_branch_user_sees_own_branch_only(self):
        with self._today():
            r = self.ph130.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual({l['branch_code'] for l in r.data['lines']}, {'130'})
        with self._today():
            self.assertEqual({l['branch_code'] for l in self.buyer.get(self.URL).data['lines']}, {'130', '140'})

    def test_request_is_idempotent_and_uses_server_qty(self):
        from apps.batches.models import ExpiryDisposalRecord
        from apps.audit.models import AuditLog
        line = dict(self.line, qty=9999)
        with self._today():
            r1 = self.buyer.post(self.URL + 'request/', {'lines': [line]}, format='json')
            r2 = self.buyer.post(self.URL + 'request/', {'lines': [line]}, format='json')
        self.assertEqual((r1.status_code, r1.data['created'], r2.data['created']), (200, 1, 0))
        rec = ExpiryDisposalRecord.objects.get()
        self.assertEqual((rec.decision, rec.source, rec.status, rec.qty), ('return_supplier', 'return_window',
                                                                            'draft', Decimal('10')))
        self.assertEqual(rec.window_closes, D(2027, 1, 31))
        self.assertEqual(rec.match_confidence, 'exact')
        self.assertTrue(AuditLog.objects.filter(action='return_requested').exists())

    def test_viewer_cannot_request(self):
        r = self.viewer.post(self.URL + 'request/', {'lines': [self.line]}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_branch_user_cannot_request_another_branch(self):
        line = dict(self.line, branch_code='140')
        with self._today():
            r = self.ph130.post(self.URL + 'request/', {'lines': [line]}, format='json')
        self.assertEqual(r.data['created'], 0)

    def test_answer_and_rejection(self):
        from apps.batches.models import ExpiryDisposalRecord
        from apps.audit.models import AuditLog
        with self._today():
            self.buyer.post(self.URL + 'request/', {'lines': [self.line]}, format='json')
        rec = ExpiryDisposalRecord.objects.get()
        r = self.buyer.post(f'{self.URL}{rec.pk}/answer/', {'answer': 'partial', 'accepted_qty': 6,
                                                           'allowed_expiry': '2026-12-01'}, format='json')
        self.assertEqual(r.status_code, 200)
        rec.refresh_from_db()
        self.assertEqual((rec.supplier_answer, rec.accepted_qty, rec.allowed_expiry, rec.status),
                         ('partial', Decimal('6'), D(2026, 12, 1), 'draft'))
        self.buyer.post(f'{self.URL}{rec.pk}/answer/', {'answer': 'rejected'}, format='json')
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'cancelled')
        self.assertIn('رفض المورد', rec.reason)
        self.assertEqual(AuditLog.objects.filter(action='return_answered').count(), 2)
        self.assertEqual(self.buyer.post(f'{self.URL}{rec.pk}/answer/', {'answer': 'maybe'},
                                         format='json').status_code, 400)

    def test_policy_edit_permissions_and_audit(self):
        from apps.procurement.models import SupplierReturnPolicy
        from apps.audit.models import AuditLog
        body = {'supplier_code': '30', 'accepts_expiry_returns': True, 'open_offset': -1, 'close_offset': 0}
        self.assertEqual(self.ph130.post(self.URL + 'policies/', body, format='json').status_code, 403)
        r = self.buyer.post(self.URL + 'policies/', body, format='json')
        self.assertEqual(r.status_code, 200)
        p = SupplierReturnPolicy.objects.get(supplier_code='30')
        self.assertEqual((p.open_offset, p.close_offset, p.updated_by_id), (-1, 0, self.buyer_staff.pk))
        self.assertTrue(AuditLog.objects.filter(action='return_policy_changed').exists())
        self.assertEqual(self.buyer.post(self.URL + 'policies/', dict(body, open_offset=5),
                                         format='json').status_code, 400)
        self.assertEqual(len(self.ph130.get(self.URL + 'policies/').data['policies']), 3)

    def test_supplier_export(self):
        with self._today():
            r = self.buyer.post(self.URL + 'export/', {'supplier_code': '565'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])


class ReconcileTests(Base):

    def setUp(self):
        super().setUp()
        from apps.batches.models import ExpiryDisposalRecord
        self.rec = ExpiryDisposalRecord.objects.create(
            item_code='A', branch_code='100', store_code='105', qty=Decimal('10'), decision='return_supplier',
            source='return_window', supplier_code='565', window_closes=D(2027, 1, 31))
        ExpiryDisposalRecord.objects.filter(pk=self.rec.pk).update(
            created_at=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc))

    def _ret(self, qty, doc='9', day=D(2026, 10, 20), supplier='565', item='A'):
        from apps.procurement.models import PurchaseLine
        return PurchaseLine.objects.create(branch_code='100', supplier_code=supplier, doc_number=doc, doc_date=day,
                                           item_code=item, doccode='120', is_return=True, raw_qty=Decimal(-qty))

    def test_doc_120_closes_once(self):
        from apps.batches.return_calendar import reconcile_returns
        self._ret(10)
        self._ret(5, supplier='260', doc='8')                  # other supplier: ignored
        self.assertEqual(reconcile_returns()['closed'], 1)
        self.rec.refresh_from_db()
        self.assertEqual((self.rec.status, self.rec.returned_qty), ('done', Decimal('10')))
        self.assertEqual(len(self.rec.softech_doc_refs), 1)
        self.assertIsNotNone(self.rec.closed_by_ledger_at)
        self.assertEqual(reconcile_returns(), {'closed': 0, 'partial': 0, 'lines_used': 0})

    def test_partial_stays_open_and_old_returns_ignored(self):
        from apps.batches.return_calendar import reconcile_returns
        self._ret(4, day=D(2026, 9, 1), doc='7')              # before the record: not ours
        self._ret(4)
        out = reconcile_returns()
        self.rec.refresh_from_db()
        self.assertEqual((out['partial'], self.rec.status, self.rec.returned_qty), (1, 'draft', Decimal('4')))
        self._ret(6, doc='10')
        reconcile_returns()
        self.rec.refresh_from_db()
        self.assertEqual((self.rec.status, self.rec.returned_qty), ('done', Decimal('10')))


class HistoryTests(Base):

    def test_counts_per_supplier_item(self):
        from apps.batches.models import ExpiryDisposalRecord
        from apps.batches.return_calendar import answer_history
        for ans in ('accepted', 'accepted', 'rejected'):
            ExpiryDisposalRecord.objects.create(item_code='A', branch_code='130', qty=1, decision='return_supplier',
                                                supplier_code='565', supplier_answer=ans)
        h = answer_history()
        self.assertEqual(h[('565', 'A')]['accepted'], 2)
        self.assertEqual(h[('565', 'A')]['rejected'], 1)
        self.assertEqual(h[('565', 'A')]['last'], 'rejected')


class DigestTests(Base):

    def setUp(self):
        super().setUp()
        from apps.tests.factories import make_user
        _entry('A', '565', D(2026, 12, 15))
        _stock('A')
        _, self.buyer, _ = make_user('buyer2', role='purchasing')
        _, self.admin, _ = make_user('adm2', role='admin')

    def test_monthly_digest_once_to_purchasing_and_snapshot(self):
        from apps.batches.models import ReturnWindowMonthly
        from apps.batches.return_calendar import monthly_digest
        from apps.notifications.models import Notification
        out = monthly_digest(today=D(2026, 11, 1))
        self.assertEqual(out['sent'], 1)
        n = Notification.objects.get()
        self.assertEqual((n.recipient_id, n.notification_type), (self.buyer.pk, 'return_window_digest'))
        snap = ReturnWindowMonthly.objects.get(supplier_code='565', month=D(2026, 11, 1))
        self.assertEqual(snap.open_value, Decimal('100'))
        self.assertEqual(monthly_digest(today=D(2026, 11, 1))['sent'], 0)
        self.assertEqual(ReturnWindowMonthly.objects.count(), 1)


class WorklistSectionTests(Base):

    def test_branch_send_by_lines(self):
        from apps.batches.return_calendar import branch_send_lines
        _entry('A', '565', D(2026, 12, 15))
        _stock('A')
        _stock('A', '100', '105')
        lines = branch_send_lines('130', today=TODAY)
        self.assertEqual(len(lines), 1)
        self.assertIn('2027-01-17', lines[0])


class WiringTests(SimpleTestCase):

    def test_freshness_domain(self):
        from apps.sync.freshness import DOMAINS, _SOURCES
        self.assertIn('purchase_expiry', DOMAINS)
        self.assertIn('purchase_expiry', _SOURCES)

    def test_scheduler_jobs(self):
        from apps.sync import tasks
        from .test_scheduler_jobs import _FakeScheduler
        with mock.patch.object(tasks, 'BackgroundScheduler', _FakeScheduler), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
            ids = {j[1] for j in tasks._scheduler.jobs}
        self.assertTrue({'return_window_reconcile', 'return_window_digest'} <= ids)


class IngestionUnionTests(Base):

    def test_policy_suppliers_are_mirrored(self):
        from apps.batches.expiry_audit import ingest_suppliers
        from apps.procurement.models import SupplierSegmentation
        SupplierSegmentation.objects.create(supplier_code='30', supplier_name='Ramco',
                                            supplier_category='OFFICIAL_DISTRIBUTOR')
        got = ingest_suppliers()
        self.assertTrue({'30', '565', '260'} <= set(got))
