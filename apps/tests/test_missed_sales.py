"""
apps/tests/test_missed_sales.py — Project 3 (a): missed sales → reservation SUGGESTIONS.

Detector rules (sold / waiting / customer / open / expiry / idempotency), the inbox API (scope,
flag), reject (reason + audit) and the confirm path through POST /reservations/ (exactly one
reservation; double confirm 409; another branch 404). Postgres only — no SOFTECH contact.
"""
import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from apps.pic_analytics.models import PicExclusion
from apps.pos_orders.missed_sales import detect_missed_sales
from apps.pos_orders.models import (
    MissedSaleSuggestion, PosSelectionEvent, SoftechSalesOrder, SoftechSalesOrderLine,
)
from apps.reservations.models import Reservation
from .factories import make_branch, make_branch2, make_customer, make_item, make_pharmacist

ON = override_settings(MISSED_SALES_ENABLED=True, MISSED_SALES_MIN_AGE_MINUTES=60,
                       MISSED_SALES_EXPIRE_DAYS=14)


def _event(branch, customer, *, token=None, code='IT001', ago_min=120, qty=1, total='50', kind='sale'):
    return PosSelectionEvent.objects.create(
        cart_token=token or uuid.uuid4(), branch=branch, softech_branchcode=branch.softech_branch_id,
        doc_kind=kind, event_type='add', item_code=code, item_name='باراسيتامول',
        itemsaleprice=total, transprice=total, transqty=qty, transprice_total=total,
        custcode='1510', seller_usercode='1509', customer=customer,
        occurred_at=timezone.now() - timedelta(minutes=ago_min))


def _order(branch, token, status, codes=()):
    o = SoftechSalesOrder.objects.create(
        branch=branch, softech_branchcode=branch.softech_branch_id, store_code='B01', channel='cash',
        doc_kind='sale', customer_name='T', client_token=token, status=status)
    for c in codes:
        SoftechSalesOrderLine.objects.create(order=o, softech_itemcode=c, item_name='X', qty=1,
                                             item_sale_price=10)
    return o


class _Base(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.item = make_item()
        self.customer = make_customer()
        self.customer.softech_pic = '170HD1'
        self.customer.save()


@ON
class DetectorTests(_Base):
    def test_unsold_item_for_known_customer_becomes_suggestion(self):
        _event(self.branch, self.customer)
        s = detect_missed_sales()
        self.assertEqual(s['created'], 1)
        m = MissedSaleSuggestion.objects.get()
        self.assertEqual((m.customer, m.branch, m.item_code, m.status),
                         (self.customer, self.branch, 'IT001', 'new'))

    def test_rerun_creates_nothing_new(self):
        _event(self.branch, self.customer)
        detect_missed_sales()
        self.assertEqual(detect_missed_sales()['created'], 0)
        self.assertEqual(MissedSaleSuggestion.objects.count(), 1)

    def test_sold_in_cart_order_skipped(self):
        tok = uuid.uuid4()
        _event(self.branch, self.customer, token=tok)
        _order(self.branch, tok, SoftechSalesOrder.STATUS_SETTLED, codes=['IT001'])
        self.assertEqual(detect_missed_sales()['created'], 0)

    def test_order_still_being_worked_waits(self):
        tok = uuid.uuid4()
        _event(self.branch, self.customer, token=tok)
        _order(self.branch, tok, SoftechSalesOrder.STATUS_READY)
        s = detect_missed_sales()
        self.assertEqual((s['created'], s['waiting']), (0, 1))

    def test_other_item_of_a_pushed_cart_is_missed(self):
        tok = uuid.uuid4()
        _event(self.branch, self.customer, token=tok, code='IT001')
        _event(self.branch, self.customer, token=tok, code='IT002')
        _order(self.branch, tok, SoftechSalesOrder.STATUS_PUSHED, codes=['IT002'])
        detect_missed_sales()
        self.assertEqual(list(MissedSaleSuggestion.objects.values_list('item_code', flat=True)), ['IT001'])

    def test_customer_taken_from_order_when_event_has_none(self):
        tok = uuid.uuid4()
        _event(self.branch, None, token=tok)
        o = _order(self.branch, tok, SoftechSalesOrder.STATUS_CANCELLED)
        o.customer = self.customer
        o.save()
        self.assertEqual(detect_missed_sales()['created'], 1)

    def test_no_customer_skipped(self):
        _event(self.branch, None)
        self.assertEqual(detect_missed_sales()['skipped_customer'], 1)

    def test_bought_later_in_softech_skipped(self):
        _event(self.branch, self.customer)
        p = PurchaseHistory.objects.create(customer=self.customer, softech_invoice_id='X1',
                                           branch=self.branch, doc_code='115', invoice_date=timezone.now())
        PurchaseHistoryLine.objects.create(purchase=p, item=self.item, quantity=1, unit_price=50,
                                           line_total=50)
        self.assertEqual(detect_missed_sales()['created'], 0)

    def test_placeholder_and_excluded_customers_skipped(self):
        self.customer.is_account_placeholder = True
        self.customer.save()
        _event(self.branch, self.customer)
        self.assertEqual(detect_missed_sales()['created'], 0)
        self.customer.is_account_placeholder = False
        self.customer.save()
        PicExclusion.objects.create(pic='170HD1', reason='حساب')
        _event(self.branch, self.customer)
        self.assertEqual(detect_missed_sales()['created'], 0)

    def test_too_recent_and_return_carts_skipped(self):
        _event(self.branch, self.customer, ago_min=10)
        _event(self.branch, self.customer, kind='return')
        self.assertEqual(detect_missed_sales()['created'], 0)

    def test_one_open_suggestion_per_customer_item(self):
        _event(self.branch, self.customer)
        _event(self.branch, self.customer)                   # a second cart, same customer + item
        detect_missed_sales()
        self.assertEqual(MissedSaleSuggestion.objects.count(), 1)

    def test_open_reservation_blocks_suggestion(self):
        Reservation.objects.create(customer=self.customer, item=self.item, branch=self.branch,
                                   contact_phone='01012345678', contact_name='x', status='pending')
        _event(self.branch, self.customer)
        self.assertEqual(detect_missed_sales()['skipped_open'], 1)

    def test_old_suggestions_expire(self):
        _event(self.branch, self.customer)
        detect_missed_sales()
        MissedSaleSuggestion.objects.update(seen_at=timezone.now() - timedelta(days=15))
        self.assertEqual(detect_missed_sales()['expired'], 1)
        self.assertEqual(MissedSaleSuggestion.objects.get().status, 'expired')


class _ApiBase(_Base):
    def setUp(self):
        super().setUp()
        _event(self.branch, self.customer)
        with ON:
            detect_missed_sales()
        self.m = MissedSaleSuggestion.objects.get()
        _, self.prof, self.client = make_pharmacist('ph_missed', branch=self.branch)

    def _confirm(self, client=None, **extra):
        body = {'customer': self.customer.pk, 'item': self.item.pk, 'branch': self.branch.pk,
                'quantity_requested': 1, 'contact_phone': '01012345678', 'contact_name': 'أحمد',
                'order_source': 'pos_missed', 'missed_sale': self.m.pk, **extra}
        return (client or self.client).post('/api/reservations/', body, format='json')


@ON
class InboxApiTests(_ApiBase):
    def test_list_scoped_to_branch(self):
        r = self.client.get('/api/pos-orders/missed-sales/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([x['id'] for x in r.json()['results']], [self.m.pk])
        other = make_branch2()
        _, _, c2 = make_pharmacist('ph_other', branch=other)
        self.assertEqual(c2.get('/api/pos-orders/missed-sales/').json()['results'], [])

    def test_reject_requires_reason(self):
        url = f'/api/pos-orders/missed-sales/{self.m.pk}/reject/'
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'reason': 'other'}, format='json').status_code, 400)

    def test_reject_audit(self):
        r = self.client.post(f'/api/pos-orders/missed-sales/{self.m.pk}/reject/',
                             {'reason': 'price_check'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.m.refresh_from_db()
        self.assertEqual((self.m.status, self.m.reject_reason, self.m.decided_by), ('rejected', 'price_check', self.prof))
        self.assertTrue(AuditLog.objects.filter(action='missed_sale_rejected', object_id=str(self.m.pk)).exists())
        again = self.client.post(f'/api/pos-orders/missed-sales/{self.m.pk}/reject/',
                                 {'reason': 'price_check'}, format='json')
        self.assertEqual(again.status_code, 409)

    def test_confirm_creates_one_reservation(self):
        r = self._confirm()
        self.assertEqual(r.status_code, 201, r.content)
        self.m.refresh_from_db()
        res = Reservation.objects.get()
        self.assertEqual((self.m.status, self.m.reservation, self.m.decided_by), ('confirmed', res, self.prof))
        self.assertEqual(res.order_source, 'pos_missed')
        self.assertTrue(AuditLog.objects.filter(action='missed_sale_confirmed').exists())
        self.assertTrue(res.activities.filter(message__contains=f'#{self.m.pk}').exists())

    def test_confirm_twice_conflict(self):
        self.assertEqual(self._confirm().status_code, 201)
        self.assertEqual(self._confirm().status_code, 409)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_confirm_out_of_scope(self):
        other = make_branch2()
        _, _, c2 = make_pharmacist('ph_other2', branch=other)
        r = self._confirm(client=c2, branch=other.pk)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_confirm_must_keep_the_customer(self):
        other = make_customer(name='آخر', phone='01099999999')
        r = self._confirm(customer=other.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Reservation.objects.count(), 0)

    def test_failed_reservation_leaves_suggestion_new(self):
        r = self._confirm(quantity_requested=0)
        self.assertEqual(r.status_code, 400)
        self.m.refresh_from_db()
        self.assertEqual(self.m.status, 'new')


class FlagOffTests(_ApiBase):
    def test_flag_off_503(self):
        self.assertEqual(self.client.get('/api/pos-orders/missed-sales/').status_code, 503)
        self.assertEqual(self._confirm().status_code, 503)
        self.assertEqual(Reservation.objects.count(), 0)
