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

            # ptclassifcode → OUR channel key (cash / delivery); anything else earns no points
            channel = {'91': 'cash', '90': 'delivery'}.get(ptclassif)
            if not channel:
                self.stdout.write(f"  ptclassif={ptclassif} is not cash/delivery — expected 0 points."); continue

            # 3. the FINAL sale lines — WITH custdiscp so we apply the discount⊻points exclusion, and
            #    feed them THROUGH the real points.py (item_alt3 rate + per-line floor + rep resolve),
            #    so this command verifies the ACTUAL shipping formula, not a divergent copy.
            lines = q("SELECT s.itemcode, s.transprice_total, s.custdiscp "
                      "FROM stktrans s WHERE s.branchcode=? AND s.doccode=? AND s.docnumber=?",
                      [br.softech_branch_id, doccode, docnumber])
            line_values = [(str(l[0]).strip(),
                            (Decimal('0') if float(l[2] or 0) > 0 else Decimal(str(l[1] or 0))))
                           for l in lines]

            from apps.pos_orders.points import compute_points
            total, bd = compute_points(reader, channel, line_values)
            self.stdout.write(f"  channel={channel}  rep→{reader.customer_personcode(channel)}  "
                              f"lines={len(line_values)} (discounted lines earn 0)")
            for b in bd:
                self.stdout.write(f"    {b['itemcode']:>8}  alt3={b['alt3'] or '—':>4}  "
                                  f"rate={b['rate']:>5}%  pts={b['points']}")
            ok = (total == actual)
            self.stdout.write(f"  → actual={actual}  points.py={total}  "
                              + ("✅ MATCH" if ok else "❌ DRIFT"))

        reader.close()
        try: conn.close()
        except Exception: pass
