"""
python manage.py check_pic_balance --pic 01HD14

Checks all three points-related locations for a PIC so we can
confirm where the trigger actually writes the balance after an INSERT
into the picpoints log table.
"""
from django.core.management.base import BaseCommand
from config.sybase import get_sybase_connection, _safe_str


class Command(BaseCommand):
    help = 'Show all points-related values for a given PIC across all SOFTECH tables'

    def add_arguments(self, parser):
        parser.add_argument('--pic', required=True)

    def handle(self, *args, **options):
        pic  = options['pic'].strip()
        conn = get_sybase_connection()

        def q(sql, params=None, rowcount=None):
            if rowcount:
                conn.cursor().execute(f'SET ROWCOUNT {rowcount}')
            cur = conn.cursor()
            cur.execute(sql, params or [])
            rows = cur.fetchall()
            if rowcount:
                conn.cursor().execute('SET ROWCOUNT 0')
            return rows

        self.stdout.write(f'\nPIC: {pic}')
        self.stdout.write('-' * 60)

        # 1. localcustomers.picpoints (flag or balance?)
        rows = q('SELECT picpoints FROM SOFTECHDB9.dbo.localcustomers WHERE phcode = ?', [pic])
        val = rows[0][0] if rows else 'NOT FOUND'
        self.stdout.write(f'\nlocalcustomers.picpoints        = {val}')

        # 2. localcustomerspoints (branch-level aggregated)
        rows = q(
            'SELECT branchcode, totpoints, conpoints '
            'FROM SOFTECHDB9.dbo.localcustomerspoints '
            'WHERE phcode = ? ORDER BY branchcode', [pic]
        )
        if rows:
            self.stdout.write('\nlocalcustomerspoints:')
            total_tot = 0
            total_con = 0
            for r in rows:
                br   = _safe_str(r[0]) or str(r[0])
                tot  = int(r[1]) if r[1] is not None else 0
                con  = int(r[2]) if r[2] is not None else 0
                net  = tot - con
                total_tot += tot
                total_con += con
                self.stdout.write(f'  branch={br}  totpoints={tot}  conpoints={con}  net={net}')
            self.stdout.write(f'  TOTAL net balance = {total_tot - total_con}')
        else:
            self.stdout.write('\nlocalcustomerspoints:  (no rows for this PIC)')

        # 3. lcpointstrans — last 5 rows
        rows = q(
            'SELECT branchcode, transsno, totpoints, conpoints, '
            '       totpointsold, conpointsold, usercode, trans_time '
            'FROM SOFTECHDB9.dbo.lcpointstrans '
            'WHERE phcode = ? ORDER BY trans_time DESC', [pic], rowcount=5
        )
        if rows:
            self.stdout.write('\nlcpointstrans (last 5):')
            for r in rows:
                br  = _safe_str(r[0]) or ''
                sno = r[1]
                tot = r[2]
                con = r[3]
                old_tot = r[4]
                old_con = r[5]
                uc  = _safe_str(r[6]) or ''
                ts  = str(r[7])
                self.stdout.write(
                    f'  {ts}  branch={br}  sno={sno}  '
                    f'tot: {old_tot}->{tot}  con: {old_con}->{con}  user={uc}'
                )
        else:
            self.stdout.write('\nlcpointstrans:  (no rows for this PIC)')

        # 4. picpoints log — last 5 rows
        rows = q(
            'SELECT transdate, points, branchcode, doccode, vf1, vf2 '
            'FROM SOFTECHDB9.dbo.picpoints '
            'WHERE phcode = ? ORDER BY transdate DESC', [pic], rowcount=5
        )
        if rows:
            self.stdout.write('\npicpoints log (last 5):')
            for r in rows:
                sign = '+' if (r[1] or 0) >= 0 else ''
                self.stdout.write(
                    f'  {r[0]}  {sign}{r[1]}  '
                    f'branch={_safe_str(r[2]) or ""}  doc={_safe_str(r[3]) or ""}  '
                    f'vf1={_safe_str(r[4]) or ""}  vf2={_safe_str(r[5]) or ""}'
                )
        else:
            self.stdout.write('\npicpoints log:  (no rows)')

        conn.close()
        self.stdout.write('')
