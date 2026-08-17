"""
python manage.py diag_purchase_verbatim --branch 100 --docnumber 63662 [--profile prod]

DIAGNOSTIC (rolls back): reinsert a VERBATIM clone of a real purchase — every
stktransm/stktrans column copied from the source, overriding ONLY the identity
docnumber + timestamps. Tests whether the hidden tr_stktrans trigger accepts a
byte-identical copy (the "copy an entered invoice and reinsert" path). Reports
@@error after each insert and whether the rows survive, then ROLLS BACK.
"""
from datetime import datetime, date
from django.core.management.base import BaseCommand, CommandError

# columns overridden with a fresh identity / timestamps on the clone
_HDR_OVERRIDE = {'docnumber', 'docdate', 'trans_time', 'table_dumped', 'docwritedate', 'vf2'}
_LINE_OVERRIDE = {'docnumber', 'docdate', 'trans_time', 'table_dumped'}


def _lit(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (datetime, date)):
        return f"convert(datetime, '{v:%Y-%m-%d %H:%M:%S}')"
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


class Command(BaseCommand):
    help = 'Reinsert a verbatim clone of a purchase (rolls back) to test trigger acceptance.'

    def add_arguments(self, parser):
        parser.add_argument('--branch', required=True)
        parser.add_argument('--docnumber', required=True, type=int)
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **o):
        from django.conf import settings
        from config.sybase import SoftechConnector, get_branch_connection

        bc = str(o['branch']).strip()

        # ── read source header + lines verbatim (all columns) ──────────────────
        sc = SoftechConnector(profile=o['profile']).connect()
        try:
            hdr = _one(sc, "SELECT * FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
                       [bc, o['docnumber']])
            if not hdr:
                raise CommandError('source header not found')
            lines = _all(sc, "SELECT * FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=? "
                             "ORDER BY itemcode", [bc, o['docnumber']])
        finally:
            sc.close()
        self.stdout.write(f'source lines={len(lines)}')

        conn = get_branch_connection(settings.SYBASE_HOST, 5000, 'SOFTECHDB9', charset='cp1256')
        try:
            conn.begin()
            newno = int(_q1(conn, "SELECT lastdocnumberin_supp FROM lastdocnumbers HOLDLOCK WHERE branchcode=?",
                            [bc])[0]) + 1
            self.stdout.write(f'clone docnumber={newno}')

            over = {'docnumber': newno,
                    'docdate': _RAW("convert(datetime, convert(char(8), getdate(), 112))"),
                    'trans_time': _RAW('getdate()'), 'table_dumped': _RAW('getdate()'),
                    'docwritedate': None, 'vf2': f'INVCLONE'}
            self._insert(conn, 'stktransm', hdr, _HDR_OVERRIDE, over)
            d = _q1(conn, "SELECT @@error, @@rowcount, @@trancount")
            self.stdout.write(f'after HEADER: @@error={d[0]} @@rowcount={d[1]} @@trancount={d[2]}')

            lover = {'docnumber': newno,
                     'docdate': _RAW("convert(datetime, convert(char(8), getdate(), 112))"),
                     'trans_time': _RAW('getdate()'), 'table_dumped': None}
            for i, ln in enumerate(lines, 1):
                self._insert(conn, 'stktrans', ln, _LINE_OVERRIDE, lover)
                d = _q1(conn, "SELECT @@error, @@rowcount, @@trancount")
                self.stdout.write(f'after LINE {i} (item {str(ln.get("itemcode")).strip()}): '
                                  f'@@error={d[0]} @@rowcount={d[1]} @@trancount={d[2]}')
                if int(d[2]) == 0:
                    self.stdout.write(self.style.ERROR('  → transaction was rolled back by a trigger; stopping.'))
                    break

            h = _q1(conn, "SELECT COUNT(*) FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
                    [bc, newno])
            l = _q1(conn, "SELECT COUNT(*) FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?",
                    [bc, newno])
            self.stdout.write(self.style.SUCCESS(f'\nFINAL in-txn: stktransm={h[0]} stktrans={l[0]} '
                                                 f'(expected 1 / {len(lines)})'))
        finally:
            try:
                conn.rollback(); self.stdout.write('rolled back.')
            except Exception as e:
                self.stdout.write(f'rollback err: {e}')
            conn.close()

    def _insert(self, conn, table, row, override_cols, overrides):
        cols, vals = [], []
        for c, v in row.items():
            cols.append(c)
            if c in override_cols:
                ov = overrides.get(c, None)
                vals.append(ov.sql if isinstance(ov, _RAW) else _lit(ov))
            else:
                vals.append(v.sql if isinstance(v, _RAW) else _lit(v))
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)})"
        cur = conn.cursor()
        try:
            cur.execute(sql)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'{table} INSERT raised: {e}'))
        finally:
            cur.close()


class _RAW:
    def __init__(self, sql):
        self.sql = sql


def _q1(conn, sql, params=None):
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
        return cur.fetchone()
    finally:
        cur.close()


def _one(sc, sql, params):
    sc._cursor().execute('SET ROWCOUNT 1')
    try:
        cur = sc._cursor(); cur.execute(sql, params)
        cols = [d[0] for d in cur.description]; r = cur.fetchone()
        return dict(zip(cols, r)) if r else None
    finally:
        sc._cursor().execute('SET ROWCOUNT 0')


def _all(sc, sql, params):
    cur = sc._cursor(); cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
