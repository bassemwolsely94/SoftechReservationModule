"""
manage.py replacement_purchase_golden 130/12095/2026-07-21 [more…] [--json exports/golden.json]

B1 pilot readiness (doc 25 §21): compare natively-posted virtual-supplier purchases with what the
module's purchase leg would send. READ-ONLY on SOFTECH; nothing is kept in PG.
"""
import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.replacement import golden


class Command(BaseCommand):
    help = 'Golden-template diff: native virtual-supplier purchase vs the replacement purchase plan (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('docs', nargs='+', help='BRANCH/DOCNUMBER/YYYY-MM-DD')
        parser.add_argument('--json', default='', help='also write the full report to this path')

    def handle(self, *args, **o):
        reports = []
        for spec in o['docs']:
            try:
                br, no, day = spec.split('/')
                rep = golden.compare(br.strip(), int(no), date.fromisoformat(day))
            except ValueError as exc:
                raise CommandError(f'{spec}: {exc}')
            reports.append(rep)
            d = rep['diff']
            self.stdout.write(f"\n{rep['native']} supplier {rep['supplier']} · native {rep['native_value']} · "
                              f"ours {rep['plan_value']} · {'IDENTICAL' if d['identical'] else 'DIFFERS'}")
            for n in rep['price_notes']:
                self.stdout.write(f'  note: {n}')
            for h in d['header']:
                self.stdout.write(f"  header {h['field']}: native={h['native']} ours={h['ours']}")
            for ln in d['lines']:
                self.stdout.write(f"  line {ln['itemcode']} {ln['field']}: native={ln['native']} ours={ln['ours']}")
            if d['missing_lines'] or d['extra_lines']:
                self.stdout.write(f"  items only native {d['missing_lines']} · only ours {d['extra_lines']}")
        if o['json']:
            p = Path(o['json'])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            self.stdout.write(f'\nreport → {p}')
