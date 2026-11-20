"""
C12 (P-49) — one-tap call reason + outcome.

An agent's save must name a reason ('pending' is only for PBX auto-logs); the outcome is
optional and editable after saving; converting call items marks an empty outcome «reserved»;
the lookup suggests a reason from what is open; the dashboard reports the tagged share.
"""
from django.test import TestCase
from django.utils import timezone

from apps.callcenter.models import CallLog, CustomerCase
from apps.callcenter.reasons import reason_stats, suggest_purpose
from apps.pbx.models import AgentExtension, CallSession
from .factories import make_call_center, make_customer, make_pharmacist

URL = '/api/callcenter/calls/'


class ReasonRequiredTests(TestCase):

    def setUp(self):
        _, self.profile, self.api = make_call_center('cc_reason')

    def _post(self, **kw):
        body = dict(phone_number='01012345678', status='answered')
        body.update(kw)
        return self.api.post(URL, body, format='json')

    def test_manual_save_without_reason_rejected(self):
        r = self._post()
        self.assertEqual(r.status_code, 400)
        self.assertIn('purpose', r.data)
        self.assertEqual(CallLog.objects.count(), 0)

    def test_pending_is_not_an_agent_choice(self):
        r = self._post(purpose='pending')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(CallLog.objects.count(), 0)

    def test_reason_and_outcome_saved(self):
        r = self._post(purpose='demand', outcome='not_available')
        self.assertEqual(r.status_code, 201, r.data)
        log = CallLog.objects.get(pk=r.data['id'])
        self.assertEqual((log.purpose, log.outcome), ('demand', 'not_available'))
        self.assertEqual(r.data['outcome_label'], '❌ غير متوفر')

    def test_outcome_is_optional(self):
        r = self._post(purpose='refill')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(CallLog.objects.get(pk=r.data['id']).outcome, '')

    def test_unknown_outcome_rejected(self):
        self.assertEqual(self._post(purpose='refill', outcome='sold_twice').status_code, 400)

    def test_merge_into_pbx_log_also_needs_a_reason(self):
        ext = AgentExtension.objects.create(extension='311', staff=self.profile, extension_type='agent')
        s = CallSession.objects.create(unique_id='u-c12', direction='inbound', state='answered',
                                       caller_number='01012345678', agent=ext,
                                       started_at=timezone.now(), answered_at=timezone.now())
        s.complete()
        pbx_log = CallLog.objects.get(pbx_session=s)
        self.assertEqual(pbx_log.purpose, 'pending')       # PBX auto-log keeps a pending state
        self.assertEqual(self._post().status_code, 400)
        pbx_log.refresh_from_db()
        self.assertEqual(pbx_log.purpose, 'pending')
        r = self._post(purpose='complaint')
        self.assertEqual(r.data['id'], pbx_log.pk)
        pbx_log.refresh_from_db()
        self.assertEqual(pbx_log.purpose, 'complaint')


class OutcomeEditTests(TestCase):

    def setUp(self):
        _, self.profile, self.api = make_call_center('cc_outcome')
        self.log = CallLog.objects.create(phone_number='01012345678', purpose='pending',
                                          source='pbx', handled_by=self.profile)

    def test_agent_tags_reason_and_outcome_after_the_call(self):
        r = self.api.patch(f'{URL}{self.log.pk}/', {'purpose': 'new_order', 'outcome': 'ordered'},
                           format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.log.refresh_from_db()
        self.assertEqual((self.log.purpose, self.log.outcome), ('new_order', 'ordered'))

    def test_cannot_set_back_to_pending(self):
        self.log.purpose = 'refill'
        self.log.save()
        r = self.api.patch(f'{URL}{self.log.pk}/', {'purpose': 'pending'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.log.refresh_from_db()
        self.assertEqual(self.log.purpose, 'refill')

    def test_branch_pharmacist_cannot_edit(self):
        _, _, pharm = make_pharmacist('ph_c12')
        r = pharm.patch(f'{URL}{self.log.pk}/', {'outcome': 'ordered'}, format='json')
        self.assertIn(r.status_code, (403, 404))
        self.log.refresh_from_db()
        self.assertEqual(self.log.outcome, '')

    def test_mark_reserved_keeps_a_chosen_outcome(self):
        from apps.callcenter.views import _mark_reserved
        _mark_reserved(self.log)
        self.log.refresh_from_db()
        self.assertEqual(self.log.outcome, 'reserved')
        self.log.outcome = 'follow_up'
        self.log.save()
        _mark_reserved(self.log)
        self.log.refresh_from_db()
        self.assertEqual(self.log.outcome, 'follow_up')


class SuggestionAndStatsTests(TestCase):

    def test_suggestion_order(self):
        self.assertIsNone(suggest_purpose({}))
        self.assertEqual(suggest_purpose({'open_reservations': [1]}), 'new_order')
        self.assertEqual(suggest_purpose({'active_demands': [1]}), 'new_order')
        self.assertEqual(suggest_purpose({'open_reservations': [1], 'open_followups': [1]}), 'refill')
        self.assertEqual(suggest_purpose({'open_followups': [1], 'open_cases': [1]}), 'complaint')

    def test_lookup_suggests_complaint_for_open_case(self):
        _, _, api = make_call_center('cc_lookup_c12')
        cust = make_customer(phone='01055554444')
        CustomerCase.objects.create(customer=cust, title='تأخير', category='complaint')
        r = api.get(f'{URL}lookup/', {'phone': '01055554444'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['suggested_purpose'], 'complaint')

    def test_reason_stats(self):
        for purpose, outcome in (('pending', ''), ('general', ''), ('refill', 'ordered'),
                                 ('demand', 'not_available')):
            CallLog.objects.create(phone_number='010', purpose=purpose, outcome=outcome)
        st = reason_stats(CallLog.objects.all())
        self.assertEqual(st['reason_tagged'], 2)
        self.assertEqual(st['reason_pending'], 1)
        self.assertEqual(st['reason_tagged_pct'], 50.0)
        self.assertEqual(st['with_outcome'], 2)
        self.assertEqual({r['outcome'] for r in st['by_outcome']}, {'ordered', 'not_available'})

    def test_dashboard_reports_reason_share(self):
        _, _, api = make_call_center('cc_dash_c12')
        CallLog.objects.create(phone_number='010', purpose='refill')
        CallLog.objects.create(phone_number='011', purpose='pending')
        r = api.get(f'{URL}dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['reason_tagged_pct'], 50.0)
        self.assertEqual(r.data['reason_pending'], 1)
