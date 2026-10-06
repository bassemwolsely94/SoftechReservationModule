"""
python manage.py inspect_insurance_schema

Discovers Softech tables and data relevant to insurance billing.
Run this from the SERVER (where Sybase connection is available).

KEY FINDING (2026-06-02):
  motalbas.docvaluenet  ← actual column name (no underscore)
  NOT docvalue_net

Sybase ASE 12.5 quirks (confirmed):
  - OR conditions work fine
  - IN ('x','y') syntax causes "Incorrect syntax near 'x'"
  - After a query error the connection enters an error state;
    must open a fresh cursor (new statement) for the next query
  - DISTINCT TOP N may cause issues; use SET ROWCOUNT + DISTINCT instead

Usage:
    python manage.py inspect_insurance_schema               # full discovery
    python manage.py inspect_insurance_schema --table motalbas
    python manage.py inspect_insurance_schema --stktransm-cols
    python manage.py inspect_insurance_schema --motalbas    # show recent motalbas
    python manage.py inspect_insurance_schema --personcodes # insurance personcodes
    python manage.py inspect_insurance_schema --sample-motalba 1254
"""
from django.core.management.base import BaseCommand


def _fresh_cursor(conn):
    """Always get a fresh CursorWrapper — avoids Sybase connection error state."""
    return conn.cursor()


class Command(BaseCommand):
    help = 'Discover Softech insurance/motalba tables and data'

    def add_arguments(self, parser):
        parser.add_argument('--table', type=str, default=None)
        parser.add_argument('--stktransm-cols', action='store_true')
        parser.add_argument('--motalbas', action='store_true',
                            help='Show 20 most recent motalbas')
        parser.add_argument('--personcodes', action='store_true',
                            help='Show insurance personcodes from stktrans')
        parser.add_argument('--sample-motalba', type=int, default=None,
                            help='Show all lines for a specific motalbano')
        parser.add_argument('--all-tables', action='store_true')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        from apps.insurance.sybase_queries import QUERY_TABLE_COLUMNS_TEMPLATE

        try:
            conn = get_sybase_connection()
            self.stdout.write(self.style.SUCCESS('[OK] Connected to Softech\n'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'[FAIL] Connection failed: {e}'))
            return

        # ── Inspect specific table ─────────────────────────────────────────────
        if options['table']:
            self._inspect_table(conn, options['table'], QUERY_TABLE_COLUMNS_TEMPLATE)
            return

        # ── stktransm columns ──────────────────────────────────────────────────
        if options['stktransm_cols']:
            self._inspect_table(conn, 'stktransm', QUERY_TABLE_COLUMNS_TEMPLATE)
            return

        # ── Recent motalbas ────────────────────────────────────────────────────
        if options['motalbas']:
            self._show_motalbas(conn)
            return

        # ── Insurance personcodes ──────────────────────────────────────────────
        if options['personcodes']:
            self._show_personcodes(conn)
            return

        # ── Sample lines for one motalba ───────────────────────────────────────
        if options['sample_motalba']:
            self._show_motalba_lines(conn, options['sample_motalba'])
            return

        # ── All tables ────────────────────────────────────────────────────────
        if options['all_tables']:
            self._all_tables(conn)
            return

        # ── DEFAULT: full discovery ────────────────────────────────────────────
        self._run_full_discovery(conn, QUERY_TABLE_COLUMNS_TEMPLATE)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _run_query(self, conn, sql, params=None, label=''):
        """Execute query with fresh cursor. Returns rows or None on error."""
        try:
            cursor = _fresh_cursor(conn)
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return rows
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  [ERROR] {label}: {e}\n'))
            return None

    def _inspect_table(self, conn, table, template):
        self.stdout.write(f'\n=== Columns of {table} ===\n')
        rows = self._run_query(conn, template.format(table=table), label=table)
        if not rows:
            self.stdout.write('  (no columns found — check table name)\n')
            return
        self.stdout.write(f'{"#":>3}  {"Column":<35}  {"Type":<15}  Len\n')
        self.stdout.write('-' * 60 + '\n')
        for i, row in enumerate(rows):
            self.stdout.write(f'{i:>3}  {str(row[0]):<35}  {str(row[1]):<15}  {row[2]}\n')

    def _show_motalbas(self, conn):
        """Show recent motalbas. Fetches all and slices in Python (avoids TOP N / SET ROWCOUNT)."""
        self.stdout.write('\n=== Recent motalbas (motalbas table) ===\n')

        # No WHERE filter — show all, slice in Python
        # Tinyint IS NULL is unreliable; 0 = active, 1 = deleted in Sybase tinyint
        rows = self._run_query(conn, """
            SELECT ms.motalbano, ms.personcode, ms.motfromdate,
                   ms.mottodate, ms.motnoofpatients, ms.docvaluetotal, ms.docvaluenet,
                   ms.motalbacomment
            FROM SOFTECHDB9.dbo.motalbas ms
            ORDER BY ms.motalbano DESC
        """, label='motalbas')  # No motalbadel filter — show all including deleted

        if rows is None:
            return
        if not rows:
            self.stdout.write('  (no rows found — table may be empty)\n')
            return

        self.stdout.write(f'  Total motalbas: {len(rows)} — showing latest 20\n\n')
        rows = rows[:20]
        self.stdout.write(
            f'{"motalbano":>10}  {"personcode":<12}  {"from":<12}  '
            f'{"to":<12}  {"#rx":>5}  {"total":>14}  {"net":>14}  comment\n'
        )
        self.stdout.write('-' * 105 + '\n')
        for r in rows:
            self.stdout.write(
                f'{str(r[0] or ""):>10}  {str(r[1] or ""):<12}  '
                f'{str(r[2] or "")[:10]:<12}  {str(r[3] or "")[:10]:<12}  '
                f'{str(r[4] or ""):>5}  {str(r[5] or ""):>14}  {str(r[6] or ""):>14}  '
                f'{str(r[7] or "")}\n'
            )

    def _show_personcodes(self, conn):
        """Show distinct personcode values from stktrans for insurance/contract docs."""
        self.stdout.write('\n=== Insurance personcodes (from stktrans via stktransm) ===\n')

        # Use a subquery approach to avoid the JOIN + OR combination that fails
        self.stdout.write('  Querying stktransm for ptclassifcode = 15 (insurance)...\n')

        self._run_query(conn, 'SET ROWCOUNT 0')

        rows15 = self._run_query(conn, """
            SELECT sm.phcode, sm.branchcode, sm.docnumber, sm.docdate
            FROM SOFTECHDB9.dbo.stktransm sm
            WHERE sm.ptclassifcode = '15'
            ORDER BY sm.docdate DESC
        """, label='ptclassifcode=15')

        self._run_query(conn, 'SET ROWCOUNT 0')

        if rows15:
            self.stdout.write(f'  Found {len(rows15)} rows with ptclassifcode=15 (insurance)\n')
            self.stdout.write('  Sample rows:\n')
            for r in rows15[:5]:
                self.stdout.write(f'    phcode={r[0]}  branch={r[1]}  docno={r[2]}  date={str(r[3])[:10]}\n')

        self.stdout.write('\n  Querying stktransm for ptclassifcode = 10 (contract)...\n')

        rows10 = self._run_query(conn, """
            SELECT sm.phcode, sm.branchcode, sm.docnumber, sm.docdate
            FROM SOFTECHDB9.dbo.stktransm sm
            WHERE sm.ptclassifcode = '10'
            ORDER BY sm.docdate DESC
        """, label='ptclassifcode=10')

        if rows10:
            self.stdout.write(f'  Found {len(rows10)} rows with ptclassifcode=10 (contract)\n')
            self.stdout.write('  Sample rows:\n')
            for r in rows10[:5]:
                self.stdout.write(f'    phcode={r[0]}  branch={r[1]}  docno={r[2]}  date={str(r[3])[:10]}\n')

        # Now get personcode from stktrans matching those docnumbers
        self.stdout.write('\n  Getting personcode from stktrans for insurance docs...\n')
        if rows15:
            # Use first 3 docnumbers from rows15 to find personcode
            sample_docs = [str(r[2]) for r in rows15[:3] if r[2]]
            for docno in sample_docs:
                pc_rows = self._run_query(conn, """
                    SELECT st.personcode, st.branchcode, st.doccode, st.docnumber
                    FROM SOFTECHDB9.dbo.stktrans st
                    WHERE st.docnumber = ?
                """, params=[docno], label=f'stktrans docno={docno}')
                if pc_rows:
                    self.stdout.write(f'    docno={docno} → personcode={pc_rows[0][0]}  branch={pc_rows[0][1]}\n')

    def _show_motalba_lines(self, conn, motalbano: int):
        """Show all lines for a specific motalba."""
        self.stdout.write(f'\n=== Lines for motalbano={motalbano} ===\n')

        # Header
        header_rows = self._run_query(conn, """
            SELECT ms.personcode, ms.motfromdate, ms.mottodate,
                   ms.motnoofpatients, ms.docvaluetotal, ms.docvaluenet
            FROM SOFTECHDB9.dbo.motalbas ms
            WHERE ms.motalbano = ?
        """, params=[motalbano], label='motalbas header')

        if header_rows:
            r = header_rows[0]
            self.stdout.write(
                f'  personcode={r[0]}  from={str(r[1])[:10]}  to={str(r[2])[:10]}\n'
                f'  patients={r[3]}  total={r[4]}  net={r[5]}\n\n'
            )

        # Detail lines
        detail_rows = self._run_query(conn, """
            SELECT m.docnumber, m.branchcode, m.docdate, m.doccode,
                   m.motalba_docorder, m.docvalue_grandtotal, m.ppersoncode, m.invdel
            FROM SOFTECHDB9.dbo.motalba m
            WHERE m.motalbano = ?
            ORDER BY m.motalba_docorder, m.docdate
        """, params=[motalbano], label='motalba lines')

        if not detail_rows:
            return
        self.stdout.write(f'  Found {len(detail_rows)} prescription lines\n')
        self.stdout.write(
            f'{"order":>6}  {"docnumber":>10}  {"branch":<8}  {"date":<12}  '
            f'{"code":<5}  {"value":>12}  {"ppersoncode":<12}  del\n'
        )
        self.stdout.write('-' * 80 + '\n')
        for r in detail_rows[:20]:
            self.stdout.write(
                f'{str(r[4] or ""):>6}  {str(r[0] or ""):>10}  {str(r[1] or ""):<8}  '
                f'{str(r[2] or "")[:10]:<12}  {str(r[3] or ""):<5}  '
                f'{str(r[5] or ""):>12}  {str(r[6] or ""):<12}  {r[7]}\n'
            )

    def _all_tables(self, conn):
        self.stdout.write('\n=== All Softech tables ===\n')
        rows = self._run_query(conn, """
            SELECT o.name
            FROM SOFTECHDB9.dbo.sysobjects o
            WHERE o.type = 'U'
            ORDER BY o.name
        """, label='all tables')
        if rows:
            for r in rows:
                self.stdout.write(f'  {r[0]}\n')
            self.stdout.write(f'\nTotal: {len(rows)} tables\n')

    def _run_full_discovery(self, conn, template):
        # ── Insurance tables ───────────────────────────────────────────────────
        self.stdout.write('\n=== Insurance-related tables ===\n')
        table_rows = self._run_query(conn, """
            SELECT o.name
            FROM SOFTECHDB9.dbo.sysobjects o
            WHERE o.type = 'U'
              AND (
                   o.name LIKE '%hi%'
                OR o.name LIKE '%health%'
                OR o.name LIKE '%insur%'
                OR o.name LIKE '%motalb%'
                OR o.name LIKE '%taamin%'
                OR o.name LIKE '%claim%'
                OR o.name LIKE '%tamin%'
              )
            ORDER BY o.name
        """, label='insurance tables')

        if table_rows:
            for row in table_rows:
                self.stdout.write(f'  {row[0]}\n')
                col_rows = self._run_query(conn, template.format(table=row[0]), label=row[0])
                if col_rows:
                    for c in col_rows:
                        self.stdout.write(f'      [{c[0]}] {c[1]}({c[2]})\n')
        else:
            self.stdout.write('  No tables found.\n')

        # ── custdiscpclassif ──────────────────────────────────────────────────
        self.stdout.write('\n=== custdiscpclassif (contract discount tiers) ===\n')
        rows = self._run_query(conn, """
            SELECT c.custdiscpcode, c.custdiscpdescr
            FROM SOFTECHDB9.dbo.custdiscpclassif c
            ORDER BY c.custdiscpcode
        """, label='custdiscpclassif')
        if rows:
            for r in rows:
                self.stdout.write(f'  [{r[0]}] {r[1]}\n')

        # ── itemsorigin ────────────────────────────────────────────────────────
        self.stdout.write('\n=== itemsorigin (local vs imported) ===\n')
        rows = self._run_query(conn, """
            SELECT io.itemorigincode, io.itemoriginname, io.originnamearabic, io.importedorigin
            FROM SOFTECHDB9.dbo.itemsorigin io
        """, label='itemsorigin')
        if rows:
            for r in rows:
                flag = '✓ IMPORTED' if str(r[3] or '').strip() == '1' else '  local'
                self.stdout.write(f'  [{r[0]}] {r[2] or r[1]}  {flag}\n')

        # ── ptclassifcode=15 transactions ─────────────────────────────────────
        self.stdout.write('\n=== Sample stktransm rows (ptclassifcode = 15 = insurance) ===\n')
        rows = self._run_query(conn, """
            SELECT sm.phcode, sm.docnumber, sm.docdate, sm.docvalue, sm.branchcode
            FROM SOFTECHDB9.dbo.stktransm sm
            WHERE sm.ptclassifcode = '15'
            ORDER BY sm.docdate DESC
        """, label='ptclassifcode=15')
        if rows:
            for r in rows[:5]:
                self.stdout.write(f'  phcode={r[0]}  doc={r[1]}  date={str(r[2])[:10]}  '
                                   f'value={r[3]}  branch={r[4]}\n')
            if len(rows) > 5:
                self.stdout.write(f'  ... {len(rows)-5} more rows\n')

        # ── Recent motalbas ────────────────────────────────────────────────────
        self.stdout.write('\n=== Recent motalbas (use --motalbas for full list) ===\n')
        rows_all = self._run_query(conn, """
            SELECT ms.motalbano, ms.personcode, ms.motfromdate, ms.mottodate,
                   ms.motnoofpatients, ms.docvaluetotal, ms.docvaluenet
            FROM SOFTECHDB9.dbo.motalbas ms
            ORDER BY ms.motalbano DESC
        """, label='motalbas sample')
        rows = (rows_all or [])[:5]
        if rows:
            for r in rows:
                self.stdout.write(
                    f'  motalbano={r[0]}  personcode={r[1]}  '
                    f'from={str(r[2])[:10]}→{str(r[3])[:10]}  '
                    f'rx={r[4]}  net={r[6]}\n'
                )

        self.stdout.write('\n')
        self.stdout.write(self.style.SUCCESS('Discovery complete.\n'))
        self.stdout.write(
            'Next steps:\n'
            '  python manage.py inspect_insurance_schema --stktransm-cols\n'
            '     → find patient name field in stktransm\n'
            '  python manage.py inspect_insurance_schema --motalbas\n'
            '     → list all motalbas with personcode, dates, totals\n'
            '  python manage.py inspect_insurance_schema --personcodes\n'
            '     → find personcode values for insurance clients in stktrans\n'
            '  python manage.py inspect_insurance_schema --sample-motalba <no>\n'
            '     → inspect all lines for a specific motalbano\n'
        )
