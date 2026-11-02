"""
probe_ap_writeback rehearsal safety — no SOFTECH connection: a fake connector answers by SQL.

The 2026-10-31 run printed nonsense (residue "51710", MAX+1 serial that already existed)
because the connector misread results. The rehearsal now refuses taken serials before any
INSERT, closes every cursor, and the residue check lists leftover rows instead of a COUNT.
"""
from django.test import SimpleTestCase

from apps.sync.management.commands.probe_ap_writeback import Command


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rows, self.closed = conn, [], False

    def execute(self, sql):
        self.conn.sql.append(' '.join(sql.split()))
        self.rows = list(self.conn.answer(sql))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, answer):
        self.answer, self.sql, self.cursors, self.began = answer, [], [], False

    def _cursor(self):
        c = FakeCursor(self)
        self.cursors.append(c)
        return c

    def begin_transaction(self):
        self.began = True

    def rollback(self):
        pass


def rehearse(answer):
    conn, lines = FakeConn(answer), []
    Command()._rehearse(conn, lines.append, None, '130', '30')
    return conn, '\n'.join(lines)


class RehearsalSafetyTests(SimpleTestCase):

    def test_taken_serials_refuse_before_any_insert(self):
        def answer(sql):
            if 'MAX(cheqsno)' in sql:
                return [(51710, 31794)]
            if 'cheqsno=51710 OR ourcheqsno=31794' in ' '.join(sql.split()):
                return [(51710, 19903)]
            return []
        conn, out = rehearse(answer)
        self.assertIn('[REFUSED]', out)
        self.assertFalse(conn.began)
        self.assertFalse(any(s.startswith('INSERT') for s in conn.sql), conn.sql)
        self.assertTrue(all(c.closed for c in conn.cursors))

    def test_residue_check_lists_rows(self):
        lines = []
        Command._residue_check(lambda sql: [], lines.append, 'APPROBE1', '130', (12362, '2026-09-17'))
        self.assertIn('RESIDUE CHECK: OK', lines[-1])

        def left(sql):
            return [(52428, 32212)] if 'chequenote' in sql else []
        Command._residue_check(left, lines.append, 'APPROBE1', '130', (12362, '2026-09-17'))
        self.assertIn('LEFT IN SOFTECH', lines[-1])
        self.assertIn('(52428, 32212)', lines[-1])
