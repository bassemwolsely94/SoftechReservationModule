"""
The shared matching core (apps/supply/line_matching.py, doc 31 phase A, owner 2026-10-25):
one WhatsApp header reader, one folding, one catalog search read by both engines, strict
flags, and the two slip fixes (strength vs pack count; product-type words).
"""
from django.test import SimpleTestCase, TestCase

from apps.supply import ingest as ING
from apps.supply import line_matching as LM


class HeaderTests(SimpleTestCase):
    def test_every_whatsapp_format(self):
        cases = {
            '[12:44 pm, 07/10/2026] Ramco: Concor 5': ('Ramco', '07/10/2026', '12:44 pm', 'Concor 5'),       # Desktop
            '[07/10/2026, 12:44:10] Ramco: Concor 5': ('Ramco', '07/10/2026', '12:44:10', 'Concor 5'),       # iOS
            '07/10/2026, 12:44 - Ramco: Concor 5': ('Ramco', '07/10/2026', '12:44', 'Concor 5'),             # Android
            '[٢٠/٩/٢٠٢٦ ١٠:١٧ ص] مخزن: كونكور': ('مخزن', '20/9/2026', '10:17 ص', 'كونكور'),                # Arabic digits
            '9/20/26, 10:15 PM - Ramco: X': ('Ramco', '9/20/26', '10:15 PM', 'X'),
        }
        for line, (sender, date, time, body) in cases.items():
            h = LM.header(line)
            self.assertEqual((h['sender'], h['date'], h['time'], h['body']), (sender, date, time, body), line)
        self.assertIsNone(LM.header('Concor 5 20%'))
        self.assertEqual(LM.header('07/10/2026, 12:44 - Messages are end-to-end encrypted')['sender'], '')

    def test_sender_rule(self):
        line = '[10:15, 07/10/2026] Branch: Nozha #2 ElAdib: THIOTACID 600 علبتين'
        self.assertEqual(LM.header(line, sender_rule='last')['sender'], 'Branch: Nozha #2 ElAdib')
        self.assertEqual(LM.header(line, sender_rule='first')['sender'], 'Branch')
        sup = '[10:15, 07/10/2026] EGY DRUG: Concor 5 : 20%'
        self.assertEqual(LM.header(sup, sender_rule='first')['body'], 'Concor 5 : 20%')

    def test_both_screens_use_it(self):
        from apps.supply import availability as A, branch_requests as BR
        msgs = BR.split_messages('[10:15, 07/10/2026] Branch: Nozha: Aricept 10\n[10:16, 07/10/2026] Branch: Nozha: Omez')
        self.assertEqual([(m['sender'], m['text']) for m in msgs], [('Branch: Nozha', 'Aricept 10'), ('Branch: Nozha', 'Omez')])
        self.assertEqual(A.clean_line('[10:15, 07/10/2026] Ramco: Concor 5 20%'), 'Concor 5 20%')
        self.assertIsNone(A.clean_line('07/10/2026, 12:44 - Ramco joined using this group\'s invite link'))
        self.assertEqual(A.detect_sender('[10:15, 07/10/2026] Ramco: a\n[10:16, 07/10/2026] Ramco: b'), 'Ramco')

    def test_fold(self):
        self.assertEqual(LM.fold('‏كونكور ٥ ٢٠٪ '), 'كونكور 5 20% ')


class SlipFixTests(SimpleTestCase):
    def test_strength_found_only_as_a_pack_count_is_flagged(self):
        # «تي 4ثيرو 100» vs T4 50MCG 100TAB — "100" is the tablet count, the strength is 50
        self.assertIn('strength_mismatch', ING.review_flags('تي 4ثيرو 100', 'T 4-THYRO 50MCG 100TAB 1JAR'))
        # …but a written pack count is not a strength: «كونكور 5 30» vs CONCOR 5MG 30TAB stays clean
        self.assertNotIn('strength_mismatch', ING.review_flags('كونكور 5 30', 'CONCOR 5MG 30TAB'))
        self.assertNotIn('strength_mismatch', ING.review_flags('T4 100 100TAB', 'T 4-THYRO 100MCG 100TAB'))

    def test_written_product_type_word_must_be_in_the_item(self):
        self.assertIn('word_mismatch', ING.review_flags('بانادول اكسترا 48 اقراص',
                                                        'PANADOL ADVANCE 500MG 48TAB LOCAL (4STRIPSX12)'))
        self.assertNotIn('word_mismatch', ING.review_flags('بانادول اكسترا 48 اقراص',
                                                           'PANADOL EXTRA  OPTIZORB 48TAB (EGYPT) (4STRIPSX12)'))
        self.assertNotIn('word_mismatch', ING.review_flags('بانادول 48', 'PANADOL EXTRA 48TAB'))   # left out = fine


class MatchTextTests(TestCase):
    def setUp(self):
        from apps.catalog.models import Item
        mk = lambda sid, name: Item.objects.create(softech_id=sid, name=name, pack_price=50, is_active=True)
        self.c5 = mk('9001', 'CONCOR 5MG 30TAB')
        self.c10 = mk('9002', 'CONCOR 10MG 30TAB')
        self.pe = mk('9003', 'PANADOL EXTRA 24TAB')
        self.pa = mk('9004', 'PANADOL ADVANCE 24TAB')

    def test_supplier_prefills_branch_does_not_guess_between_versions(self):
        sup = LM.match_text('Concor', source=LM.SUPPLIER)
        br = LM.match_text('Concor', source=LM.BRANCH)
        self.assertIsNotNone(sup['item'])                         # supplier screen: a suggestion…
        self.assertIn('choose_variant', sup['flags'])             # …that a person must check
        self.assertIsNone(br['item'])                             # branch screen: never a guess (owner 2026-10-04)
        self.assertIn('choose_variant', br['flags'])
        self.assertEqual({c['id'] for c in br['candidates'] if c['variant']}, {self.c5.id, self.c10.id})

    def test_written_strength_settles_it(self):
        for src in (LM.SUPPLIER, LM.BRANCH):
            r = LM.match_text('Concor 10', source=src)
            self.assertEqual(r['item'].id, self.c10.id, src)
            self.assertFalse(LM.needs_review(r['flags']), (src, r['flags']))

    def test_word_and_flags_labelled(self):
        r = LM.match_text('panadol advance 24', source=LM.SUPPLIER)
        self.assertEqual(r['item'].id, self.pa.id)
        self.assertTrue(all(f in LM.FLAG_LABELS for f in r['flags']))
        self.assertIn('engines', r)
