"""
C33 — reservation stock check on every line, not the header item only.

Mixed-availability basket: the header is in stock, one extra line is short → «بعض الأصناف ناقصة»,
and the automatic «المخزون متاح» promotion leaves it pending. Unsellable stock (quarantine store)
never counts; the same item on two lines is checked against the total; a manual line needs review.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import ItemStock
from apps.reservations import stock_check
from apps.reservations.models import Reservation, ReservationLine
from .factories import make_branch, make_customer, make_item, make_pharmacist, make_viewer


class _Base(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.para = make_item('باراسيتامول', 'IT001')
        self.vit = make_item('فيتامين سي', 'IT002')
        self.customer = make_customer()

    def _stock(self, item, qty, store='01'):
        ItemStock.objects.create(item=item, branch=self.branch, softech_store_code=store,
                                 quantity_on_hand=qty)

    def _res(self, item=None, qty=2, manual=''):
        return Reservation.objects.create(customer=self.customer, item=item, manual_item_name=manual,
                                          branch=self.branch, quantity_requested=qty,
                                          contact_phone='01012345678', contact_name='أحمد',
                                          status='pending')

    def _line(self, r, item=None, qty=1, manual=''):
        return ReservationLine.objects.create(reservation=r, item=item, manual_item_name=manual,
                                              quantity_requested=qty)


class CheckRuleTests(_Base):
    def test_mixed_availability_basket_is_partial(self):
        self._stock(self.para, 10)
        self._stock(self.vit, 1)
        r = self._res(self.para, qty=2)
        ln = self._line(r, self.vit, qty=3)
        res = stock_check.check(r)
        self.assertEqual(res['overall'], stock_check.PARTIAL)
        by_key = {x['key']: x for x in res['lines']}
        self.assertEqual(by_key['header']['status'], 'ok')
        self.assertEqual(by_key[f'line:{ln.pk}']['status'], 'short')
        self.assertEqual(by_key[f'line:{ln.pk}']['on_hand'], 1.0)

    def test_all_lines_covered(self):
        self._stock(self.para, 10)
        self._stock(self.vit, 5)
        r = self._res(self.para)
        self._line(r, self.vit, qty=5)
        self.assertEqual(stock_check.check(r)['overall'], stock_check.ALL_AVAILABLE)

    def test_none_available(self):
        r = self._res(self.para)
        self._line(r, self.vit)
        res = stock_check.check(r)
        self.assertEqual(res['overall'], stock_check.NONE_AVAILABLE)
        self.assertEqual({x['status'] for x in res['lines']}, {'out'})

    def test_quarantine_stock_does_not_count(self):
        self._stock(self.para, 50, store='102')
        self.assertEqual(stock_check.check(self._res(self.para))['lines'][0]['status'], 'out')

    def test_stock_summed_across_sellable_stores(self):
        self._stock(self.para, 1, store='01')
        self._stock(self.para, 1, store='02')
        self.assertEqual(stock_check.check(self._res(self.para, qty=2))['overall'], 'all')

    def test_same_item_on_two_lines_checked_against_total(self):
        self._stock(self.para, 3)
        r = self._res(self.para, qty=2)
        self._line(r, self.para, qty=2)
        res = stock_check.check(r)
        self.assertEqual(res['overall'], stock_check.PARTIAL)
        self.assertEqual({x['status'] for x in res['lines']}, {'short'})

    def test_manual_line_needs_review(self):
        self._stock(self.para, 10)
        r = self._res(self.para)
        self._line(r, manual='كريم مستورد')
        res = stock_check.check(r)
        self.assertEqual(res['overall'], stock_check.NEEDS_REVIEW)
        self.assertEqual(res['lines'][1]['status'], 'manual')
        self.assertIsNone(res['lines'][1]['on_hand'])

    def test_other_branch_stock_does_not_count(self):
        from .factories import make_branch2
        ItemStock.objects.create(item=self.para, branch=make_branch2(), softech_store_code='01',
                                 quantity_on_hand=50)
        self.assertEqual(stock_check.check(self._res(self.para))['overall'], 'none')


class PromotionTests(_Base):
    def _run(self):
        call_command('notify_stock_available', verbosity=0, stdout=StringIO())

    def test_partial_basket_stays_pending(self):
        self._stock(self.para, 10)
        r = self._res(self.para)
        self._line(r, self.vit, qty=1)                       # vitamin: no stock
        self._run()
        r.refresh_from_db()
        self.assertEqual(r.status, 'pending')

    def test_full_basket_is_promoted_with_line_detail(self):
        self._stock(self.para, 10)
        self._stock(self.vit, 4)
        r = self._res(self.para)
        self._line(r, self.vit, qty=2)
        self._run()
        r.refresh_from_db()
        self.assertEqual(r.status, 'available')
        log = r.status_logs.get(new_status='available')
        self.assertIn('فيتامين سي', log.note)
        self.assertTrue(r.activities.filter(activity_type='stock_checked',
                                            message__contains='لكل الأصناف').exists())

    def test_single_item_reservation_still_promoted(self):
        self._stock(self.para, 5)
        r = self._res(self.para, qty=2)
        self._run()
        r.refresh_from_db()
        self.assertEqual(r.status, 'available')

    def test_unsellable_stock_does_not_promote(self):
        self._stock(self.para, 50, store='103')
        r = self._res(self.para)
        self._run()
        r.refresh_from_db()
        self.assertEqual(r.status, 'pending')

    def test_manual_header_is_not_promoted_and_does_not_crash(self):
        r = self._res(None, manual='صنف يدوي')
        self._run()
        r.refresh_from_db()
        self.assertEqual(r.status, 'pending')

    def test_dry_run_changes_nothing(self):
        self._stock(self.para, 10)
        r = self._res(self.para)
        call_command('notify_stock_available', dry_run=True, stdout=StringIO())
        r.refresh_from_db()
        self.assertEqual(r.status, 'pending')


class DetailApiTests(_Base):
    def test_detail_returns_line_stock(self):
        self._stock(self.para, 10)
        r = self._res(self.para)
        ln = self._line(r, self.vit)
        _, _, client = make_pharmacist('ph_c33', branch=self.branch)
        resp = client.get(f'/api/reservations/{r.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        ls = resp.data['line_stock']
        self.assertEqual(ls['overall'], 'partial')
        self.assertEqual([x['key'] for x in ls['lines']], ['header', f'line:{ln.pk}'])

    def test_other_branch_viewer_cannot_read(self):
        from .factories import make_branch2
        r = self._res(self.para)
        _, _, client = make_viewer('vw_c33', branch=make_branch2())
        self.assertIn(client.get(f'/api/reservations/{r.pk}/').status_code, (403, 404))
