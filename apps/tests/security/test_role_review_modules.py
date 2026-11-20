"""Role review 2026-11-20 (task 1): ten new tool modules and their starting grants."""
import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from apps.users.management.commands.seed_permissions import (
    ALL_ACTIONS, ALL_MODULES, PERMISSIONS, ROLE_REVIEW_MODULES,
)
from apps.users.models import MODULE_CHOICES, RoleModuleAccess
from apps.users.roles import ROLE_KEYS as ROLES

NEW = ('forecast', 'recommendations', 'catalog_tools', 'stock', 'loyalty', 'dispatch',
       'rider', 'reconciliation', 'access_control', 'code_maps')
PARENTS = {'forecast': 'analytics', 'recommendations': 'analytics', 'catalog_tools': 'catalog',
           'stock': 'catalog', 'loyalty': 'customers', 'dispatch': 'delivery', 'rider': 'delivery',
           'reconciliation': 'finance', 'access_control': 'settings', 'code_maps': 'settings'}


class RoleReviewModulesTests(TestCase):
    def test_every_new_module_is_a_choice_and_in_the_seed(self):
        for m in NEW:
            self.assertIn(m, dict(MODULE_CHOICES))
            self.assertIn(m, ALL_MODULES)

    def test_starting_view_roles(self):   # spec table, verbatim
        expect = {'forecast': {'admin', 'purchasing', 'supervisor', 'quality_manager'},
                  'recommendations': {'admin', 'call_center', 'pharmacist', 'purchasing', 'supervisor', 'quality_manager'},
                  'catalog_tools': {'admin', 'purchasing', 'supervisor', 'call_center'},
                  'stock': {'admin', 'pharmacist', 'purchasing', 'quality_manager', 'supervisor', 'call_center', 'salesperson'},
                  'loyalty': {'admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor', 'quality_manager'},
                  'dispatch': {'admin', 'call_center', 'quality_manager', 'supervisor', 'pharmacist', 'salesperson'},
                  'rider': {'admin', 'delivery', 'supervisor', 'call_center'},
                  'reconciliation': {'admin', 'accountant', 'purchasing', 'quality_manager', 'supervisor'},
                  'access_control': {'admin'},
                  'code_maps': {'admin', 'purchasing', 'supervisor'}}
        for m, roles in expect.items():
            self.assertEqual({r for r in ROLES if 'view' in PERMISSIONS[r].get(m, set())}, roles, m)
            self.assertEqual(set(ROLE_REVIEW_MODULES[m][1]), roles, m)
            self.assertEqual(ROLE_REVIEW_MODULES[m][0], PARENTS[m])

    def test_other_actions_copy_the_parent_never_wider_than_view(self):
        for m, parent in PARENTS.items():
            for r in ROLES:
                acts = PERMISSIONS[r].get(m, set())
                if r == 'admin':
                    self.assertEqual(acts, set(ALL_ACTIONS))
                    continue
                if 'view' not in acts:
                    self.assertEqual(acts, set(), f'{r}/{m}')
                else:
                    self.assertTrue(acts - {'view'} <= PERMISSIONS[r].get(parent, set()), f'{r}/{m}')
                    self.assertEqual(acts, {'view'} | (PERMISSIONS[r].get(parent, set()) - {'view'}))

    def test_purchasing_has_no_settings(self):
        self.assertFalse(PERMISSIONS['purchasing'].get('settings'))

    def test_migration_inserts_rows_and_keeps_an_edit(self):
        mig = importlib.import_module('apps.users.migrations.0061_role_review_modules')
        RoleModuleAccess.objects.filter(module__in=NEW).delete()
        RoleModuleAccess.objects.get_or_create(role='purchasing', module='settings', action='view',
                                               defaults={'is_allowed': True})
        RoleModuleAccess.objects.filter(role='purchasing', module='settings', action='view').update(is_allowed=True)
        mig.forwards(django_apps, None)
        self.assertEqual(RoleModuleAccess.objects.filter(module__in=NEW).count(),
                         len(ROLES) * len(NEW) * len(ALL_ACTIONS))
        for m in NEW:
            for r in ROLES:
                for a in ALL_ACTIONS:
                    self.assertEqual(RoleModuleAccess.objects.get(role=r, module=m, action=a).is_allowed,
                                     a in PERMISSIONS[r].get(m, set()), (r, m, a))
        self.assertFalse(RoleModuleAccess.objects.filter(role='purchasing', module='settings', is_allowed=True).exists())
        # owner flips a row; a second run must keep it
        RoleModuleAccess.objects.filter(role='accountant', module='stock', action='view').update(is_allowed=True)
        RoleModuleAccess.objects.filter(role='admin', module='rider', action='view').update(is_allowed=False)
        mig.forwards(django_apps, None)
        self.assertTrue(RoleModuleAccess.objects.get(role='accountant', module='stock', action='view').is_allowed)
        self.assertFalse(RoleModuleAccess.objects.get(role='admin', module='rider', action='view').is_allowed)
        mig.backwards(django_apps, None)  # no-op
