"""POS Speed Wave Task 8 — verified alternatives (apps/composition/alternatives.py).
Only ItemMoleculeIndex rows with source='approved' count; Item.name_scientific is never used."""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalog.models import ItemStock
from apps.composition.alternatives import alternatives_for
from apps.composition.models import ItemMoleculeIndex
from .factories import make_branch, make_item, make_user

URL = '/api/composition/alternatives/'
_aicode = [1000]


def _idx(item, molecule, value, unit='MG', form='TABLET', source='approved'):
    _aicode[0] += 1
    return ItemMoleculeIndex.objects.create(
        item=item, item_softech_id=item.softech_id, item_name=item.name, aicode=_aicode[0],
        molecule=molecule, strength_value=Decimal(str(value)) if value is not None else None,
        strength_unit=unit, dosage_form=form, source=source)


def _ids(rows):
    return [r['softech_id'] for r in rows]


class AlternativesHelperTests(TestCase):
    def test_unverified_item_returns_not_verified(self):
        a = make_item('CONCOR 5', 'A0001')
        _idx(a, 'BISOPROLOL', 5, source='parsed')
        self.assertEqual(alternatives_for(a.id, branch_id=None),
                         {'verified': False, 'same': [], 'other': []})

    def test_item_without_rows_not_verified(self):
        a = make_item('NOROWS', 'A0002')
        self.assertFalse(alternatives_for(a.id, branch_id=None)['verified'])

    def test_same_signature_same_form(self):
        a, b = make_item('CONCOR 5', 'A0003'), make_item('BISOCOR 5', 'A0004')
        _idx(a, 'BISOPROLOL', 5); _idx(b, 'BISOPROLOL', 5)
        r = alternatives_for(a.id, branch_id=None)
        self.assertTrue(r['verified'])
        self.assertEqual(_ids(r['same']), ['A0004'])
        self.assertEqual(r['other'], [])
        for k in ('item_id', 'softech_id', 'name', 'strength', 'dosage_form',
                  'pack_price', 'thumb', 'here_qty', 'branch_stock'):
            self.assertIn(k, r['same'][0])

    def test_other_strength_goes_to_other(self):
        a, b, c = (make_item('CONCOR 5', 'A0005'), make_item('CONCOR 10', 'A0006'),
                   make_item('BISO SYR', 'A0007'))
        _idx(a, 'BISOPROLOL', 5); _idx(b, 'BISOPROLOL', 10); _idx(c, 'BISOPROLOL', 5, form='SYRUP')
        r = alternatives_for(a.id, branch_id=None)
        self.assertEqual(r['same'], [])
        self.assertEqual(sorted(_ids(r['other'])), ['A0006', 'A0007'])

    def test_combo_requires_full_molecule_set(self):
        combo, mono, combo2 = (make_item('CONCOR AM', 'A0008'), make_item('AMLO 5', 'A0009'),
                               make_item('AMLO+BISO', 'A0010'))
        _idx(combo, 'AMLODIPINE', 5); _idx(combo, 'BISOPROLOL', 5)
        _idx(mono, 'AMLODIPINE', 5)
        _idx(combo2, 'AMLODIPINE', 5); _idx(combo2, 'BISOPROLOL', 5)
        r = alternatives_for(combo.id, branch_id=None)
        self.assertEqual(_ids(r['same']), ['A0010'])
        self.assertNotIn('A0009', _ids(r['same']) + _ids(r['other']))
        r2 = alternatives_for(mono.id, branch_id=None)
        self.assertEqual(r2['same'] + r2['other'], [])

    def test_candidate_with_unapproved_row_excluded(self):
        a, b, c = make_item('X 5', 'A0011'), make_item('Y 5', 'A0012'), make_item('Z 5', 'A0013')
        for i in (a, b, c):
            _idx(i, 'BISOPROLOL', 5)
        _idx(c, 'AMLODIPINE', 5, source='parsed')       # one stray unapproved row
        r = alternatives_for(a.id, branch_id=None)
        self.assertEqual(_ids(r['same']), ['A0012'])

    def test_inactive_candidate_excluded(self):
        a, b = make_item('X 5', 'A0014'), make_item('Y 5', 'A0015')
        _idx(a, 'BISOPROLOL', 5); _idx(b, 'BISOPROLOL', 5)
        b.is_active = False; b.save(update_fields=['is_active'])
        self.assertEqual(alternatives_for(a.id, branch_id=None)['same'], [])

    def test_never_uses_name_scientific(self):
        a, b = make_item('P 1', 'A0016'), make_item('Q 1', 'A0017')
        for i in (a, b):
            i.name_scientific = 'PARACETAMOL'; i.save(update_fields=['name_scientific'])
        r = alternatives_for(a.id, branch_id=None)
        self.assertEqual(r, {'verified': False, 'same': [], 'other': []})
        _idx(a, 'PARACETAMOL', 500)                         # b has no approved rows
        r = alternatives_for(a.id, branch_id=None)
        self.assertEqual(r['same'] + r['other'], [])

    def test_sorted_here_qty_desc_then_price_asc_and_stock(self):
        br = make_branch()
        a = make_item('A', 'A0018')
        b, c, d = make_item('B', 'A0019'), make_item('C', 'A0020'), make_item('D', 'A0021')
        for i, p in ((b, 30), (c, 20), (d, 10)):
            i.pack_price = Decimal(p); i.save(update_fields=['pack_price'])
        for i in (a, b, c, d):
            _idx(i, 'BISOPROLOL', 5)
        ItemStock.objects.create(item=b, branch=br, softech_store_code='100', quantity_on_hand=5)
        ItemStock.objects.create(item=c, branch=br, softech_store_code='100', quantity_on_hand=5)
        r = alternatives_for(a.id, branch_id=br.id)
        self.assertEqual(_ids(r['same']), ['A0020', 'A0019', 'A0021'])   # qty 5 (cheap first), then 0
        self.assertEqual(r['same'][0]['here_qty'], 5.0)
        self.assertEqual(r['same'][0]['branch_stock'][0]['branch_id'], br.id)


class AlternativesApiTests(TestCase):
    def test_alternatives_requires_auth(self):
        a = make_item('A', 'A0030')
        self.assertIn(APIClient().get(f'{URL}?item={a.id}').status_code, (401, 403))

    def test_api_ok_for_pos_role(self):
        a, b = make_item('A', 'A0031'), make_item('B', 'A0032')
        _idx(a, 'BISOPROLOL', 5); _idx(b, 'BISOPROLOL', 5)
        _, _, client = make_user('alt_ph', role='pharmacist')
        r = client.get(f'{URL}?item={a.id}')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['verified'])
        self.assertEqual(_ids(r.data['same']), ['A0032'])

    def test_api_bad_item(self):
        _, _, client = make_user('alt_ph2', role='pharmacist')
        self.assertEqual(client.get(URL).status_code, 400)
        self.assertEqual(client.get(f'{URL}?item=99999999').status_code, 404)
