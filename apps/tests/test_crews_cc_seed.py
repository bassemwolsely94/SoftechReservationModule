"""Crews piece 2b, Task 1: call-center crew seed, shadow rollups, one CC lookup."""
import pathlib
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.crews import cc_seed
from apps.crews.models import Crew, CrewKpiRollup, CrewManualMember
from apps.forecasting.call_center import legacy_cc_branch
from apps.forecasting.management.commands.build_call_center_rollups import get_cc_branch
from apps.forecasting.models import CallCenterConfig, KpiActualRollup
from apps.hr.models import Employee
from apps.pbx.models import AgentExtension


def cc_with_rollup(year=2024, month=8):
    cc = Branch.objects.create(softech_branch_id='CC', code='CC', name='Call Center',
                               is_operational=False, kind=Branch.KIND_CALL_CENTER)
    KpiActualRollup.objects.create(branch=cc, year=year, month=month, metric='call_count', value=5)
    return cc


class CcSeedTests(TestCase):
    def setUp(self):
        cfg = CallCenterConfig.get_solo()
        cfg.sales_agent_usercodes = ['62', '63', '64']
        cfg.call_agent_extensions = ['10', '12', '15']
        cfg.save()

    def test_seed_creates_crew_and_dated_rows(self):
        cc_with_rollup()
        res = cc_seed.seed()
        crew = Crew.objects.get(name=cc_seed.CC_CREW_NAME)
        self.assertEqual(crew.type, 'call_center')
        rows = crew.manual_members.all()
        self.assertEqual(rows.count(), 6)
        self.assertEqual(res['start'], date(2024, 8, 1))
        for r in rows:
            self.assertEqual((r.mode, r.valid_from, r.valid_to, r.reason),
                             ('include', date(2024, 8, 1), None, cc_seed.SEED_REASON))
        self.assertEqual({r.softech_usercode for r in rows} - {''}, {'62', '63', '64'})
        self.assertEqual({r.pbx_extension for r in rows} - {''}, {'10', '12', '15'})
        self.assertIn('مندوب 62', {r.label for r in rows})
        self.assertIn('داخلي 10', {r.label for r in rows})

    def test_seed_starts_this_month_without_rollups(self):
        self.assertEqual(cc_seed.seed_start(), timezone.localdate().replace(day=1))

    def test_seed_links_employee_by_usercode_and_extension(self):
        cc_with_rollup()
        e1 = Employee.objects.create(hr_number='1', name_ar='أ', softech_usercode='62',
                                     start_date=date(2024, 1, 1))
        e2 = Employee.objects.create(hr_number='2', name_ar='ب', pbx_extensions=['12'],
                                     start_date=date(2024, 1, 1))
        cc_seed.seed()
        crew = Crew.objects.get(name=cc_seed.CC_CREW_NAME)
        self.assertEqual(crew.manual_members.get(softech_usercode='62').employee_id, e1.pk)
        self.assertEqual(crew.manual_members.get(pbx_extension='12').employee_id, e2.pk)
        self.assertIsNone(crew.manual_members.get(softech_usercode='63').employee_id)

    def test_seed_idempotent_and_reseed_replaces(self):
        cc_with_rollup()
        cc_seed.seed()
        res = cc_seed.seed()
        self.assertEqual((len(res['created']), len(res['skipped'])), (0, 6))
        self.assertEqual(CrewManualMember.objects.count(), 6)
        crew = Crew.objects.get(name=cc_seed.CC_CREW_NAME)
        CrewKpiRollup.objects.create(crew=crew, year=2024, month=8, metric='call_count',
                                     value=Decimal('1'))
        cc_seed.reseed()
        self.assertEqual(CrewManualMember.objects.count(), 6)
        self.assertEqual(CrewKpiRollup.objects.count(), 0)
        self.assertEqual(Crew.objects.filter(name=cc_seed.CC_CREW_NAME).count(), 1)

    def test_dry_run_writes_nothing(self):
        res = cc_seed.seed(dry_run=True)
        self.assertEqual(len(res['created']), 6)
        self.assertFalse(Crew.objects.exists())

    def test_extra_pbx_agent_extensions_opt_in(self):
        for ext, t in [('10', 'agent'), ('11', 'agent'), ('13', 'agent'), ('9', 'agent'),
                       ('20', 'branch')]:
            AgentExtension.objects.create(extension=ext, extension_type=t)
        AgentExtension.objects.create(extension='14', extension_type='agent', is_active=False)
        self.assertEqual(cc_seed.extra_pbx_agent_extensions(), ['9', '11', '13'])
        self.assertEqual(len(cc_seed.seed_plan()), 6)
        self.assertEqual(len(cc_seed.seed_plan(include_pbx_agent_extensions=True)), 9)

    def test_seed_audited(self):
        cc_with_rollup()
        cc_seed.seed()
        crew = Crew.objects.get(name=cc_seed.CC_CREW_NAME)
        self.assertTrue(AuditLog.objects.filter(action='crew_cc_seeded',
                                                object_id=str(crew.pk)).exists())
        cc_seed.reseed()
        self.assertTrue(AuditLog.objects.filter(action='crew_cc_reseeded').exists())

    def test_has_history_true_with_rollups(self):
        crew = Crew.objects.create(name='ط', type='custom')
        self.assertFalse(crew.has_history())
        CrewKpiRollup.objects.create(crew=crew, year=2026, month=11, metric='x', value=1)
        self.assertTrue(crew.has_history())

    def test_get_cc_branch_creates_call_center_kind(self):
        b = get_cc_branch()
        self.assertEqual(b.kind, Branch.KIND_CALL_CENTER)
        self.assertEqual(legacy_cc_branch().pk, b.pk)

    def test_legacy_cc_branch_helper_used_everywhere(self):
        root = pathlib.Path(__file__).resolve().parents[1] / 'forecasting'
        for name in ('views.py', 'references.py', 'kpi_export.py', 'engine.py', 'rollup_refresh.py'):
            src = (root / name).read_text(encoding='utf-8')
            self.assertNotIn("softech_branch_id='CC'", src, name)
            self.assertIn('legacy_cc_branch', src, name)
