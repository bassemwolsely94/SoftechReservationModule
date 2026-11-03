"""
apps/tests/test_sort_s5_ordering.py

Sortable-grid sweep (batch S5, operations screens): the paged / server-cut lists take a whitelisted `ordering`,
so the headers sort ALL rows on the server. Every view has real rows (an empty table skips the ordered query,
so a bad field path would still answer 200), every whitelisted field is requested ascending and descending
(must be HTTP 200), and each view has one ordering assertion. Equal sort values page without repeats or gaps.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from .factories import make_admin, make_branch, make_branch2, make_item


class _Base(TestCase):
    def setUp(self):
        self.user, self.profile, self.client = make_admin('sort_s5')
        self.b1 = make_branch('أ فرع', 'S501')
        self.b2 = make_branch2('ب فرع', 'S502')

    def every_field(self, url, fields):
        for f in fields:
            for o in (f, '-' + f):
                r = self.client.get(url, {'ordering': o})
                self.assertEqual(r.status_code, 200, '%s ?ordering=%s -> %s' % (url, o, r.status_code))

    def results(self, url, ordering, key):
        r = self.client.get(url, {'ordering': ordering})
        self.assertEqual(r.status_code, 200)
        data = r.data.get('results', r.data) if hasattr(r.data, 'get') else r.data
        return [row[key] for row in data]


class ReservationOrderingTests(_Base):
    FIELDS = ['id', 'customer_sort', 'item_sort', 'branch__name', 'status_rank', 'priority_rank',
              'follow_up_date', 'created_at']

    def setUp(self):
        super().setUp()
        from apps.reservations.models import Reservation
        item = make_item(softech_id='S5-R1', name='ج صنف')
        for name, phone, status, prio, br in (('ج', '01000000001', 'fulfilled', 'urgent', self.b1),
                                              ('أ', '01000000002', 'pending', 'normal', self.b2),
                                              ('ب', '01000000003', 'confirmed', 'chronic', self.b1)):
            Reservation.objects.create(item=item, branch=br, quantity_requested=1, contact_name=name,
                                       contact_phone=phone, status=status, priority=prio, created_by=self.profile)

    def test_every_whitelisted_field_answers_200(self):
        self.every_field('/api/reservations/', self.FIELDS)

    def test_customer_status_and_priority_order_by_what_the_cell_shows(self):
        url = '/api/reservations/'
        self.assertEqual(self.results(url, 'customer_sort', 'contact_name'), ['أ', 'ب', 'ج'])
        self.assertEqual(self.results(url, '-customer_sort', 'contact_name'), ['ج', 'ب', 'أ'])
        # lifecycle rank, not the alphabetical order of the stored codes
        self.assertEqual(self.results(url, 'status_rank', 'status'), ['pending', 'confirmed', 'fulfilled'])
        self.assertEqual(self.results(url, '-priority_rank', 'priority'), ['chronic', 'urgent', 'normal'])

    def test_ties_page_without_repeats(self):
        from apps.reservations.models import Reservation
        for i in range(60):
            Reservation.objects.create(item=Reservation.objects.first().item, branch=self.b1, quantity_requested=1,
                                       contact_name='س', contact_phone='0100001%04d' % i, created_by=self.profile)
        seen = []
        for page in (1, 2):
            r = self.client.get('/api/reservations/', {'ordering': 'status_rank', 'page': page})
            seen += [x['id'] for x in r.data['results']]
        self.assertEqual(len(seen), len(set(seen)))


class TransferOrderingTests(_Base):
    FIELDS = ['request_number', 'requesting_sort', 'supplying_sort', 'items_count', 'status_rank',
              'created_by_sort', 'notes', 'created_at']

    def setUp(self):
        super().setUp()
        from apps.transfers.models import TransferRequest, TransferRequestItem
        item = make_item(softech_id='S5-T1', name='صنف تحويل')
        for status, n, req, sup in (('pending', 3, self.b2, self.b1), ('draft', 1, self.b1, None),
                                    ('approved', 2, self.b1, self.b2)):
            tr = TransferRequest.objects.create(requesting_branch=req, supplying_branch=sup, status=status,
                                                created_by=self.profile, notes='ن%s' % n)
            for i in range(n):
                TransferRequestItem.objects.create(request=tr, item=make_item(softech_id='S5-T%s%s' % (n, i), name='ص'),
                                                   quantity=1)

    def test_every_whitelisted_field_answers_200(self):
        self.every_field('/api/transfers/', self.FIELDS)

    def test_items_count_status_rank_and_null_branch_last(self):
        url = '/api/transfers/'
        self.assertEqual(self.results(url, 'items_count', 'total_items'), [1, 2, 3])
        self.assertEqual(self.results(url, '-items_count', 'total_items'), [3, 2, 1])
        self.assertEqual(self.results(url, 'status_rank', 'status'), ['draft', 'pending', 'approved'])
        # the draft has no supplying branch -> last in BOTH directions
        for o in ('supplying_sort', '-supplying_sort'):
            self.assertEqual(self.results(url, o, 'status')[-1], 'draft')

    def test_discrepancy_report_orders_before_the_cut(self):
        from apps.transfers.models import TransferRequest, TransferRequestItem
        tr = TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2, status='completed',
                                            created_by=self.profile, completed_at=timezone.now())
        for code, appr, rec in (('D1', 10, 9), ('D2', 10, 2), ('D3', 10, 5)):
            TransferRequestItem.objects.create(request=tr, item=make_item(softech_id='S5-' + code, name=code),
                                               quantity=10, approved_quantity=appr, received_quantity=rec)
        url = '/api/transfers/discrepancy-report/'
        self.every_field(url, ['request_number', 'item_name', 'supplying_branch', 'approved_quantity',
                               'received_quantity', 'discrepancy', 'completed_at'])
        r = self.client.get(url, {'ordering': '-discrepancy'})
        self.assertEqual([x['item_name'] for x in r.data['discrepancies']], ['D2', 'D3', 'D1'])
        self.assertEqual(self.client.get(url, {'ordering': 'nope'}).status_code, 400)


class DemandOrderingTests(_Base):
    FIELDS = ['demand_number', 'customer_name', 'branch_sort', 'items_count', 'status_rank', 'priority_rank',
              'sla_sort', 'assignee_sort']

    def setUp(self):
        super().setUp()
        from apps.demand.models import DemandItem, DemandRecord
        item = make_item(softech_id='S5-D1', name='صنف طلب')
        self.recs = []
        for name, st, pr, n in (('ج', 'new', 'urgent', 2), ('أ', 'assigned', 'normal', 1), ('ب', 'fulfilled', 'high', 3)):
            d = DemandRecord.objects.create(phone='0100000000%d' % n, customer_name=name, branch=self.b1, status=st,
                                            priority=pr, assigned_to=self.profile if st == 'assigned' else None,
                                            assigned_at=timezone.now() if st == 'assigned' else None)
            for _ in range(n):
                DemandItem.objects.create(demand=d, item=item, quantity=Decimal('1'), item_status='available_again')
            self.recs.append(d)

    def test_every_whitelisted_field_answers_200(self):
        self.every_field('/api/demand/', self.FIELDS)

    def test_orders_and_sla_without_deadline_last(self):
        url = '/api/demand/'
        self.assertEqual(self.results(url, 'customer_name', 'customer_name'), ['أ', 'ب', 'ج'])
        self.assertEqual(self.results(url, 'items_count', 'total_items'), [1, 2, 3])
        # fulfilled has no SLA -> NULL deadline -> last in both directions
        for o in ('sla_sort', '-sla_sort'):
            self.assertEqual(self.results(url, o, 'status')[-1], 'fulfilled')

    def test_recovery_queue_orders_all_fields(self):
        url = '/api/demand/recovery-queue/'
        self.assertTrue(self.client.get(url).data['results'])
        self.every_field(url, ['customer_name', 'item', 'branch', 'stock', 'value', 'waiting'])
        self.assertEqual(self.client.get(url, {'ordering': 'nope'}).status_code, 400)
        names = [r['customer_name'] for r in self.client.get(url, {'ordering': 'customer_name'}).data['results']]
        self.assertEqual(names, sorted(names))


class TaskOrderingTests(_Base):
    def setUp(self):
        super().setUp()
        from apps.tasks.models import OperationalTask, TaskSchedule
        for title, st, pr, tp in (('ج', 'completed', 'critical', 'delivery'), ('أ', 'open', 'low', 'stock_count'),
                                  ('ب', 'in_progress', 'high', 'receiving')):
            OperationalTask.objects.create(title=title, status=st, priority=pr, task_type=tp, branch=self.b1,
                                           created_by=self.profile, assigned_to=self.profile if st == 'open' else None)
        for name, fr in (('ج', 'monthly'), ('أ', 'daily'), ('ب', 'weekly')):
            TaskSchedule.objects.create(name=name, frequency=fr, title_template='t', created_by=self.profile,
                                        branch=None if name == 'أ' else self.b1)

    def test_every_whitelisted_task_field_answers_200(self):
        self.every_field('/api/tasks/', ['task_number', 'title', 'status', 'priority', 'task_type', 'branch',
                                         'assigned_to', 'due_date', 'created_at', 'updated_at'])

    def test_task_orders_by_rank_and_unknown_falls_back_to_default(self):
        url = '/api/tasks/'
        self.assertEqual(self.results(url, 'title', 'title'), ['أ', 'ب', 'ج'])
        self.assertEqual(self.results(url, 'status', 'status'), ['open', 'in_progress', 'completed'])
        self.assertEqual(self.results(url, '-priority', 'priority'), ['critical', 'high', 'low'])
        self.assertEqual(self.client.get(url, {'ordering': 'bogus'}).status_code, 200)
        self.assertEqual(self.client.get(url, {'ordering': 'title', 'mine': '1'}).status_code, 200)

    def test_schedules_every_field_and_order(self):
        url = '/api/tasks/schedules/'
        self.every_field(url, ['name', 'frequency', 'branch', 'assign_to', 'generated_count', 'last_run_at', 'is_active'])
        self.assertEqual(self.results(url, 'frequency', 'frequency'), ['daily', 'weekly', 'monthly'])
        # the all-branches schedule (NULL branch) is last in both directions
        for o in ('branch', '-branch'):
            self.assertEqual(self.results(url, o, 'name')[-1], 'أ')


class ApprovalOrderingTests(_Base):
    def setUp(self):
        super().setUp()
        from apps.approvals.models import ApprovalRequest, ApprovalWorkflowDefinition
        wf = ApprovalWorkflowDefinition.objects.create(code='s5wf', name='x', name_ar='ب مسار')
        for title, st in (('ج', 'approved'), ('أ', 'pending'), ('ب', 'rejected')):
            ApprovalRequest.objects.create(workflow=wf, requested_by=self.profile, title=title, status=st)

    def test_every_field_and_status_rank(self):
        url = '/api/approvals/requests/'
        self.every_field(url, ['title', 'workflow__name_ar', 'requested_by_sort', 'status_rank', 'requested_at'])
        self.assertEqual(self.results(url, 'title', 'title'), ['أ', 'ب', 'ج'])
        self.assertEqual(self.results(url, 'status_rank', 'status'), ['pending', 'approved', 'rejected'])
        self.assertEqual(self.client.get(url).status_code, 200)       # default (newest first) untouched


class HrOrderingTests(_Base):
    def setUp(self):
        super().setUp()
        from apps.hr.models import (ExpenseClaim, LeaveRequest, LeaveType, OvertimeRequest, Permit,
                                    SalaryAdvance)
        lt = LeaveType.objects.create(code='s5lt', name='x', name_ar='ب إجازة')
        today = date.today()
        for i, st in enumerate(('approved', 'draft', 'rejected')):
            who = dict(staff=self.profile, employee_hr_code='HR%d' % (3 - i), employee_name='م%d' % (3 - i))
            LeaveRequest.objects.create(leave_type=lt, start_date=today + timedelta(days=3 - i),
                                        end_date=today + timedelta(days=5), days_requested=Decimal(3 - i),
                                        status=st, **who)
            OvertimeRequest.objects.create(branch=self.b1, date=today + timedelta(days=3 - i),
                                           hours=Decimal(3 - i), reason='r', status=st, **who)
            SalaryAdvance.objects.create(amount=Decimal(100 * (3 - i)), repayment_date=today, reason='س%d' % (3 - i),
                                         status=st, **who)
            ExpenseClaim.objects.create(branch=self.b1, category='meal' if i else 'transport',
                                        expense_date=today, amount=Decimal(10 * (3 - i)),
                                        description='و%d' % (3 - i), status=st, **who)
            Permit.objects.create(branch=self.b1, permit_type=Permit.TYPE_CHOICES[i % len(Permit.TYPE_CHOICES)][0],
                                  date=today, time_from=time(9 + i), destination='ج%d' % (3 - i), status=st, **who)

    def test_every_whitelisted_field_on_every_hr_list(self):
        self.every_field('/api/hr/leave-requests/', ['staff_sort', 'code_sort', 'leave_type__name_ar', 'start_date',
                                                      'end_date', 'days_requested', 'status_rank', 'created_at'])
        self.every_field('/api/hr/overtime/', ['staff_sort', 'code_sort', 'date', 'hours', 'status_rank', 'created_at'])
        self.every_field('/api/hr/salary-advances/', ['staff_sort', 'amount', 'repayment_date', 'reason',
                                                       'status_rank', 'created_at'])
        self.every_field('/api/hr/expense-claims/', ['staff_sort', 'amount', 'category_sort', 'description',
                                                      'status_rank', 'created_at'])
        self.every_field('/api/hr/permits/', ['staff_sort', 'code_sort', 'type_sort', 'date', 'time_from',
                                               'destination', 'status_rank', 'created_at'])

    def test_orders(self):
        self.assertEqual(self.results('/api/hr/leave-requests/', 'days_requested', 'status'),
                         ['rejected', 'draft', 'approved'])
        self.assertEqual(self.results('/api/hr/salary-advances/', 'amount', 'reason'), ['س1', 'س2', 'س3'])
        # «employee name, else the staff member» is what the advance grid shows -> it is the sort key
        self.assertEqual(self.results('/api/hr/salary-advances/', '-staff_sort', 'reason'), ['س3', 'س2', 'س1'])
        self.assertEqual(self.results('/api/hr/permits/', '-destination', 'destination'), ['ج3', 'ج2', 'ج1'])


class ReplacementOrderingTests(_Base):
    def setUp(self):
        super().setUp()
        from apps.replacement.models import ReplacementCase as RC
        for n, name, st, ent, conf in ((1, 'ج', RC.STATUS_DRAFT, '30', 'low'), (2, 'أ', RC.STATUS_CALCULATED, '10', 'high'),
                                       (3, 'ب', RC.STATUS_UNCLAIMED, '20', '')):
            RC.objects.create(number='S5-%d' % n, source_type=RC.SOURCE_INSURANCE_RX, status=st, branch=self.b1,
                              branchcode=self.b1.softech_branch_id, patient_name=name, entitlement=Decimal(ent),
                              link_confidence=conf, purchase_date=date(2026, 1, n))

    def test_every_field_and_order(self):
        url = '/api/replacement/cases/'
        keys = ['purchase_date', 'entitlement', 'outstanding', 'open_exceptions', 'number', 'patient_name', 'branch',
                'supplier_personcode', 'redeemed_products', 'redeemed_cash', 'redeemed_unclassified', 'status',
                'link_confidence']
        self.every_field(url, keys)
        self.assertEqual(self.results(url, 'patient_name', 'patient_name'), ['أ', 'ب', 'ج'])
        self.assertEqual(self.results(url, '-entitlement', 'number'), ['S5-1', 'S5-3', 'S5-2'])
        # unknown field -> default order, never an error
        self.assertEqual(self.client.get(url, {'ordering': 'bogus'}).status_code, 200)
