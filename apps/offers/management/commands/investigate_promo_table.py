"""
investigate_promo_table — READ-ONLY discovery of SOFTECH's native Sales-Promotions
table(s) behind the "العروض الخاصة للمبيعات" screen. Finds candidate tables, prints
their columns, and samples a few rows so we can design the Channel-B writer.
SELECT only — never writes.

    python manage.py investigate_promo_table
    python manage.py investigate_promo_table --table salespromotions --find 6457
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Read-only: discover the SOFTECH sales-promotions table + schema.'

    def add_arguments(self, parser):
        parser.add_argument('--table', default=None, help='inspect a specific table')
        parser.add_argument('--find', default=None, help='find rows where any int col == this offer no')
        parser.add_argument('--branch', default=None)

    def _conn(self, host):
        from config.sybase import get_sybase_connection, get_branch_connection
        return get_branch_connection(host) if host else get_sybase_connection()

    def handle(self, *a, **o):
        try:
            conn = self._conn(o['branch'])
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'connect failed: {e}'))
            return
        cur = conn.cursor()

        tables = [o['table']] if o['table'] else self._candidates(cur)
        if not tables:
            self.stdout.write(self.style.ERROR('no candidate tables found — widen the LIKE filters'))
            return

        for t in tables:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n===== {t} ====="))
            try:
                cur.execute("SET ROWCOUNT 3")               # ASE has no TOP here
                cur.execute(f"SELECT * FROM SOFTECHDB9.dbo.{t}")
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                cur.execute("SET ROWCOUNT 0")
                self.stdout.write("COLUMNS: " + ', '.join(cols))
                for r in rows:
                    self.stdout.write('  ROW: ' + ' | '.join(f'{c}={v!r}' for c, v in zip(cols, r) if v not in (None, '', 0, 0.0)))
                cur.execute(f"SELECT COUNT(*) FROM SOFTECHDB9.dbo.{t}")
                self.stdout.write(f"  rowcount: {cur.fetchone()[0]}")
                if o['find']:
                    self._find(cur, t, cols, o['find'])
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  inspect failed: {e}'))
        try:
            conn.close()
        except Exception:
            pass

    def _candidates(self, cur):
        like = " OR ".join(f"name LIKE '%{p}%'" for p in
                           ('promo', 'offer', 'bonus', 'special', '3ard', 'aroud', 'discount', 'sale5'))
        cur.execute(f"SELECT name FROM SOFTECHDB9.dbo.sysobjects WHERE type='U' AND ({like}) ORDER BY name")
        found = [r[0] for r in cur.fetchall()]
        self.stdout.write(self.style.WARNING(f'candidate tables: {found}'))
        return found

    def _find(self, cur, t, cols, val):
        for c in cols:
            try:
                cur.execute("SET ROWCOUNT 2")
                cur.execute(f"SELECT * FROM SOFTECHDB9.dbo.{t} WHERE {c} = ?", [val])
                rows = cur.fetchall()
                cur.execute("SET ROWCOUNT 0")
                if rows:
                    self.stdout.write(self.style.SUCCESS(f"  MATCH on {c}={val}:"))
                    for r in rows:
                        self.stdout.write('    ' + ' | '.join(f'{cc}={v!r}' for cc, v in zip(cols, r) if v not in (None, '', 0, 0.0)))
            except Exception:
                pass
