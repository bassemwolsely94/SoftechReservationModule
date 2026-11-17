"""Bundle item add (/api/items/bundles/<pk>/items/): an existing member is a 400, never a 500.

BundleItem is unique per (bundle, item) and the serializer has no validator for it, so the
view checks before saving (and catches a racing IntegrityError)."""
from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import BundleItem, ProductBundle
from .factories import make_item, make_user


class BundleItemAddTests(TestCase):
    def setUp(self):
        call_command('seed_permissions', verbosity=0)   # the real matrix (unseeded fails open)
        _, _, self.client_api = make_user('bundle_admin', role='admin')
        self.bundle = ProductBundle.objects.create(name='B')
        self.item = make_item(name='Mate', softech_id='BUN1')
        self.url = f'/api/items/bundles/{self.bundle.pk}/items/'

    def test_first_add_is_created(self):
        r = self.client_api.post(self.url, {'item': self.item.pk, 'quantity': 1}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['item'], self.item.pk)

    def test_second_add_of_the_same_item_is_400_and_one_row(self):
        self.client_api.post(self.url, {'item': self.item.pk, 'quantity': 1}, format='json')
        r = self.client_api.post(self.url, {'item': self.item.pk, 'quantity': 1}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['detail'], 'الصنف موجود بالفعل في الباقة')
        self.assertEqual(BundleItem.objects.filter(bundle=self.bundle, item=self.item).count(), 1)

    def test_read_only_role_cannot_add(self):
        _, _, viewer = make_user('bundle_cc', role='call_center')   # catalog: view only
        r = viewer.post(self.url, {'item': self.item.pk, 'quantity': 1}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(BundleItem.objects.filter(bundle=self.bundle).exists())
