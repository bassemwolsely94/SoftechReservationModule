"""
Derive the candidate unit set from real SOFTECH active-ingredient names.

Instead of hard-coding which strength units exist, this scans the actual
``ainame`` strings, pulls every "<number><token>" occurrence, and reports the
token frequencies so the owner can APPROVE the authoritative unit list. The
approved set then replaces the provisional list in ``parser.PROVISIONAL_UNITS``.

    python manage.py derive_ingredient_units                 # from the PG mirror
    python manage.py derive_ingredient_units --source live   # straight from SOFTECH
    python manage.py derive_ingredient_units --top 60 --out scratch/units.txt
"""
import re
from collections import Counter

from django.core.management.base import BaseCommand

from apps.composition.parser import PROVISIONAL_UNITS

# number  +  unit-ish token (letters/%/ratio, may include digits for "mg/5ml")
_TOKEN = re.compile(r'\d+(?:[.,]\d+)?\s*([A-Za-z%][A-Za-z0-9%/.]*)')


class Command(BaseCommand):
    help = 'Report strength-unit token frequencies from real ainame data for approval.'

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['mirror', 'live'], default='mirror',
                            help="'mirror' = SoftechIngredientRaw (default); 'live' = SOFTECH.")
        parser.add_argument('--top', type=int, default=50, help='How many tokens to list.')
        parser.add_argument('--min', type=int, default=1, help='Minimum frequency to include.')
        parser.add_argument('--out', type=str, default='', help='Optional file to also write to.')

    def _names(self, source):
        if source == 'mirror':
            from apps.composition.models import SoftechIngredientRaw
            names = list(SoftechIngredientRaw.objects.values_list('ainame', flat=True))
            if names:
                return names
            self.stdout.write(self.style.WARNING(
                'Mirror is empty — run `probe_softech_ingredients --mirror` first, '
                'or use --source live.'))
            return []
        # live
        from config.sybase import get_sybase_connection
        conn = get_sybase_connection()
        cur = conn.cursor()
        cur.execute("SELECT ainame FROM SOFTECHDB9.dbo.activeingredients "
                    "WHERE ainame IS NOT NULL AND ainame != ''")
        names = [r[0] for r in cur.fetchall()]
        conn.close()
        return names

    def handle(self, *args, **opts):
        names = self._names(opts['source'])
        if not names:
            self.stdout.write(self.style.ERROR('No names to scan.'))
            return

        counter = Counter()
        examples = {}
        for name in names:
            for m in _TOKEN.finditer(name or ''):
                tok = m.group(1).lower().rstrip('.')
                if not tok:
                    continue
                counter[tok] += 1
                examples.setdefault(tok, name.strip())

        known = {u.lower() for u in PROVISIONAL_UNITS}
        lines = []
        lines.append('=' * 68)
        lines.append(f'UNIT TOKEN FREQUENCIES  (scanned {len(names)} names, '
                     f'{len(counter)} distinct tokens)')
        lines.append('=' * 68)
        lines.append(f'{"token":<12}{"count":>8}   {"status":<9} example')
        lines.append('-' * 68)
        for tok, cnt in counter.most_common(opts['top']):
            if cnt < opts['min']:
                break
            status = 'known' if tok in known else 'NEW'
            lines.append(f'{tok:<12}{cnt:>8}   {status:<9} {examples.get(tok, "")[:34]}')

        new_tokens = [t for t, c in counter.items()
                      if t not in known and c >= opts['min']]
        lines.append('-' * 68)
        lines.append(f'NEW tokens not in the provisional set ({len(new_tokens)}): '
                     + ', '.join(sorted(new_tokens)[:40]))
        lines.append('')
        lines.append('→ Review this list and reply with the approved unit set; I will bake')
        lines.append('  it into parser.PROVISIONAL_UNITS and regenerate candidates.')

        report = '\n'.join(lines)
        self.stdout.write(report)
        if opts['out']:
            import os
            d = os.path.dirname(opts['out'])
            if d:
                os.makedirs(d, exist_ok=True)
            with open(opts['out'], 'w', encoding='utf-8') as fh:
                fh.write(report)
            self.stdout.write(self.style.SUCCESS(f'\nWritten to {opts["out"]}'))
