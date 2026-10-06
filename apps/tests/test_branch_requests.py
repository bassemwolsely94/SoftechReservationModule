"""
/supply «طلبات واتساب» — branch requests pasted from WhatsApp groups
(apps/supply/branch_requests.py + apps/purchasing/branch_request_views.py).

Built on the real messages of branch 130's «طلبات مستعجلة - النزهه» group (2026-10-03),
including the two cases that used to resolve WRONG and automatically:
  "Aricept 10"  → was qty 10 + ARICEPT 5MG      (strength read as a quantity)
  "Euthyrox 25" → was qty 25 + EUTHYROX 100     (same)
and the shared-matcher miss "PREVAGLIP 5MG 30TAB (3STRIPSX10)" → BIOPREX 5MG.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.supply import branch_requests as W

User = get_user_model()

SAMPLE = """[12:52 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: THIOTACID LIPOSOMAL  30TAB (3STRPSX10) BIG NEW SIZ مطلوب لتعاقد
[3:13 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: 130HD16417
عميل كهربا محتاج 4 علب اوميز 10
و كارفيد 25 علبة
[3:38 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: عميل كهربا مستعجل علي ادويته من يوم الخميس
[5:50 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: EFALEX SYRUP 120ML
01283222557
Mahmoud ElFizy
[6:33 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: LAry pro
Pectol
كل الانواع
Strepsils كل الانواع
[6:33 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: Nevine ibrahim
1box Eliquis 2.5
2box Donazepine 10mg  (DONAZEPINE 28/10 MG 20 CAP (2STRIPSX10))
[7:16 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: 01010084260
Ahmed Sabry
Mixtard Penfill
لكم طرفنا تبع الكرباء
عدد 3 خراطيش
[8:45 pm, 03/10/2026] Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy: PREVAGLIP 5MG 30TAB (3STRIPSX10)
ضرورى"""


class QuantityRuleTests(SimpleTestCase):
    """A number is a quantity only next to a unit word / count marker; a bare trailing
    number is the strength (owner rule, 2026-10-04)."""

    def q(self, s):
        p = W.parse_qty(s)
        return p['text'], p['qty'], p['unit'], p['qty_source']

    def test_bare_trailing_number_is_strength_not_qty(self):
        self.assertEqual(self.q('Aricept 10'), ('Aricept 10', 1, 'pack', 'default'))
        self.assertEqual(self.q('Euthyrox 25'), ('Euthyrox 25', 1, 'pack', 'default'))
        self.assertEqual(self.q('One Alpha 0.5'), ('One Alpha 0.5', 1, 'pack', 'default'))

    def test_unit_words_and_counts(self):
        self.assertEqual(self.q('4 علب اوميز 10'), ('اوميز 10', 4, 'pack', 'unit'))   # item follows
        self.assertEqual(self.q('كارفيد 25 علبة'), ('كارفيد', 25, 'pack', 'unit'))
        self.assertEqual(self.q('1box Eliquis 2.5'), ('Eliquis 2.5', 1, 'pack', 'unit'))
        self.assertEqual(self.q('2box Donazepine 10mg'), ('Donazepine 10mg', 2, 'pack', 'unit'))
        self.assertEqual(self.q('عدد 3 خراطيش'), ('', 3, 'pack', 'count'))
        self.assertEqual(self.q('علبتين بانادول'), ('بانادول', 2, 'pack', 'unit'))
        self.assertEqual(self.q('Panadol x2'), ('Panadol', 2, 'pack', 'count'))
        self.assertEqual(self.q('شريط بروفين 400'), ('بروفين 400', 1, 'strip', 'unit'))

    def test_pack_descriptors_are_not_quantities(self):
        self.assertEqual(self.q('PREVAGLIP 5MG 30TAB (3STRIPSX10)'),
                         ('PREVAGLIP 5MG 30TAB (3STRIPSX10)', 1, 'pack', 'default'))
        self.assertEqual(self.q('CELLCEPT 500MG 50TAB (XX) (5 STRIPSX10)')[1:], (1, 'pack', 'default'))

    def test_fillers_and_all_types(self):
        p = W.parse_qty('Strepsils كل الانواع')
        self.assertEqual((p['text'], p['all_variants']), ('Strepsils', True))
        self.assertEqual(W.parse_qty('THIOTACID LIPOSOMAL 30TAB مطلوب لتعاقد')['text'], 'THIOTACID LIPOSOMAL 30TAB')
        self.assertEqual(W.parse_qty('١ box Eliquis ٢.٥')['text'], 'Eliquis 2.5')    # Arabic digits


class MessageSplitTests(SimpleTestCase):
    def test_desktop_copy_sender_with_colon(self):
        msgs = W.split_messages(SAMPLE)
        self.assertEqual(len(msgs), 8)
        self.assertEqual({m['sender'] for m in msgs}, {'Branch: Nozha #2 ElAdib ElSebaie Aliaa Pharmacy'})
        self.assertTrue(msgs[0]['text'].startswith('THIOTACID'))
        self.assertEqual(msgs[1]['text'].split('\n')[0], '130HD16417')           # multi-line kept

    def test_android_export_and_system_lines(self):
        txt = ('03/10/2026, 3:13 pm - Messages and calls are end-to-end encrypted.\n'
               '03/10/2026, 3:14 pm - Ahmed: Panadol extra\nBrufen 400\n'
               '03/10/2026, 3:15 pm - Ahmed: <Media omitted>')
        msgs = W.split_messages(txt)
        self.assertEqual([(m['sender'], m['text']) for m in msgs], [('Ahmed', 'Panadol extra\nBrufen 400')])

    def test_plain_paste_blocks(self):
        msgs = W.split_messages('Panadol\nBrufen 400\n\nEliquis 2.5')
        self.assertEqual([m['text'] for m in msgs], ['Panadol\nBrufen 400', 'Eliquis 2.5'])


class FragmentTests(TestCase):
    """Names, phones, references and remarks become notes; a quantity-only or
    «كل الانواع»-only line applies to the item before it."""

    def frags(self, msg):
        return [(f['kind'], f.get('note') or f['text'], f.get('qty'), f.get('all_variants'))
                for f in W.extract(msg)]

    def test_customer_message(self):
        self.assertEqual(self.frags('01010084260\nAhmed Sabry\nMixtard Penfill\nلكم طرفنا تبع الكرباء\nعدد 3 خراطيش'), [
            ('note', 'phone', None, None), ('note', 'name', None, None),
            ('item', 'Mixtard Penfill', 3, False),                       # «عدد 3» lands HERE
            ('note', 'remark', None, None)])

    def test_reference_and_arabic_sentence_split(self):
        out = self.frags('130HD16417\nعميل كهربا محتاج 4 علب اوميز 10\nو كارفيد 25 علبة')
        self.assertEqual(out, [('note', 'ref', None, None), ('item', 'اوميز 10', 4, False),
                               ('item', 'كارفيد', 25, False)])

    def test_all_types_line_and_names(self):
        self.assertEqual(self.frags('LAry pro\nPectol\nكل الانواع\nStrepsils كل الانواع'), [
            ('item', 'LAry pro', 1, False), ('item', 'Pectol', 1, True), ('item', 'Strepsils', 1, True)])
        self.assertEqual(self.frags('Nevine ibrahim\n1box Eliquis 2.5')[0], ('note', 'name', None, None))
        self.assertEqual(self.frags('عميل كهربا مستعجل علي ادويته من يوم الخميس'),
                         [('note', 'remark', None, None)])


def _items(*names):
    from apps.catalog.models import Item
    return [Item.objects.create(softech_id=str(900000 + i), name=n, pack_price=100, cost_price=80)
            for i, n in enumerate(names)]


class ResolveTests(TestCase):
    """Matching against a small catalog — the dangerous cases first."""

    def r(self, raw):
        frag = W.extract(raw)[0]
        out = W.resolve(frag)
        return out, frag

    def test_aricept_10_is_10mg_not_qty_10(self):
        _items('ARICEPT  5 MG  7 TAB', 'ARICEPT 10MG 14TAB (2STRIPSX7)')
        out, frag = self.r('Aricept 10')
        self.assertEqual((frag['qty'], out['item'].name), (1, 'ARICEPT 10MG 14TAB (2STRIPSX7)'))
        self.assertNotIn('choose_variant', out['flags'])

    def test_euthyrox_25_is_25ug_not_qty_25(self):
        _items('EUTHYROX 100UG/MCG 100TAB (XX) (4STRIPSX25)', 'EUTHYROX 25UG/MCG 100TAB (XX) (4STRIPSX25)',
               'EUTHYROX 50UG/MCG 100TAB (XX) (4STRIPSX25)')
        out, frag = self.r('Euthyrox 25')
        self.assertEqual((frag['qty'], out['item'].name), (1, 'EUTHYROX 25UG/MCG 100TAB (XX) (4STRIPSX25)'))

    def test_written_pack_size_narrows_but_never_rules_out(self):
        """"Euthyrox 25mcg 60tab" — the catalog only has the 100TAB pack: still EUTHYROX 25,
        flagged 'pack_not_found' with a conversion hint (never «التركيز غير موجود»)."""
        _items('EUTHYROX 25UG/MCG 100TAB (XX) (4STRIPSX25)', 'EUTHYROX 50UG/MCG 100TAB (XX) (4STRIPSX25)')
        out, frag = self.r('Euthyrox 25mcg 60tab')
        self.assertEqual(out['item'].name, 'EUTHYROX 25UG/MCG 100TAB (XX) (4STRIPSX25)')
        self.assertIn('pack_not_found', out['flags'])
        self.assertNotIn('strength_mismatch', out['flags'])
        self.assertEqual(W.pack_hint(frag['text'], out['item'].name), {'written': 60, 'per_pack': 100, 'packs': 1})

    def test_written_pack_picks_the_matching_pack(self):
        _items('ARICEPT 5MG 14TAB (2STRIPSX7) BIG NEW SIZE', 'ARICEPT  5 MG  7 TAB', 'ARICEPT 10MG 14TAB (2STRIPSX7)')
        out, _ = self.r('Aricept 5mg 14tab')
        self.assertEqual((out['item'].name, out['flags']), ('ARICEPT 5MG 14TAB (2STRIPSX7) BIG NEW SIZE', []))
        out, frag = self.r('Aricept 5mg 60tab')                 # no 60 pack: both 5mg packs offered
        self.assertIsNone(out['item'])
        self.assertEqual(set(out['flags']), {'pack_not_found', 'choose_variant'})
        self.assertEqual({c['name'] for c in out['candidates'] if c['variant']},
                         {'ARICEPT 5MG 14TAB (2STRIPSX7) BIG NEW SIZE', 'ARICEPT  5 MG  7 TAB'})
        self.assertEqual(W.pack_hint(frag['text'], 'ARICEPT 5MG 14TAB (2STRIPSX7) BIG NEW SIZE'),
                         {'written': 60, 'per_pack': 14, 'packs': 5})

    def test_versions_are_never_auto_picked(self):
        _items('STREPSILS (ANTI BECTRIAL ) 24 LOZE(ORIGINAL)', 'STREPSILS (COOL) 16LOZENGES 2 STR XX')
        out, _ = self.r('Strepsils')
        self.assertIsNone(out['item'])
        self.assertIn('choose_variant', out['flags'])
        self.assertEqual(len(out['candidates']), 2)

    def test_all_types_anchors_the_family_and_expands_to_fitting_versions(self):
        from apps.supply.models import BranchRequest, BranchRequestLine as L
        a, b, other = _items('STREPSILS (ANTI BECTRIAL ) 24 LOZE(ORIGINAL)', 'STREPSILS (COOL) 16LOZENGES 2 STR XX',
                             'STREPSILS SPRAY 20ML')
        out, frag = self.r('Strepsils lozenges كل الانواع')
        self.assertIsNotNone(out['item'])
        self.assertNotIn('choose_variant', out['flags'])
        ln = L(request=BranchRequest(branch=_branch()), raw_text='x', item=out['item'],
               all_variants=True, candidates=out['candidates'])
        self.assertEqual({i.id for i in W.expand_items(ln)}, {a.id, b.id})      # not the spray

    def test_exact_pack_beats_other_pack_and_other_product(self):
        _items('PREVAGLIP 5MG 10TAB', 'PREVAGLIP 5MG 30TAB (3STRIPSX10)', 'BIOPREX 5MG 30TAB (3STRIPSX10)')
        out, _ = self.r('PREVAGLIP 5MG 30TAB (3STRIPSX10)')
        self.assertEqual(out['item'].name, 'PREVAGLIP 5MG 30TAB (3STRIPSX10)')
        self.assertEqual(out['flags'], [])

    def test_unit_qty_that_is_also_a_strength_is_flagged(self):
        _items('CARVID 25MG 30TAB (3STRIPSX10) BIG NEW SIZE', 'CARVID 6.25MG 20TAB (2STRIPSX10)')
        out, frag = self.r('Carvid 25 علبة')
        self.assertEqual(frag['qty'], 25)
        self.assertIn('qty_maybe_strength', out['flags'])
        self.assertIn('qty_large', out['flags'])
        self.assertEqual(out['candidates'][0]['name'], 'CARVID 25MG 30TAB (3STRIPSX10) BIG NEW SIZE')

    def test_duplicate_codes_show_sales_and_stock(self):
        _items('HIGH FORTE CREAM 50GM', 'HI-FORTE CREAM 50GM')
        out, _ = self.r('HIGH FORTE CREAM 50GM')
        self.assertEqual(out['item'].name, 'HIGH FORTE CREAM 50GM')
        for c in out['candidates']:
            self.assertIn('network_rate', c)
            self.assertIn('branch_stock', c)


class MatcherAnchorTests(TestCase):
    """Shared matcher: pack tokens ("30tab", "3stripsx10") match thousands of items and the
    capped prefilter dropped the real product — the drug word now anchors the candidates."""

    def test_real_product_survives_a_flood_of_same_pack_items(self):
        from apps.catalog.models import Item
        from apps.shortage.matching import find_best_matches
        Item.objects.bulk_create([Item(softech_id=str(700000 + i), name=f'DECOY{i:04d} 5MG 30TAB (3STRIPSX10)')
                                  for i in range(1300)])
        Item.objects.create(softech_id='126673', name='PREVAGLIP 5MG 30TAB (3STRIPSX10)')
        top = find_best_matches('PREVAGLIP 5MG 30TAB (3STRIPSX10)', top_n=1)[0]
        self.assertEqual(top['item_softech_id'], '126673')


def _branch(code='130'):
    from apps.branches.models import Branch
    return Branch.objects.create(name=f'B{code}', softech_branch_id=code, is_active=True,
                                 is_operational=True, db_host='10.0.0.1')


def _user(username, *, role='salesperson', group=None):
    from apps.users.models import ERPUser, StaffProfile
    u = User.objects.create_user(username=username, password='x')
    StaffProfile.objects.create(user=u, role=role)
    if group is not None:
        ERPUser.objects.create(username=username, user_group=str(group), is_active=True)
    return u


@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class ApiTests(TestCase):
    URL = '/api/purchasing/isr/branch-requests/'

    def setUp(self):
        self.br = _branch()
        self.aricept5, self.aricept10, self.eliquis = _items(
            'ARICEPT  5 MG  7 TAB', 'ARICEPT 10MG 14TAB (2STRIPSX7)', 'ELIQUIS 2.5MG 20TAB (XX)  (2STRIPSX10)')
        self.c = APIClient()
        self.c.force_authenticate(_user('18', group=19))

    def test_access(self):
        c = APIClient()
        c.force_authenticate(_user('1399', group=14))
        self.assertEqual(c.get(self.URL).status_code, 403)
        self.assertEqual(c.post(self.URL, {'branch': '130', 'text': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.c.post(self.URL, {'branch': '999', 'text': 'x'}, format='json').status_code, 400)

    def test_paste_review_confirm_creates_shortage_list_and_learns(self):
        from apps.catalog.models import ItemAlias
        from apps.shortage.models import ShortageList
        r = self.c.post(self.URL, {'branch': '130', 'group_name': 'طلبات مستعجلة - النزهه',
                                   'text': 'Nevine ibrahim\n1box Eliquis 2.5\nAricept 10\nAriceptt'},
                        format='json')
        self.assertEqual(r.status_code, 201)
        lines = {l['raw_text']: l for l in r.data['lines']}
        self.assertEqual(lines['Nevine ibrahim']['kind'], 'note')
        self.assertEqual(lines['Aricept 10']['item']['id'], self.aricept10.id)
        pk = r.data['id']
        # «تأكيد الآمنة» confirms only clean lines
        r = self.c.post(f'{self.URL}{pk}/confirm-safe/', format='json')
        safe = {l['raw_text']: l['confirmed'] for l in r.data['lines'] if l['kind'] == 'item'}
        self.assertTrue(safe['1box Eliquis 2.5'])
        # a person picks the version for an unclear line → confirmed + taught
        typo = next(l for l in r.data['lines'] if l['raw_text'] == 'Ariceptt')
        r = self.c.patch(f'{self.URL}{pk}/lines/{typo["id"]}/', {'item_id': self.aricept5.id, 'qty': 2},
                         format='json')
        typo = next(l for l in r.data['lines'] if l['raw_text'] == 'Ariceptt')
        self.assertEqual((typo['confirmed'], typo['qty'], typo['qty_source']), (True, 2.0, 'manual'))
        # confirm → shortage list for branch 130, idempotent
        r = self.c.post(f'{self.URL}{pk}/confirm/', format='json')
        self.assertEqual(r.status_code, 200)
        sl = ShortageList.objects.get(pk=r.data['shortage_list_id'])
        self.assertEqual((sl.branch_id, sl.source), (self.br.id, 'whatsapp'))
        self.assertEqual({(i.item_id, float(i.quantity_needed)) for i in sl.items.all()} >= {(self.aricept5.id, 2.0)}, True)
        self.assertTrue(ItemAlias.objects.filter(item=self.aricept5).exists())
        again = self.c.post(f'{self.URL}{pk}/confirm/', format='json')
        self.assertEqual(again.data['shortage_list_id'], sl.pk)
        self.assertEqual(ShortageList.objects.count(), 1)
        # confirmed requests are read-only
        self.assertEqual(self.c.patch(f'{self.URL}{pk}/lines/{typo["id"]}/', {'qty': 5},
                                      format='json').status_code, 400)

    def test_analysis_uses_isr_engine_without_return_legs(self):
        from apps.purchasing import isr_fulfillment as F
        r = self.c.post(self.URL, {'branch': '130', 'text': '2box Eliquis 2.5'}, format='json')
        pk = r.data['id']
        snap = {'isr_numbers': [f'WA-{pk}'], 'branches': ['130', '150'], 'branch_names': {}, 'down': [],
                'fallback': {}, 'run_id': 1, 'taken_at': '2026-10-04T10:00:00', 'names': {},
                'eng': {}, 'stock': {'150': {self.eliquis.softech_id: 9.0}},
                'isrs': [{'isr': f'WA-{pk}', 'kind': 'whatsapp', 'branch': '130', 'for_branch': '130',
                          'date': '2026-10-04', 'approved': 0, 'value': 0, 'user': '18', 'user_name': '',
                          'lines': [{'code': self.eliquis.softech_id, 'qty': 2.0, 'cost': 80.0}]}]}
        with mock.patch.object(F, 'collect_requests', return_value=snap) as col:
            plan = self.c.post(f'{self.URL}{pk}/analysis/', {'coverage': 1.5}, format='json')
            pi = col.call_args[0][0][0]
            ex = self.c.post(f'{self.URL}{pk}/analysis/export/', {'coverage': 1.5,
                                                                   'token': plan.data['token']}, format='json')
        self.assertEqual(pi['lines'], [{'code': self.eliquis.softech_id, 'qty': 2.0, 'cost': 80.0,
                                        'price': 100.0, 'nowqty_at_request': 0.0}])
        self.assertEqual(plan.data['isrs'][0]['kind'], 'whatsapp')
        self.assertEqual(plan.data['isrs'][0]['totals']['from_branches'], 2)      # 150's excess
        self.assertEqual(plan.data['returns'], {})
        self.assertEqual(ex.status_code, 200)
        self.assertIn(f'whatsapp_request_{pk}_br130', ex['Content-Disposition'])


def _fake_items_plan(node, items):
    """isr_writer.build_items_plan without SOFTECH: one line per (code, qty)."""
    return [{'itemcode': c, 'item_name': c, 'itemqty': int(q), 'itemqty_cfarma': float(q), 'nowqty': 0.0,
             'itemsaleprice': 1.0, 'itemcostprice': 2.0, 'suppcode': '', 'gap': float(q)} for c, q in items]


@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class TransferProposalTests(TestCase):
    """«from other branches» on a WhatsApp request → per donor TWO linked proposals:
    donor → 100 (branch_to_hq) and 100 → requesting branch (hq_to_branch). Confirmed lines
    only, fresh stock read, never twice for the same (request, donor)."""
    URL = '/api/purchasing/isr/branch-requests/'

    def setUp(self):
        from apps.supply.models import BranchRequest, BranchRequestLine as L
        self.br = _branch('130')
        self.a, self.b = _items('ELIQUIS 2.5MG 20TAB (XX)  (2STRIPSX10)', 'CELLCEPT 500MG 50TAB (XX) (5 STRIPSX10)')
        self.req = BranchRequest.objects.create(branch=self.br)
        L.objects.create(request=self.req, raw_text='Eliquis 2.5', item=self.a, qty=5, confirmed=True, score=0.95)
        L.objects.create(request=self.req, raw_text='Cellcept', item=self.b, qty=3, confirmed=False, score=1.0,
                         position=1)                                   # NOT confirmed → never moved
        p = mock.patch('apps.purchasing.isr_writer.build_items_plan', side_effect=_fake_items_plan)
        p.start()
        self.addCleanup(p.stop)
        self.c = APIClient()
        self.c.force_authenticate(_user('18', group=19))

    def snap(self, pi):
        a, b = self.a.softech_id, self.b.softech_id
        return {'isr_numbers': [pi['isr']], 'branches': ['130', '150', '160'], 'branch_names': {}, 'down': [],
                'fallback': {}, 'run_id': None, 'taken_at': '2026-10-04T10:00:00', 'names': {}, 'eng': {},
                'stock': {'150': {a: 3.0, b: 9.0}, '160': {a: 1.0}, '100': {}}, 'isrs': [pi]}

    def post(self):
        from apps.purchasing import isr_fulfillment as F
        with mock.patch.object(F, 'collect_requests', side_effect=lambda isrs: self.snap(isrs[0])) as col:
            r = self.c.post(f'{self.URL}{self.req.pk}/transfers/', {'coverage': 1.5}, format='json')
        return r, col

    def test_two_linked_legs_per_donor_from_confirmed_lines(self):
        from apps.purchasing.models import IsrPush
        r, col = self.post()
        self.assertEqual(r.status_code, 201)
        self.assertEqual([l['code'] for l in col.call_args[0][0][0]['lines']], [self.a.softech_id])
        self.assertEqual([(c['donor'], c['qty']) for c in r.data['created']], [('150', 3.0), ('160', 1.0)])
        for c in r.data['created']:
            leg1, leg2 = IsrPush.objects.get(pk=c['leg1_id']), IsrPush.objects.get(pk=c['leg2_id'])
            self.assertEqual((leg1.kind, leg1.branchcode, leg1.dest_branchcode), ('branch_to_hq', c['donor'], '100'))
            self.assertEqual((leg2.kind, leg2.branchcode, leg2.dest_branchcode), ('hq_to_branch', '100', '130'))
            self.assertEqual((leg1.linked_push_id, leg2.linked_push_id), (leg2.id, leg1.id))
            for p in (leg1, leg2):
                self.assertEqual((p.status, p.origin_request_id, p.origin_donor), ('proposed', self.req.pk, c['donor']))
                self.assertIn(f'WA-{self.req.pk}', p.notes)
        self.assertEqual(len(r.data['plan']['transfers']), 2)

    def test_never_twice_and_cancel_frees(self):
        from apps.purchasing.models import IsrPush
        self.post()
        r, _ = self.post()
        self.assertEqual((r.status_code, r.data['created']), (200, []))
        self.assertEqual(IsrPush.objects.count(), 4)
        IsrPush.objects.filter(origin_donor='160').update(status='cancelled')
        r, _ = self.post()
        self.assertEqual([c['donor'] for c in r.data['created']], ['160'])

    def test_db_blocks_a_parallel_duplicate_leg(self):
        from django.db import IntegrityError, transaction
        from apps.purchasing.models import IsrPush
        kw = dict(branchcode='150', dest_branchcode='100', kind='branch_to_hq', origin_request=self.req,
                  origin_donor='150')
        IsrPush.objects.create(**kw)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IsrPush.objects.create(**kw)

    def test_guards(self):
        from apps.supply.models import BranchRequestLine as L
        c = APIClient()
        c.force_authenticate(_user('1399', group=14))
        self.assertEqual(c.post(f'{self.URL}{self.req.pk}/transfers/', {}, format='json').status_code, 403)
        L.objects.filter(request=self.req).update(confirmed=False)
        r, _ = self.post()
        self.assertEqual(r.status_code, 400)                          # nothing confirmed yet
        self.req.status = 'cancelled'
        self.req.save()
        r, _ = self.post()
        self.assertEqual(r.status_code, 400)


@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class MultiPickTests(TestCase):
    """One line → several hand-picked items ("Strepsils" → two chosen flavours). Each pick
    gets the line's quantity; the matcher is not taught a one-to-many spelling."""
    URL = '/api/purchasing/isr/branch-requests/'

    def setUp(self):
        from apps.supply.models import BranchRequest, BranchRequestLine as L
        self.req = BranchRequest.objects.create(branch=_branch())
        self.cool, self.honey, self.orig = _items('STREPSILS (COOL) 16LOZENGES 2 STR XX',
                                                  'STREPSILS (HONEY&LEMON) 24 LOZ', 'STREPSILS ORIGINAL 24 LOZ')
        self.ln = L.objects.create(request=self.req, raw_text='Strepsils 2', match_text='Strepsils', qty=2,
                                   all_variants=True)
        self.c = APIClient()
        self.c.force_authenticate(_user('18', group=19))

    def patch(self, data):
        return self.c.patch(f'{self.URL}{self.req.pk}/lines/{self.ln.pk}/', data, format='json')

    def test_pick_several_confirm_and_expand(self):
        from apps.catalog.models import ItemAlias
        from apps.shortage.models import ShortageList
        r = self.patch({'item_ids': [self.cool.id, self.honey.id]})
        line = r.data['lines'][0]
        self.assertEqual([p['id'] for p in line['picks']], [self.cool.id, self.honey.id])
        self.assertEqual((line['confirmed'], line['all_variants'], line['item']['id']), (True, False, self.cool.id))
        self.assertEqual({l['code']: l['qty'] for l in W.pseudo_isr(self.req)['lines']},
                         {self.cool.softech_id: 2.0, self.honey.softech_id: 2.0})      # qty for each
        self.c.post(f'{self.URL}{self.req.pk}/confirm/', format='json')
        sl = ShortageList.objects.get()
        self.assertEqual({(i.item_id, float(i.quantity_needed)) for i in sl.items.all()},
                         {(self.cool.id, 2.0), (self.honey.id, 2.0)})
        self.assertFalse(ItemAlias.objects.exists())                  # one-to-many is never taught

    def test_single_pick_replaces_and_empty_clears(self):
        self.patch({'item_ids': [self.cool.id, self.honey.id]})
        r = self.patch({'item_id': self.orig.id})
        self.assertEqual([p['id'] for p in r.data['lines'][0]['picks']], [self.orig.id])
        r = self.patch({'item_ids': []})
        self.assertEqual((r.data['lines'][0]['item'], r.data['lines'][0]['picks'],
                          r.data['lines'][0]['confirmed']), (None, [], False))
        self.assertEqual(self.patch({'item_ids': [999999]}).status_code, 400)


class PacksAndExpandTests(TestCase):
    def test_strips_convert_to_packs_and_all_types_expand(self):
        from apps.supply.models import BranchRequest, BranchRequestLine as L
        br = _branch()
        it, other = _items('BRUFEN 400MG 30TAB (3STRIPSX10)', 'BRUFEN 600MG 30TAB (3STRIPSX10)')
        req = BranchRequest.objects.create(branch=br)
        ln = L.objects.create(request=req, raw_text='6 شريط بروفين', item=it, qty=6, qty_unit='strip')
        self.assertEqual(W.packs(ln), 2.0)
        ln2 = L.objects.create(request=req, raw_text='Brufen كل الانواع', item=it, all_variants=True, position=1)
        self.assertEqual({i.id for i in W.expand_items(ln2)}, {it.id, other.id})
        pi = W.pseudo_isr(req)
        self.assertEqual(pi['lines'], [])                     # unconfirmed + no score → not counted
        L.objects.filter(request=req).update(confirmed=True)
        pi = W.pseudo_isr(req)
        self.assertEqual({l['code']: l['qty'] for l in pi['lines']},
                         {it.softech_id: 3.0, other.softech_id: 1.0})             # 2 + 1, and 1
        # a doubtful suggestion never enters the analysis until a person confirms it
        L.objects.create(request=req, raw_text='اوميز 10', item=other, score=0.59, flags=['low_score'], position=2)
        self.assertEqual({l['code']: l['qty'] for l in W.pseudo_isr(req)['lines']},
                         {it.softech_id: 3.0, other.softech_id: 1.0})
