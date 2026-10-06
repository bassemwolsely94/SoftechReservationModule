"""
python manage.py generate_transfer_isr                       # from latest TransferRecommendationRun
python manage.py generate_transfer_isr --from 160 --to 130   # only this surplus→deficit pair
python manage.py generate_transfer_isr --min-qty 2 --max-pairs 20

L2 — inter-branch allocation. Reads the demand engine's deficit↔surplus transfer
recommendations (apps/purchasing/transfer_engine.py → TransferRecommendation) and
creates, per (surplus A → deficit B) pair, TWO linked ISR proposals:
  leg 1: A → HQ (branch_to_hq)   — surplus branch prepares, ships to HQ for revision
  leg 2: HQ → B (hq_to_branch)   — HQ prepares, ships to the deficit branch
Both land as PG proposals for human review + approval + push in /supply (on-request).
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from apps.purchasing.models import TransferRecommendationRun, TransferRecommendation
from apps.purchasing import isr_writer


class Command(BaseCommand):
    help = 'Create two-leg (A→HQ, HQ→B) ISR proposals from TransferEngine recommendations'

    def add_arguments(self, parser):
        parser.add_argument('--run', type=int, default=None, help='TransferRecommendationRun id (default: latest)')
        parser.add_argument('--from', dest='from_branch', default=None, help='restrict to this surplus branch')
        parser.add_argument('--to', dest='to_branch', default=None, help='restrict to this deficit branch')
        parser.add_argument('--min-qty', type=float, default=1.0, dest='min_qty')
        parser.add_argument('--max-pairs', type=int, default=None, dest='max_pairs')

    def handle(self, *a, **o):
        run = (TransferRecommendationRun.objects.get(pk=o['run']) if o.get('run')
               else TransferRecommendationRun.objects.filter(status='success').order_by('-id').first())
        if run is None:
            raise CommandError('No successful TransferRecommendationRun — run the demand engine first.')

        qs = (TransferRecommendation.objects.filter(run=run)
              .select_related('item', 'from_branch', 'to_branch')
              .only('quantity', 'item__softech_id', 'from_branch__softech_branch_id',
                    'to_branch__softech_branch_id'))
        if o.get('from_branch'):
            qs = qs.filter(from_branch__softech_branch_id=str(o['from_branch']))
        if o.get('to_branch'):
            qs = qs.filter(to_branch__softech_branch_id=str(o['to_branch']))

        # group items by (surplus A, deficit B)
        pairs = defaultdict(list)
        for r in qs.iterator():
            a = r.from_branch.softech_branch_id if r.from_branch_id else None
            b = r.to_branch.softech_branch_id if r.to_branch_id else None
            code = str(r.item.softech_id or '').strip() if r.item_id else ''
            q = float(r.quantity or 0)
            if a and b and code and q >= o['min_qty']:
                pairs[(a, b)].append((code, q))

        if not pairs:
            self.stdout.write(self.style.WARNING('No transfer recommendations match — nothing to allocate.'))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ generate_transfer_isr — run {run.id} — {len(pairs)} (A→B) pair(s) ═══'))
        made = 0
        for (a, b), items in sorted(pairs.items(), key=lambda kv: -len(kv[1])):
            if o.get('max_pairs') and made >= o['max_pairs']:
                break
            try:
                leg1, leg2 = isr_writer.create_transfer_proposals(a, b, items)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  {a}→HQ→{b}: FAILED — {str(exc)[:120]}'))
                continue
            if not (leg1 or leg2):
                self.stdout.write(f'  {a}→HQ→{b}: no valid items')
                continue
            made += 1
            self.stdout.write(self.style.SUCCESS(
                f'  {a}→HQ→{b}: {len(items)} صنف · leg1 #{leg1.id} (A→HQ, {leg1.line_count}) · '
                f'leg2 #{leg2.id} (HQ→B, {leg2.line_count})'))
        self.stdout.write(f'\n  created {made} allocation(s) as PG proposals — review + approve + push in /supply.')
