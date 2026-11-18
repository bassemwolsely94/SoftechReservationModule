from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.rpa.models import (
    BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob, SupplierPortal,
)


class PortalModelTests(TestCase):
    def _user(self):
        from django.contrib.auth import get_user_model
        from apps.users.models import StaffProfile
        u = get_user_model().objects.create_user(username='p2', password='x')
        return StaffProfile.objects.get_or_create(user=u)[0]

    def _job(self, staff):
        portal = SupplierPortal.objects.get(key='pharma_overseas')
        acct = PortalAccount.objects.create(portal=portal, label='a')
        bl = BuyList.objects.create(source_kind='upload', created_by=staff)
        return PortalJob.objects.create(portal=portal, account=acct, buylist=bl, created_by=staff)

    def test_portals_seeded_off(self):
        rows = SupplierPortal.objects.all()
        self.assertEqual(rows.count(), 2)
        for p in rows:
            self.assertFalse(p.enabled)
            self.assertFalse(p.live)
            self.assertEqual(p.basket_size, 10)

    def test_account_has_no_secret_field(self):
        for f in PortalAccount._meta.get_fields():
            for bad in ('pass', 'secret', 'token', 'cookie'):
                self.assertNotIn(bad, f.name)

    def test_portal_ref_unique_per_portal(self):
        job = self._job(self._user())
        PortalBasket.objects.create(job=job, seq=1, portal_key='pharma_overseas:2104322530')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PortalBasket.objects.create(job=job, seq=2, portal_key='pharma_overseas:2104322530')
        PortalBasket.objects.create(job=job, seq=3)
        PortalBasket.objects.create(job=job, seq=4)

    def test_source_line_in_one_open_buylist(self):
        from apps.catalog.models import Item
        staff = self._user()
        item = Item.objects.create(name='x', softech_id='T2X')
        b1 = BuyList.objects.create(source_kind='pivot', created_by=staff)
        b2 = BuyList.objects.create(source_kind='pivot', created_by=staff)
        kw = dict(item=item, needed_qty=1, remaining_qty=1, source_key='pivot:41:123456')
        BuyListLine.objects.create(buylist=b1, seq=1, **kw)
        with self.assertRaises(IntegrityError), transaction.atomic():
            BuyListLine.objects.create(buylist=b2, seq=1, **kw)
        BuyListLine.objects.filter(buylist=b1).update(open_guard=False)
        BuyListLine.objects.create(buylist=b2, seq=1, **kw)
