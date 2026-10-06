"""
apps/tests/test_catalog_tags.py

Curated merchandising tags + subcategory tree (Commerce-OS Phase 1). Write is
RBAC-gated (catalog/edit); read is open to staff.
"""
from django.test import TestCase

from apps.catalog.models import Category, Item, ItemTag
from .factories import make_item, make_user

BASE = '/api/items/'


class TagApiTests(TestCase):
    def setUp(self):
        _, _, self.admin = make_user('tag_admin', role='admin')
        _, _, self.viewer = make_user('tag_viewer', role='viewer')
        self.item = make_item(name='بانادول', softech_id='T1001')

    def test_viewer_cannot_create_tag(self):
        r = self.viewer.post(BASE + 'tags/', {'name': 'عرض'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_admin_creates_and_lists_tag(self):
        r = self.admin.post(BASE + 'tags/', {'name': 'Offer', 'name_ar': 'عرض', 'color': '#ea0000'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data['slug'])
        lst = self.admin.get(BASE + 'tags/')
        self.assertEqual(lst.status_code, 200)
        self.assertTrue(any(t['name'] == 'Offer' for t in lst.data))

    def test_duplicate_slug_rejected(self):
        self.admin.post(BASE + 'tags/', {'name': 'Seasonal', 'slug': 'seasonal'}, format='json')
        r = self.admin.post(BASE + 'tags/', {'name': 'Seasonal 2', 'slug': 'seasonal'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_assign_and_unassign_tag_to_item(self):
        tag = ItemTag.objects.create(slug='hot', name='Hot')
        r = self.admin.post(f'{BASE}{self.item.id}/tags/', {'tag_id': tag.id}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.item.tags.count(), 1)
        r2 = self.admin.delete(f'{BASE}{self.item.id}/tags/{tag.id}/')
        self.assertEqual(r2.status_code, 204)
        self.assertEqual(self.item.tags.count(), 0)

    def test_viewer_cannot_assign(self):
        tag = ItemTag.objects.create(slug='vip', name='VIP')
        r = self.viewer.post(f'{BASE}{self.item.id}/tags/', {'tag_id': tag.id}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_category_tree_nests_subcategories(self):
        root = Category.objects.create(softech_id='C1', name='Meds', name_ar='أدوية')
        Category.objects.create(softech_id='C2', name='Antibiotics', name_ar='مضادات', parent=root)
        r = self.admin.get(BASE + 'category-tree/')
        self.assertEqual(r.status_code, 200)
        node = next(n for n in r.data if n['softech_id'] == 'C1')
        self.assertEqual(len(node['children']), 1)
        self.assertEqual(node['children'][0]['softech_id'], 'C2')
