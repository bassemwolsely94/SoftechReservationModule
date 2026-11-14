"""
apps/tests/test_crews_membership.py

Crews piece 2a, Task 2: Crew / CrewRule / CrewManualMember + the membership resolver
(spec 2026-11-13 §6.3–6.4). Membership is dated: editing from a day never changes earlier spans.
"""
from datetime import date, timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.crews import membership as m
from apps.crews.models import Crew, CrewManualMember, CrewRule
from apps.hr.assignments import record_assignment
from apps.hr.models import Employee
from apps.tests.factories import make_branch, make_user

D = date


def emp(hr, job, branch, *, start=D(2025, 1, 1), end=None, dept='', section='', usercode='',
        exts=None, staff=None):
    e = Employee.objects.create(
        hr_number=hr, name_ar=f'موظف {hr}', job_title=job, branch=branch, department=dept,
        section=section, start_date=start, end_date=end, softech_usercode=usercode,
        pbx_extensions=exts or [], staff=staff, status='left' if end else 'active')
    record_assignment(e, on=start, source='seed')
    return e


def change(e, on, **fields):
    for k, v in fields.items():
        setattr(e, k, v)
    e.save()
    record_assignment(e, on=on, source='manual')


def rule(crew, *, jobs=(), branches=(), depts=(), sections=(), frm=D(2025, 1, 1), to=None):
    r = CrewRule.objects.create(crew=crew, job_titles=list(jobs), departments=list(depts),
                                sections=list(sections), valid_from=frm, valid_to=to)
    r.branches.set(branches)
    return r


def manual(crew, mode, *, employee=None, code='', ext='', label='', frm=D(2025, 1, 1), to=None):
    return CrewManualMember.objects.create(
        crew=crew, mode=mode, employee=employee, softech_usercode=code, pbx_extension=ext,
        label=label, reason='اختبار', valid_from=frm, valid_to=to)


def keys(members):
    return {x.key for x in members}


class CrewMembershipTests(TestCase):
    def setUp(self):
        self.b130 = make_branch('فرع 130', '130')
        self.b140 = make_branch('فرع 140', '140')
        self.crew = Crew.objects.create(name='صيادلة', type='job')
        self.day = D(2026, 10, 10)

    def test_rule_matches_job_and_branch(self):
        a = emp('1', 'صيدلي', self.b130)
        b = emp('2', 'صيدلي', self.b140)
        c = emp('3', 'كاشير', self.b130)
        rule(self.crew, jobs=['صيدلي'], branches=[self.b130])
        got = m.members(self.crew, self.day)
        self.assertEqual(keys(got), {('emp', a.id)})
        self.assertNotIn(('emp', b.id), keys(got))
        self.assertNotIn(('emp', c.id), keys(got))
        only = got[0]
        self.assertEqual((only.source, only.job_title, only.branch_id, only.off_payroll),
                         ('rule', 'صيدلي', self.b130.id, False))

    def test_empty_sets_are_wildcards_but_all_empty_rule_matches_nobody(self):
        a = emp('1', 'صيدلي', self.b130)
        b = emp('2', 'صيدلي', self.b140)
        emp('3', 'كاشير', self.b130)
        r = rule(self.crew, jobs=['صيدلي'])          # any branch
        self.assertEqual(keys(m.members(self.crew, self.day)), {('emp', a.id), ('emp', b.id)})
        r.job_titles = []
        r.save()                                      # all sets empty → nobody
        self.assertEqual(m.members(self.crew, self.day), [])

    def test_rule_with_several_job_titles(self):
        a = emp('1', 'صيدلي', self.b130)
        b = emp('2', 'مساعد صيدلي', self.b140)
        emp('3', 'كاشير', self.b130)
        rule(self.crew, jobs=['صيدلي', 'مساعد صيدلي'])
        self.assertEqual(keys(m.members(self.crew, self.day)), {('emp', a.id), ('emp', b.id)})

    def test_department_and_section_sets(self):
        a = emp('1', 'موظف', self.b130, dept='المبيعات', section='الكول سنتر')
        emp('2', 'موظف', self.b130, dept='المبيعات', section='الفروع')
        emp('3', 'موظف', self.b130, dept='الحسابات', section='الكول سنتر')
        rule(self.crew, depts=['المبيعات'], sections=['الكول سنتر'])
        self.assertEqual(keys(m.members(self.crew, self.day)), {('emp', a.id)})

    def test_assignment_change_splits_span(self):
        a = emp('1', 'صيدلي', self.b130)
        rule(self.crew, jobs=['صيدلي'])
        change(a, D(2026, 10, 15), job_title='مدير فرع')
        spans = m.members_between(self.crew, D(2026, 10, 1), D(2026, 10, 31))
        self.assertEqual(spans, {('emp', a.id): [(D(2026, 10, 1), D(2026, 10, 14))]})

    def test_left_employee_drops_after_end_date(self):
        a = emp('1', 'صيدلي', self.b130, end=D(2026, 10, 20))
        rule(self.crew, jobs=['صيدلي'])
        spans = m.members_between(self.crew, D(2026, 10, 1), D(2026, 10, 31))
        self.assertEqual(spans, {('emp', a.id): [(D(2026, 10, 1), D(2026, 10, 20))]})
        self.assertEqual(m.members(self.crew, D(2026, 10, 21)), [])
        late = emp('2', 'صيدلي', self.b130, start=D(2026, 10, 5))
        self.assertEqual(m.members_between(self.crew, D(2026, 10, 1), D(2026, 10, 31))[('emp', late.id)],
                         [(D(2026, 10, 5), D(2026, 10, 31))])

    def test_manual_include_off_payroll_usercode(self):
        manual(self.crew, 'include', code='777', label='وكيل خارجي')
        got = m.members(self.crew, self.day)
        self.assertEqual(len(got), 1)
        x = got[0]
        self.assertIs(x.off_payroll, True)
        self.assertEqual(x.key, ('code', '777'))
        self.assertEqual(x.softech_usercodes, ('777',))
        self.assertEqual((x.employee_id, x.name, x.source), (None, 'وكيل خارجي', 'manual'))
        manual(self.crew, 'include', ext='215')
        ext = [y for y in m.members(self.crew, self.day) if y.key == ('ext', '215')][0]
        self.assertEqual((ext.extensions, ext.off_payroll), (('215',), True))

    def test_manual_exclude_only_inside_its_dates(self):
        a = emp('1', 'صيدلي', self.b130)
        rule(self.crew, jobs=['صيدلي'])
        manual(self.crew, 'exclude', employee=a, frm=D(2026, 10, 10), to=D(2026, 10, 20))
        spans = m.members_between(self.crew, D(2026, 10, 1), D(2026, 10, 31))
        self.assertEqual(spans[('emp', a.id)],
                         [(D(2026, 10, 1), D(2026, 10, 9)), (D(2026, 10, 21), D(2026, 10, 31))])
        # a manual include of an employee outside every rule
        b = emp('2', 'كاشير', self.b140)
        manual(self.crew, 'include', employee=b, frm=D(2026, 10, 25))
        self.assertEqual(m.members_between(self.crew, D(2026, 10, 1), D(2026, 10, 31))[('emp', b.id)],
                         [(D(2026, 10, 25), D(2026, 10, 31))])
        inc = [x for x in m.members(self.crew, D(2026, 10, 26)) if x.employee_id == b.id][0]
        self.assertEqual((inc.source, inc.job_title, inc.branch_id), ('manual', 'كاشير', self.b140.id))

    def test_exclude_by_usercode_removes_matching_employee(self):
        a = emp('1', 'صيدلي', self.b130, usercode='55')
        b = emp('2', 'صيدلي', self.b130, usercode='56')
        rule(self.crew, jobs=['صيدلي'])
        manual(self.crew, 'include', code='88')
        manual(self.crew, 'exclude', code='55')
        manual(self.crew, 'exclude', code='88')
        self.assertEqual(keys(m.members(self.crew, self.day)), {('emp', b.id)})
        self.assertNotIn(('emp', a.id), keys(m.members(self.crew, self.day)))

    def test_ended_rule_stops_at_valid_to_and_voided_row_ignored(self):
        a = emp('1', 'صيدلي', self.b130)
        rule(self.crew, jobs=['صيدلي'], to=D(2026, 10, 12))
        x = manual(self.crew, 'exclude', employee=a, frm=D(2026, 10, 1))
        x.voided_at = timezone.now()
        x.save()
        v = rule(self.crew, jobs=['صيدلي'], frm=D(2026, 10, 20))
        v.voided_at = timezone.now()
        v.save()
        spans = m.members_between(self.crew, D(2026, 10, 1), D(2026, 10, 31))
        self.assertEqual(spans, {('emp', a.id): [(D(2026, 10, 1), D(2026, 10, 12))]})

    def test_replacing_rule_from_d_keeps_earlier_membership(self):
        a = emp('1', 'صيدلي', self.b130)
        b = emp('2', 'صيدلي', self.b140)
        old = rule(self.crew, jobs=['صيدلي'], branches=[self.b130, self.b140])
        oct_ = (D(2026, 10, 1), D(2026, 10, 31))
        before = m.members_between(self.crew, *oct_)
        old.valid_to = D(2026, 11, 30)
        old.save()
        rule(self.crew, jobs=['صيدلي'], branches=[self.b130], frm=D(2026, 12, 1))
        self.assertEqual(m.members_between(self.crew, *oct_), before)
        self.assertEqual(keys(m.members(self.crew, D(2026, 12, 5))), {('emp', a.id)})
        self.assertEqual(m.members_between(self.crew, D(2026, 11, 1), D(2026, 12, 31))[('emp', b.id)],
                         [(D(2026, 11, 1), D(2026, 11, 30))])

    def test_identities_carry_codes_extensions_staff_with_spans(self):
        _, profile, _ = make_user('crew_staff', branch=self.b130)
        a = emp('1', 'صيدلي', self.b130, usercode='55', exts=['201', '202'], staff=profile)
        rule(self.crew, jobs=['صيدلي'], to=D(2026, 10, 15))
        manual(self.crew, 'include', ext='215', frm=D(2026, 10, 10))
        got = m.identities(self.crew, D(2026, 10, 1), D(2026, 10, 31))
        ka = ('emp', a.id)
        oct1, oct15 = D(2026, 10, 1), D(2026, 10, 15)
        self.assertCountEqual(got, [
            m.Identity('softech_user', '55', oct1, oct15, ka),
            m.Identity('extension', '201', oct1, oct15, ka),
            m.Identity('extension', '202', oct1, oct15, ka),
            m.Identity('staff', str(profile.id), oct1, oct15, ka),
            m.Identity('extension', '215', D(2026, 10, 10), D(2026, 10, 31), ('ext', '215')),
        ])

    def test_members_between_query_count_independent_of_range(self):
        a = emp('1', 'صيدلي', self.b130)
        emp('2', 'صيدلي', self.b140)
        rule(self.crew, jobs=['صيدلي'])
        manual(self.crew, 'include', code='777')
        manual(self.crew, 'exclude', employee=a, frm=D(2026, 3, 1), to=D(2026, 3, 10))
        change(a, D(2026, 6, 1), branch=self.b140)
        with CaptureQueriesContext(connection) as short:
            m.members_between(self.crew, D(2026, 10, 1), D(2026, 10, 31))
        with self.assertNumQueries(len(short.captured_queries)):
            m.members_between(self.crew, D(2026, 1, 1), D(2026, 12, 31))

    def test_preview_uses_unsaved_rules_and_crew_manual_rows(self):
        a = emp('1', 'صيدلي', self.b130)
        b = emp('2', 'صيدلي', self.b140)
        c = emp('3', 'كاشير', self.b130)
        manual(self.crew, 'include', employee=c)
        manual(self.crew, 'exclude', employee=b, frm=self.day + timedelta(days=1))
        specs = [{'job_titles': ['صيدلي'], 'branch_ids': [self.b130.id, self.b140.id],
                  'departments': [], 'sections': []}]
        self.assertEqual(keys(m.preview(specs, self.day)), {('emp', a.id), ('emp', b.id)})
        self.assertEqual(keys(m.preview(specs, self.day, crew=self.crew)),
                         {('emp', a.id), ('emp', b.id), ('emp', c.id)})
        self.assertEqual(keys(m.preview(specs, self.day + timedelta(days=1), crew=self.crew)),
                         {('emp', a.id), ('emp', c.id)})
        self.assertFalse(CrewRule.objects.exists())     # nothing saved
        self.assertEqual(m.preview([{'job_titles': [], 'branch_ids': []}], self.day), [])

    def test_crew_name_unique_among_live_only(self):
        Crew.objects.create(name='Old', type='custom', is_archived=True)
        Crew.objects.create(name='old', type='custom')          # archived duplicate allowed
        with self.assertRaises(IntegrityError), transaction.atomic():
            Crew.objects.create(name='OLD', type='custom')

    def test_has_history_and_members_sorted_by_name(self):
        self.assertFalse(self.crew.has_history())
        today = timezone.localdate()
        rule(self.crew, jobs=['صيدلي'], frm=today)
        self.assertFalse(self.crew.has_history())
        manual(self.crew, 'include', code='9', frm=today - timedelta(days=1))
        self.assertTrue(self.crew.has_history())
        emp('2', 'صيدلي', self.b130)
        emp('1', 'صيدلي', self.b140)
        Employee.objects.filter(hr_number='2').update(name_ar='ي')
        Employee.objects.filter(hr_number='1').update(name_ar='أ')
        names = [x.name for x in m.members(self.crew, today)]
        self.assertEqual(names, sorted(names))


class CrewMembershipReviewFixTests(TestCase):
    """Review round 1: one member per identity, dated identities, consistency of members/spans."""

    def setUp(self):
        self.b130 = make_branch('فرع 130', '130')
        self.crew = Crew.objects.create(name='كول سنتر', type='call_center')
        self.day = D(2026, 10, 10)

    def test_bare_include_of_an_employee_code_is_one_member(self):
        a = emp('1', 'صيدلي', self.b130, usercode='555', exts=['201'])
        rule(self.crew, jobs=['صيدلي'])
        manual(self.crew, 'include', code='555')
        manual(self.crew, 'include', ext='201')
        self.assertEqual(keys(m.members(self.crew, self.day)), {('emp', a.id)})
        got = m.identities(self.crew, D(2026, 10, 1), D(2026, 10, 31))
        self.assertEqual([i for i in got if i.kind == 'softech_user'],
                         [m.Identity('softech_user', '555', D(2026, 10, 1), D(2026, 10, 31), ('emp', a.id))])
        self.assertEqual(len([i for i in got if i.kind == 'extension']), 1)

    def test_identities_are_dated_by_assignment(self):
        a = emp('1', 'صيدلي', self.b130, usercode='55', exts=['201'])
        rule(self.crew, jobs=['صيدلي'])
        today = timezone.localdate()
        last_end = today.replace(day=1) - timedelta(days=1)
        last_start = last_end.replace(day=1)
        before = m.identities(self.crew, last_start, last_end)
        change(a, today, softech_usercode='66', pbx_extensions=['299'])
        self.assertEqual(m.identities(self.crew, last_start, last_end), before)
        self.assertEqual({i.value for i in before}, {'55', '201'})
        now = m.members(self.crew, today)[0]
        self.assertEqual((now.softech_usercodes, now.extensions), (('66',), ('299',)))
        # exclusion follows the dated code too: excluding 66 does not touch last month
        manual(self.crew, 'exclude', code='66', frm=last_start)
        self.assertEqual(m.identities(self.crew, last_start, last_end), before)
        self.assertEqual(m.members(self.crew, today), [])

    def test_bare_row_with_code_and_extension_keeps_both(self):
        manual(self.crew, 'include', code='777', ext='215', label='وكيل')
        x = m.members(self.crew, self.day)[0]
        self.assertEqual((x.key, x.softech_usercodes, x.extensions), (('code', '777'), ('777',), ('215',)))
        kinds = {(i.kind, i.value) for i in m.identities(self.crew, self.day, self.day)}
        self.assertEqual(kinds, {('softech_user', '777'), ('extension', '215')})

    def test_extension_exclude_removes_employee_carrying_it(self):
        a = emp('1', 'صيدلي', self.b130, exts=['201', '202'])
        b = emp('2', 'صيدلي', self.b130, exts=['203'])
        rule(self.crew, jobs=['صيدلي'])
        manual(self.crew, 'exclude', ext='202')
        self.assertEqual(keys(m.members(self.crew, self.day)), {('emp', b.id)})
        self.assertNotIn(('emp', a.id), keys(m.members(self.crew, self.day)))

    def test_preview_with_crew_does_not_read_its_rules(self):
        rule(self.crew, jobs=['صيدلي'])
        with CaptureQueriesContext(connection) as ctx:
            m.preview([{'job_titles': ['كاشير']}], self.day, crew=self.crew)
        self.assertFalse([q for q in ctx.captured_queries if 'crews_crewrule' in q['sql']])

    # ── final review F2: identities are deduped one by one ──────────────────────────────

    def test_employee_include_row_adds_its_own_code_and_extension_while_active(self):
        a = emp('1', 'كاشير', self.b130, usercode='55', exts=['201'])
        manual(self.crew, 'include', employee=a, code='900', ext='250', frm=D(2026, 10, 5), to=D(2026, 10, 20))
        x = m.members(self.crew, self.day)[0]
        self.assertEqual((x.key, set(x.softech_usercodes), set(x.extensions)),
                         (('emp', a.id), {'55', '900'}, {'201', '250'}))
        # also when the employee is in by a rule, and only while the row is active
        rule(self.crew, jobs=['كاشير'])
        x = m.members(self.crew, self.day)[0]
        self.assertEqual((set(x.softech_usercodes), set(x.extensions)), ({'55', '900'}, {'201', '250'}))
        later = m.members(self.crew, D(2026, 10, 25))[0]
        self.assertEqual((later.softech_usercodes, later.extensions), (('55',), ('201',)))
        got = {(i.kind, i.value): (i.valid_from, i.valid_to)
               for i in m.identities(self.crew, D(2026, 10, 1), D(2026, 10, 31))}
        self.assertEqual(got[('softech_user', '900')], (D(2026, 10, 5), D(2026, 10, 20)))
        self.assertEqual(got[('softech_user', '55')], (D(2026, 10, 1), D(2026, 10, 31)))

    def test_bare_row_keeps_the_identity_no_employee_carries(self):
        a = emp('1', 'صيدلي', self.b130, usercode='555')
        rule(self.crew, jobs=['صيدلي'])
        manual(self.crew, 'include', code='555', ext='299', label='وكيل')
        got = {x.key: x for x in m.members(self.crew, self.day)}
        self.assertEqual(set(got), {('emp', a.id), ('code', '555')})
        bare = got[('code', '555')]
        self.assertEqual((bare.softech_usercodes, bare.extensions, bare.off_payroll), ((), ('299',), True))
        self.assertEqual(got[('emp', a.id)].softech_usercodes, ('555',))
        ids = [(i.kind, i.value, i.member_key) for i in m.identities(self.crew, self.day, self.day)]
        self.assertCountEqual(ids, [('softech_user', '555', ('emp', a.id)),
                                    ('extension', '299', ('code', '555'))])

    def test_employee_exclude_also_strips_that_employee_identities_from_bare_rows(self):
        a = emp('1', 'صيدلي', self.b130, usercode='555', exts=['201'])
        rule(self.crew, jobs=['صيدلي'])
        manual(self.crew, 'include', code='555', label='كود أ')
        manual(self.crew, 'include', ext='201', label='داخلي أ')
        manual(self.crew, 'include', code='777', ext='201', label='وكيل')
        manual(self.crew, 'exclude', employee=a, frm=D(2026, 10, 10))
        before = {x.key for x in m.members(self.crew, D(2026, 10, 9))}
        self.assertEqual(before, {('emp', a.id), ('code', '777')})
        got = {x.key: x for x in m.members(self.crew, self.day)}
        self.assertEqual(set(got), {('code', '777')})
        self.assertEqual((got[('code', '777')].softech_usercodes, got[('code', '777')].extensions), (('777',), ()))
        self.assertFalse([i for i in m.identities(self.crew, self.day, self.day) if i.value in ('555', '201')])

    def test_employee_exclude_strips_identities_even_when_not_otherwise_a_member(self):
        a = emp('1', 'صيدلي', self.b130, usercode='555')
        manual(self.crew, 'include', code='555', label='كود أ')
        manual(self.crew, 'exclude', employee=a)
        self.assertEqual(m.members(self.crew, self.day), [])

    def test_members_agree_with_members_between_every_day(self):
        b140 = make_branch('فرع 140', '140')
        a = emp('1', 'صيدلي', self.b130, usercode='55')
        b = emp('2', 'صيدلي', b140, start=D(2026, 10, 7), end=D(2026, 10, 24))
        c = emp('3', 'كاشير', self.b130)
        rule(self.crew, jobs=['صيدلي'], to=D(2026, 10, 20))
        rule(self.crew, jobs=['صيدلي'], branches=[self.b130], frm=D(2026, 10, 21))
        manual(self.crew, 'include', employee=c, frm=D(2026, 10, 5), to=D(2026, 10, 12))
        manual(self.crew, 'exclude', code='55', frm=D(2026, 10, 15), to=D(2026, 10, 17))
        manual(self.crew, 'include', code='777', frm=D(2026, 10, 9))
        change(a, D(2026, 10, 27), branch=b140)
        start, end = D(2026, 10, 1), D(2026, 10, 31)
        spans = m.members_between(self.crew, start, end)
        self.assertEqual(set(spans), {('emp', a.id), ('emp', b.id), ('emp', c.id), ('code', '777')})
        d = start
        while d <= end:
            expected = {k for k, lst in spans.items() if any(f <= d <= t for f, t in lst)}
            self.assertEqual(keys(m.members(self.crew, d)), expected, d)
            d += timedelta(days=1)
