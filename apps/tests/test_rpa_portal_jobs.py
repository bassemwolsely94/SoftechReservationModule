from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.branches.models import Branch
from apps.catalog.models import Item, ItemSupplierLink
from apps.config.models import SystemSetting
from apps.invoices.models import VendorProfile
from apps.procurement.models import PurchaseLine
from apps.rpa.models import (BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob,
                             SupplierPortal)
from apps.rpa.portal import buylist as bl
from apps.rpa.portal import jobs
from apps.users.models import RoleModuleAccess
from .factories import make_user

PATCH = 'apps.supply.execution.preview_order'


def _preview(exceed=(), price=10):
    def fn(lines, **kw):
        rows = [{'item_id': ln['item_id'], 'qty': ln['qty'], 'exceeds_need': ln['item_id'] in exceed,
                 'line_value': price * ln['qty']} for ln in lines]
        return {'lines': rows, 'estimated_value': sum(r['line_value'] for r in rows)}
    return fn


def _grant(role, action):
    RoleModuleAccess.objects.update_or_create(role=role, module='rpa', action=action,
                                              defaults={'is_allowed': True})


class JobTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _grant('purchasing', 'create')
        _grant('accountant', 'create')
        _grant('accountant', 'approve')
        _, cls.buyer, _ = make_user('pj_buyer', role='purchasing')
        _, cls.boss, _ = make_user('pj_boss', role='accountant')
        cls.hq = Branch.objects.create(softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        cls.portal, _ = SupplierPortal.objects.get_or_create(   # seeded by migration 0002
            key='pharma_overseas', defaults={'supplier_code': '565'})
        cls.account = PortalAccount.objects.create(portal=cls.portal, label='main',
                                                  identity_text='HQ 565')
        cls.vendor = VendorProfile.objects.create(name='PO', softech_personcode='565')
        cls.items = [Item.objects.create(softech_id=f'PJ{n}', name=f'item {n}', is_active=True,
                            pack_price=Decimal('10'))
                     for n in range(25)]

    def _list(self, n=3, others=0):
        b = BuyList.objects.create(source_kind='upload', created_by=self.buyer)
        for i in range(n + others):
            BuyListLine.objects.create(
                buylist=b, seq=i + 1, item=self.items[i], needed_qty=2, remaining_qty=2,
                chosen_supplier='565' if i < n else '30', source_key=f'pj:{b.pk}:{i}')
        return b

    def _job(self, **kw):
        return jobs.create_job(self._list(**kw), portal=self.portal, account=self.account,
                               staff=self.buyer)

    def test_job_takes_only_this_portals_lines(self):
        job = self._job(n=3, others=2)
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(job, staff=self.buyer)
        self.assertEqual(sum(b.lines.count() for b in job.baskets.all()), 3)
        with self.assertRaises(jobs.JobError):
            jobs.create_job(self._list(n=0, others=2), portal=self.portal, account=self.account,
                            staff=self.buyer)

    def test_over_need_without_reason_blocks(self):
        job = self._job(n=2)
        first = job.buylist.lines.first()
        with mock.patch(PATCH, _preview(exceed={first.item_id})):
            with self.assertRaises(jobs.JobError) as cm:
                jobs.approve_job(job, staff=self.buyer)
            self.assertIn(first.item.name, str(cm.exception))
            jobs.approve_job(job, staff=self.buyer, reasons={first.pk: 'special offer'})
        first.refresh_from_db()
        self.assertEqual(first.reason, 'special offer')

    def test_self_approval_allowed_below_threshold(self):
        SystemSetting.objects.create(key='portal_four_eyes_above', label='x', value='1000',
                                     value_type='decimal')
        job = self._job(n=2)
        with mock.patch(PATCH, _preview(price=10)):
            jobs.approve_job(job, staff=self.buyer)
        job.refresh_from_db()
        self.assertEqual(job.status, 'approved')
        self.assertEqual(job.estimated_value, Decimal('40'))

    def test_four_eyes_above_threshold(self):
        SystemSetting.objects.create(key='portal_four_eyes_above', label='x', value='10',
                                     value_type='decimal')
        job = self._job(n=2)
        with mock.patch(PATCH, _preview(price=10)):
            with self.assertRaises(PermissionDenied):
                jobs.approve_job(job, staff=self.buyer)
            jobs.approve_job(job, staff=self.boss)
        job.refresh_from_db()
        self.assertEqual(job.approved_by_id, self.boss.pk)

    def test_four_eyes_creator_holding_approve_still_denied(self):
        SystemSetting.objects.create(key='portal_four_eyes_above', label='x', value='10',
                                     value_type='decimal')
        job = jobs.create_job(self._list(n=2), portal=self.portal, account=self.account, staff=self.boss)
        with mock.patch(PATCH, _preview(price=10)):
            with self.assertRaises(PermissionDenied):
                jobs.approve_job(job, staff=self.boss)

    def test_no_create_permission_cannot_approve(self):
        _, nobody, _ = make_user('pj_nobody', role='pharmacist')
        job = self._job(n=1)
        with mock.patch(PATCH, _preview()):
            with self.assertRaises(PermissionDenied):
                jobs.approve_job(job, staff=nobody)

    def test_baskets_of_ten_in_order(self):
        job = self._job(n=23)
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(job, staff=self.buyer)
        baskets = list(job.baskets.order_by('seq'))
        self.assertEqual([b.seq for b in baskets], [1, 2, 3])
        self.assertEqual([b.lines.count() for b in baskets], [10, 10, 3])
        self.assertEqual(baskets[0].lines.order_by('id').first().buyline.seq, 1)

    def test_basket_ready_only_when_all_keys_known(self):
        job = self._job(n=12)
        for it in self.items[:10]:   # basket 1 fully known, basket 2 has none
            ItemSupplierLink.objects.create(item_code=it.softech_id, item=it, supp_code='565',
                                            supp_item_code='000000000000052872')
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(job, staff=self.buyer)
        b1, b2 = job.baskets.order_by('seq')
        self.assertEqual((b1.status, b2.status), ('ready', 'pending'))
        self.assertEqual(b1.lines.first().supplier_key, '52872')
        self.assertEqual(b1.lines.first().supplier_key_padded, '000000000000052872')

    def test_one_keyless_line_keeps_basket_pending(self):
        job = self._job(n=3)
        for it in self.items[:2]:
            ItemSupplierLink.objects.create(item_code=it.softech_id, item=it, supp_code='565',
                                            supp_item_code='77')
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(job, staff=self.buyer)
        self.assertEqual(job.baskets.get().status, 'pending')

    def test_cancel_refused_after_claim(self):
        job = self._job(n=2)
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(job, staff=self.buyer)
        b = job.baskets.get()
        PortalBasket.objects.filter(pk=b.pk).update(status='in_progress')
        with self.assertRaises(jobs.JobError):
            jobs.cancel_job(job, staff=self.buyer, reason='x')
        PortalBasket.objects.filter(pk=b.pk).update(status='ready')
        jobs.cancel_job(job, staff=self.buyer, reason='x')
        job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
        self.assertEqual(job.baskets.get().status, 'cancelled')

    def test_pick_refused_after_approval(self):
        job = self._job(n=2)
        line = job.buylist.lines.first()
        bl.pick(line, '30', staff=self.buyer)      # draft: fine
        bl.pick(line, '565', staff=self.buyer)
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(job, staff=self.buyer)
        with self.assertRaises(bl.BuyListError):
            bl.pick(line, '30', staff=self.buyer)
        # robot results still come back
        bl.apply_result(line, supplier_code='565', accepted=1, basket_id=1)
        line.refresh_from_db()
        self.assertEqual(line.remaining_qty, 1)

    def test_audit_actions(self):
        from apps.audit.models import AuditLog
        job = self._job(n=1)
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(job, staff=self.buyer)
        jobs.cancel_job(job, staff=self.buyer, reason='x')
        for a in ('created', 'approved', 'cancelled'):
            self.assertTrue(AuditLog.objects.filter(action=f'rpa_portal_job_{a}').exists(), a)

    def _buy(self, item, cost_total=500, qty=10, day=None):
        from django.utils import timezone
        return PurchaseLine.objects.create(
            branch_code='100', supplier_code='565', doc_number=f'D{item.pk}{cost_total}',
            doc_date=day or timezone.localdate(), item_code=item.softech_id, doccode='10',
            net_qty=qty, net_value=cost_total, public_price=100)

    def test_four_eyes_uses_purchase_cost(self):
        # unit cost 50 (500/10); 2 lines x qty 2 = 200. pack_price alone would give 40.
        SystemSetting.objects.create(key='portal_four_eyes_above', label='x', value='100',
                                     value_type='decimal')
        for it in self.items[:2]:
            self._buy(it)
        job = self._job(n=2)
        with mock.patch(PATCH, _preview(price=0)):   # preview line values are not used
            with self.assertRaises(PermissionDenied):
                jobs.approve_job(job, staff=self.buyer)
            jobs.approve_job(job, staff=self.boss)
        job.refresh_from_db()
        self.assertEqual(job.estimated_value, Decimal('200'))

    def test_four_eyes_required_when_unpriced(self):
        SystemSetting.objects.create(key='portal_four_eyes_above', label='x', value='1000000',
                                     value_type='decimal')
        Item.objects.filter(pk=self.items[0].pk).update(pack_price=0)
        job = self._job(n=2)
        with mock.patch(PATCH, _preview()):
            with self.assertRaises(PermissionDenied):
                jobs.approve_job(job, staff=self.buyer)
            jobs.approve_job(job, staff=self.boss)

    def test_second_job_for_same_lines_refused(self):
        b = self._list(n=2)
        jobs.create_job(b, portal=self.portal, account=self.account, staff=self.buyer)
        with self.assertRaises(jobs.JobError):
            jobs.create_job(b, portal=self.portal, account=self.account, staff=self.buyer)

    def test_approve_refused_when_lines_in_other_approved_job(self):
        b = self._list(n=2)
        first = jobs.create_job(b, portal=self.portal, account=self.account, staff=self.buyer)
        second = PortalJob.objects.create(portal=self.portal, account=self.account, buylist=b,
                                          created_by=self.buyer)   # bypasses create_job
        with mock.patch(PATCH, _preview()):
            jobs.approve_job(first, staff=self.buyer)
            with self.assertRaises(jobs.JobError):
                jobs.approve_job(second, staff=self.buyer)
        second.refresh_from_db()
        self.assertEqual(second.status, 'draft')
        self.assertEqual(second.baskets.count(), 0)
