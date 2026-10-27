"""
Arabic product names → the mostly-English catalog (apps/shortage/phonetic.py + the shared
matcher apps/shortage/matching.find_best_matches). Every case below is a real line from the
owner's confirmed matches (eval_matching benchmark, 2026-10-05). Memory is OFF here: these
measure the engine itself.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.shortage import phonetic as P
from apps.shortage.matching import find_best_matches


class SkeletonTests(SimpleTestCase):
    def test_arabic_and_latin_sound_alike(self):
        for ar, en in [('سيريلاك', 'CERELAC'), ('ريباريل', 'REPARIL'), ('سولوبرد', 'SOLUPRED'),
                       ('يوراليت', 'URALYT'), ('سبلفكت', 'SUPLFECT'), ('انتروجيرمينا', 'ENTEROGERMINA'),
                       ('تلفاست', 'TELFAST'), ('رينكس', 'RHINEX'), ('جينيرا', 'GYNERA'), ('اوكسميت', 'OXYMET'),
                       ('سيبيركس', 'SPIREX'), ('بيتادين', 'BETADINE'), ('كونجيستال', 'CONGESTAL'),
                       ('جليبتس', 'GLIPTUS'), ('بيبيلاك', 'BEBELAC'), ('نان', 'NAN'), ('كارفيد', 'CARVID')]:
            self.assertEqual(P.skeleton_ar(ar), P.skeleton_en(en), (ar, en))

    def test_vowel_key_separates_short_names(self):
        self.assertEqual(P.vkey_ar('بيبيلاك'), P.vkey_en('BEBELAC'))
        self.assertNotEqual(P.vkey_ar('نان'), P.vkey_en('NANO'))

    def test_query_parsing(self):
        p = P.parse_query('سيريلاك فواكه 125 جرام كوته')
        self.assertEqual(p['skels'], ['SRLK'])                   # فواكه / جرام / كوته aren't name words
        self.assertIn('fruit', p['words'])
        self.assertIn('gm', p['forms'])
        p = P.parse_query('اوكسميت كبار ...اطفال نقط')
        self.assertEqual(p['skels'], ['KSMT'])
        self.assertTrue({'adult', 'inf'} <= p['words'])
        self.assertIn('drop', p['forms'])


def _items(*names):
    from apps.catalog.models import Item
    return {n: Item.objects.create(softech_id=str(930000 + i), name=n, pack_price=100)
            for i, n in enumerate(names)}


class ArabicMatchingTests(TestCase):
    def setUp(self):
        P.reset_index()
        self.it = _items(
            'CERELAC WHEAT 125GM', 'CERELAC 3FRUITS&WHEAT W/ MILK 125GM', 'CERELAC RICE WITH MILK 125GM',
            'CETAL 500MG 20TAB', 'ACETYLCYSTEINE  600MG 10SACH', 'STILL POWER POWDER',
            'OXYMET  INF .025% NASAL DROPS', 'OXYMET ADULT .05%  NASAL DROPS',
            'NAN (1) FORMULA MILK POWDER 400GM', 'NANO PROTEIN  KERATIN 1 L',
            'TELFAST 120MG 20TAB', 'TELFAST 180MG 20TAB', 'ONE TWO THREE 120ML SYRUP', 'ATOR 80 MG 10TAB',
            'OMEZ 10 14/CAP (2STRIPSX7)', 'OMEZ 40 MG  10 CAP.', 'LA ROCHE-POSAY LIPIKAR AP+M BAUME',
            'ENTEROGERMINA 2 BILLION/5ML', 'ENTEROGERMINA 4 BILLION/5ML', 'ANTINAL 220MG/5ML SUSP 60ML',
            'BETADINE 10% ANTISEPTIC SOLUTION 120ML', 'BETADINE   20  GM  OINT')

    def top(self, q):
        res = find_best_matches(q, top_n=3, use_memory=False)
        return res[0]['item_name'] if res else None

    def test_real_supplier_and_whatsapp_lines(self):
        cases = {
            'سيريلاك فواكه 125 جرام': 'CERELAC 3FRUITS&WHEAT W/ MILK 125GM',     # descriptor word
            'استيل سيساتين 600': 'ACETYLCYSTEINE  600MG 10SACH',                # 2 Arabic words = 1 name
            'اوكسميت اطفال نقط': 'OXYMET  INF .025% NASAL DROPS',                # اطفال → INF
            'نان 1': 'NAN (1) FORMULA MILK POWDER 400GM',                         # stage number, not NANO
            'تلفاست 180 ق': 'TELFAST 180MG 20TAB',                                # strength picks the pack
            'وان تو ثري ش': 'ONE TWO THREE 120ML SYRUP',                         # English words in Arabic
            'اوميز 10': 'OMEZ 10 14/CAP (2STRIPSX7)',                             # was LA ROCHE-POSAY
            'انتروجيرمينا 2': 'ENTEROGERMINA 2 BILLION/5ML',                     # was ANTINAL
            'بيتادين مطهر صغير': 'BETADINE 10% ANTISEPTIC SOLUTION 120ML',        # مطهر → ANTISEPTIC
        }
        for q, want in cases.items():
            self.assertEqual(self.top(q), want, q)

    def test_scores_stay_in_range_and_rank_is_stable(self):
        res = find_best_matches('سيريلاك فواكه 125 جرام', top_n=5, use_memory=False)
        self.assertTrue(all(0 <= r['score'] <= 1 for r in res))
        self.assertEqual(len({r['item_id'] for r in res}), len(res))


class ContradictedMemoryTests(TestCase):
    def test_misaligned_confirmation_is_not_pinned(self):
        from apps.shortage import learning as LRN
        P.reset_index()
        it = _items('TRENTAL SR 400MG 20TAB (2STRIPSX10)', 'DECLOPHEN ADULT 5SUPP 100MG')
        LRN.learn_alias('tRENTA', it['DECLOPHEN ADULT 5SUPP 100MG'], source='invoice')
        res = find_best_matches('tRENTA', top_n=3)
        self.assertEqual(res[0]['item_name'], 'TRENTAL SR 400MG 20TAB (2STRIPSX10)')
        self.assertTrue(res[1].get('contradicted'))                          # still offered, second

    def test_arabic_memory_is_never_called_contradicted(self):
        from apps.shortage import learning as LRN
        P.reset_index()
        it = _items('OMEZ 10 14/CAP (2STRIPSX7)', 'LA ROCHE-POSAY LIPIKAR AP+M BAUME')
        LRN.learn_alias('اوميز 10', it['OMEZ 10 14/CAP (2STRIPSX7)'])
        self.assertEqual(find_best_matches('اوميز 10', top_n=1)[0]['item_name'], 'OMEZ 10 14/CAP (2STRIPSX7)')


class SearchBoxSoundTests(TestCase):
    def setUp(self):
        P.reset_index()
        self.it = _items('CERELAC WHEAT 125GM', 'TELFAST 120MG 20TAB')
        self.user = get_user_model().objects.create_superuser('snd', password='x')

    def test_item_picker_and_ctrl_k_find_arabic_by_sound(self):
        from rest_framework.test import APIClient
        from apps.catalog.universal import universal_search
        c = APIClient()
        c.force_authenticate(self.user)
        with mock.patch('config.sybase.get_sybase_connection', side_effect=RuntimeError('offline')):
            r = c.get('/api/items/softech-search/', {'q': 'تلفاست'})
        self.assertEqual(r.data['results'][0]['name'], 'TELFAST 120MG 20TAB')
        self.assertTrue(r.data['results'][0]['sound'])
        items = universal_search('سيريلاك', types=['items'])['items']
        self.assertEqual((items[0]['name'], items[0]['sound']), ('CERELAC WHEAT 125GM', True))
