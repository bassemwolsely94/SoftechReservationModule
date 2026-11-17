"""AI GPC brick proposals (batch S2, task 3): switch, shortlist, answer validation, queue order. The provider is
always mocked — no real HTTP."""
import datetime as dt
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.catalog.models import Item
from apps.tax_invoicing import gpc_ai
from apps.tax_invoicing.models import (EtaCodeUsage, EtaReconUncodedItem, TaxBrickSuggestion, TaxCodingDecision,
                                       TaxGpcBrick, TaxItemProfile)

HAIR, PET, VIT, FAM = '10000100', '10000200', '10000300', '10000400'
COMPLETE = 'apps.enrichment.ai_extractor.complete_json'
ON = override_settings(TAX_GPC_AI_ENABLED=True)


def brick(code, name, segment, source='gs1-20260520', definition=''):
    return TaxGpcBrick.objects.create(code=code, name_en=name, segment_code=segment, source=source,
                                      definition=definition)


class Base(TestCase):
    def setUp(self):
        self.n = 0
        brick(PET, 'Pet Shampoo', '10000000')
        brick(HAIR, 'Hair Shampoo', '53000000', definition='Includes any products that can be described as shampoo')
        brick(VIT, 'Vitamins', '51000000')
        brick(FAM, 'Family Brick', '53000000', source='workbook')

    def item(self, name='HEAD SHAMPOO 200ML', family='Shampoo', mtype='Cosmetics', value=100, gpc_code=''):
        self.n += 1
        code = f'AI{self.n:03d}'
        item = Item.objects.create(softech_id=code, name=name, family_name=family, medicine_type_name=mtype,
                                   origin_name='Egypt', producer_name='Acme')
        p = TaxItemProfile.objects.create(softech_itemcode=code, item=item, gpc_code=gpc_code)
        EtaReconUncodedItem.objects.create(system='production', softech_branchcode='01', day=dt.date(2026, 11, 1),
                                           itemcode=code, docs=1, qty=1, value=Decimal(value))
        return p


class SwitchTests(Base):
    @mock.patch(COMPLETE)
    def test_switch_off_nothing_called(self, complete):
        p = self.item()
        self.assertEqual(gpc_ai.run(), {'skipped': 'switch_off'})
        self.assertIsNone(gpc_ai.suggest_one(p))
        out = StringIO()
        call_command('suggest_bricks', stdout=out)
        self.assertIn('off', out.getvalue())
        complete.assert_not_called()
        self.assertFalse(TaxBrickSuggestion.objects.exists())


@ON
class SuggestOneTests(Base):
    def ask(self, answer, model='gemini-x', **item):
        p = self.item(**item)
        with mock.patch(COMPLETE, return_value=(answer, model)) as complete:
            row = gpc_ai.suggest_one(p)
        return p, row, complete

    def test_valid_answer_stored(self):
        p, row, complete = self.ask({'brick': HAIR, 'second': PET, 'confidence': 'High', 'reason': 'شامبو ' * 50})
        self.assertEqual((row.source, row.brick, row.second, row.confidence, row.model, row.error),
                         ('ai', HAIR, PET, 'high', 'gemini-x', ''))
        self.assertLessEqual(len(row.reason), 120)
        self.assertEqual(TaxBrickSuggestion.objects.get(profile=p).brick, HAIR)
        prompt = complete.call_args[0][1]
        self.assertIn('HEAD SHAMPOO', prompt)
        self.assertIn(HAIR, prompt)
        self.assertIn('Acme', prompt)
        self.assertNotIn('100', prompt.replace(HAIR, '').replace(PET, '').replace(VIT, '').replace(FAM, ''))

    def test_brick_outside_shortlist_discarded(self):
        _, row, _ = self.ask({'brick': '99999999', 'confidence': 'high'})
        self.assertEqual((row.source, row.brick), ('none', ''))
        self.assertIn(gpc_ai.NOT_LISTED, row.error)

    def test_unknown_brick_discarded(self):
        with mock.patch('apps.tax_invoicing.gpc.known', return_value=False):
            _, row, _ = self.ask({'brick': HAIR, 'confidence': 'high'})
        self.assertEqual(row.source, 'none')
        self.assertIn(gpc_ai.NOT_KNOWN, row.error)

    def test_malformed_answer(self):
        for answer in ({'brick': 'abc'}, {'other': 1}, 'not json'):
            TaxBrickSuggestion.objects.all().delete()
            _, row, _ = self.ask(answer)
            self.assertEqual((row.source, row.error), ('none', gpc_ai.BAD_ANSWER), answer)

    def test_bad_second_and_confidence_dropped(self):
        _, row, _ = self.ask({'brick': HAIR, 'second': '99999999', 'confidence': 'sure'})
        self.assertEqual((row.source, row.second, row.confidence), ('ai', '', ''))

    def test_provider_returns_nothing(self):
        _, row, _ = self.ask({}, model='')
        self.assertEqual((row.source, row.error), ('none', gpc_ai.NO_ANSWER))

    def test_provider_raises_is_stored(self):
        p = self.item()
        with mock.patch(COMPLETE, side_effect=TimeoutError('x')):
            row = gpc_ai.suggest_one(p)
        self.assertEqual(row.source, 'none')
        self.assertIn(gpc_ai.NO_ANSWER, row.error)

    @mock.patch(COMPLETE)
    def test_medicine_skipped(self, complete):
        p = self.item(mtype='Medicine')
        self.assertIsNone(gpc_ai.suggest_one(p))
        complete.assert_not_called()

    @mock.patch(COMPLETE)
    def test_learned_skipped(self, complete):
        p = self.item(gpc_code=VIT)
        self.assertIsNone(gpc_ai.suggest_one(p))
        complete.assert_not_called()

    def test_asking_again_overwrites(self):
        p, _, _ = self.ask({'brick': HAIR, 'confidence': 'low'})
        with mock.patch(COMPLETE, return_value=({}, '')):
            gpc_ai.suggest_one(p)
        self.assertEqual(TaxBrickSuggestion.objects.filter(profile=p).count(), 1)
        self.assertEqual(TaxBrickSuggestion.objects.get(profile=p).source, 'none')


class ShortlistTests(Base):
    def test_family_bricks_then_word_matches_segments_first(self):
        p = self.item()
        for i in range(3):
            other = self.item(name=f'OTHER {i}')
            TaxCodingDecision.objects.create(profile=other, decision='code', brick=FAM)
        codes = [b['code'] for b in gpc_ai.shortlist(p.item)]
        self.assertEqual(codes, [FAM, HAIR, PET])     # VIT shares no word; segment 53 before segment 10
        hair = next(b for b in gpc_ai.shortlist(p.item) if b['code'] == HAIR)
        self.assertEqual(hair['name'], 'Hair Shampoo')
        self.assertLessEqual(len(hair['definition']), gpc_ai.DEFINITION_CHARS)

    def test_eta_family_bricks_count(self):
        p = self.item()
        for i in range(2):
            other = self.item(name=f'OTHER {i}')
            EtaCodeUsage.objects.create(system='production', code_type='EGS', item_code=f'EG-{other.softech_itemcode}',
                                        status='Approved', gpc=VIT, itemcode=other.softech_itemcode)
        self.assertEqual(gpc_ai.shortlist(p.item)[0]['code'], VIT)

    def test_limit(self):
        p = self.item()
        self.assertEqual(len(gpc_ai.shortlist(p.item, limit=1)), 1)

    def test_fallback_without_gs1(self):
        TaxGpcBrick.objects.exclude(source='workbook').delete()
        brick('10000500', 'Owner Healthcare', '51000000', source='workbook')
        brick('10000600', 'Owner Tools', '70000000', source='workbook')
        p = self.item()
        self.assertEqual([b['code'] for b in gpc_ai.shortlist(p.item)], ['10000500', FAM])


@ON
class RunTests(Base):
    def test_biggest_value_first_and_filters(self):
        small = self.item(name='SMALL SHAMPOO', value=10)
        big = self.item(name='BIG SHAMPOO', value=900)
        mid = self.item(name='MID SHAMPOO', value=500)
        self.item(name='MED', mtype='Medicine', value=5000)
        self.item(name='SHEET', gpc_code=VIT, value=5000)
        kept = self.item(name='KEPT SHAMPOO', value=5000)
        TaxCodingDecision.objects.create(profile=kept, decision='keep_out')
        fresh = self.item(name='FRESH SHAMPOO', value=5000)
        TaxBrickSuggestion.objects.create(profile=fresh, source='none', asked_at=timezone.now() - dt.timedelta(days=5))
        old = self.item(name='OLD SHAMPOO', value=50)
        TaxBrickSuggestion.objects.create(profile=old, source='none', asked_at=timezone.now() - dt.timedelta(days=40))

        self.assertEqual([p.pk for p in gpc_ai.pending()], [big.pk, mid.pk, old.pk, small.pk])
        asked = []

        def answer(item, prompt):
            asked.append(item.name)
            return ({'brick': HAIR, 'confidence': 'medium'}, 'm') if item.name != 'MID SHAMPOO' else ({}, '')
        with mock.patch(COMPLETE, side_effect=answer):
            counts = gpc_ai.run(limit=3)
        self.assertEqual(asked, ['BIG SHAMPOO', 'MID SHAMPOO', 'OLD SHAMPOO'])
        self.assertEqual(counts, {'suggested': 2, 'none': 1})
        self.assertEqual(TaxBrickSuggestion.objects.get(profile=mid).error, gpc_ai.NO_ANSWER)

    def test_one_item_failing_does_not_stop_the_job(self):
        a = self.item(name='A SHAMPOO', value=900)
        self.item(name='B SHAMPOO', value=100)
        real = gpc_ai.suggest_one

        def flaky(profile):
            if profile.pk == a.pk:
                raise RuntimeError('db')
            return real(profile)
        with mock.patch.object(gpc_ai, 'suggest_one', side_effect=flaky), \
                mock.patch(COMPLETE, return_value=({'brick': HAIR}, 'm')):
            counts = gpc_ai.run()
        self.assertEqual(counts, {'errors': 1, 'suggested': 1})

    def test_command_one_item(self):
        p = self.item()
        out = StringIO()
        with mock.patch(COMPLETE, return_value=({'brick': HAIR, 'confidence': 'high'}, 'm')):
            call_command('suggest_bricks', itemcode=p.softech_itemcode, stdout=out)
        self.assertIn(f'ai {HAIR} high', out.getvalue())

    def test_scheduler_job_runs_quietly(self):
        from apps.sync import tasks
        self.item()
        with mock.patch(COMPLETE, return_value=({}, '')):
            tasks._run_gpc_ai_suggest()
        self.assertEqual(TaxBrickSuggestion.objects.get().source, 'none')


@ON
class OutageTests(Base):
    def test_provider_outage_stops_after_five_and_items_stay_pending(self):
        profiles = [self.item(name=f'S{i} SHAMPOO', value=100 + i) for i in range(8)]
        with mock.patch(COMPLETE, return_value=({}, '')) as complete:
            counts = gpc_ai.run()
        self.assertEqual(complete.call_count, gpc_ai.OUTAGE_STREAK)
        self.assertEqual(counts, {'none': 5, 'stopped': 'provider'})
        self.assertEqual({p.pk for p in gpc_ai.pending()}, {p.pk for p in profiles})

    def test_a_real_answer_resets_the_streak(self):
        for i in range(7):
            self.item(name=f'S{i} SHAMPOO', value=100 - i)
        answers = iter([({}, '')] * 4 + [({'brick': HAIR}, 'm')] + [({}, '')] * 2)
        with mock.patch(COMPLETE, side_effect=lambda item, prompt: next(answers)):
            counts = gpc_ai.run()
        self.assertEqual(counts, {'none': 6, 'suggested': 1})

    def test_answered_none_stays_fresh(self):
        p = self.item()
        with mock.patch(COMPLETE, return_value=({'brick': '99999999'}, 'm')):
            gpc_ai.suggest_one(p)
        self.assertEqual(gpc_ai.pending(), [])

    def test_medicine_linked_by_item_id_not_pending(self):
        p = self.item(mtype='Medicine')
        other = TaxItemProfile.objects.create(softech_itemcode='ZLINK', item=p.item)
        EtaReconUncodedItem.objects.create(system='production', softech_branchcode='01', day=dt.date(2026, 11, 1),
                                           itemcode='ZLINK', docs=1, qty=1, value=Decimal(999))
        self.assertNotIn(other.pk, [x.pk for x in gpc_ai.pending()])

    def test_shortlist_failure_labelled(self):
        p = self.item()
        with mock.patch.object(gpc_ai, 'shortlist', side_effect=ValueError('x')), mock.patch(COMPLETE) as complete:
            row = gpc_ai.suggest_one(p)
        complete.assert_not_called()
        self.assertEqual(row.error, f'{gpc_ai.SHORTLIST_ERROR} (ValueError)')
