from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.audit.models import AuditLog
from apps.rpa.dld import decode_dld, parse_dld, recipe_from_dld
from apps.rpa.models import RpaRecipe, RpaScreen
from apps.users.models import StaffProfile

FIXTURE = Path(__file__).parent / 'fixtures' / 'rpa' / 'issue_125.dld'
KEYS, DATA = 'keys', 'data'
TITLE = 'SofTech Smart Business® - MINI - [إذن صـرف للفــروع]'


class ParseDldTests(SimpleTestCase):
    def test_parse_owner_issue_template(self):
        t = parse_dld(FIXTURE.read_text(encoding='utf-8-sig'))
        self.assertEqual(t.window_title, TITLE)
        self.assertEqual(t.cell_delay, Decimal('0.2'))
        self.assertEqual(t.form_delay, Decimal('0.25'))
        self.assertEqual(t.column_kinds, [KEYS, DATA, KEYS, KEYS, KEYS, DATA, KEYS, DATA, KEYS, KEYS, KEYS])
        self.assertEqual(t.rows[0], [r'\{F2}', '52', r'\{ENTER}', r'\{ENTER}', r'\{TAB}', '1/5/25',
                                     r'\{TAB}', '1', r'\{ENTER}', r'\{ENTER}', r'\{ENTER}'])
        self.assertEqual(len(t.rows), 5)          # blank rows dropped

    def test_bom_is_stripped(self):
        t = parse_dld(FIXTURE.read_bytes().decode('utf-8'))   # BOM kept in the text
        self.assertEqual(t.cell_delay, Decimal('0.2'))

    def test_missing_window_raises(self):
        text = FIXTURE.read_text(encoding='utf-8-sig').replace('Window=', 'Other=')
        with self.assertRaises(ValueError):
            parse_dld(text)

    def test_decode_accepts_legacy_ansi_window_line(self):
        raw = FIXTURE.read_bytes()
        ansi = raw.replace('إذن صـرف للفــروع'.encode('utf-8'), 'إذن صـرف للفــروع'.encode('cp1256')) \
                  .replace('®'.encode('utf-8'), '®'.encode('cp1256'))
        self.assertNotEqual(raw, ansi)
        self.assertEqual(parse_dld(decode_dld(ansi)).window_title, TITLE)


class RecipeFromDldTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='rpa_t3', password='x')
        self.staff = StaffProfile.objects.get_or_create(user=user, defaults={'role': 'admin'})[0]
        self.screen = RpaScreen.objects.get(key='issue_125')
        self.t = parse_dld(FIXTURE.read_text(encoding='utf-8-sig'))

    def _make(self, **kw):
        kw.setdefault('field_map', ['itemcode', 'expiry', 'qty'])
        return recipe_from_dld(self.t, screen=self.screen, created_by=self.staff, **kw)

    def test_recipe_from_template_maps_fields_in_order(self):
        r = self._make(source_filename='Dataload اذن الصرف.dld')
        self.assertEqual(r.line_cells[0], {'kind': 'keys', 'value': r'\{F2}'})
        self.assertEqual(r.line_cells[1], {'kind': 'field', 'value': 'itemcode'})
        self.assertEqual(r.line_cells[5], {'kind': 'field', 'value': 'expiry'})
        self.assertEqual(r.line_cells[7], {'kind': 'field', 'value': 'qty'})
        self.assertEqual(len(r.line_cells), 11)
        self.assertEqual((r.status, r.version), ('draft', 1))
        self.assertEqual(r.window_title, TITLE)
        self.assertEqual(r.cell_delay, Decimal('0.2'))
        self.assertEqual(r.source_filename, 'Dataload اذن الصرف.dld')
        self.assertTrue(RpaRecipe.objects.filter(pk=r.pk).exists())

    def test_version_is_max_plus_one(self):
        self.assertEqual(self._make().version, 1)
        self.assertEqual(self._make().version, 2)

    def test_audited(self):
        r = self._make()
        log = AuditLog.objects.get(action='rpa_recipe_imported')
        self.assertEqual(log.object_id, str(r.pk))
        self.assertEqual(log.user_id, self.staff.pk)

    def test_field_map_length_must_equal_data_columns(self):
        for bad in (['itemcode', 'expiry'], ['itemcode', 'expiry', 'qty', 'x']):
            with self.assertRaises(ValueError):
                self._make(field_map=bad)
        self.assertEqual(RpaRecipe.objects.count(), 0)
