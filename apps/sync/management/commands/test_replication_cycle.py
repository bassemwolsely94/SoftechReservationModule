"""
python manage.py test_replication_cycle --mode plant
python manage.py test_replication_cycle --mode verify

Proves that a single HQ items UPDATE replicates to all branches via the
SSB9 service bus (~30 min cycle).

plant : record every branch's current state for the test item, then write
        distinctive markers to HQ items (posdiscp/pharmacydiscp/itemsaleprice).
verify: re-read every branch and report which picked up the markers.

State is stored in a JSON file between the two runs.
"""
import json
import os
import datetime
from django.core.management.base import BaseCommand

ITEM = '127397'
STATE_FILE = os.path.join(os.path.dirname(__file__), '_repl_test_state.json')

# Distinctive markers unlikely to collide with real values
MARK_POS   = 17.0
MARK_PHARM = 33.0
MARK_PRICE = 52.0


class Command(BaseCommand):
    help = 'Plant/verify a HQ->branch replication cycle test'

    def add_arguments(self, parser):
        parser.add_argument('--mode', required=True, choices=['plant', 'verify'])

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        branches = list(Branch.objects.filter(
            is_operational=True, db_host__isnull=False
        ).exclude(softech_branch_id='100').exclude(db_host=''))

        def read_branch(b):
            bc = get_branch_connection(b.db_host, b.db_port or 5000)
            cur = bc.cursor()
            cur.execute('SELECT posdiscp, pharmacydiscp, itemsaleprice, usercode FROM items WHERE itemcode=?', [ITEM])
            r = cur.fetchone(); bc.close()
            return {
                'pos':   float(r[0] or 0), 'pharm': float(r[1] or 0),
                'price': float(r[2] or 0), 'user':  str(r[3] or '').strip(),
            } if r else None

        if options['mode'] == 'plant':
            # snapshot HQ + branches
            conn = get_sybase_connection(); cur = conn.cursor()
            cur.execute('SELECT posdiscp, pharmacydiscp, itemsaleprice, usercode FROM SOFTECHDB9.dbo.items WHERE itemcode=?', [ITEM])
            r = cur.fetchone()
            hq_orig = {'pos': float(r[0] or 0), 'pharm': float(r[1] or 0),
                       'price': float(r[2] or 0), 'user': str(r[3] or '').strip()}
            conn.close()
            out(f'HQ orig: {hq_orig}')

            branch_orig = {}
            for b in branches:
                try:
                    branch_orig[b.softech_branch_id] = read_branch(b)
                    out(f'BR{b.softech_branch_id} orig: {branch_orig[b.softech_branch_id]}')
                except Exception as e:
                    out(f'BR{b.softech_branch_id} read ERROR: {str(e)[:60]}')
                    branch_orig[b.softech_branch_id] = None

            # write markers to HQ items (the exact thing the module/ERP does)
            conn = get_sybase_connection(); cur = conn.cursor()
            cur.execute(
                'UPDATE SOFTECHDB9.dbo.items SET posdiscp=?, pharmacydiscp=?, itemsaleprice=?, usercode=? WHERE itemcode=?',
                [MARK_POS, MARK_PHARM, MARK_PRICE, '00099', ITEM]
            )
            conn.close()
            out(f'\n>>> Planted markers on HQ items: pos={MARK_POS} pharm={MARK_PHARM} price={MARK_PRICE}')

            state = {
                'planted_at': datetime.datetime.now().isoformat(),
                'item': ITEM,
                'markers': {'pos': MARK_POS, 'pharm': MARK_PHARM, 'price': MARK_PRICE},
                'hq_orig': hq_orig,
                'branch_orig': branch_orig,
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
            out(f'\nState saved -> {STATE_FILE}')
            out('Now wait ~30 min for the SSB9 service-bus cycle, then run --mode verify')

        else:  # verify
            if not os.path.exists(STATE_FILE):
                out('No plant state found. Run --mode plant first.'); return
            with open(STATE_FILE) as f:
                state = json.load(f)
            m = state['markers']
            planted = state['planted_at']
            out(f'Planted at: {planted}')
            out(f'Markers: pos={m["pos"]} pharm={m["pharm"]} price={m["price"]}')
            out(f'Now: {datetime.datetime.now().isoformat()}')
            out('')

            picked = 0
            for b in branches:
                bc_code = b.softech_branch_id
                try:
                    now = read_branch(b)
                    orig = state['branch_orig'].get(bc_code) or {}
                    pos_ok   = abs(now['pos']   - m['pos'])   < 0.01
                    pharm_ok = abs(now['pharm'] - m['pharm']) < 0.01
                    price_ok = abs(now['price'] - m['price']) < 0.01
                    all_ok   = pos_ok and pharm_ok and price_ok
                    if all_ok:
                        picked += 1
                    out(f'BR{bc_code}: pos={now["pos"]}({"OK" if pos_ok else "no"}) '
                        f'pharm={now["pharm"]}({"OK" if pharm_ok else "no"}) '
                        f'price={now["price"]}({"OK" if price_ok else "no"}) '
                        f'user={now["user"]}  [was pos={orig.get("pos")}]')
                except Exception as e:
                    out(f'BR{bc_code}: ERROR {str(e)[:60]}')

            out('')
            out(f'RESULT: {picked}/{len(branches)} branches replicated the HQ items change')
            if picked == len(branches):
                out('CONFIRMED: single HQ items UPDATE replicates to ALL branches (incl posdiscp)')
            elif picked > 0:
                out('PARTIAL: some branches replicated; others may be mid-cycle or offline')
            else:
                out('NOT YET: no branch has picked up the change (cycle may not have run)')
