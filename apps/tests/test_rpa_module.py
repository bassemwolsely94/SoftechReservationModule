import importlib

from django.conf import settings
from django.test import TestCase

from apps.users.models import RoleModuleAccess


class RpaModuleWiringTests(TestCase):
    def test_flag_defaults_off_and_is_a_writer_flag(self):
        from config.writers import WRITER_FLAGS, writer_allowed
        self.assertIn('RPA_SOFTECH_ENTRY_ENABLED', WRITER_FLAGS)
        self.assertFalse(settings.RPA_SOFTECH_ENTRY_ENABLED)
        self.assertFalse(writer_allowed('RPA_SOFTECH_ENTRY_ENABLED'))

    def test_prefix_maps_to_module(self):
        from core.middleware.module_access import MODULE_BY_PREFIX
        self.assertEqual(MODULE_BY_PREFIX['rpa'], 'rpa')

    def test_seed_grants(self):
        mig = importlib.import_module('apps.users.migrations.0058_rpa_module')
        from django.apps import apps as real_apps
        mig.forwards(real_apps, None)
        get = lambda role, action: RoleModuleAccess.objects.get(
            role=role, module='rpa', action=action).is_allowed
        self.assertTrue(get('supervisor', 'approve'))
        self.assertTrue(get('supervisor', 'edit'))
        self.assertFalse(get('purchasing', 'approve'))
        self.assertTrue(get('quality_manager', 'approve'))
        self.assertFalse(get('quality_manager', 'edit'))
        self.assertTrue(get('admin', 'finalize'))
        self.assertFalse(RoleModuleAccess.objects.filter(
            role='call_center', module='rpa', is_allowed=True).exists())

    def test_seed_command_table_agrees_with_migration(self):
        from apps.users.management.commands.seed_permissions import PERMISSIONS
        mig = importlib.import_module('apps.users.migrations.0058_rpa_module')
        for role, actions in mig.GRANTS.items():
            if role != 'admin':
                self.assertEqual(PERMISSIONS[role]['rpa'], actions)
        self.assertEqual({r for r, m in PERMISSIONS.items() if r != 'admin' and m.get('rpa')},
                         {r for r in mig.GRANTS if r != 'admin'})
