"""
python manage.py diag_appname [--item 404] [--qty 10]

Test whether tr_stktrans/sp_expirytrans gate on the connection's program_name /
hostname / language. Opens jConnect connections with different APPLICATIONNAME +
HOSTNAME (mimicking the native SofTech client), inserts a purchase header+line for
one item, and reports @@error. Also lists custom languages + error-message tables.
Rolls back everything.
"""
from django.core.management.base import BaseCommand


def _connect(app, host, charset='cp1256'):
    """Open a raw jConnect connection with a chosen APPLICATIONNAME + HOSTNAME."""
    import jpype
    from django.conf import settings
    from config.sybase import _ensure_jvm, ConnectionWrapper, SYBASE_LOGIN_TIMEOUT_SECONDS
    _ensure_jvm()
    jpype.imports.registerDomain('com')
    from com.sybase.jdbc3.jdbc import SybDriver
    from java.util import Properties
    props = Properties()
    props.setProperty('user', settings.SYBASE_USER)
    props.setProperty('password', settings.SYBASE_PASSWORD)
    props.setProperty('LOGIN_TIMEOUT', str(SYBASE_LOGIN_TIMEOUT_SECONDS))
    if app:
        props.setProperty('APPLICATIONNAME', app)
    if host:
        props.setProperty('HOSTNAME', host)
    if charset:
        props.setProperty('CHARSET', charset)
    url = f'jdbc:sybase:Tds:{settings.SYBASE_HOST}:5000/SOFTECHDB9'
    return ConnectionWrapper(SybDriver().connect(url, props))


class Command(BaseCommand):
    help = 'Probe program_name/hostname/language gating of the stktrans insert (rolls back).'

    def add_arguments(self, parser):
        parser.add_argument('--item', default='404')
        parser.add_argument('--qty', type=float, default=10.0)
        parser.add_argument('--branch', default='100')
        parser.add_argument('--supplier', default='30')

    def handle(self, *args, **o):
        from apps.invoices import writer as W

        bc, ic, qty, sup = o['branch'], str(o['item']), float(o['qty']), str(o['supplier'])

        # ── context: languages + candidate error-message tables ────────────────
        info = _connect('BASSEM', 'SSB')
        try:
            cur = info.cursor(); cur.execute("SELECT langid, name, alias FROM master..syslanguages")
            self.stdout.write('languages: ' + '; '.join(f'{r[0]}:{r[1]}/{r[2]}' for r in cur.fetchall()))
            cur = info.cursor()
            cur.execute("SELECT name FROM sysobjects WHERE type='U' AND (lower(name) LIKE '%error%' "
                        "OR lower(name) LIKE '%msg%' OR lower(name) LIKE '%message%')")
            self.stdout.write('msg/error tables: ' + ', '.join(str(r[0]) for r in cur.fetchall()))
        finally:
            info.close()

        expiry = W._Raw("convert(datetime,'2028-03-31 00:00:00')")

        def hdr(dn):
            return {'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
                    'specialdiscp': 0.0, 'origintaxp': 0.0, 'storecode': bc, 'fatstatuscode': '10',
                    'ptcode': '20', 'ptclassifcode': '60', 'fatcurrentstatus': '15',
                    'docwritedate': W._TODAY_MIDNIGHT, 'custdiscp': 0.0, 'usercode': '1509',
                    'cust_branch_store': bc, 'cust_professional': '0', 'saleprice_extrap': 0.0,
                    'docvalue': 285.0, 'docvaluepay': 0.0, 'docvaluereturn': 0.0, 'patientpayment': 0.0,
                    'docvalue1': 0.0, 'docvalue2': 0.0, 'docvalue3': 0.0, 'bcurrency': 1,
                    'docvaluebc': 285.0, 'docvaluepaybc': 0.0, 'bcrate': 1.0, 'supp_main_code': '00',
                    'cust_branch_code': sup, 'origdoc': 0, 'docnumber2': 9990002}

        def line(dn, nq):
            return {'branchcode': bc, 'doccode': '10', 'docnumber': dn, 'docdate': W._TODAY_MIDNIGHT,
                    'storecode': bc, 'itemcode': ic, 'itemsalestax': 0.0, 'itemsaleprice_tax': 38.0,
                    'pharmacydiscp': 25.0, 'additionaldiscp': 0.0, 'itemexpirydate': expiry,
                    'transprice': 28.5, 'transprice_total': 285.0, 'origintaxp': 0.0, 'custdiscp': 0.0,
                    'specialdiscp': 0.0, 'saleprice_extrap': 0.0, 'usercode': '1509', 'bonusqty': 0.0,
                    'dblitemflag': 1, 'storecode2': '0', 'transqty': qty, 'newqty': nq, 'retqty': 0.0,
                    'suppliercode': sup, 'personcode': sup, 'itemsaleprice': 38.0, 'promtype': 1}

        # ── try several identities ─────────────────────────────────────────────
        identities = [
            ('BASSEM', 'SSB'),
            ('SofTech9', 'SSB'),
            ('', 'SSB'),
            ('SC_ASEJ_Mgmt', 'Server'),
        ]
        for app, host in identities:
            conn = _connect(app, host)
            try:
                who = conn.cursor(); who.execute("SELECT hostname, program_name FROM master..sysprocesses WHERE spid=@@spid")
                idrow = who.fetchone()
                base = int(W._q1(conn, "SELECT lastdocnumberin_supp FROM lastdocnumbers WHERE branchcode=?", [bc])[0])
                nowq = float((W._q1(conn, "SELECT nowqty FROM stkbal WHERE storecode=? AND itemcode=?", [bc, ic]) or [0])[0] or 0)
                conn.begin()
                dn = base + 1
                W._exec_insert(conn, 'stktransm', hdr(dn))
                W._exec_insert(conn, 'stktrans', line(dn, nowq + qty))
                d = W._q1(conn, "SELECT @@error, @@rowcount, @@trancount")
                lc = W._q1(conn, "SELECT COUNT(*) FROM stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?", [bc, dn])
                st = 'LANDS ✓✓✓' if int(lc[0]) == 1 else 'rejected'
                self.stdout.write(f'app={app!r:<16} host={host!r:<8} -> sysproc={idrow} '
                                  f'@@error={d[0]} rowcount={d[1]} lines={lc[0]} => {st}')
            except Exception as e:
                self.stdout.write(f'app={app!r} host={host!r}: EXC {str(e)[:150]}')
            finally:
                try:
                    conn.rollback()
                except Exception:
                    pass
                conn.close()
