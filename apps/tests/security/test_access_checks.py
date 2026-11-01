from django.test import SimpleTestCase, override_settings

from apps.access.checks import network_settings_check


def ids():
    return {m.id for m in network_settings_check(None)}


class NetworkSettingsCheckTests(SimpleTestCase):

    @override_settings(DEBUG=False, NETWORK_HEADER_TRUSTED=False)
    def test_warning_when_untrusted_outside_debug(self):
        self.assertIn('access.W001', ids())

    @override_settings(DEBUG=False, NETWORK_HEADER_TRUSTED=True)
    def test_no_warning_when_trusted(self):
        self.assertNotIn('access.W001', ids())

    @override_settings(DEBUG=True, NETWORK_HEADER_TRUSTED=False)
    def test_no_warning_in_debug(self):
        self.assertNotIn('access.W001', ids())

    @override_settings(NETWORK_UNTRUSTED_ZONE='intranet')
    def test_invalid_zone_is_error(self):
        self.assertIn('access.E001', ids())

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enfroce')
    def test_invalid_enforcement_is_error(self):
        self.assertIn('access.E002', ids())

    @override_settings(DEBUG=False, NETWORK_HEADER_TRUSTED=True, NETWORK_UNTRUSTED_ZONE='external',
                       NETWORK_POLICY_ENFORCEMENT='log')
    def test_valid_settings_clean(self):
        self.assertEqual(ids(), set())
