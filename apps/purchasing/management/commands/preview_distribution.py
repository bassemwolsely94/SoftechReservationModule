"""
python manage.py preview_distribution                       # all four categories
python manage.py preview_distribution --category new_no_rate
python manage.py preview_distribution --limit 40

L3 «توزيعة» — READ-ONLY preview of proactive distribution suggestions from the latest
engine run (apps/purchasing/distribution.py). Never writes to SOFTECH.
"""
from django.core.management.base import BaseCommand

from apps.purchasing import distribution


class Command(BaseCommand):
    help = 'Preview L3 توزيعة distribution suggestions (read-only)'

    def add_arguments(self, parser):
        parser.add_argument('--category', action='append', default=None,
                            help='hq_dormant | over_piled | new_no_rate | never_stocked (repeatable)')
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *a, **o):
        sugs = distribution.analyze(categories=o.get('category'), limit=o['limit'])
        s = distribution.summary()
        self.stdout.write(self.style.MIGRATE_HEADING('\n═══ توزيعة — distribution preview ═══'))
        self.stdout.write(f'  total suggestions: {s["total"]}')
        for cat, v in s['by_category'].items():
            self.stdout.write(f'    {cat}: {v["count"]} items, {v["qty"]} packs')
        self.stdout.write('')
        for g in sugs[:o['limit']]:
            tgts = ', '.join(f'{t["code"]}×{t.get("qty", g["qty_each"])}' for t in g['to_branches'])
            age = f'{g["age_days"]}d' if g.get('age_days') is not None else '?'
            newc = '🆕' if g.get('is_new_code') else '  '
            self.stdout.write(
                f'  [{g["category"]:<13}] {newc} {g["itemcode"]:<8} {(g["item_name"] or "")[:28]:<28} '
                f'{g["from_branch"]}⟶[{tgts}]  '
                f'sells@{g["sells_at"]}/{g["of_branches"]} age={age} avg={g["network_avg"]} '
                f'[{",".join(g.get("signals", []))}]')
