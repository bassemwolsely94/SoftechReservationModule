"""Load the GPC brick list (code, English, Arabic) from the owner's GPC workbook. Adds and updates; never deletes."""
from django.core.management.base import BaseCommand, CommandError

from apps.tax_invoicing import gpc
from apps.tax_invoicing.services import audit


class Command(BaseCommand):
    help = 'Load GPC bricks from an xlsx with a "Brick Code" (or "BrickCode") column.'

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=None)
        parser.add_argument('--sheet', default=None)
        parser.add_argument('--gs1-json', default=None, help='GS1 GPC JSON (May 2026, v20260520) from gpc-browser.gs1.org')

    def handle(self, *args, **opts):
        if bool(opts['path']) == bool(opts['gs1_json']):
            raise CommandError('Give exactly one of: a workbook path, or --gs1-json PATH.')
        try:
            if opts['gs1_json']:
                result = gpc.load_gs1(gpc.read_gs1_json(opts['gs1_json']))
            else:
                result = gpc.load(gpc.read_workbook(opts['path'], opts['sheet']))
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        audit('gpc_bricks_loaded', actor=None, entity='gpc', after=result)
        self.stdout.write(f"read {result['read']} bricks: {result['created']} new, {result['updated']} updated")
