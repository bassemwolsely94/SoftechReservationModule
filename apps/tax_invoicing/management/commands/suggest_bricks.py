"""Ask the AI for a GPC brick proposal for uncoded queue items (biggest uncoded value first), or for one item.
Does nothing while TAX_GPC_AI_ENABLED is off. Proposals are only shown; a person confirms the brick."""
from django.core.management.base import BaseCommand, CommandError

from apps.tax_invoicing import gpc_ai
from apps.tax_invoicing.models import TaxItemProfile


class Command(BaseCommand):
    help = 'AI GPC brick proposals for uncoded items (needs TAX_GPC_AI_ENABLED)'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=200)
        parser.add_argument('--itemcode', default='')

    def handle(self, *args, limit, itemcode, **opts):
        if not gpc_ai.enabled():
            self.stdout.write('TAX_GPC_AI_ENABLED is off — nothing asked')
            return
        if itemcode:
            profile = TaxItemProfile.objects.filter(softech_itemcode=itemcode).first()
            if profile is None:
                raise CommandError(f'no tax profile for item {itemcode}')
            row = gpc_ai.suggest_one(profile)
            if row is None:
                self.stdout.write(f'{itemcode}: not asked (medicine or learned brick)')
            else:
                self.stdout.write(f'{itemcode}: {row.source} {row.brick} {row.confidence} {row.error}'.rstrip())
            return
        counts = gpc_ai.run(limit=limit)
        self.stdout.write(' '.join(f'{k} {v}' for k, v in sorted(counts.items())) or 'nothing to ask')
