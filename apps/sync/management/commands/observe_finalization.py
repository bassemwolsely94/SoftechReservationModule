"""
Empirically capture what the SOFTECH cashier "settle/finalize" action does to a
PENDING indirect-POS order — by snapshotting all relevant tables BEFORE and AFTER
and diffing them. READ-ONLY on our side; the human performs the settle in SOFTECH.

Workflow (controlled experiment on a branch you can act on, e.g. 130):
  1. Have a PENDING order sitting in stktransm5 awaiting the cashier. Note its docnumber.
  2. python manage.py observe_finalization --host 192.168.30.12 --docnumber <N> --label before
  3. In SOFTECH, settle/pay that order on the Cashier screen.
  4. python manage.py observe_finalization --host 192.168.30.12 --docnumber <N> --label after
  5. python manage.py observe_finalization --diff
  6. (optional) reverse/return the transaction in SOFTECH to clean up.

Captures (filtered to the order's branch / PIC / item codes):
  pending : stktransm5, stktrans5, branchesales5
  final   : stktransm, stktrans, branchesales  (same docnumber AND phcode-recent — to catch reuse vs new#)
  stock   : stkbal (per item/store)
  points  : picpoints (log), localcustomerspoints, localcustomers.picpoints
  serials : lastdocnumbers (branchcode='000'), stktransm_inv

ABSOLUTE RULE: SELECT only.
Snapshots -> docs/architecture/finalization_<label>.json
"""
import os
import json
import datetime
from django.core.management.base import BaseCommand

SNAP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture')


def _snap_path(label):
    return os.path.abspath(os.path.join(SNAP_DIR, f'finalization_{label}.json'))


class Command(BaseCommand):
    help = 'READ-ONLY before/after snapshot + diff of a cashier finalization'

    def add_arguments(self, parser):
        parser.add_argument('--host', default='192.168.30.12', help='branch ASE host (130=192.168.30.12, 160=192.168.1.5)')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--docnumber', type=int, help='pending stktransm5 docnumber to track')
        parser.add_argument('--label', choices=['before', 'after'], help='snapshot label')
        parser.add_argument('--diff', action='store_true', help='diff before vs after snapshots')

    def handle(self, *args, **options):
        if options['diff']:
            self._diff()
            return
        if not options['label'] or not options['docnumber']:
            self.stderr.write('Provide --docnumber and --label before|after, or --diff'); return
        self._snapshot(options['host'], options['port'], options['docnumber'], options['label'])

    # ── snapshot ──────────────────────────────────────────────────────────────
    def _snapshot(self, host, port, docnumber, label):
        from config.sybase import get_branch_connection
        conn = get_branch_connection(host, port)
        cur = conn.cursor()

        def rows(sql, rc=200):
            try:
                cur.execute(f'SET ROWCOUNT {rc}'); cur.execute(sql)
                cols = [d[0] for d in cur.description]
                out = [dict(zip(cols, [self._py(v) for v in r])) for r in cur.fetchall()]
                cur.execute('SET ROWCOUNT 0')
                return out
            except Exception as e:
                return [{'__error__': str(e)}]

        # pending header → derive branch, phcode, storecode, itemcodes
        hdr = rows(f"SELECT * FROM stktransm5 WHERE docnumber={docnumber}")
        branch = phcode = store = None
        items = []
        if hdr and '__error__' not in hdr[0]:
            branch = str(hdr[0].get('branchcode') or '').strip()
            phcode = str(hdr[0].get('phcode') or '').strip()
            store  = str(hdr[0].get('storecode') or '').strip()
        plines = rows(f"SELECT * FROM stktrans5 WHERE docnumber={docnumber}")
        for r in plines:
            ic = str(r.get('itemcode') or '').strip()
            if ic and ic not in items:
                items.append(ic)
        # If the pending order is already gone (e.g. AFTER settlement), recover the
        # keys (phcode/items/store/branch) from the BEFORE snapshot so we can still
        # query stkbal/points/final-doc for the SAME entities.
        if not phcode:
            bp = _snap_path('before')
            if os.path.exists(bp):
                try:
                    bmeta = json.load(open(bp, encoding='utf-8')).get('meta', {})
                    branch = branch or bmeta.get('branch')
                    phcode = phcode or bmeta.get('phcode')
                    store  = store  or bmeta.get('store')
                    items  = items  or list(bmeta.get('items') or [])
                except Exception:
                    pass
        in_list = ','.join(f"'{i}'" for i in items) if items else "''"
        ph = phcode or '@@none@@'

        snap = {
            'meta': {'label': label, 'host': host, 'docnumber': docnumber,
                     'branch': branch, 'phcode': phcode, 'store': store, 'items': items,
                     'captured_at': datetime.datetime.now().isoformat()},
            # pending
            'stktransm5':   hdr,
            'stktrans5':    plines,
            'branchesales5': rows(f"SELECT * FROM branchesales5 WHERE docnumber={docnumber}"),
            # final (same docnumber AND phcode-recent to catch reuse vs new number)
            'stktransm_samedoc':  rows(f"SELECT * FROM stktransm WHERE docnumber={docnumber}"),
            'stktrans_samedoc':   rows(f"SELECT * FROM stktrans WHERE docnumber={docnumber}"),
            'branchesales_samedoc': rows(f"SELECT * FROM branchesales WHERE docnumber={docnumber}"),
            'stktransm_phcode_recent': rows(
                f"SELECT branchcode,doccode,docnumber,docvalue,docvaluepay,patientpayment,ptclassifcode,trans_time "
                f"FROM stktransm WHERE phcode='{ph}' AND docdate>=DATEADD(day,-1,GETDATE())"),
            # stock
            'stkbal': rows(f"SELECT storecode,itemcode,nowqty,nowqtyout,nowcostprice,opencostprice FROM stkbal "
                           f"WHERE itemcode IN ({in_list})") if items else [],
            # points
            'picpoints': rows(f"SELECT transdate,points,branchcode,doccode,docnumber,vf1,vf2 FROM picpoints "
                              f"WHERE phcode='{ph}' AND transdate>=DATEADD(day,-2,GETDATE())"),
            'localcustomerspoints': rows(f"SELECT branchcode,phcode,totpoints,conpoints FROM localcustomerspoints WHERE phcode='{ph}'"),
            'localcustomers_pic': rows(f"SELECT branchcode,phcode,picpoints FROM localcustomers WHERE phcode='{ph}'"),
            # serials / e-invoice
            # ALL rows: '000'=ver_branch0 staging counters, the branch's own row=ver_branch1 FINAL counters
            'lastdocnumbers': rows("SELECT branchcode,lastdocnumberin,lastdocnumberout,lastdocnumberout_cust,"
                                   "lastdocnumberout_inv,paymentsno,ver_branch FROM lastdocnumbers"),
            'stktransm_inv': rows(f"SELECT branchcode,doccode,docnumber,docnumber_inv FROM stktransm_inv WHERE docnumber={docnumber}"),
        }
        conn.close()
        path = _snap_path(label)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=2, default=str)
        self.stdout.write(self.style.SUCCESS(
            f'[{label}] saved -> {path}\n  branch={branch} phcode={phcode} store={store} items={items}\n'
            f'  pending hdr rows={len(hdr)} lines={len(plines)} pay={len(snap["branchesales5"])}'))

    # ── diff ──────────────────────────────────────────────────────────────────
    def _diff(self):
        b_path, a_path = _snap_path('before'), _snap_path('after')
        if not (os.path.exists(b_path) and os.path.exists(a_path)):
            self.stderr.write('Need both finalization_before.json and finalization_after.json'); return
        before = json.load(open(b_path, encoding='utf-8'))
        after  = json.load(open(a_path, encoding='utf-8'))

        def line(s=''):
            self.stdout.write(s)

        line('=' * 78)
        line('  FINALIZATION DIFF  (before -> after)')
        line(f"  docnumber={before['meta']['docnumber']}  branch={before['meta']['branch']}  "
             f"phcode={before['meta']['phcode']}  items={before['meta']['items']}")
        line('=' * 78)

        def count(snap, key):
            v = snap.get(key, [])
            return 0 if (v and isinstance(v, list) and v and '__error__' in v[0]) else len(v)

        # presence/row-count changes
        line('\n-- table row-count changes --')
        for key in ['stktransm5', 'stktrans5', 'branchesales5',
                    'stktransm_samedoc', 'stktrans_samedoc', 'branchesales_samedoc',
                    'stktransm_phcode_recent', 'picpoints']:
            nb, na = count(before, key), count(after, key)
            flag = '' if nb == na else '   <<< CHANGED'
            line(f'  {key:<26} {nb:>3} -> {na:>3}{flag}')

        # stkbal numeric deltas
        line('\n-- stkbal (stock) deltas --')
        bmap = {(r.get('storecode'), r.get('itemcode')): r for r in before.get('stkbal', []) if '__error__' not in r}
        amap = {(r.get('storecode'), r.get('itemcode')): r for r in after.get('stkbal', []) if '__error__' not in r}
        for k in sorted(set(bmap) | set(amap)):
            rb, ra = bmap.get(k, {}), amap.get(k, {})
            for col in ('nowqty', 'nowqtyout', 'nowcostprice'):
                vb, va = rb.get(col), ra.get(col)
                if str(vb) != str(va):
                    line(f'  item {k[1]} store {k[0]}  {col}: {vb} -> {va}')

        # points deltas
        line('\n-- points deltas --')
        for key, cols in [('localcustomerspoints', ('totpoints', 'conpoints')),
                          ('localcustomers_pic', ('picpoints',))]:
            rb = (before.get(key) or [{}])[0]
            ra = (after.get(key) or [{}])[0]
            for col in cols:
                if str(rb.get(col)) != str(ra.get(col)):
                    line(f'  {key}.{col}: {rb.get(col)} -> {ra.get(col)}')
        nb_pp = count(before, 'picpoints'); na_pp = count(after, 'picpoints')
        if na_pp > nb_pp:
            line(f'  picpoints: {na_pp - nb_pp} NEW log row(s):')
            bkeys = {(r.get('transdate'), r.get('docnumber'), r.get('points')) for r in before.get('picpoints', [])}
            for r in after.get('picpoints', []):
                if (r.get('transdate'), r.get('docnumber'), r.get('points')) not in bkeys:
                    line(f'    {r}')

        # lastdocnumbers counter deltas
        line('\n-- lastdocnumbers counter deltas --')
        bmap = {r.get('branchcode'): r for r in before.get('lastdocnumbers', []) if '__error__' not in r}
        amap = {r.get('branchcode'): r for r in after.get('lastdocnumbers', []) if '__error__' not in r}
        for bc in sorted(set(bmap) | set(amap)):
            rb, ra = bmap.get(bc, {}), amap.get(bc, {})
            for col in ('lastdocnumberout_cust', 'lastdocnumberout', 'paymentsno', 'lastdocnumberout_inv'):
                if str(rb.get(col)) != str(ra.get(col)):
                    line(f'  [{bc}] {col}: {rb.get(col)} -> {ra.get(col)}')

        # NEW final rows (the settled document)
        line('\n-- NEW final stktransm rows for this PIC (the settled doc) --')
        bset = {(r.get('docnumber')) for r in before.get('stktransm_phcode_recent', [])}
        for r in after.get('stktransm_phcode_recent', []):
            if r.get('docnumber') not in bset:
                line(f'    {r}')
        line('\n(Use the new docnumber above to pull its stktrans/branchesales lines next.)')

    @staticmethod
    def _py(v):
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v.isoformat()
        return v
