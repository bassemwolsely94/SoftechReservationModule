"""
Multi-select list filters on the catalog screens (core/multi_filter.py): two values = union,
one value = as before, nothing = no filter.

- /api/products/ (+ export): effect_code (also matches effect_code2), shape_code, insurance_type
- /api/images/products/search/: category_id, producer_name (each a partial match)
- /api/composition/search/: strength_unit, dosage_form, class_key
- /api/pricing-approvals/replication/scans/<id>/: status, source_channel
"""
import io

from django.test import TestCase

from apps.catalog.models import Category, Item
from apps.chronic.models import IngredientClass
from apps.composition.models import ItemMoleculeIndex
from apps.discount_approvals.models import ReplicationGap, ReplicationScan
from .factories import make_admin, make_item


def _rows(resp):
    data = resp.data
    return data.get('results', data) if isinstance(data, dict) else data


class ProductCatalogMultiFilterTests(TestCase):
    URL = '/api/products/'

    def setUp(self):
        _, _, self.client_ = make_admin('msc_admin')
        specs = [('MC001', '10', '', 'T', '0'),
                 ('MC002', '20', '', 'C', '1'),
                 ('MC003', '30', '10', 'S', '2')]   # effect_code2 = 10 → matches effect 10 too
        for sid, eff, eff2, shape, ins in specs:
            it = make_item(f'صنف {sid}', sid)
            Item.objects.filter(pk=it.pk).update(effect_code=eff, effect_code2=eff2,
                                                 shape_code=shape, insurance_type=ins)

    def _get(self, **params):
        r = self.client_.get(self.URL, {'page_size': 100, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return {row['softech_id'] for row in _rows(r)}

    def test_effect_code_multi(self):
        self.assertEqual(self._get(effect_code='20,30'), {'MC002', 'MC003'})
        self.assertEqual(self._get(effect_code='10'), {'MC001', 'MC003'})   # one value: as before (code or code2)

    def test_shape_code_multi(self):
        self.assertEqual(self._get(shape_code='T,C'), {'MC001', 'MC002'})
        self.assertEqual(self._get(shape_code='S'), {'MC003'})

    def test_insurance_type_multi_includes_zero(self):
        self.assertEqual(self._get(insurance_type='0,2'), {'MC001', 'MC003'})
        self.assertEqual(self._get(insurance_type='0'), {'MC001'})

    def test_repeated_param_form(self):
        r = self.client_.get(f'{self.URL}?shape_code=T&shape_code=S&page_size=100')
        self.assertEqual({row['softech_id'] for row in _rows(r)}, {'MC001', 'MC003'})

    def test_no_filter_is_all_and_empty_list_is_not_a_filter(self):
        self.assertEqual(self._get(browse=1), {'MC001', 'MC002', 'MC003'})
        # an empty multi-select must not count as a filter: still the «ابحث» prompt state
        r = self.client_.get(self.URL, {'effect_code': '', 'shape_code': ''})
        self.assertTrue(r.data.get('requires_search'))

    def test_export_uses_the_same_multi_filter(self):
        import openpyxl
        r = self.client_.get(f'{self.URL}export/', {'shape_code': 'T,S'})
        self.assertEqual(r.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        codes = {row[0] for row in ws.iter_rows(min_row=2, values_only=True)}
        self.assertEqual(codes, {'MC001', 'MC003'})


class ImageGalleryMultiFilterTests(TestCase):
    URL = '/api/images/products/search/'

    def setUp(self):
        _, _, self.client_ = make_admin('msi_admin')
        # Category.softech_id is unique — give each its own code
        self.c1, self.c2, self.c3 = (Category.objects.create(softech_id=f'MSC{i}', name=f'فئة {i}')
                                     for i in (1, 2, 3))
        for sid, cat, producer in [('MI001', self.c1, 'Pharco Pharma'),
                                   ('MI002', self.c2, 'EIPICO'),
                                   ('MI003', self.c3, 'Amoun')]:
            it = make_item(f'صنف {sid}', sid)
            Item.objects.filter(pk=it.pk).update(category=cat, producer_name=producer)

    def _get(self, **params):
        r = self.client_.get(self.URL, {'page_size': 100, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return {row['softech_id'] for row in r.data['results']}

    def test_category_multi(self):
        self.assertEqual(self._get(category_id=f'{self.c1.pk},{self.c3.pk}'), {'MI001', 'MI003'})
        self.assertEqual(self._get(category_id=str(self.c2.pk)), {'MI002'})

    def test_producer_multi_partial(self):
        self.assertEqual(self._get(producer_name='pharco,amoun'), {'MI001', 'MI003'})
        self.assertEqual(self._get(producer_name='EIPICO'), {'MI002'})

    def test_no_filter_is_all(self):
        self.assertEqual(self._get(), {'MI001', 'MI002', 'MI003'})


class IngredientSearchMultiFilterTests(TestCase):
    URL = '/api/composition/search/'

    def setUp(self):
        _, _, self.client_ = make_admin('msa_admin')
        self.k1 = IngredientClass.objects.create(key='msa-statins', name='MSA Statins')
        self.k2 = IngredientClass.objects.create(key='msa-ppi', name='MSA PPI')
        rows = [('MA001', 1, 'MG', 'TABLET', self.k1),
                ('MA002', 2, 'ML', 'SYRUP', self.k2),
                ('MA003', 3, 'MCG', 'CAPSULE', None)]
        for sid, aicode, unit, form, klass in rows:
            ItemMoleculeIndex.objects.create(item_softech_id=sid, item_name=sid, aicode=aicode,
                                             molecule='MSA MOLECULE', strength_unit=unit,
                                             dosage_form=form, ingredient_class=klass)

    def _get(self, **params):
        r = self.client_.get(self.URL, {'molecule': 'MSA MOLECULE', 'page_size': 100, **params})
        self.assertEqual(r.status_code, 200, r.data)
        return {row['item_softech_id'] for row in _rows(r)}

    def test_unit_multi_case_insensitive(self):
        self.assertEqual(self._get(strength_unit='mg,mcg'), {'MA001', 'MA003'})
        self.assertEqual(self._get(strength_unit='ml'), {'MA002'})

    def test_dosage_form_multi(self):
        self.assertEqual(self._get(dosage_form='TABLET,SYRUP'), {'MA001', 'MA002'})
        self.assertEqual(self._get(dosage_form='CAPS'), {'MA003'})   # one value: partial, as before

    def test_class_key_multi(self):
        self.assertEqual(self._get(class_key='msa-statins,msa-ppi'), {'MA001', 'MA002'})
        self.assertEqual(self._get(class_key='msa-ppi'), {'MA002'})

    def test_no_filter_is_all(self):
        self.assertEqual(self._get(), {'MA001', 'MA002', 'MA003'})


class ReplicationGapMultiFilterTests(TestCase):
    def setUp(self):
        _, _, self.client_ = make_admin('msr_admin')
        self.scan = ReplicationScan.objects.create(status=ReplicationScan.STATUS_DONE)
        self.g1 = ReplicationGap.objects.create(scan=self.scan, item_softech_id='MR001', branch_code='120',
                                                status='stale', source_channel='direct')
        self.g2 = ReplicationGap.objects.create(scan=self.scan, item_softech_id='MR002', branch_code='130',
                                                status='unreachable', source_channel='module')
        self.g3 = ReplicationGap.objects.create(scan=self.scan, item_softech_id='MR003', branch_code='140',
                                                status='repaired', source_channel='direct')
        self.url = f'/api/pricing-approvals/replication/scans/{self.scan.pk}/'

    def _get(self, **params):
        r = self.client_.get(self.url, params)
        self.assertEqual(r.status_code, 200, r.data)
        return {g['id'] for g in r.data['gaps']}

    def test_status_multi(self):
        self.assertEqual(self._get(status='stale,unreachable'), {self.g1.pk, self.g2.pk})
        self.assertEqual(self._get(status='repaired'), {self.g3.pk})

    def test_source_multi_combined_with_status(self):
        self.assertEqual(self._get(source_channel='direct'), {self.g1.pk, self.g3.pk})
        self.assertEqual(self._get(source_channel='direct,module', status='stale,repaired'),
                         {self.g1.pk, self.g3.pk})

    def test_no_filter_is_all(self):
        self.assertEqual(self._get(), {self.g1.pk, self.g2.pk, self.g3.pk})
