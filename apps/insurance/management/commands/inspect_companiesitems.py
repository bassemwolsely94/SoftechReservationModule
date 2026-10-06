"""Inspect companiesitems data for motalba 117 prescriptions."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Verify companiesitems patient names for motalba 117'

    def handle(self, *args, **opts):
        from config.sybase import get_sybase_connection
        conn = get_sybase_connection()
        cursor = conn.cursor()

        # Join motalba -> companiesitems via docnumber + branchcode + doccode
        cursor.execute("""
            SELECT
                m.motalba_docorder,
                m.docnumber,
                m.branchcode,
                ci.patientname,
                ci.patientno,
                ci.membershipno,
                ci.deptname,
                ci.roshettano,
                ci.relativedegree
            FROM SOFTECHDB9.dbo.motalba m
            LEFT JOIN SOFTECHDB9.dbo.companiesitems ci
                ON  ci.docnumber  = m.docnumber
                AND ci.branchcode = m.branchcode
                AND ci.doccode    = m.doccode
            WHERE m.personcode = '4227'
              AND m.motalbano  = 117
              AND m.invdel     = 1
            ORDER BY m.motalba_docorder
        """)
        rows = cursor.fetchall()
        self.stdout.write(f'Total rows: {len(rows)}')

        named = [r for r in rows if r[3]]
        unnamed = [r for r in rows if not r[3]]
        self.stdout.write(f'With patientname: {len(named)}  |  Without: {len(unnamed)}')

        self.stdout.write('\nFirst 8 WITH names:')
        for r in named[:8]:
            self.stdout.write(
                f'  seq={r[0]}  docno={str(r[1]).split(".")[0]}  '
                f'name={r[3]}  patno={r[4]}  '
                f'member={r[5]}  dept={r[6]}'
            )

        if unnamed:
            self.stdout.write(f'\nFirst 3 WITHOUT names:')
            for r in unnamed[:3]:
                self.stdout.write(f'  seq={r[0]}  docno={str(r[1]).split(".")[0]}')
