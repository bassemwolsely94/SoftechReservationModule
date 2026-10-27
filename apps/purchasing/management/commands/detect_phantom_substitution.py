"""
python manage.py detect_phantom_substitution [--dry-run] [--list N]

Runs the phantom-substitution detector (apps.purchasing.phantom.scan): scores every
item's buyback/sold ratio over the rolling window and flags items >= threshold.
SELECT-only against SOFTECH; writes the local catalog.Item phantom flag/metrics.

  --dry-run   score + report only, do not persist the flags.
  --list N    after scanning, print the top N flagged items (by sold qty).
"""
from django.core.management.base import BaseCommand
from apps.purchasing import phantom


class Command(BaseCommand):
    help = 'Detect phantom-substitution items (مبيعات وهمية) and flag them on catalog.Item.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='score + report only, do not persist')
        parser.add_argument('--list', type=int, default=0, metavar='N', help='print top N flagged items')

    def handle(self, *args, **opts):
        summary = phantom.scan(persist=not opts['dry_run'])
        self.stdout.write(self.style.SUCCESS(
            f"buyback_accounts={summary['buyback_accounts']} "
            f"scored={summary['scored_items']} flagged={summary['flagged']} "
            f"persisted={summary['persisted']} "
            f"(threshold={summary['threshold']:.0%}, window={summary['flag_window_months']}mo)"
        ))
        n = opts['list']
        if n and not opts['dry_run']:
            from apps.catalog.models import Item
            rows = (Item.objects.filter(is_phantom_substitution=True)
                    .order_by('-phantom_sold_qty')[:n])
            for it in rows:
                self.stdout.write(
                    f"  {it.softech_id:>8}  ratio={it.phantom_ratio:>4.0%}  "
                    f"order={it.phantom_order_pct:>4.0%}  sold={it.phantom_sold_qty:>7.0f}  "
                    f"bb={it.phantom_buyback_qty:>7.0f}  genuine={it.phantom_genuine_need:>6.0f}  "
                    f"{(it.name or '')[:34]}"
                )
