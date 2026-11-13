"""
apps/tests/test_code_maps_item_types.py  (piece 4, Task 2)

The item-category registry (apps/config/item_types.py) over MedicineTypeMap:
lazy seed, unknown/blank codes, owner edits, and the sync hook for new codes.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from apps.config import item_types
from apps.config.models import MedicineTypeMap
from apps.notifications.models import Notification
from apps.users.models import StaffProfile


class ItemTypeRegistryTests(TestCase):
    def setUp(self):
        item_types.invalidate_cache()

    def tearDown(self):
        item_types.invalidate_cache()

    def test_seeded_meanings(self):
        item_types.ensure_defaults()
        self.assertEqual(item_types.medicine_codes(), ['10'])
        self.assertEqual(item_types.planning_excluded_codes(), ['60'])

    def test_empty_table_lazy_seeds(self):
        MedicineTypeMap.objects.all().delete()
        item_types.invalidate_cache()
        self.assertEqual(item_types.medicine_codes(), ['10'])
        self.assertEqual(item_types.planning_excluded_codes(), ['60'])
        self.assertEqual(MedicineTypeMap.objects.count(), 8)

    def test_existing_row_not_reseeded(self):
        MedicineTypeMap.objects.all().delete()
        MedicineTypeMap.objects.create(code='10', group='medicine', is_medicine=True)
        item_types.invalidate_cache()
        self.assertEqual(item_types.medicine_codes(), ['10'])
        self.assertEqual(MedicineTypeMap.objects.count(), 1)

    def test_unknown_code(self):
        item_types.ensure_defaults()
        self.assertEqual(item_types.label('85'), 'غير مصنف (85)')
        self.assertNotIn('85', item_types.medicine_codes())
        self.assertEqual(item_types.label(''), '')
        self.assertEqual(item_types.label(None), '')

    def test_owner_flag_edit_visible(self):
        item_types.ensure_defaults()
        self.assertEqual(item_types.planning_excluded_codes(), ['60'])
        row = MedicineTypeMap.objects.get(code='70')
        row.excluded_from_planning = True
        row.save()
        self.assertEqual(item_types.planning_excluded_codes(), ['60', '70'])

    def test_all_types_listed(self):
        self.assertEqual(len(item_types.all_types()), 8)

    def test_sync_new_code_notifies_once(self):
        admin = User.objects.create(username='itemtype_admin')
        sp = StaffProfile.objects.create(user=admin, role='admin')
        item_types.ensure_defaults()
        self.assertEqual(item_types.sync_item_types({'85': ('X', 'س')}), ['85'])
        self.assertEqual(item_types.sync_item_types({'85': ('X', 'س')}), [])
        row = MedicineTypeMap.objects.get(code='85')
        self.assertEqual((row.group, row.label, row.is_medicine, row.excluded_from_planning),
                         ('unclassified', 'س', False, False))
        self.assertEqual(Notification.objects.filter(recipient=sp).count(), 1)

    def test_sync_notification_dedup_after_row_deleted(self):
        admin = User.objects.create(username='itemtype_admin2')
        sp = StaffProfile.objects.create(user=admin, role='admin')
        item_types.ensure_defaults()
        self.assertEqual(item_types.sync_item_types({'85': ('X', '')}), ['85'])
        MedicineTypeMap.objects.filter(code='85').delete()
        self.assertEqual(item_types.sync_item_types({'85': ('X', '')}), ['85'])
        self.assertEqual(Notification.objects.filter(recipient=sp).count(), 1)

    def test_sync_refreshes_label_and_keeps_owner_flags(self):
        item_types.ensure_defaults()
        item_types.sync_item_types({'10': ('Medicine', 'دواء جديد')})
        row = MedicineTypeMap.objects.get(code='10')
        self.assertEqual(row.label, 'دواء جديد')
        self.assertTrue(row.is_medicine)
        self.assertEqual(item_types.label('10'), 'دواء جديد')

    def test_sync_never_raises(self):
        self.assertEqual(item_types.sync_item_types(None), [])


class MedicineTypeMapSeedMigrationTests(TestCase):
    """The data seed of migration 0004 (called directly with the real models)."""

    def setUp(self):
        item_types.invalidate_cache()
        MedicineTypeMap.objects.all().delete()

    def tearDown(self):
        item_types.invalidate_cache()

    def _seed(self):
        import importlib
        from django.apps import apps
        mod = importlib.import_module('apps.config.migrations.0004_medicinetypemap')
        mod.seed_item_types(apps, None)
        return set(MedicineTypeMap.objects.filter(excluded_from_planning=True)
                   .values_list('code', flat=True))

    def test_seed_honours_old_excluded_setting(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='analytics_excluded_medicine_types',
                                               defaults={'value': '60,70'})
        self.assertEqual(self._seed(), {'60', '70'})

    def test_seed_without_setting_excludes_only_gifts(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.filter(key='analytics_excluded_medicine_types').delete()
        self.assertEqual(self._seed(), {'60'})
