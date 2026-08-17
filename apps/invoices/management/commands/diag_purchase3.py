"""
python manage.py diag_purchase3 --branch 100 --docnumber 63662 [--profile prod]

DIAGNOSTIC (rolls back): reproduce the writer's NEW (captured-DML) insert path for a
cloned purchase, printing @@error / @@rowcount / @@trancount after the header insert
and after EACH line insert, so we see exactly which statement the trigger rejects and
why (now that newqty is the live running balance and newcostprice is omitted).
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Diagnose the new writer insert path with per-statement @@error (rolls back).'

    def add_arguments(self, parser):
        parser.add_argument('--branch', required=True)
        parser.add_argument('--docnumber', required=True, type=int)
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **o):
        from django.db import transaction
        from config.sybase import SoftechConnector, get_branch_connection
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.invoices.models import SupplierInvoice, InvoiceLine, VendorProfile
        from apps.invoices import writer

        bc = str(o['branch']).strip()
        sc = SoftechConnector(profile=o['profile']).connect()
        try:
            sc._cursor().execute('SET ROWCOUNT 1')
            cur = sc._cursor()
            cur.execute("SELECT cust_branch_code FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
                        [bc, o['docnumber']])
            r = cur.fetchone()
            sc._cursor().execute('SET ROWCOUNT 0')
            if not r:
                raise CommandError('source not found')
            personcode = str(r[0]).strip()
            cur = sc._cursor()
            cur.execute("SELECT itemcode, transqty, itemsaleprice, transprice, pharmacydiscp, additionaldiscp, "
                        "origintaxp, itemexpirydate FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?",
                        [bc, o['docnumber']])
            src_lines = cur.fetchall()
        finally:
            sc.close()

        branch = Branch.objects.filter(softech_branch_id=bc).first()
        vendor, _ = VendorProfile.objects.get_or_create(softech_personcode=personcode,
                                                        defaults={'name': f'SUP{personcode}'})

        try:
            with transaction.atomic():
                inv = SupplierInvoice.objects.create(branch=branch, vendor=vendor, doc_kind='purchase',
                                                     invoice_number='9999999', status='confirmed')
                for sl in src_lines:
                    item = Item.objects.filter(softech_id=str(sl[0]).strip()).first()
                    if not item:
                        continue
                    InvoiceLine.objects.create(invoice=inv, item=item, quantity=sl[1],
                                               public_price=sl[2], unit_price=sl[3],
                                               discount_pct=sl[4], extra_discount_pct=sl[5],
                                               vat_pct=sl[6], expiry_date=str(sl[7] or '')[:10])
                computed, header = writer.compute(inv)
                self.stdout.write(f'lines matched: {len(computed)}')

                conn = get_branch_connection(writer.branch_host(inv), 5000, 'SOFTECHDB9', charset='cp1256')
                try:
                    # session options the native PB client uses (trigger may require them)
                    for so in ('set quoted_identifier on', 'set arithabort off',
                               'set arithignore off', 'set ansinull off', 'set chained off'):
                        try:
                            writer._exec(conn, so)
                        except Exception as e:
                            self.stdout.write(f'  [set fail] {so}: {e}')
                    conn.begin()
                    counter = inv.softech_counter_column
                    docnumber = int(writer._q1(conn, f"SELECT {counter} FROM lastdocnumbers HOLDLOCK WHERE branchcode=?", [bc])[0]) + 1
                    store = inv.store_code or bc
                    nowq = writer.read_stkbal(conn, bc, store, [c['_line'].item.softech_id for c in computed])
                    self.stdout.write(f'docnumber={docnumber} stkbal={nowq}')

                    writer._exec_insert(conn, 'stktransm', writer._header_row(inv, header, docnumber, '60', '1509'))
                    d = writer._q1(conn, "SELECT @@error, @@rowcount, @@trancount")
                    hc = writer._q1(conn, "SELECT COUNT(*) FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?", [bc, docnumber])
                    self.stdout.write(f'HEADER: @@error={d[0]} rowcount={d[1]} trancount={d[2]} present={hc[0]}')

                    jconn = conn._conn   # java connection for raw warning capture
                    jst = jconn.createStatement()
                    for i, c in enumerate(computed, 1):
                        code = str(c['_line'].item.softech_id).strip()
                        qv = float(c['_line'].quantity or 0)
                        nq = nowq.get(code, 0.0) + qv
                        row = writer._line_row(inv, c, docnumber, '1509', nq)
                        cols = list(row.keys())
                        vals = [writer._sql_literal(row[k]) for k in cols]
                        sql = f"INSERT INTO stktrans ({', '.join(cols)}) VALUES ({', '.join(vals)})"
                        jst.clearWarnings()
                        try:
                            jst.execute(sql)
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f'LINE {i} raised: {str(e)[:400]}'))
                        msgs = []
                        w = jst.getWarnings()
                        while w is not None:
                            try:
                                msgs.append(str(w.getMessage()))
                            except Exception:
                                pass
                            w = w.getNextWarning()
                        d = writer._q1(conn, "SELECT @@error, @@rowcount, @@trancount")
                        self.stdout.write(f'LINE {i} item {code} qty {qv} newqty {nq}: '
                                          f'@@error={d[0]} rowcount={d[1]} trancount={d[2]}')
                        if msgs:
                            self.stdout.write('  MESSAGES: ' + ' || '.join(m[:200] for m in msgs))
                        if int(d[2]) == 0:
                            self.stdout.write(self.style.ERROR('  → transaction rolled back; stopping.'))
                            break
                    lc = writer._q1(conn, "SELECT COUNT(*) FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?", [bc, docnumber])
                    hc = writer._q1(conn, "SELECT COUNT(*) FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?", [bc, docnumber])
                    self.stdout.write(self.style.SUCCESS(f'FINAL in-txn: stktransm={hc[0]} stktrans={lc[0]} / {len(computed)}'))
                finally:
                    try:
                        conn.rollback(); self.stdout.write('sybase rolled back.')
                    except Exception as e:
                        self.stdout.write(f'rollback err: {e}')
                    conn.close()
                raise _Rollback()
        except _Rollback:
            self.stdout.write('PG rolled back.')


class _Rollback(Exception):
    pass
