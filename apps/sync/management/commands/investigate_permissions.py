"""
python manage.py investigate_permissions

Reverse-engineers the SOFTECH permission/authorization model:
  • user groups / user types
  • per-module / per-screen / per-action permission tables
  • menu & form access control
  • how users map to groups and groups to permissions

Read-only. Saves a full report to docs/softech_permissions_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..',
                   'docs', 'softech_permissions_investigation.txt')

# Catalog name fragments that usually indicate authorization objects
PERM_FRAGMENTS = [
    'group', 'perm', 'right', 'access', 'menu', 'role', 'auth', 'secur',
    'priv', 'screen', 'form', 'module', 'usertype', 'user_type', 'allow',
    'deny', 'grant', 'authoriz', 'page', 'function', 'feature', 'option',
]


class Command(BaseCommand):
    help = 'Reverse-engineer SOFTECH permissions/usergroups model'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        lines = []

        def out(text=''):
            safe = str(text).encode('ascii', 'replace').decode('ascii')
            self.stdout.write(safe)
            lines.append(str(text))

        def section(t):
            out(''); out('=' * 78); out('  ' + t); out('=' * 78)

        def schema(conn, tbl):
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT c.name, t.name, c.length, c.colid
                    FROM SOFTECHDB9.dbo.syscolumns c
                    JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
                    JOIN SOFTECHDB9.dbo.systypes   t ON c.usertype=t.usertype
                    WHERE o.name=? ORDER BY c.colid
                """, [tbl])
                rows = cur.fetchall(); cur.close()
                if not rows:
                    return False
                out(f'\n  TABLE: {tbl}')
                for r in rows:
                    out(f'    [{r[3]:>3}] {str(r[0]):<32} {str(r[1]):<12} len={r[2]}')
                return True
            except Exception as e:
                out(f'  schema({tbl}) ERROR: {e}')
                return False

        def count(conn, tbl):
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9.dbo.{tbl}')
                n = cur.fetchone()[0]; cur.close()
                return int(n or 0)
            except Exception:
                return -1

        def sample(conn, tbl, n=8, order=None):
            try:
                cur = conn.cursor()
                cur.execute(f'SET ROWCOUNT {n}')
                q = f'SELECT * FROM SOFTECHDB9.dbo.{tbl}'
                if order:
                    q += f' ORDER BY {order}'
                cur.execute(q)
                rows = cur.fetchall()
                cur.execute('SET ROWCOUNT 0'); cur.close()
                for r in rows:
                    out('    ' + ' | '.join(str(c) for c in r))
            except Exception as e:
                out(f'    sample({tbl}) ERROR: {e}')

        conn = get_sybase_connection()
        out(f'Started: {datetime.datetime.now().isoformat()}')

        # ── 1. Find all candidate permission/auth tables ──────────────────────
        section('1. Candidate permission / authorization tables')
        like = ' OR '.join(f"LOWER(o.name) LIKE '%{f}%'" for f in PERM_FRAGMENTS)
        cands = []
        try:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT o.name, o.type, o.crdate
                FROM SOFTECHDB9.dbo.sysobjects o
                WHERE o.type IN ('U','V') AND ({like})
                ORDER BY o.name
            """)
            for r in cur.fetchall():
                cands.append(r[0])
                out(f'  {r[0]:<34} type={r[1]}  created={str(r[2])[:10]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')
        out(f'\n  -> {len(cands)} candidate tables')

        # ── 2. Row counts for candidates (focus on the populated ones) ────────
        section('2. Row counts (populated tables matter most)')
        populated = []
        for t in cands:
            n = count(conn, t)
            if n > 0:
                populated.append((t, n))
                out(f'  {t:<34} {n:>8} rows')
        out(f'\n  -> {len(populated)} populated candidate tables')

        # ── 3. usergroups / usertype definitions ──────────────────────────────
        section('3. User group / type definitions')
        for t in ['usergroups', 'usergroup', 'usertypes', 'usertype',
                  'groups', 'roles', 'userlevels', 'userlevel', 'securitygroups']:
            if schema(conn, t):
                out(f'  -- sample {t} --')
                sample(conn, t, 20)

        # The users table usergroup linkage
        section('3b. users -> usergroup linkage (distinct groups in use)')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT usergroup, COUNT(*) AS n
                FROM SOFTECHDB9.dbo.users
                GROUP BY usergroup ORDER BY usergroup
            """)
            for r in cur.fetchall():
                out(f'  usergroup={r[0]:<6} users={r[1]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── 4. Permission / access tables — schema + sample for populated ─────
        section('4. Schema + sample of every POPULATED candidate table')
        for t, n in populated:
            schema(conn, t)
            out(f'  -- sample ({n} rows) --')
            sample(conn, t, 6)

        # ── 5. Menu / form / screen catalog (what modules exist in SOFTECH) ───
        section('5. Menu / form / screen catalog')
        for t in ['menu', 'menus', 'forms', 'screens', 'mitems', 'modules',
                  'sysmenu', 'menuitems', 'programs', 'functions']:
            if schema(conn, t):
                out(f'  -- sample {t} --')
                sample(conn, t, 15)

        # ── 6. Stored procedures that check permissions ───────────────────────
        section('6. Procedures referencing permission/group keywords')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT o.name
                FROM SOFTECHDB9.dbo.syscomments sc
                JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
                WHERE o.type='P' AND (
                    LOWER(sc.text) LIKE '%usergroup%'
                    OR LOWER(sc.text) LIKE '%permission%'
                    OR LOWER(sc.text) LIKE '%userright%'
                    OR LOWER(sc.text) LIKE '%user_right%'
                )
                ORDER BY o.name
            """)
            for r in cur.fetchall():
                out(f'  {r[0]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        conn.close()
        out(f'\nComplete: {datetime.datetime.now().isoformat()}')

        dest = os.path.abspath(OUT)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.stdout.write(f'\nSaved -> {dest}')
