"""
READ-ONLY SOFTECH probe for doc 37 Phase 2 — can we pull only what CHANGED?

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
 [2b] when HQ stock changes arrive (one timestamp per batch → the batch rhythm)
 [3] stkbal read twice, --watch minutes apart: every row whose QUANTITY changed
     must also carry a newer modif_lastupdate             ← decides step 2.1
     (HQ stock follows the branches in batches, so a sale minutes ago may not be
      at HQ yet — comparing against sale times is not a fair test; this is.)
 [4] stktrans — late lines: rows dated yesterday that were written today  ← step 2.2
 [5] items.itemlastupdate — coverage, and price changes since our last sync
     that did NOT bump it                                                  ← step 2.3
 [6] localcustomers — every date column: coverage and recency
 [6b] customers whose SOFTECH flags differ from our copy (= changed since our
      last customer sync): did each one get a newer trans_time?         ← step 2.3

    --watch 15     minutes between the two stock reads in [3] (0 = no wait)
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
    help = 'READ-ONLY: check SOFTECH change-time columns before switching syncs to delta pulls (doc 37 Phase 2).'

    def add_arguments(self, parser):
        parser.add_argument('--out', default='scratch/softech_change_columns_probe.txt',
                            help='also write the report here (scratch/ is git-ignored)')
        parser.add_argument('--keys', type=int, default=3000,
                            help='max (item, branch, store) stock rows watched in [3]')
        parser.add_argument('--watch', type=int, default=15,
                            help='minutes between the two stock reads in [3] (0 = no wait)')
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

    def s_batches(self):
        rows = self._q(
            f"SELECT modif_lastupdate, COUNT(*) FROM {DB}.stkbal "
            f"WHERE modif_lastupdate >= DATEADD(hour, -3, GETDATE()) "
            f"GROUP BY modif_lastupdate ORDER BY modif_lastupdate DESC", limit=200)
        if not rows:
            self._emit('  no stock changes at HQ in the last 3 hours')
            return
        stamps = sorted(r[0] for r in rows if r[0])
        self._emit(f'  distinct change times in the last 3 h: {len(rows)}   rows: {sum(r[1] for r in rows):,}')
        for t, n in rows[:15]:
            self._emit(f'    {t}  {n:6,} rows')
        gaps = sorted((b - a).total_seconds() / 60 for a, b in zip(stamps, stamps[1:]))
        if gaps:
            self._emit(f'  gap between change times: median {gaps[len(gaps) // 2]:.1f} min, max {gaps[-1]:.1f} min')
        self._emit('  → few distinct times with many rows each = stock arrives at HQ in batches')

    def _stock_rows(self, keys):
        """{(item, branch, store): (nowqty, modif_lastupdate)} for the given keys."""
        by_branch = defaultdict(set)
        for k in keys:
            by_branch[k[1]].add(k[0])
        out = {}
        for br, items in by_branch.items():
            items = sorted(items)
            for i in range(0, len(items), 200):
                chunk = items[i:i + 200]
                ph = ','.join('?' * len(chunk))
                for item, store, qty, mod in self._q(
                        f"SELECT itemcode, storecode, nowqty, modif_lastupdate FROM {DB}.stkbal "
                        f"WHERE branchcode = ? AND itemcode IN ({ph})", [br, *chunk]):
                    out[(str(item).strip(), br, str(store).strip())] = (qty, mod)
        return out

    def s_stkbal_watch(self):
        import time
        today = datetime.date.today().isoformat()
        keys = set()
        for item, br, store in self._q(
                f"SELECT itemcode, branchcode, storecode FROM {DB}.stkbal "
                f"WHERE modif_lastupdate >= DATEADD(day, -1, GETDATE())", limit=self.opts['keys']):
            keys.add((str(item).strip(), str(br).strip(), str(store).strip()))
        for item, br, store in self._q(
                f"SELECT DISTINCT st.itemcode, st.branchcode, st.storecode FROM {DB}.stktrans st "
                f"WHERE st.docdate >= ?", [today], limit=self.opts['keys']):
            keys.add((str(item).strip(), str(br).strip(), str(store).strip()))
        keys = sorted(keys)[:self.opts['keys']]
        if not keys:
            self._emit('  nothing moved in the last day — run again during working hours')
            return
        first = self._stock_rows(keys)
        mins = max(0, self.opts['watch'])
        self._emit(f'  watching {len(first):,} stock rows (changed in the last 24 h or moved today); '
                   f'second read in {mins} min …')
        if mins:
            self.stdout.write('  (waiting — leave this window open)')
            time.sleep(mins * 60)
        second = self._stock_rows(keys)
        good = bad = touched = 0
        samples = []
        for k, (q1, m1) in first.items():
            if k not in second:
                continue
            q2, m2 = second[k]
            qty_changed = (q1 or 0) != (q2 or 0)
            mod_changed = (m1 != m2)
            if qty_changed and mod_changed:
                good += 1
            elif qty_changed:
                bad += 1
                if len(samples) < self.opts['samples']:
                    samples.append(f'    item {k[0]} branch {k[1]} store {k[2]}: qty {q1} → {q2} '
                                   f'but modif_lastupdate stayed {m1}')
            elif mod_changed:
                touched += 1
        self._emit(f'  quantity changed WITH a newer modif_lastupdate   : {good:,}')
        self._emit(f'  quantity changed WITHOUT a newer modif_lastupdate: {bad:,}')
        self._emit(f'  modif_lastupdate moved, quantity the same        : {touched:,} (harmless)')
        if good + bad == 0:
            self._emit('  → no quantity changed during the window — run with a longer --watch in busy hours')
        elif bad == 0:
            self._emit(f'  → ✅ every quantity change ({good}) carried a new modif_lastupdate — safe to pull stock by it')
        else:
            self._emit('  → ⚠️ some quantity changes did NOT move modif_lastupdate — stock must stay a full read')
        for x in samples:
            self._emit(x)

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
        synced = self._last_sync_start('items')
        if synced is None:
            self._emit('  (no successful item sync recorded here — price cross-check skipped)')
            return
        self._emit(f'  our last item sync started: {synced}')
        mirror = {i.softech_id: float(i.pack_price or 0) for i in Item.objects.only('softech_id', 'pack_price')}
        diff, bumped, samples = 0, 0, []
        for code, price, upd in self._q(f"SELECT itemcode, itemsaleprice, itemlastupdate FROM {DB}.items"):
            m = mirror.get(str(code).strip())
            if m is None or price is None or abs(float(price) - m) < 0.005:
                continue
            diff += 1
            if upd and upd >= synced - datetime.timedelta(minutes=5):
                bumped += 1
            elif len(samples) < self.opts['samples']:
                samples.append(f'    item {code}: ours {m} → SOFTECH {price}, itemlastupdate {upd}')
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

    def _last_sync_start(self, table):
        """Local (server-time) start of our last successful sync run that logged `table`.
        (Item.last_synced is not refreshed by the bulk upsert, so it cannot be used.)"""
        from apps.sync.models import SyncLog
        log = (SyncLog.objects.filter(table_name=table, sync_run__status='success')
               .select_related('sync_run').order_by('-sync_run__started_at').first())
        if not log:
            return None
        # SOFTECH datetimes are server-local (Cairo); ours are aware — compare in local time
        return timezone.localtime(log.sync_run.started_at).replace(tzinfo=None)

    def s_customers_vs_mirror(self):
        from apps.customers.models import Customer
        synced = self._last_sync_start('items')   # customers run right after items in the slow lane
        if synced is None:
            self._emit('  (no successful slow sync recorded here — skipped)')
            return
        self._emit(f'  our last customer sync started about: {synced}')
        ours = {c['softech_pic']: (c['softech_status'], c['softech_locked'], c['softech_deceased'],
                                   c['points_enrolled'])
                for c in Customer.objects.exclude(softech_pic__isnull=True).exclude(softech_pic='')
                .values('softech_pic', 'softech_status', 'softech_locked', 'softech_deceased',
                        'points_enrolled')}
        rows = defaultdict(list)
        for pic, st, lock, died, pts, tt in self._q(
                f"SELECT phcode, phcodestatus, piclock, picdied, picpoints, trans_time "
                f"FROM {DB}.localcustomers WHERE phcode IS NOT NULL AND phcode != ''"):
            pic = str(pic).strip()
            # same conversions as sync_customers, so an unchanged customer compares equal
            rows[pic].append(((str(st or '').strip()[:2], bool(lock), bool(died), bool(pts)), tt))
        changed = bumped = 0
        samples = []
        for pic, variants in rows.items():
            mine = ours.get(pic)
            if mine is None or any(v == mine for v, _ in variants):
                continue                     # unknown to us, or one SOFTECH copy still matches ours
            changed += 1
            newest = max((t for _, t in variants if t), default=None)
            if newest and newest >= synced - datetime.timedelta(minutes=5):
                bumped += 1
            elif len(samples) < self.opts['samples']:
                samples.append(f'    {pic}: ours {mine} → SOFTECH {variants[0][0]}, newest trans_time {newest}')
        self._emit(f'  customers whose flags changed since our last sync: {changed} — trans_time newer: {bumped}')
        self._emit('  → ' + ('no flag changes to test right now — run again later in the day' if not changed else
                            ('✅ every flag change moved trans_time — candidate change marker' if bumped == changed
                             else '⚠️ some flag changes did NOT move trans_time — see samples')))
        for x in samples:
            self._emit(x)

    # ── entry ─────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_sybase_connection
        self.opts, self._buf = o, []
        self._emit(f'SOFTECH change-column probe — {datetime.datetime.now():%Y-%m-%d %H:%M} (READ-ONLY)')
        self.conn = get_sybase_connection()
        try:
            self._safe('[1] date/time columns', self.s_columns)
            self._safe('[2] stkbal.modif_lastupdate', self.s_stkbal)
            self._safe('[2b] when stock changes arrive at HQ', self.s_batches)
            self._safe('[4] stktrans late lines (yesterday written today)', self.s_late_lines)
            self._safe('[5] items.itemlastupdate', self.s_items)
            self._safe('[6] localcustomers date columns', self.s_customers)
            self._safe('[6b] customers changed since our last sync', self.s_customers_vs_mirror)
            # last: it waits --watch minutes between its two reads
            self._safe('[3] stock rows read twice, --watch minutes apart', self.s_stkbal_watch)
        finally:
            self.conn.close()
        if o['out']:
            os.makedirs(os.path.dirname(o['out']) or '.', exist_ok=True)
            with open(o['out'], 'w', encoding='utf-8') as f:
                f.write('\n'.join(self._buf) + '\n')
            self.stdout.write(self.style.SUCCESS(f'\nWritten to {o["out"]}'))
