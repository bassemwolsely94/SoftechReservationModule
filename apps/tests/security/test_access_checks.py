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

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce', NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='')
    def test_check_e003_enforce_without_key(self):
        self.assertIn('access.E003', ids())

    @override_settings(NETWORK_POLICY_ENFORCEMENT='enforce', NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='k')
    def test_no_e003_with_key(self):
        self.assertNotIn('access.E003', ids())

    @override_settings(DEBUG=False, NETWORK_POLICY_ENFORCEMENT='log', NETWORK_HEADER_TRUSTED=True,
                       NETWORK_PROXY_KEY='')
    def test_w002_trusted_without_key_outside_debug(self):
        self.assertIn('access.W002', ids())
        self.assertNotIn('access.E003', ids())

    @override_settings(DEBUG=True, NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='')
    def test_no_w002_in_debug(self):
        self.assertNotIn('access.W002', ids())

    @override_settings(DEBUG=False, NETWORK_HEADER_TRUSTED=True, NETWORK_UNTRUSTED_ZONE='external',
                       NETWORK_POLICY_ENFORCEMENT='log', NETWORK_PROXY_KEY='k')
    def test_valid_settings_clean(self):
        self.assertEqual(ids(), set())
