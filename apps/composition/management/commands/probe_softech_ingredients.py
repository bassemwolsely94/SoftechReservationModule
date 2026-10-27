"""
Read-only SOFTECH probe for the active-ingredient subsystem.

Discovers the exact schema our code does NOT yet cover — the class taxonomy
table/column, the real ``itemsai`` columns, and (critically for the later
cleanup phase) whether INSERT/UPDATE/DELETE triggers or FK references exist on
``activeingredients`` / ``itemsai`` that would revert or cascade our writes.

STRICTLY READ-ONLY. It runs only SELECTs (plus ``SET ROWCOUNT`` to bound
samples). ``--mirror`` additionally copies the SOFTECH master into our Postgres
mirror tables (still a SOFTECH read; writes go only to our own DB).

    python manage.py probe_softech_ingredients
    python manage.py probe_softech_ingredients --mirror
    python manage.py probe_softech_ingredients --samples 40 --out scratch/ai_probe.txt
"""
import os

from django.core.management.base import BaseCommand

DB = 'SOFTECHDB9.dbo'
CLASS_HINTS = ('class', 'type', 'categ', 'group')
# activeingredients.classcode → basic_data.bdatacode WHERE bdatasno=600 → bdataname
AI_CLASS_BDATASNO = 600


class Command(BaseCommand):
    help = 'Read-only probe of the SOFTECH active-ingredient tables (schema + integrity).'

    def add_arguments(self, parser):
        parser.add_argument('--samples', type=int, default=20,
                            help='How many sample rows to dump per table (default 20).')
        parser.add_argument('--mirror', action='store_true',
                            help='Also copy the SOFTECH master into our Postgres mirror tables.')
        parser.add_argument('--out', type=str, default='',
                            help='Optional file path to also write the report to.')
        parser.add_argument('--find-class', action='store_true',
                            help='Content-search every table for the AI-class name lookup '
                                 '(classcode 1-23 → SGLT2 INHIBITORS, etc.).')
        parser.add_argument('--class-group', action='store_true',
                            help='Locate + dump the AI-class group inside basic_data '
                                 '(the bdatasno holding SGLT2 INHIBITORS, etc.).')

    # ── output helpers ────────────────────────────────────────────────────────
    def _emit(self, line=''):
        self.stdout.write(line)
        if self._buf is not None:
            self._buf.append(line)

    def _cols(self, cur, table):
        """Return the column-name list of a table via a bounded SELECT."""
        try:
            cur.execute('SET ROWCOUNT 1')
            cur.execute(f'SELECT * FROM {DB}.{table}')
            cur.fetchall()
            names = [d[0] for d in cur.description]
            cur.execute('SET ROWCOUNT 0')
            return names
        except Exception as exc:
            cur.execute('SET ROWCOUNT 0')
            self._emit(f'  ! could not read columns of {table}: {str(exc)[:120]}')
            return []

    def _scalar(self, cur, sql):
        cur.execute(sql)
        row = cur.fetchone()
        return row[0] if row else None

    def handle(self, *args, **opts):
        from config.sybase import get_sybase_connection

        self._buf = [] if opts['out'] else None
        samples = opts['samples']

        self._emit('=' * 72)
        self._emit('SOFTECH ACTIVE-INGREDIENT PROBE (read-only)')
        self._emit('=' * 72)

        conn = get_sybase_connection()
        cur = conn.cursor()

        # 1) Column layouts ----------------------------------------------------
        ai_cols = self._cols(cur, 'activeingredients')
        ia_cols = self._cols(cur, 'itemsai')
        self._emit('\n[activeingredients] columns:')
        self._emit('  ' + (', '.join(ai_cols) or '(none)'))
        self._emit('\n[itemsai] columns:')
        self._emit('  ' + (', '.join(ia_cols) or '(none)'))

        class_col = next((c for c in ai_cols
                          if any(h in c.lower() for h in CLASS_HINTS)), '')
        self._emit(f'\n  → candidate class column on activeingredients: '
                   f'{class_col or "(none detected — class may live in a separate table)"}')

        # 2) Related tables (class taxonomy lives somewhere) -------------------
        self._emit('\n[related tables] (sysobjects search):')
        try:
            cur.execute(
                f"SELECT name FROM {DB}.sysobjects WHERE type='U' AND ("
                "name LIKE '%activeingredient%' OR name LIKE '%aiclass%' OR "
                "name LIKE '%ai_class%' OR name LIKE 'itemsai%' OR "
                "name LIKE '%ingredientclass%' OR name LIKE '%aitype%') "
                "ORDER BY name"
            )
            for r in cur.fetchall():
                self._emit(f'  - {r[0]}')
        except Exception as exc:
            self._emit(f'  ! sysobjects search failed: {str(exc)[:120]}')

        # 2b) Where do the class NAMES live? classcode on activeingredients FKs
        #     to some lookup table — find it by column name, then sample it.
        self._emit('\n[class lookup] tables carrying a class-code/name column:')
        try:
            cur.execute(
                "SELECT DISTINCT o.name, c.name FROM "
                f"{DB}.syscolumns c JOIN {DB}.sysobjects o ON o.id = c.id "
                "WHERE o.type='U' AND (c.name LIKE '%classcode%' OR "
                "c.name LIKE '%classname%' OR c.name LIKE '%aiclass%') "
                "ORDER BY o.name"
            )
            rows = cur.fetchall()
            if not rows:
                self._emit('  (no class-code/name columns found)')
            for r in rows:
                self._emit(f'  {r[0]}.{r[1]}')
        except Exception as exc:
            self._emit(f'  ! class-column search failed: {str(exc)[:120]}')
        try:
            cur.execute(
                f"SELECT name FROM {DB}.sysobjects WHERE type='U' AND "
                "(name LIKE '%class%' OR name LIKE '%aiclassif%') ORDER BY name")
            class_tables = [r[0] for r in cur.fetchall()]
            self._emit('  class-like tables: ' + (', '.join(class_tables) or '(none)'))
            for t in class_tables[:8]:
                try:
                    cur.execute('SET ROWCOUNT 5')
                    cur.execute(f'SELECT * FROM {DB}.{t}')
                    sample = cur.fetchall()
                    cols = [d[0] for d in cur.description]
                    cur.execute('SET ROWCOUNT 0')
                    self._emit(f'    [{t}] cols: {", ".join(cols)}')
                    for s in sample:
                        self._emit('      ' + ' | '.join('' if v is None else str(v) for v in s))
                except Exception as exc:
                    cur.execute('SET ROWCOUNT 0')
                    self._emit(f'    ! {t} sample failed: {str(exc)[:80]}')
        except Exception as exc:
            self._emit(f'  ! class-table search failed: {str(exc)[:120]}')

        # 2c) Is classcode actually populated, and what's the value domain? ----
        try:
            n_cc = self._scalar(
                cur, f"SELECT count(*) FROM {DB}.activeingredients "
                     "WHERE classcode IS NOT NULL AND classcode != ''")
            self._emit(f'\n  activeingredients rows with a NON-EMPTY classcode: {n_cc}')
            if n_cc:
                cur.execute('SET ROWCOUNT 15')
                cur.execute(f"SELECT classcode, count(*) FROM {DB}.activeingredients "
                            "WHERE classcode IS NOT NULL AND classcode != '' "
                            "GROUP BY classcode ORDER BY classcode")
                for r in cur.fetchall():
                    self._emit(f'    classcode {r[0]}: {r[1]} rows')
                cur.execute('SET ROWCOUNT 0')
        except Exception as exc:
            cur.execute('SET ROWCOUNT 0')
            self._emit(f'  ! classcode usage check failed: {str(exc)[:100]}')

        # 2d) Wider hunt for the AI-class taxonomy table -----------------------
        try:
            cur.execute(
                f"SELECT name FROM {DB}.sysobjects WHERE type='U' AND ("
                "name LIKE 'ai%' OR name LIKE '%ingredient%' OR name LIKE '%inn%' "
                "OR name LIKE '%atc%' OR name LIKE '%therap%' OR name LIKE '%pharma%' "
                "OR name LIKE '%moa%' OR name LIKE '%mechanism%') ORDER BY name")
            self._emit('  wider AI/class table hunt: '
                       + (', '.join(r[0] for r in cur.fetchall()) or '(none)'))
        except Exception as exc:
            self._emit(f'  ! wide hunt failed: {str(exc)[:100]}')

        # 2e) SOFTECH's OWN migration columns — show populated examples --------
        try:
            cur.execute('SET ROWCOUNT 15')
            cur.execute(
                f'SELECT aicode, ainame, [ainame new modified], [aicode new modified] '
                f'FROM {DB}.activeingredients '
                f"WHERE [ainame new modified] IS NOT NULL AND [ainame new modified] != ''")
            rows = cur.fetchall()
            cur.execute('SET ROWCOUNT 0')
            self._emit(f'\n[new-modified] {len(rows)} sample rows where SOFTECH '
                       'populated "ainame new modified":')
            for r in rows:
                self._emit('  ' + ' | '.join('' if v is None else str(v) for v in r))
        except Exception as exc:
            cur.execute('SET ROWCOUNT 0')
            self._emit(f'  ! new-modified sample failed: {str(exc)[:100]}')

        # 2f) Deep content-search for the class-name lookup table (opt-in) -----
        if opts['find_class']:
            self._find_class_table(cur)

        # 2g) Dump the AI-class group inside basic_data (opt-in) --------------
        if opts['class_group']:
            self._dump_class_group(cur)

        # 3) Triggers on the two tables (do our future writes get reverted?) ---
        self._emit('\n[triggers] on activeingredients / itemsai:')
        try:
            cur.execute(
                "SELECT t.name, d.name, i.name, u.name FROM "
                f"{DB}.sysobjects t "
                f"LEFT JOIN {DB}.sysobjects d ON d.id = t.deltrig "
                f"LEFT JOIN {DB}.sysobjects i ON i.id = t.instrig "
                f"LEFT JOIN {DB}.sysobjects u ON u.id = t.updtrig "
                "WHERE t.name IN ('activeingredients','itemsai')"
            )
            for r in cur.fetchall():
                self._emit(f'  {r[0]}: del={r[1] or "-"} ins={r[2] or "-"} upd={r[3] or "-"}')
        except Exception as exc:
            self._emit(f'  ! trigger probe failed: {str(exc)[:120]}')

        # 4) FK references touching them (delete cascade / block risk) ---------
        self._emit('\n[references] involving activeingredients / itemsai:')
        try:
            cur.execute(
                "SELECT object_name(tableid), object_name(reftabid) "
                f"FROM {DB}.sysreferences "
                "WHERE object_name(reftabid) IN ('activeingredients','itemsai') "
                "   OR object_name(tableid) IN ('activeingredients','itemsai')"
            )
            rows = cur.fetchall()
            if not rows:
                self._emit('  (no declared FK references found)')
            for r in rows:
                self._emit(f'  {r[0]} → references → {r[1]}')
        except Exception as exc:
            self._emit(f'  ! reference probe failed: {str(exc)[:120]}')

        # 5) Integrity counts --------------------------------------------------
        self._emit('\n[counts]')
        try:
            n_ai = self._scalar(cur, f'SELECT count(*) FROM {DB}.activeingredients')
            n_ia = self._scalar(cur, f'SELECT count(*) FROM {DB}.itemsai')
            n_ai_used = self._scalar(
                cur, f'SELECT count(DISTINCT aicode) FROM {DB}.itemsai')
            n_orphan = self._scalar(
                cur,
                f'SELECT count(DISTINCT ia.aicode) FROM {DB}.itemsai ia '
                f'WHERE NOT EXISTS (SELECT 1 FROM {DB}.activeingredients ai '
                'WHERE ai.aicode = ia.aicode)')
            self._emit(f'  activeingredients rows ........ {n_ai}')
            self._emit(f'  itemsai links ................. {n_ia}')
            self._emit(f'  distinct AIs used by items .... {n_ai_used}')
            self._emit(f'  AIs unused (deletable safely) . '
                       f'{(n_ai - n_ai_used) if (n_ai and n_ai_used) else "?"}')
            self._emit(f'  ORPHAN aicodes in itemsai ..... {n_orphan}  '
                       f'(referenced by items but missing from master)')
        except Exception as exc:
            self._emit(f'  ! count probe failed: {str(exc)[:120]}')

        # 6) Sample rows -------------------------------------------------------
        self._emit(f'\n[sample] first {samples} activeingredients rows:')
        try:
            cur.execute(f'SET ROWCOUNT {samples}')
            cur.execute(f'SELECT * FROM {DB}.activeingredients')
            rows = cur.fetchall()
            cur.execute('SET ROWCOUNT 0')
            for r in rows:
                self._emit('  ' + ' | '.join('' if v is None else str(v) for v in r))
        except Exception as exc:
            cur.execute('SET ROWCOUNT 0')
            self._emit(f'  ! sample failed: {str(exc)[:120]}')

        # 7) Optional mirror into our Postgres --------------------------------
        if opts['mirror']:
            try:
                self._mirror(cur, ai_cols)
            except Exception as exc:
                self._emit(f'\n[mirror] FAILED: {str(exc)[:200]}')
                self._emit('  → apply migrations first:  '
                           'python manage.py migrate composition && python manage.py migrate chronic')

        conn.close()

        if self._buf is not None:
            d = os.path.dirname(opts['out'])
            if d:
                os.makedirs(d, exist_ok=True)
            with open(opts['out'], 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(self._buf))
            self.stdout.write(self.style.SUCCESS(f'\nReport also written to {opts["out"]}'))

        self._emit('\nDone (read-only).')

    # ── deep class-table hunt --------------------------------------------------
    def _find_class_table(self, cur):
        """
        Find the table that maps classcode 1-23 → class name by CONTENT, since it
        isn't named/columned with 'class'. Two passes: (1) brute-force likely
        table names; (2) scan every user table's first rows for class-name tokens.
        """
        self._emit('\n[find-class] deep hunt for the AI-class name table ...')
        HINTS = ('INHIBITOR', 'BLOCKER', 'ANTAGONIST', 'AGONIST', 'STATIN',
                 'DIURETIC', 'ADRENERGIC', 'GLUCOSIDASE', 'BIGUANIDE',
                 'SULFONYLUREA', 'SULPHONYLUREA', 'MEGLITINIDE', 'MACR')
        # skip the big transactional tables — content-scanning them is pure noise
        SKIP = ('items', 'itemsbal', 'stktrans', 'stktransm', 'customers',
                'personsdata', 'localcustomers', 'purchase', 'sales', 'branchesales')

        def _dump(t, rows, cols, marker='  '):
            self._emit(f'{marker}[{t}] cols: {", ".join(cols)}')
            for r in rows:
                self._emit(f'{marker}   ' + ' | '.join('' if v is None else str(v) for v in r))

        # 1) brute-force candidate names
        candidates = [
            'aiclasses', 'aiclass', 'aiclassif', 'aiclassifs', 'aiclassification',
            'aiclassifications', 'activeingredientclass', 'activeingredientsclass',
            'activeingredientclasses', 'ingredientclass', 'ingredientsclass',
            'ingredientclasses', 'medclass', 'medclasses', 'drugclass', 'drugclasses',
            'pharmaclass', 'therapclass', 'atcclass', 'maingroups', 'aigroups',
            'aicategories', 'aitypes', 'aitype', 'ainame', 'ainames', 'ainameclass',
        ]
        self._emit('  pass 1 — brute-force candidate table names:')
        for t in candidates:
            try:
                cur.execute('SET ROWCOUNT 5')
                cur.execute(f'SELECT * FROM {DB}.{t}')
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                cur.execute('SET ROWCOUNT 0')
                _dump(t, rows, cols, marker='  ✓ ')
            except Exception:
                cur.execute('SET ROWCOUNT 0')

        # 2) content-scan every (non-huge) user table
        try:
            cur.execute(f"SELECT name FROM {DB}.sysobjects WHERE type='U' ORDER BY name")
            tables = [r[0] for r in cur.fetchall()]
        except Exception as exc:
            self._emit(f'  ! could not list tables: {str(exc)[:100]}')
            return
        self._emit(f'  pass 2 — content-scanning {len(tables)} user tables for class-name tokens ...')
        found = 0
        for t in tables:
            low = t.lower()
            if any(s in low for s in SKIP):
                continue
            try:
                cur.execute('SET ROWCOUNT 60')
                cur.execute(f'SELECT * FROM {DB}.{t}')
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                cur.execute('SET ROWCOUNT 0')
            except Exception:
                cur.execute('SET ROWCOUNT 0')
                continue
            hit = any(
                isinstance(v, str) and any(h in v.upper() for h in HINTS)
                for r in rows for v in r
            )
            if hit:
                found += 1
                _dump(t, rows[:30], cols, marker='  ★ ')
        if not found:
            self._emit('  (no table contained class-name tokens — names may be app-side)')

    # ── AI-class group inside basic_data --------------------------------------
    def _dump_class_group(self, cur):
        """
        The AI-class names live in basic_data (SOFTECH's shared dropdown store),
        partitioned by bdatasno. Find the group holding pharmacology class names
        and dump it — that bdatasno + bdatacode is what activeingredients.classcode
        (1-23) points at.
        """
        self._emit('\n[class-group] locating AI classes inside basic_data ...')
        try:
            cur.execute(
                f"SELECT DISTINCT bdatasno FROM {DB}.basic_data WHERE "
                "upper(bdataname) LIKE '%INHIBITOR%' OR upper(bdataname) LIKE '%BLOCKER%' "
                "OR upper(bdataname) LIKE '%ANTAGONIST%' OR upper(bdataname) LIKE '%SGLT2%' "
                "OR upper(bdataname) LIKE '%BIGUANIDE%' OR upper(bdataname) LIKE '%STATINS%'")
            groups = [r[0] for r in cur.fetchall()]
        except Exception as exc:
            self._emit(f'  ! basic_data query failed: {str(exc)[:120]}')
            return
        self._emit(f'  candidate bdatasno groups: {groups or "(none)"}')
        for g in groups:
            try:
                cur.execute(
                    f'SELECT bdatacode, bdataname, bdatanamearabic FROM {DB}.basic_data '
                    'WHERE bdatasno = ? ORDER BY bdatacode', [g])
                rows = cur.fetchall()
                self._emit(f'\n  bdatasno={g}  ({len(rows)} rows):')
                for r in rows:
                    self._emit(f'    {r[0]} | {r[1]} | {r[2] or ""}')
            except Exception as exc:
                self._emit(f'  ! dump of group {g} failed: {str(exc)[:100]}')

    # ── class taxonomy mirror --------------------------------------------------
    def _mirror_classes(self, cur):
        """basic_data[bdatasno=600] → SoftechIngredientClassRaw. Returns {code: name}."""
        from apps.composition.models import SoftechIngredientClassRaw
        classmap = {}
        try:
            cur.execute(
                f'SELECT bdatacode, bdataname, bdatanamearabic FROM {DB}.basic_data '
                f'WHERE bdatasno = {AI_CLASS_BDATASNO} ORDER BY bdatacode')
            rows = cur.fetchall()
        except Exception as exc:
            self._emit(f'  ! class mirror read failed: {str(exc)[:120]}')
            return classmap
        for r in rows:
            code = ('' if r[0] is None else str(r[0])).strip()
            name = (r[1] or '').strip()
            if not code:
                continue
            classmap[code] = name
            SoftechIngredientClassRaw.objects.update_or_create(
                softech_code=code, defaults={'name': name[:200]})
        self._emit(f'  mirrored {len(classmap)} AI classes (basic_data bdatasno={AI_CLASS_BDATASNO}).')
        return classmap

    # ── mirror -----------------------------------------------------------------
    def _mirror(self, cur, ai_cols):
        """Copy every activeingredients row verbatim into our Postgres mirror.

        Selects ALL discovered columns (bracket-quoted, since SOFTECH has names
        with spaces like "ainame new modified") so nothing is silently dropped —
        unmodeled columns land in ``extra`` for later reconciliation.
        """
        from django.utils import timezone
        from apps.composition.models import SoftechIngredientRaw

        self._emit('\n[mirror] copying activeingredients → SoftechIngredientRaw ...')
        # Mirror the class taxonomy first so we can resolve classcode → name.
        classmap = self._mirror_classes(cur)
        # item counts per aicode
        cur.execute(f'SELECT aicode, count(*) FROM {DB}.itemsai GROUP BY aicode')
        counts = {int(r[0]): int(r[1]) for r in cur.fetchall() if r[0] is not None}

        collist = ', '.join('[' + c + ']' for c in ai_cols)
        cur.execute(f'SELECT {collist} FROM {DB}.activeingredients')
        rows = cur.fetchall()

        known = {'aicode', 'ainame', 'classcode', 'usercode', 'modif_lastupdate'}
        now = timezone.now()
        created = updated = 0
        for r in rows:
            rec = {ai_cols[i]: r[i] for i in range(len(ai_cols))}
            try:
                aicode = int(rec.get('aicode'))
            except (TypeError, ValueError):
                continue
            ainame = rec.get('ainame')
            ainame = (ainame if isinstance(ainame, str) else str(ainame or '')).strip()
            classcode = rec.get('classcode')
            classcode = ('' if classcode is None else str(classcode)).strip()
            # Preserve SOFTECH's own migration columns (aicode/ainame "new modified").
            extra = {k: (None if v is None else str(v))
                     for k, v in rec.items() if k not in known}
            _, was_created = SoftechIngredientRaw.objects.update_or_create(
                aicode=aicode,
                defaults={
                    'ainame': ainame[:300],
                    'class_code': classcode[:20],
                    'class_name': classmap.get(classcode, '')[:200],
                    'item_count': counts.get(aicode, 0),
                    'extra': extra,
                    'synced_at': now,
                },
            )
            created += was_created
            updated += (not was_created)
        self._emit(f'  mirrored {len(rows)} rows → {created} created, {updated} updated.')
        self._mirror_itemsai(cur)

    def _mirror_itemsai(self, cur):
        """itemsai → SoftechItemAI (full refresh; powers the Track A search index)."""
        from apps.composition.models import SoftechItemAI
        self._emit('[mirror] copying itemsai → SoftechItemAI ...')
        cur.execute(f'SELECT itemcode, aicode, aiblock FROM {DB}.itemsai')
        rows = cur.fetchall()
        objs, seen = [], set()
        for r in rows:
            icode = str(r[0] or '').strip()
            try:
                aicode = int(r[1])
            except (TypeError, ValueError):
                continue
            if not icode:
                continue
            key = (icode, aicode)
            if key in seen:
                continue
            seen.add(key)
            blocked = str(r[2] or '').strip() == '1'
            objs.append(SoftechItemAI(item_softech_id=icode, aicode=aicode, is_blocked=blocked))
        SoftechItemAI.objects.all().delete()
        SoftechItemAI.objects.bulk_create(objs, batch_size=1000)
        self._emit(f'  mirrored {len(objs)} itemsai links.')
