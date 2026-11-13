"""
apps/tests/test_crews_api.py

Crews piece 2a, Task 3: the /api/crews/ API, RBAC module `crews` (view / edit, admin only by
default), audit of every change, and the «بائع غير محدد» share (spec 2026-11-13 §6.5, §6.8, §10).
"""
import importlib
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.crews.models import Crew, CrewManualMember, CrewRule
from apps.customers.models import PurchaseHistory
from apps.hr.assignments import record_assignment
from apps.hr.models import Employee
from apps.tests.factories import make_anon_client, make_branch, make_customer, make_user
from apps.users.models import ERPUser, RoleModuleAccess

MONTH_LOCKED = 'لا يمكن تطبيق تغيير قبل أول الشهر الحالي — الشهور السابقة مقفلة.'


def emp(hr, job, branch, *, usercode='', start=date(2025, 1, 1)):
    e = Employee.objects.create(hr_number=hr, name_ar=f'موظف {hr}', job_title=job, branch=branch,
                                start_date=start, softech_usercode=usercode)
    record_assignment(e, on=start, source='seed')
    return e


class CrewsApiBase(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.month_start = self.today.replace(day=1)
        self.b1 = make_branch('فرع 130', '130')
        _, self.admin, self.client = make_user('crew_admin', role='admin', branch=self.b1)
        self.e1 = emp('E1', 'صيدلي', self.b1)

    def crew(self, name='صيادلة 130', type_='job'):
        r = self.client.post('/api/crews/', {'name': name, 'type': type_}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()['id']


class CrewsApiTests(CrewsApiBase):
    def test_admin_full_flow(self):
        cid = self.crew()
        r = self.client.post(f'/api/crews/{cid}/rules/', {
            'job_titles': ['صيدلي'], 'branch_ids': [self.b1.id], 'valid_from': str(self.month_start)},
            format='json')
        self.assertEqual(r.status_code, 201, r.content)

        r = self.client.post('/api/crews/preview/', {'rules': [{'job_titles': ['صيدلي']}],
                                                     'date': str(self.today)}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([m['employee_id'] for m in r.json()], [self.e1.id])

        r = self.client.get(f'/api/crews/{cid}/members/?date={self.today}')
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'موظف E1')
        self.assertEqual(rows[0]['branch_label'], 'فرع 130')
        self.assertFalse(rows[0]['off_payroll'])

        r = self.client.get(f'/api/crews/{cid}/history/')
        self.assertEqual(r.status_code, 200)
        actions = {c['action'] for c in r.json()['changes']}
        self.assertTrue({'crew_created', 'crew_rule_added'} <= actions, actions)
        self.assertEqual([s['key'] for s in r.json()['spans']], [f'emp:{self.e1.id}'])

        r = self.client.get('/api/crews/')
        row = next(x for x in r.json() if x['id'] == cid)
        self.assertEqual(row['member_count'], 1)
        self.assertEqual(row['type_label'], 'وظيفي')
        self.assertIsNotNone(row['last_change'])

        detail = self.client.get(f'/api/crews/{cid}/').json()
        self.assertEqual(detail['rules'][0]['status'], 'active')
        self.assertEqual(detail['rules'][0]['branch_labels'], ['فرع 130'])

    def test_pharmacist_and_supervisor_refused_view_and_edit(self):
        for role in ('pharmacist', 'supervisor'):
            _, _, client = make_user(f'crew_{role}', role=role, branch=self.b1)
            with self.subTest(role=role):
                self.assertEqual(client.get('/api/crews/').status_code, 403)
                self.assertEqual(client.post('/api/crews/', {'name': 'x', 'type': 'custom'},
                                             format='json').status_code, 403)
                self.assertEqual(client.get('/api/crews/options/').status_code, 403)
                self.assertEqual(client.get('/api/crews/unattributed-sales/').status_code, 403)

    def test_anonymous_401(self):
        self.assertEqual(make_anon_client().get('/api/crews/').status_code, 401)

    def test_role_granted_view_only_cannot_edit(self):
        RoleModuleAccess.objects.update_or_create(role='supervisor', module='crews', action='view',
                                                  defaults={'is_allowed': True})
        _, _, client = make_user('crew_sup', role='supervisor', branch=self.b1)
        self.assertEqual(client.get('/api/crews/').status_code, 200)
        self.assertEqual(client.post('/api/crews/', {'name': 'x', 'type': 'custom'},
                                     format='json').status_code, 403)
        self.assertEqual(client.put('/api/crews/unattributed-sales/config/', {'groups': []},
                                    format='json').status_code, 403)

    def test_effective_date_before_month_start_refused(self):
        cid = self.crew()
        r = self.client.post(f'/api/crews/{cid}/rules/', {
            'job_titles': ['صيدلي'], 'valid_from': str(self.month_start - timedelta(days=1))},
            format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn(MONTH_LOCKED, r.content.decode())
        self.assertFalse(CrewRule.objects.filter(crew_id=cid).exists())

    def test_end_rule_sets_previous_day_and_future_row_voided(self):
        cid = self.crew()
        old = CrewRule.objects.create(crew_id=cid, job_titles=['صيدلي'], valid_from=date(2025, 1, 1))
        r = self.client.post(f'/api/crews/{cid}/rules/{old.id}/end/', {'on': str(self.today)}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        old.refresh_from_db()
        self.assertEqual(old.valid_to, self.today - timedelta(days=1))
        self.assertIsNone(old.voided_at)
        self.assertEqual(old.ended_by, self.admin)

        r = self.client.post(f'/api/crews/{cid}/rules/', {
            'job_titles': ['صيدلي'], 'valid_from': str(self.today + timedelta(days=10))}, format='json')
        future = CrewRule.objects.get(pk=r.json()['id'])
        r = self.client.post(f'/api/crews/{cid}/rules/{future.id}/end/', {'on': str(self.today)}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        future.refresh_from_db()
        self.assertIsNotNone(future.voided_at)
        self.assertIsNone(future.valid_to)
        self.assertEqual(r.json()['status'], 'voided')
        self.assertTrue(AuditLog.objects.filter(action='crew_rule_voided', object_id=str(cid)).exists())
        self.assertTrue(AuditLog.objects.filter(action='crew_rule_ended', object_id=str(cid)).exists())

    def test_replace_rule_ends_old_and_starts_new_on_the_day(self):
        cid = self.crew()
        old = CrewRule.objects.create(crew_id=cid, job_titles=['صيدلي'], valid_from=date(2025, 1, 1))
        r = self.client.post(f'/api/crews/{cid}/rules/{old.id}/replace/', {
            'job_titles': ['مساعد'], 'on': str(self.today)}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        old.refresh_from_db()
        self.assertEqual(old.valid_to, self.today - timedelta(days=1))
        new = CrewRule.objects.get(pk=r.json()['id'])
        self.assertEqual((new.valid_from, new.job_titles), (self.today, ['مساعد']))
        self.assertTrue(AuditLog.objects.filter(action='crew_rule_replaced', object_id=str(cid)).exists())

    def test_delete_unused_crew_deletes_used_crew_archives(self):
        unused = self.crew('طاقم فارغ', 'custom')
        r = self.client.delete(f'/api/crews/{unused}/')
        self.assertEqual(r.json(), {'result': 'deleted'})
        self.assertFalse(Crew.objects.filter(pk=unused).exists())
        self.assertTrue(AuditLog.objects.filter(action='crew_deleted', object_id=str(unused)).exists())

        used = self.crew('طاقم مستخدم', 'custom')
        CrewRule.objects.create(crew_id=used, job_titles=['صيدلي'],
                                valid_from=self.today - timedelta(days=1))
        r = self.client.delete(f'/api/crews/{used}/')
        self.assertEqual(r.json(), {'result': 'archived'})
        self.assertTrue(Crew.objects.get(pk=used).is_archived)
        self.assertNotIn(used, [x['id'] for x in self.client.get('/api/crews/').json()])
        self.assertIn(used, [x['id'] for x in self.client.get('/api/crews/?archived=1').json()])

        again = self.crew('طاقم مستخدم', 'custom')        # the name is free for a live crew
        self.assertNotEqual(again, used)
        r = self.client.post(f'/api/crews/{used}/unarchive/')
        self.assertEqual(r.status_code, 400)                  # a live crew holds the name now

    def test_manual_usercode_matching_employee_stores_fk(self):
        e2 = emp('E2', 'كاشير', self.b1, usercode='777')
        cid = self.crew()
        r = self.client.post(f'/api/crews/{cid}/manual/', {
            'mode': 'include', 'softech_usercode': '777', 'reason': 'وكيل', 'valid_from': str(self.today)},
            format='json')
        self.assertEqual(r.status_code, 201, r.content)
        row = CrewManualMember.objects.get(pk=r.json()['id'])
        self.assertEqual(row.employee_id, e2.id)
        self.assertFalse(r.json()['off_payroll'])

        r = self.client.post(f'/api/crews/{cid}/manual/', {
            'mode': 'include', 'softech_usercode': '9001', 'label': 'وكيل خارجي', 'reason': 'خارج الكشف',
            'valid_from': str(self.today)}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.json()['off_payroll'])
        self.assertTrue(AuditLog.objects.filter(action='crew_member_added', object_id=str(cid)).count() == 2)

    def test_options_lists_new_job_title_and_live_branches_only(self):
        emp('E3', 'منسق مبيعات جديد', self.b1)
        closed = Branch.objects.create(softech_branch_id='999', name='مغلق', name_ar='فرع مغلق', kind='closed')
        r = self.client.get('/api/crews/options/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('منسق مبيعات جديد', data['job_titles'])
        ids = {b['id'] for b in data['branches']}
        self.assertIn(self.b1.id, ids)
        self.assertNotIn(closed.id, ids)
        self.assertTrue(all(b['label'] for b in data['branches']))
        self.assertIn(self.e1.id, {e['id'] for e in data['employees']})


class UnattributedSalesTests(CrewsApiBase):
    def setUp(self):
        super().setUp()
        self.b2 = make_branch('فرع 140', '140')
        ERPUser.objects.create(username='C17', full_name='cashir 2 130', user_group='17')
        ERPUser.objects.create(username='S1', full_name='بائع أول', user_group='5')
        customer = make_customer()
        now = timezone.now()
        for i, (seller, amount, doc) in enumerate([('', '100', '115'), ('C17', '50', '115'),
                                                    ('S1', '250', '115'), ('', '999', '30')]):
            PurchaseHistory.objects.create(customer=customer, softech_invoice_id=f'INV{i}', branch=self.b1,
                                           doc_code=doc, total_amount=Decimal(amount), invoice_date=now,
                                           softech_user=seller)

    def _report(self):
        r = self.client.get(f'/api/crews/unattributed-sales/?start={self.today}&end={self.today}')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_unattributed_sales_share(self):
        data = self._report()
        rows = {b['branch_id']: b for b in data['branches']}
        b1 = rows[self.b1.id]
        self.assertEqual((b1['invoices'], b1['amount']), (3, 400.0))
        self.assertEqual((b1['unattributed_invoices'], b1['unattributed_amount']), (2, 150.0))
        self.assertAlmostEqual(b1['share'], 0.375)
        self.assertEqual(b1['label'], 'فرع 130')
        self.assertEqual(rows[self.b2.id]['share'], 0)
        sellers = {s['code']: s for s in data['sellers']}
        self.assertTrue(sellers['C17']['generic'])
        self.assertFalse(sellers['S1']['generic'])
        self.assertEqual(sellers['S1']['name'], 'بائع أول')
        self.assertEqual(data['rule'], {'groups': ['17'], 'usercodes': []})

    def test_generic_config_put_audited_and_used(self):
        r = self.client.put('/api/crews/unattributed-sales/config/', {'groups': ['17'], 'usercodes': ['S1']},
                            format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.client.get('/api/crews/unattributed-sales/config/').json()['rule'],
                         {'groups': ['17'], 'usercodes': ['S1']})
        log = AuditLog.objects.get(action='crew_generic_sellers_set')
        self.assertEqual(log.new_data, {'groups': ['17'], 'usercodes': ['S1']})
        self.assertEqual(log.old_data, {'groups': ['17'], 'usercodes': []})
        b1 = next(b for b in self._report()['branches'] if b['branch_id'] == self.b1.id)
        self.assertEqual(b1['unattributed_amount'], 400.0)
        self.assertEqual(b1['share'], 1.0)


class CrewsModuleRegistrationTests(TestCase):
    def test_module_mapped_and_matrix_migration_agree(self):
        from apps.users.management.commands.seed_permissions import ALL_MODULES, PERMISSIONS
        from core.middleware.module_access import MODULE_BY_PREFIX, required
        self.assertEqual(MODULE_BY_PREFIX['crews'], 'crews')
        self.assertIn('crews', ALL_MODULES)
        self.assertEqual({r for r, mods in PERMISSIONS.items() if r != 'admin' and mods.get('crews')}, set())
        mig = importlib.import_module('apps.users.migrations.0057_crews_module')
        self.assertEqual(mig.GRANTS, {'admin': set(mig.ACTIONS)})
        # the module has only view / edit: every write (DELETE included) asks `edit`, as the views do
        self.assertEqual(required('/api/crews/3/', 'DELETE'), ('crews', ('edit',)))
        self.assertEqual(required('/api/crews/', 'GET'), ('crews', ('view',)))
