"""
Staff searches find accounts whose name lives only in StaffProfile.softech_username
(first/last name empty, username = a numeric code) — 2026-11-04. Synthetic data.
"""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase

from apps.pbx.management.commands.assign_pbx_extensions import _get_staff
from apps.pbx.models import AgentExtension
from apps.users.models import StaffProfile
from .factories import make_branch


def _staff(code, softech_name, hr_code=''):
    user = get_user_model().objects.create(username=code, first_name='', last_name='')
    sp, _ = StaffProfile.objects.get_or_create(user=user, defaults={'branch': make_branch()})
    sp.softech_username = softech_name
    sp.hr_code = hr_code
    sp.save()
    return sp


class AssignExtensionStaffLookupTests(TestCase):

    def setUp(self):
        self.mona = _staff('90001', 'منى سمير', hr_code='HR-7')
        self.mohamed = _staff('90002', 'محمد سمير')

    def test_softech_name_fragment_finds_the_one_staff(self):
        self.assertEqual(_get_staff('منى'), self.mona)

    def test_exact_softech_name_and_hr_code(self):
        self.assertEqual(_get_staff('محمد سمير'), self.mohamed)
        self.assertEqual(_get_staff('hr-7'), self.mona)

    def test_username_code_still_works(self):
        self.assertEqual(_get_staff('90002'), self.mohamed)

    def test_ambiguous_fragment_is_refused(self):
        with self.assertRaises(CommandError):
            _get_staff('سمير')

    def test_blank_is_refused(self):
        with self.assertRaises(CommandError):
            _get_staff('   ')


class AdminSearchTests(TestCase):

    def test_extension_admin_finds_staff_by_softech_name(self):
        sp = _staff('90003', 'هالة فؤاد')
        ext = AgentExtension.objects.create(extension='4711', staff=sp)
        model_admin = admin.site._registry[AgentExtension]
        qs, _ = model_admin.get_search_results(RequestFactory().get('/'),
                                               AgentExtension.objects.all(), 'هالة')
        self.assertEqual(list(qs), [ext])
