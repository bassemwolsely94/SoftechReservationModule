"""Mirrors the code-usage history ETA holds. Reads ETA only. --probe fetches one page, prints its shape, stores nothing."""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.tax_invoicing import eta_codes
from apps.tax_invoicing.eta_client import _json
from apps.tax_invoicing.eta_reader import SYSTEMS, EtaReader


class Command(BaseCommand):
    help = 'eta_code_usages --system production [--probe]'

    def add_arguments(self, parser):
        parser.add_argument('--system', required=True, choices=SYSTEMS)
        parser.add_argument('--probe', action='store_true', help='one page, print the shape, write nothing')

    def handle(self, *args, **o):
        system = o['system']
        reader = EtaReader(system)
        if not reader.enabled():
            raise CommandError(reader.why_not())
        if o['probe']:
            r = reader.get(eta_codes.PATH, {'Ps': 100, 'Pn': 1, 'OrderDirections': 'Descending'})
            body = _json(r)
            rows = eta_codes._rows(body)
            self.stdout.write(f'HTTP {r.status_code}; rows on page: {len(rows)}')
            if isinstance(body, dict):
                self.stdout.write('body keys: ' + ', '.join(sorted(body)))
                meta = {k: v for k, v in body.items() if not isinstance(v, (list, dict))}
                self.stdout.write('metadata: ' + json.dumps(meta, ensure_ascii=False))
            if rows:
                self.stdout.write('first row: ' + json.dumps(rows[0], ensure_ascii=False, default=str))
            return
        self.stdout.write(str(eta_codes.fetch(system)))
