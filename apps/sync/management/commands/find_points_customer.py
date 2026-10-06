"""
python manage.py find_points_customer

Finds PICs that have actual points balances in localcustomerspoints
so you can use one for testing.
"""
from django.core.management.base import BaseCommand
from config.sybase import get_sybase_connection, _safe_str


class Command(BaseCommand):
    help = 'Find PICs with non-zero points balances for testing'

    def handle(self, *args, **options):
        conn = get_sybase_connection()

        # SET ROWCOUNT 20 — get first 20 PICs with a positive net balance
        conn.cursor().execute('SET ROWCOUNT 20')
        cur = conn.cursor()
        cur.execute("""
            SELECT lcp.phcode,
                   SUM(lcp.totpoints) AS tot,
                   SUM(lcp.conpoints) AS con,
                   SUM(lcp.totpoints) - SUM(lcp.conpoints) AS net
            FROM   SOFTECHDB9.dbo.localcustomerspoints lcp
            GROUP  BY lcp.phcode
            HAVING SUM(lcp.totpoints) - SUM(lcp.conpoints) > 0
            ORDER  BY net DESC
        """)
        rows = cur.fetchall()
        conn.cursor().execute('SET ROWCOUNT 0')
        conn.close()

        if not rows:
            self.stdout.write(self.style.WARNING('No PICs found with a positive balance.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\n{"PIC":<15} {"TotEarned":>10} {"Consumed":>10} {"NetBalance":>10}'))
        self.stdout.write('-' * 50)
        for row in rows:
            pic = _safe_str(row[0]) or str(row[0])
            self.stdout.write(f'{pic:<15} {int(row[1] or 0):>10,} {int(row[2] or 0):>10,} {int(row[3] or 0):>10,}')

        self.stdout.write(self.style.WARNING(
            '\nPick any PIC above and run:\n'
            '  python manage.py check_pic_balance --pic <PIC>\n'
            '  python manage.py test_pic_points --pic <PIC> --dry-run'
        ))
