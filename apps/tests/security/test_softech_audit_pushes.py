"""
SOFTECH write safety — who pushed (CLAUDE.md rule 8; Batch 2, P-16b).

Invoice and POS pushes kept the SOFTECH payload and readback but never WHO pushed; the
sales-rate execute dropped executed_by; ISR approve / push and the coverage commands only
logged. Every one now leaves an AuditLog row. POS: the audit sits in the views only — the
checkout writer (push_order / cancel_order) is not touched.
"""
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.tests.factories import make_admin, make_branch, make_item, make_user



def _row(action):
    return AuditLog.objects.filter(action=action).order_by('-id').first()


class InvoicePushAuditTests(TestCase):

    def setUp(self):
        from apps.invoices.models import InvoiceLine, SupplierInvoice, VendorProfile
        self.user, self.staff, self.client = make_admin('inv_pusher')
        vendor = VendorProfile.objects.create(name='V', softech_personcode='5014', is_main=True)
        self.inv = SupplierInvoice.objects.create(branch=make_branch(), vendor=vendor, supplier_name='S',
                                                  invoice_number='111', status='confirmed')
        InvoiceLine.objects.create(invoice=self.inv, item=make_item(softech_id='90792'), manual_name='X',
                                   quantity=5, public_price=28, unit_price=22.10)
        self.pushed = {'mode': 'commit', 'wrote_to_softech': True, 'ok': True, 'docnumber': 4711}

    def test_push_records_who(self):
        with mock.patch('apps.invoices.writer.push_final', return_value=self.pushed):
            r = self.client.post(f'/api/invoices/invoices/{self.inv.id}/push/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        row = _row('softech_invoice_pushed')
        self.assertIsNotNone(row, 'invoice written to SOFTECH with no record of who pushed it')
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.new_data['docnumber'], 4711)

    def test_batch_push_records_who(self):
        with mock.patch('apps.invoices.writer.push_final', return_value=self.pushed):
            self.client.post('/api/invoices/invoices/push-batch/', {'invoice_ids': [self.inv.id]},
                             format='json')
        row = _row('softech_invoice_pushed')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)

    def test_dry_run_is_not_audited_as_a_push(self):
        with mock.patch('apps.invoices.writer.push_final',
                        return_value={'mode': 'dry_run', 'wrote_to_softech': False}):
            self.client.post(f'/api/invoices/invoices/{self.inv.id}/push/', {}, format='json')
        self.assertIsNone(_row('softech_invoice_pushed'))


@override_settings(POS_WRITER_ENABLED=True)
class PosPushAuditTests(TestCase):

    def setUp(self):
        from apps.pos_orders.models import SoftechSalesOrder
        branch = make_branch()
        self.user, self.staff, self.client = make_user('pos_pusher', role='pharmacist')
        self.order = SoftechSalesOrder.objects.create(
            branch=branch, softech_branchcode=branch.softech_branch_id, store_code='1',
            seller_usercode='1', softech_pic='PIC', channel='cash')

    def test_push_records_who(self):
        with mock.patch('apps.pos_orders.views.validate_order'), \
                mock.patch('apps.pos_orders.views.writer.writer_enabled', return_value=True), \
                mock.patch('apps.pos_orders.views.writer.push_order',
                           return_value={'mode': 'commit', 'wrote_to_softech': True, 'ok': True,
                                         'docnumber': 5123}):
            self.client.post(f'/api/pos-orders/{self.order.id}/push/', {'dry_run': False, 'confirm': True},
                             format='json')
        row = _row('softech_pos_order_pushed')
        self.assertIsNotNone(row, 'sale written to SOFTECH with no record of who pushed it')
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.new_data['docnumber'], 5123)

    def test_cancel_records_who(self):
        with mock.patch('apps.pos_orders.views.writer.cancel_order'):
            self.client.post(f'/api/pos-orders/{self.order.id}/cancel/', {}, format='json')
        row = _row('softech_pos_order_cancelled')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)


class PurchasingAuditTests(TestCase):

    def setUp(self):
        self.user, self.staff, _ = make_admin('supply_admin')
        self.branch = make_branch(softech_id='130')

    @override_settings(SALES_RATE_WRITER_ENABLED=True)
    def test_rate_execute_records_who(self):
        from apps.purchasing import rate_writer
        from apps.purchasing.models import SalesRatePush, SalesRatePushLine
        push = SalesRatePush.objects.create(status=SalesRatePush.STATUS_APPROVED)
        SalesRatePushLine.objects.create(push=push, itemcode='A1', branchcode='130', storecode='130',
                                         old_rate=Decimal('2'), new_rate=Decimal('3'))
        with mock.patch.object(rate_writer, '_write_all_surfaces', return_value=({'A1': True}, [])):
            rate_writer.execute_push(push, executed_by=self.user)
        row = _row('softech_sales_rates_written')
        self.assertIsNotNone(row, 'executed_by was dropped')
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.new_data['verified'], 1)

    @override_settings(ISR_WRITER_ENABLED=True)
    def test_isr_approve_records_who_and_prior_state(self):
        from apps.purchasing import isr_writer
        cur = mock.MagicMock()
        cur.fetchone.side_effect = [(0,), (1,)]
        conn = mock.MagicMock(); conn.cursor.return_value = cur
        with mock.patch('config.sybase.get_branch_connection', return_value=conn):
            isr_writer.approve_isr('130', 2613000001, executed_by=self.user)
        row = _row('softech_isr_approved')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.old_data, {'israpp': 0})

    @override_settings(ISR_WRITER_ENABLED=True)
    def test_isr_push_records_who(self):
        from apps.purchasing import isr_writer as W
        from apps.purchasing.models import IsrPush as P
        from apps.tests.test_isr_guards import _lines
        make_branch(softech_id='100'), make_branch(softech_id='160')
        p = W._persist_proposal(source='100', dest='160', kind=P.KIND_HQ_TO_BRANCH, lines=_lines(('A', 2)))
        P.objects.filter(pk=p.pk).update(status=P.STATUS_APPROVED)
        p.refresh_from_db()
        with mock.patch('config.sybase.get_branch_connection'), \
                mock.patch.object(W, '_write_isr', return_value={'verified': True, 'committed': True,
                                                                 'isrdocnumber': 2610000042}):
            W.push_isr_record(p, executed_by=self.user)
        row = _row('softech_isr_pushed')
        self.assertIsNotNone(row)
        self.assertEqual(row.user_id, self.staff.pk)
        self.assertEqual(row.new_data['isrdocnumber'], 2610000042)

    @override_settings(COVERAGE_WRITER_ENABLED=True)
    def test_coverage_push_is_audited(self):
        from apps.purchasing import coverage_writer as cw
        plan = {'coverage_months': 2.0, 'target': 'node', 'totals': {'eligible': 1, 'branches': 1},
                'branches': [{'reachable': True, 'branchcode': '130', 'store': '130',
                              'changes': [{'itemcode': 'A1', 'eligible': True}]}]}
        with mock.patch.object(cw, 'build_coverage_plan', return_value=plan), \
                mock.patch.object(cw, '_write_surface_with_resume', return_value=({'A1': True}, [])):
            cw.push_coverage(coverage_months=2.0, dry_run=False, target='node')
        row = _row('softech_coverage_written')
        self.assertIsNotNone(row, 'coverage written to SOFTECH with only a logger line')
        self.assertEqual(row.new_data['verified'], 1)
