"""
Multi-select list filters on the tasks and reservations screens (core/multi_filter.py).

/tasks (status · priority · task_type · branch), /tasks/dashboard (branch), /reservations list and
board (status · priority · branch) and /reservations analytics (branch) take one value as before
or several as a comma list (?status=open,on_hold). Two values = the union, one value = as before,
nothing = every row the user may see. The filters run after branch scoping, so a branch user who
asks for a branch outside their scope still sees only their own rows.
"""
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.reservations.models import Reservation
from apps.tasks.models import OperationalTask
from apps.tests.factories import make_branch, make_branch2, make_item, make_user
from apps.tests.security.fixtures import seed_code_matrix
from core.middleware import module_access


def _rows(resp):
    data = resp.data
    return data.get('results', data) if hasattr(data, 'get') else data


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):
    def setUp(self):
        seed_code_matrix()
        self.b1 = make_branch('فرع م1', 'MS01')
        self.b2 = make_branch2('فرع م2', 'MS02')
        self.b3 = make_branch('فرع م3', 'MS03')
        _, self.admin, self.admin_c = make_user('ms_ops_admin', role='admin', access_all=True)
        _, self.pharm, self.pharm_c = make_user('ms_ops_pharm', role='pharmacist', branch=self.b1)

    def tearDown(self):
        module_access.clear_cache()


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TaskListMultiFilterTests(_Base):
    URL = '/api/tasks/'

    def setUp(self):
        super().setUp()
        self.t1 = self.task('t1', 'open', 'low', 'stock_count', self.b1)
        self.t2 = self.task('t2', 'on_hold', 'high', 'receiving', self.b2)
        self.t3 = self.task('t3', 'completed', 'urgent', 'delivery', self.b3)

    def task(self, title, st, pr, tp, br):
        return OperationalTask.objects.create(title=title, status=st, priority=pr, task_type=tp,
                                              branch=br, created_by=self.admin)

    def ids(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200, r.data)
        return {row['id'] for row in _rows(r)}

    def test_status_two_one_none(self):
        self.assertEqual(self.ids(status='open,on_hold'), {self.t1.id, self.t2.id})
        self.assertEqual(self.ids(status='open'), {self.t1.id})
        self.assertEqual(self.ids(), {self.t1.id, self.t2.id, self.t3.id})

    def test_status_repeated_param(self):
        r = self.admin_c.get(self.URL + '?status=open&status=completed')
        self.assertEqual({row['id'] for row in _rows(r)}, {self.t1.id, self.t3.id})

    def test_priority_two_one(self):
        self.assertEqual(self.ids(priority='low,urgent'), {self.t1.id, self.t3.id})
        self.assertEqual(self.ids(priority='high'), {self.t2.id})

    def test_task_type_two_one(self):
        self.assertEqual(self.ids(task_type='stock_count,receiving'), {self.t1.id, self.t2.id})
        self.assertEqual(self.ids(task_type='delivery'), {self.t3.id})

    def test_branch_two_one(self):
        self.assertEqual(self.ids(branch=f'{self.b1.id},{self.b3.id}'), {self.t1.id, self.t3.id})
        self.assertEqual(self.ids(branch=str(self.b2.id)), {self.t2.id})

    def test_branch_filter_never_widens_scope(self):
        # a branch-1 pharmacist asking for branches 1+2 still sees only branch 1
        self.assertEqual(self.ids(self.pharm_c, branch=f'{self.b1.id},{self.b2.id}'), {self.t1.id})
        self.assertEqual(self.ids(self.pharm_c, branch=str(self.b2.id)), set())


class TaskDashboardMultiBranchTests(_Base):
    URL = '/api/tasks/dashboard/'

    def setUp(self):
        super().setUp()
        for br in (self.b1, self.b2, self.b2, self.b3):
            OperationalTask.objects.create(title='d', status='open', branch=br, created_by=self.admin)

    def total(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200)
        return r.data['total_tasks']

    def test_branch_two_one_none(self):
        self.assertEqual(self.total(branch=f'{self.b1.id},{self.b2.id}'), 3)
        self.assertEqual(self.total(branch=str(self.b3.id)), 1)
        self.assertEqual(self.total(), 4)

    def test_branch_filter_never_widens_scope(self):
        self.assertEqual(self.total(self.pharm_c, branch=f'{self.b1.id},{self.b2.id}'), 1)


# ── Reservations ──────────────────────────────────────────────────────────────

class _ResBase(_Base):
    URL = '/api/reservations/'

    def setUp(self):
        super().setUp()
        self.item = make_item('باراسيتامول م', 'MSI1')

    def res(self, **kw):
        base = dict(item=self.item, branch=self.b1, quantity_requested=Decimal('1'),
                    contact_name='زبون', contact_phone='01000000009', created_by=self.admin)
        base.update(kw)
        return Reservation.objects.create(**base)


class ReservationListMultiFilterTests(_ResBase):

    def setUp(self):
        super().setUp()
        self.r1 = self.res(status='pending', priority='normal', branch=self.b1)
        self.r2 = self.res(status='available', priority='urgent', branch=self.b2)
        self.r3 = self.res(status='confirmed', priority='chronic', branch=self.b3)

    def ids(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, {'page_size': 500, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return {row['id'] for row in _rows(r)}

    def test_status_two_one_none(self):
        self.assertEqual(self.ids(status='pending,available'), {self.r1.id, self.r2.id})
        self.assertEqual(self.ids(status='confirmed'), {self.r3.id})
        self.assertEqual(self.ids(), {self.r1.id, self.r2.id, self.r3.id})

    def test_status_in_still_works(self):
        self.assertEqual(self.ids(status__in='pending,confirmed'), {self.r1.id, self.r3.id})

    def test_priority_two_one(self):
        self.assertEqual(self.ids(priority='urgent,chronic'), {self.r2.id, self.r3.id})
        self.assertEqual(self.ids(priority='normal'), {self.r1.id})

    def test_branch_two_one(self):
        self.assertEqual(self.ids(branch=f'{self.b1.id},{self.b2.id}'), {self.r1.id, self.r2.id})
        self.assertEqual(self.ids(branch=str(self.b3.id)), {self.r3.id})

    def test_branch_filter_never_widens_scope(self):
        self.assertEqual(self.ids(self.pharm_c, branch=f'{self.b1.id},{self.b2.id}'), {self.r1.id})


class ReservationAnalyticsMultiBranchTests(_ResBase):
    URL = '/api/reservations/analytics/'

    def setUp(self):
        super().setUp()
        self.res(branch=self.b1)
        self.res(branch=self.b2)
        self.res(branch=self.b2)
        self.res(branch=self.b3)

    def total(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200)
        return r.data['summary']['total']

    def test_branch_two_one_none(self):
        self.assertEqual(self.total(branch=f'{self.b2.id},{self.b3.id}'), 3)
        self.assertEqual(self.total(branch=str(self.b1.id)), 1)
        self.assertEqual(self.total(), 4)

    def test_branch_filter_never_widens_scope(self):
        self.assertEqual(self.total(self.pharm_c, branch=f'{self.b1.id},{self.b2.id}'), 1)
