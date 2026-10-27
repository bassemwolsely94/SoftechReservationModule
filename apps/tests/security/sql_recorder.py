"""
apps/tests/security/sql_recorder.py

RecordingSybase — a stand-in for SOFTECH that records every (sql, params) a piece of
code sends, so a test can push SQL-injection payloads through the real endpoint and
prove they arrive as bound parameters, never as SQL text.

    with RecordingSybase(rows=[...]) as rec:
        client.get('/api/…?code=' + PAYLOAD)
    assert_payload_bound(self, rec.calls, PAYLOAD)

Every execute also checks that the number of '?' markers equals len(params).
"""
from unittest import mock


class _Cursor:
    def __init__(self, rec):
        self._rec = rec
        self.description = []
        self._rows = []

    def execute(self, sql, params=None, timeout=None):
        params = list(params or [])
        assert sql.count('?') == len(params), (
            f'{sql.count("?")} placeholders but {len(params)} params:\n{sql}')
        self._rec.calls.append((sql, params))
        self._rows = list(self._rec.rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchmany(self, n=1):
        return self._rows[:n]

    def close(self):
        pass


class _Conn:
    def __init__(self, rec):
        self._rec = rec

    def cursor(self):
        return _Cursor(self._rec)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class RecordingSybase:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def __enter__(self):
        conn = lambda *a, **k: _Conn(self)   # noqa: E731
        rec = self

        def _connector_connect(connector_self):
            connector_self._conn = _Conn(rec)     # SoftechConnector keeps its wrapper here
            return connector_self
        self._patches = [mock.patch('config.sybase.get_sybase_connection', side_effect=conn),
                         mock.patch('config.sybase.get_branch_connection', side_effect=conn),
                         mock.patch('config.sybase.SoftechConnector.connect', _connector_connect)]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def assert_payload_bound(testcase, calls, payload):
    """payload must appear in some bound param and in NO sql text."""
    pasted = [sql for sql, _ in calls if payload in sql]
    if pasted:
        testcase.fail(f'payload pasted into SQL text:\n{pasted[0]}')
    bound = any(payload in str(p) for _, params in calls for p in params)
    if not bound:
        testcase.fail(f'payload not found in any bound parameter ({len(calls)} statements)')
