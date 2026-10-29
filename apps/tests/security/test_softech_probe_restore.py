"""
SOFTECH write safety — investigation commands that leave changes behind (Batch 2, P-14).

Six sync investigations write test values into LIVE SOFTECH rows (HQ items replicate to
every branch) and "revert" at the end with plain sequential code:
  * a crash between the write and the revert leaves the test value in SOFTECH;
  * the reverts never put the last-editor usercode back (rows stay stamped '00099');
  * investigate_britems2 never reverts its britems marker (77) and reverts the other britems
    write with swapped columns (pharmacydiscp <- trans_time);
  * test_replication_cycle --mode plant has no restore at all, and a second plant records the
    markers as the "originals".
Every row a probe touches is now snapshotted first and put back — all columns — whatever
happens (core.softech_probe_restore.RowGuards).
"""
import datetime
import io
import json
import os
import re
import tempfile
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.branches.models import Branch

ORIG = 5.0


class _Row:
    """Any column of any row reads ORIG."""

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [ORIG] * 4
        return ORIG

    def __len__(self):
        return 4

    def __iter__(self):
        return iter([ORIG] * 4)


class _Softech:
    """One recorder shared by every fake connection (HQ and branch).

    fail_after_write: the first SELECT after the first probe UPDATE raises — the link drops.
    """

    def __init__(self, fail_after_write=True):
        self.updates = []                   # (sql, params) in order
        self.fail_after_write = fail_after_write
        self.failed = False

    def connect(self, *a, **k):
        return _Conn(self)


class _Conn:
    def __init__(self, sw):
        self.sw = sw

    def cursor(self):
        return _Cur(self.sw)

    def close(self):
        pass


class _Cur:
    description = [('c',)]

    def __init__(self, sw):
        self.sw = sw

    def execute(self, sql, params=None):
        s = sql.strip().upper()
        if s.startswith('UPDATE'):
            self.sw.updates.append((sql, list(params or [])))
        elif (s.startswith('SELECT') and self.sw.fail_after_write and not self.sw.failed
              and len(self.sw.updates) == 1):
            self.sw.failed = True
            raise RuntimeError('link dropped mid-investigation')

    def fetchone(self):
        return _Row()

    def fetchall(self):
        return []

    def close(self):
        pass


# ── the helper ────────────────────────────────────────────────────────────────

class RowGuardTests(SimpleTestCase):

    def test_restores_every_column_even_when_the_probe_crashes(self):
        from core.softech_probe_restore import RowGuards
        sw = _Softech(fail_after_write=False)
        with self.assertRaises(RuntimeError):
            with RowGuards() as guards:
                guards.track(sw.connect, 'SOFTECHDB9.dbo.items', {'itemcode': '127397'},
                             ('posdiscp', 'usercode'))
                sw.connect().cursor().execute(
                    'UPDATE SOFTECHDB9.dbo.items SET posdiscp=?, usercode=? WHERE itemcode=?',
                    [6.0, '00099', '127397'])
                raise RuntimeError('probe crashed')
        sql, params = sw.updates[-1]
        self.assertEqual(len(sw.updates), 2)
        self.assertIn('posdiscp=?', sql)
        self.assertIn('usercode=?', sql)
        self.assertEqual(params, [ORIG, ORIG, '127397'])

    def test_datetime_goes_back_as_a_literal_and_none_as_null(self):
        from core.softech_probe_restore import restore_sql
        sql, params = restore_sql(
            'SOFTECHDB9.dbo.britems', {'itemcode': '127397', 'branchcode': '160'},
            {'pharmacydiscp': 20.0, 'trans_time': datetime.datetime(2026, 6, 3, 17, 37, 35, 480000),
             'usercode': None})
        self.assertIn("trans_time=convert(datetime, '2026-06-03 17:37:35.480')", sql)
        self.assertIn('usercode=NULL', sql)
        self.assertEqual(params, [20.0, '127397', '160'])

    def test_identifiers_are_checked(self):
        from core.softech_probe_restore import restore_sql
        for bad in ('items; drop table x', 'items--', "it'ems"):
            with self.assertRaises(ValueError):
                restore_sql(bad, {'itemcode': '1'}, {'posdiscp': 1.0})
        with self.assertRaises(ValueError):
            restore_sql('items', {'itemcode': '1'}, {'pos discp': 1.0})

    def test_same_row_tracked_twice_keeps_the_first_snapshot(self):
        from core.softech_probe_restore import RowGuards
        sw = _Softech(fail_after_write=False)
        with RowGuards() as guards:
            guards.track(sw.connect, 'items', {'itemcode': '1'}, ('posdiscp',))
            again = guards.track(lambda: self.fail('second snapshot read SOFTECH'),
                                 'items', {'itemcode': '1'}, ('posdiscp',))
            self.assertEqual(again.original, {'posdiscp': ORIG})
        self.assertEqual(len(sw.updates), 1)

    def test_rows_go_back_newest_first_and_only_once(self):
        from core.softech_probe_restore import RowGuards
        sw = _Softech(fail_after_write=False)
        with RowGuards() as guards:
            guards.track(sw.connect, 'britems', {'itemcode': '1', 'branchcode': '160'}, ('pharmacydiscp',))
            guards.track(sw.connect, 'items', {'itemcode': '1'}, ('pharmacydiscp',))
            guards.restore_all()
        self.assertEqual([u[0].split()[1] for u in sw.updates], ['items', 'britems'])


# ── the six investigations ────────────────────────────────────────────────────

INVESTIGATIONS = ['investigate_britems', 'investigate_britems2', 'investigate_replication',
                  'probe_itemlastupdate', 'probe_repl_queue', 'probe_replication_source']


def _table(sql):
    return sql.split()[1].split('.')[-1].lower()


def _is_restore(sql, params):
    """A put-back: original values only — no probe stamp, no marker number, no GETDATE()."""
    set_clause = re.split(r'\bWHERE\b', sql, flags=re.I)[0]
    return ('00099' not in params
            and all(p == ORIG for p in params if not isinstance(p, str))
            and not re.search(r'=\s*\d|getdate', set_clause, re.I))


@override_settings(SOFTECH_PROBES_ENABLED=True)
class InvestigationRestoreTests(TestCase):

    def setUp(self):
        for code in ('160', '140'):
            Branch.objects.get_or_create(softech_branch_id=code, defaults={
                'name': code, 'name_ar': code, 'is_active': True,
                'db_host': f'10.0.0.{code}', 'db_port': 5000})

    def _crash_mid_run(self, command):
        sw = _Softech()
        with mock.patch('config.sybase.get_sybase_connection', sw.connect), \
                mock.patch('config.sybase.get_branch_connection', sw.connect), \
                mock.patch('time.sleep', side_effect=RuntimeError('link dropped mid-investigation')):
            try:
                call_command(command, stdout=io.StringIO())
            except Exception:
                pass
        return sw

    def test_a_crash_after_the_write_still_restores_every_row(self):
        for command in INVESTIGATIONS:
            with self.subTest(command):
                sw = self._crash_mid_run(command)
                writes = [u for u in sw.updates if not _is_restore(*u)]
                restores = [u for u in sw.updates if _is_restore(*u)]
                self.assertTrue(writes, 'the probe never wrote — the fake is too thin')
                self.assertEqual({_table(sql) for sql, _ in restores},
                                 {_table(sql) for sql, _ in writes},
                                 'a row the probe changed was never put back')

    def test_usercode_goes_back_too(self):
        for command in ('investigate_britems', 'investigate_replication', 'probe_itemlastupdate',
                        'probe_repl_queue'):
            with self.subTest(command):
                sw = _Softech(fail_after_write=False)
                with mock.patch('config.sybase.get_sybase_connection', sw.connect), \
                        mock.patch('config.sybase.get_branch_connection', sw.connect), \
                        mock.patch('time.sleep'):
                    call_command(command, stdout=io.StringIO())
                sql, params = sw.updates[-1]
                self.assertIn('usercode', sql, 'last-editor stamp left as 00099')
                self.assertNotIn('00099', params)

# ── test_replication_cycle (30-minute plant) ──────────────────────────────────

@override_settings(SOFTECH_PROBES_ENABLED=True)
class ReplicationCyclePlantTests(TestCase):

    def setUp(self):
        from apps.sync.management.commands import test_replication_cycle as cmd
        self.cmd = cmd
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, 'state.json')
        self.p = mock.patch.object(cmd, 'STATE_FILE', self.state)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def _run(self, mode, sw):
        with mock.patch('config.sybase.get_sybase_connection', sw.connect), \
                mock.patch('config.sybase.get_branch_connection', sw.connect):
            call_command('test_replication_cycle', mode=mode,
                         stdout=io.StringIO())

    def test_second_plant_refused_while_one_is_out(self):
        from django.core.management import CommandError
        with open(self.state, 'w') as f:
            json.dump({'markers': {}, 'hq_orig': {}}, f)
        with self.assertRaises(CommandError):
            self._run('plant', _Softech(fail_after_write=False))

    def test_restore_mode_puts_hq_back_when_the_markers_are_still_there(self):
        m = self.cmd
        with open(self.state, 'w') as f:
            json.dump({'item': m.ITEM, 'markers': {'pos': m.MARK_POS, 'pharm': m.MARK_PHARM,
                                                   'price': m.MARK_PRICE},
                       'hq_orig': {'pos': 11.0, 'pharm': 20.0, 'price': 48.0, 'user': '1509'}}, f)
        sw = _Softech(fail_after_write=False)
        with mock.patch.object(_Row, '__getitem__',
                               lambda self, i: [m.MARK_POS, m.MARK_PHARM, m.MARK_PRICE, '00099'][i]):
            self._run('restore', sw)
        sql, params = sw.updates[-1]
        self.assertEqual(params, [11.0, 20.0, 48.0, '1509', m.ITEM])
        self.assertFalse(os.path.exists(self.state))

    def test_restore_mode_refuses_when_someone_edited_the_item_since(self):
        from django.core.management import CommandError
        m = self.cmd
        with open(self.state, 'w') as f:
            json.dump({'item': m.ITEM, 'markers': {'pos': m.MARK_POS, 'pharm': m.MARK_PHARM,
                                                   'price': m.MARK_PRICE},
                       'hq_orig': {'pos': 11.0, 'pharm': 20.0, 'price': 48.0, 'user': '1509'}}, f)
        sw = _Softech(fail_after_write=False)          # every column reads 5.0 ≠ the markers
        with self.assertRaises(CommandError):
            self._run('restore', sw)
        self.assertEqual(sw.updates, [], 'overwrote a real edit with June originals')
        self.assertTrue(os.path.exists(self.state))
