import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.rpa.keyplan import _tokens, build_keyplan, format_field, to_send_keys
from apps.rpa.models import RpaDocument, RpaJob, RpaLine, RpaRecipe, RpaScreen
from apps.tests.factories import make_branch
from apps.users.models import StaffProfile

KEYS = lambda v: {'kind': 'keys', 'value': v}
FIELD = lambda v: {'kind': 'field', 'value': v}


class KeyplanTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='rpa_t7', password='x')
        self.staff = StaffProfile.objects.get_or_create(user=user, defaults={'role': 'admin'})[0]
        self.screen = RpaScreen.objects.get(key='issue_125')
        self.recipe = RpaRecipe.objects.create(
            screen=self.screen, version=1, status='approved', created_by=self.staff,
            window_title='إذن صرف', header_checklist=['افتح الشاشة'],
            line_cells=[KEYS(r'\{F2}'), FIELD('itemcode'), KEYS(r'\{ENTER}\{ENTER}\{TAB}'),
                        FIELD('expiry'), KEYS(r'\{TAB}'), FIELD('qty'),
                        KEYS(r'\{ENTER}\{ENTER}\{ENTER}')],
            ref_cells=[FIELD('reference'), KEYS(r'\{ENTER}')],
            save_keys=[KEYS(r'\{F10}')], cancel_keys=[KEYS(r'\{ESC}')])
        self.target = make_branch('T7B', 'T7B')
        self.target.name = 'فرع المعادي'
        self.target.save()
        self.job = RpaJob.objects.create(
            screen=self.screen, branch=make_branch('T7A', 'T7A'), target_branch=self.target,
            recipe=self.recipe, created_by=self.staff, store_code='105')
        self.doc = RpaDocument.objects.create(job=self.job, seq=1)
        RpaLine.objects.create(document=self.doc, row_no=1, itemcode='52', qty=Decimal('1.00000'),
                               expiry=datetime.date(2025, 5, 1))

    def test_dataload_keys_converted(self):
        self.assertEqual(to_send_keys(r'\{ENTER}'), '{ENTER}')

    def test_specials_escaped(self):
        self.assertEqual(to_send_keys('a+b(1)'), 'a{+}b{(}1{)}')

    def test_format_field(self):
        line = self.doc.lines.get()
        self.assertEqual(format_field(line, 'qty'), '1')
        line.qty = Decimal('2.50000')
        self.assertEqual(format_field(line, 'qty'), '2.5')
        line.qty = Decimal('10.00000')
        self.assertEqual(format_field(line, 'qty'), '10')
        line.expiry = None
        self.assertEqual(format_field(line, 'expiry'), '')

    def test_line_step_matches_owner_template(self):
        plan = build_keyplan(self.doc, mode='dry_run')
        self.assertEqual(plan['steps'][0]['send'],
                         '{F2}52{ENTER}{ENTER}{TAB}1/5/25{TAB}1{ENTER}{ENTER}{ENTER}')
        self.assertEqual(plan['steps'][0]['label'], 'سطر 1')
        self.assertEqual(plan['reference'], f'RPA-{self.doc.pk}')
        self.assertEqual(plan['steps'][1]['send'], f'RPA-{self.doc.pk}{{ENTER}}')

    def test_dry_run_ends_with_cancel_never_save(self):
        plan = build_keyplan(self.doc, mode='dry_run')
        last = plan['steps'][-1]
        self.assertTrue(last['final'])
        self.assertEqual(last['label'], 'إلغاء بدون حفظ')
        self.assertEqual(last['send'], '{ESC}')
        self.assertNotIn('{F10}', ''.join(s['send'] for s in plan['steps']))
        self.assertEqual([s['i'] for s in plan['steps']], [1, 2, 3])

    def test_dry_run_requires_cancel_keys(self):
        RpaRecipe.objects.filter(pk=self.recipe.pk).update(cancel_keys=[])
        self.doc = RpaDocument.objects.get(pk=self.doc.pk)
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_live_refused_in_stage1(self):
        with self.assertRaises(PermissionError):
            build_keyplan(self.doc, mode='live')

    def test_live_allowed_only_with_everything_on(self):
        self.screen.live = True
        self.screen.save()
        with mock.patch('apps.rpa.keyplan.writer_allowed', return_value=True):
            plan = build_keyplan(self.doc, mode='live')
        self.assertEqual(plan['steps'][-1]['label'], 'حفظ')
        self.assertTrue(plan['steps'][-1]['final'])
        with mock.patch('apps.rpa.keyplan.writer_allowed', return_value=False):
            with self.assertRaises(PermissionError):
                build_keyplan(self.doc, mode='live')

    def test_checklist_names_target_branch_not_code(self):
        plan = build_keyplan(self.doc, mode='dry_run')
        text = '\n'.join(plan['checklist'])
        self.assertIn('فرع المعادي', text)
        self.assertNotIn('T7B', text)
        self.assertIn('105', text)
        self.assertIn('افتح الشاشة', text)

    def _set(self, **fields):
        RpaRecipe.objects.filter(pk=self.recipe.pk).update(**fields)
        self.doc = RpaDocument.objects.get(pk=self.doc.pk)

    def test_dry_run_refuses_save_keys_in_line_cells(self):
        self._set(line_cells=self.recipe.line_cells + [KEYS(r'\{F10}')])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_dry_run_refuses_save_keys_in_cancel_keys(self):
        self._set(cancel_keys=[KEYS(r'\{ESC}'), KEYS(r'\{F10}')])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_document_without_lines_refused(self):
        self.doc.lines.all().delete()
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_popup_answer_keys_converted(self):
        self._set(popups=[{'title': 'x', 'answer_keys': r'\{ENTER}'}])
        plan = build_keyplan(self.doc, mode='dry_run')
        self.assertEqual(plan['popups'][0]['answer_keys'], '{ENTER}')

    def test_whitespace_in_literals_and_data_is_braced(self):
        self.assertEqual(to_send_keys('a b\tc\nd'), 'a{SPACE}b{TAB}c{ENTER}d')
        RpaLine.objects.filter(document=self.doc).update(itemcode='AB 12')
        plan = build_keyplan(self.doc, mode='dry_run')
        self.assertIn('AB{SPACE}12', plan['steps'][0]['send'])
        self.assertNotIn(' ', plan['steps'][0]['send'])

    def test_reference_field_in_line_cells_refused(self):
        self._set(line_cells=[FIELD('reference')])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_line_field_in_ref_cells_refused(self):
        self._set(ref_cells=[FIELD('qty')])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_live_refused_when_save_keys_empty(self):
        self._set(save_keys=[])
        self.screen.live = True
        self.screen.save()
        with mock.patch('apps.rpa.keyplan.writer_allowed', return_value=True):
            with self.assertRaises(PermissionError):
                build_keyplan(self.doc, mode='live')

    def test_unknown_mode_refused(self):
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='bogus')

    def test_missing_recipe_refused(self):
        RpaJob.objects.filter(pk=self.job.pk).update(recipe=None)
        self.doc = RpaDocument.objects.get(pk=self.doc.pk)
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_dry_run_refuses_lowercase_save_keys(self):
        self._set(line_cells=self.recipe.line_cells + [KEYS(r'\{f10}')])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_dry_run_refuses_save_keys_split_across_steps(self):
        self._set(save_keys=[KEYS(r'\{F10}\{ENTER}')],
                  line_cells=[FIELD('itemcode'), KEYS(r'\{F10}')],
                  ref_cells=[KEYS(r'\{ENTER}')])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_dry_run_refuses_save_keys_in_popup_answer(self):
        self._set(popups=[{'title': 'x', 'answer_keys': r'\{F10}'}])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')

    def test_data_value_with_newline_or_tab_refused(self):
        for bad in ('a\nb', 'a\tb'):
            RpaLine.objects.filter(document=self.doc).update(itemcode=bad)
            with self.assertRaises(ValueError):
                build_keyplan(self.doc, mode='dry_run')

    def test_equivalent_spellings_tokenise_identically(self):
        base = _tokens('^s')
        for spelling in ('^{s}', '^S', '^(s)', '^{S}'):
            self.assertEqual(_tokens(spelling), base, spelling)
        self.assertEqual(_tokens('{VK_F10}'), _tokens('{f10 2}'))

    def test_dry_run_refuses_equivalent_spellings_of_save_key(self):
        # Recipe cells are escaped literals unless written in DataLoad form, so use that form.
        for spelling in (r'\{^}s', r'\{^}S', r'\{^}\{s}', r'\{^}\{S}'):
            self._set(save_keys=[KEYS(r'\{^}s')], line_cells=[KEYS(spelling)])
            with self.assertRaises(ValueError, msg=spelling):
                build_keyplan(self.doc, mode='dry_run')

    def test_dry_run_refuses_vk_prefixed_save_key(self):
        self._set(save_keys=[KEYS(r'\{F10}')], line_cells=[KEYS(r'\{VK_F10}')])
        with self.assertRaises(ValueError):
            build_keyplan(self.doc, mode='dry_run')
