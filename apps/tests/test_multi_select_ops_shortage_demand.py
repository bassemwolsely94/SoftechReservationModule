"""
apps/tests/test_multi_select_ops_shortage_demand.py

Multi-select list filters (core/multi_filter.py) on the shortage lists, the shortage aggregate
view, replacement cases, transfers in transit and customer demand: two values → the union,
one value → as before, nothing → everything the user may see. Read-only API calls; nothing
here touches SOFTECH.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.demand.models import DemandRecord
from apps.replacement.models import ReplacementCase as RC
from apps.shortage.models import ShortageItem, ShortageList
from apps.transits.models import InTransitTransfer
from .factories import make_admin, make_branch, make_branch2


def _ids(r):
    assert r.status_code == 200, (r.status_code, getattr(r, 'data', None))
    rows = r.data.get('results', r.data) if isinstance(r.data, dict) else r.data
    return {row['id'] for row in rows}


class _Branches(TestCase):
    def setUp(self):
        from apps.branches.models import Branch
        self.b1 = make_branch('فرع ١', 'M01')
        self.b2 = make_branch2('فرع ٢', 'M02')
        self.b3 = Branch.objects.create(softech_branch_id='M03', name='فرع ٣', name_ar='فرع ٣', is_active=True)
        _, _, self.client = make_admin('ms_ops_admin')

    def g(self, params):
        """ids of the rows the list endpoint returns for these query params."""
        return _ids(self.client.get(self.URL, {'page_size': 50, **params}))


# ── Shortage lists (/api/shortage/lists/) ─────────────────────────────────────
class ShortageListFilterTests(_Branches):
    URL = '/api/shortage/lists/'

    def setUp(self):
        super().setUp()
        self.l1 = ShortageList.objects.create(branch=self.b1, status='open')
        self.l2 = ShortageList.objects.create(branch=self.b2, status='submitted')
        self.l3 = ShortageList.objects.create(branch=self.b3, status='resolved')

    def test_status_two_one_none(self):
        self.assertEqual(self.g({'status': 'open,submitted'}), {self.l1.id, self.l2.id})
        self.assertEqual(self.g({'status': 'resolved'}), {self.l3.id})
        self.assertEqual(self.g({}), {self.l1.id, self.l2.id, self.l3.id})

    def test_branch_two_one_none(self):
        self.assertEqual(self.g({'branch': f'{self.b1.id},{self.b3.id}'}), {self.l1.id, self.l3.id})
        self.assertEqual(self.g({'branch': str(self.b2.id)}), {self.l2.id})
        self.assertEqual(self.g({'branch': ''}), {self.l1.id, self.l2.id, self.l3.id})


class ShortageAggregateFilterTests(_Branches):
    URL = '/api/shortage/lists/aggregate/'

    def setUp(self):
        super().setUp()
        for br, st, name in ((self.b1, 'open', 'صنف مفتوح'), (self.b2, 'submitted', 'صنف مرسل'),
                             (self.b3, 'resolved', 'صنف محلول')):
            sl = ShortageList.objects.create(branch=br, status=st)
            ShortageItem.objects.create(shortage_list=sl, raw_name=name, quantity_needed=1)

    def _names(self, params):
        r = self.client.get(self.URL, params)
        self.assertEqual(r.status_code, 200)
        return {row['item_name'] for row in r.data['results']}

    def test_status_two_one_none_and_default(self):
        self.assertEqual(self._names({'status': 'open,submitted'}), {'صنف مفتوح', 'صنف مرسل'})
        self.assertEqual(self._names({'status': 'submitted'}), {'صنف مرسل'})
        self.assertEqual(self._names({'status': ''}), {'صنف مفتوح', 'صنف مرسل', 'صنف محلول'})
        self.assertEqual(self._names({}), {'صنف مفتوح'})          # no param = open, as before

    def test_branch_ids_with_status(self):
        self.assertEqual(self._names({'status': '', 'branch_ids': f'{self.b2.id},{self.b3.id}'}),
                         {'صنف مرسل', 'صنف محلول'})


# ── Replacement cases (/api/replacement/cases/) ───────────────────────────────
class ReplacementCaseFilterTests(_Branches):
    URL = '/api/replacement/cases/'

    def _case(self, br, status, supplier):
        return RC.objects.create(source_type=RC.SOURCE_INSURANCE_RX, status=status, branch=br,
                                 branchcode=br.softech_branch_id, supplier_personcode=supplier,
                                 purchase_date=date(2026, 11, 1), entitlement=Decimal('100'))

    def setUp(self):
        super().setUp()
        self.c1 = self._case(self.b1, RC.STATUS_ENTITLEMENT_ACTIVE, '4472')
        self.c2 = self._case(self.b2, RC.STATUS_SETTLED, '4471')
        self.c3 = self._case(self.b3, RC.STATUS_UNCLAIMED, '3068')

    def test_status_two_one_none(self):
        self.assertEqual(self.g({'status': 'entitlement_active,unclaimed'}), {self.c1.id, self.c3.id})
        self.assertEqual(self.g({'status': 'settled'}), {self.c2.id})
        self.assertEqual(self.g({}), {self.c1.id, self.c2.id, self.c3.id})

    def test_supplier_two_one_none(self):
        self.assertEqual(self.g({'supplier': '4472,4471'}), {self.c1.id, self.c2.id})
        self.assertEqual(self.g({'supplier': '3068'}), {self.c3.id})
        self.assertEqual(self.g({'supplier': ''}), {self.c1.id, self.c2.id, self.c3.id})


# ── Transfers in transit (/api/transits/) ─────────────────────────────────────
class InTransitFilterTests(_Branches):
    URL = '/api/transits/'

    def _mk(self, doc, supply, recv, priority, transit_status):
        return InTransitTransfer.objects.create(
            erp_doc_number=doc, erp_supplying_branch_code=supply.softech_branch_id,
            erp_receiving_branch_code=recv.softech_branch_id, supplying_branch=supply, receiving_branch=recv,
            issue_date='2026-11-01', transit_status=transit_status, priority=priority,
            days_in_transit=1, item_count=1, doc_value=Decimal('10.00'), items_snapshot=[])

    def setUp(self):
        super().setUp()
        self.t1 = self._mk('901', self.b1, self.b2, 'green', 'in_transit')
        self.t2 = self._mk('902', self.b2, self.b3, 'red', 'received')
        self.t3 = self._mk('903', self.b3, self.b1, 'critical', 'in_transit')

    def test_priority_two_one_none(self):
        self.assertEqual(self.g({'priority': 'red,critical'}), {self.t2.id, self.t3.id})
        self.assertEqual(self.g({'priority': 'green'}), {self.t1.id})
        self.assertEqual(self.g({}), {self.t1.id, self.t2.id, self.t3.id})

    def test_transit_status_two_one_none(self):
        self.assertEqual(self.g({'transit_status': 'in_transit,received'}), {self.t1.id, self.t2.id, self.t3.id})
        self.assertEqual(self.g({'transit_status': 'received'}), {self.t2.id})
        self.assertEqual(self.g({'transit_status': ''}), {self.t1.id, self.t2.id, self.t3.id})

    def test_branches_two_one_none(self):
        self.assertEqual(self.g({'supplying_branch': f'{self.b1.id},{self.b2.id}'}), {self.t1.id, self.t2.id})
        self.assertEqual(self.g({'supplying_branch': str(self.b3.id)}), {self.t3.id})
        self.assertEqual(self.g({'receiving_branch': f'{self.b1.id},{self.b3.id}'}), {self.t2.id, self.t3.id})
        self.assertEqual(self.g({'receiving_branch': str(self.b2.id)}), {self.t1.id})
        self.assertEqual(self.g({'receiving_branch': ''}), {self.t1.id, self.t2.id, self.t3.id})


# ── Customer demand (/api/demand/) ────────────────────────────────────────────
class DemandFilterTests(_Branches):
    URL = '/api/demand/'

    def _d(self, br, priority):
        return DemandRecord.objects.create(phone='01000000000', customer_name='عميل', branch=br, priority=priority)

    def setUp(self):
        super().setUp()
        self.d1 = self._d(self.b1, 'low')
        self.d2 = self._d(self.b2, 'urgent')
        self.d3 = self._d(self.b3, 'chronic')

    def test_priority_two_one_none(self):
        self.assertEqual(self.g({'priority': 'urgent,chronic'}), {self.d2.id, self.d3.id})
        self.assertEqual(self.g({'priority': 'low'}), {self.d1.id})
        self.assertEqual(self.g({}), {self.d1.id, self.d2.id, self.d3.id})

    def test_branch_two_one_none(self):
        self.assertEqual(self.g({'branch': f'{self.b1.id},{self.b2.id}'}), {self.d1.id, self.d2.id})
        self.assertEqual(self.g({'branch': str(self.b3.id)}), {self.d3.id})
        self.assertEqual(self.g({'branch': ''}), {self.d1.id, self.d2.id, self.d3.id})


class MarketShortageMedFilterTests(TestCase):
    """«كل التصنيفات» on /market-shortage: ?med=a,b keeps the confirmed rows of those categories."""

    def setUp(self):
        from .factories import make_admin, make_item
        _, _, self.client_ = make_admin('ms_med_admin')
        self.codes = {}
        for sid, med in (('MS1', 'TB'), ('MS2', 'SY'), ('MS3', 'AM')):
            it = make_item(name=f'صنف {sid}', softech_id=sid)
            it.in_shortage, it.medicine_type = True, med
            it.save(update_fields=['in_shortage', 'medicine_type'])
            self.codes[med] = sid

    def _codes(self, qs=''):
        r = self.client_.get(f'/api/purchasing/shortage/confirmed/{qs}')
        self.assertEqual(r.status_code, 200)
        return {x['code'] for x in r.json()['items']}

    def test_med_two_one_none(self):
        self.assertEqual(self._codes('?med=TB,SY'), {'MS1', 'MS2'})
        self.assertEqual(self._codes('?med=AM'), {'MS3'})
        self.assertEqual(self._codes(), {'MS1', 'MS2', 'MS3'})
