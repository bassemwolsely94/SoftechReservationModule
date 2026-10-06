"""
investigate_override — READ-ONLY diagnostic for the Ctrl+M / OFFERS discount
override. Pulls two pending POS sales (one Ctrl+M-overridden, one normal) from the
stktrans5/stktransm5 pending tables and diffs them column-by-column to find whether
the override leaves any stamp we must replicate. SELECT only — never writes.

    python manage.py investigate_override --override 7854 --normal 7855
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Read-only: diff a Ctrl+M-overridden POS sale vs a normal one.'

    def add_arguments(self, parser):
        parser.add_argument('--override', type=int, default=7854)
        parser.add_argument('--normal', type=int, default=7855)
        parser.add_argument('--branch', default=None, help='branch db host (default HQ)')

    def _conn(self, host):
        from config.sybase import get_sybase_connection, get_branch_connection
        return get_branch_connection(host) if host else get_sybase_connection()

    def _rows(self, cur, table, docs):
        cur.execute(f"SELECT * FROM SOFTECHDB9.dbo.{table} WHERE docnumber IN (?, ?)", list(docs))
        cols = [d[0] for d in cur.description]
        out = {}
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            out.setdefault(int(row.get('docnumber')), []).append(row)
        return cols, out

    def handle(self, *a, **o):
        ov, nm = o['override'], o['normal']
        try:
            conn = self._conn(o['branch'])
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'SOFTECH connect failed: {e}'))
            return
        cur = conn.cursor()

        # confirm OFFERS + its max discount
        try:
            cur.execute("SELECT usercode, userid FROM SOFTECHDB9.dbo.users WHERE userid = 'OFFERS'")
            self.stdout.write(self.style.WARNING(f"OFFERS user: {cur.fetchall()}"))
            cur.execute("SELECT personcode, branchcode, max_custdiscp FROM SOFTECHDB9.dbo.managerdiscount WHERE personcode = '89'")
            self.stdout.write(self.style.WARNING(f"managerdiscount[89]: {cur.fetchall()}"))
        except Exception as e:
            self.stdout.write(f'(user/managerdiscount lookup skipped: {e})')

        for table in ('stktrans5', 'stktransm5'):
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n===== {table} ====="))
            try:
                cols, rows = self._rows(cur, table, (ov, nm))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'query failed: {e}'))
                continue
            o_rows, n_rows = rows.get(ov, []), rows.get(nm, [])
            self.stdout.write(f"override {ov}: {len(o_rows)} row(s) · normal {nm}: {len(n_rows)} row(s)")
            if not o_rows or not n_rows:
                self.stdout.write(self.style.ERROR('one side missing — try --branch <host>'))
                continue
            # pick the discounted line for the override, and any line for normal
            orow = next((r for r in o_rows if _num(r.get('custdiscp')) > 0), o_rows[0])
            nrow = next((r for r in n_rows if _num(r.get('custdiscp')) > 0), n_rows[0])
            self._diff(cols, orow, nrow, ov, nm)
        try:
            conn.close()
        except Exception:
            pass

    def _diff(self, cols, orow, nrow, ov, nm):
        self.stdout.write(self.style.SUCCESS('--- columns that DIFFER (override vs normal) ---'))
        for c in cols:
            a, b = orow.get(c), nrow.get(c)
            if _norm(a) != _norm(b):
                flag = ''
                if '89' in _norm(a) and '89' not in _norm(b):
                    flag = '   <== contains 89 (OFFERS) only on override!'
                self.stdout.write(f"  {c:<24} override={a!r:<22} normal={b!r}{flag}")
        # also surface any column literally equal to 89 on the override
        hits = [c for c in cols if _norm(orow.get(c)) == '89']
        self.stdout.write(self.style.SUCCESS(f"columns == 89 on override {ov}: {hits or 'NONE'}"))


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _norm(v):
    return str(v).strip() if v is not None else ''
