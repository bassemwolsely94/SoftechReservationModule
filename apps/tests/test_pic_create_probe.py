"""
apps/tests/test_pic_create_probe.py — investigate_pic_create must be SELECT-only and never print
personal data (POS speed wave, Task 7). Uses a fake cursor; never touches a SOFTECH server.
"""
import io
import os
import re
import tempfile
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

SECRET_NAME = 'محمد السري'
SECRET_PHONE = '01234567890'


class FakeCursor:
    def __init__(self, log):
        self.log, self.description, self._rows = log, [], []

    def execute(self, sql, params=None):
        self.log.append(sql)
        s = sql.upper()
        self.description = [('c',)]
        if 'SYSCOLUMNS' in s:
            self.description = [('table_name',), ('col',), ('allownulls',), ('default_name',)]
            self._rows = [('localcustomers', 'phcode', 0, None), ('localcustomers', 'custname', 1, None)]
        elif 'TRIGGER_NAME' in s:
            self.description = [('trigger',), ('table',)]
            self._rows = [('tr_lc_ins', 'localcustomers')]
        elif 'PHCODE' in s and 'ORDER BY' in s:
            self.description = [('phcode',), ('branchcode',), ('custname',), ('phone',)]
            self._rows = [('03HD3059', '03', SECRET_NAME, SECRET_PHONE),
                          ('03HD3061', '03', SECRET_NAME, SECRET_PHONE)]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return FakeCursor(self.log)

    def close(self):
        pass


def _run(extra=()):
    log = []
    out = io.StringIO()
    path = os.path.join(tempfile.mkdtemp(), 'probe.txt')
    with mock.patch('config.sybase.get_sybase_connection', lambda: FakeConn(log)), \
         mock.patch('config.sybase.get_branch_connection', lambda *a, **k: FakeConn(log)):
        call_command('investigate_pic_create', '--out', path, *extra, stdout=out)
    with open(path, encoding='utf-8') as f:
        return log, out.getvalue(), f.read()


class PicCreateProbeTests(SimpleTestCase):
    def test_pic_probe_issues_only_selects(self):
        log, _, _ = _run()
        self.assertTrue(log)
        for sql in log:
            self.assertRegex(sql.strip(), r'(?i)^(select|sp_help|set rowcount)\b', sql)
            self.assertNotRegex(sql, r'(?i)\b(insert|update|delete|truncate|drop|alter|create|exec(ute)?\s+(?!sp_help))\b', sql)
            self.assertNotRegex(sql, r'(?i)\binto\b')

    def test_pic_probe_masks_personal_data(self):
        _, stdout, report = _run()
        for text in (stdout, report):
            self.assertNotIn(SECRET_NAME, text)
            self.assertNotIn(SECRET_PHONE, text)
        self.assertIn('localcustomers', report)
        self.assertIn('phcode', report)
