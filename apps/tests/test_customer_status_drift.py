"""B7 step 2 — daily HQ vs branch-node check of customer status / lock / points (read-only)."""
import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from apps.customers import status_drift as SD
from apps.customers.models import CustomerStatusDrift as D

# phcode, phcodestatus, piclock, picpoints, picdied
HQ = [('100HD6038', '0', 0, 1, 0), ('06HD24310', '5', 0, 1, 0), ('07HD2044', '1', 1, 1, 0),
      ('07HD11624', '1', 0, 1, 0), ('RESET1', '1', 0, 0, 0), ('SAME', '1', 0, 1, 0), ('HQONLY', '0', 0, 1, 0)]
NODE = [('100HD6038', '1', 0, 1, 0), ('06HD24310', '1', 0, 1, 0), ('07HD2044', '1', 0, 1, 0),
        ('07HD11624', '0', 0, 1, 0), ('RESET1', '1', 0, 1, 0), ('SAME', '1', 0, 1, 0), ('NODEONLY', '0', 0, 1, 0)]


class Conn:
    def __init__(self, rows, own='140'):
        self.rows, self.own = rows, own

    def cursor(self):
        conn = self

        class C:
            def execute(self, sql, p=None):
                self.r = [(conn.own,)] if 'lastdocnumbers' in sql else list(conn.rows)

            def fetchall(self):
                return self.r
        return C()

    def close(self):
        pass


class CompareTests(TestCase):
    def test_directions(self):
        rows = {(p, f): (h, n, d) for p, f, h, n, d in SD.compare(SD.load(Conn(HQ)), SD.load(Conn(NODE)))}
        self.assertEqual(rows[('100HD6038', 'status')], ('0', '1', D.HQ_STRICTER))
        self.assertEqual(rows[('06HD24310', 'status')], ('5', '1', D.HQ_STRICTER))
        self.assertEqual(rows[('07HD2044', 'lock')], ('1', '0', D.HQ_STRICTER))
        self.assertEqual(rows[('07HD11624', 'status')], ('1', '0', D.NODE_STRICTER))
        self.assertEqual(rows[('RESET1', 'points')], ('0', '1', D.HQ_STRICTER))
        self.assertEqual(len(rows), 5)                     # SAME equal; HQONLY / NODEONLY not on both


class ScanTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_branch, make_user
        b = make_branch('B', '140')
        b.db_host, b.is_operational = '10.0.0.4', True
        b.save()
        make_user('adm', role='admin')
        make_user('ph', role='pharmacist', branch=b)

    def run_scan(self, node_rows):
        with mock.patch('config.sybase.get_sybase_connection', return_value=Conn(HQ)), \
                mock.patch('config.sybase.get_branch_connection', return_value=Conn(node_rows)):
            return SD.scan()

    def test_scan_records_resolves_and_notifies_once_a_day(self):
        r = self.run_scan(NODE)
        self.assertEqual((r['open'], r['open_risk']), (5, 4))
        self.assertEqual(r['nodes']['140']['differences'], 5)
        self.assertEqual(SD.notify(r), 1)                   # admin only, not the pharmacist
        self.assertEqual(SD.notify(r), 0)                   # deduped for the day
        from apps.notifications.models import Notification
        n = Notification.objects.get(notification_type='customer_status_drift')
        self.assertIn('100HD6038 — الرئيسي: ملف مغلق / فرع 140: نشط', n.body)
        self.assertIn('+ 1 اختلاف آخر', n.body)
        fixed = [r for r in NODE if r[0] != '100HD6038'] + [('100HD6038', '0', 0, 1, 0)]
        r2 = self.run_scan(fixed)
        self.assertEqual(r2['open_risk'], 3)
        self.assertIsNotNone(D.objects.get(pic='100HD6038').resolved_at)

    def test_offline_node_keeps_open_rows(self):
        self.run_scan(NODE)
        with mock.patch('config.sybase.get_sybase_connection', return_value=Conn(HQ)), \
                mock.patch('config.sybase.get_branch_connection', side_effect=OSError('down')):
            r = SD.scan()
        self.assertIn('error', r['nodes']['140'])
        self.assertEqual(r['open'], 5)

    def test_command(self):
        out = io.StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=Conn(HQ)), \
                mock.patch('config.sybase.get_branch_connection', return_value=Conn(NODE)):
            call_command('check_customer_status_drift', notify=True, stdout=out)
        self.assertIn('HQ stricter (branch still serves): 4', out.getvalue())
        self.assertIn('notifications: 1', out.getvalue())
