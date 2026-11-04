"""N3 "before enforce" items.

  1. The help-centre «هل أفاد هذا الشرح؟» answer (POST /api/help/feedback/) was refused in the
     read-only zones; its list and resolve stay trainers' writes under the zone policy.
  2. /rider/security had no RequireRole on the frontend route.
  3. access_preflight lists accounts without a staff profile and service accounts for review.
"""
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.access import preflight
from apps.access.policy import decide
from apps.tests.factories import make_user


@override_settings(ACCESS_POLICY_TTL=0)
class HelpFeedbackOpenTests(TestCase):

    def test_feedback_answer_is_open_in_read_only_zones(self):
        _, ph, _ = make_user('n3fb_ph', role='pharmacist')
        self.assertTrue(decide(ph, 'Z2', '/api/help/feedback/', 'POST').allowed)
        _, rider, _ = make_user('n3fb_rider', role='delivery')
        self.assertTrue(decide(rider, 'Z4', '/api/help/feedback/', 'POST').allowed)

    def test_resolve_and_other_help_writes_still_follow_the_policy(self):
        _, ph, _ = make_user('n3fb_ph2', role='pharmacist')
        for path in ('/api/help/feedback/3/resolve/', '/api/help/feedback/x/',
                     '/api/help/feedbackx/'):
            r = decide(ph, 'Z2', path, 'POST')
            self.assertEqual((r.allowed, r.reason), (False, 'read_only'), path)


class RiderSecurityRouteTests(SimpleTestCase):

    def test_rider_security_route_has_require_role(self):
        src = (Path(settings.BASE_DIR) / 'frontend' / 'src' / 'App.jsx').read_text('utf-8')
        line = next(l for l in src.splitlines() if 'path="/rider/security"' in l)
        self.assertIn("<RequireRole roles={['delivery','admin','supervisor']}>", line)


class AccountReviewTests(TestCase):

    def _item(self, code):
        return next((i for i in preflight.check_accounts() if i.code == code), None)

    def test_clean_company_is_ok(self):
        make_user('n3acc_person', role='pharmacist')
        self.assertEqual([i.code for i in preflight.check_accounts()], ['accounts'])

    def test_accounts_without_profile_are_listed(self):
        User = get_user_model()
        User.objects.create_user('n3acc_loose', password='x-Pass-123')
        User.objects.create_superuser('n3acc_root', password='x-Pass-123')
        User.objects.create_user('n3acc_gone', password='x-Pass-123', is_active=False)
        item = self._item('accounts_no_profile')
        self.assertEqual(item.level, preflight.WARN)
        names = ' '.join(item.names)
        self.assertIn('n3acc_loose (viewer rows, never signed in)', names)
        self.assertIn('n3acc_root (superuser', names)
        self.assertNotIn('n3acc_gone', names)

    def test_service_accounts_are_listed(self):
        User = get_user_model()
        User.objects.create_user('n3acc_tokenonly')                 # no usable password
        make_user('pos_api_bridge', role='viewer')                   # machine-like name
        make_user('n3acc_human', role='pharmacist')
        item = self._item('accounts_service')
        self.assertEqual(item.level, preflight.WARN)
        names = ' '.join(item.names)
        self.assertIn('n3acc_tokenonly (no profile', names)
        self.assertIn('pos_api_bridge (viewer', names)
        self.assertNotIn('n3acc_human', names)

    def test_command_prints_the_list(self):
        get_user_model().objects.create_user('n3acc_cmd_svc')
        out = StringIO()
        try:
            call_command('access_preflight', stdout=out)
        except Exception:
            pass                                     # other blockers in a bare test DB
        self.assertIn('[accounts_service]', out.getvalue())
        self.assertIn('n3acc_cmd_svc', out.getvalue())
