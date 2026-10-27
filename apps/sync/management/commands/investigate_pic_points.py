"""
python manage.py investigate_pic_points

Writes results to  investigate_output.txt  (UTF-8) in the project root.
No terminal encoding issues — just open the file and share it.

Sections:
  1. Procedures whose SOURCE body contains 'picpoints' or phcode+UPDATE
  2. Triggers on localcustomers
  3. Tables that look like a points history / transaction log
  4. Views that reference picpoints
"""
import os
import sys
import io

from django.core.management.base import BaseCommand
from django.conf import settings

from config.sybase import get_sybase_connection, _safe_str

OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(settings.BASE_DIR
                                    if hasattr(settings, 'BASE_DIR')
                                    else __file__)),
    'investigate_output.txt',
)


class Command(BaseCommand):
    help = 'Investigate how SOFTECH ERP modifies PIC points — writes UTF-8 output file'

    def handle(self, *args, **options):
        # Resolve output path relative to manage.py
        base = getattr(settings, 'BASE_DIR', None)
        if base is None:
            import django
            base = os.path.dirname(os.path.abspath(django.__file__))
        out_path = os.path.join(str(base), 'investigate_output.txt')

        buf = io.StringIO()

        def w(line=''):
            buf.write(line + '\n')

        def section(title):
            w()
            w('=' * 72)
            w('  ' + title)
            w('=' * 72)

        def rows(conn, sql, params=None):
            cur = conn.cursor()
            cur.execute(sql, params or [])
            return cur.fetchall()

        def safe(val):
            if val is None:
                return ''
            s = _safe_str(val) if callable(_safe_str) else str(val)
            return s.strip() if s else str(val).strip()

        def print_source(conn, obj_name):
            w()
            w(f'  +-- {obj_name} ' + '-' * max(0, 60 - len(obj_name)))
            try:
                cur = conn.cursor()
                cur.execute(f"EXEC sp_helptext '{obj_name}'")
                src_rows = cur.fetchall()
                if not src_rows:
                    w('  |  (no source returned)')
                else:
                    for r in src_rows:
                        line = safe(r[0]) if r[0] is not None else ''
                        w('  | ' + line)
            except Exception as exc:
                w(f'  |  sp_helptext failed: {exc}')
            w('  +' + '-' * 68)

        def print_columns(conn, table_name):
            sql = f"""
                SELECT c.name, t.name, c.length
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.systypes   t ON t.usertype = c.usertype
                JOIN   SOFTECHDB9.dbo.sysobjects o ON o.id       = c.id
                WHERE  LOWER(o.name) = LOWER('{table_name}')
                ORDER  BY c.colid
            """
            try:
                col_rows = rows(conn, sql)
                if not col_rows:
                    w('    (no columns returned)')
                    return
                for r in col_rows:
                    col   = safe(r[0])
                    dtype = safe(r[1])
                    length = str(r[2]) if r[2] is not None else ''
                    w(f'    {col:<35} {dtype}({length})')
            except Exception as exc:
                w(f'    columns query failed: {exc}')

        # ── connect ──────────────────────────────────────────────────────────
        w('Connecting to SOFTECH...')
        try:
            conn = get_sybase_connection()
        except Exception as exc:
            w(f'CONNECTION FAILED: {exc}')
            self._flush(buf, out_path)
            return
        w('Connected.')

        # ── 1. Procedures / triggers / views whose body mentions picpoints ────
        section('1 - Objects whose SOURCE body references picpoints or phcode+UPDATE')
        body_sql = """
            SELECT DISTINCT o.name, o.type
            FROM   SOFTECHDB9.dbo.sysobjects  o
            JOIN   SOFTECHDB9.dbo.syscomments c ON c.id = o.id
            WHERE  o.type IN ('P', 'TR', 'V')
              AND  (
                       LOWER(c.text) LIKE '%picpoints%'
                    OR (LOWER(c.text) LIKE '%phcode%' AND LOWER(c.text) LIKE '%update%')
                   )
            ORDER  BY o.type, o.name
        """
        try:
            body_rows = rows(conn, body_sql)
        except Exception as exc:
            w(f'  Query failed: {exc}')
            body_rows = []

        if not body_rows:
            w('  No procedures/triggers/views found referencing picpoints.')
        else:
            w(f'  {"Name":<50} Type')
            w('  ' + '-' * 60)
            for r in body_rows:
                name  = safe(r[0])
                typ   = safe(r[1])
                label = {'P': 'Procedure', 'TR': 'Trigger', 'V': 'View'}.get(typ, typ)
                w(f'  {name:<50} {label}')
            w()
            w('  -- Full source of each match --')
            for r in body_rows:
                print_source(conn, safe(r[0]))

        # ── 2. Triggers on localcustomers ────────────────────────────────────
        section('2 - Triggers on or related to localcustomers')
        # Sybase: deltrig/instrig/updtrig columns on sysobjects point to trigger ids
        trig_sql = """
            SELECT o.name
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type = 'TR'
              AND  (
                       LOWER(o.name) LIKE '%customer%'
                    OR LOWER(o.name) LIKE '%localcust%'
                    OR LOWER(o.name) LIKE '%pic%'
                    OR LOWER(o.name) LIKE '%point%'
                   )
        """
        # Also find triggers by checking which table object has them linked
        trig_sql2 = """
            SELECT tr.name
            FROM   SOFTECHDB9.dbo.sysobjects tbl
            JOIN   SOFTECHDB9.dbo.sysobjects tr
                   ON tr.id IN (tbl.deltrig, tbl.instrig, tbl.updtrig)
            WHERE  LOWER(tbl.name) = 'localcustomers'
              AND  tr.type = 'TR'
        """
        trig_names = set()
        for sql in (trig_sql, trig_sql2):
            try:
                for r in rows(conn, sql):
                    n = safe(r[0])
                    if n:
                        trig_names.add(n)
            except Exception:
                pass

        if not trig_names:
            w('  No triggers found linked to localcustomers.')
        else:
            for name in sorted(trig_names):
                w(f'  Trigger: {name}')
                print_source(conn, name)

        # ── 3. Tables that look like a points history / log ──────────────────
        section('3 - Tables that may be a points history / transaction log')
        keywords = ['pic', 'point', 'loyal', 'reward', 'bonus', 'redeem',
                    'voucher', 'trans', 'hist', 'log']
        like_parts = ' OR '.join([f"LOWER(name) LIKE '%{k}%'" for k in keywords])
        tbl_sql = f"""
            SELECT name
            FROM   SOFTECHDB9.dbo.sysobjects
            WHERE  type = 'U'
              AND  ({like_parts})
            ORDER  BY name
        """
        try:
            tbl_rows = rows(conn, tbl_sql)
        except Exception as exc:
            w(f'  Query failed: {exc}')
            tbl_rows = []

        if not tbl_rows:
            w('  No candidate tables found.')
        else:
            for r in tbl_rows:
                tname = safe(r[0])
                w()
                w(f'  Table: {tname}')
                print_columns(conn, tname)

        # ── 4. Views referencing picpoints ───────────────────────────────────
        section('4 - Views whose source references picpoints')
        view_sql = """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.sysobjects  o
            JOIN   SOFTECHDB9.dbo.syscomments c ON c.id = o.id
            WHERE  o.type = 'V'
              AND  LOWER(c.text) LIKE '%picpoints%'
            ORDER  BY o.name
        """
        try:
            view_rows = rows(conn, view_sql)
        except Exception as exc:
            w(f'  Query failed: {exc}')
            view_rows = []

        if not view_rows:
            w('  No views reference picpoints.')
        else:
            for r in view_rows:
                w(f'  View: {safe(r[0])}')

        conn.close()
        w()
        w('Done.')

        self._flush(buf, out_path)
        self.stdout.write(f'Output written to: {out_path}')

    @staticmethod
    def _flush(buf, path):
        content = buf.getvalue()
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(content)
