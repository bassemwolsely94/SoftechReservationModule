"""
READ-ONLY SOFTECH study: how does SOFTECH create a customer (PIC)?  (POS speed wave, Task 7)

Owner decision 2026-10-26: there is NO safe SOFTECH test server, so this command issues
SELECT statements (and catalogue reads) ONLY. No trial rows, no rollback probe, no temp tables.
The create-PIC writer stays deferred until a safe target exists and the owner approves the
findings (docs/architecture/PIC_CREATE_INVESTIGATION.md).

    python manage.py investigate_pic_create                    # HQ only
    python manage.py investigate_pic_create --branch-nodes     # + which branch nodes hold the newest PICs

Sections (written to scratch/pic_create_probe.txt, git-ignored; names and phones are never read)
  [C1] localcustomers columns, NOT NULL and defaults
  [C2] every other table carrying a PIC column (phcode / picphcode / pphcode) - same detail
  [C3] triggers on those tables (names only; read the bodies with sp_helptext in a SOFTECH client)
  [C4] PIC allocation pattern from the newest customers: per branch prefix, highest serial and gaps
  [C5] replication: which branch nodes already hold those newest PICs (lag)
"""
import os
import re
from collections import defaultdict

from django.core.management.base import BaseCommand

DB = 'SOFTECHDB9.dbo'
MAIN = 'localcustomers'
NEWEST = 50
PIC_COLS = ('phcode', 'picphcode', 'pphcode')   # candidate PIC column names in other tables

_PIC = re.compile(r'^(\d{2,3}[A-Za-z]{2})(\d+)$')


def _marks(values):
    """'?,?,?' for an IN list — the values themselves are always bound."""
    return ','.join('?' * len(values))


def _s(v):
    return str(v).strip() if v is not None else ''


def split_pic(pic):
    """'03HD3059' -> ('03HD', 3059); None when it does not follow the prefix+serial pattern."""
    m = _PIC.match(_s(pic))
    return (m.group(1).upper(), int(m.group(2))) if m else None


class Command(BaseCommand):
    help = 'READ-ONLY: study how SOFTECH creates a customer (schema, triggers, PIC allocation, replication).'

    def add_arguments(self, parser):
        parser.add_argument('--branch-nodes', action='store_true',
                            help='also check which branch nodes already hold the newest PICs')
        parser.add_argument('--out', default='scratch/pic_create_probe.txt')

    # ── helpers ───────────────────────────────────────────────────────────────
    def _emit(self, line=''):
        self.stdout.write(str(line))
        self._buf.append(str(line))

    def _q(self, conn, sql, limit=None, params=None):
        """Run ONE read statement. Every statement goes through here (the test asserts on it)."""
        cur = conn.cursor()
        try:
            if limit:
                cur.execute(f'SET ROWCOUNT {int(limit)}')
            cur.execute(sql, params) if params else cur.execute(sql)
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

    # ── sections ──────────────────────────────────────────────────────────────
    def _columns(self, tables):
        _, rows = self._q(self.hq, (
            'SELECT o.name AS table_name, c.name AS col, c.status, c.cdefault, c.length '
            f'FROM {DB}.syscolumns c, {DB}.sysobjects o '
            f"WHERE c.id = o.id AND o.type = 'U' AND o.name IN ({_marks(tables)}) ORDER BY o.name, c.colid"),
            params=list(tables))
        out = defaultdict(list)
        for row in rows:
            t, col, flags, cdefault = row[0], row[1], row[2], row[3]
            length = row[4] if len(row) > 4 else ''
            nullable = bool((flags or 0) & 8) if isinstance(flags, int) else bool(flags)  # status bit 8 = NULL ok
            out[_s(t)].append((_s(col), 'NULL ok' if nullable else 'NOT NULL',
                               'default' if cdefault else '', length))
        return out

    def s_main(self):
        for t, items in self._columns([MAIN]).items():
            self._emit(f'  {t}: {len(items)} columns')
            for col, nul, dflt, length in items:
                self._emit(f'    {col:<28} {nul:<9} {dflt:<8} len={length}')

    def s_pic_tables(self):
        _, rows = self._q(self.hq, (
            'SELECT DISTINCT o.name '
            f'FROM {DB}.syscolumns c, {DB}.sysobjects o '
            f"WHERE c.id = o.id AND o.type = 'U' AND c.name IN ({_marks(PIC_COLS)}) ORDER BY o.name"),
            params=list(PIC_COLS))
        self.pic_tables = [_s(r[0]) for r in rows]
        self._emit(f'  {len(self.pic_tables)} tables carry a PIC column: ' + ', '.join(self.pic_tables))
        others = [t for t in self.pic_tables if t != MAIN]
        if others:
            for t, items in self._columns(others).items():
                req = [c for c, nul, dflt, _ in items if nul == 'NOT NULL' and not dflt]
                self._emit(f'    {t}: {len(items)} columns; NOT NULL without default: {", ".join(req) or "none"}')

    def s_triggers(self):
        names = [MAIN] + [t for t in self.pic_tables if t != MAIN]
        _, rows = self._q(self.hq, (
            'SELECT t.name AS trigger_name, o.name AS table_name '
            f'FROM {DB}.sysobjects t, {DB}.sysobjects o '
            f"WHERE t.type = 'TR' AND o.type = 'U' AND o.name IN ({_marks(names)}) "
            'AND (t.id = o.instrig OR t.id = o.updtrig OR t.id = o.deltrig) ORDER BY o.name, t.name'),
            params=names)
        if not rows:
            self._emit('  (no triggers found)')
        for trig, table in rows:
            self._emit(f'  {_s(table)}: trigger {_s(trig)}   (read the body: sp_helptext {_s(trig)})')

    def s_allocation(self):
        _, rows = self._q(self.hq, f'SELECT phcode FROM {DB}.{MAIN} ORDER BY trans_time DESC', limit=NEWEST)
        self.newest = [_s(r[0]) for r in rows]
        by_prefix, odd = defaultdict(list), 0
        for pic in self.newest:
            sp = split_pic(pic)
            if sp:
                by_prefix[sp[0]].append(sp[1])
            else:
                odd += 1
        self._emit(f'  {len(self.newest)} newest customers by trans_time; {odd} do not match <branch><type><serial>')
        for prefix, serials in sorted(by_prefix.items()):
            serials.sort()
            gaps = [n for n in range(serials[0], serials[-1]) if n not in serials]
            self._emit(f'    prefix {prefix}: {len(serials)} codes, highest serial {serials[-1]}, '
                       f'gaps inside the window: {gaps[:15] or "none"}')

    def s_replication(self, targets):
        from config.sybase import get_branch_connection
        if not self.newest:
            self._emit('  (no newest codes - skipped)')
            return
        for host, port, label in targets:
            try:
                conn = get_branch_connection(host, port, 'SOFTECHDB9')
            except Exception as exc:
                self._emit(f'  {label}: ! not reachable - {str(exc)[:100]}')
                continue
            try:
                _, rows = self._q(conn, f'SELECT phcode FROM {DB}.{MAIN} WHERE phcode IN ({_marks(self.newest)})',
                                  params=list(self.newest))
                have = {_s(r[0]) for r in rows}
                missing = [p for p in self.newest if p not in have]
                self._emit(f'  {label}: holds {len(have)}/{len(self.newest)} of the newest HQ codes'
                           + (f'; missing (first 10): {", ".join(missing[:10])}' if missing else ''))
            except Exception as exc:
                self._emit(f'  {label}: ! {str(exc)[:100]}')
            finally:
                conn.close()

    # ── run ───────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_sybase_connection
        self._buf, self.pic_tables, self.newest = [], [], []
        self._emit('=' * 72)
        self._emit('SOFTECH CUSTOMER (PIC) CREATION STUDY - read-only, SELECT statements only')
        self._emit('=' * 72)
        targets = []
        if o['branch_nodes']:
            from apps.branches.models import Branch
            targets = [(b.db_host, b.db_port or 5000, f'{b.softech_branch_id} ({b.db_host})')
                       for b in Branch.objects.filter(is_operational=True).exclude(softech_branch_id='100')
                       .exclude(db_host='').exclude(db_host__isnull=True).order_by('softech_branch_id')]
        self.hq = get_sybase_connection()
        try:
            self._safe(f'[C1] {MAIN} columns, NOT NULL and defaults', self.s_main)
            self._safe('[C2] other tables carrying a PIC', self.s_pic_tables)
            self._safe('[C3] triggers on those tables', self.s_triggers)
            self._safe(f'[C4] PIC allocation pattern - {NEWEST} newest customers', self.s_allocation)
            if o['branch_nodes']:
                self._safe('[C5] replication - do the branch nodes hold the newest HQ codes?',
                           lambda: self.s_replication(targets))
        finally:
            self.hq.close()
        out = o.get('out')
        if out:
            os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
            with open(out, 'w', encoding='utf-8') as f:
                f.write('\n'.join(self._buf) + '\n')
            self.stdout.write(f'\nreport written to {out}')
