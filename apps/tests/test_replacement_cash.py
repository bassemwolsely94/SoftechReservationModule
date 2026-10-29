"""
Doc 25 §23 — B3: cash handed to the patient. The cashier makes the سداد voucher natively (owner Q2); the
module records the instruction (reserving the amount), links the voucher in the daily check and verifies
it (amount, maker-checker, timeliness), and takes the handing employee's confirmation.
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from apps.finance.recon_models import Allocation, APInvoice, Payment, ReconParty
from apps.replacement import cash as CASH
from apps.replacement import legs as LG
from apps.replacement import reconstruct as R
from apps.replacement.models import CaseException as X, CashPayout as P, ReplacementCase as RC

from . import test_replacement_workflow as TW

D = Decimal
TODAY = timezone.localdate()


class CashPayoutTests(TW._Base):
    approved = TW.LegTests.approved

    def setUp(self):
        super().setUp()
        self.p4470 = ReconParty.objects.create(party_type='supplier', softech_personcode='4470', name='مورد شركات 40%')
        self.p4471 = ReconParty.objects.create(party_type='supplier', softech_personcode='4471', name='مورد شركات 30%')
        self._n = 14000

    def live_case(self, mode='cash'):
        c = self.approved(item=self.small, mode=mode)                     # cash 600 / products 700
        self._n += 1
        inv = APInvoice.objects.create(party=self.p4470 if mode == 'cash' else self.p4471, party_type='supplier',
                                       branchcode='130', doccode='10', docnumber=str(self._n), docdate=TODAY,
                                       doc_value=c.entitlement)
        LG.link_native_purchase(c.pk, user=self.sup, version=self.v(c), branchcode='130',
                                docnumber=str(self._n), docdate=TODAY)
        return RC.objects.get(pk=c.pk), inv

    def v(self, c):
        return RC.objects.get(pk=c.pk).version

    def pay(self, c, amount):
        return CASH.request_payout(c.pk, user=self.sup, version=self.v(c), amount=amount)

    def voucher(self, inv, amount, *, usercode='1309', sno='980'):
        p = Payment.objects.create(party=inv.party, party_type='supplier', branchcode='130', cheqsno=sno, cheqtype='20',
                                   direction='out', voucher_date=TODAY, amount=D(amount), usercode=usercode, bankcode='01',
                                   trans_time=datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, tzinfo=dt_tz.utc))
        Allocation.objects.create(payment=p, invoice=inv, amount=D(amount), origin='softech')
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())

    def exc(self, c, t):
        return X.objects.filter(case=c, exception_type=t, status__in=['open', 'acknowledged'])

    # ── instruction ───────────────────────────────────────────────────────────
    def test_instruction_reserves_and_respects_limits(self):
        c, _ = self.live_case()
        self.assertEqual(LG.available(c)['available'], D('600.00'))
        with self.assertRaises(ValidationError):
            self.pay(c, '700')                                             # > available
        self.pay(c, '250')
        self.assertEqual(LG.available(RC.objects.get(pk=c.pk))['available'], D('350.00'))
        p = c.payouts.get()
        self.assertEqual(CASH.instruction(c, p)['note'], f'صرف نقدي من فاتورة رقم {c.purchase_ref.docnumber}')
        with self.assertRaises(ValidationError):                           # reason required
            CASH.cancel_payout(c.pk, p.pk, user=self.sup, version=self.v(c), reason='')
        CASH.cancel_payout(c.pk, p.pk, user=self.sup, version=self.v(c), reason='غيّر رأيه')
        self.assertEqual(LG.available(RC.objects.get(pk=c.pk))['available'], D('600.00'))

    def test_products_case_never_pays_cash(self):
        c, _ = self.live_case(mode='products')
        with self.assertRaises(ValidationError):
            self.pay(c, '100')

    # ── daily check ───────────────────────────────────────────────────────────
    def test_voucher_is_linked_to_its_instruction_then_confirmed(self):
        c, inv = self.live_case()
        self.pay(c, '250')
        p = c.payouts.get()
        with self.assertRaises(ValidationError):                           # nothing to confirm yet
            CASH.confirm_payout(c.pk, p.pk, user=self.maker, version=self.v(c))
        self.voucher(inv, '250')
        p.refresh_from_db()
        c.refresh_from_db()
        self.assertEqual((p.status, p.voucher_usercode, p.voucher_box), (P.ST_PAID, '1309', '01'))
        self.assertEqual((c.redeemed_cash, c.outstanding), (D('250.00'), D('350.00')))
        self.assertEqual(LG.available(c)['available'], D('350.00'))       # no double reservation
        self.assertFalse(self.exc(c, 'cash_without_instruction').exists())
        CASH.confirm_payout(c.pk, p.pk, user=self.maker, version=self.v(c), reference='إيصال 77')
        p.refresh_from_db()
        self.assertEqual((p.status, p.confirmed_by, p.reference), (P.ST_CONFIRMED, self.maker, 'إيصال 77'))
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())              # re-run never re-decides
        p.refresh_from_db()
        self.assertEqual(p.status, P.ST_CONFIRMED)

    def test_cash_without_instruction_is_high(self):
        c, inv = self.live_case()
        self.voucher(inv, '200')
        self.assertEqual(self.exc(c, 'cash_without_instruction').get().severity, X.SEV_HIGH)

    def test_amount_differing_from_the_instruction_is_high(self):
        c, inv = self.live_case()
        self.pay(c, '250')
        self.voucher(inv, '300')
        self.assertEqual(self.exc(c, 'payout_amount_mismatch').get().severity, X.SEV_HIGH)
        self.assertEqual(c.payouts.get().status, P.ST_INSTRUCTED)          # not linked

    @override_settings(REPLACEMENT_APPROVAL_CASH_MANAGER_ABOVE=D('100'))
    def test_voucher_by_the_case_creator_above_threshold(self):
        self.maker.softech_user_id = '1777'
        self.maker.save(update_fields=['softech_user_id'])
        with override_settings(REPLACEMENT_APPROVAL_CASH_MANAGER_ABOVE=D('1500')):
            c, inv = self.live_case()                                      # approved by the supervisor as usual
        self.pay(c, '250')
        self.voucher(inv, '250', usercode='1777')
        self.assertTrue(self.exc(c, 'voucher_by_creator').exists())

    def test_ageing(self):
        c, inv = self.live_case()
        self.pay(c, '100')
        P.objects.filter(case=c).update(created_at=timezone.now() - timedelta(days=5))
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        self.assertTrue(self.exc(c, 'payout_not_executed').exists())
        P.objects.filter(case=c).update(created_at=timezone.now())
        self.voucher(inv, '100')
        P.objects.filter(case=c).update(paid_at=timezone.now() - timedelta(days=3))
        R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
        self.assertTrue(self.exc(c, 'payout_not_confirmed').exists())
        self.assertFalse(self.exc(c, 'payout_not_executed').exists())     # auto-cleared once paid

    # ── API ───────────────────────────────────────────────────────────────────
    def test_api(self):
        c, inv = self.live_case()
        r = self.sup_api.post(f'/api/replacement/cases/{c.pk}/payouts/', {'version': self.v(c), 'amount': '150'},
                              format='json')
        self.assertEqual(r.status_code, 200, r.data)
        po = r.data['workflow']['payouts'][0]
        self.assertEqual((po['amount'], po['status'], po['instruction']['amount']), ('150.00', 'instructed', '150.00'))
        self.voucher(inv, '150')
        r = self.maker_api.post(f'/api/replacement/cases/{c.pk}/payouts/{po["id"]}/confirm/',
                                {'version': self.v(c), 'reference': 'ok'}, format='json')
        self.assertEqual((r.status_code, r.data['workflow']['payouts'][0]['status']), (200, 'confirmed'))
