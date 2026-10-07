"""
READ-ONLY SOFTECH probe for B7 — merging duplicate customer codes (PIC / phcode).

Goal: learn, WITHOUT guessing, how SOFTECH itself marks a customer code inactive and how points
live, before any merge write is designed (owner 2026-10-07: "turn some PIC inactive and merge
points to the active PIC code"). Only SELECTs (plus SET ROWCOUNT to bound samples). Phones are
masked and customer names are NOT printed in the summary sections, so the report can be shared.

    python manage.py investigate_pic_merge
    python manage.py investigate_pic_merge --pic 130HD123 --pic 04HD731     # compare specific PICs
    python manage.py investigate_pic_merge --host 192.168.30.12             # a branch node
    python manage.py investigate_pic_merge --out scratch/pic_merge_probe.txt

Best use: pass one PIC you KNOW staff already stopped / deactivated in SOFTECH and one normal
active PIC — the side-by-side dump shows which column the SOFTECH screen changes.

Sections: [1] schema of the customer + points tables · [2] row counts / one-row-per-branch shape ·
[3] candidate status/flag columns with value distributions · [4] triggers (+ text if readable) ·
[5] procs/triggers referencing localcustomers / picpoints · [6] FK references · [7] every table
carrying a PIC column (what history stays under an old code) · [8] duplicate-phone PIC groups ·
[9] points: picpoints doc codes, ADJ usage, enrollment/balance columns · [10] --pic side-by-side.
"""
import os
import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

DB = 'SOFTECHDB9.dbo'
TABLES = ('localcustomers', 'personsdata', 'personphones', 'picpoints', 'localcustomerspoints')
FLAG_HINT = re.compile(r'(stop|activ|block|cancel|status|valid|del|susp|flag|close|lock|allow|use|merg|old|new|repl)',
                       re.I)
PIC_COLS = ('phcode', 'personcode', 'ppersoncode', 'custcode', 'branchcustcode', 'personglobalcode')


def _mask(phone):
    d = re.sub(r'\D', '', str(phone or ''))
    return f'••{d[-4:]}' if len(d) >= 4 else ('—' if not d else '••')


def _norm_phone(phone):
    d = re.sub(r'\D', '', str(phone or ''))
    if d.startswith('20') and len(d) == 12:
        d = d[1:]
    return d[-10:] if len(d) >= 10 else ''


class Command(BaseCommand):
    help = 'READ-ONLY probe: how SOFTECH deactivates a customer code (PIC) and stores points (B7).'

    def add_arguments(self, parser):
        parser.add_argument('--pic', action='append', default=[], help='PIC to dump side-by-side (repeatable)')
        parser.add_argument('--host', default='', help='branch node host (default: HQ connection)')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--out', default='scratch/pic_merge_probe.txt',
                            help='also write the report here (scratch/ is git-ignored)')
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
            cur.execute(sql, params or [])
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
        self._emit(f'── {title} ' + '─' * max(0, 66 - len(title)))
        try:
            fn()
        except Exception as exc:
            self._emit(f'  ! failed: {str(exc)[:300]}')

    def _columns(self, table):
        _, rows = self._q(
            f"SELECT c.name, t.name, c.length FROM {DB}.syscolumns c, {DB}.systypes t, {DB}.sysobjects o "
            "WHERE o.name = ? AND o.type = 'U' AND c.id = o.id AND c.usertype = t.usertype ORDER BY c.colid",
            [table])
        return [(r[0], r[1], r[2]) for r in rows]

    # ── sections ──────────────────────────────────────────────────────────────
    def s_schema(self):
        self.schema = {}
        for t in TABLES:
            cols = self._columns(t)
            self.schema[t] = cols
            self._emit(f'  {t}: ' + (', '.join(f'{n}:{ty}({ln})' for n, ty, ln in cols) if cols else '(not found)'))

    def s_shape(self):
        _, r = self._q(f'SELECT count(*), count(distinct phcode), count(distinct branchcode) FROM {DB}.localcustomers')
        rows, pics, branches = r[0]
        self._emit(f'  localcustomers: {rows} rows · {pics} distinct PIC · {branches} branch codes')
        _, r = self._q(f'SELECT n, count(*) FROM (SELECT phcode, count(*) n FROM {DB}.localcustomers '
                       'GROUP BY phcode) x GROUP BY n ORDER BY n')
        self._emit('  rows per PIC (rows → how many PICs): ' + ', '.join(f'{a}→{b}' for a, b in r[:12]))
        _, r = self._q(f'SELECT count(*) FROM {DB}.personsdata p WHERE EXISTS '
                       f'(SELECT 1 FROM {DB}.localcustomers l WHERE l.phcode = p.personcode)')
        self._emit(f'  personsdata rows whose personcode is a PIC: {r[0][0]}')

    def s_flags(self):
        for t in ('localcustomers', 'personsdata', 'personphones'):
            for name, ty, ln in self.schema.get(t, []):
                small = ty in ('bit', 'tinyint') or (ty in ('char', 'varchar', 'nchar') and ln <= 2)
                if not (FLAG_HINT.search(name) or small):
                    continue
                _, rows = self._q(f'SELECT {name}, count(*) FROM {DB}.{t} GROUP BY {name} ORDER BY 2 DESC', limit=8)
                if len(rows) <= 1 and not FLAG_HINT.search(name):
                    continue                     # constant column, no signal
                self._emit(f'  {t}.{name} ({ty}): ' + ', '.join(f'{v!r}={n}' for v, n in rows))

    def s_triggers(self):
        names = "','".join(TABLES)
        _, rows = self._q(
            f"SELECT t.name, d.name, i.name, u.name FROM {DB}.sysobjects t "
            f"LEFT JOIN {DB}.sysobjects d ON d.id = t.deltrig LEFT JOIN {DB}.sysobjects i ON i.id = t.instrig "
            f"LEFT JOIN {DB}.sysobjects u ON u.id = t.updtrig WHERE t.name IN ('{names}') AND t.type = 'U'")
        trig = set()
        for t, d, i, u in rows:
            self._emit(f'  {t}: insert={i or "-"} update={u or "-"} delete={d or "-"}')
            trig |= {x for x in (d, i, u) if x}
        for tr in sorted(trig):
            _, txt = self._q(f"SELECT c.text FROM {DB}.syscomments c, {DB}.sysobjects o "
                             "WHERE o.name = ? AND c.id = o.id ORDER BY c.colid", [tr])
            body = ''.join((x[0] or '') for x in txt)
            self._emit(f'  · {tr}: ' + (body[:3000].replace('\n', ' ') if body.strip()
                                        else '(text hidden / encrypted)'))

    def s_refs_code(self):
        _, rows = self._q(
            f"SELECT DISTINCT o.name, o.type FROM {DB}.sysobjects o, {DB}.syscomments c WHERE c.id = o.id "
            "AND o.type IN ('P','TR','V') AND (c.text LIKE '%localcustomers%' OR c.text LIKE '%picpoints%')")
        self._emit(f'  {len(rows)} readable procs/triggers/views mention localcustomers or picpoints: '
                   + ', '.join(f'{n}({t.strip()})' for n, t in rows[:60]))

    def s_fk(self):
        names = "','".join(TABLES)
        _, rows = self._q(f"SELECT object_name(tableid), object_name(reftabid) FROM {DB}.sysreferences "
                          f"WHERE object_name(reftabid) IN ('{names}') OR object_name(tableid) IN ('{names}')")
        self._emit('  ' + (', '.join(f'{a} → {b}' for a, b in rows) if rows else '(no declared FK references)'))

    def s_footprint(self):
        cols = "','".join(PIC_COLS)
        _, rows = self._q(f"SELECT o.name, c.name FROM {DB}.sysobjects o, {DB}.syscolumns c "
                          f"WHERE o.type = 'U' AND c.id = o.id AND c.name IN ('{cols}') ORDER BY o.name")
        by = defaultdict(list)
        for t, c in rows:
            by[t].append(c)
        self._emit(f'  {len(by)} tables carry a customer-code column (history that stays under an old PIC):')
        for t in sorted(by):
            self._emit(f'    {t}: {", ".join(by[t])}')

    def s_duplicates(self):
        _, lc = self._q(f'SELECT phcode, mobileno, branchcustphone FROM {DB}.localcustomers')
        try:
            _, pp = self._q(f'SELECT personcode, phoneno FROM {DB}.personphones WHERE phoneblock = 0')
        except Exception:
            pp = []
        groups = defaultdict(set)
        for pic, m1, m2 in lc:
            for p in (m1, m2):
                k = _norm_phone(p)
                if k and pic:
                    groups[k].add(str(pic).strip())
        for pic, p in pp:
            k = _norm_phone(p)
            if k and pic:
                groups[k].add(str(pic).strip())
        dup = {k: v for k, v in groups.items() if len(v) > 1}
        sizes = Counter(len(v) for v in dup.values())
        pics = set().union(*dup.values()) if dup else set()
        self._emit(f'  phone numbers shared by >1 PIC: {len(dup)} numbers · {len(pics)} PICs involved')
        self._emit('  group size → count: ' + ', '.join(f'{s}→{n}' for s, n in sorted(sizes.items())))
        for k, v in sorted(dup.items(), key=lambda kv: -len(kv[1]))[:self.samples]:
            self._emit(f'    {_mask(k)}: {", ".join(sorted(v))}')

    def s_points(self):
        _, rows = self._q(f'SELECT doccode, count(*), sum(points) FROM {DB}.picpoints GROUP BY doccode ORDER BY 2 DESC',
                          limit=20)
        self._emit('  picpoints by doccode (rows, Σpoints): ' + ', '.join(f'{d!r}:{n}/{s}' for d, n, s in rows))
        _, rows = self._q(f"SELECT vf1, vf2, count(*) FROM {DB}.picpoints WHERE doccode = 'ADJ' "
                          'GROUP BY vf1, vf2 ORDER BY 3 DESC', limit=self.samples)
        self._emit('  ADJ adjustments (reason vf1 / operator vf2 → rows): '
                   + (', '.join(f'{a!r}/{b!r}→{n}' for a, b, n in rows) or 'none'))
        _, rows = self._q(f'SELECT picpoints, count(*) FROM {DB}.localcustomers GROUP BY picpoints ORDER BY 2 DESC',
                          limit=10)
        self._emit('  localcustomers.picpoints values (enrollment flag or balance?): '
                   + ', '.join(f'{v!r}={n}' for v, n in rows))
        cols, rows = self._q(f'SELECT * FROM {DB}.localcustomerspoints', limit=3)
        self._emit(f'  localcustomerspoints sample columns: {cols}')

    def s_pics(self):
        for pic in self.pics:
            self._emit(f'  ═ PIC {pic}')
            for t, where in (('localcustomers', 'phcode'), ('personsdata', 'personcode')):
                cols, rows = self._q(f'SELECT * FROM {DB}.{t} WHERE {where} = ?', [pic])
                for r in rows:
                    shown = {c: (_mask(v) if re.search(r'phone|mobile|tel', c, re.I) else v)
                             for c, v in zip(cols, r) if not re.search(r'name|address', c, re.I)}
                    self._emit(f'    {t}: {shown}')
                if not rows:
                    self._emit(f'    {t}: (none)')
            _, rows = self._q(f'SELECT phoneno, phoneblock, stckorderallow FROM {DB}.personphones WHERE personcode = ?', [pic])
            self._emit('    personphones: ' + (', '.join(f'{_mask(p)} block={b} order={o}' for p, b, o in rows) or '(none)'))
            _, rows = self._q(f'SELECT count(*), sum(points), max(transdate) FROM {DB}.picpoints WHERE phcode = ?', [pic])
            self._emit(f'    picpoints: rows={rows[0][0]} Σ={rows[0][1]} last={rows[0][2]}')
            _, rows = self._q(f'SELECT count(*), max(docdate) FROM {DB}.stktransm WHERE phcode = ?', [pic])
            self._emit(f'    stktransm docs: {rows[0][0]} · last {rows[0][1]}')

    # ── run ───────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_branch_connection, get_sybase_connection
        self._buf, self.samples, self.pics = [], o['samples'], [p.strip() for p in o['pic'] if p.strip()]
        self.conn = get_branch_connection(o['host'], o['port'], 'SOFTECHDB9') if o['host'] else get_sybase_connection()
        self.schema = {}
        self._emit('=' * 72)
        self._emit(f'SOFTECH PIC MERGE PROBE (read-only) — {"node " + o["host"] if o["host"] else "HQ"}')
        self._emit('=' * 72)
        try:
            self._safe('[1] schema', self.s_schema)
            self._safe('[2] shape', self.s_shape)
            self._safe('[3] candidate status / flag columns', self.s_flags)
            self._safe('[4] triggers', self.s_triggers)
            self._safe('[5] code referencing the tables', self.s_refs_code)
            self._safe('[6] FK references', self.s_fk)
            self._safe('[7] tables carrying a customer code', self.s_footprint)
            self._safe('[8] duplicate-phone PIC groups', self.s_duplicates)
            self._safe('[9] points', self.s_points)
            if self.pics:
                self._safe('[10] PIC side-by-side', self.s_pics)
        finally:
            self.conn.close()
        if o['out']:
            os.makedirs(os.path.dirname(o['out']) or '.', exist_ok=True)
            with open(o['out'], 'w', encoding='utf-8') as f:
                f.write('\n'.join(self._buf) + '\n')
            self.stdout.write(self.style.SUCCESS(f'\nWritten to {o["out"]}'))
