"""
READ-ONLY SOFTECH probe for doc 38 — stock-count entry (الجرد), step 1 only.

SOFTECH records a count in two steps: an employee ENTERS and saves the count,
then an administrator APPROVES it so it takes effect. The owner's rule
(2026-10-12): the new system may do step 1, NEVER step 2 — approval always
happens inside SOFTECH.

Before any step-1 writer is designed we must know, from live data, what an
entered-but-unapproved count looks like in SOFTECH. Only SELECTs (plus SET
ROWCOUNT to bound samples); no customer names or phones.

    python manage.py investigate_stockcount_entry
    python manage.py investigate_stockcount_entry --host 192.168.30.12      # a branch node
    python manage.py investigate_stockcount_entry --doc 150/130/12345       # dump one document

Best: run it once right after an employee SAVES a count in SOFTECH (step 1,
before approval) and once after the administrator approves it, with --doc for
that document — the difference between the two dumps is the approval.

Sections:
 [1] transdoc: how SOFTECH names doc codes 50 / 150 / 160
 [2] tables that may hold counts (names, size, doc codes inside) — including
     staging copies like the POS stktransm5 / stktrans5
 [3] stktransm / stktrans columns that look like a status / approval marker
 [4] value spread of those columns on recent 50 / 150 headers vs sales (115)
 [5] the latest 50 and 150 documents in full (header + first lines)
 [6] lastdocnumbers row(s) for the node (number sequences)
 [7] --doc: one document in full, from every candidate table
"""
import datetime
import os
import re

from django.core.management.base import BaseCommand

DB = 'SOFTECHDB9.dbo'
COUNT_DOCS = ('50', '150', '160')
TABLE_HINT = re.compile(r'(jard|gard|inv|count|taking|adj|stktransm?\d|stktrans_?\w*temp|pend|draft)', re.I)
STATUS_HINT = re.compile(r'(approv|post|status|confirm|accept|lock|close|valid|ok$|flag|done|final|apply|'
                         r'usercode|user2|user_|admin|manager|cancel|del)', re.I)
SKIP_BIG = {'stktrans', 'stktransm', 'stkbal', 'localcustomers', 'picpoints'}
_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _ident(name):
    """Table / column names come from SOFTECH's own sysobjects / syscolumns and cannot be
    bound as parameters — accept plain identifiers only, so nothing else reaches the SQL."""
    if not _IDENT.match(str(name or '')):
        raise ValueError(f'not a plain identifier: {name!r}')
    return name


class Command(BaseCommand):
    help = 'READ-ONLY: how SOFTECH stores an entered-but-unapproved stock count (doc 38, step 1 only).'

    def add_arguments(self, parser):
        parser.add_argument('--host', default='', help='branch node host (default: HQ connection)')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--doc', default='', help='dump one document: DOCCODE/BRANCH/DOCNUMBER')
        parser.add_argument('--days', type=int, default=90, help='look-back for [4] and [5]')
        parser.add_argument('--out', default='scratch/stockcount_entry_probe.txt',
                            help='also write the report here (scratch/ is git-ignored)')

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
            cols = [d[0] for d in (cur.description or [])]
            return cols, cur.fetchall()
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

    def _columns(self, table):
        _, rows = self._q(
            f"SELECT c.name, t.name FROM {DB}.syscolumns c, {DB}.systypes t, {DB}.sysobjects o "
            "WHERE o.name = ? AND o.type = 'U' AND c.id = o.id AND c.usertype = t.usertype ORDER BY c.colid",
            [table])
        return [r[0] for r in rows]

    def _dump(self, cols, rows, indent='    '):
        for r in rows:
            parts = [f'{c}={v}' for c, v in zip(cols, r) if v not in (None, '', 0, 0.0)]
            self._emit(indent + ' | '.join(parts))

    # ── sections ──────────────────────────────────────────────────────────────
    def s_transdoc(self):
        cols, rows = self._q(f"SELECT * FROM {DB}.transdoc WHERE doccode IN ('50', '150', '160')")
        self._dump(cols, rows)

    def s_tables(self):
        _, rows = self._q(
            f"SELECT o.name, i.rowcnt FROM {DB}.sysobjects o, {DB}.sysindexes i "
            "WHERE o.type = 'U' AND i.id = o.id AND i.indid IN (0, 1) ORDER BY o.name")
        self.candidates = []
        for name, cnt in rows:
            if not TABLE_HINT.search(name):
                continue
            cols = [c.lower() for c in self._columns(name)]
            has_doc = 'doccode' in cols
            line = f'  {name:28s} rows≈{int(cnt or 0):>10,}  doccode column: {"yes" if has_doc else "no"}'
            if has_doc and name.lower() not in SKIP_BIG and int(cnt or 0) < 2_000_000:
                _, dist = self._q(f"SELECT doccode, COUNT(*) FROM {DB}.{_ident(name)} GROUP BY doccode",
                                  limit=40)
                hits = {str(d).strip(): n for d, n in dist}
                count_hits = {d: hits[d] for d in COUNT_DOCS if d in hits}
                line += f'  50/150/160 rows: {count_hits or "none"}'
                if count_hits:
                    self.candidates.append(name)
            self._emit(line)
        self._emit(f'  → tables carrying count documents (besides stktransm/stktrans): {self.candidates or "none"}')

    def s_status_columns(self):
        self.status_cols = {}
        for t in ('stktransm', 'stktrans', *getattr(self, 'candidates', [])):
            cols = [c for c in self._columns(t) if STATUS_HINT.search(c)]
            self.status_cols[t] = cols
            self._emit(f'  {t:14s} {", ".join(cols) or "(none)"}')

    def s_spread(self):
        since = (datetime.date.today() - datetime.timedelta(days=self.opts['days'])).isoformat()
        week = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        for col in self.status_cols.get('stktransm', []):
            col = _ident(col)
            self._emit(f'  stktransm.{col}:')
            for label, codes, frm in (('counts 50/150', "('50', '150')", since), ('sales 115', "('115')", week)):
                _, rows = self._q(
                    f"SELECT {col}, COUNT(*) FROM {DB}.stktransm WHERE doccode IN {codes} AND docdate >= ? "
                    f"GROUP BY {col} ORDER BY 2 DESC", [frm], limit=8)
                spread = ', '.join(f'{v!r}: {n}' for v, n in rows) or '—'
                self._emit(f'    {label:14s} {spread}')
        self._emit('  → a column whose values differ between counts and sales, or that has a minority value on '
                   'counts, is a candidate "not yet approved" marker — confirm with --doc before/after approval')

    def s_latest(self):
        since = (datetime.date.today() - datetime.timedelta(days=self.opts['days'])).isoformat()
        for dc in ('150', '50'):
            cols, rows = self._q(
                f"SELECT * FROM {DB}.stktransm WHERE doccode = ? AND docdate >= ? ORDER BY trans_time DESC",
                [dc, since], limit=2)
            self._emit(f'  latest doccode {dc} headers:')
            self._dump(cols, rows)
            for r in rows:
                rec = dict(zip([c.lower() for c in cols], r))
                lcols, lines = self._q(
                    f"SELECT * FROM {DB}.stktrans WHERE doccode = ? AND branchcode = ? AND docnumber = ?",
                    [dc, rec.get('branchcode'), rec.get('docnumber')], limit=3)
                self._emit(f'    first lines of {dc}/{rec.get("branchcode")}/{rec.get("docnumber")}:')
                self._dump(lcols, lines, indent='      ')

    def s_lastdoc(self):
        cols, rows = self._q(f"SELECT * FROM {DB}.lastdocnumbers", limit=10)
        self._dump(cols, rows)

    def s_doc(self):
        dc, br, num = (self.opts['doc'].split('/') + ['', '', ''])[:3]
        try:
            num = int(num)
        except ValueError:
            pass
        for t in ('stktransm', 'stktrans', *getattr(self, 'candidates', [])):
            cols = [c.lower() for c in self._columns(t)]
            if not {'doccode', 'branchcode', 'docnumber'} <= set(cols):
                continue
            c, rows = self._q(f"SELECT * FROM {DB}.{_ident(t)} WHERE doccode = ? AND branchcode = ? AND docnumber = ?",
                              [dc, br, num], limit=50)
            self._emit(f'  {t}: {len(rows)} row(s)')
            self._dump(c, rows)

    # ── entry ─────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_branch_connection, get_sybase_connection
        self.opts, self._buf = o, []
        node = o['host'] or 'HQ'
        self._emit(f'Stock-count entry probe — {datetime.datetime.now():%Y-%m-%d %H:%M} — node {node} (READ-ONLY)')
        self.conn = get_branch_connection(o['host'], o['port']) if o['host'] else get_sybase_connection()
        try:
            self._safe('[1] transdoc — doc codes 50 / 150 / 160', self.s_transdoc)
            self._safe('[2] tables that may hold counts', self.s_tables)
            self._safe('[3] status / approval-looking columns', self.s_status_columns)
            self._safe('[4] value spread: counts vs sales', self.s_spread)
            self._safe('[5] latest count documents in full', self.s_latest)
            self._safe('[6] lastdocnumbers', self.s_lastdoc)
            if o['doc']:
                self._safe(f'[7] document {o["doc"]} in every candidate table', self.s_doc)
        finally:
            self.conn.close()
        if o['out']:
            os.makedirs(os.path.dirname(o['out']) or '.', exist_ok=True)
            with open(o['out'], 'w', encoding='utf-8') as f:
                f.write('\n'.join(self._buf) + '\n')
            self.stdout.write(self.style.SUCCESS(f'\nWritten to {o["out"]}'))
