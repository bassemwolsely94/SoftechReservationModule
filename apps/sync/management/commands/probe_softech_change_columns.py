"""
READ-ONLY SOFTECH probe for doc 30 Phase 2 — can we pull only what CHANGED?

Before the stock / sales / items / customers syncs switch from "read everything"
to "read what changed since last time", we must know whether SOFTECH keeps its
change-time columns up to date. This probe answers that from live data. Only
SELECTs (plus SET ROWCOUNT to bound samples). No customer names or phones are
printed, so the report can be shared.

    python manage.py probe_softech_change_columns
    python manage.py probe_softech_change_columns --out scratch/softech_change_columns_probe.txt

Run it during working hours (so today has sales / transfers to test against),
ideally once in the morning and once in the afternoon.

Sections:
 [1] date/time columns on the tables the syncs read
 [2] stkbal.modif_lastupdate — coverage and recency
 [3] stkbal vs today's movements — is modif_lastupdate bumped by every movement
     type (sale, return, transfer, purchase …)?   ← decides step 2.1
 [4] stktrans — late lines: rows dated yesterday that were written today  ← step 2.2
 [5] items.itemlastupdate — coverage, and price changes since our last sync
     that did NOT bump it                                                  ← step 2.3
 [6] localcustomers — every date column: coverage and recency; new codes   ← step 2.3
"""
import datetime
import os
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

DB = 'SOFTECHDB9.dbo'
TABLES = ('stkbal', 'stktrans', 'stktransm', 'items', 'itembarcode', 'localcustomers', 'personsdata')
DOC_NAMES = {'115': 'بيع', '30': 'مرتجع بيع', '125': 'صرف تبادل', '25': 'استلام تبادل',
             '10': 'شراء', '20': 'مرتجع شراء', '50': 'فائض جرد', '150': 'عجز جرد'}


class Command(BaseCommand):
    help = 'READ-ONLY: check SOFTECH change-time columns before switching syncs to delta pulls (doc 30 Phase 2).'

    def add_arguments(self, parser):
        parser.add_argument('--out', default='scratch/softech_change_columns_probe.txt',
                            help='also write the report here (scratch/ is git-ignored)')
        parser.add_argument('--keys', type=int, default=400,
                            help='max (item, branch, store) keys moved today to test in [3]')
        parser.add_argument('--samples', type=int, default=10)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _emit(self, line=''):
        self.stdout.write(str(line))
        self._buf.append(str(line))

    def _q(self, sql, params=None, limit=None):
        cur = self.conn.cursor()
        try:
            if limit:
                cur.execute(f'SET ROWCOUNT {int(limit)}')
            cur.execute(sql, params or [], timeout=300)
            return cur.fetchall()
        finally:
            if limit:
                try:
                    cur.execute('SET ROWCOUNT 0')
                except Exception:
                    pass

    def _safe(self, title, fn):
        self._emit('')
        self._emit(f'── {title} ' + '─' * max(0, 70 - len(title)))
        try:
            fn()
        except Exception as exc:
            self._emit(f'  ! failed: {str(exc)[:300]}')

    @staticmethod
    def _pct(a, b):
        return f'{(100.0 * a / b):.1f}%' if b else '—'

    def _date_columns(self, table):
        rows = self._q(
            f"SELECT c.name, t.name FROM {DB}.syscolumns c, {DB}.systypes t, {DB}.sysobjects o "
            "WHERE o.name = ? AND o.type = 'U' AND c.id = o.id AND c.usertype = t.usertype ORDER BY c.colid",
            [table])
        return [r[0] for r in rows if str(r[1]).lower() in ('datetime', 'smalldatetime', 'date', 'time', 'timestamp')]

    # ── sections ──────────────────────────────────────────────────────────────
    def s_columns(self):
        self.datecols = {}
        for t in TABLES:
            cols = self._date_columns(t)
            self.datecols[t] = cols
            self._emit(f'  {t:16s} {", ".join(cols) or "(none)"}')

    def s_stkbal(self):
        r = self._q(
            f"SELECT COUNT(*), SUM(CASE WHEN modif_lastupdate IS NULL THEN 1 ELSE 0 END), "
            f"MIN(modif_lastupdate), MAX(modif_lastupdate), "
            f"SUM(CASE WHEN modif_lastupdate >= DATEADD(hour, -1, GETDATE()) THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN modif_lastupdate >= DATEADD(day, -1, GETDATE()) THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN modif_lastupdate >= DATEADD(day, -7, GETDATE()) THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN nowqty > 0 THEN 1 ELSE 0 END), GETDATE() "
            f"FROM {DB}.stkbal")[0]
        total, nulls, lo, hi, h1, d1, d7, pos, now = r
        self.server_now = now
        self._emit(f'  server time now      : {now}')
        self._emit(f'  rows                 : {total:,}   (nowqty > 0: {pos:,} — what the 5-min sync reads today)')
        self._emit(f'  modif_lastupdate NULL: {nulls:,} ({self._pct(nulls, total)})')
        self._emit(f'  oldest / newest      : {lo}  /  {hi}')
        self._emit(f'  changed last 1 h     : {h1:,}')
        self._emit(f'  changed last 24 h    : {d1:,}')
        self._emit(f'  changed last 7 days  : {d7:,}')
        self._emit(f'  → a delta pull every 5 min would read ~{(h1 or 0) // 12:,} rows instead of {pos:,}')

    def s_stkbal_vs_moves(self):
        today = datetime.date.today().isoformat()
        moves = self._q(
            f"SELECT st.itemcode, st.branchcode, st.storecode, st.doccode, MAX(st.trans_time) "
            f"FROM {DB}.stktrans st WHERE st.docdate >= ? "
            f"GROUP BY st.itemcode, st.branchcode, st.storecode, st.doccode",
            [today], limit=self.opts['keys'] * 3)
        if not moves:
            self._emit('  no stktrans lines dated today yet — run again during working hours')
            return
        latest = {}                       # key -> (max trans_time, set of doccodes)
        for item, br, store, dc, tt in moves:
            k = (str(item).strip(), str(br).strip(), str(store).strip())
            prev = latest.get(k, (None, set()))
            t = tt if (prev[0] is None or (tt and tt > prev[0])) else prev[0]
            latest[k] = (t, prev[1] | {str(dc).strip()})
        keys = list(latest)[:self.opts['keys']]
        by_branch = defaultdict(list)
        for k in keys:
            by_branch[k[1]].append(k)
        bal = {}
        for br, ks in by_branch.items():
            items = sorted({k[0] for k in ks})
            for i in range(0, len(items), 200):
                chunk = items[i:i + 200]
                ph = ','.join('?' * len(chunk))
                for item, store, mod in self._q(
                        f"SELECT itemcode, storecode, modif_lastupdate FROM {DB}.stkbal "
                        f"WHERE branchcode = ? AND itemcode IN ({ph})", [br, *chunk]):
                    bal[(str(item).strip(), br, str(store).strip())] = mod
        ok, stale, null, missing = Counter(), Counter(), Counter(), Counter()
        samples = []
        for k in keys:
            tt, dcs = latest[k]
            label = '+'.join(sorted(dcs))
            if k not in bal:
                missing[label] += 1
                continue
            mod = bal[k]
            if mod is None:
                null[label] += 1
            elif tt is None or mod >= tt - datetime.timedelta(minutes=1):
                ok[label] += 1
            else:
                stale[label] += 1
                if len(samples) < self.opts['samples']:
                    samples.append(f'    item {k[0]} branch {k[1]} store {k[2]} doc {label}: '
                                   f'moved {tt} but modif_lastupdate {mod}')
        self._emit(f'  keys moved today tested: {len(keys)}')
        self._emit(f'  {"doc codes":22s} {"bumped":>7s} {"NOT bumped":>11s} {"NULL":>6s} {"no stkbal row":>14s}')
        for label in sorted(set(ok) | set(stale) | set(null) | set(missing)):
            names = '+'.join(DOC_NAMES.get(d, d) for d in label.split('+'))
            self._emit(f'  {label:8s} {names[:13]:13s} {ok[label]:7d} {stale[label]:11d} {null[label]:6d} {missing[label]:14d}')
        total_ok, total = sum(ok.values()), len(keys) - sum(missing.values())
        self._emit(f'  → bumped on {total_ok}/{total} ({self._pct(total_ok, total)})'
                   + ('  ✅ safe to pull stock by modif_lastupdate' if total and total_ok == total
                      else '  ⚠️ NOT every movement bumps it — see samples'))
        for s in samples:
            self._emit(s)

    def s_late_lines(self):
        today = datetime.date.today()
        yday = (today - datetime.timedelta(days=1)).isoformat()
        r = self._q(
            f"SELECT st.doccode, COUNT(*), "
            f"SUM(CASE WHEN st.trans_time >= ? THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN st.trans_time IS NULL THEN 1 ELSE 0 END) "
            f"FROM {DB}.stktrans st WHERE st.docdate >= ? AND st.docdate < ? GROUP BY st.doccode",
            [today.isoformat(), yday, today.isoformat()])
        self._emit("  lines dated YESTERDAY: total / written after midnight (trans_time today) / no trans_time")
        for dc, n, late, nul in sorted(r, key=lambda x: -x[1]):
            dc = str(dc).strip()
            self._emit(f'    {dc:5s} {DOC_NAMES.get(dc, ""):12s} {n:8,}  late {late or 0:6,}  no-time {nul or 0:6,}')
        r = self._q(
            f"SELECT COUNT(*), SUM(CASE WHEN st.trans_time IS NULL THEN 1 ELSE 0 END), MAX(st.trans_time) "
            f"FROM {DB}.stktrans st WHERE st.docdate >= ? AND st.doccode IN ('115', '30')",
            [today.isoformat()])[0]
        self._emit(f'  sales/returns lines today: {r[0]:,}  without trans_time: {r[1] or 0:,}  latest: {r[2]}')
        self._emit('  → "late" > 0 means yesterday still changes after midnight: keep one morning re-pull of yesterday')

    def s_items(self):
        r = self._q(
            f"SELECT COUNT(*), SUM(CASE WHEN itemlastupdate IS NULL THEN 1 ELSE 0 END), MAX(itemlastupdate), "
            f"SUM(CASE WHEN itemlastupdate >= DATEADD(day, -1, GETDATE()) THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN itemlastupdate >= DATEADD(day, -7, GETDATE()) THEN 1 ELSE 0 END) FROM {DB}.items")[0]
        self._emit(f'  items: {r[0]:,}  itemlastupdate NULL: {r[1] or 0:,} ({self._pct(r[1] or 0, r[0])})  newest: {r[2]}')
        self._emit(f'  changed last 24 h: {r[3] or 0:,}   last 7 days: {r[4] or 0:,}')
        from apps.catalog.models import Item
        mirror = {i.softech_id: (float(i.pack_price or 0), i.last_synced)
                  for i in Item.objects.only('softech_id', 'pack_price', 'last_synced')}
        if not mirror:
            self._emit('  (our catalog mirror is empty — price cross-check skipped)')
            return
        diff, bumped, samples = 0, 0, []
        for code, price, upd in self._q(f"SELECT itemcode, itemsaleprice, itemlastupdate FROM {DB}.items"):
            m = mirror.get(str(code).strip())
            if not m or price is None or abs(float(price) - m[0]) < 0.005:
                continue
            diff += 1
            # SOFTECH datetimes are server-local (Cairo); ours are aware — compare in local time
            synced = timezone.localtime(m[1]).replace(tzinfo=None) if m[1] else None
            if upd and synced and upd >= synced - datetime.timedelta(minutes=5):
                bumped += 1
            elif len(samples) < self.opts['samples']:
                samples.append(f'    item {code}: ours {m[0]} → SOFTECH {price}, itemlastupdate {upd}, our last sync {m[1]}')
        self._emit(f'  price changed in SOFTECH since our last item sync: {diff}  — itemlastupdate bumped: {bumped}')
        self._emit('  → ' + ('✅ price changes bump itemlastupdate' if diff and bumped == diff else
                            ('no price changes to test right now — run again after a price update' if not diff
                             else '⚠️ some price changes did NOT bump itemlastupdate — see samples')))
        for s in samples:
            self._emit(s)

    def s_customers(self):
        cols = self.datecols.get('localcustomers') or []
        r = self._q(f"SELECT COUNT(*) FROM {DB}.localcustomers")[0]
        self._emit(f'  rows: {r[0]:,}')
        for c in cols:
            x = self._q(
                f"SELECT SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END), MAX({c}), "
                f"SUM(CASE WHEN {c} >= DATEADD(day, -1, GETDATE()) THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN {c} >= DATEADD(day, -7, GETDATE()) THEN 1 ELSE 0 END) FROM {DB}.localcustomers")[0]
            self._emit(f'  {c:22s} NULL {x[0] or 0:8,} ({self._pct(x[0] or 0, r[0])})  newest {x[1]}  '
                       f'last 24 h {x[2] or 0:6,}  last 7 d {x[3] or 0:7,}')
        from apps.customers.models import Customer
        ours = Customer.objects.count()
        self._emit(f'  our mirror: {ours:,} customers (SOFTECH {r[0]:,})')
        self._emit('  → a column that is (almost) never NULL and moves daily is a candidate change marker; '
                   'otherwise customers stay full-nightly + new-codes-hourly')

    # ── entry ─────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_sybase_connection
        self.opts, self._buf = o, []
        self._emit(f'SOFTECH change-column probe — {datetime.datetime.now():%Y-%m-%d %H:%M} (READ-ONLY)')
        self.conn = get_sybase_connection()
        try:
            self._safe('[1] date/time columns', self.s_columns)
            self._safe('[2] stkbal.modif_lastupdate', self.s_stkbal)
            self._safe('[3] stkbal vs today\'s movements', self.s_stkbal_vs_moves)
            self._safe('[4] stktrans late lines (yesterday written today)', self.s_late_lines)
            self._safe('[5] items.itemlastupdate', self.s_items)
            self._safe('[6] localcustomers date columns', self.s_customers)
        finally:
            self.conn.close()
        if o['out']:
            os.makedirs(os.path.dirname(o['out']) or '.', exist_ok=True)
            with open(o['out'], 'w', encoding='utf-8') as f:
                f.write('\n'.join(self._buf) + '\n')
            self.stdout.write(self.style.SUCCESS(f'\nWritten to {o["out"]}'))
