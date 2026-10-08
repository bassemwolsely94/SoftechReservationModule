"""
READ-ONLY SOFTECH probe for B7 — does a customer-code (PIC) change made at HQ reach the branch nodes?

Owner 2026-10-08: "a deactivated PIC should be deactivated on both branch and HQ and it should be
replicated, maybe this is a replication error". The branch-150 node had no copy of the deactivated
03HD3059 at all, and no '0' code anywhere. This probe compares HQ with EVERY branch node, side by side,
using SOFTECH's own replication stamp `table_dumped` (the agent ships a row and stamps the time; HQ
triggers reset it to 1900-01-01 to force a re-ship, see tr_personphones_*). Only SELECTs. Phones are
never read and names are never printed.

    python manage.py investigate_pic_replication                         # HQ vs all operational nodes
    python manage.py investigate_pic_replication --host 192.168.3.10     # one node (repeatable)
    python manage.py investigate_pic_replication --pic 03HD3059 --pic 06HD8958

Sections
  [R1] each node: own branch code (lastdocnumbers.ver_branch='1'), row counts, which branch codes it holds
  [R2] HQ's non-active / locked codes (+ any --pic): present on which node, with what status / balance
  [R3] codes on HQ AND a node: status / lock / balance mismatches, and which side changed last
  [R4] HQ replication stamps: table_dumped NULL / 1900 / stamped, and status changed AFTER the last ship
  [R5] SOFTECH's own code-change / parent / points-edit tables (localcustomers_main, _2, _n,
       lcpointstrans, picstrans, temppic) + procs that rewrite phcode / pphcode
  --explain:
  [R6] SOFTECH's native merge (localcustomers2) and PIC-edit log (picstrans) on HQ and every node
  [R7] the largest balance gaps per node: points log + manual points edits (lcpointstrans) on both sides
"""
import os
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

DB = 'SOFTECHDB9.dbo'
SIDE_TABLES = ('localcustomers_main', 'localcustomers2', 'localcustomers_n', 'lcpointstrans', 'picstrans', 'temppic')
EPOCH_YEAR = 1900


def _s(v):
    return str(v).strip() if v is not None else ''


def _year(v):
    return getattr(v, 'year', None)


class Command(BaseCommand):
    help = 'READ-ONLY probe: HQ vs branch-node copies of customer codes (status, lock, points) — B7.'

    def add_arguments(self, parser):
        parser.add_argument('--host', action='append', default=[], help='branch node host (repeatable; default: all)')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--pic', action='append', default=[], help='extra PIC to trace on every node')
        parser.add_argument('--samples', type=int, default=8)
        parser.add_argument('--explain', action='store_true',
                            help='also explain balance mismatches (points log + manual edits, both sides) and read '
                                 "SOFTECH's own merge / PIC-edit tables on every node")
        parser.add_argument('--out', default='scratch/pic_replication_probe.txt',
                            help='also write the report here (scratch/ is git-ignored)')

    # ── helpers ───────────────────────────────────────────────────────────────
    def _emit(self, line=''):
        self.stdout.write(str(line))
        self._buf.append(str(line))

    def _q(self, conn, sql, params=None, limit=None):
        cur = conn.cursor()
        try:
            if limit:
                cur.execute(f'SET ROWCOUNT {int(limit)}')
            cur.execute(sql, params or [])
            return [d[0] for d in (cur.description or [])], cur.fetchall()
        finally:
            if limit:
                try:
                    cur.execute('SET ROWCOUNT 0')
                except Exception:
                    pass

    def _safe(self, title, fn):
        self._emit('')
        self._emit(f'── {title} ' + '─' * max(0, 66 - len(title)))
        try:
            fn()
        except Exception as exc:
            self._emit(f'  ! failed: {str(exc)[:300]}')

    def _load(self, conn):
        """{phcode: {...}} customers + points of one database (no names, no phones)."""
        _, rows = self._q(conn, f'SELECT phcode, phcodestatus, piclock, branchcode, trans_time, table_dumped, '
                                f'phcodestatustime, pphcode FROM {DB}.localcustomers')
        cust = {_s(r[0]): {'status': _s(r[1]), 'lock': r[2] or 0, 'branch': _s(r[3]), 'trans': r[4],
                           'dumped': r[5], 'st_time': r[6], 'pph': _s(r[7])} for r in rows}
        _, rows = self._q(conn, f'SELECT phcode, totpoints, conpoints, table_dumped FROM {DB}.localcustomerspoints')
        pts = {_s(r[0]): ((r[1] or 0), (r[2] or 0), r[3]) for r in rows}
        return cust, pts

    def _bal(self, pts, pic):
        p = pts.get(pic)
        return None if p is None else p[0] - p[1]

    # ── sections ──────────────────────────────────────────────────────────────
    def s_nodes(self):
        for n in self.nodes:
            if n.get('error'):
                self._emit(f'  {n["label"]}: ! not reachable — {n["error"]}')
                continue
            by_branch = Counter(c['branch'] for c in n['cust'].values())
            self._emit(f'  {n["label"]}: own branch {n["own"] or "?"} · {len(n["cust"])} customers · '
                       f'{len(n["pts"])} balance rows · held by creating branch: '
                       + ', '.join(f'{b}={k}' for b, k in by_branch.most_common(14)))
            st = Counter(c['status'] for c in n['cust'].values())
            self._emit('      phcodestatus: ' + ', '.join(f'{k!r}={v}' for k, v in st.most_common()))

    def s_trace(self):
        hq = self.hq_cust
        watch = sorted({p for p, c in hq.items() if c['status'] != '1' or c['lock']} | set(self.pics))
        self._emit(f'  {len(watch)} codes traced (HQ non-active / locked + --pic):')
        for pic in watch:
            c = hq.get(pic)
            if not c:
                self._emit(f'    {pic}: not at HQ')
                continue
            self._emit(f'    {pic}: HQ status={c["status"]!r} lock={c["lock"]} created_at_branch={c["branch"]} '
                       f'status_changed={c["st_time"]} modified={c["trans"]} last_shipped={c["dumped"]} '
                       f'balance={self._bal(self.hq_pts, pic)}')
            for n in self.nodes:
                if n.get('error'):
                    continue
                x = n['cust'].get(pic)
                if not x:
                    self._emit(f'        {n["label"]}: absent')
                    continue
                flag = '' if (x['status'], x['lock']) == (c['status'], c['lock']) else '   ◀ DIFFERENT'
                self._emit(f'        {n["label"]}: status={x["status"]!r} lock={x["lock"]} modified={x["trans"]} '
                           f'shipped={x["dumped"]} balance={self._bal(n["pts"], pic)}{flag}')

    def s_diff(self):
        hq, hp = self.hq_cust, self.hq_pts
        for n in self.nodes:
            if n.get('error'):
                continue
            both = set(hq) & set(n['cust'])
            only_node = len(set(n['cust']) - set(hq))
            st, lk, bal, ex, diff_sizes = Counter(), 0, Counter(), defaultdict(list), Counter()
            for pic in both:
                a, b = hq[pic], n['cust'][pic]
                if a['status'] != b['status']:
                    k = f"HQ {a['status']!r} / node {b['status']!r}"
                    st[k] += 1
                    if len(ex[k]) < self.samples:
                        newer = ('same time' if a['trans'] == b['trans'] else
                                 'HQ' if a['trans'] and (not b['trans'] or a['trans'] > b['trans']) else 'node')
                        ex[k].append(f'{pic} (changed last: {newer})')
                if bool(a['lock']) != bool(b['lock']):
                    lk += 1
                ba, bb = self._bal(hp, pic), self._bal(n['pts'], pic)
                if ba is not None and bb is not None and ba != bb:
                    bal['different'] += 1
                    n.setdefault('bal_diff', []).append((pic, ba, bb))
                    diff_sizes[bb - ba] += 1
                    if len(ex['balance']) < self.samples:
                        ex['balance'].append(f'{pic} HQ {ba} / node {bb}')
                elif (ba is None) != (bb is None):
                    bal['row on one side only'] += 1
            # codes this node CREATED that HQ holds but the node does not (the node lost its own customer)
            own = n['own']
            lost = sum(1 for p, c in hq.items() if own and c['branch'] == own and p not in n['cust'])
            self._emit(f'  {n["label"]}: on both {len(both)} · node-only {only_node} · '
                       f'HQ codes created at {own or "?"} missing on the node {lost}')
            self._emit('      status mismatches: ' + (', '.join(f'{k}={v}' for k, v in st.items()) or 'none'))
            for k in st:
                self._emit(f'        e.g. {k}: ' + ', '.join(ex[k]))
            self._emit(f'      lock mismatches: {lk} · balance: ' + (', '.join(f'{k}={v}' for k, v in bal.items()) or 'all equal'))
            if ex['balance']:
                self._emit('        e.g. ' + ', '.join(ex['balance']))
                self._emit('      most common (node − HQ): ' + ', '.join(f'{d:+}×{k}' for d, k in diff_sizes.most_common(10)))
                higher = sum(k for d, k in diff_sizes.items() if d > 0)
                self._emit(f'      node higher than HQ: {higher} · HQ higher than node: {sum(diff_sizes.values()) - higher}')

    def s_stamps(self):
        hq = self.hq_cust
        prof = Counter()
        for c in hq.values():
            d = c['dumped']
            prof['never shipped (NULL)' if d is None else 're-ship requested (1900)' if _year(d) == EPOCH_YEAR
                 else 'modified after last ship' if c['trans'] and c['trans'] > d else 'shipped, unchanged since'] += 1
        self._emit('  HQ localcustomers by replication stamp: ' + ', '.join(f'{k}={v}' for k, v in prof.most_common()))
        late = [(p, c) for p, c in hq.items() if c['st_time'] and (c['dumped'] is None or c['st_time'] > c['dumped'])]
        self._emit(f'  codes whose status changed AFTER their last ship (a change that cannot have replicated): {len(late)}')
        for p, c in sorted(late)[:self.samples]:
            self._emit(f'    {p}: status={c["status"]!r} changed={c["st_time"]} last_shipped={c["dumped"]}')
        _, r = self._q(self.hq, f'SELECT count(*), sum(case when table_dumped is null then 1 else 0 end) '
                                f'FROM {DB}.localcustomerspoints')
        self._emit(f'  HQ localcustomerspoints: {r[0][0]} rows · never shipped (NULL) {r[0][1]}')

    def s_side(self):
        for t in SIDE_TABLES:
            _, cols = self._q(self.hq, f"SELECT c.name FROM {DB}.syscolumns c, {DB}.sysobjects o "
                                       "WHERE o.name = ? AND o.type = 'U' AND c.id = o.id ORDER BY c.colid", [t])
            cols = [_s(c[0]) for c in cols]
            if not cols:
                self._emit(f'  {t}: (not found)')
                continue
            _, n = self._q(self.hq, f'SELECT count(*) FROM {DB}.{t}')
            self._emit(f'  {t}: {n[0][0]} rows · {", ".join(cols)}')
            safe = [c for c in cols if not any(w in c.lower() for w in ('name', 'address', 'phone', 'mobile', 'email', 'picid'))]
            if n[0][0] and safe:
                order = ' ORDER BY trans_time DESC' if 'trans_time' in cols else ''
                cn, rows = self._q(self.hq, f'SELECT {", ".join(safe[:14])} FROM {DB}.{t}{order}', limit=3)
                for r in rows:
                    self._emit('    ' + str(dict(zip(cn, r))))
        _, rows = self._q(self.hq,
                          f"SELECT DISTINCT o.name, o.type FROM {DB}.sysobjects o, {DB}.syscomments c WHERE c.id = o.id "
                          "AND o.type IN ('P','TR','V') AND (c.text LIKE '%set phcode%' OR c.text LIKE '%set pphcode%' "
                          "OR c.text LIKE '%phcode = @new%' OR c.text LIKE '%phcode=@new%' OR c.text LIKE '%oldphcode%' "
                          "OR c.text LIKE '%newphcode%')")
        self._emit('  procs/triggers/views that rewrite a phcode: '
                   + (', '.join(f'{_s(a)}({_s(b)})' for a, b in rows) or 'none readable → the code change lives in the '
                      'SOFTECH client (capture it with capture_save_sql while staff change one code)'))

    # ── --explain ─────────────────────────────────────────────────────────────
    def _points_profile(self, conn, pic):
        _, r = self._q(conn, f'SELECT count(*), sum(case when points > 0 then points else 0 end), '
                             f'sum(case when points < 0 then -points else 0 end), max(transdate) '
                             f'FROM {DB}.picpoints WHERE phcode = ?', [pic])
        n, plus, minus, last = r[0]
        _, d = self._q(conn, f'SELECT doccode, count(*), sum(points) FROM {DB}.picpoints WHERE phcode = ? '
                             'GROUP BY doccode ORDER BY 2 DESC', [pic], limit=6)
        _, e = self._q(conn, f'SELECT totpointsold, conpointsold, totpoints, conpoints, branchcode, usercode, trans_time '
                             f'FROM {DB}.lcpointstrans WHERE phcode = ? ORDER BY trans_time DESC', [pic], limit=2)
        _, b = self._q(conn, f'SELECT totpoints, conpoints FROM {DB}.localcustomerspoints WHERE phcode = ?', [pic])
        bal = f'{b[0][0]}−{b[0][1]}' if b else 'none'
        return (f'balance {bal} · log {n} rows earned {plus or 0} used {minus or 0} last {last} · by doc '
                + ', '.join(f'{_s(x)}:{c}/{t}' for x, c, t in d)
                + ' · manual edits ' + ('; '.join(f'{a}/{c}→{t}/{u} at {br} by {us} {tt}' for a, c, t, u, br, us, tt in e)
                                         or 'none'))

    def s_explain(self):
        """Why do balances differ? For a few mismatched codes per node: the points log and the manual
        points edits (lcpointstrans) on BOTH sides."""
        from config.sybase import get_branch_connection
        for n in self.nodes:
            rows = n.get('bal_diff') or []
            if not rows:
                continue
            rows = sorted(rows, key=lambda r: -abs(r[2] - r[1]))[:self.samples]
            self._emit(f'  {n["label"]}:')
            conn = get_branch_connection(n['host'], n['port'], 'SOFTECHDB9')
            try:
                for pic, ba, bb in rows:
                    self._emit(f'    {pic} (HQ {ba} / node {bb}, created at {self.hq_cust[pic]["branch"]})')
                    for side, c in (('HQ  ', self.hq), ('node', conn)):
                        try:
                            self._emit(f'      {side}: {self._points_profile(c, pic)}')
                        except Exception as exc:
                            self._emit(f'      {side}: (skipped — {str(exc)[:80]})')
            finally:
                conn.close()

    def s_native(self):
        """SOFTECH's own merge (localcustomers2: phcode ← sourcepic + sourcepicpoints, mgmdate) and
        PIC-edit log (picstrans: phcode→phcode2, pphcode→pphcode2) on HQ and every node."""
        from config.sybase import get_branch_connection
        sides = [('HQ', None)] + [(n['label'], n) for n in self.nodes if not n.get('error')]
        for label, n in sides:
            conn = self.hq if n is None else get_branch_connection(n['host'], n['port'], 'SOFTECHDB9')
            try:
                out = []
                for t, sql in (
                        ('localcustomers2 (merge)', f'SELECT count(*), max(mgmdate) FROM {DB}.localcustomers2'),
                        ('picstrans (PIC edits)', f'SELECT count(*), max(trans_time) FROM {DB}.picstrans'),
                        ('picstrans code changes', f"SELECT count(*), max(trans_time) FROM {DB}.picstrans "
                                                   "WHERE phcode <> phcode2 OR isnull(pphcode,'') <> isnull(pphcode2,'')"),
                        ('lcpointstrans (points edits)', f'SELECT count(*), max(trans_time) FROM {DB}.lcpointstrans')):
                    try:
                        _, r = self._q(conn, sql)
                        out.append(f'{t} {r[0][0]} (last {r[0][1]})')
                    except Exception as exc:
                        out.append(f'{t} ? ({str(exc)[:50]})')
                self._emit(f'  {label}: ' + ' · '.join(out))
                for t, sql in (
                        ('merge', f'SELECT phcode, sourcepic, sourcepicpoints, usercode, trans_time, mgmdate '
                                  f'FROM {DB}.localcustomers2 ORDER BY trans_time DESC'),
                        ('code change', f'SELECT phcode, phcode2, pphcode, pphcode2, phcodestatus, piclock, picpoints, '
                                        f'usercode, trans_time, branchcode FROM {DB}.picstrans WHERE phcode <> phcode2 '
                                        "OR isnull(pphcode,'') <> isnull(pphcode2,'') ORDER BY trans_time DESC")):
                    try:
                        cn, rows = self._q(conn, sql, limit=self.samples)
                    except Exception:
                        continue
                    for r in rows:
                        self._emit(f'      {t}: ' + str({c: v for c, v in zip(cn, r)}))
            finally:
                if n is not None:
                    conn.close()

    # ── run ───────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_branch_connection, get_sybase_connection
        self._buf, self.samples = [], o['samples']
        self.pics = [p.strip() for p in o['pic'] if p.strip()]
        if o['host']:
            targets = [(h, o['port'], h) for h in o['host']]
        else:
            from apps.branches.models import Branch
            targets = [(b.db_host, b.db_port or 5000, f'{b.softech_branch_id} ({b.db_host})')
                       for b in Branch.objects.filter(is_operational=True).exclude(softech_branch_id='100')
                       .exclude(db_host='').exclude(db_host__isnull=True).order_by('softech_branch_id')]
        self._emit('=' * 72)
        self._emit(f'SOFTECH PIC REPLICATION PROBE (read-only) — HQ vs {len(targets)} node(s)')
        self._emit('=' * 72)
        self.hq = get_sybase_connection()
        try:
            self.hq_cust, self.hq_pts = self._load(self.hq)
            self._emit(f'  HQ: {len(self.hq_cust)} customers · {len(self.hq_pts)} balance rows')
            self.nodes = []
            for host, port, label in targets:
                n = {'label': label, 'host': host, 'port': port}
                try:
                    conn = get_branch_connection(host, port, 'SOFTECHDB9')
                    try:
                        _, own = self._q(conn, f"SELECT branchcode FROM {DB}.lastdocnumbers WHERE ver_branch = '1'")
                        n['own'] = _s(own[0][0]) if own else ''
                        n['cust'], n['pts'] = self._load(conn)
                    finally:
                        conn.close()
                except Exception as exc:
                    n['error'] = str(exc)[:160]
                self.nodes.append(n)
            self._safe('[R1] nodes', self.s_nodes)
            self._safe('[R2] non-active / locked codes on every node', self.s_trace)
            self._safe('[R3] HQ vs node mismatches', self.s_diff)
            self._safe('[R4] HQ replication stamps (table_dumped)', self.s_stamps)
            self._safe('[R5] SOFTECH code-change / parent / points-edit tables', self.s_side)
            if o['explain']:
                self._safe('[R6] SOFTECH native merge / PIC edits on every node', self.s_native)
                self._safe('[R7] why balances differ (largest gaps, both sides)', self.s_explain)
        finally:
            self.hq.close()
        if o['out']:
            os.makedirs(os.path.dirname(o['out']) or '.', exist_ok=True)
            with open(o['out'], 'w', encoding='utf-8') as f:
                f.write('\n'.join(self._buf) + '\n')
            self.stdout.write(self.style.SUCCESS(f'\nWritten to {o["out"]}'))
