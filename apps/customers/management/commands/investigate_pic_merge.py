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
    python manage.py investigate_pic_merge --suggest                       # propose duplicate pairs to review

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
_AR = str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ؤ': 'و', 'ئ': 'ي', 'ـ': ''})


def _norm_text(t):
    """Arabic-tolerant compare key: unify alef/ya/ta-marbuta, drop diacritics, punctuation, spaces."""
    t = re.sub(r'[\u064B-\u0652]', '', str(t or '')).translate(_AR).lower()
    return re.sub(r'[^0-9a-z\u0621-\u064a]+', ' ', t).strip()


def _name_match(a, b):
    """'same' (identical), 'similar' (first two words equal), '' (different/empty)."""
    a, b = _norm_text(a), _norm_text(b)
    if not a or not b:
        return ''
    if a == b:
        return 'same'
    return 'similar' if a.split()[:2] == b.split()[:2] and len(a.split()) > 1 else ''


PLACEHOLDER_GROUP = 10        # > this many codes on one number = shared/junk number, not a duplicate


def _placeholder(n):
    """01000000000 / 01111111111 style numbers (few distinct digits in the last 8)."""
    return len(set(n[-8:])) <= 2


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
        parser.add_argument('--suggest', action='store_true',
                            help='list non-active / locked codes + phone-mates and propose a pair (uses our sales mirror)')
        parser.add_argument('--points-log', action='store_true',
                            help='also scan the last 60 days of the (huge) picpoints log by doc code')

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
        _, lc = self._q(f'SELECT phcode, mobileno, branchcustphone, branchcustname, branchcustaddress1, '
                        f'phcodestatus FROM {DB}.localcustomers')
        self.info = {str(r[0]).strip(): {'name': r[3], 'addr': r[4], 'status': str(r[5] or '').strip()} for r in lc}
        try:
            _, pp = self._q(f'SELECT personcode, phoneno FROM {DB}.personphones WHERE phoneblock = 0')
        except Exception:
            pp = []
        groups = defaultdict(set)
        for pic, m1, m2, *_ in lc:
            for p in (m1, m2):
                k = _norm_phone(p)
                if k and pic:
                    groups[k].add(str(pic).strip())
        for pic, p in pp:
            k = _norm_phone(p)
            if k and pic:
                groups[k].add(str(pic).strip())
        self.phones_of = defaultdict(set)
        for k, v in groups.items():
            for pic in v:
                self.phones_of[pic].add(k)
        self.groups = groups
        shared = {k: v for k, v in groups.items() if len(v) > 1}
        placeholder = {k: v for k, v in shared.items() if _placeholder(k) or len(v) > PLACEHOLDER_GROUP}
        dup = {k: v for k, v in shared.items() if k not in placeholder}
        self.dup_groups = dup
        sizes = Counter(len(v) for v in dup.values())
        pics = set().union(*dup.values()) if dup else set()
        self._emit(f'  placeholder / junk numbers excluded: {len(placeholder)} numbers · '
                   f'{len(set().union(*placeholder.values())) if placeholder else 0} PICs '
                   f'(repeated digits or > {PLACEHOLDER_GROUP} codes on one number)')
        self._emit(f'  REAL shared numbers: {len(dup)} numbers · {len(pics)} PICs involved')
        self._emit('  group size → count: ' + ', '.join(f'{s}→{n}' for s, n in sorted(sizes.items())))
        for k, v in sorted(dup.items(), key=lambda kv: -len(kv[1]))[:self.samples]:
            self._emit(f'    {_mask(k)}: {", ".join(sorted(v))}')

    def s_points(self):
        """Light by default (the picpoints log is huge — a full GROUP BY timed out)."""
        _, rows = self._q(f'SELECT count(*), count(distinct phcode), sum(totpoints), sum(conpoints) '
                          f'FROM {DB}.localcustomerspoints')
        n, pics, tot, con = rows[0]
        self._emit(f'  localcustomerspoints (balance table): {n} rows · {pics} PICs · earned {tot} · consumed {con}')
        _, rows = self._q(f'SELECT n, count(*) FROM (SELECT phcode, count(*) n FROM {DB}.localcustomerspoints '
                          'GROUP BY phcode) x GROUP BY n ORDER BY n')
        self._emit('  balance rows per PIC: ' + ', '.join(f'{a}→{b}' for a, b in rows[:8]))
        if not self.points_log:
            self._emit('  (picpoints log by doc code skipped — add --points-log to scan the last 60 days)')
            return
        _, rows = self._q(f'SELECT doccode, count(*), sum(points) FROM {DB}.picpoints '
                          'WHERE transdate >= dateadd(day, -60, getdate()) GROUP BY doccode ORDER BY 2 DESC', limit=20)
        self._emit('  picpoints last 60 days by doccode (rows, Σpoints): '
                   + ', '.join(f'{d!r}:{c}/{t}' for d, c, t in rows))

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
            _, rows = self._q(f'SELECT totpoints, conpoints, branchcode FROM {DB}.localcustomerspoints WHERE phcode = ?', [pic])
            self._emit('    points balance: ' + (', '.join(f'earned {t} − consumed {c} = {(t or 0) - (c or 0)} (branch {b})'
                                                     for t, c, b in rows) or '(no balance row)'))
            for label, sql in (('picpoints log', f'SELECT count(*), sum(points), max(transdate) FROM {DB}.picpoints WHERE phcode = ?'),
                               ('stktransm docs', f'SELECT count(*), max(docdate), 0 FROM {DB}.stktransm WHERE phcode = ?')):
                try:                                  # big tables — a timeout must not lose the rest
                    _, rows = self._q(sql, [pic])
                    self._emit(f'    {label}: rows={rows[0][0]} last={rows[0][2] if label == "picpoints log" else rows[0][1]}'
                               + (f' Σ={rows[0][1]}' if label == 'picpoints log' else ''))
                except Exception as exc:
                    self._emit(f'    {label}: (skipped — {str(exc)[:80]})')

    def s_status(self):
        """The real SOFTECH deactivation field is localcustomers.phcodestatus ('1' = active; '0' / '5' /
        blank seen on ~20 codes) with phcodestatususercode / phcodestatustime, plus piclock. List every
        non-active or locked code, who shares its phone, and each code's last sale in our mirror, then
        propose the pair to review. Also profiles pphcode (possible parent/main-PIC link)."""
        from django.db.models import Max
        from apps.customers.models import PurchaseHistory
        cols = 'phcode, phcodestatus, piclock, picdied, phcodestatususercode, phcodestatustime, ' \
               'custdateactive, usercode, trans_time, pphcode, relativecode, branchcode, picpoints'
        cnames, rows = self._q(f"SELECT {cols} FROM {DB}.localcustomers WHERE isnull(phcodestatus, '') <> '1' "
                               'OR piclock = 1')
        recs = [dict(zip(cnames, r)) for r in rows]
        mates = {}
        for r in recs:
            pic = str(r['phcode']).strip()
            mates[pic] = sorted({m for k in self.phones_of.get(pic, ()) for m in self.groups.get(k, ()) if m != pic})
        allpics = {str(r['phcode']).strip() for r in recs} | {m for v in mates.values() for m in v}
        status = {}
        for i, chunk in enumerate([sorted(allpics)[j:j + 200] for j in range(0, len(allpics), 200)]):
            if not chunk:
                continue
            marks = ','.join('?' * len(chunk))
            _, st = self._q(f'SELECT phcode, phcodestatus, piclock FROM {DB}.localcustomers WHERE phcode IN ({marks})', chunk)
            status.update({str(a).strip(): (b, c) for a, b, c in st})
        last = dict(PurchaseHistory.objects.filter(softech_phcode__in=allpics).values('softech_phcode')
                    .annotate(m=Max('invoice_date')).values_list('softech_phcode', 'm'))

        def ls(pic):
            d = last.get(pic)
            return d.date().isoformat() if d else 'no sale in mirror'
        self._emit(f'  {len(recs)} codes are not active ("1") or are locked:')
        suggested = []
        for r in recs:
            pic = str(r['phcode']).strip()
            self._emit(f'    {pic}: status={r["phcodestatus"]!r} lock={r["piclock"]} died={r["picdied"]} '
                       f'changed_by={r["phcodestatususercode"]} at={r["phcodestatustime"]} '
                       f'active_since={r["custdateactive"]} created_by={r["usercode"]} pphcode={r["pphcode"]!r} '
                       f'last_sale={ls(pic)}')
            for m in mates[pic][:8]:
                ms = status.get(m, (None, None))
                self._emit(f'        shares a phone with {m}: status={ms[0]!r} lock={ms[1]} last_sale={ls(m)}')
                if str(ms[0] or '').strip() == '1' and not ms[1]:
                    suggested.append((pic, m))
        if suggested:
            a, b = max(suggested, key=lambda x: (last.get(x[1]) is not None, last.get(x[1]) or 0))
            self._emit(f'  ▶ SUGGESTED PAIR to review in SOFTECH: {a} (not active) ↔ {b} (active, same phone)')
            self._emit(f'      then run: python manage.py investigate_pic_merge --pic {a} --pic {b}')
        else:
            self._emit('  ▶ no non-active code shares a phone with an active one — duplicates are NOT being '
                       'deactivated in SOFTECH today (they stay active side by side)')
        # pphcode — possible parent / main-PIC link
        _, r = self._q(f"SELECT count(*) FROM {DB}.localcustomers WHERE isnull(pphcode, '') <> ''")
        _, r2 = self._q(f"SELECT count(*) FROM {DB}.localcustomers WHERE isnull(pphcode, '') <> '' AND pphcode <> phcode")
        _, r3 = self._q(f"SELECT count(*) FROM {DB}.localcustomers l WHERE isnull(l.pphcode, '') <> '' "
                        f"AND l.pphcode <> l.phcode AND EXISTS (SELECT 1 FROM {DB}.localcustomers p WHERE p.phcode = l.pphcode)")
        self._emit(f'  pphcode filled on {r[0][0]} codes · pointing to ANOTHER code on {r2[0][0]} · '
                   f'of which the target exists as a customer: {r3[0][0]}')
        _, ex = self._q(f"SELECT phcode, pphcode, relativecode FROM {DB}.localcustomers "
                        "WHERE isnull(pphcode, '') <> '' AND pphcode <> phcode", limit=self.samples)
        for a, b, c in ex:
            self._emit(f'    {a} → pphcode {b} (relativecode {c})')
        _, rc = self._q(f'SELECT relativecode, count(*) FROM {DB}.localcustomers GROUP BY relativecode ORDER BY 2 DESC',
                        limit=10)
        self._emit('  relativecode values: ' + ', '.join(f'{v!r}={n}' for v, n in rc))

    def s_strength(self):
        """How many shared-phone pairs are TRUE duplicates (same person) vs a family sharing a phone.
        Names / addresses are compared, never printed."""
        cls, samples = Counter(), defaultdict(list)
        for phone, group in getattr(self, 'dup_groups', {}).items():
            g = sorted(group)
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    a, b = self.info.get(g[i], {}), self.info.get(g[j], {})
                    nm = _name_match(a.get('name'), b.get('name'))
                    ad = bool(_norm_text(a.get('addr'))) and _norm_text(a.get('addr')) == _norm_text(b.get('addr'))
                    k = ('same name + same address' if nm == 'same' and ad else 'same name' if nm == 'same'
                         else 'similar name' if nm == 'similar' else 'different names (family / shared phone?)')
                    cls[k] += 1
                    if len(samples[k]) < 5:
                        samples[k].append(f'{g[i]} ↔ {g[j]}')
        for k in ('same name + same address', 'same name', 'similar name', 'different names (family / shared phone?)'):
            self._emit(f'  {k}: {cls[k]} pairs   e.g. {", ".join(samples[k])}')
        self._emit('  (same name ± address on one phone = strong duplicate → merge queue; different names = '
                   'likely family members → NOT merged, possibly linked)')

    def s_links(self):
        """Forensics on codes whose pphcode points to ANOTHER code (owner: looks like concurrent-save
        accidents). Compares creation/modification times, users and data — names never printed."""
        cols = 'phcode, pphcode, branchcode, branchcustcode, usercode, custdate, custdateactive, trans_time, ' \
               'branchcustname, mobileno, branchcustaddress1, phcodestatus'
        cn, rows = self._q(f"SELECT {cols} FROM {DB}.localcustomers WHERE isnull(pphcode, '') <> '' AND pphcode <> phcode")
        links = [dict(zip(cn, r)) for r in rows]
        targets = sorted({str(l['pphcode']).strip() for l in links})
        tgt = {}
        for i in range(0, len(targets), 200):
            chunk = targets[i:i + 200]
            marks = ','.join('?' * len(chunk))
            cn2, rows2 = self._q(f'SELECT {cols} FROM {DB}.localcustomers WHERE phcode IN ({marks})', chunk)
            tgt.update({str(r[0]).strip(): dict(zip(cn2, r)) for r in rows2})

        def secs(a, b):
            try:
                return int(abs((a - b).total_seconds()))
            except Exception:
                return None
        quick = 0
        for l in links:
            t = tgt.get(str(l['pphcode']).strip(), {})
            d_create, d_mod = secs(l['custdate'], t.get('custdate')), secs(l['trans_time'], t.get('trans_time'))
            if d_create is not None and d_create <= 120:
                quick += 1
            self._emit(f"    {l['phcode']} → {l['pphcode']}: branch {l['branchcode']}/{t.get('branchcode')} · "
                       f"custno {l['branchcustcode']}/{t.get('branchcustcode')} · users {l['usercode']}/{t.get('usercode')} · "
                       f"created Δ{d_create}s ({l['custdate']}) · modified Δ{d_mod}s · "
                       f"name {_name_match(l['branchcustname'], t.get('branchcustname')) or 'DIFFERENT'} · "
                       f"phone {'same' if _norm_phone(l['mobileno']) and _norm_phone(l['mobileno']) == _norm_phone(t.get('mobileno')) else 'different'} · "
                       f"status {l['phcodestatus']!r}/{t.get('phcodestatus')!r}")
        self._emit(f'  {len(links)} links · created within 2 minutes of their target: {quick}')

    def s_relatives(self):
        """SOFTECH's family tables — the proper place for 'same phone, different person'."""
        for t in ('localcustomersrelatives', 'custpatientrelatives', 'custrelativespercent'):
            cols = self._columns(t)
            if not cols:
                self._emit(f'  {t}: (not found)')
                continue
            _, n = self._q(f'SELECT count(*) FROM {DB}.{t}')
            self._emit(f'  {t}: {n[0][0]} rows · ' + ', '.join(f'{c}:{ty}' for c, ty, _ in cols))
            if n[0][0]:
                cn, rows = self._q(f'SELECT * FROM {DB}.{t}', limit=3)
                for r in rows:
                    self._emit('    ' + str({c: v for c, v in zip(cn, r) if not re.search(r'name|address|phone|mobile', c, re.I)}))

    # ── run ───────────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_branch_connection, get_sybase_connection
        self._buf, self.samples, self.pics = [], o['samples'], [p.strip() for p in o['pic'] if p.strip()]
        self.points_log, self.phones_of, self.groups, self.info = o['points_log'], {}, {}, {}
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
            self._safe('[12] duplicate strength (same person vs family)', self.s_strength)
            if o['suggest']:
                self._safe('[11] non-active / locked codes, their phone-mates and the suggested pair', self.s_status)
                self._safe('[13] pphcode links — forensics', self.s_links)
                self._safe('[14] SOFTECH relatives tables', self.s_relatives)
            if self.pics:
                self._safe('[10] PIC side-by-side', self.s_pics)
        finally:
            self.conn.close()
        if o['out']:
            os.makedirs(os.path.dirname(o['out']) or '.', exist_ok=True)
            with open(o['out'], 'w', encoding='utf-8') as f:
                f.write('\n'.join(self._buf) + '\n')
            self.stdout.write(self.style.SUCCESS(f'\nWritten to {o["out"]}'))
