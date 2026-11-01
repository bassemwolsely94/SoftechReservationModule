"""
W2 نواقص writer: SOFTECH's own values are read before our first change and put back
on un-flag / retrieve (never a fixed '0'), every write is verified, a missing item is
not marked synced, and the audit carries the real before → after. SOFTECH is faked.
"""
from unittest import mock

from django.test import TestCase, override_settings

from apps.purchasing import shortage_writer as sw
from .factories import make_item


class _FakeItems:
    """A one-table SOFTECH: {itemcode: {itemmodified, itemcode_alt2, itemnomoreuse}}."""

    def __init__(self, rows):
        self.rows = rows

    def connection(self):
        db = self

        class Cur:
            def __init__(self):
                self._row = None

            def execute(self, sql, params):
                code = str(params[-1])
                if sql.lstrip().upper().startswith('SELECT'):
                    r = db.rows.get(code)
                    self._row = (r['itemmodified'], r['itemcode_alt2'], r['itemnomoreuse']) if r else None
                    return
                r = db.rows.get(code)
                if r is None:
                    return
                r['itemmodified'] = params[0]
                ours = params[1]
                if "CASE WHEN" in sql:
                    if r['itemcode_alt2'] == ours:
                        r['itemcode_alt2'] = ''
                else:
                    r['itemcode_alt2'] = ours
                if 'itemnomoreuse = ?' in sql:
                    r['itemnomoreuse'] = params[2]

            def fetchone(self):
                return self._row

        conn = mock.MagicMock()
        conn.cursor.side_effect = Cur
        return conn


@override_settings(SHORTAGE_SOFTECH_WRITE_ENABLED=True, WRITER_INSTANCE=True)
class ShortageRestoreTests(TestCase):
    def setUp(self):
        self.item = make_item(softech_id='55501')

    def _run(self, rows, **state):
        fake = _FakeItems(rows)
        for k, v in state.items():
            setattr(self.item, k, v)
        with mock.patch('config.sybase.get_sybase_connection', side_effect=fake.connection), \
             mock.patch('core.softech_audit.audit_softech_write') as audit:
            ok = sw.push_item(self.item)
        self.item.refresh_from_db()
        return ok, audit

    def test_unflag_restores_a_hand_set_flag(self):
        rows = {'55501': {'itemmodified': '1', 'itemcode_alt2': 'يدوى', 'itemnomoreuse': '0'}}
        ok, audit = self._run(rows, in_shortage=True)
        self.assertTrue(ok)
        self.assertEqual(self.item.shortage_softech_before, {'itemmodified': '1', 'itemnomoreuse': '0'})
        self.assertEqual(audit.call_args.kwargs['before']['itemmodified'], '1')
        ok, _ = self._run(rows, in_shortage=False)
        self.assertTrue(ok)
        self.assertEqual(rows['55501']['itemmodified'], '1')        # hand-set flag survives our undo
        self.assertIsNone(self.item.shortage_softech_before)

    def test_unflag_of_a_clean_item_clears_it(self):
        rows = {'55501': {'itemmodified': '0', 'itemcode_alt2': '', 'itemnomoreuse': '0'}}
        self._run(rows, in_shortage=True)
        self.assertEqual(rows['55501']['itemmodified'], '1')
        self._run(rows, in_shortage=False)
        self.assertEqual(rows['55501']['itemmodified'], '0')

    def test_retrieve_restores_supply_state_from_before(self):
        rows = {'55501': {'itemmodified': '0', 'itemcode_alt2': '', 'itemnomoreuse': '1'}}   # already موقوف by hand
        self._run(rows, in_shortage=False, shortage_dismissed=True, shortage_dismiss_reason='obsolete')
        self.assertTrue(self.item.shortage_supply_suspended)
        self._run(rows, in_shortage=False, shortage_dismissed=False, shortage_dismiss_reason='')
        self.assertEqual(rows['55501']['itemnomoreuse'], '1')       # stays موقوف as it was before us
        self.assertFalse(self.item.shortage_supply_suspended)

    def test_missing_item_is_not_marked_synced(self):
        ok, audit = self._run({}, in_shortage=True)
        self.assertFalse(ok)
        self.assertFalse(self.item.shortage_softech_synced)
        self.assertIn('غير موجود', self.item.shortage_softech_error)
        audit.assert_not_called()
