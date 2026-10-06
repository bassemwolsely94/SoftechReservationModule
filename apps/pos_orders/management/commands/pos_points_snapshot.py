"""
pos_points_snapshot — READ-ONLY. Snapshot a PIC's SOFTECH points state before/after a test
finalization, to answer: does the cashier's finalization RECOMPUTE personnewbal (→ our pending 0
is safe) or COPY it (→ 0 would award 0 points)?

Run it BEFORE the test (baseline) and AFTER the cashier finalizes the test order; compare the
balance delta to the expected award. Nothing is written.

  python manage.py pos_points_snapshot --branch 130 --pic 130HD16941
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "READ-ONLY snapshot of a PIC's SOFTECH points (balance, enrollment, recent log, pending orders)."

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='130', help='softech_branch_id')
        parser.add_argument('--pic', required=True, help='the PIC (phcode)')

    def handle(self, *args, **o):
        from apps.branches.models import Branch
        from apps.loyalty import pic_bridge
        from config.sybase import get_branch_connection

        pic = o['pic'].strip()
        try:
            br = Branch.objects.get(softech_branch_id=o['branch'])
        except Branch.DoesNotExist:
            self.stderr.write(f"branch {o['branch']} not found"); return

        # enrollment + balance (central reads via pic_bridge)
        enrolled = pic_bridge.is_softech_points_enrolled(pic)
        balance = pic_bridge.read_softech_points(pic)
        self.stdout.write(f"PIC {pic}")
        self.stdout.write(f"  enrolled (localcustomers.picpoints=1): {enrolled}")
        self.stdout.write(f"  points balance (Σtotpoints−Σconpoints): {balance}")

        self.stdout.write("  recent picpoints log:")
        for r in pic_bridge.read_softech_points_log(pic, limit=8):
            self.stdout.write(f"    {r['transdate']}  {r['points']:+}  doccode={r['doccode']} "
                              f"docnumber={r['docnumber']} branch={r['branchcode']}  {r['vf1']}")

        # any PENDING (stktransm5) orders for this PIC at the branch + their personnewbal
        try:
            conn = get_branch_connection(br.effective_db_host, br.effective_db_port,
                                         br.db_name or 'SOFTECHDB9')
            cur = conn.cursor()
            cur.execute("SELECT doccode, docnumber, docvalue, personnewbal, ptclassifcode, trans_time "
                        "FROM stktransm5 WHERE phcode=? ORDER BY trans_time DESC", [pic])
            rows = cur.fetchall()
            conn.close()
            self.stdout.write(f"  PENDING stktransm5 orders for this PIC: {len(rows)}")
            for r in rows[:8]:
                self.stdout.write(f"    doccode={str(r[0]).strip()} docnumber={r[1]} docvalue={r[2]} "
                                  f"personnewbal={r[3]} ptclassif={str(r[4]).strip()} at {r[5]}")
        except Exception as e:
            self.stdout.write(f"  (pending read failed: {e})")
