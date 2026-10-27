"""
python manage.py inspect_procurement_sources [--days 365]

READ-ONLY diagnostic for the Procurement Intelligence overhaul.  SELECT-only —
never writes to SOFTECHDB9.  Two investigations:

  A) FREE-GOODS / BONUS / DISCOUNT column discovery
     Scans syscolumns on stktrans / stktransm for names hinting at free goods,
     bonus, gift, offer, or discount, then samples real data on purchase docs
     (doccode 10) so we can find the TRUE FOC signal (current engine only flags
     unit_price = 0, which the AVG(transprice) grouping hides).

  B) SUPPLIER CLASSIFICATION (persontypes / persontypesclassif)
     Dumps the real SofTech ptcode / ptclassifcode label tables, then shows how
     actual purchase suppliers (cust_branch_code on doccode-10 docs in the last
     N days) distribute across those codes — the ground truth the segmentation
     engine should map to instead of its hard-coded guess map.

Usage:
    python manage.py inspect_procurement_sources
    python manage.py inspect_procurement_sources --days 180
    python manage.py inspect_procurement_sources > procurement_probe.txt
"""
from django.core.management.base import BaseCommand


# Column-name hints for free-goods / bonus / discount signals
FOC_HINTS = ['free', 'bonus', 'gift', 'offer', 'hadya', 'hadeya', 'foc', 'grant']
DISCOUNT_HINTS = ['disc', 'discount', 'promo']

NUMERIC_TYPE_NAMES = {
    'int', 'smallint', 'tinyint', 'bigint',
    'numeric', 'decimal', 'float', 'real', 'money', 'smallmoney',
}


class Command(BaseCommand):
    help = 'READ-ONLY probe: discover FOC/bonus/discount columns + dump SofTech supplier classification codes'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=365,
                            help='Lookback window for supplier classification sampling (default 365)')
        parser.add_argument('--sample', type=int, default=8,
                            help='Number of sample values for text columns (default 8)')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        days   = options['days']
        sample = options['sample']

        try:
            conn = get_sybase_connection()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Cannot connect to Sybase: {e}'))
            return

        self._section('A) FREE-GOODS / BONUS / DISCOUNT COLUMN DISCOVERY')
        self._discover_foc_columns(conn, sample)
        self._probe_foc_signals(conn, days)

        self._section('B) SUPPLIER CLASSIFICATION (persontypes / persontypesclassif)')
        self._dump_person_types(conn)
        self._dump_person_classifs(conn)
        self._supplier_code_distribution(conn, days)

        conn.close()
        self.stdout.write('\nDone. This command performed SELECT queries only.\n')

    # ── helpers ────────────────────────────────────────────────────────────────

    def _section(self, title):
        self.stdout.write('\n' + '═' * 82)
        self.stdout.write(f'  {title}')
        self.stdout.write('═' * 82)

    def _q(self, conn, sql, params=None):
        cur = conn.cursor()
        cur.execute(sql, params or [])
        rows = cur.fetchall()
        cur.close()
        return rows

    # ── A) FOC column discovery ─────────────────────────────────────────────────

    def _discover_foc_columns(self, conn, sample):
        like_parts = []
        for kw in FOC_HINTS + DISCOUNT_HINTS:
            like_parts.append(f"LOWER(c.name) LIKE '%{kw}%'")
        where_like = ' OR '.join(like_parts)

        sql = f"""
            SELECT o.name AS table_name, c.name AS col_name,
                   t.name AS data_type, c.length AS col_len, c.colid
            FROM   SOFTECHDB9.dbo.syscolumns c
            JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
            JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
            WHERE  o.type = 'U'
              AND  o.name IN ('stktrans', 'stktransm')
              AND  ({where_like})
            ORDER  BY o.name, c.colid
        """
        try:
            cols = self._q(conn, sql)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'syscolumns discovery failed: {e}'))
            return

        if not cols:
            self.stdout.write(self.style.WARNING(
                'No free/bonus/discount-named columns found on stktrans/stktransm.'
            ))
        else:
            self.stdout.write(f'Found {len(cols)} candidate column(s):\n')
            for tbl, col, typ, ln, pos in cols:
                self.stdout.write(f'  {str(tbl):<12} [{pos:>3}] {str(col):<28} {str(typ):<12} len={ln}')
                data_type = str(typ).lower()
                is_num = any(nt in data_type for nt in NUMERIC_TYPE_NAMES)
                try:
                    if is_num:
                        r = self._q(conn, f"""
                            SELECT COUNT(*),
                                   SUM(CASE WHEN {col} IS NOT NULL AND {col} <> 0 THEN 1 ELSE 0 END),
                                   MIN({col}), MAX({col}), AVG(CONVERT(float,{col}))
                            FROM SOFTECHDB9.dbo.{tbl}
                        """)[0]
                        tot, nz, mn, mx, av = r
                        pct = round(100.0 * int(nz or 0) / int(tot), 2) if tot else 0
                        av = round(float(av), 4) if av is not None else None
                        self.stdout.write(f'        rows={tot} non-zero={nz or 0} ({pct}%) min={mn} max={mx} avg={av}')
                    else:
                        vals = [str(x[0]) for x in self._q(conn, f"""
                            SELECT TOP {sample} DISTINCT {col} FROM SOFTECHDB9.dbo.{tbl}
                            WHERE {col} IS NOT NULL AND {col} != ''
                        """)]
                        self.stdout.write(f'        samples: {vals or "(all empty/null)"}')
                except Exception as e:
                    self.stdout.write(f'        [sample failed: {e}]')

    def _probe_foc_signals(self, conn, days):
        """Compare candidate FOC signals on real purchase (doccode 10) lines."""
        self.stdout.write('\n  FOC signal comparison on doccode-10 purchase lines '
                          f'(last {days} days):')
        probes = [
            ('transqty>0 AND transprice=0        (current engine rule)',
             'st.transqty > 0 AND st.transprice = 0'),
            ('transqty>0 AND transprice_total=0  (line value zero)',
             'st.transqty > 0 AND COALESCE(st.transprice_total,0) = 0'),
            ('transqty>0 AND transprice>0 AND transprice_total=0',
             'st.transqty > 0 AND st.transprice > 0 AND COALESCE(st.transprice_total,0) = 0'),
        ]
        for label, cond in probes:
            try:
                r = self._q(conn, f"""
                    SELECT COUNT(*)
                    FROM SOFTECHDB9.dbo.stktransm sm
                    JOIN SOFTECHDB9.dbo.stktrans  st
                      ON st.branchcode=sm.branchcode AND st.doccode=sm.doccode
                     AND st.docnumber=sm.docnumber   AND st.docdate=sm.docdate
                    WHERE sm.doccode='10'
                      AND sm.docdate >= DATEADD(day, -{int(days)}, GETDATE())
                      AND {cond}
                """)[0]
                self.stdout.write(f'    {label:<52} → {r[0]:>10,} lines')
            except Exception as e:
                self.stdout.write(f'    {label:<52} → [failed: {e}]')

    # ── B) classification dumps ─────────────────────────────────────────────────

    def _dump_person_types(self, conn):
        self.stdout.write('\n  persontypes (ptcode → label):')
        try:
            for r in self._q(conn, """
                SELECT ptcode, ptdescr, ptedescr FROM SOFTECHDB9.dbo.persontypes
                ORDER BY ptcode
            """):
                self.stdout.write(f'    {str(r[0]):<6} {str(r[1] or ""):<40} {str(r[2] or "")}')
        except Exception as e:
            self.stdout.write(f'    [persontypes failed: {e}]')

    def _dump_person_classifs(self, conn):
        self.stdout.write('\n  persontypesclassif (ptcode, ptclassifcode → label):')
        try:
            for r in self._q(conn, """
                SELECT ptcode, ptclassifcode, ptclassifdescr
                FROM SOFTECHDB9.dbo.persontypesclassif
                ORDER BY ptcode, ptclassifcode
            """):
                self.stdout.write(f'     pt={str(r[0]):<5} classif={str(r[1]):<8} {str(r[2] or "")}')
        except Exception as e:
            self.stdout.write(f'    [persontypesclassif failed: {e}]')

    def _supplier_code_distribution(self, conn, days):
        """How real purchase suppliers distribute across ptcode/ptclassifcode."""
        self.stdout.write(f'\n  Real purchase suppliers (doccode-10 cust_branch_code, last {days}d) '
                          'by ptcode/ptclassifcode:')
        try:
            rows = self._q(conn, f"""
                SELECT pd.ptcode, pd.ptclassifcode,
                       COUNT(DISTINCT sup.supplier_code) AS supplier_count
                FROM (
                    SELECT DISTINCT sm.cust_branch_code AS supplier_code
                    FROM SOFTECHDB9.dbo.stktransm sm
                    WHERE sm.doccode='10'
                      AND sm.docdate >= DATEADD(day, -{int(days)}, GETDATE())
                      AND sm.cust_branch_code IS NOT NULL
                      AND sm.cust_branch_code != ''
                ) sup
                LEFT JOIN SOFTECHDB9.dbo.personsdata pd
                       ON pd.personcode = sup.supplier_code
                GROUP BY pd.ptcode, pd.ptclassifcode
                ORDER BY supplier_count DESC
            """)
            self.stdout.write(f'    {"ptcode":<8} {"classif":<10} {"suppliers":>10}   label')
            self.stdout.write('    ' + '-' * 70)
            # Pre-load classif labels for readability
            labels = {}
            try:
                for r in self._q(conn, """
                    SELECT ptcode, ptclassifcode, ptclassifdescr
                    FROM SOFTECHDB9.dbo.persontypesclassif
                """):
                    labels[(str(r[0]), str(r[1]))] = str(r[2] or '')
            except Exception:
                pass
            for pt, cl, cnt in rows:
                lbl = labels.get((str(pt), str(cl)), '')
                self.stdout.write(f'    {str(pt or "-"):<8} {str(cl or "-"):<10} {cnt:>10,}   {lbl}')
        except Exception as e:
            self.stdout.write(f'    [supplier distribution failed: {e}]')
