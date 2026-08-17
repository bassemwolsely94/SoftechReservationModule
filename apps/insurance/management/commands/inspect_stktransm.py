"""Inspect stktransm fields for motalba 117 prescriptions to find patient name source."""
from django.core.management.base import BaseCommand

SQL = """
    SELECT sm.docnumber, sm.comments, sm.supp_main_code,
           sm.cust_branch_code, sm.phcode, sm.vf1, sm.vf2
    FROM SOFTECHDB9.dbo.motalba m
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON sm.docnumber=m.docnumber AND sm.branchcode=m.branchcode AND sm.doccode=m.doccode
    WHERE m.personcode='4227' AND m.motalbano=117 AND m.invdel=1
    ORDER BY m.motalba_docorder
"""

SQL_LC = """
    SELECT sm.docnumber, sm.phcode, lc.branchcustname
    FROM SOFTECHDB9.dbo.motalba m
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON sm.docnumber=m.docnumber AND sm.branchcode=m.branchcode AND sm.doccode=m.doccode
    LEFT JOIN SOFTECHDB9.dbo.localcustomers lc ON lc.phcode=sm.phcode
    WHERE m.personcode='4227' AND m.motalbano=117 AND m.invdel=1
    ORDER BY m.motalba_docorder
"""


class Command(BaseCommand):
    help = 'Find patient name source in stktransm for motalba 117'

    def handle(self, *args, **opts):
        from config.sybase import get_sybase_connection
        conn = get_sybase_connection()
        cursor = conn.cursor()

        cursor.execute(SQL)
        rows = cursor.fetchall()
        self.stdout.write(f'Total prescriptions: {len(rows)}')

        non_null = {f: 0 for f in ['comments','supp_main_code','cust_branch_code','phcode','vf1','vf2']}
        for r in rows:
            for i, f in enumerate(non_null):
                if r[i+1]:
                    non_null[f] += 1

        self.stdout.write('Non-null counts:')
        for f, cnt in non_null.items():
            self.stdout.write(f'  {f}: {cnt}/{len(rows)}')

        self.stdout.write('\nFirst 5 rows (full):')
        for r in rows[:5]:
            self.stdout.write(
                f'  docno={r[0]}  comments={repr(r[1])}  supp={r[2]}'
                f'  cust_branch={r[3]}  phcode={r[4]}  vf1={r[5]}  vf2={r[6]}'
            )

        # Also check localcustomers via phcode (even if user says to avoid it,
        # useful to understand the data model)
        self.stdout.write('\n--- localcustomers via phcode (for reference) ---')
        cursor2 = conn.cursor()
        cursor2.execute(SQL_LC)
        rows2 = cursor2.fetchall()
        named_lc = [(r[0], r[1], r[2]) for r in rows2 if r[2]]
        self.stdout.write(f'With name via localcustomers: {len(named_lc)}')
        for r in named_lc[:5]:
            self.stdout.write(f'  docno={r[0]}  phcode={r[1]}  name={r[2]}')
