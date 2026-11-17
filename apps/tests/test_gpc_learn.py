"""Learned GPC brick suggestions (batch S2): people's decisions, ETA's approved codes, the owner's sheet, the medicine
default; and the sheet import command."""
import os
import tempfile

import openpyxl
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Item
from apps.tax_invoicing import gpc_learn
from apps.tax_invoicing.models import (EtaCodeUsage, TaxAuditEvent, TaxCodingDecision, TaxGpcBrick,
                                       TaxItemProfile)
from apps.tests.test_tax_invoicing import Fixture

A, B, C = '10000111', '10000222', '10000333'


class LearnedTests(Fixture, TestCase):
    def setUp(self):
        self.build('gl')
        self.n = 0

    def profile(self, family='Fam', mtype='Cosmetics', gpc_code=''):
        self.n += 1
        code = f'G{self.n:04d}'
        item = Item.objects.create(softech_id=code, name=f'Item {code}', family_name=family, medicine_type_name=mtype)
        return TaxItemProfile.objects.create(softech_itemcode=code, item=item, gpc_code=gpc_code)

    def decided(self, brick, family='Fam', decision='code'):
        p = self.profile(family)
        TaxCodingDecision.objects.create(profile=p, decision=decision, brick=brick)
        return p

    def on_eta(self, brick, family='Fam', status='Approved', system='production'):
        p = self.profile(family)
        EtaCodeUsage.objects.create(system=system, code_type='EGS', item_code=f'EG-1-{p.softech_itemcode}',
                                    status=status, gpc=brick, itemcode=p.softech_itemcode)
        return p

    def test_decisions_family_brick(self):
        for _ in range(3):
            self.decided(A)
        target = self.profile()
        got = gpc_learn.learned([target])[target.pk]
        self.assertEqual((got['code'], got['source'], got['n']), (A, 'decisions', 3))
        self.assertEqual(got['share'], 1.0)
        self.assertIn('Fam', got['basis'])

    def test_decisions_need_three(self):
        self.decided(A)
        self.decided(A)
        target = self.profile()
        self.assertNotIn(target.pk, gpc_learn.learned([target]))

    def test_mixed_family_60_40_falls_through(self):
        for _ in range(3):
            self.decided(A)
        for _ in range(2):
            self.decided(B)
        target = self.profile(gpc_code=C)
        got = gpc_learn.learned([target])[target.pk]
        self.assertEqual((got['code'], got['source']), (C, 'sheet'))

    def test_eighty_percent_is_enough(self):
        for _ in range(4):
            self.decided(A)
        self.decided(B)
        target = self.profile()
        got = gpc_learn.learned([target])[target.pk]
        self.assertEqual((got['code'], got['share'], got['n']), (A, 0.8, 5))

    def test_keep_out_and_blank_brick_ignored(self):
        for _ in range(3):
            self.decided(A, decision='keep_out')
        for _ in range(3):
            self.decided('')
        target = self.profile()
        self.assertNotIn(target.pk, gpc_learn.learned([target]))

    def test_other_family_ignored(self):
        for _ in range(3):
            self.decided(A, family='Other')
        target = self.profile()
        self.assertNotIn(target.pk, gpc_learn.learned([target]))

    def test_eta_family_brick(self):
        for _ in range(3):
            self.on_eta(B)
        target = self.profile()
        got = gpc_learn.learned([target])[target.pk]
        self.assertEqual((got['code'], got['source'], got['n']), (B, 'eta', 3))

    def test_eta_ignores_rejected_and_preprod(self):
        self.on_eta(B, status='Rejected')
        self.on_eta(B, system='preprod')
        self.on_eta(B)
        self.on_eta(B)
        target = self.profile()
        self.assertNotIn(target.pk, gpc_learn.learned([target]))

    def test_decisions_beat_eta(self):
        for _ in range(3):
            self.decided(A)
            self.on_eta(B)
        target = self.profile(gpc_code=C, mtype='Medicine')
        self.assertEqual(gpc_learn.learned([target])[target.pk]['source'], 'decisions')

    def test_eta_beats_sheet(self):
        for _ in range(3):
            self.on_eta(B)
        target = self.profile(gpc_code=C)
        self.assertEqual(gpc_learn.learned([target])[target.pk]['code'], B)

    def test_sheet_beats_medicine_and_zero_is_blank(self):
        sheet = self.profile(mtype='Medicine', gpc_code=C)
        zero = self.profile(mtype='Medicine', gpc_code='0')
        other = self.profile(mtype='Cosmetics', gpc_code='0')
        got = gpc_learn.learned([sheet, zero, other])
        self.assertEqual((got[sheet.pk]['code'], got[sheet.pk]['source']), (C, 'sheet'))
        self.assertEqual((got[zero.pk]['code'], got[zero.pk]['source']), (gpc_learn.MEDICINE_BRICK, 'medicine'))
        self.assertEqual(gpc_learn.MEDICINE_BRICK, '10005845')
        self.assertNotIn(other.pk, got)

    def test_profile_without_item_uses_sheet_only(self):
        p = TaxItemProfile.objects.create(softech_itemcode='GNOITEM', gpc_code=A)
        q = TaxItemProfile.objects.create(softech_itemcode='GNOITEM2')
        got = gpc_learn.learned([p, q])
        self.assertEqual(got[p.pk]['source'], 'sheet')
        self.assertNotIn(q.pk, got)

    def test_empty(self):
        self.assertEqual(gpc_learn.learned([]), {})

    def test_constant_query_count(self):
        for _ in range(3):
            self.decided(A)
            self.on_eta(B, family='Fam2')
        few = [self.profile(), self.profile(family='Fam2')]
        many = few + [self.profile(family=f'F{i}', mtype='Medicine') for i in range(10)]
        few = list(TaxItemProfile.objects.filter(pk__in=[p.pk for p in few]))
        many = list(TaxItemProfile.objects.filter(pk__in=[p.pk for p in many]))
        with CaptureQueriesContext(connection) as small:
            gpc_learn.learned(few)
        with CaptureQueriesContext(connection) as big:
            got = gpc_learn.learned(many)
        self.assertEqual(len(small), len(big))
        self.assertEqual(len([v for v in got.values() if v['source'] == 'medicine']), 10)


class LoadSheetBricksTests(Fixture, TestCase):
    def setUp(self):
        self.build('gs')
        fd, self.path = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        self.addCleanup(os.remove, self.path)

    def sheet(self, rows, title='ElRezeiky GPC Applied'):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Other'
        ws.append(['itemcode', 'أكواد الضرائب'])
        ws.append(['S1', A])
        ws = wb.create_sheet(title)
        ws.append(['itemcode', 'name', 'أكواد الضرائب'])
        for r in rows:
            ws.append(r)
        wb.save(self.path)

    def run_cmd(self):
        from io import StringIO
        out = StringIO()
        call_command('load_sheet_bricks', self.path, stdout=out)
        return out.getvalue()

    def test_fills_only_empty_and_known(self):
        TaxGpcBrick.objects.create(code=A)
        TaxGpcBrick.objects.create(code=B)
        for code, gpc_code in (('S1', ''), ('S2', '0'), ('S3', B), ('S4', ''), ('S5', ''), ('S6', '')):
            TaxItemProfile.objects.create(softech_itemcode=code, gpc_code=gpc_code)
        self.sheet([['S1', 'x', A], ['S2', 'x', 10000222.0], ['S3', 'x', A], ['S4', 'x', C],
                    ['S5', 'x', '123'], ['S6', 'x', None], ['NOPE', 'x', A]])
        out = self.run_cmd()
        got = dict(TaxItemProfile.objects.values_list('softech_itemcode', 'gpc_code'))
        self.assertEqual(got, {'S1': A, 'S2': B, 'S3': B, 'S4': '', 'S5': '', 'S6': ''})
        self.assertIn('set 2', out)
        ev = TaxAuditEvent.objects.get(action='gpc_sheet_bricks_loaded')
        self.assertEqual(ev.after['set'], {'S1': A, 'S2': B})
        self.assertEqual(ev.after['counts']['unknown_brick'], 1)
        self.assertEqual(ev.after['counts']['no_profile'], 1)
        self.assertEqual(ev.after['counts']['already_set'], 1)

    def test_missing_sheet_or_column_errors(self):
        from django.core.management.base import CommandError
        self.sheet([['S1', 'x', A]], title='Wrong')
        with self.assertRaises(CommandError):
            self.run_cmd()
