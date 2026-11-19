"""
apps/tests/test_stock_audit_finding_tasks.py

C13 — a stock-audit finding becomes an assigned task + a targeted count of just its items; closing
the count closes the finding (matched) or leaves it open with the variance. One open task per
finding, branch scope, AuditLog rows, server-side refusal. Nothing here touches SOFTECH.
"""
from decimal import Decimal

from apps.audit.models import AuditLog
from apps.stock_audit.assignment import default_assignee
from apps.stock_audit.models import StockAuditFinding, StockAuditFindingTask
from apps.stockcount.models import StockCountSession, StockCountSnapshot
from apps.tasks.models import OperationalTask
from apps.tests.factories import make_user
from apps.tests.test_stock_audit_api import StockAuditApiBase, finding

CREATED = 'stock_audit_finding_task_created'
CLOSED = 'stock_audit_finding_task_closed'


def task_url(f):
    return f'/api/stock-audit/findings/{f.pk}/task/'


class FindingTaskBase(StockAuditApiBase):

    def make(self, f, client=None):
        return (client or self.sup).post(task_url(f), {}, format='json')

    def counted(self, session, code, expected, counted):
        diff = Decimal(counted) - Decimal(expected)
        StockCountSnapshot.objects.create(
            session=session, item_code=code, item_name=code, branch_code=session.branch_code,
            expected_qty=Decimal(expected), counted_qty=Decimal(counted), difference=diff,
            variance_type='ok' if diff == 0 else ('surplus' if diff > 0 else 'deficit'))

    def close(self, session):
        session.status = 'uploaded'
        session.save(update_fields=['status'])
        return self.admin.post(f'/api/stockcount/sessions/{session.pk}/close/')


class CreateTests(FindingTaskBase):

    def test_one_task_and_targeted_count_per_finding(self):
        r = self.make(self.f1)
        self.assertEqual(r.status_code, 201, r.content)
        link = StockAuditFindingTask.objects.get(finding=self.f1)
        task, session = link.task, link.count_session
        self.assertEqual((task.assigned_to, task.branch, task.related_model, task.related_id),
                         (self.ph_p, self.b1, 'stock_audit_finding', self.f1.pk))
        self.assertEqual((session.mode, session.branch_code, session.item_codes_filter, session.status),
                         ('filtered', 'B01', ['100001'], 'draft'))
        self.assertEqual(r.json()['finding']['task']['task_number'], task.task_number)
        again = self.make(self.f1)                                   # idempotent: the open task comes back
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(again.json()['existing']), 1)
        self.assertEqual(OperationalTask.objects.count(), 1)
        self.assertEqual(StockCountSession.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(action=CREATED).count(), 1)

    def test_evidence_items_join_the_count(self):
        self.f1.evidence = {'lines': [{'itemcode': '100001'}, {'itemcode': '200002'}]}
        self.f1.save(update_fields=['evidence'])
        self.make(self.f1)
        self.assertEqual(StockCountSession.objects.get().item_codes_filter, ['100001', '200002'])

    def test_closed_finding_is_refused(self):
        self.f1.status = StockAuditFinding.ST_DISMISSED
        self.f1.save(update_fields=['status'])
        self.assertEqual(self.make(self.f1).status_code, 400)
        self.assertFalse(OperationalTask.objects.exists())

    def test_cancelled_task_frees_the_finding(self):
        self.make(self.f1)
        OperationalTask.objects.update(status='cancelled')
        self.assertEqual(self.make(self.f1).status_code, 201)
        self.assertEqual(StockAuditFindingTask.objects.filter(finding=self.f1, status='open').count(), 1)
        self.assertEqual(StockAuditFindingTask.objects.get(finding=self.f1, status='closed').outcome, 'cancelled')

    def test_bulk_one_count_per_branch(self):
        f3 = finding('B01', n=3)
        f4 = finding('B01', n=4, status='dismissed')
        self.make(self.f1)                                           # already has a task
        r = self.sup.post('/api/stock-audit/findings/bulk-task/',
                          {'ids': [self.f1.pk, self.f2.pk, f3.pk, f4.pk]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(sorted(x['finding'] for x in body['created']), sorted([self.f2.pk, f3.pk]))
        self.assertEqual([x['finding'] for x in body['existing']], [self.f1.pk])
        self.assertEqual([x['id'] for x in body['skipped']], [f4.pk])
        self.assertEqual(OperationalTask.objects.count(), 3)
        self.assertEqual(StockCountSession.objects.count(), 3)       # f1's own + one per branch in the batch
        self.assertEqual(AuditLog.objects.filter(action=CREATED).count(), 3)


class AssigneeTests(FindingTaskBase):

    def test_named_branch_manager_first_then_pharmacist_then_nobody(self):
        _, other_p, _ = make_user('sa_ph2', role='pharmacist', branch=self.b1)
        self.assertEqual(default_assignee(self.f1), self.ph_p)       # lowest-id branch lead
        self.grant(other_p)
        self.assertEqual(default_assignee(self.f1), other_p)         # the named branch manager wins
        self.assertIsNone(default_assignee(self.f2))                 # nobody at B02


class ScopeAndPermissionTests(FindingTaskBase):

    def test_viewer_and_ungranted_pharmacist_refused(self):
        for c in (self.viewer, self.ph):
            self.assertEqual(self.make(self.f1, c).status_code, 403)
            r = c.post('/api/stock-audit/findings/bulk-task/', {'ids': [self.f1.pk]}, format='json')
            self.assertEqual(r.status_code, 403)
        self.assertFalse(OperationalTask.objects.exists())

    def test_branch_manager_own_branch_only(self):
        self.grant()
        self.assertEqual(self.make(self.f2, self.ph).status_code, 404)
        r = self.ph.post('/api/stock-audit/findings/bulk-task/', {'ids': [self.f1.pk, self.f2.pk]}, format='json')
        body = r.json()
        self.assertEqual([x['finding'] for x in body['created']], [self.f1.pk])
        self.assertEqual([x['id'] for x in body['skipped']], [self.f2.pk])
        self.assertFalse(StockCountSession.objects.filter(branch_code='B02').exists())


class CloseOnFinalizeTests(FindingTaskBase):

    def test_matching_count_closes_the_finding(self):
        self.make(self.f1)
        link = StockAuditFindingTask.objects.get()
        self.counted(link.count_session, '100001', '5', '5')
        r = self.close(link.count_session)
        self.assertEqual((r.status_code, r.json()['audit_findings_closed']), (200, 1))
        link.refresh_from_db()
        self.f1.refresh_from_db()
        self.assertEqual((link.status, link.outcome), ('closed', 'match'))
        self.assertEqual(self.f1.status, 'reviewed')
        self.assertIn('مطابق', self.f1.review_note)
        self.assertEqual(link.task.status, 'completed')
        log = AuditLog.objects.get(action=CLOSED)
        self.assertEqual(log.changes, {'status': ['open', 'reviewed']})

    def test_variance_keeps_the_finding_open(self):
        self.make(self.f1)
        link = StockAuditFindingTask.objects.get()
        self.counted(link.count_session, '100001', '5', '3')
        self.close(link.count_session)
        link.refresh_from_db()
        self.f1.refresh_from_db()
        self.assertEqual((link.status, link.outcome), ('closed', 'variance'))
        self.assertEqual(self.f1.status, 'open')
        self.assertIn('-2', self.f1.review_note)
        self.assertEqual(link.result['100001']['variance_type'], 'deficit')
        self.assertEqual(AuditLog.objects.filter(action=CLOSED).count(), 1)
        self.assertEqual(self.make(self.f1).status_code, 201)        # a recount can be ordered

    def test_uncounted_item_is_a_variance(self):
        self.make(self.f1)
        link = StockAuditFindingTask.objects.get()
        self.close(link.count_session)
        link.refresh_from_db()
        self.assertEqual((link.outcome, link.result['100001']['variance_type']), ('variance', 'not_counted'))

    def test_plain_count_close_untouched(self):
        s = StockCountSession.objects.create(name='جرد', branch_code='B01', status='variance_ready')
        r = self.admin.post(f'/api/stockcount/sessions/{s.pk}/close/')
        self.assertEqual((r.status_code, r.json()['audit_findings_closed']), (200, 0))
        self.assertFalse(AuditLog.objects.filter(action=CLOSED).exists())
