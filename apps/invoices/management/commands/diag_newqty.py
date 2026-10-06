"""
python manage.py diag_newqty [--branch 100] [--item 404] [--qty 10] [--profile prod]

Test whether the stktrans line insert (err 2732 from tr_stktrans -> sp_expirytrans)
is gated by the newqty VALUE. For a single item, read stkbal.nowqty and
sum(stkbalexpiry), then try inserting the line with several candidate newqty values
(each in its own rollback), reporting which — if any — the trigger accepts (@@error=0).
Rolls back everything.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Probe which newqty value makes the stktrans purchase line insert land (rolls back).'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='100')
        parser.add_argument('--item', default='404')
        parser.add_argument('--qty', type=float, default=10.0)
        parser.add_argument('--supplier', default='30')
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **o):
        from django.conf import settings
        from config.sybase import get_branch_connection
        from apps.invoices import writer as W

        bc, ic, qty, sup = str(o['branch']), str(o['item']), float(o['qty']), str(o['supplier'])
        conn = get_branch_connection(settings.SYBASE_HOST, 5000, 'SOFTECHDB9', charset='cp1256')

        def q1(sql, p=None):
            return W._q1(conn, sql, p)

        nowqty = float((q1("SELECT nowqty FROM stkbal WHERE storecode=? AND itemcode=?", [bc, ic]) or [0])[0] or 0)
        esum = q1("SELECT sum(itemqty) FROM stkbalexpiry WHERE storecode=? AND itemcode=?", [bc, ic])
        expiry_sum = float(esum[0]) if esum and esum[0] is not None else 0.0
        exprow = q1("SELECT itemexpirydate, itemqty FROM stkbalexpiry WHERE storecode=? AND itemcode=? "
                    "AND itemqty>0", [bc, ic])
        exp = exprow[0] if exprow else None
        self.stdout.write(f'item {ic} @ store {bc}: stkbal.nowqty={nowqty}  sum(stkbalexpiry)={expiry_sum}  '
                          f'sample_batch_expiry={exp}')
        exp_lit = W._Raw(f"convert(datetime,'{exp:%Y-%m-%d} 00:00:00')") if exp else \
            W._Raw("convert(datetime,'2028-09-09 00:00:00')")

        candidates = {
            'stkbal+qty':        nowqty + qty,
            'expirysum+qty':     expiry_sum + qty,
            'qty_only':          qty,
            'stkbal_only':       nowqty,
            'expirysum_only':    expiry_sum,
        }

        counter = 'lastdocnumberin_supp'
        base = int(q1(f"SELECT {counter} FROM lastdocnumbers WHERE branchcode=?", [bc])[0])

        def hdr(dn):
            return {  # 32-col captured header
                'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
                'specialdiscp': 0.0, 'origintaxp': 0.0, 'storecode': bc, 'fatstatuscode': '10',
                'ptcode': '20', 'ptclassifcode': '60', 'fatcurrentstatus': '15',
                'docwritedate': W._TODAY_MIDNIGHT, 'custdiscp': 0.0, 'usercode': '1509',
                'cust_branch_store': bc, 'cust_professional': '0', 'saleprice_extrap': 0.0,
                'docvalue': 285.0, 'docvaluepay': 0.0, 'docvaluereturn': 0.0, 'patientpayment': 0.0,
                'docvalue1': 0.0, 'docvalue2': 0.0, 'docvalue3': 0.0, 'bcurrency': 1,
                'docvaluebc': 285.0, 'docvaluepaybc': 0.0, 'bcrate': 1.0, 'supp_main_code': '00',
                'cust_branch_code': sup, 'origdoc': 0, 'docnumber2': 9990001,
            }

        def line(dn, nq):
            return {  # 28-col captured line
                'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
                'storecode': bc, 'itemcode': ic, 'itemsalestax': 0.0, 'itemsaleprice_tax': 38.0,
                'pharmacydiscp': 25.0, 'additionaldiscp': 0.0, 'itemexpirydate': exp_lit,
                'transprice': 28.5, 'transprice_total': 285.0, 'origintaxp': 0.0, 'custdiscp': 0.0,
                'specialdiscp': 0.0, 'saleprice_extrap': 0.0, 'usercode': '1509', 'bonusqty': 0.0,
                'dblitemflag': 1, 'storecode2': '0', 'transqty': qty, 'newqty': nq, 'retqty': 0.0,
                'suppliercode': sup, 'personcode': sup, 'itemsaleprice': 38.0, 'promtype': 1,
            }

        for name, nq in candidates.items():
            try:
                conn.begin()
                dn = base + 1
                W._exec_insert(conn, 'stktransm', hdr(dn))
                W._exec_insert(conn, 'stktrans', line(dn, nq))
                d = q1("SELECT @@error, @@rowcount, @@trancount")
                lc = q1("SELECT COUNT(*) FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?", [bc, dn])
                status = 'LANDS ✓' if int(d[1]) == 1 and int(lc[0]) == 1 else 'rejected'
                self.stdout.write(f'  newqty={nq:<10} [{name:<15}] @@error={d[0]} rowcount={d[1]} '
                                  f'lines={lc[0]} -> {status}')
            except Exception as e:
                self.stdout.write(f'  [{name}] EXC {str(e)[:150]}')
            finally:
                try:
                    conn.rollback()
                except Exception:
                    pass
        conn.close()
