"""
D-09 (owner approved 2026-11-19; full audit S-11 / BE-14): the price-change writer re-reads the
item from SOFTECH inside its own transaction and writes with a compare-and-set.

    match                    -> one UPDATE, committed, executed
    mismatch                 -> no UPDATE, request "changed in SOFTECH", both values kept, audited
    pack size / VAT changed  -> derived prices recomputed from the LIVE row, not our mirror
    retry                    -> already at target: no second UPDATE, executed
    row count 0              -> rolled back, failed, never success
    rollback probe           -> the same statements, always ROLLBACK, SOFTECH unchanged

SOFTECH is never reached: _ItemsTable is a fake `items` row with a fake transaction.
"""
import re
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.audit.models import AuditLog
from apps.discount_approvals.models import ItemPriceChangeRequest as Req
from apps.discount_approvals.services import _cas_write, _update_count, execute_price_change
from apps.tests.factories import make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

BASE = '/api/pricing-approvals/'
WRITES_ON = dict(WRITER_INSTANCE=True, PRICING_SOFTECH_WRITE_ENABLED=True)
_COND = re.compile(r'ABS\(ISNULL\((\w+), 0\) - \?\) <= ([\d.]+)')


class _ItemsTable:
    """One SOFTECH items row behind a fake cursor. BEGIN/COMMIT/ROLLBACK TRAN snapshot and restore
    it; SELECT answers the named columns; UPDATE evaluates the SET list and the WHERE guards the
    way ASE would, and reports its row count. `force_rowcount` fakes a driver answering 0;
    `after_select` runs once after the first SELECT (another user editing SOFTECH meanwhile)."""

    def __init__(self, **row):
        self.row = dict(row)
        self.updates, self.stmts, self.rowcount = 0, [], -1
        self.force_rowcount, self.after_select = None, None
        self._snap, self._last = None, None

    def execute(self, sql, params=None):
        head = sql.split()[0].upper()
        self.stmts.append(head)
        params = list(params or [])
        if head == 'BEGIN':
            self._snap = dict(self.row)
        elif head == 'COMMIT':
            self._snap = None
        elif head == 'ROLLBACK':
            self.row, self._snap = self._snap, None
        elif head == 'SELECT':
            cols = [c.strip().lower() for c in sql.split('SELECT', 1)[1].split('FROM')[0].split(',')]
            if cols == ['*']:
                cols = list(self.row)
            self.description = [(c,) for c in cols]
            self._last = tuple(self.row.get(c) for c in cols) if self.row else None
            if self.after_select:
                hook, self.after_select = self.after_select, None
                hook(self.row)
        elif head == 'UPDATE':
            set_part, where_part = sql.split(' SET ', 1)[1].split(' WHERE ', 1)
            sets = {}
            for part in set_part.split(', '):
                col, val = [x.strip() for x in part.split('=', 1)]
                sets[col.lower()] = params.pop(0) if val == '?' else val
            ok = True
            for cond in where_part.split(' AND '):
                m = _COND.match(cond.strip())
                if m:
                    ok &= abs(float(self.row.get(m.group(1)) or 0) - params.pop(0)) <= float(m.group(2))
                else:
                    assert cond.strip() == 'itemcode = ?', cond
                    ok &= self.row['itemcode'] == params.pop(0)
            assert not params, f'unused params {params}'
            self.rowcount = 1 if ok else 0
            if ok:
                self.updates += 1
                self.row.update(sets)
            if self.force_rowcount is not None:
                self.rowcount = self.force_rowcount
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self._last

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur, self.closed = cur, False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True


def _live(**kw):
    """SOFTECH row in its own units: pack 3, VAT 14 %, pack price 90."""
    row = dict(itemcode='CAS01', packqty=3, itemsalestaxp=14.0, itemsaleprice=90.0,
               itemsaleprice_tax=102.6, unitsaleprice=30.0, pharmacydiscp=10.0,
               additionaldiscp=0.0, specialdiscp=0.0, posdiscp=0.0,
               usercode='OLD', itemlastupdate='before')
    row.update(kw)
    return _ItemsTable(**row)


class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.item = make_item(name='CAS item', softech_id='CAS01')
        self.item.pack_qty, self.item.sale_tax_pct, self.item.pack_price = 3, Decimal('14'), Decimal('90')
        self.item.save()
        self.admin_user, profile, _ = make_user('cas_admin', role='admin', access_all=True)
        profile.softech_user_id, profile.softech_username = 'U9', 'cas admin'
        profile.save()
        self.admin = bearer_client(self.admin_user)
        self.pharm_user = make_user('cas_pharm', role='pharmacist')[0]

    def tearDown(self):
        module_access.clear_cache()

    def _req(self, new=None, status=Req.STATUS_PENDING):
        return Req.objects.create(
            item=self.item, requested_by=self.pharm_user, status=status, reason='d09',
            old_values={'pack_price': '90.000', 'pharmacy_discp': '10.00', 'pos_discp': '0',
                        'additional_discp': '0', 'special_discp': '0',
                        'unit_price': '30.0000', 'pack_price_tax': '102.6000'},
            new_values=new or {'pack_price': '100'})

    def _approve(self, req, table):
        conn = _Conn(table)
        with mock.patch('config.sybase.get_sybase_connection', return_value=conn) as connect:
            r = self.admin.post(f'{BASE}{req.pk}/approve/', {}, format='json')
        if r.status_code in (400, 409):             # refused before SOFTECH: never connected
            connect.assert_not_called()
        else:
            self.assertTrue(conn.closed, 'connection left open')
        req.refresh_from_db()
        return r


@override_settings(**WRITES_ON)
class CompareAndSetTests(_Base):

    def test_match_writes_one_update_and_commits(self):
        table = _live()
        req = self._req()
        r = self._approve(req, table)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(table.updates, 1)
        self.assertEqual(table.stmts, ['BEGIN', 'SELECT', 'UPDATE', 'SELECT', 'COMMIT'])
        self.assertEqual(table.row['itemsaleprice'], 100.0)
        self.assertEqual(table.row['unitsaleprice'], 33.3333)
        self.assertEqual(table.row['itemsaleprice_tax'], 114.0)
        self.assertEqual(table.row['usercode'], 'U9')
        self.assertEqual(req.status, Req.STATUS_EXECUTED)
        self.assertEqual(req.executed_values['_hq'], 'ok')
        self.assertEqual(req.softech_conflict, {})
        self.assertTrue(AuditLog.objects.filter(action='softech_price_change_written').exists())

    def test_mismatch_writes_nothing_and_flags_both_values(self):
        table = _live(itemsaleprice=95.0)           # someone set 95 in SOFTECH after the request
        req = self._req()
        r = self._approve(req, table)
        self.assertEqual(r.status_code, 207)
        self.assertEqual(table.updates, 0)
        self.assertNotIn('UPDATE', table.stmts)
        self.assertEqual(table.stmts[-1], 'ROLLBACK')
        self.assertEqual(table.row['itemsaleprice'], 95.0)
        self.assertEqual(req.status, Req.STATUS_SOFTECH_CHANGED)
        self.assertEqual(req.softech_conflict['fields'],
                         {'pack_price': {'approved': '90.000', 'softech': '95.0'}})
        self.assertIn('95.0', req.erp_error)
        self.assertEqual(r.json()['softech_conflict']['fields']['pack_price']['softech'], '95.0')
        self.assertTrue(AuditLog.objects.filter(action='softech_price_change_conflict').exists())
        self.item.refresh_from_db()
        self.assertEqual(self.item.pack_price, Decimal('90.000'))   # our copy untouched

    def test_unrequested_field_drift_is_not_a_conflict(self):
        # a discount changed in SOFTECH; the request only touches the pack price -> still written
        table = _live(pharmacydiscp=12.0)
        req = self._req()
        self.assertEqual(self._approve(req, table).status_code, 200)
        self.assertEqual(table.updates, 1)
        self.assertEqual(table.row['pharmacydiscp'], 12.0)

    def test_pack_and_vat_changed_in_softech_recompute_from_live(self):
        # our mirror says pack 3 / VAT 14 %; SOFTECH now holds pack 4 / VAT 5 %
        table = _live(packqty=4, itemsalestaxp=5.0)
        req = self._req()
        self.assertEqual(self._approve(req, table).status_code, 200)
        self.assertEqual(table.updates, 1)
        self.assertEqual(table.row['unitsaleprice'], 25.0)          # 100 / 4, not 100 / 3
        self.assertEqual(table.row['itemsaleprice_tax'], 105.0)     # 100 x 1.05, not x 1.14
        self.assertEqual(req.executed_values['unit_price'], '25.0000')
        self.assertEqual(req.executed_values['_live_pack_qty'], '4')
        self.item.refresh_from_db()
        self.assertEqual((self.item.pack_qty, self.item.sale_tax_pct), (4, Decimal('5.00')))

    def test_retry_is_idempotent(self):
        table = _live()
        req = self._req()
        self.assertEqual(self._approve(req, table).status_code, 200)
        self.assertEqual(table.updates, 1)
        # the reply was lost: the request reads "failed" though SOFTECH holds the change
        Req.objects.filter(pk=req.pk).update(status=Req.STATUS_FAILED)
        self.assertEqual(self._approve(req, table).status_code, 200)
        self.assertEqual(table.updates, 1, 'a retry wrote SOFTECH a second time')
        self.assertEqual(req.status, Req.STATUS_EXECUTED)
        self.assertEqual(req.executed_values['_hq'], 'already_applied')
        self.assertEqual(AuditLog.objects.filter(action='softech_price_change_written').count(), 1)

    def test_executed_request_cannot_be_approved_again(self):
        table = _live()
        req = self._req()
        self._approve(req, table)
        self.assertEqual(self._approve(req, table).status_code, 400)
        self.assertEqual(table.updates, 1)

    def test_lost_claim_race_returns_409_without_writing(self):
        table, req = _live(), self._req()
        real_filter = Req.objects.filter

        def other_approver_won(*a, **kw):          # another approval claimed it first
            Req.objects.exclude(pk=-1).filter(pk=req.pk).update(status=Req.STATUS_APPROVED)
            return real_filter(*a, **kw)
        with mock.patch.object(Req.objects, 'filter', side_effect=other_approver_won), \
                mock.patch('config.sybase.get_sybase_connection', return_value=_Conn(table)):
            r = self.admin.post(f'{BASE}{req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(table.updates, 0)
        self.assertEqual(table.stmts, [])

    def test_rowcount_zero_is_flagged_not_success(self):
        table = _live()
        table.force_rowcount = 0
        req = self._req()
        r = self._approve(req, table)
        self.assertEqual(r.status_code, 207)
        self.assertEqual(req.status, Req.STATUS_FAILED)
        self.assertIn('لم يُحدَّث أي صف', req.erp_error)
        self.assertEqual(table.stmts[-1], 'ROLLBACK')
        self.assertNotIn('COMMIT', table.stmts)
        self.assertEqual(table.row['itemsaleprice'], 90.0)          # rolled back
        self.assertTrue(AuditLog.objects.filter(action='softech_price_change_refused').exists())

    def test_change_between_read_and_update_hits_the_sql_guard(self):
        # SOFTECH edited after our read: the UPDATE's own WHERE matches nothing (row count 0)
        table = _live()
        table.after_select = lambda row: row.update(itemsaleprice=97.0)
        req = self._req()
        self._approve(req, table)
        self.assertEqual(table.updates, 0)
        self.assertEqual(req.status, Req.STATUS_FAILED)
        self.assertNotIn('COMMIT', table.stmts)

    def test_vat_changed_between_read_and_update_hits_the_sql_guard(self):
        table = _live()
        table.after_select = lambda row: row.update(itemsalestaxp=0.0)
        req = self._req()
        self._approve(req, table)
        self.assertEqual(table.updates, 0)
        self.assertEqual(req.status, Req.STATUS_FAILED)

    def test_discount_only_request_has_no_pack_guard(self):
        table = _live(packqty=6)
        req = self._req(new={'pos_discp': '7'})
        self.assertEqual(self._approve(req, table).status_code, 200)
        self.assertEqual(table.row['posdiscp'], 7.0)
        self.assertEqual(table.row['unitsaleprice'], 30.0)          # nothing derived

    def test_item_missing_in_softech_fails(self):
        table = _live()
        table.row = {}                              # SELECT finds nothing
        req = self._req()
        self._approve(req, table)
        self.assertEqual(req.status, Req.STATUS_FAILED)
        self.assertEqual(table.updates, 0)

    def test_softech_changed_request_can_be_closed(self):
        req = self._req()
        self._approve(req, _live(itemsaleprice=95.0))
        r = self.admin.post(f'{BASE}{req.pk}/reject/', {'notes': 'stale'}, format='json')
        self.assertEqual(r.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, Req.STATUS_REJECTED)
        # and it is not approvable: a fresh request on the current value is the way
        self.assertEqual(self._approve(self._req(status=Req.STATUS_SOFTECH_CHANGED),
                                       _live()).status_code, 400)

    def test_switch_off_writes_nothing(self):
        req = self._req()
        with override_settings(PRICING_SOFTECH_WRITE_ENABLED=False), \
                mock.patch('config.sybase.get_sybase_connection') as connect:
            self.assertFalse(execute_price_change(req, erp_usercode='U9'))
        connect.assert_not_called()


class RollbackProbeTests(_Base):
    """The probe path: same statements, commit=False -> always rolled back."""

    def test_probe_rolls_back_and_leaves_softech_unchanged(self):
        table = _live()
        before = dict(table.row)
        res = _cas_write(table, self._req(), 'U9', commit=False)
        self.assertEqual(res['outcome'], 'written')
        self.assertFalse(res['committed'])
        self.assertEqual(res['rowcount'], 1)
        self.assertEqual(res['readback'], {'pack_price': '100.0', 'unit_price': '33.3333',
                                           'pack_price_tax': '114.0'})
        self.assertEqual(table.stmts, ['BEGIN', 'SELECT', 'UPDATE', 'SELECT', 'ROLLBACK'])
        self.assertEqual(table.row, before)


class ProbeCommandTests(_Base):

    def test_plan_only_never_connects(self):
        req = self._req()
        with mock.patch('config.sybase.get_sybase_connection') as connect:
            call_command('price_change_probe', '--request', str(req.pk), stdout=StringIO())
        connect.assert_not_called()

    def test_run_rolls_back_and_reports_changed_columns(self):
        table = _live()
        before = dict(table.row)
        req = self._req()
        out = StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn(table)):
            call_command('price_change_probe', '--request', str(req.pk), '--usercode', 'U9',
                         '--run', stdout=out)
        text = out.getvalue()
        self.assertIn('"row_restored_after_rollback": true', text)
        self.assertIn('"rowcount_reported": 1', text)
        self.assertIn('"itemsaleprice"', text)                  # a column changed inside the tran
        self.assertEqual(table.row, before)
        self.assertEqual(table.updates, 1)                       # ran once, then rolled back
        self.assertIn('ROLLBACK', table.stmts)
        self.assertNotIn('COMMIT', table.stmts)
        req.refresh_from_db()
        self.assertEqual(req.status, Req.STATUS_PENDING)         # our row never touched

    def test_item_probe_uses_an_unsaved_request(self):
        table = _live()
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn(table)):
            call_command('price_change_probe', '--item', 'CAS01', '--set', 'pos_discp=7', '--run',
                         stdout=StringIO())
        self.assertFalse(Req.objects.exists())
        self.assertEqual(table.row['posdiscp'], 0.0)


class UpdateCountTests(SimpleTestCase):

    def test_jdbc_update_count_when_cursor_has_no_rowcount(self):
        cur = mock.Mock(spec=['_stmt'])
        cur._stmt.getUpdateCount.return_value = 1
        self.assertEqual(_update_count(cur), 1)

    def test_unknown_count_is_none(self):
        self.assertIsNone(_update_count(mock.Mock(spec=[])))
