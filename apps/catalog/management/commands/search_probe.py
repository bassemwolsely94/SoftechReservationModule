"""
search_probe — the item-search golden corpus (apps/catalog/search_corpus.py) on the REAL catalog,
through every search path, with timings. Run before and after each search batch.

    python manage.py search_probe                       # 3 timed runs per query and path
    python manage.py search_probe --repeat 5 --json out.json
    python manage.py search_probe --with-temp-indexes   # dev DB without catalog 0044/0045

Paths (in-process, APIRequestFactory as an existing superuser — no server needed):
  A  /api/items/softech-search/?no_live=1   (the POS / pickers endpoint)
  B  /api/items/?search=                    (item list)            — report-only until S2
  C  /api/search/universal?types=items      (Ctrl+K)               — report-only until S2
  D  wildcard.item_search(q)                (the engine itself)

Exit code 1 when a corpus entry fails on A or D, or D's p95 is over BUDGET_MS. The time budget
is only judged when the folded-name indexes (catalog 0044 + 0045) exist — without them the
timings mean nothing, and the probe says so loudly. Entries marked `real_report_only` (the real
catalog lacks the data) are printed but never fail the run.

Read-only: everything runs in ONE transaction that is always rolled back. --with-temp-indexes
creates the 0044/0045 indexes inside that transaction (rolled back with it, never committed). Note
CREATE INDEX holds a SHARE lock on catalog_item until the run ends: catalog writes (the item
sync) wait for it — a minute or two.
"""
import importlib
import json
import math
import re
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

BUDGET_MS = 40
PATHS = ('A', 'B', 'C', 'D')
GATED = ('A', 'D')                      # B and C are report-only until S2
LABELS = {'A': 'softech-search no_live', 'B': 'items ?search=', 'C': 'universal items',
          'D': 'item_search()'}
INDEX_MIGRATIONS = ('apps.catalog.migrations.0044_folded_name_trgm',
                    'apps.catalog.migrations.0045_folded_name_prefix')


def index_sql() -> list:
    """The CREATE INDEX statements of catalog 0044 + 0045 (same SQL, so the same index names)."""
    sql = []
    for mod in INDEX_MIGRATIONS:
        sql += importlib.import_module(mod).SQL
    return sql


def index_names() -> list:
    return [re.search(r'CREATE INDEX IF NOT EXISTS (\w+)', s).group(1) for s in index_sql()]


def missing_indexes() -> list:
    names = index_names()
    with connection.cursor() as c:
        c.execute('SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)', [names])
        have = {r[0] for r in c.fetchall()}
    return [n for n in names if n not in have]


def pct(xs, p) -> float:
    """Nearest-rank percentile; 0 for no samples."""
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[max(0, math.ceil(p * len(s)) - 1)]


class Command(BaseCommand):
    help = 'Item-search golden corpus on the real catalog: pass/fail and p50/p95 ms per search path (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--repeat', type=int, default=3, help='Timed runs per query and path (default 3).')
        parser.add_argument('--json', dest='json_path', default='', help='Write every query result to this JSON file.')
        parser.add_argument('--with-temp-indexes', action='store_true',
                            help='Create the catalog 0044/0045 indexes for this run only (always rolled back).')

    def handle(self, *args, **opts):
        user = (get_user_model().objects.filter(is_superuser=True, is_active=True).order_by('id').first())
        if user is None:
            raise CommandError('search_probe needs an active superuser to call the endpoints as.')
        repeat = max(1, opts['repeat'])
        with transaction.atomic():
            try:
                missing = missing_indexes()
                if opts['with_temp_indexes'] and missing:
                    with connection.cursor() as c:
                        for name, s in zip(index_names(), index_sql()):
                            if name in missing:
                                c.execute(s)
                        c.execute('ANALYZE catalog_item')
                    self.stdout.write('temporary indexes created (rolled back at the end): ' + ', '.join(missing))
                    missing = missing_indexes()
                elif opts['with_temp_indexes']:
                    self.stdout.write('the catalog 0044/0045 indexes already exist — nothing to create')
                records = self._run(user, repeat)
            finally:
                transaction.set_rollback(True)          # read-only: nothing this run did is kept
        failed = self._report(records, missing, repeat)
        if opts['json_path']:
            with open(opts['json_path'], 'w', encoding='utf-8') as f:
                json.dump({'missing_indexes': missing, 'repeat': repeat, 'records': records}, f,
                          ensure_ascii=False, indent=1)
            self.stdout.write(f'JSON written to {opts["json_path"]}')
        if failed:
            raise CommandError('search_probe: ' + '; '.join(failed))

    # ── running ────────────────────────────────────────────────────────────────
    def _run(self, user, repeat) -> list:
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.catalog.models import Item
        from apps.catalog.search_corpus import CORPUS, check
        from apps.catalog.search_views import universal_search_view
        from apps.catalog.views import ItemViewSet
        from apps.catalog.wildcard import item_search
        from apps.shortage.phonetic import warm_search_index

        factory = APIRequestFactory(SERVER_NAME='localhost')
        softech = ItemViewSet.as_view({'get': 'softech_search'})
        listing = ItemViewSet.as_view({'get': 'list'})

        def view_rows(view, url, params):
            req = factory.get(url, params)
            force_authenticate(req, user=user)
            resp = view(req)
            data = resp.data
            rows = data.get('results') if isinstance(data, dict) else data
            if isinstance(rows, dict):                  # universal: {'items': [...], ...}
                rows = rows.get('items', [])
            return [(r.get('name'), r.get('tier')) for r in (rows or [])]

        calls = {
            'A': lambda q: view_rows(softech, '/api/items/softech-search/', {'q': q, 'no_live': '1'}),
            'B': lambda q: view_rows(listing, '/api/items/', {'search': q, 'page_size': 10}),
            'C': lambda q: view_rows(universal_search_view, '/api/search/universal',
                                     {'q': q, 'types': 'items', 'limit': 8}),
            'D': item_search,
        }
        warm_search_index()
        records = []
        for e in CORPUS:
            rec = {'q': e['q'], 'expect': e['expect'], 'top': e.get('top', 1), 'tier': e.get('tier'),
                   'note': e.get('note', ''), 'report_only': bool(e.get('real_report_only')), 'paths': {}}
            for p in PATHS:
                out, times, err = None, [], ''
                for k in range(repeat + 1):              # run 0 warms up, untimed
                    try:
                        with transaction.atomic():       # a failing call can't poison the run
                            t = time.perf_counter()
                            res = calls[p](e['q'])
                            ms = (time.perf_counter() - t) * 1000
                    except Exception as ex:              # reported per path; the run goes on
                        err = f'{type(ex).__name__}: {ex}'[:200]
                        break
                    if k:
                        times.append(round(ms, 2))
                    out = res
                if p == 'D' and out is not None:
                    names = dict(Item.objects.filter(id__in=[i for i, _ in out[:5]]).values_list('id', 'name'))
                    out = [(names.get(i), t) for i, t in out]
                rows = out or []
                # B and C carry no tier: judged on the name only
                ok = (not err) and check(e if p in GATED else dict(e, tier=None), rows)
                rec['paths'][p] = {'ok': ok, 'ms': times, 'top': rows[:5], 'error': err}
            records.append(rec)
        return records

    # ── reporting ──────────────────────────────────────────────────────────────
    def _report(self, records, missing, repeat) -> list:
        w = self.stdout.write
        w('')
        w(f'{"query":28} ' + ' '.join(f'{p:>4}' for p in PATHS) + '   D ms (p50)')
        for r in records:
            flags = ' '.join(f'{("ok" if r["paths"][p]["ok"] else "FAIL"):>4}' for p in PATHS)
            mark = '  (report-only here)' if r['report_only'] else ''
            w(f'{r["q"]!r:28} {flags}   {pct(r["paths"]["D"]["ms"], 0.5):6.1f}{mark}')
        w('')
        w(f'Summary — {len(records)} queries × {repeat} timed runs (after one warm-up run)')
        w('| path | what | top-k pass | p50 ms | p95 ms | gate |')
        w('|---|---|---|---|---|---|')
        gated = [r for r in records if not r['report_only']]
        for p in PATHS:
            ms = [m for r in records for m in r['paths'][p]['ms']]
            ok = sum(1 for r in gated if r['paths'][p]['ok'])
            gate = ('pass + time' if p == 'D' else 'pass') if p in GATED else 'report-only'
            w(f'| {p} | {LABELS[p]} | {ok}/{len(gated)} | {pct(ms, 0.5):.1f} | {pct(ms, 0.95):.1f} | {gate} |')
        ro = [r for r in records if r['report_only']]
        for r in ro:
            w(f'report-only: {r["q"]!r} — A {"ok" if r["paths"]["A"]["ok"] else "not met"}, '
              f'top {r["paths"]["A"]["top"][:1]} ({r["note"]})')
        failed = []
        for p in GATED:
            bad = [r['q'] for r in gated if not r['paths'][p]['ok']]
            if bad:
                failed.append(f'path {p} failed {len(bad)}: {bad}')
        d_ms = [m for r in records for m in r['paths']['D']['ms']]
        p95 = pct(d_ms, 0.95)
        slow = sorted(((pct(r['paths']['D']['ms'], 0.5), r['q']) for r in records), reverse=True)
        slow = [(round(m, 1), q) for m, q in slow if m > BUDGET_MS]
        if slow:
            w(f'queries over {BUDGET_MS} ms (D, median): {slow}')
        if missing:
            w('')
            w('!' * 78)
            w(f'!! WARNING: indexes missing: {", ".join(missing)}')
            w('!! The engine is tuned WITH catalog 0044/0045 — these timings mean nothing and the')
            w(f'!! {BUDGET_MS} ms budget is NOT judged. Apply the migrations or use --with-temp-indexes.')
            w('!' * 78)
        elif p95 > BUDGET_MS:
            failed.append(f'item_search p95 {p95:.1f} ms > {BUDGET_MS} ms')
        w('')
        w('RESULT: ' + ('FAIL — ' + '; '.join(failed) if failed else 'PASS'))
        return failed
