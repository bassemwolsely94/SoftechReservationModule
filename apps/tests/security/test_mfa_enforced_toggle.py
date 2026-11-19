"""
apps/tests/security/test_mfa_enforced_toggle.py — UAT finding B-01.

security.mfa_enforced must do what it says: "false" switches 2FA enforcement off. mfa_enforced()
used to test the bound method typed_value (always true), so any row at all turned enforcement on.
"""
from django.test import TestCase

from apps.config.models import SystemSetting
from apps.users.mfa import mfa_enforced

KEY = 'security.mfa_enforced'


def _set(value, value_type='boolean'):
    SystemSetting.objects.update_or_create(key=KEY, defaults={'value': value, 'value_type': value_type})


class MfaEnforcedToggleTests(TestCase):

    def test_no_row_is_off(self):
        SystemSetting.objects.filter(key=KEY).delete()
        self.assertFalse(mfa_enforced())

    def test_boolean_true_is_on(self):
        _set('true')
        self.assertTrue(mfa_enforced())

    def test_boolean_false_is_off(self):
        _set('false')
        self.assertFalse(mfa_enforced())

    def test_string_typed_rows_are_read_as_text(self):
        _set('false', 'string')
        self.assertFalse(mfa_enforced())
        _set('true', 'string')
        self.assertTrue(mfa_enforced())
