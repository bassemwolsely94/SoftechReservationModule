"""
python manage.py diag_chained [--item 404] [--qty 10]

Test whether the stktrans purchase-line insert succeeds in UNCHAINED transaction
mode (explicit begin tran/rollback tran, autocommit left ON) vs the CHAINED mode
jConnect uses when we setAutoCommit(false). Runs the whole thing as ONE batch and
rolls back. Also prints sp_expirytrans / tr_stktrans required transaction mode.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Test chained vs unchained transaction mode for the stktrans insert (rolls back).'

    def add_arguments(self, parser):
        parser.add_argument('--item', default='404')
        parser.add_argument('--qty', type=float, default=10.0)
        parser.add_argument('--branch', default='100')
        parser.add_argument('--supplier', default='30')

    def handle(self, *args, **o):
        from django.conf import settings
        from config.sybase import get_branch_connection
        from apps.invoices import writer as W

        bc, ic, qty, sup = o['branch'], str(o['item']), float(o['qty']), str(o['supplier'])
        conn = get_branch_connection(settings.SYBASE_HOST, 5000, 'SOFTECHDB9', charset='cp1256')
        jconn = conn._conn   # raw java connection; leave autocommit = true (UNCHAINED)

        def sql_row(table, row):
            cols = list(row.keys())
            vals = [W._sql_literal(row[c]) for c in cols]
            return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)})"

        base = int(W._q1(conn, "SELECT lastdocnumberin_supp FROM lastdocnumbers WHERE branchcode=?", [bc])[0])
        nowq = float((W._q1(conn, "SELECT nowqty FROM stkbal WHERE storecode=? AND itemcode=?", [bc, ic]) or [0])[0] or 0)
        dn = base + 1
        newqty = nowq + qty

        hdr = {'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
               'specialdiscp': 0.0, 'origintaxp': 0.0, 'storecode': bc, 'fatstatuscode': '10',
               'ptcode': '20', 'ptclassifcode': '60', 'fatcurrentstatus': '15',
               'docwritedate': W._TODAY_MIDNIGHT, 'custdiscp': 0.0, 'usercode': '1509',
               'cust_branch_store': bc, 'cust_professional': '0', 'saleprice_extrap': 0.0,
               'docvalue': 285.0, 'docvaluepay': 0.0, 'docvaluereturn': 0.0, 'patientpayment': 0.0,
               'docvalue1': 0.0, 'docvalue2': 0.0, 'docvalue3': 0.0, 'bcurrency': 1,
               'docvaluebc': 285.0, 'docvaluepaybc': 0.0, 'bcrate': 1.0, 'supp_main_code': '00',
               'cust_branch_code': sup, 'origdoc': 0, 'docnumber2': 9990003}
        line = {'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
                'storecode': bc, 'itemcode': ic, 'itemsalestax': 0.0, 'itemsaleprice_tax': 38.0,
                'pharmacydiscp': 25.0, 'additionaldiscp': 0.0,
                'itemexpirydate': W._Raw("convert(datetime,'2028-03-31 00:00:00')"),
                'transprice': 28.5, 'transprice_total': 285.0, 'origintaxp': 0.0, 'custdiscp': 0.0,
                'specialdiscp': 0.0, 'saleprice_extrap': 0.0, 'usercode': '1509', 'bonusqty': 0.0,
                'dblitemflag': 1, 'storecode2': '0', 'transqty': qty, 'newqty': newqty, 'retqty': 0.0,
                'suppliercode': sup, 'personcode': sup, 'itemsaleprice': 38.0, 'promtype': 1}

        batch = f"""
set chained off
declare @e1 int, @e2 int, @lines int, @tc int
begin tran
{sql_row('stktransm', hdr)}
select @e1 = @@error
{sql_row('stktrans', line)}
select @e2 = @@error, @tc = @@trancount
select @lines = count(*) from stktrans where branchcode='{bc}' and doccode='10' and docnumber={dn}
if @@trancount > 0 rollback tran
select @e1 as hdr_err, @e2 as line_err, @lines as lines, @tc as trancount_after_line
"""
        st = jconn.createStatement()
        try:
            has_rs = st.execute(batch)
            # walk all results, keep the last result set (our final SELECT)
            last = None
            while True:
                if has_rs:
                    rs = st.getResultSet()
                    if rs is not None:
                        cols = rs.getMetaData().getColumnCount()
                        if rs.next():
                            last = [rs.getObject(i) for i in range(1, cols + 1)]
                        rs.close()
                if (not has_rs) and st.getUpdateCount() == -1:
                    break
                has_rs = st.getMoreResults()
            self.stdout.write(f'UNCHAINED test item {ic}: docnumber={dn} newqty={newqty}')
            self.stdout.write(f'  RESULT: hdr_err/line_err/lines/trancount = {last}')
            if last and int(last[2] or 0) == 1 and int(last[1] or -1) == 0:
                self.stdout.write(self.style.SUCCESS('  ✓✓✓ LINE LANDED in UNCHAINED mode — this was the bottleneck!'))
            else:
                self.stdout.write(self.style.WARNING('  still rejected in unchained mode.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'batch EXC: {str(e)[:400]}'))
        finally:
            try:
                st.execute('if @@trancount > 0 rollback tran')
            except Exception:
                pass
            st.close(); conn.close()

        # transaction mode of the objects (read-only)
        c2 = get_branch_connection(settings.SYBASE_HOST, 5000, 'SOFTECHDB9')
        try:
            for nm in ('sp_expirytrans', 'tr_stktrans', 'tr_stktransm'):
                r = W._q1(c2, "SELECT sysstat2 & 6 FROM sysobjects WHERE name=?", [nm])
                mode = {0: 'anymode', 2: 'chained', 4: 'unchained', 6: 'anymode?'}.get(int(r[0]) if r and r[0] is not None else -1, '?')
                self.stdout.write(f'  xmode {nm}: sysstat2&6={r[0] if r else None} -> {mode}')
        finally:
            c2.close()
