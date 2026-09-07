"""
python manage.py diag_purchase_insert --branch 100 --docnumber 63662 [--profile prod]

DIAGNOSTIC (rolls back): figure out why the stktransm (final purchase) header INSERT
does not land. Clones ONE header from a real source doc, inserts it inline inside a
transaction, then immediately reads @@error / @@rowcount / @@trancount and re-selects
the row — surfacing whatever the silent failure is — then ROLLS BACK.
"""
from types import SimpleNamespace
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Diagnose the stktransm final-insert silent no-op (rolls back).'

    def add_arguments(self, parser):
        parser.add_argument('--branch', required=True)
        parser.add_argument('--docnumber', required=True, type=int)
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **o):
        from django.conf import settings
        from config.sybase import SoftechConnector, get_branch_connection
        from apps.invoices import writer

        branchcode = str(o['branch']).strip()

        # read the source header for realistic values
        sc = SoftechConnector(profile=o['profile']).connect()
        try:
            cur = sc._cursor()
            cur.execute("SET ROWCOUNT 1")
            cur = sc._cursor()
            cur.execute("SELECT cust_branch_code, docnumber2, docvalue FROM stktransm "
                        "WHERE branchcode=? AND doccode='10' AND docnumber=?", [branchcode, o['docnumber']])
            r = cur.fetchone()
            sc._cursor().execute("SET ROWCOUNT 0")
            if not r:
                raise CommandError('source not found')
            personcode = str(r[0]).strip()
            docnumber2 = r[1]
            docvalue = float(r[2] or 0)
        finally:
            sc.close()
        self.stdout.write(f'source: supplier={personcode} docnumber2={docnumber2} docvalue={docvalue}')

        # fake invoice just for writer._header_row / _docnumber2 / softech_token
        inv = SimpleNamespace(
            pk=999999, softech_branchcode=branchcode, store_code=branchcode,
            softech_doccode='10', doc_kind='purchase', return_of_docnumber=None,
            invoice_number=str(docnumber2 or ''),
            vendor=SimpleNamespace(softech_personcode=personcode),
        )
        header = {'doc_value': docvalue}

        host = branchcode == '100' and settings.SYBASE_HOST or settings.SYBASE_HOST
        conn = get_branch_connection(host, 5000, 'SOFTECHDB9', charset='cp1256')
        try:
            conn.begin()
            row = _q1(conn, "SELECT lastdocnumberin_supp FROM lastdocnumbers HOLDLOCK WHERE branchcode=?",
                      [branchcode])
            docnumber = int(row[0]) + 1
            self.stdout.write(f'allocated docnumber={docnumber}')

            hrow = writer._header_row(inv, header, docnumber, ptclassifcode='10', usercode='1')
            cols = list(hrow.keys())
            vals = [writer._sql_literal(hrow[c]) for c in cols]
            sql = f"INSERT INTO stktransm ({', '.join(cols)}) VALUES ({', '.join(vals)})"
            self.stdout.write(f'\nINSERT SQL:\n{sql}\n')

            try:
                _exec(conn, sql)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'HEADER INSERT raised: {e}'))
            diag = _q1(conn, "SELECT @@error, @@rowcount, @@trancount")
            self.stdout.write(f'after HEADER: @@error={diag[0]} @@rowcount={diag[1]} @@trancount={diag[2]}')
            cnt = _q1(conn, "SELECT COUNT(*) FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
                      [branchcode, docnumber])
            self.stdout.write(f'  stktransm rows in-txn: {cnt[0]}')

            # ── now the FIRST real line (fires tr_stktrans stock/cost trigger) ──
            sc2 = SoftechConnector(profile=o['profile']).connect()
            try:
                c2 = sc2._cursor()
                c2.execute('SET ROWCOUNT 1')
                c2 = sc2._cursor()
                c2.execute("SELECT itemcode, transqty, itemsaleprice, transprice, pharmacydiscp, "
                           "additionaldiscp, origintaxp, itemexpirydate FROM stktrans "
                           "WHERE branchcode=? AND doccode='10' AND docnumber=?", [branchcode, o['docnumber']])
                sl = c2.fetchone()
                sc2._cursor().execute('SET ROWCOUNT 0')
            finally:
                sc2.close()
            from apps.invoices import pricing
            comp = pricing.compute_line(public_price=sl[2], unit_price=sl[3], qty=sl[1],
                                        discount_pct=sl[4], extra_discount_pct=sl[5], vat_pct=sl[6])
            exp = str(sl[7])[:10] if sl[7] else ''
            comp['_line'] = SimpleNamespace(item=SimpleNamespace(softech_id=str(sl[0]).strip()),
                                            quantity=sl[1], expiry_date=exp)
            lrow = writer._line_row(inv, comp, docnumber, '1')
            lcols = list(lrow.keys()); lvals = [writer._sql_literal(lrow[c]) for c in lcols]
            lsql = f"INSERT INTO stktrans ({', '.join(lcols)}) VALUES ({', '.join(lvals)})"
            self.stdout.write(f'\nLINE SQL:\n{lsql}\n')
            try:
                _exec(conn, lsql)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'LINE INSERT raised: {e}'))
            diag = _q1(conn, "SELECT @@error, @@rowcount, @@trancount")
            self.stdout.write(f'after LINE: @@error={diag[0]} @@rowcount={diag[1]} @@trancount={diag[2]}')
            h2 = _q1(conn, "SELECT COUNT(*) FROM stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?",
                     [branchcode, docnumber])
            l2 = _q1(conn, "SELECT COUNT(*) FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?",
                     [branchcode, docnumber])
            self.stdout.write(f'  after line → stktransm rows: {h2[0]} | stktrans rows: {l2[0]}')
        finally:
            try:
                conn.rollback()
                self.stdout.write('rolled back.')
            except Exception as e:
                self.stdout.write(f'rollback error: {e}')
            conn.close()


def _q1(conn, sql, params=None):
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
        return cur.fetchone()
    finally:
        cur.close()


def _exec(conn, sql):
    cur = conn.cursor()
    try:
        cur.execute(sql)
    finally:
        cur.close()
