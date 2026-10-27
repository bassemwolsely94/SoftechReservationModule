"""
core/softech_probe_restore.py

Put back every SOFTECH row an investigation touched — all of it, whatever happens.

The sync investigations (investigate_*, probe_*) write test values into LIVE rows — HQ items
replicate to every branch — to watch triggers and replication. Their old "revert" was plain
code at the end: a crash in between left the test value in SOFTECH, and the reverts never put
the last-editor usercode back. Now every row is snapshotted before the first write and
restored, newest first, when the command ends — normally or not (Batch 2, P-14).

    with RowGuards(out) as guards:
        guards.track(get_sybase_connection, 'SOFTECHDB9.dbo.items', {'itemcode': ITEM},
                     ('posdiscp', 'usercode'))
        ... UPDATE ... observe ...
    # ← every tracked row is back here, even after an exception

Restoring a row is itself a write: HQ items triggers fire again (itemlastupdate, britems
trans_time) exactly as the old revert did. Values the probe never tracked are not touched.
"""
import datetime
import logging
import re

logger = logging.getLogger(__name__)

_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$')
_COLUMN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _ident(name, pattern=_IDENT):
    if not isinstance(name, str) or not pattern.match(name):
        raise ValueError(f'not a SOFTECH identifier: {name!r}')
    return name


def _value_sql(value):
    """(sql, params) for one SET value — jConnect cannot bind a Python datetime."""
    if value is None:
        return 'NULL', []
    if isinstance(value, datetime.datetime):
        return f"convert(datetime, '{value:%Y-%m-%d %H:%M:%S}.{value.microsecond // 1000:03d}')", []
    if isinstance(value, datetime.date):
        return f"convert(datetime, '{value:%Y-%m-%d}')", []
    return '?', [value]


def _where(key):
    return ' AND '.join(f'{_ident(k, _COLUMN)}=?' for k in key), [key[k] for k in key]


def restore_sql(table, key, values):
    """UPDATE <table> SET <every column back> WHERE <key> — identifiers checked, values bound."""
    sets, params = [], []
    for col, val in values.items():
        sql, p = _value_sql(val)
        sets.append(f'{_ident(col, _COLUMN)}={sql}')
        params += p
    where, wparams = _where(key)
    return f'UPDATE {_ident(table)} SET {", ".join(sets)} WHERE {where}', params + wparams


class RowGuard:
    def __init__(self, connect, table, key, columns, node='hq'):
        self.connect, self.table, self.key, self.node = connect, _ident(table), dict(key), str(node)
        self.columns = tuple(_ident(c, _COLUMN) for c in columns)
        self.original = None          # {column: value}; None = no row (nothing to put back)
        self.restored = False

    def snapshot(self):
        where, params = _where(self.key)
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(f'SELECT {", ".join(self.columns)} FROM {self.table} WHERE {where}', params)
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        if row is not None:
            self.original = {c: row[i] for i, c in enumerate(self.columns)}
        return self

    def restore(self):
        if self.restored or self.original is None:
            self.restored = True
            return
        sql, params = restore_sql(self.table, self.key, self.original)
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            cur.close()
        finally:
            conn.close()
        self.restored = True

    def __str__(self):
        return f'{self.node}:{self.table}[{", ".join(f"{k}={v}" for k, v in self.key.items())}]'


class RowGuards:
    """Every row tracked here goes back when the block ends — newest first, once each."""

    def __init__(self, out=None):
        self.out = out or (lambda text: None)
        self.guards = []

    def track(self, connect, table, key, columns, node='hq'):
        """Snapshot a row BEFORE the probe writes it. node names the server (HQ / a branch) so the
        same table on two servers is two rows. The same row twice keeps the FIRST snapshot."""
        for g in self.guards:
            if g.node == str(node) and g.table == table and g.key == dict(key):
                missing = set(columns) - set(g.columns)
                if missing:
                    raise ValueError(f'{g}: already tracked without {sorted(missing)}')
                return g
        g = RowGuard(connect, table, key, columns, node).snapshot()
        self.guards.append(g)
        return g

    def restore_all(self):
        failed = []
        for g in reversed(self.guards):
            if g.restored:
                continue
            try:
                g.restore()
                self.out(f'  restored {g}: {g.original}')
            except Exception as exc:          # keep going — the other rows still go back
                failed.append(g)
                logger.error('[softech_probe_restore] RESTORE FAILED %s -> %s: %s', g, g.original, exc)
                self.out(f'  !!! RESTORE FAILED {g}: put back by hand -> {g.original} ({exc})')
        if failed:
            raise RuntimeError(f'{len(failed)} SOFTECH row(s) NOT restored: '
                               + '; '.join(f'{g} -> {g.original}' for g in failed))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.restore_all()
        return False
