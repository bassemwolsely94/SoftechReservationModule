"""
Multi-select list filters on follow-ups, call lists, call-center calls and delivery
(core/multi_filter.py): two values = union, one value = as before, nothing = no filter.
Filters narrow the user's branch scope; they never widen it.
"""
from datetime import date

from django.test import TestCase
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.customers.models import Customer
from apps.delivery.models import DeliveryCSAT, DeliveryDriver, DeliveryOrder
from apps.followups.models import FollowUpTask
from .factories import make_admin, make_branch, make_branch2, make_customer, make_item, make_pharmacist


def _rows(resp):
    data = resp.data
    return data.get('results', data) if isinstance(data, dict) else data


def _ids(resp):
    return {r['id'] for r in _rows(resp)}


class FollowUpTaskMultiFilterTests(TestCase):
    URL = '/api/followups/tasks/'

    def setUp(self):
        _, _, self.client_ = make_admin('msf_admin')
        self.b1, self.b2 = make_branch(), make_branch2()
        self.b3 = make_branch('فرع ثالث', 'B03')
        items = []
        for i, (mt, eff) in enumerate([('01', 'ضغط الدم'), ('02', 'السكر'), ('03', 'القلب')]):
            it = make_item(f'صنف {i}', f'MS{i:03d}')
            it.medicine_type, it.effect_name_ar = mt, eff
            it.save()
            items.append(it)
        segs = [('vip', 'low'), ('loyal', 'medium'), ('at_risk', 'high')]
        self.tasks = []
        for i, (branch, item, (seg, churn)) in enumerate(zip((self.b1, self.b2, self.b3), items, segs)):
            c = make_customer(f'عميل {i}', f'0105550000{i}')
            Customer.objects.filter(pk=c.pk).update(segment=seg, churn_segment=churn)
            self.tasks.append(FollowUpTask.objects.create(
                customer=c, item=item, branch=branch, due_date=date(2026, 11, 20), status='pending'))
        self.t1, self.t2, self.t3 = (t.pk for t in self.tasks)

    def _get(self, **params):
        r = self.client_.get(self.URL, {'page_size': 100, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return _ids(r)

    def test_branch_multi(self):
        self.assertEqual(self._get(branch=f'{self.b1.pk},{self.b2.pk}'), {self.t1, self.t2})
        self.assertEqual(self._get(branch=str(self.b3.pk)), {self.t3})
        self.assertEqual(self._get(), {self.t1, self.t2, self.t3})

    def test_medicine_type_multi(self):
        self.assertEqual(self._get(medicine_type='01,03'), {self.t1, self.t3})
        self.assertEqual(self._get(medicine_type='02'), {self.t2})
        self.assertEqual(self._get(medicine_type=''), {self.t1, self.t2, self.t3})

    def test_indication_multi(self):
        self.assertEqual(self._get(indication='ضغط الدم,القلب'), {self.t1, self.t3})
        self.assertEqual(self._get(indication='السكر'), {self.t2})
        self.assertEqual(self._get(indication=''), {self.t1, self.t2, self.t3})

    def test_segment_multi(self):
        self.assertEqual(self._get(segment='vip,loyal'), {self.t1, self.t2})
        self.assertEqual(self._get(segment='at_risk'), {self.t3})
        self.assertEqual(self._get(segment=''), {self.t1, self.t2, self.t3})

    def test_churn_segment_multi(self):
        self.assertEqual(self._get(churn_segment='medium,high'), {self.t2, self.t3})
        self.assertEqual(self._get(churn_segment='low'), {self.t1})
        self.assertEqual(self._get(churn_segment=''), {self.t1, self.t2, self.t3})


class CallListBranchMultiTests(TestCase):
    URL = '/api/followups/call-lists/preview/'

    def setUp(self):
        _, _, self.client_ = make_admin('msf_cl_admin')
        self.b1, self.b2 = make_branch(), make_branch2()
        self.b3 = make_branch('فرع ثالث', 'B03')
        for i, b in enumerate((self.b1, self.b2, self.b3)):
            c = make_customer(f'عميل قائمة {i}', f'0105551111{i}')
            Customer.objects.filter(pk=c.pk).update(segment='at_risk', preferred_branch=b)

    def _matching(self, **criteria):
        r = self.client_.post(self.URL, {'criteria': {'segments': ['at_risk'], **criteria}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return r.data['matching']

    def test_branch_ids_multi(self):
        self.assertEqual(self._matching(branch_ids=[self.b1.pk, self.b2.pk]), 2)
        self.assertEqual(self._matching(branch_ids=[self.b3.pk]), 1)
        self.assertEqual(self._matching(branch_ids=[]), 3)
        self.assertEqual(self._matching(), 3)

    def test_old_single_branch_id_still_works(self):
        self.assertEqual(self._matching(branch_id=self.b2.pk), 1)

    def test_junk_branch_is_rejected_not_widened(self):
        r = self.client_.post(self.URL, {'criteria': {'segments': ['at_risk'], 'branch_ids': ['x']}},
                              format='json')
        self.assertEqual(r.status_code, 400)


class CallLogMultiFilterTests(TestCase):
    URL = '/api/callcenter/calls/'

    def setUp(self):
        _, _, self.client_ = make_admin('msf_cc_admin')
        b = make_branch()

        def mk(d, s, p):
            return CallLog.objects.create(phone_number='01055522200', branch=b,
                                          direction=d, status=s, purpose=p).pk
        self.c1 = mk('inbound', 'answered', 'reservation')
        self.c2 = mk('outbound', 'no_answer', 'delivery')
        self.c3 = mk('whatsapp', 'busy', 'refill')

    def _get(self, **params):
        r = self.client_.get(self.URL, {'page_size': 100, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return _ids(r)

    def test_status_multi(self):
        self.assertEqual(self._get(status='answered,busy'), {self.c1, self.c3})
        self.assertEqual(self._get(status='no_answer'), {self.c2})
        self.assertEqual(self._get(), {self.c1, self.c2, self.c3})

    def test_purpose_multi(self):
        self.assertEqual(self._get(purpose='delivery,refill'), {self.c2, self.c3})
        self.assertEqual(self._get(purpose='reservation'), {self.c1})
        self.assertEqual(self._get(purpose=''), {self.c1, self.c2, self.c3})

    def test_direction_multi(self):
        self.assertEqual(self._get(direction='inbound,outbound'), {self.c1, self.c2})
        self.assertEqual(self._get(direction='whatsapp'), {self.c3})
        self.assertEqual(self._get(direction=''), {self.c1, self.c2, self.c3})


class DeliveryMultiFilterTests(TestCase):
    URL = '/api/delivery/'

    def setUp(self):
        _, _, self.client_ = make_admin('msf_del_admin')
        self.b1, self.b2 = make_branch(), make_branch2()
        self.b3 = make_branch('فرع ثالث', 'B03')
        self.driver = DeliveryDriver.objects.create(full_name='سائق', mobile='0100000099')
        self.orders = []
        for b, src, score in ((self.b1, 'call_center', 5), (self.b2, 'branch_pos', 4), (self.b3, 'call_center', 1)):
            o = DeliveryOrder.objects.create(branch=b, customer_name='عميل', source_type=src,
                                             assigned_driver=self.driver)
            DeliveryCSAT.objects.create(order=o, score=score)
            self.orders.append(o.pk)
        self.o1, self.o2, self.o3 = self.orders

    def _list(self, client=None, **params):
        r = (client or self.client_).get(self.URL, {'page_size': 100, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return _ids(r)

    def test_list_branch_multi(self):
        self.assertEqual(self._list(branch=f'{self.b1.pk},{self.b3.pk}'), {self.o1, self.o3})
        self.assertEqual(self._list(branch=str(self.b2.pk)), {self.o2})
        self.assertEqual(self._list(), {self.o1, self.o2, self.o3})

    def test_list_source_multi(self):
        self.assertEqual(self._list(source_type='call_center,branch_pos'), {self.o1, self.o2, self.o3})
        self.assertEqual(self._list(source_type='branch_pos'), {self.o2})
        self.assertEqual(self._list(source_type=''), {self.o1, self.o2, self.o3})

    def test_list_branch_multi_never_widens_scope(self):
        _, _, pharm = make_pharmacist('msf_del_ph', branch=self.b1)
        self.assertEqual(self._list(pharm, branch=f'{self.b1.pk},{self.b2.pk}'), {self.o1})

    def _analytics(self, path, **params):
        today = timezone.localdate().isoformat()
        r = self.client_.get(f'/api/delivery/{path}/', {'date_from': today, 'date_to': today, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_driver_performance_branch_multi(self):
        def total(**p):
            return sum(d['total'] for d in self._analytics('driver-performance', **p)['drivers'])
        self.assertEqual(total(branch=f'{self.b1.pk},{self.b2.pk}'), 2)
        self.assertEqual(total(branch=str(self.b3.pk)), 1)
        self.assertEqual(total(), 3)

    def test_csat_branch_multi(self):
        def total(**p):
            return self._analytics('csat-report', **p)['total']
        self.assertEqual(total(branch=f'{self.b2.pk},{self.b3.pk}'), 2)
        self.assertEqual(total(branch=str(self.b1.pk)), 1)
        self.assertEqual(total(), 3)
