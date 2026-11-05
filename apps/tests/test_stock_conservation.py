"""
Round 2 / R2 — stock count, transfers and transits: conservation and status transitions
(docs/security/2026-11-05-full-project-test-plan.md §7 R2).

Sources:
  * Transfers — docs/architecture/06_WORKFLOW_REGISTRY.md §3 state machine
        DRAFT → PENDING → APPROVED → SENT_TO_ERP → COMPLETED;  PENDING → REJECTED | NEEDS_REVISION → PENDING
    and the can_* properties on apps/transfers/models.TransferRequest (the views refuse anything else
    with 400). The registry also lists APPROVED → CANCELLED, which the code refuses (can_cancel =
    draft / pending / needs_revision): that disagreement is an owner question (see the R2 report), so
    it is not asserted either way here.
  * Transits — apps/transits/models.compute_reconciliation (issued 125 vs received 25): every issued
    unit is either received or reported (missing / qty diff); extras are reported; value_diff =
    received − sent. Views: mark-received only from in_transit / expired_pending, once; force-close
    never from received / force_closed; the viewset is read-only (no PATCH).
  * Stock count — apps/stockcount/engine.process_upload / apply_single_count: expected_qty is never
    modified, difference = counted − expected, variance ok | surplus | deficit; the count-item view
    refuses a negative count ("الكمية يجب ألا تكون سالبة") — the upload path must agree.
    Statuses: draft → snapshot_taken → exported → uploaded → variance_ready → closed; no generic PATCH.
"""
import datetime
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from apps.stockcount import engine as SC
from apps.stockcount.models import StockCountSession, StockCountSnapshot
from apps.transfers.models import TransferRequest, TransferRequestItem
from apps.transits.models import InTransitTransfer, compute_reconciliation

from .factories import make_branch, make_branch2, make_item, make_user

D = Decimal


# ── transits: issued = received + reported shortfall ─────────────────────────
RECON = [
    ('fully received', [('A', 10, 100), ('B', 5, 50)], [('A', 10, 100), ('B', 5, 50)]),
    ('short, missing and extra', [('A', 10, 100), ('B', 5, 50), ('C', 3, 30)],
     [('A', 10, 100), ('B', 3, 30), ('W', 2, 20)]),
    ('over-received', [('A', 1, 10)], [('A', 4, 40)]),
    ('split lines of one item', [('A', 2, 20), ('A', 3, 30)], [('A', 5, 50)]),
    ('fractional packs', [('A', 0.33333, 3.33)], [('A', 0.33333, 3.33)]),
]


def _items(rows):
    return [{'itemcode': c, 'itemname': c, 'qty': q, 'extended_cost': v} for c, q, v in rows]


class TransitReconciliationTests(SimpleTestCase):
    def test_issued_quantity_is_conserved(self):
        for label, sent, recv in RECON:
            with self.subTest(label):
                r = compute_reconciliation(_items(sent), _items(recv))
                s_tot = {c: D('0') for c, _, _ in sent + recv}
                r_tot = dict(s_tot)
                for c, q, _ in sent:
                    s_tot[c] += D(str(q))
                for c, q, _ in recv:
                    r_tot[c] += D(str(q))
                reported = {}                                   # received − sent per item, as reported
                for x in r['missing_items']:
                    reported[x['itemcode']] = D(str(x['received_qty'])) - D(str(x['sent_qty']))
                for x in r['qty_diffs']:
                    reported[x['itemcode']] = D(str(x['diff']))
                for x in r['extra_items']:
                    reported[x['itemcode']] = D(str(x['received_qty']))
                for c in s_tot:
                    self.assertEqual(r_tot[c] - s_tot[c], reported.get(c, D('0')), c)
                self.assertEqual(r['has_discrepancy'], bool(reported))
                self.assertEqual(D(str(r['value_diff'])), D(str(r['received_value'])) - D(str(r['sent_value'])))


class _Api(TestCase):
    def setUp(self):
        self.b1, self.b2 = make_branch(), make_branch2()
        _, self.admin, self.api = make_user('r2_stock_admin', role='admin', branch=self.b1, access_all=True)


class TransitTransitionTests(_Api):
    BASE = '/api/transits/'

    def transit(self, status):
        return InTransitTransfer.objects.create(
            erp_doc_number=f'{InTransitTransfer.objects.count() + 1}', issue_date=datetime.date.today(),
            supplying_branch=self.b1, receiving_branch=self.b2, transit_status=status)

    def test_mark_received_only_from_open_states_and_once(self):
        for st in ('in_transit', 'expired_pending'):
            with self.subTest(st):
                t = self.transit(st)
                self.assertEqual(self.api.post(f'{self.BASE}{t.pk}/mark-received/', {}, format='json').status_code, 200)
                t.refresh_from_db()
                self.assertEqual(t.transit_status, 'received')
                r = self.api.post(f'{self.BASE}{t.pk}/mark-received/', {}, format='json')
                self.assertEqual(r.status_code, 400)
        for st in ('received', 'erp_mismatch', 'cancelled', 'force_closed'):
            with self.subTest(st):
                t = self.transit(st)
                self.assertEqual(self.api.post(f'{self.BASE}{t.pk}/mark-received/', {}, format='json').status_code, 400)
                t.refresh_from_db()
                self.assertEqual(t.transit_status, st)

    def test_force_close_never_reopens_a_closed_transit(self):
        for st in ('received', 'force_closed'):
            with self.subTest(st):
                t = self.transit(st)
                r = self.api.post(f'{self.BASE}{t.pk}/force-close/', {'reason': 'R2 test reason'}, format='json')
                self.assertEqual(r.status_code, 400)
                t.refresh_from_db()
                self.assertEqual(t.transit_status, st)

    def test_status_cannot_be_patched(self):
        t = self.transit('in_transit')
        r = self.api.patch(f'{self.BASE}{t.pk}/', {'transit_status': 'received'}, format='json')
        self.assertEqual(r.status_code, 405)
        t.refresh_from_db()
        self.assertEqual(t.transit_status, 'in_transit')


class TransferTransitionTests(_Api):
    BASE = '/api/transfers/'

    def setUp(self):
        super().setUp()
        self.item = make_item(name='T', softech_id='R2T1')

    def tr(self, status='draft', items=True):
        t = TransferRequest.objects.create(requesting_branch=self.b2, supplying_branch=self.b1, status=status,
                                           created_by=self.admin)
        if items:
            TransferRequestItem.objects.create(request=t, item=self.item, quantity=D('7.500'))
        return t

    def act(self, t, action, body=None):
        return self.api.post(f'{self.BASE}{t.pk}/{action}/', body or {}, format='json')

    def test_the_happy_path_moves_one_step_at_a_time(self):
        t = self.tr()
        steps = [('submit', {}, 'pending'),
                 ('approve', {'items': [{'item_id': self.item.pk, 'approved_quantity': '5.000'}]}, 'approved'),
                 ('send-to-erp', {'erp_reference': '125-1'}, 'sent_to_erp'),
                 ('complete', {'items': [{'item_id': self.item.pk, 'received_quantity': '5.000'}]}, 'completed')]
        for action, body, want in steps:
            with self.subTest(action):
                r = self.act(t, action, body)
                self.assertEqual(r.status_code, 200, r.content)
                t.refresh_from_db()
                self.assertEqual(t.status, want)
        line = t.items.get()
        self.assertEqual((line.quantity, line.approved_quantity, line.received_quantity),
                         (D('7.500'), D('5.000'), D('5.000')))

    # (from status, action, body) — every step that skips or reverses the state machine
    SKIPS = [
        ('draft', 'approve', {}), ('draft', 'send-to-erp', {}), ('draft', 'complete', {}),
        ('draft', 'record-dispatch', {'delivery_person_name': 'م'}),
        ('pending', 'send-to-erp', {}), ('pending', 'complete', {}), ('pending', 'submit', {}),
        ('approved', 'submit', {}), ('approved', 'approve', {}), ('approved', 'complete', {}),
        ('approved', 'reject', {'rejection_reason': 'سبب الرفض'}),
        ('sent_to_erp', 'approve', {}), ('sent_to_erp', 'cancel', {}), ('sent_to_erp', 'submit', {}),
        ('completed', 'complete', {}), ('completed', 'cancel', {}), ('completed', 'send-to-erp', {}),
        ('rejected', 'approve', {}), ('rejected', 'complete', {}),
        ('cancelled', 'submit', {}), ('cancelled', 'approve', {}),
    ]

    def test_a_skipped_or_backward_step_is_refused(self):
        for st, action, body in self.SKIPS:
            with self.subTest(f'{st} → {action}'):
                t = self.tr(st)
                r = self.act(t, action, body)
                self.assertIn(r.status_code, (400, 409), r.content)
                t.refresh_from_db()
                self.assertEqual(t.status, st)

    def test_submit_needs_items_and_status_is_not_patchable(self):
        t = self.tr(items=False)
        self.assertEqual(self.act(t, 'submit').status_code, 400)
        r = self.api.patch(f'{self.BASE}{t.pk}/', {'status': 'completed', 'notes': 'n'}, format='json')
        self.assertIn(r.status_code, (200, 400), r.content)
        t.refresh_from_db()
        self.assertEqual(t.status, 'draft')


class StockCountTests(_Api):
    BASE = '/api/stockcount/sessions/'
    EXPECTED = [('S1', '10.000'), ('S2', '0.500'), ('S3', '3.000'), ('S4', '7.000')]

    def session(self, status='snapshot_taken'):
        s = StockCountSession.objects.create(name='R2', branch_code=self.b1.softech_branch_id, status=status,
                                             created_by=self.admin)
        for code, q in self.EXPECTED:
            StockCountSnapshot.objects.create(session=s, item_code=code, item_name=code,
                                              branch_code=s.branch_code, expected_qty=D(q))
        return s

    def snaps(self, s):
        return {x.item_code: x for x in StockCountSnapshot.objects.filter(session=s)}

    def test_upload_keeps_expected_and_conserves_the_difference(self):
        s = self.session()
        rows = [{'item_code': 'S1', 'counted_qty': D('8')}, {'item_code': 'S2', 'counted_qty': D('0.5')},
                {'item_code': 'S3', 'counted_qty': D('4.25')}, {'item_code': 'NOPE', 'counted_qty': D('1')}]
        out = SC.process_upload(s, rows)
        self.assertEqual(out['rejected'], ['NOPE'])
        snaps = self.snaps(s)
        for code, q in self.EXPECTED:
            self.assertEqual(snaps[code].expected_qty, D(q), code)
        counted = [x for x in snaps.values() if x.counted_qty is not None]
        self.assertEqual(sum((x.difference for x in counted), D('0')),
                         sum((x.counted_qty for x in counted), D('0')) - sum((x.expected_qty for x in counted), D('0')))
        self.assertEqual({c: snaps[c].variance_type for c in ('S1', 'S2', 'S3', 'S4')},
                         {'S1': 'deficit', 'S2': 'ok', 'S3': 'surplus', 'S4': ''})
        s.refresh_from_db()
        self.assertEqual((s.status, s.surplus_count, s.deficit_count, s.ok_count), ('variance_ready', 1, 1, 1))

    def test_upload_refuses_a_negative_count_like_live_entry(self):
        s = self.session()
        r = self.api.post(f'{self.BASE}{s.pk}/count-item/', {'item_code': 'S1', 'counted_qty': '-2'}, format='json')
        self.assertEqual(r.status_code, 400)
        out = SC.process_upload(s, [{'item_code': 'S1', 'counted_qty': D('-2')},
                                    {'item_code': 'S2', 'counted_qty': D('1')}])
        self.assertEqual(out['rejected'], ['S1'])
        snaps = self.snaps(s)
        self.assertIsNone(snaps['S1'].counted_qty)
        self.assertEqual(snaps['S2'].counted_qty, D('1.000'))

    def test_upload_file_with_a_negative_count(self):
        s = self.session()
        csv = 'item_code,counted_qty\nS1,-2\nS2,1\n'.encode('utf-8')
        f = SimpleUploadedFile('count.csv', csv, content_type='text/csv')
        r = self.api.post(f'{self.BASE}{s.pk}/upload-results/', {'file': f}, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIsNone(self.snaps(s)['S1'].counted_qty)

    def test_steps_cannot_be_skipped(self):
        cases = [('draft', 'upload-results', 400), ('draft', 'count-item', 400), ('draft', 'close', 400),
                 ('snapshot_taken', 'close', 400), ('exported', 'close', 400),
                 ('closed', 'count-item', 400), ('closed', 'generate-snapshot', 400),
                 ('closed', 'upload-results', 400), ('variance_ready', 'generate-snapshot', 400)]
        for st, action, code in cases:
            with self.subTest(f'{st} → {action}'):
                s = self.session(st)
                body = {'item_code': 'S1', 'counted_qty': '1'} if action == 'count-item' else {}
                if action == 'upload-results':
                    body = {'file': SimpleUploadedFile('c.csv', b'item_code,counted_qty\nS1,1\n')}
                r = self.api.post(f'{self.BASE}{s.pk}/{action}/', body,
                                  format='multipart' if action == 'upload-results' else 'json')
                self.assertEqual(r.status_code, code, r.content)
                s.refresh_from_db()
                self.assertEqual(s.status, st)
                self.assertTrue(all(x.counted_qty is None for x in self.snaps(s).values()))

    def test_close_is_one_step_from_variance(self):
        s = self.session('variance_ready')
        self.assertEqual(self.api.post(f'{self.BASE}{s.pk}/close/').status_code, 200)
        s.refresh_from_db()
        self.assertEqual(s.status, 'closed')
        r = self.api.patch(f'{self.BASE}{s.pk}/', {'status': 'variance_ready'}, format='json')
        self.assertEqual(r.status_code, 405)
