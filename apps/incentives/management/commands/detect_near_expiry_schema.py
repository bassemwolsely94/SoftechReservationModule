"""
apps/incentives/management/commands/detect_near_expiry_schema.py

Schema-detection command for Near Expiry Incentive implementation.

Queries the live SOFTECHDB9 Sybase database and reports:
  1. All columns on stktrans  (+ their types)
  2. All columns on stktransm (+ their types)
  3. All columns on stkbal    (+ their types)
  4. Any batch-related tables (stkbalbatch, itemsbatch, lotmaster, etc.)
  5. A sample of stktrans rows to see actual batch/expiry values
  6. Whether items table has shelf_life / max_expiry_days fields

Run with:
    python manage.py detect_near_expiry_schema
"""
import sys
from django.core.management.base import BaseCommand

# Force stdout to utf-8 to avoid cp1256 encoding issues on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


class Command(BaseCommand):
    help = 'Detect SOFTECH stktrans batch/expiry schema for Near Expiry Incentive'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        self._print('='*70)
        self._print('  SOFTECH Near-Expiry Schema Detection')
        self._print('='*70)

        try:
            conn = get_sybase_connection()
        except Exception as e:
            self._print(f'ERROR: Cannot connect to Sybase: {e}')
            return

        cur = conn.cursor()

        # ── 1. Full column list: stktrans ─────────────────────────────────────
        self._section('1. stktrans columns (sp_columns)')
        self._sp_columns(cur, 'stktrans')

        # ── 2. Full column list: stktransm ────────────────────────────────────
        self._section('2. stktransm columns (sp_columns)')
        self._sp_columns(cur, 'stktransm')

        # ── 3. Full column list: stkbal ───────────────────────────────────────
        self._section('3. stkbal columns (sp_columns)')
        self._sp_columns(cur, 'stkbal')

        # ── 4. Search for batch-related tables ────────────────────────────────
        self._section('4. Batch/expiry-related tables in SOFTECHDB9')
        batch_table_sql = """
            SELECT name
            FROM SOFTECHDB9.dbo.sysobjects
            WHERE type = 'U'
              AND (
                   LOWER(name) LIKE '%batch%'
                OR LOWER(name) LIKE '%expir%'
                OR LOWER(name) LIKE '%lot%'
                OR LOWER(name) LIKE '%shelf%'
                OR LOWER(name) LIKE '%stkbal%'
              )
            ORDER BY name
        """
        try:
            cur.execute(batch_table_sql)
            rows = cur.fetchall()
            if rows:
                self._print(f'  Found {len(rows)} related table(s):')
                for r in rows:
                    tbl = str(r[0]).strip()
                    self._print(f'    TABLE: {tbl}')
                    self._sp_columns(cur, tbl, indent=6)
            else:
                self._print('  No batch/expiry/lot tables found.')
        except Exception as e:
            self._print(f'  Query failed: {e}')

        # ── 5. Sample stktrans rows (sale doccode=115) ─────────────────────────
        self._section('5. Sample stktrans rows (doccode=115, rowcount=3)')
        sample_sql = """
            SET ROWCOUNT 3
            SELECT
                st.branchcode,
                st.doccode,
                st.docnumber,
                st.docdate,
                st.itemcode,
                st.transqty,
                st.dblitemflag,
                st.storecode
            FROM SOFTECHDB9.dbo.stktrans st
            WHERE st.doccode = '115'
              AND st.transqty > 0
            ORDER BY st.docdate DESC
            SET ROWCOUNT 0
        """
        try:
            cur.execute(sample_sql)
            rows = cur.fetchall()
            desc = cur.description
            if desc:
                headers = [str(d[0]) for d in desc]
                self._print('  Columns: ' + ' | '.join(headers))
                for r in rows:
                    self._print('  Row:     ' + ' | '.join(str(v) for v in r))
            else:
                self._print('  (no result set)')
        except Exception as e:
            self._print(f'  Sample query failed: {e}')

        # ── 6. Probe for batch/expiry specific columns on stktrans ────────────
        self._section('6. Probing batch/expiry column names on stktrans')
        candidate_cols = [
            'lotno', 'lot_no', 'batchno', 'batch_no', 'batchnumber',
            'expirydate', 'expiry_date', 'expdate', 'exp_date',
            'productiondate', 'mfgdate', 'manufacture_date',
            'shelflife', 'shelf_life', 'lotexpiry',
        ]
        found_stktrans = []
        for col in candidate_cols:
            probe_sql = f"SELECT {col} FROM SOFTECHDB9.dbo.stktrans WHERE 1=0"
            try:
                cur.execute(probe_sql)
                cur.fetchall()
                sample_val = self._get_sample_val(cur, 'stktrans', col)
                found_stktrans.append((col, sample_val))
                self._print(f'  [FOUND] stktrans.{col}  (sample: {sample_val})')
            except Exception:
                pass

        if not found_stktrans:
            self._print(
                '  No standard batch/expiry columns found on stktrans.\n'
                '  Batch info is likely in a separate table (see section 4).'
            )

        # ── 7. Probe batch/expiry columns on stkbal ───────────────────────────
        self._section('7. Probing batch/expiry column names on stkbal')
        found_stkbal = []
        for col in candidate_cols:
            probe_sql = f"SELECT {col} FROM SOFTECHDB9.dbo.stkbal WHERE 1=0"
            try:
                cur.execute(probe_sql)
                cur.fetchall()
                sample_val = self._get_sample_val(cur, 'stkbal', col)
                found_stkbal.append((col, sample_val))
                self._print(f'  [FOUND] stkbal.{col}  (sample: {sample_val})')
            except Exception:
                pass
        if not found_stkbal:
            self._print('  No batch/expiry columns on stkbal.')

        # ── 8. items table shelf-life fields ──────────────────────────────────
        self._section('8. Probing items table for shelf-life / expiry fields')
        item_candidates = [
            'shelflife', 'shelf_life', 'maxexpiry', 'max_expiry',
            'expirydays', 'expiry_days', 'itemexpiry', 'expirymonths',
            'validitydays', 'validity_days',
        ]
        found_items = []
        for col in item_candidates:
            probe_sql = f"SELECT {col} FROM SOFTECHDB9.dbo.items WHERE 1=0"
            try:
                cur.execute(probe_sql)
                cur.fetchall()
                sample_val = self._get_sample_val(cur, 'items', col)
                found_items.append((col, sample_val))
                self._print(f'  [FOUND] items.{col}  (sample: {sample_val})')
            except Exception:
                pass
        if not found_items:
            self._print('  No shelf-life/expiry fields on items table.')

        # ── 9. Batch-split statistics ─────────────────────────────────────────
        self._section('9. Batch-split stats (last 30 days, doccode=115)')
        stats_sql = """
            SELECT
                COUNT(*)                                              AS total_rows,
                SUM(CASE WHEN dblitemflag > 1 THEN 1 ELSE 0 END)    AS multi_batch_rows,
                COUNT(DISTINCT itemcode)                              AS distinct_items,
                MIN(dblitemflag)                                      AS min_dblitemflag,
                MAX(dblitemflag)                                      AS max_dblitemflag
            FROM SOFTECHDB9.dbo.stktrans
            WHERE doccode = '115'
              AND docdate >= DATEADD(day, -30, GETDATE())
        """
        try:
            cur.execute(stats_sql)
            row = cur.fetchone()
            if row:
                self._print(
                    f'  total_rows={row[0]}  multi_batch_rows={row[1]}  '
                    f'distinct_items={row[2]}  '
                    f'dblitemflag range: {row[3]}..{row[4]}'
                )
        except Exception as e:
            self._print(f'  Stats query failed: {e}')

        # ── 10. If stkbalbatch or similar found, sample it ────────────────────
        # (handled in section 4 already)

        conn.close()
        self._print('\n' + '='*70)
        self._print('  Schema detection complete.')
        self._print('='*70)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _print(self, msg):
        """Safe stdout write that handles encoding issues."""
        try:
            self.stdout.write(str(msg))
        except UnicodeEncodeError:
            self.stdout.write(str(msg).encode('ascii', 'replace').decode('ascii'))

    def _section(self, title):
        self._print(f'\n--- {title} ---')

    def _sp_columns(self, cur, table_name, indent=2):
        """Use sp_columns to list columns for a table."""
        pad = ' ' * indent
        try:
            cur.execute(f'EXEC sp_columns {table_name}')
            rows = cur.fetchall()
            desc = cur.description
            if not rows:
                self._print(f'{pad}(no columns returned)')
                return
            # Find column indices from description
            col_names = [str(d[0]).upper() for d in desc]
            try:
                col_name_idx  = col_names.index('COLUMN_NAME')
            except ValueError:
                col_name_idx = 3
            try:
                type_name_idx = col_names.index('TYPE_NAME')
            except ValueError:
                type_name_idx = 5
            try:
                size_idx = col_names.index('COLUMN_SIZE')
            except ValueError:
                size_idx = 6
            try:
                nullable_idx = col_names.index('NULLABLE')
            except ValueError:
                nullable_idx = 10

            self._print(f'{pad}{"COLUMN_NAME":<35} {"TYPE_NAME":<20} {"SIZE":<8} NULLABLE')
            self._print(f'{pad}' + '-' * 65)
            for r in rows:
                try:
                    col_n  = str(r[col_name_idx]).strip()
                    type_n = str(r[type_name_idx]).strip()
                    size   = str(r[size_idx])
                    nullok = 'YES' if r[nullable_idx] else 'NO'
                    self._print(f'{pad}{col_n:<35} {type_n:<20} {size:<8} {nullok}')
                except Exception as row_err:
                    self._print(f'{pad}  (row parse error: {row_err})')
        except Exception as e:
            self._print(f'{pad}(sp_columns failed: {e})')

    def _get_sample_val(self, cur, table, col):
        """Get a non-null sample value for a column."""
        try:
            cur.execute(f"""
                SET ROWCOUNT 1
                SELECT {col} FROM SOFTECHDB9.dbo.{table} WHERE {col} IS NOT NULL
                SET ROWCOUNT 0
            """)
            r = cur.fetchone()
            return str(r[0]) if r else '(all null)'
        except Exception:
            return '(sample failed)'
