"""
apps/transfers/management/commands/check_unfulfilled_transfers.py

Run daily at 6PM via Windows Task Scheduler:
  python manage.py check_unfulfilled_transfers

Flags any transfer that was accepted/partial more than 14 days ago
but has no matching PurchaseHistory sale for that item at that branch.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Flag accepted transfers with no recorded sale after 14 days'

    def handle(self, *args, **options):
        from apps.transfers.models import TransferRequest
        from apps.customers.models import PurchaseHistory
        from apps.transfers.notifications import notify_unfulfilled_flag

        cutoff = timezone.now() - timedelta(days=14)

        # Find accepted/partial transfers older than 14 days, not yet flagged
        candidates = TransferRequest.objects.filter(
            status__in=('accepted', 'partial', 'fulfilled'),
            responded_at__lte=cutoff,
            flagged_no_sale=False,
        ).select_related('item', 'requesting_branch', 'requested_by')

        flagged = 0
        for transfer in candidates:
            # Check if there's any sale of this item at the requesting branch
            # in the period after the transfer was accepted
            has_sale = PurchaseHistory.objects.filter(
                branch=transfer.requesting_branch,
                invoice_date__gte=transfer.responded_at.date() if transfer.responded_at else None,
                lines__item=transfer.item,
            ).exists()

            if not has_sale:
                notify_unfulfilled_flag(transfer)
                flagged += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'  ⚠ Transfer #{transfer.id} — {transfer.item.name} @ '
                        f'{transfer.requesting_branch} — no sale in 14 days'
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(f'✅ Check complete — {flagged} transfers flagged')
        )
