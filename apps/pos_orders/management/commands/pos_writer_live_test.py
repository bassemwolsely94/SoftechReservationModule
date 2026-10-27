"""
pos_writer_live_test — replicate the 01HD10 cash sale (branch 100, items 404/101852/122668/4179)
through OUR writer, to test whether SOFTECH's finalization RECOMPUTES our personnewbal=0 (→ safe)
or COPIES it (→ points lost).

  --mode probe   : run the REAL serial-allocation + INSERTs + verify-readback, then ROLL BACK
                   (zero residue; writer gate not required). The true rehearsal of the commit.
  --mode commit  : LIVE — actually creates the pending order in SOFTECH. Requires --confirm AND
                   POS_WRITER_ENABLED=True. Prints the allocated docnumber to finalize on the cashier.

The PG test order is deleted after a probe (unless --keep) and kept after a commit (it holds the
SOFTECH docnumber). FEFO-picks one batch per item at store 100 for a faithful, returnable write.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand


BRANCH = '100'
STORE = '100'
PIC = '01HD10'
SELLER = '1509'
# (itemcode, unit sale price, tax %) — matches the native sale nets (853 total)
ITEMS = [('404', '38', '0'), ('101852', '70', '0'), ('122668', '295', '14'), ('4179', '450', '0')]


class Command(BaseCommand):
    help = "Replicate the 01HD10 cash sale via our writer (probe=rollback rehearsal / commit=LIVE)."

    def add_arguments(self, parser):
        parser.add_argument('--mode', choices=['probe', 'commit'], default='probe')
        parser.add_argument('--confirm', action='store_true', help='required for commit')
        parser.add_argument('--keep', action='store_true', help='keep the PG order after a probe')

    def handle(self, *args, **o):
        from apps.branches.models import Branch
        from apps.pos_orders.models import (SoftechSalesOrder, SoftechSalesOrderLine,
                                            SoftechSalesOrderPayment)
        from apps.pos_orders import writer
        from apps.pos_orders.validators import validate_order
        from config.sybase import get_branch_connection

        br = Branch.objects.get(softech_branch_id=BRANCH)

        # FEFO: earliest-expiry batch per item at the store (for a faithful, returnable pending)
        conn = get_branch_connection(br.effective_db_host, br.effective_db_port, br.db_name or 'SOFTECHDB9')
        expiries = {}
        for code, _, _ in ITEMS:
            c = conn.cursor()
            c.execute("SET ROWCOUNT 1")
            c.execute("SELECT itemexpirydate FROM stkbalexpiry WHERE storecode=? AND itemcode=? "
                      "AND itemqty>0 ORDER BY itemexpirydate", [STORE, code])
            r = c.fetchone()
            c2 = conn.cursor(); c2.execute("SET ROWCOUNT 0")
            expiries[code] = (str(r[0])[:10] if r and r[0] else None)
        conn.close()
        self.stdout.write(f"FEFO expiries: {expiries}")

        order = SoftechSalesOrder.objects.create(
            branch=br, softech_branchcode=BRANCH, store_code=STORE,
            channel='cash', doc_kind='sale',
            softech_pic=PIC, customer_name=f'WRITER-TEST {PIC}', cust_branch_code='1510',
            seller_usercode=SELLER, cashier_usercode=SELLER, payment_method='cash',
        )
        total = Decimal('0')
        for code, price, tax in ITEMS:
            SoftechSalesOrderLine.objects.create(
                order=order, softech_itemcode=code, item_name=code, qty=Decimal('1'),
                item_sale_price=Decimal(price), sale_tax_pct=Decimal(tax), cust_discp=Decimal('0'),
                item_expiry=expiries.get(code))
            total += Decimal(price)
        SoftechSalesOrderPayment.objects.create(order=order, pay_type='cash', amount=total)

        writer.prepare_order(order, live=True)
        try:
            validate_order(order, for_push=False)   # basic only: an OOS item shouldn't block the points test
        except Exception as e:
            self.stderr.write(f"VALIDATION FAILED: {e}"); order.delete(); return
        from apps.pos_orders import points as _points
        pts, bd = _points.order_points(order)
        self.stdout.write(f"order#{order.pk} prepared: doc_value={order.doc_value} "
                          f"pic={order.softech_pic} channel={order.channel} → personnewbal={pts}")
        for b in bd:
            self.stdout.write(f"    {b['itemcode']}: alt3={b['alt3']} rate={b['rate']}% → {b['points']}")

        if o['mode'] == 'probe':
            res = writer.probe_order(order, confirm=True, live=False)
            self.stdout.write("── PROBE (real DML, ROLLED BACK, zero residue) ──")
            self.stdout.write(str(res))
            if not o['keep']:
                order.delete()
                self.stdout.write("(PG test order deleted)")
        else:  # commit
            if not o['confirm']:
                self.stderr.write("commit requires --confirm"); order.delete(); return
            if not writer.writer_enabled():
                self.stderr.write("POS_WRITER_ENABLED is OFF — enable it, then re-run"); order.delete(); return
            res = writer.push_order(order, dry_run=False, live=True)
            self.stdout.write("── LIVE COMMIT ──")
            self.stdout.write(str(res))
            self.stdout.write(f"PG order#{order.pk} status={order.status} "
                              f"softech_docnumber={order.softech_docnumber}")
