"""python manage.py import_gl_parties <xlsx> [--create-only] [--propose]"""
from django.core.management.base import BaseCommand

from apps.finance.gl.parties import import_parties, parse_party_sheets, propose_matches


class Command(BaseCommand):
    help = ("Import finance's supplier / creditor / customer codes (and the 2020 master sheets: "
            "suppliers, employees, customers) as GL parties.")

    def add_arguments(self, parser):
        parser.add_argument('xlsx')
        parser.add_argument('--create-only', action='store_true',
                            help='only add missing codes; never rename an existing party (Ruling P26)')
        parser.add_argument('--propose', action='store_true',
                            help='also propose SOFTECH matches by name (never confirms)')

    def handle(self, *args, **opts):
        rows = parse_party_sheets(opts['xlsx'])
        res = import_parties(rows, user=None, create_only=opts['create_only'])
        self.stdout.write(f"rows={len(rows)} created={res['created']} updated={res['updated']}")
        if res['master_skipped']:
            self.stdout.write(f"skipped {res['master_skipped']} master-sheet rows ({', '.join(res['master_sheets'])}): "
                              'master sheets are imported only with --create-only')
        if opts['propose']:
            p = propose_matches(user=None)
            self.stdout.write(f"proposed exact={p['exact']} tokens={p['tokens']} none={p['none']}")
