"""Load the GPC brick list (code, English, Arabic) from the owner's GPC workbook. Adds and updates; never deletes."""
from django.core.management.base import BaseCommand, CommandError

from apps.tax_invoicing import gpc
from apps.tax_invoicing.services import audit


class Command(BaseCommand):
    help = 'Load GPC bricks from an xlsx with a "Brick Code" (or "BrickCode") column.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--sheet', default=None)

    def handle(self, *args, **opts):
        try:
            rows = gpc.read_workbook(opts['path'], opts['sheet'])
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        result = gpc.load(rows)
        audit('gpc_bricks_loaded', actor=None, entity='gpc', after=result)
        self.stdout.write(f"read {result['read']} bricks: {result['created']} new, {result['updated']} updated")
