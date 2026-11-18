"""Crews piece 2b, Task 4: PBX extension classification from crews, employee data and a file."""
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.crews.models import Crew, CrewManualMember
from apps.hr.assignments import record_assignment
from apps.hr.models import Employee
from apps.pbx import classification
from apps.pbx.models import AgentExtension

TODAY = date(2026, 11, 18)


def ext(n, t='other'):
    return AgentExtension.objects.create(extension=n, extension_type=t)


def kind(n):
    return AgentExtension.objects.get(extension=n).extension_type


class PbxClassificationTests(TestCase):
    def setUp(self):
        self.hq = Branch.objects.create(softech_branch_id='100', code='100', name='HQ',
                                        kind=Branch.KIND_HQ)
        self.shop = Branch.objects.create(softech_branch_id='981', code='981', name='Shop',
                                          kind=Branch.KIND_RETAIL)

    def crew(self, extension, valid_from=date(2026, 1, 1), name='الكول سنتر'):
        c = Crew.objects.create(name=name, type='call_center')
        CrewManualMember.objects.create(crew=c, mode='include', pbx_extension=extension,
                                        valid_from=valid_from, reason='t')
        return c

    def employee(self, hr, exts, branch):
        e = Employee.objects.create(hr_number=hr, name_ar='م' + hr, pbx_extensions=exts,
                                    start_date=date(2025, 1, 1), branch=branch)
        record_assignment(e, on=date(2025, 1, 1), source='seed')
        return e

    def test_crew_extension_becomes_agent(self):
        ext('999')
        self.crew('999')
        res = classification.proposed_types(TODAY)
        self.assertEqual(res['999'], ('agent', 'crew:الكول سنتر'))
        changes = classification.classify(apply=True, today=TODAY)
        self.assertEqual(kind('999'), 'agent')
        self.assertEqual(changes, [{'extension': '999', 'old': 'other', 'new': 'agent',
                                    'source': 'crew:الكول سنتر'}])

    def test_employee_extension_by_assignment_branch(self):
        ext('901')
        ext('902')
        self.employee('7', ['901'], self.hq)
        self.employee('8', ['902'], self.shop)
        res = classification.proposed_types(TODAY)
        self.assertEqual(res['901'], ('hq', 'employee:7'))
        self.assertEqual(res['902'], ('branch', 'employee:8'))

    def test_confirmed_file_is_last_resort(self):
        ext('45')
        ext('10')
        self.assertEqual(classification.proposed_types(TODAY)['45'], ('hq', 'confirmed'))
        # an employee and a crew both outrank the file
        self.employee('9', ['45'], self.shop)
        self.crew('45')
        self.assertEqual(classification.proposed_types(TODAY)['45'], ('agent', 'crew:الكول سنتر'))
        self.assertEqual(classification.proposed_types(TODAY)['10'], ('agent', 'confirmed'))

    def test_employee_outranks_confirmed_file(self):
        self.employee('9', ['45'], self.shop)
        self.assertEqual(classification.proposed_types(TODAY)['45'], ('branch', 'employee:9'))

    def test_gateway_untouched(self):
        ext('10', 'gateway')
        self.crew('10')
        classification.classify(apply=True, today=TODAY)
        self.assertEqual(kind('10'), 'gateway')

    def test_archived_or_future_crew_ignored(self):
        ext('998')
        c = self.crew('998')
        c.is_archived = True
        c.save()
        self.assertNotIn('998', classification.proposed_types(TODAY))
        self.crew('997', valid_from=date(2027, 1, 1), name='آخر')
        self.assertNotIn('997', classification.proposed_types(TODAY))

    def test_dry_run_changes_nothing(self):
        ext('999')
        self.crew('999')
        changes = classification.classify(apply=False, today=TODAY)
        self.assertEqual(len(changes), 1)
        self.assertEqual(kind('999'), 'other')
        self.assertFalse(AuditLog.objects.filter(action='pbx_extensions_classified').exists())
        out = StringIO()
        call_command('classify_pbx_extensions', stdout=out)
        self.assertEqual(kind('999'), 'other')

    def test_apply_audited(self):
        ext('999')
        self.crew('999')
        call_command('classify_pbx_extensions', '--apply', stdout=StringIO())
        self.assertEqual(kind('999'), 'agent')
        log = AuditLog.objects.get(action='pbx_extensions_classified')
        self.assertEqual(log.new_data['changes'][0]['extension'], '999')

    def test_two_employees_on_one_extension_first_kept_and_reported(self):
        ext('903')
        self.employee('11', ['903'], self.hq)
        self.employee('12', ['903'], self.shop)
        conflicts = []
        res = classification.proposed_types(TODAY, conflicts)
        self.assertEqual(res['903'], ('hq', 'employee:11'))       # hr_number order: first kept
        self.assertEqual(conflicts, [{'extension': '903', 'kept': 'employee:11',
                                      'dropped': 'employee:12'}])
        out = StringIO()
        call_command('classify_pbx_extensions', stdout=out)
        self.assertIn('conflict ext=903', out.getvalue())
        self.assertIn('dropped employee:12', out.getvalue())

    def test_two_crews_on_one_extension_first_kept_and_reported(self):
        ext('904')
        self.crew('904', name='أ كول')
        self.crew('904', name='ب كول')
        found = []
        changes = classification.classify(apply=False, today=TODAY, conflicts=found)
        self.assertEqual(changes[0]['source'], 'crew:أ كول')
        self.assertEqual(found, [{'extension': '904', 'kept': 'crew:أ كول', 'dropped': 'crew:ب كول'}])

    def test_new_crew_extension_needs_no_code_change(self):
        ext('555')
        self.assertNotIn('555', classification.proposed_types(TODAY))
        self.crew('555')
        self.assertEqual(classification.proposed_types(TODAY)['555'][0], 'agent')
