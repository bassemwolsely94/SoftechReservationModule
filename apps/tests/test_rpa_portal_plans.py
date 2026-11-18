import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Item
from apps.rpa.models import (BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob,
                             PortalLine, SupplierPortal)
from apps.rpa.portal import plans
from .factories import make_user


class PlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _, cls.buyer, _ = make_user('plan_buyer', role='purchasing')
        cls.portal, _ = SupplierPortal.objects.get_or_create(
            key='pharma_overseas', defaults={'supplier_code': '565'})
        cls.account = PortalAccount.objects.create(portal=cls.portal, label='main',
                                                   identity_text='Branch 5 Cairo')
        cls.items = [Item.objects.create(softech_id=f'PL{n}', name=nm, is_active=True)
                     for n, nm in enumerate(['PANADOL EXTRA 24 TAB', 'AUGMENTIN 1GM 14 TABS',
                                             'VOLTAREN 75MG', 'CATAFLAM 50 MG 20 STRIP'])]
        cls.buylist = BuyList.objects.create(source_kind='upload', created_by=cls.buyer)

    def _job(self, dry_run=True, live=False):
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=live)
        self.portal.refresh_from_db()
        job = PortalJob.objects.create(portal=self.portal, account=self.account, buylist=self.buylist,
                                       dry_run=dry_run, created_by=self.buyer)
        basket = PortalBasket.objects.create(job=job, seq=1, status='ready')
        return job, basket

    def _line(self, job, basket, i, key='', status='pending', qty=3):
        bl = BuyListLine.objects.create(buylist=self.buylist, seq=i + 1, item=self.items[i],
                                        needed_qty=qty, remaining_qty=qty, chosen_supplier='565',
                                        source_key=f'pl:{job.pk}:{i}')
        return PortalLine.objects.create(
            basket=basket, buyline=bl, item=self.items[i], wanted_qty=qty, status=status,
            supplier_key=key, supplier_key_padded=str(key).zfill(18) if key else '')

    def test_fill_plan_dry_run_unless_portal_live_and_job_live(self):
        for live, dry, mode in [(False, True, 'dry_run'), (False, False, 'dry_run'),
                                (True, True, 'dry_run'), (True, False, 'live')]:
            job, basket = self._job(dry_run=dry, live=live)
            self._line(job, basket, 0, key='52872')
            self.assertEqual(plans.fill_plan(basket)['mode'], mode, (live, dry))

    def test_fill_plan_lines_in_seq_with_padded_sku(self):
        job, basket = self._job()
        a = self._line(job, basket, 0, key='52872', qty=10)
        self._line(job, basket, 1, key='', status='not_found')
        b = self._line(job, basket, 2, key='7')
        plan = plans.fill_plan(basket)
        self.assertEqual(plan['kind'], 'fill')
        self.assertEqual(plan['basket_id'], basket.pk)
        self.assertEqual(plan['portal'], 'pharma_overseas')
        self.assertEqual(plan['account'], {'identity_text': 'Branch 5 Cairo'})
        self.assertEqual(plan['lines'][0], {'line_id': a.pk, 'sku_padded': '000000000000052872',
                                            'sku': '52872', 'qty': 10})
        self.assertEqual([x['line_id'] for x in plan['lines']], [a.pk, b.pk])
        self.assertEqual(plan['expect_lines'], 2)
        self.assertEqual(plan['max_stepdown_tries'], 6)

    def test_fill_plan_refuses_non_ready_basket(self):
        job, basket = self._job()
        self._line(job, basket, 0, key='1')
        PortalBasket.objects.filter(pk=basket.pk).update(status='pending')
        basket.refresh_from_db()
        with self.assertRaises(plans.PlanError):
            plans.fill_plan(basket)

    def test_discovery_plan_only_keyless_pending_one_per_buyline(self):
        job, basket = self._job()
        keyless = self._line(job, basket, 0)
        self._line(job, basket, 1, key='55')
        self._line(job, basket, 2, status='not_found')
        plan = plans.discovery_plan(job)
        self.assertEqual(plan['kind'], 'discovery')
        self.assertEqual(plan['portal'], 'pharma_overseas')
        self.assertEqual(plan['account'], {'identity_text': 'Branch 5 Cairo'})
        self.assertEqual(plan['searches'], [{'buyline_id': keyless.buyline_id, 'term': 'PANADOL EXTRA'}])

    def test_discovery_term_trims_pack_words(self):
        t = plans.discovery_term
        self.assertEqual(t('PANADOL EXTRA 24 TAB'), 'PANADOL EXTRA')
        self.assertEqual(t('AUGMENTIN 1GM 14 TABS'), 'AUGMENTIN 1GM')
        self.assertEqual(t('CATAFLAM 50 MG 20 STRIP'), 'CATAFLAM 50 MG')
        self.assertEqual(t('VOLTAREN 75MG'), 'VOLTAREN 75MG')
        self.assertEqual(t('  '), '')

    def test_history_plan(self):
        job, basket = self._job()
        with self.assertRaises(plans.PlanError):          # no window, no read
            plans.history_plan(basket)
        start = timezone.now() - timedelta(hours=2)
        self.assertEqual(plans.history_plan(basket, since=start)['since'], start.isoformat())
        at = timezone.now() - timedelta(days=1)
        PortalBasket.objects.filter(pk=basket.pk).update(filled_at=at, portal_ref='R-9')
        basket.refresh_from_db()
        p = plans.history_plan(basket)
        self.assertEqual(p, {'kind': 'history', 'basket_id': basket.pk, 'since': at.isoformat(),
                             'order_ref': 'R-9'})

    def test_plan_has_no_submit_or_secret(self):
        job, basket = self._job(dry_run=False, live=True)
        self._line(job, basket, 0)
        self._line(job, basket, 1, key='52872')
        PortalBasket.objects.filter(pk=basket.pk).update(filled_at=timezone.now(), portal_ref='R-1')
        basket.refresh_from_db()
        for plan in (plans.discovery_plan(job), plans.fill_plan(basket), plans.history_plan(basket)):
            text = json.dumps(plan).lower()
            for word in ('submit', 'password', 'cookie', 'http'):
                self.assertNotIn(word, text)
