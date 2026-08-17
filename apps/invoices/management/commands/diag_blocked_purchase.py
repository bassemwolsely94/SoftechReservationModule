"""
python manage.py diag_blocked_purchase [--branch 100]

DIAGNOSTIC (rolls back): does SofTech's stktrans trigger ENFORCE the purchase block
(items.itemtrans3 IN 2/3), or is it only the client that blocks? Finds a purchase-
blocked-but-otherwise-active item, attempts a real doccode-10 header+line insert on
the branch DB, reports @@error/@@rowcount (did the line land?), then ROLLS BACK.
Also tests a normal item (itemtrans3=0) as a control.
"""
from types import SimpleNamespace
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Test whether SofTech DB enforces the purchase block (itemtrans3), rolls back.'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='100')
        parser.add_argument('--supplier', default='30')

    def handle(self, *args, **o):
        from django.conf import settings
        from config.sybase import SoftechConnector, get_branch_connection
        from apps.invoices import writer as W

        bc, sup = str(o['branch']), str(o['supplier'])
        sc = SoftechConnector(profile='prod').connect()

        def one(sql, p=None):
            sc._cursor().execute('SET ROWCOUNT 1')
            try:
                cur = sc._cursor(); cur.execute(sql, p or [])
                r = cur.fetchone(); return r
            finally:
                sc._cursor().execute('SET ROWCOUNT 0')

        # blocked-but-active item (itemtrans3=3, not discontinued/archived, has stock at this store)
        blk = one("SELECT i.itemcode, i.itemsaleprice, i.itemsalestaxp, i.itemtrans3, i.itemexpiry "
                  "FROM items i, stkbal b WHERE i.itemtrans3=3 AND i.itemnomoreuse='0' AND i.itemarchive=0 "
                  "AND b.itemcode=i.itemcode AND b.storecode=? AND b.nowqty>0", [bc])
        norm = one("SELECT i.itemcode, i.itemsaleprice, i.itemsalestaxp, i.itemtrans3, i.itemexpiry "
                   "FROM items i, stkbal b WHERE i.itemtrans3=0 AND i.itemnomoreuse='0' AND i.itemarchive=0 "
                   "AND b.itemcode=i.itemcode AND b.storecode=? AND b.nowqty>0", [bc])
        sc.close()
        if not blk:
            self.stdout.write('No blocked-but-active item found (all itemtrans3=3 are also discontinued/archived).')
        for tag, row in (('BLOCKED itemtrans3=3', blk), ('CONTROL itemtrans3=0', norm)):
            if not row:
                continue
            self._test(settings, get_branch_connection, W, bc, sup, tag, row)

    def _test(self, settings, get_branch_connection, W, bc, sup, tag, row):
        code = str(row[0]).strip(); public = float(row[1] or 0); taxp = float(row[2] or 0)
        trans3 = int(row[3] or 0)
        self.stdout.write(f'\n=== {tag}: item {code} public={public} itemtrans3={trans3} ===')
        conn = get_branch_connection(settings.SYBASE_HOST, 5000, 'SOFTECHDB9', charset='cp1256')
        try:
            conn.execute if False else None
            W._exec(conn, 'set chained off')
            conn.begin()
            nowq = float((W._q1(conn, "SELECT nowqty FROM stkbal WHERE storecode=? AND itemcode=?", [bc, code]) or [0])[0] or 0)
            dn = int(W._q1(conn, "SELECT lastdocnumberin_supp FROM lastdocnumbers WHERE branchcode=?", [bc])[0]) + 1
            exp = W._q1(conn, "SELECT itemexpirydate FROM stkbalexpiry WHERE storecode=? AND itemcode=? AND itemqty>0", [bc, code])
            expd = exp[0] if exp else None
            net = round(public * 0.8, 4) or 1.0
            hdr = {  # 32-col purchase header
                'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
                'specialdiscp': 0.0, 'origintaxp': 0.0, 'storecode': bc, 'fatstatuscode': '10',
                'ptcode': '20', 'ptclassifcode': '60', 'fatcurrentstatus': '15',
                'docwritedate': W._TODAY_MIDNIGHT, 'custdiscp': 0.0, 'usercode': '1509',
                'cust_branch_store': bc, 'cust_professional': '0', 'saleprice_extrap': 0.0,
                'docvalue': net, 'docvaluepay': 0.0, 'docvaluereturn': 0.0, 'patientpayment': 0.0,
                'docvalue1': 0.0, 'docvalue2': 0.0, 'docvalue3': 0.0, 'bcurrency': 1,
                'docvaluebc': net, 'docvaluepaybc': 0.0, 'bcrate': 1.0, 'supp_main_code': '00',
                'cust_branch_code': sup, 'origdoc': 0, 'docnumber2': 9990009,
            }
            pd = round((1 - net / public) * 100, 4) if public > 0 else 0.0
            line = {  # 28-col purchase line
                'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
                'storecode': bc, 'itemcode': code, 'itemsalestax': 0.0, 'itemsaleprice_tax': public,
                'pharmacydiscp': pd, 'additionaldiscp': 0.0,
                'itemexpirydate': (W._Raw(f"convert(datetime, '{expd:%Y-%m-%d} 00:00:00')") if expd else None),
                'transprice': net, 'transprice_total': net, 'origintaxp': 0.0, 'custdiscp': 0.0,
                'specialdiscp': 0.0, 'saleprice_extrap': 0.0, 'usercode': '1509', 'bonusqty': 0.0,
                'dblitemflag': 1, 'storecode2': '0', 'transqty': 1.0, 'newqty': nowq + 1.0,
                'retqty': 0.0, 'suppliercode': sup, 'personcode': sup, 'itemsaleprice': public, 'promtype': 1,
            }
            W._exec_insert(conn, 'stktransm', hdr)
            W._exec_insert(conn, 'stktrans', line)
            d = W._q1(conn, "SELECT @@error, @@rowcount, @@trancount")
            lc = W._q1(conn, "SELECT COUNT(*) FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?", [bc, dn])
            landed = int(lc[0]) == 1
            self.stdout.write(f'  @@error={d[0]} @@rowcount={d[1]} line_present={lc[0]} → '
                              + ('LANDED (DB does NOT enforce the block)' if landed
                                 else 'REJECTED (DB enforces the block)'))
        except Exception as e:
            self.stdout.write(f'  EXC {str(e)[:200]}')
        finally:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
