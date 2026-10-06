"""
python manage.py inspect_tax_columns [--tables stktransm stktrans items ...]

Scans SOFTECHDB9 syscolumns for every column whose name contains 'tax' or 'vat'
(case-insensitive, anywhere in the name).

For each hit it also runs a lightweight aggregate against the real table to show:
  - how many rows have a non-NULL, non-zero value
  - min / max / avg value (for numeric columns)
  - a few sample values (for varchar columns)

Output is tab-separated so you can pipe it to a file:
    python manage.py inspect_tax_columns > tax_columns.txt

Usage:
    python manage.py inspect_tax_columns               # all tables in SOFTECHDB9
    python manage.py inspect_tax_columns --tables stktransm stktrans
    python manage.py inspect_tax_columns --sample 10   # show N sample values for text cols
"""
from django.core.management.base import BaseCommand


# Tables we care about most for purchase cost intelligence
PRIORITY_TABLES = {
    'stktransm', 'stktrans', 'items', 'personsdata',
    'invoices', 'invoicelines', 'taxrates', 'taxcodes',
}

# Sybase numeric base types (type ids from systypes)
NUMERIC_TYPE_NAMES = {
    'int', 'smallint', 'tinyint', 'bigint',
    'numeric', 'decimal', 'float', 'real',
    'money', 'smallmoney',
}


class Command(BaseCommand):
    help = 'Discover all tax/vat columns in SOFTECHDB9 and sample their actual data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tables', nargs='*', default=None,
            help='Restrict scan to these table names (default: all user tables)',
        )
        parser.add_argument(
            '--sample', type=int, default=5,
            help='Number of non-zero sample values to show for text columns (default: 5)',
        )
        parser.add_argument(
            '--no-sample', action='store_true',
            help='Skip data sampling — only report column metadata',
        )

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        restrict_tables = options['tables']
        sample_n        = options['sample']
        skip_sample     = options['no_sample']

        self.stdout.write('\n' + '═' * 80)
        self.stdout.write('  SOFTECHDB9 — TAX / VAT COLUMN DISCOVERY')
        self.stdout.write('═' * 80 + '\n')

        try:
            conn = get_sybase_connection()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Cannot connect to Sybase: {e}'))
            return

        # ── Step 1: find all matching columns via syscolumns ──────────────────
        table_filter = ''
        if restrict_tables:
            quoted = ', '.join(f"'{t}'" for t in restrict_tables)
            table_filter = f"AND o.name IN ({quoted})"

        discovery_sql = f"""
            SELECT
                o.name      AS table_name,
                c.name      AS col_name,
                t.name      AS data_type,
                c.length    AS col_len,
                c.colid     AS col_pos
            FROM   SOFTECHDB9.dbo.syscolumns c
            JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
            JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
            WHERE  o.type = 'U'
              AND  (LOWER(c.name) LIKE '%tax%'
                OR  LOWER(c.name) LIKE '%vat%')
              {table_filter}
            ORDER  BY
                CASE WHEN o.name IN ('stktransm','stktrans') THEN 0 ELSE 1 END,
                o.name,
                c.colid
        """

        try:
            cur = conn.cursor()
            cur.execute(discovery_sql)
            columns = cur.fetchall()
            cur.close()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'syscolumns query failed: {e}'))
            conn.close()
            return

        if not columns:
            self.stdout.write(self.style.WARNING(
                'No columns found matching *tax* or *vat* in SOFTECHDB9.'
            ))
            conn.close()
            return

        self.stdout.write(
            f'Found {len(columns)} column(s) matching *tax* or *vat*:\n'
        )

        # Group by table for readability
        tables_seen: dict[str, list] = {}
        for row in columns:
            tbl = str(row[0])
            tables_seen.setdefault(tbl, []).append(row)

        # ── Step 2: for each column, sample real data ─────────────────────────
        for tbl, cols in tables_seen.items():
            is_priority = tbl.lower() in PRIORITY_TABLES
            marker = ' ★' if is_priority else ''
            self.stdout.write(
                self.style.SUCCESS(f'\n┌─ TABLE: SOFTECHDB9.dbo.{tbl}{marker}')
            )
            self.stdout.write(f'│  ({len(cols)} matching column(s))\n│')

            for row in cols:
                col_name  = str(row[1])
                data_type = str(row[2]).lower()
                col_len   = row[3]
                col_pos   = row[4]

                self.stdout.write(
                    f'│  [{col_pos:>3}] {col_name:<30}  type={data_type:<12}  len={col_len}'
                )

                if skip_sample:
                    continue

                # Sample query — different for numeric vs text
                is_numeric = any(nt in data_type for nt in NUMERIC_TYPE_NAMES)
                try:
                    cur = conn.cursor()
                    if is_numeric:
                        cur.execute(f"""
                            SELECT
                                COUNT(*)                           AS total_rows,
                                SUM(CASE WHEN {col_name} IS NOT NULL
                                          AND {col_name} <> 0
                                         THEN 1 ELSE 0 END)       AS nonzero_count,
                                MIN({col_name})                    AS min_val,
                                MAX({col_name})                    AS max_val,
                                AVG(CONVERT(float, {col_name}))   AS avg_val
                            FROM SOFTECHDB9.dbo.{tbl}
                        """)
                        r = cur.fetchone()
                        if r:
                            total      = r[0]
                            nonzero    = r[1] or 0
                            min_v      = r[2]
                            max_v      = r[3]
                            avg_v      = round(float(r[4]), 4) if r[4] is not None else None
                            pct = round(100.0 * int(nonzero) / int(total), 1) if total else 0
                            self.stdout.write(
                                f'│       rows={total}  non-zero={nonzero} ({pct}%)  '
                                f'min={min_v}  max={max_v}  avg={avg_v}'
                            )
                    else:
                        # Text column — show distinct non-empty samples
                        cur.execute(f"""
                            SELECT TOP {sample_n} DISTINCT {col_name}
                            FROM   SOFTECHDB9.dbo.{tbl}
                            WHERE  {col_name} IS NOT NULL
                              AND  {col_name} != ''
                        """)
                        samples = [str(r[0]) for r in cur.fetchall()]
                        self.stdout.write(
                            f'│       samples: {samples if samples else "(all empty/null)"}'
                        )
                    cur.close()
                except Exception as e:
                    self.stdout.write(f'│       [sample failed: {e}]')

            self.stdout.write('└' + '─' * 60)

        conn.close()

        # ── Step 3: summary table ─────────────────────────────────────────────
        self.stdout.write('\n' + '═' * 80)
        self.stdout.write('  SUMMARY — all discovered columns')
        self.stdout.write('═' * 80)
        self.stdout.write(f'  {"Table":<25} {"Column":<30} {"Type":<12} Priority')
        self.stdout.write('  ' + '-' * 75)
        for row in columns:
            tbl  = str(row[0])
            col  = str(row[1])
            typ  = str(row[2])
            mark = '★' if tbl.lower() in PRIORITY_TABLES else ' '
            self.stdout.write(f'  {tbl:<25} {col:<30} {typ:<12} {mark}')
        self.stdout.write('═' * 80 + '\n')
        self.stdout.write(
            'Next step: run_procurement_engine will use any confirmed columns above.\n'
            'Update apps/procurement/queries.py → QUERY_INVOICE_TAX with the real column names.\n'
        )
