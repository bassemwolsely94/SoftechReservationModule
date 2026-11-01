"""
Patient-roster wrong-allocation check (apps/insurance/roster.py) + its API.

Rosters are derived from earlier claims; a receipt whose patient was billed to a
different company (or another فئة / فئة فوترة of the same جهة) is flagged «wrong».
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.insurance import models as m
from apps.insurance.roster import (
    check_claim_roster, group_key, name_key, same_group,
)

_n = iter(range(1, 10_000))


def _client(name, sub='فئة'):
    c = m.InsuranceClient.objects.create(name=name)
    return m.InsuranceSubClient.objects.create(client=c, name=sub)


def _claim(sub, status='draft'):
    return m.InsuranceClaim.objects.create(
        claim_number=f'MT-R-{next(_n)}', subclient=sub, status=status,
        period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))


def _rx(claim, name, group=None, net=100):
    return m.InsuranceClaimPrescription.objects.create(
        claim=claim, softech_docnumber=str(next(_n)), softech_docdate=date(2026, 10, 5),
        softech_branchcode='160', patient_name=name, billing_group=group,
        gross_before=net, net_after=net)


def _group(claim, name, code):
    return m.InsuranceClaimBillingGroup.objects.create(claim=claim, code=code, name=name)


def _cat(result, name):
    return next(r['category'] for r in result['rows'] if r['patient_name'] == name) \
        if any(r['patient_name'] == name for r in result['rows']) else 'known'


class RosterKeyTests(TestCase):
    def test_abd_compound_joined(self):
        self.assertEqual(name_key('محمد عبد الموجود سيد'), name_key('محمد عبدالموجود سيد'))

    def test_group_key_ignores_article_and_order(self):
        self.assertTrue(same_group(group_key('منطقة القاهرة - الجهد الفائق'),
                                   group_key('منطقة القاهرة - جهد فائق')))
        self.assertTrue(same_group(group_key('التشغيل'), group_key('تشغيل')))
        self.assertFalse(same_group(group_key('شركة إنتاج الكهرباء - قطاع الجيزه'),
                                    group_key('شركة جنوب القاهرة للتوزيع - قطاع الجيزه')))


class RosterClassifyTests(TestCase):
    def setUp(self):
        self.a = _client('شركة جنوب القاهرة لتوزيع الكهرباء', 'العاملين')
        self.b = _client('الشركة القومية للتوزيع', 'شهرى')
        # sister record of A (same company name, pensioners)
        self.a2 = _client('شركة جنوب القاهرة لتوزيع الكهرباء', 'المعاشات')
        hist_a, hist_b, hist_a2 = _claim(self.a), _claim(self.b), _claim(self.a2)
        _rx(hist_a, 'احمد محمود سيد حسن')
        _rx(hist_b, 'سامي فوزي عبد الله بشاي')
        _rx(hist_a2, 'فاطمه علي حسن ابراهيم')
        _rx(hist_b, 'هاني رمزي فهيم جرجس')
        _rx(hist_a, 'هاني رمزي فهيم جرجس')
        self.claim = _claim(self.a)

    def test_categories(self):
        _rx(self.claim, 'احمد محمود سيد حسن')          # known here
        _rx(self.claim, 'سامى فوزى عبدالله بشاى')        # billed to another company only
        _rx(self.claim, 'فاطمة على حسن إبراهيم')         # only on the sister record
        _rx(self.claim, 'كريم ناجي عوض')                # nowhere
        _rx(self.claim, 'هاني رمزي فهيم جرجس')           # here AND another company
        r = check_claim_roster(self.claim)
        self.assertEqual(_cat(r, 'احمد محمود سيد حسن'), 'known')
        self.assertEqual(_cat(r, 'سامى فوزى عبدالله بشاى'), 'wrong')
        self.assertEqual(_cat(r, 'فاطمة على حسن إبراهيم'), 'sister')
        self.assertEqual(_cat(r, 'كريم ناجي عوض'), 'new')
        self.assertEqual(_cat(r, 'هاني رمزي فهيم جرجس'), 'shared')
        wrong = next(x for x in r['rows'] if x['category'] == 'wrong')
        self.assertEqual(wrong['confidence'], 'full')
        self.assertEqual(wrong['where'][0]['scope'], 'company')
        self.assertEqual(wrong['where'][0]['client_id'], self.b.client_id)
        self.assertEqual(r['wrong_net'], 100.0)

    def test_excluded_and_cancelled_history_is_not_evidence(self):
        cancelled = _claim(self.b, status='cancelled')
        _rx(cancelled, 'مجدي صبحي نصر الله')
        excl = _rx(_claim(self.b), 'وائل حمدي توفيق شاكر')
        m.InsuranceClaimExclusion.objects.create(prescription=excl, reason='x')
        _rx(self.claim, 'مجدي صبحي نصر الله')
        _rx(self.claim, 'وائل حمدي توفيق شاكر')
        r = check_claim_roster(self.claim)
        self.assertEqual(_cat(r, 'مجدي صبحي نصر الله'), 'new')
        self.assertEqual(_cat(r, 'وائل حمدي توفيق شاكر'), 'new')

    def test_three_word_name_inside_longer_is_only_partial(self):
        _rx(_claim(self.b), 'محمد سيد احمد')
        _rx(self.claim, 'محمد عبدالموجود سيد احمد')
        row = next(x for x in check_claim_roster(self.claim)['rows']
                   if x['patient_name'] == 'محمد عبدالموجود سيد احمد')
        self.assertEqual(row['confidence'], 'partial')

    def test_billing_group_division(self):
        """Same جهة, but the patient belongs to a different فئة فوترة."""
        hist = _claim(self.a)
        _rx(hist, 'ابراهيم عادل شوقي مرسي', group=_group(hist, 'التشغيل', '101'))
        _rx(hist, 'رامي نبيل صادق ميخائيل', group=_group(hist, 'الإتصالات', '102'))
        g_op = _group(self.claim, 'تشغيل', '101')
        _rx(self.claim, 'ابراهيم عادل شوقي مرسي', group=g_op)     # same group, other spelling
        _rx(self.claim, 'رامي نبيل صادق ميخائيل', group=g_op)     # was under اتصالات
        r = check_claim_roster(self.claim)
        self.assertEqual(_cat(r, 'ابراهيم عادل شوقي مرسي'), 'known')
        row = next(x for x in r['rows'] if x['patient_name'] == 'رامي نبيل صادق ميخائيل')
        self.assertEqual(row['category'], 'wrong')
        self.assertEqual(row['where'][0]['scope'], 'division')
        self.assertEqual(row['where'][0]['group_label'], 'الإتصالات')

    def test_separation_list_target_counts_as_roster(self):
        lst = m.InsuranceSeparationList.objects.create(label='ق', target_client=self.b.client)
        m.InsuranceSeparationName.objects.create(sep_list=lst, name='نبيل حنا جورجي فرج')
        _rx(self.claim, 'نبيل حنا جورجي فرج')
        r = check_claim_roster(self.claim)
        self.assertEqual(_cat(r, 'نبيل حنا جورجي فرج'), 'wrong')
        self.assertTrue(r['rows'][0]['where'][0]['from_list'])


class RosterApiTests(TestCase):
    def setUp(self):
        u = get_user_model().objects.create_user(username='r', password='x',
                                                  is_staff=True, is_superuser=True)
        self.api = APIClient(); self.api.force_authenticate(u)
        self.a = _client('جهة أ')
        self.b = _client('جهة ب')
        _rx(_claim(self.b), 'سامي فوزي عبد الله بشاي')
        self.claim = _claim(self.a)
        self.rx = _rx(self.claim, 'سامي فوزي عبد الله بشاي')

    def _check(self):
        r = self.api.get(f'/api/insurance/claims/{self.claim.id}/roster-check/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def _decide(self, **body):
        return self.api.post(f'/api/insurance/claims/{self.claim.id}/roster-decision/',
                             {'prescription_ids': [self.rx.id], **body}, format='json')

    def test_member_decision_silences_flag_and_is_audited(self):
        self.assertEqual(self._check()['counts']['wrong'], 1)
        self.assertEqual(self._decide(verdict='member').status_code, 200)
        self.assertEqual(self._check()['counts']['wrong'], 0)
        self.assertTrue(m.InsuranceAuditEvent.objects.filter(
            claim=self.claim, action='roster_decision').exists())
        # clearing brings the flag back
        self._decide(verdict='clear')
        self.assertEqual(self._check()['counts']['wrong'], 1)

    def test_not_member_with_target_makes_name_known_there(self):
        r = self._decide(verdict='not_member', target={'client_id': self.b.client_id,
                                                       'subclient_id': self.b.id})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(m.InsuranceRosterDecision.objects.filter(
            client=self.b.client, verdict='member').exists())
        # next month on B's claim the patient is known, A's old billing is not evidence
        nxt = _claim(self.b)
        _rx(nxt, 'سامي فوزي عبد الله بشاي')
        res = check_claim_roster(nxt)
        self.assertEqual(res['counts']['wrong'], 0)

    def test_bad_input(self):
        self.assertEqual(self._decide(verdict='maybe').status_code, 400)
        self.assertEqual(self._decide(verdict='not_member', target={'client_id': 999999}).status_code, 400)

    def test_decisions_do_not_change_totals(self):
        before = self.claim.final_net_after
        self._decide(verdict='not_member')
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.final_net_after, before)
