"""python manage.py import_gl_parties <xlsx> [--propose]"""
from django.core.management.base import BaseCommand

from apps.finance.gl.parties import import_parties, parse_party_sheets, propose_matches


class Command(BaseCommand):
    help = "Import finance's supplier / creditor / customer codes as GL parties."

    def add_arguments(self, parser):
        parser.add_argument('xlsx')
        parser.add_argument('--propose', action='store_true',
                            help='also propose SOFTECH matches by name (never confirms)')

    def handle(self, *args, **opts):
        rows = parse_party_sheets(opts['xlsx'])
        res = import_parties(rows, user=None)
        self.stdout.write(f"rows={len(rows)} created={res['created']} updated={res['updated']}")
        if opts['propose']:
            p = propose_matches(user=None)
            self.stdout.write(f"proposed exact={p['exact']} tokens={p['tokens']} none={p['none']}")
