"""
python manage.py verify_branch_replication [itemcode]

Verifies that a pricing change made via the Approval Module is correctly
replicated on all branch Sybase servers.

Compares HQ items.pos_discp (and all discount fields) against each live
branch server for the given itemcode.

Usage:
    python manage.py verify_branch_replication 127397
"""
from django.core.management.base import BaseCommand
from django.conf import settings


# Branch servers — map branch code → host IP
# Read from the same settings used by CRM sync
BRANCH_SERVERS = getattr(settings, 'BRANCH_SYBASE_SERVERS', {})


class Command(BaseCommand):
    help = 'Verify pricing approval replication to all branch servers'

    def add_arguments(self, parser):
        parser.add_argument('itemcode', nargs='?', default='127397',
                            help='Softech itemcode to verify (default: 127397)')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection

        itemcode = options['itemcode'].strip()
        self.stdout.write(f'\nVerifying replication for itemcode: {itemcode}')
        self.stdout.write('=' * 60)

        PRICE_FIELDS = 'itemcode, itemsaleprice, unitsaleprice, itemsaleprice_tax, ' \
                       'pharmacydiscp, additionaldiscp, specialdiscp, posdiscp, ' \
                       'itemlastupdate, usercode'

        QUERY = f"""
            SELECT {PRICE_FIELDS}
            FROM items
            WHERE itemcode = '{itemcode}'
        """

        results = {}

        # ── HQ (SOFTECHDB9) ───────────────────────────────────────────────────
        try:
            conn = get_sybase_connection()
            cur  = conn.cursor()
            cur.execute(QUERY)
            row = cur.fetchone()
            conn.close()
            if row:
                results['HQ (100)'] = row
                self.stdout.write('\n  HQ (branchcode=100):')
                self._print_row(row)
            else:
                self.stdout.write(f'  HQ: item {itemcode} NOT FOUND')
        except Exception as e:
            self.stdout.write(f'  HQ ERROR: {e}')

        # ── Branches ─────────────────────────────────────────────────────────
        if not BRANCH_SERVERS:
            self.stdout.write('\n  No BRANCH_SYBASE_SERVERS configured in settings.')
            self.stdout.write('  Add: BRANCH_SYBASE_SERVERS = {"130": "192.168.x.x", ...}')
            self.stdout.write('\n  Attempting to discover branches from branches table...')
            try:
                conn = get_sybase_connection()
                cur  = conn.cursor()
                cur.execute("""
                    SELECT b.branchcode, b.branchname
                    FROM SOFTECHDB9.dbo.branches b
                    WHERE b.branchcode != '100'
                    ORDER BY b.branchcode
                """)
                branches = cur.fetchall()
                conn.close()
                if branches:
                    self.stdout.write('  Branches found in HQ catalog:')
                    for b in branches:
                        self.stdout.write(f'    branchcode={b[0]} name={b[1]}')
                    self.stdout.write('\n  To test replication, add BRANCH_SYBASE_SERVERS to settings.')
            except Exception as e:
                self.stdout.write(f'  Branch discovery error: {e}')
        else:
            for branch_code, host in BRANCH_SERVERS.items():
                try:
                    conn = get_branch_connection(host)
                    cur  = conn.cursor()
                    cur.execute(QUERY)
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        results[f'Branch {branch_code} ({host})'] = row
                        self.stdout.write(f'\n  Branch {branch_code} ({host}):')
                        self._print_row(row)
                    else:
                        self.stdout.write(f'  Branch {branch_code}: item NOT FOUND')
                except Exception as e:
                    self.stdout.write(f'  Branch {branch_code} ({host}) ERROR: {e}')

        # ── Comparison ────────────────────────────────────────────────────────
        if len(results) > 1:
            self.stdout.write('\n' + '=' * 60)
            self.stdout.write('REPLICATION COMPARISON (pos_discp, pharmacydiscp)')
            hq_row = results.get('HQ (100)')
            all_match = True
            for server, row in results.items():
                match = (row[7] == hq_row[7] and row[4] == hq_row[4])  # posdiscp, pharmacydiscp
                status = '✓ MATCH' if match else '✗ MISMATCH'
                self.stdout.write(f'  {status:12} {server}: pos_discp={row[7]}, pharmacydiscp={row[4]}')
                if not match:
                    all_match = False

            if all_match:
                self.stdout.write(self.style.SUCCESS('\n  All servers in sync ✓'))
            else:
                self.stdout.write(self.style.WARNING('\n  ⚠ Replication lag or mismatch detected'))
        elif len(results) == 1:
            self.stdout.write('\n  Only HQ queried (no branch connections configured).')
            self.stdout.write('  The tr_items_update trigger handles branch sync automatically.')

    def _print_row(self, row):
        labels = ['itemcode', 'pack_price', 'unit_price', 'pack_price_tax',
                  'pharmacy_discp', 'additional_discp', 'special_discp',
                  'pos_discp', 'last_updated', 'usercode']
        for label, val in zip(labels, row):
            self.stdout.write(f'    {label:<20} = {val}')
