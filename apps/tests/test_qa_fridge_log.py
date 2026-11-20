"""
C31 (audit doc 08, P-53): fridge temperature log + EDA visit checklist on the existing QA inspections.
Rules: one reading per fridge per slot, append-only; out of range = any of the three values outside
the fridge's range (alert at once); a missed slot alerts the branch once; branch-scoped; QA roles only.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.notifications.models import Notification
from apps.qa import fridge as F
from apps.qa.models import FridgeReading, FridgeUnit, QAChecklistTemplate
from apps.tests.factories import make_branch, make_branch2, make_user
from core.middleware import module_access

from .security.fixtures import bearer_client, seed_code_matrix

READINGS = '/api/qa/fridge-readings/'
FRIDGES = '/api/qa/fridges/'


def _cairo(h, m=0, day=None):
    day = day or timezone.localdate()
    return timezone.make_aware(dt.datetime.combine(day, dt.time(h, m)))


class FridgeRuleTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.f = FridgeUnit.objects.create(branch=self.branch, name='ثلاجة 1')
        make_user('fr_staff', role='pharmacist', branch=self.branch)

    def _r(self, temp, lo=None, hi=None):
        return FridgeReading(fridge=self.f, day=timezone.localdate(), slot='am', temp_c=Decimal(temp),
                             min_seen_c=None if lo is None else Decimal(lo),
                             max_seen_c=None if hi is None else Decimal(hi), initials='م.ع')

    def test_out_of_range_is_any_value_outside_inclusive_range(self):
        self.assertFalse(self._r('2.0', '2.0', '8.0').compute_out_of_range())   # edges are in range
        self.assertTrue(self._r('8.1').compute_out_of_range())
        self.assertTrue(self._r('5', '1.5', '6').compute_out_of_range())       # min-seen dipped
        self.assertTrue(self._r('5', '3', '9').compute_out_of_range())         # max-seen peaked

    def test_slot_follows_cairo_time(self):
        self.assertEqual(F.slot_for(_cairo(9)), 'am')
        self.assertEqual(F.slot_for(_cairo(18)), 'pm')

    def test_missed_alert_once_per_fridge_day_slot(self):
        self.assertEqual(F.check_missed(_cairo(11)), 0)            # nothing due before 12:00
        sent = F.check_missed(_cairo(12, 15))
        self.assertGreaterEqual(sent, 1)
        n = Notification.objects.filter(notification_type=F.NOTIF_TYPE).count()
        self.assertGreater(n, 0)
        F.check_missed(_cairo(12, 45))                              # re-run: nothing new
        self.assertEqual(Notification.objects.filter(notification_type=F.NOTIF_TYPE).count(), n)

    def test_no_missed_alert_when_the_reading_is_there_or_fridge_off(self):
        FridgeReading.objects.create(fridge=self.f, day=timezone.localdate(), slot='am', temp_c=5, initials='x')
        self.assertEqual(F.check_missed(_cairo(12, 15)), 0)
        self.f.is_active = False
        self.f.save()
        self.assertEqual(F.check_missed(_cairo(20, 15)), 0)

    def test_month_sheet_counts_only_due_slots(self):
        day = timezone.localdate()
        FridgeReading.objects.create(fridge=self.f, day=day, slot='am', temp_c=5, initials='x')
        sheet = F.month_sheet(self.f, day.year, day.month, now=_cairo(13, 0, day))
        today = next(r for r in sheet['rows'] if r['day'] == day.isoformat())
        self.assertEqual(today['am']['temp_c'], 5)
        self.assertEqual(today['pm'], {'missing': False})          # 20:00 not reached yet
        self.assertEqual(sheet['due_slots'], (day.day - 1) * 2 + 1)
        self.assertEqual(sheet['present'], 1)

    def test_eda_visit_template_is_seeded(self):
        t = QAChecklistTemplate.objects.get(name='eda_visit')
        keys = {i['key'] for i in t.items}
        self.assertTrue({'fridge_log', 'fridge_range', 'license', 'controlled'} <= keys)


@override_settings(RBAC_ENFORCEMENT='enforce')
class FridgeApiTests(TestCase):
    def setUp(self):
        seed_code_matrix()
        self.branch, self.other = make_branch(), make_branch2()
        self.f = FridgeUnit.objects.create(branch=self.branch, name='ثلاجة 1')
        self.f_other = FridgeUnit.objects.create(branch=self.other, name='ثلاجة 2')
        self.ph = bearer_client(make_user('fr_ph', role='pharmacist', branch=self.branch)[0])

    def tearDown(self):
        module_access.clear_cache()

    def _post(self, client, fridge, temp='5.0', **extra):
        body = {'fridge': fridge.pk, 'day': timezone.localdate().isoformat(), 'slot': 'am',
                'temp_c': temp, 'initials': 'م.ع', **extra}
        return client.post(READINGS, body, format='json')

    def test_pharmacist_records_a_reading_for_own_branch(self):
        r = self._post(self.ph, self.f)
        self.assertEqual(r.status_code, 201, r.content)
        reading = FridgeReading.objects.get()
        self.assertFalse(reading.out_of_range)
        self.assertEqual(reading.recorded_by.user.username, 'fr_ph')

    def test_one_reading_per_slot_and_append_only(self):
        self.assertEqual(self._post(self.ph, self.f).status_code, 201)
        self.assertEqual(self._post(self.ph, self.f, temp='6').status_code, 400)
        rid = FridgeReading.objects.get().pk
        # the pharmacist has no hr edit grant, so the matrix refuses first (403); an admin passes the
        # matrix and still finds no reading detail URL at all (404) — readings are append-only for everyone
        self.assertEqual(self.ph.patch(f'{READINGS}{rid}/', {'temp_c': '4'}, format='json').status_code, 403)
        admin = bearer_client(make_user('fr_admin', role='admin', branch=self.branch)[0])
        self.assertEqual(admin.patch(f'{READINGS}{rid}/', {'temp_c': '4'}, format='json').status_code, 404)
        self.assertEqual(admin.delete(f'{READINGS}{rid}/').status_code, 404)
        self.assertEqual(FridgeReading.objects.get().temp_c, Decimal('5.0'))

    def test_only_today_or_yesterday(self):
        old = (timezone.localdate() - dt.timedelta(days=3)).isoformat()
        self.assertEqual(self._post(self.ph, self.f, day=old).status_code, 400)

    def test_out_of_range_alerts_the_branch(self):
        with mock.patch.object(Notification, 'send_to_branch', return_value=1) as send:
            r = self._post(self.ph, self.f, temp='9.5')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.data['out_of_range'])
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs['branch'], self.branch)

    def test_branch_scope(self):
        self.assertEqual(self._post(self.ph, self.f_other).status_code, 403)
        ids = [f['id'] for f in self.ph.get(FRIDGES).data.get('results', self.ph.get(FRIDGES).data)]
        self.assertEqual(ids, [self.f.pk])
        self.assertEqual(self.ph.get(f'{FRIDGES}{self.f_other.pk}/month/').status_code, 404)

    def test_range_is_fixed_after_registration(self):
        # admin passes the edit grant, so this exercises the view's own rule, not the matrix
        admin = bearer_client(make_user('fr_admin2', role='admin', branch=self.branch)[0])
        r = admin.patch(f'{FRIDGES}{self.f.pk}/', {'max_c': '12'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(admin.patch(f'{FRIDGES}{self.f.pk}/', {'name': 'ثلاجة الأنسولين'}, format='json').status_code, 200)
        self.f.refresh_from_db()
        self.assertEqual(self.f.max_c, 8)

    def test_roles_without_the_qa_flag_are_refused(self):
        for role in ('salesperson', 'call_center', 'viewer', 'accountant'):
            with self.subTest(role=role):
                c = bearer_client(make_user(f'fr_{role}', role=role, branch=self.branch)[0])
                self.assertEqual(c.get(READINGS).status_code, 403)
                self.assertEqual(c.get(FRIDGES).status_code, 403)

    def test_month_sheet_endpoint(self):
        self._post(self.ph, self.f)
        r = self.ph.get(f'{FRIDGES}{self.f.pk}/month/', {'month': timezone.localdate().strftime('%Y-%m')})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['fridge']['id'], self.f.pk)
        self.assertEqual(self.ph.get(f'{FRIDGES}{self.f.pk}/month/', {'month': 'bad'}).status_code, 400)


class SeesAllBranchesFlagTests(TestCase):
    """/api/auth/me/ sees_all_branches drives the fridge page's branch picker (no JS role list)."""

    def test_flag_follows_branch_scope(self):
        branch = make_branch()
        self.assertTrue(make_user('fr_flag_qm', role='quality_manager')[2].get('/api/auth/me/').json()['sees_all_branches'])
        self.assertFalse(make_user('fr_flag_ph', role='pharmacist', branch=branch)[2].get('/api/auth/me/').json()['sees_all_branches'])
