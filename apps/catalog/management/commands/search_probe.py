"""
search_probe — the item-search golden corpus (apps/catalog/search_corpus.py) on the REAL catalog,
through every search path, with timings. Run before and after each search batch.

    python manage.py search_probe                       # 3 timed runs per query and path
    python manage.py search_probe --repeat 5 --json out.json
    python manage.py search_probe --with-temp-indexes   # build the search indexes for this run

Paths (in-process, APIRequestFactory as an existing superuser — no server needed):
  A  /api/items/softech-search/?no_live=1        (the POS / pickers endpoint)
  B  /api/items/?search=&rank=engine&page_size=10 (item list in the engine's order)
  C  /api/search/universal?types=items           (Ctrl+K)               — report-only
  D  wildcard.item_search(q)                     (the engine itself)

Exit code 1 when a corpus entry fails on A, B or D, D's p95 is over BUDGET_MS or B's p95 over
B_BUDGET_MS. The time budgets are only judged when the search indexes (the fold indexes as
catalog 0047 rebuilt them, the code-part ones of 0046) exist — without them the timings mean
nothing, and the probe says so loudly. Entries marked `real_report_only` (the real catalog
lacks the data) are printed but never fail the run.

Read-only: everything runs in ONE transaction that is always rolled back. --with-temp-indexes
compares each search index's pg_get_indexdef with its migration's SQL and, inside that
transaction (rolled back with it, never committed), CREATEs the missing ones and DROPs +
CREATEs only those built on another definition (e.g. an older fold expression, so that is
never what gets timed). It prints which. Correct indexes are left alone; when one is rebuilt,
DROP INDEX takes an ACCESS EXCLUSIVE lock on catalog_item / catalog_itembarcode until the run
ends (and CREATE INDEX blocks writes): catalog reads and the item sync from other sessions wait
for it — a minute or two.
"""
import importlib
import json
import math
import re
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

BUDGET_MS = 40                          # D: the engine itself, p95
B_BUDGET_MS = 150                       # B: the item list (rank=engine) over HTTP-in-process, p95
PATHS = ('A', 'B', 'C', 'D')
GATED = ('A', 'B', 'D')                 # C is report-only
LABELS = {'A': 'softech-search no_live', 'B': 'items ?search=&rank=engine', 'C': 'universal items',
          'D': 'item_search()'}
# (migration module, its CREATE list, its DROP list): the CURRENT definition of every search
# index — the fold indexes as 0047 rebuilt them, the code-part ones from 0046
INDEX_MIGRATIONS = (('apps.catalog.migrations.0047_fold_marks_narrow', 'CREATE', 'DROP'),
                    ('apps.catalog.migrations.0046_code_part_trgm', 'SQL', 'REVERSE'))
_NAME_RE = re.compile(r'(?:CREATE INDEX IF NOT EXISTS|DROP INDEX IF EXISTS) (\w+)')


def budget_ms(path):
    """The p95 budget a path is judged on (when the indexes exist); None = pass/fail only."""
    return {'D': BUDGET_MS, 'B': B_BUDGET_MS}.get(path)


def index_sql() -> list:
    """The current CREATE INDEX statements of the search indexes (the migrations' own SQL, so
    the same index names)."""
    sql = []
    for mod, create, _ in INDEX_MIGRATIONS:
        sql += getattr(importlib.import_module(mod), create)
    return sql


def index_drop_sql() -> dict:
    """{index name: its migration's constant DROP INDEX IF EXISTS statement} — so
    --with-temp-indexes never builds SQL from text."""
    out = {}
    for mod, _, drop in INDEX_MIGRATIONS:
        for s in getattr(importlib.import_module(mod), drop):
            out[_NAME_RE.match(s).group(1)] = s
    return out


def index_names() -> list:
    return [_NAME_RE.match(s).group(1) for s in index_sql()]


def live_indexdefs() -> dict:
    """{index name: pg_get_indexdef(…) or None when the index does not exist}."""
    names = index_names()
    with connection.cursor() as c:
        c.execute('SELECT c.relname, pg_get_indexdef(c.oid) FROM pg_class c '
                  "WHERE c.relkind = 'i' AND c.relname = ANY(%s)", [names])
        have = dict(c.fetchall())
    return {n: have.get(n) for n in names}


def missing_indexes() -> list:
    return [n for n, d in live_indexdefs().items() if d is None]


_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _norm_indexdef(sql: str) -> str:
    """The comparable form of an index definition: string literals kept byte for byte; outside
    them case, whitespace, parentheses, type casts, `IF NOT EXISTS`, the `public.` schema and
    the default `USING btree` dropped (what pg_get_indexdef adds or the migration leaves out)."""
    out, pos = [], 0
    for m in list(_LITERAL.finditer(sql)) + [None]:
        code = sql[pos:m.start() if m else len(sql)].lower()
        code = re.sub(r'::\s*(?:character varying|double precision|[a-z_]+)', '', code)
        code = re.sub(r'\bif not exists\b|\bpublic\.|\busing btree\b', ' ', code)
        out.append(re.sub(r'[\s()]+', '', code))
        if m:
            out.append(m.group(0))
            pos = m.end()
    return ''.join(out)


def indexdef_matches(live_def: str, migration_sql: str) -> bool:
    """True when the live index (pg_get_indexdef) is the one the migration statement builds."""
    return _norm_indexdef(live_def) == _norm_indexdef(migration_sql)


def plan_temp_indexes(live: dict) -> tuple:
    """(names to DROP, names to CREATE) for --with-temp-indexes: an index that is missing is
    created; one built on another definition (e.g. an older fold expression) is dropped and
    created; a correct one is left alone — no DROP, so no ACCESS EXCLUSIVE lock."""
    drop, create = [], []
    for name, sql in zip(index_names(), index_sql()):
        d = live.get(name)
        if d is None:
            create.append(name)
        elif not indexdef_matches(d, sql):
            drop.append(name)
            create.append(name)
    return drop, create


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
                            help='Drop and rebuild the catalog 0044–0046 indexes from the migrations for this '
                                 'run only (always rolled back).')

    def handle(self, *args, **opts):
        user = (get_user_model().objects.filter(is_superuser=True, is_active=True).order_by('id').first())
        if user is None:
            raise CommandError('search_probe needs an active superuser to call the endpoints as.')
        repeat = max(1, opts['repeat'])
        with transaction.atomic():
            try:
                missing = missing_indexes()
                if opts['with_temp_indexes']:
                    # only what is missing or differs: CREATE … IF NOT EXISTS would keep an index
                    # of the same name built on an older expression (and the run would time that
                    # one), so those are dropped first; correct ones are not touched (no lock)
                    drop, create = plan_temp_indexes(live_indexdefs())
                    if create:
                        drops = index_drop_sql()
                        creates = dict(zip(index_names(), index_sql()))
                        with connection.cursor() as c:
                            # DDL refuses a table with pending deferred-FK checks (rows written
                            # earlier in this transaction, e.g. a test's fixtures): run them now
                            c.execute('SET CONSTRAINTS ALL IMMEDIATE')
                            for n in drop:              # the migrations' constant DROP statements
                                c.execute(drops[n])
                            for n in create:
                                c.execute(creates[n])
                            c.execute('ANALYZE catalog_item')
                            c.execute('ANALYZE catalog_itembarcode')
                    self.stdout.write('temp indexes (rolled back at the end): '
                                      f'rebuilt (definition differed): {", ".join(drop) or "none"}; '
                                      f'created (missing): {", ".join(n for n in create if n not in drop) or "none"}; '
                                      f'left as they are: {len(index_names()) - len(create)}')
                    missing = missing_indexes()
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
            'B': lambda q: view_rows(listing, '/api/items/',
                                     {'search': q, 'rank': 'engine', 'page_size': 10}),
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
                # A, B (rank=engine rows carry the engine's tier) and D: name and tier;
                # C carries no tier: judged on the name only
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
            gate = ((f'pass + p95 ≤ {budget_ms(p)} ms' if budget_ms(p) else 'pass')
                    if p in GATED else 'report-only')
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
        timed = [p for p in GATED if budget_ms(p)]
        for p in timed:
            slow = sorted(((pct(r['paths'][p]['ms'], 0.5), r['q']) for r in records), reverse=True)
            slow = [(round(m, 1), q) for m, q in slow if m > budget_ms(p)]
            if slow:
                w(f'queries over {budget_ms(p)} ms ({p}, median): {slow}')
        if missing:
            w('')
            w('!' * 78)
            w(f'!! WARNING: indexes missing: {", ".join(missing)}')
            w('!! The engine is tuned WITH catalog 0044–0047 — these timings mean nothing and the')
            w('!! time budgets (' + ', '.join(f'{p} {budget_ms(p)} ms' for p in timed)
              + ') are NOT judged. Apply the migrations or use --with-temp-indexes.')
            w('!' * 78)
        else:
            for p in timed:
                p95 = pct([m for r in records for m in r['paths'][p]['ms']], 0.95)
                if p95 > budget_ms(p):
                    failed.append(f'path {p} p95 {p95:.1f} ms > {budget_ms(p)} ms')
        w('')
        w('RESULT: ' + ('FAIL — ' + '; '.join(failed) if failed else 'PASS'))
        return failed
