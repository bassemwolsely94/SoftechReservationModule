"""
verify_pos_points — compare a REAL finalized sale's actual SOFTECH picpoints award to the points
our formula computes (Σ line_net × classification% / 100, from the channel-rep custdiscounts).

Read-only. Confirms (or refutes) the points model against live data.

Usage:
  python manage.py verify_pos_points --branch 130 --limit 5
  python manage.py verify_pos_points --branch 130 --docnumber 452724
"""
from decimal import Decimal

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Verify PIC points: actual picpoints award vs our per-classification formula."

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='130', help='softech_branch_id')
        parser.add_argument('--docnumber', type=int, default=None, help='a specific final sale docnumber')
        parser.add_argument('--limit', type=int, default=5, help='how many recent point-earning sales to check')

    def handle(self, *args, **o):
        from apps.branches.models import Branch
        from apps.pos_orders.discount_authority import DiscountAuthorityReader
        from config.sybase import get_branch_connection

        try:
            br = Branch.objects.get(softech_branch_id=o['branch'])
        except Branch.DoesNotExist:
            self.stderr.write(f"branch {o['branch']} not found"); return
        host, port, db = br.effective_db_host, br.effective_db_port, br.db_name or 'SOFTECHDB9'
        self.stdout.write(f"Branch {br.softech_branch_id} @ {host}:{port}/{db}")

        try:
            conn = get_branch_connection(host, port, db)
        except Exception as e:
            self.stderr.write(f"CONNECT FAILED: {e}"); return
        cur = conn.cursor()

        def q(sql, params=None):
            c = conn.cursor(); c.execute(sql, params or []); return c.fetchall()

        # 1. pick point-earning sales: recent picpoints rows with points>0 at this branch
        try:
            conn.cursor().execute(f"SET ROWCOUNT {int(o['limit'])}")
            if o['docnumber']:
                pts_rows = q("SELECT phcode, points, doccode, docnumber, branchcode, transdate "
                             "FROM picpoints WHERE branchcode=? AND docnumber=? ORDER BY transdate DESC",
                             [br.softech_branch_id, o['docnumber']])
            else:
                pts_rows = q("SELECT phcode, points, doccode, docnumber, branchcode, transdate "
                             "FROM picpoints WHERE branchcode=? AND points>0 ORDER BY transdate DESC",
                             [br.softech_branch_id])
            conn.cursor().execute("SET ROWCOUNT 0")
        except Exception as e:
            self.stderr.write(f"picpoints read failed: {e}"); return

        if not pts_rows:
            self.stdout.write("No positive picpoints rows found for this branch."); return

        reader = DiscountAuthorityReader(host, port, db)
        # channel ptclassifcode → representative personglobalcode
        REP_GC = {'91': 'CashCust', '90': 'HomeDlvry'}

        for pr in pts_rows:
            phcode = str(pr[0]).strip() if pr[0] else ''
            actual = int(pr[1]) if pr[1] is not None else 0
            doccode = str(pr[2]).strip() if pr[2] else ''
            docnumber = int(pr[3]) if pr[3] is not None else 0
            self.stdout.write("\n" + "=" * 70)
            self.stdout.write(f"picpoints: PIC={phcode} points={actual} doccode={doccode} docnumber={docnumber}")

            # 2. the FINAL sale header → channel (ptclassifcode)
            hdr = q("SELECT ptclassifcode, docvalue, phcode FROM stktransm "
                    "WHERE branchcode=? AND doccode=? AND docnumber=?",
                    [br.softech_branch_id, doccode, docnumber])
            if not hdr:
                self.stdout.write("  (no stktransm header found — skipping)"); continue
            ptclassif = str(hdr[0][0]).strip() if hdr[0][0] is not None else ''
            docvalue = Decimal(str(hdr[0][1] or 0))
            self.stdout.write(f"  sale: ptclassifcode={ptclassif} docvalue={docvalue}")

            rep_gc = REP_GC.get(ptclassif)
            if not rep_gc:
                self.stdout.write(f"  channel ptclassif={ptclassif} is not cash/delivery — expected 0 points."); continue
            rep_pc = None
            row = q("SELECT personcode FROM personsdata WHERE personglobalcode=?", [rep_gc])
            if row:
                rep_pc = str(row[0][0]).strip()
            self.stdout.write(f"  channel rep: {rep_gc} → personcode {rep_pc}")

            # the PIC's OWN personcode (individuals may have their own schedule)
            pic_pc = None
            prow = q("SELECT personcode FROM personsdata WHERE personglobalcode=?", [phcode])
            if prow:
                pic_pc = str(prow[0][0]).strip()

            # 3. the FINAL sale lines — dump everything + test both schedules
            lines = q("SELECT s.itemcode, s.transqty, s.transprice, s.transprice_total, "
                      "       i.itemstoreclassif, i.itempointsys "
                      "FROM stktrans s LEFT JOIN items i ON i.itemcode = s.itemcode "
                      "WHERE s.branchcode=? AND s.doccode=? AND s.docnumber=?",
                      [br.softech_branch_id, doccode, docnumber])
            comp_rep = Decimal('0'); comp_pic = Decimal('0')
            self.stdout.write(f"  PIC own personcode={pic_pc}")
            self.stdout.write(f"  {'item':>8} {'qty':>6} {'net':>9} {'classif':>8} {'ipsys':>5} "
                              f"{'rep%':>5} {'pic%':>5}  {'rep_pts':>8} {'pic_pts':>8}")
            for ln in lines:
                itemcode = str(ln[0]).strip() if ln[0] else ''
                qty = Decimal(str(ln[1] or 0))
                net = Decimal(str(ln[3] or 0))
                classif = str(ln[4]).strip() if ln[4] is not None else ''
                ipsys = str(ln[5]).strip() if ln[5] is not None else ''

                def rate(pc):
                    if not (pc and classif):
                        c0 = reader.contracted(pc, '0') if pc else None
                        return c0[0] if c0 else Decimal('0')
                    c = reader.contracted(pc, classif)
                    if c is not None:
                        return c[0]
                    c0 = reader.contracted(pc, '0')
                    return c0[0] if c0 else Decimal('0')

                rrep = rate(rep_pc); rpic = rate(pic_pc)
                prep = net * rrep / Decimal('100'); ppic = net * rpic / Decimal('100')
                comp_rep += prep; comp_pic += ppic
                self.stdout.write(f"  {itemcode:>8} {qty:>6} {net:>9} {classif:>8} {ipsys:>5} "
                                  f"{rrep:>5} {rpic:>5}  {prep:>8.2f} {ppic:>8.2f}")

            self.stdout.write(f"  → actual={actual}  rep_formula={int(comp_rep)}  "
                              f"pic_formula={int(comp_pic)}"
                              + ("  ✅rep" if int(comp_rep) == actual else "")
                              + ("  ✅pic" if int(comp_pic) == actual else ""))

        reader.close()
        try: conn.close()
        except Exception: pass
