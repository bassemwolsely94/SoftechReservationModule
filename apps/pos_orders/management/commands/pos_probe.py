"""
python manage.py pos_probe --clone <docnumber> [--host 192.168.30.12] [--keep]
python manage.py pos_probe --order <pg_id>

ROLLBACK PROBE for the Indirect-POS writer against PRODUCTION — with ZERO
persistence. It executes the REAL serial-allocation + stktransm5/stktrans5/
branchesales5 INSERTs + a verify-readback inside a transaction, then ALWAYS
ROLLS BACK (no committed rows, no serial gap, can never be settled).

--clone <docnumber>: read an existing PENDING order from the branch, duplicate it
                     into a temporary PG order, probe-save it, then delete the temp
                     PG order. (Run OFF-PEAK: the probe briefly locks lastdocnumbers.)
--order <pg_id>:     probe an existing PG SoftechSalesOrder.

SAFETY: never commits; the dangerous step (settlement → stock/points/e-invoice) is
never reached. Reads + the throwaway transaction only.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError

from apps.pos_orders.models import (
    SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment,
    CHANNEL_TO_PTCLASSIF, DOCKIND_TO_DOCCODE, PAYTYPE_TO_SOFTECH,
)
from apps.pos_orders import writer

PTCLASSIF_TO_CHANNEL = {v: k for k, v in CHANNEL_TO_PTCLASSIF.items()}
DOCCODE_TO_DOCKIND   = {v: k for k, v in DOCKIND_TO_DOCCODE.items()}
SOFTECH_TO_PAYTYPE   = {v: k for k, v in PAYTYPE_TO_SOFTECH.items()}


class Command(BaseCommand):
    help = 'Rollback probe of the POS writer against production (zero persistence)'

    def add_arguments(self, parser):
        parser.add_argument('--host', default='192.168.30.12')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--clone', type=int, help='existing pending docnumber to duplicate (create probe)')
        parser.add_argument('--order', type=int, help='existing PG order id to probe (create)')
        parser.add_argument('--cancel-probe', type=int, dest='cancel_probe',
                            help='existing pending docnumber: DELETE-then-ROLLBACK (cancel probe)')
        parser.add_argument('--keep', action='store_true', help='keep the temp PG clone order')
        parser.add_argument('--commit', action='store_true',
                            help='with --clone: LIVE COMMIT the duplicate to SOFTECH (leaves it pending). '
                                 'Requires POS_WRITER_ENABLED=True.')

    def handle(self, *args, **o):
        if o.get('cancel_probe'):
            self._cancel_probe(o['host'], o['port'], o['cancel_probe'])
            return
        if o.get('order'):
            order = SoftechSalesOrder.objects.get(pk=o['order'])
            self._run(order)
            return
        if not o.get('clone'):
            raise CommandError('Provide --clone <docnumber>, --order <pg_id>, or --cancel-probe <docnumber>')
        order = self._clone(o['host'], o['port'], o['clone'])
        if o.get('commit'):
            self._commit(order)          # LIVE — keeps the PG order as the record
            return
        try:
            self._run(order)
        finally:
            if not o.get('keep'):
                order.delete()
                self.stdout.write('  (temp PG clone deleted)')

    # ── duplicate an existing pending order from the branch into a PG order ──────
    def _clone(self, host, port, docnumber):
        from apps.branches.models import Branch
        from config.sybase import get_branch_connection

        branch = Branch.objects.filter(db_host=host).first()
        if not branch:
            raise CommandError(f'No Branch with db_host={host}')

        conn = get_branch_connection(host, port, branch.db_name or 'SOFTECHDB9')
        cur = conn.cursor()
        cur.execute(
            "SELECT branchcode, doccode, ptclassifcode, phcode, storecode, cust_branch_code, "
            "usercode, cashiercode, refdoctorcode, docvalue, docvalue1, docvalue2, docvalue3, "
            "docvaluepay, patientpayment, cust_professional, origintaxp, cust_branch_store, custdiscp "
            "FROM stktransm5 WHERE docnumber=?", [docnumber])
        h = cur.fetchone()
        if not h:
            conn.close()
            raise CommandError(f'No pending stktransm5 row with docnumber={docnumber} on {host}')
        (branchcode, doccode, ptclassif, phcode, storecode, cust_branch_code, usercode,
         cashiercode, refdoctor, docvalue, dv1, dv2, dv3, docvaluepay, patientpayment,
         cust_professional, origintaxp, cust_branch_store, hdr_custdiscp) = [
            (str(x).strip() if isinstance(x, str) else x) for x in h]
        # native header fields we must reproduce (contract/patient sales need these)
        header_raw = {
            'cust_professional': (str(cust_professional).strip() if cust_professional is not None else None),
            'origintaxp': float(origintaxp) if origintaxp is not None else 0.0,
            'cust_branch_store': (str(cust_branch_store).strip() if cust_branch_store is not None else None),
            'custdiscp': float(hdr_custdiscp) if hdr_custdiscp is not None else 0.0,
        }

        order = SoftechSalesOrder.objects.create(
            branch=branch, softech_branchcode=str(branchcode).strip(), store_code=str(storecode).strip(),
            channel=PTCLASSIF_TO_CHANNEL.get(str(ptclassif).strip(), 'cash'),
            doc_kind=DOCCODE_TO_DOCKIND.get(str(doccode).strip(), 'sale'),
            softech_pic=str(phcode or '').strip(), cust_branch_code=str(cust_branch_code or '').strip(),
            seller_usercode=str(usercode or '').strip()[:5],
            cashier_usercode=str(cashiercode or '').strip()[:5],
            referral_doctor_code=str(refdoctor or '').strip(),
            doc_value=Decimal(str(docvalue or 0)), doc_value_gross=Decimal(str(dv1 or 0)),
            doc_value_cogs=Decimal(str(dv2 or 0)), doc_value_tax=Decimal(str(dv3 or 0)),
            doc_value_pay=Decimal(str(docvaluepay or 0)), patient_payment=Decimal(str(patientpayment or 0)),
            status=SoftechSalesOrder.STATUS_READY, notes=f'CLONE of pending {docnumber} (rollback probe)',
            source_header_raw=header_raw,
        )

        # SELECT * for a verbatim copy, plus the itemexpirydate components via datepart
        # (tz-safe: gives the DB's own naive value with no timezone shift; ASE 12.5 has
        # no convert style 121). r_docdate defaults to the native sentinel 1900-01-01.
        cur.execute(
            "SELECT *, datepart(yy,itemexpirydate) _ey, datepart(mm,itemexpirydate) _em, "
            "datepart(dd,itemexpirydate) _ed, datepart(hh,itemexpirydate) _eh, "
            "datepart(mi,itemexpirydate) _emi, datepart(ss,itemexpirydate) _es "
            "FROM stktrans5 WHERE docnumber=?", [docnumber])
        lcols = [d[0] for d in cur.description]
        # datetime columns we DON'T keep verbatim (writer overrides/nulls them)
        drop_dt = {'docdate', 'trans_time', 's_docdate', 'table_dumped', 'docnumber'}
        part_cols = {'_ey', '_em', '_ed', '_eh', '_emi', '_es'}
        for r in cur.fetchall():
            d = dict(zip(lcols, r))
            exp_str = None
            if d.get('_ey') is not None:
                exp_str = '%04d-%02d-%02d %02d:%02d:%02d' % (
                    int(d['_ey']), int(d['_em']), int(d['_ed']),
                    int(d['_eh'] or 0), int(d['_emi'] or 0), int(d['_es'] or 0))
            raw = {}
            for k, v in d.items():
                if k in part_cols or k in drop_dt:
                    continue
                if k == 'itemexpirydate':
                    raw[k] = {'__dt__': exp_str} if exp_str else None
                elif k == 'r_docdate':
                    raw[k] = {'__dt__': '1900-01-01 00:00:00'}
                elif isinstance(v, Decimal):
                    raw[k] = float(v)
                elif hasattr(v, 'isoformat'):     # any other stray datetime → skip
                    continue
                else:
                    raw[k] = v.strip() if isinstance(v, str) else v
            tpt = Decimal(str(d.get('transprice_total') or 0))
            tax = Decimal(str(d.get('itemsalestax') or 0))
            taxp = (tax / (tpt - tax) * Decimal('100')).quantize(Decimal('0.01')) if (tpt and tax and tpt != tax) else Decimal('0')
            SoftechSalesOrderLine.objects.create(
                order=order, item=None, softech_itemcode=str(d.get('itemcode') or '').strip(),
                qty=Decimal(str(d.get('transqty') or 0)), item_sale_price=Decimal(str(d.get('itemsaleprice') or 0)),
                item_sale_price_tax=Decimal(str(d.get('itemsaleprice_tax') or 0)), item_sale_tax=tax,
                trans_price=Decimal(str(d.get('transprice') or 0)), trans_price_total=tpt,
                cust_discp=Decimal(str(d.get('custdiscp') or 0)), new_cost_price=Decimal(str(d.get('newcostprice') or 0)),
                sale_tax_pct=taxp, source_raw=raw)

        cur.execute("SELECT paymenttype, paymentvalue FROM branchesales5 WHERE docnumber=?", [docnumber])
        for r in cur.fetchall():
            SoftechSalesOrderPayment.objects.create(
                order=order, pay_type=SOFTECH_TO_PAYTYPE.get(str(r[0]).strip(), 'cash'),
                amount=Decimal(str(r[1] or 0)))

        # ── contract/insurance companions (companiesitems5 + branchesalescc5) ──
        # Captured faithfully so the duplicate settles into a returnable contract sale.
        cur.execute(
            "SELECT patientname,patientno,financialno,fileno,roshettano,membershipno,deptname,"
            "patientnationality,relativedegree,comment,hi_typecode,vf1, "
            "datepart(yy,examdate),datepart(mm,examdate),datepart(dd,examdate), "
            "datepart(yy,cdate),datepart(mm,cdate),datepart(dd,cdate) "
            "FROM companiesitems5 WHERE branchcode=? AND docnumber=?", [branchcode, docnumber])
        cr = cur.fetchone()
        if cr:
            def _dts(y, m, d):
                return {'__dt__': '%04d-%02d-%02d 00:00:00' % (int(y), int(m), int(d))} if y is not None else None
            order.source_companies_raw = {
                'patientname': (str(cr[0]).strip() if cr[0] is not None else None),
                'patientno': (str(cr[1]).strip() if cr[1] is not None else None),
                'financialno': (str(cr[2]).strip() if cr[2] is not None else None),
                'fileno': (str(cr[3]).strip() if cr[3] is not None else None),
                'roshettano': (str(cr[4]).strip() if cr[4] is not None else None),
                'membershipno': (str(cr[5]).strip() if cr[5] is not None else None),
                'deptname': (str(cr[6]).strip() if cr[6] is not None else None),
                'patientnationality': (str(cr[7]).strip() if cr[7] is not None else None),
                'relativedegree': (str(cr[8]).strip() if cr[8] is not None else None),
                'comment': (str(cr[9]).strip() if cr[9] is not None else None),
                'hi_typecode': (str(cr[10]).strip() if cr[10] is not None else None),
                'vf1': (str(cr[11]).strip() if cr[11] is not None else None),
                'examdate': _dts(cr[12], cr[13], cr[14]),
                'cdate': _dts(cr[15], cr[16], cr[17]),
            }
        cur.execute(
            "SELECT costcentercode, moneyvalue FROM branchesalescc5 WHERE branchcode=? AND docnumber=?",
            [branchcode, docnumber])
        order.source_cc_raw = [
            {'costcentercode': (str(x[0]).strip() if x[0] is not None else '00/000'),
             'moneyvalue': float(x[1] or 0)} for x in cur.fetchall()]
        if order.source_companies_raw or order.source_cc_raw:
            order.save(update_fields=['source_companies_raw', 'source_cc_raw'])
            self.stdout.write(f'  captured contract claim data: companiesitems5={bool(order.source_companies_raw)} '
                              f'branchesalescc5={len(order.source_cc_raw)} rows')
        conn.close()
        self.stdout.write(self.style.SUCCESS(
            f'Cloned pending {docnumber} → temp PG order #{order.pk} '
            f'(channel={order.channel} doc_kind={order.doc_kind} pic={order.softech_pic} '
            f'lines={order.lines.count()} pay={order.payments.count()} value={order.doc_value})'))
        return order

    # ── run the rollback probe ──────────────────────────────────────────────────
    def _run(self, order):
        self.stdout.write(self.style.WARNING(
            f'\n⚠ ROLLBACK PROBE on branch {order.softech_branchcode} '
            f'(real INSERTs, then ROLLBACK — zero persistence)…'))
        res = writer.probe_order(order, confirm=True, live=False)
        self.stdout.write('\n--- probe result ---')
        for k, v in res.items():
            self.stdout.write(f'  {k}: {v}')
        if res.get('ok') and res.get('rolled_back'):
            self.stdout.write(self.style.SUCCESS(
                '\n✓ Write VALID and fully rolled back — nothing persisted to SOFTECH.'))
        else:
            self.stdout.write(self.style.ERROR(
                '\n✗ Probe did not complete cleanly — see error above (still rolled back).'))

    # ── LIVE COMMIT: persist the duplicate to SOFTECH and LEAVE it pending ───────
    def _commit(self, order):
        from apps.pos_orders import writer
        from config.sybase import get_branch_connection

        if not writer.writer_enabled():
            raise CommandError('POS_WRITER_ENABLED is False — refusing live commit. '
                               'Re-run with POS_WRITER_ENABLED=True.')
        self.stdout.write(self.style.WARNING(
            f'\n⚠ LIVE COMMIT to branch {order.softech_branchcode} — creates a REAL pending order '
            f'on the cashier (value {order.doc_value}, pic {order.softech_pic}). It will remain until '
            f'settled or cancelled.'))
        res = writer.push_order(order, dry_run=False)
        order.refresh_from_db()
        self.stdout.write('\n--- commit result ---')
        for k, v in res.items():
            self.stdout.write(f'  {k}: {v}')

        if order.status == order.STATUS_PUSHED and order.softech_docnumber:
            # confirm it persisted on a FRESH connection (not just within the txn)
            conn = get_branch_connection(order.branch.db_host, order.branch.db_port or 5000,
                                         order.branch.db_name or 'SOFTECHDB9')
            cur = conn.cursor()
            cur.execute('SELECT branchcode, doccode, docnumber, docvalue, docvaluepay, phcode '
                        'FROM stktransm5 WHERE docnumber=?', [int(order.softech_docnumber)])
            row = cur.fetchone()
            conn.close()
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ LIVE pending order committed: SOFTECH docnumber={order.softech_docnumber}, '
                f'PG order #{order.pk}. Persisted row: {row}'))
            self.stdout.write(self.style.WARNING(
                f'  It is now on the cashier. To remove it: '
                f'python manage.py shell -c "from apps.pos_orders.models import SoftechSalesOrder; '
                f'from apps.pos_orders import writer; '
                f'writer.cancel_order(SoftechSalesOrder.objects.get(pk={order.pk}))"  (POS_WRITER_ENABLED=True)'))
        else:
            self.stdout.write(self.style.ERROR(
                f'\n✗ Commit did not complete: status={order.status} error={order.erp_error}'))

    # ── cancel rollback probe: DELETE an existing pending order, then ROLLBACK ───
    def _cancel_probe(self, host, port, docnumber):
        from apps.branches.models import Branch
        from config.sybase import get_branch_connection
        from apps.pos_orders import writer

        branch = Branch.objects.filter(db_host=host).first()
        if not branch:
            raise CommandError(f'No Branch with db_host={host}')
        dbname = branch.db_name or 'SOFTECHDB9'

        # read the exact keys (branchcode, doccode) for this docnumber
        conn = get_branch_connection(host, port, dbname)
        cur = conn.cursor()
        cur.execute('SELECT branchcode, doccode FROM stktransm5 WHERE docnumber=?', [int(docnumber)])
        row = cur.fetchone()
        conn.close()
        if not row:
            raise CommandError(f'No pending stktransm5 row with docnumber={docnumber} on {host}')
        branchcode = str(row[0]).strip()
        doccode = str(row[1]).strip()

        self.stdout.write(self.style.WARNING(
            f'\n⚠ CANCEL ROLLBACK PROBE on branch {branchcode} doc {docnumber} '
            f'(real DELETE, then ROLLBACK — the row is NOT removed)…'))
        res = writer.probe_cancel(host, port, dbname, branchcode, doccode, docnumber, confirm=True)
        self.stdout.write('\n--- cancel-probe result ---')
        for k, v in res.items():
            self.stdout.write(f'  {k}: {v}')

        # confirm the row STILL exists after rollback (delete was undone)
        conn = get_branch_connection(host, port, dbname)
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM stktransm5 WHERE docnumber=?', [int(docnumber)])
        still = int(cur.fetchone()[0])
        conn.close()
        if res.get('ok') and res.get('rolled_back') and still >= 1:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Delete VALID and rolled back — row {docnumber} still present ({still}). Nothing removed.'))
        else:
            self.stdout.write(self.style.ERROR(
                f'\n✗ Cancel-probe not clean (ok={res.get("ok")}, still_present={still}).'))
