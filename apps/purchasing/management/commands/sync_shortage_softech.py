"""
Push any market-shortage flags that haven't reached SOFTECH yet (offline queue).

Run on a schedule (e.g. every 30 min) so confirm/revert made while SOFTECH was
down get written once it's reachable:

    python manage.py sync_shortage_softech
"""
from django.core.management.base import BaseCommand
from apps.purchasing.shortage_writer import sync_pending


class Command(BaseCommand):
    help = 'Retry SOFTECH writeback for shortage flags not yet synced.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=500)

    def handle(self, *args, **opts):
        res = sync_pending(limit=opts['limit'])
        if not res.get('enabled'):
            self.stdout.write(self.style.WARNING(
                'SHORTAGE_SOFTECH_WRITE_ENABLED is False — nothing pushed (local only).'))
            return
        self.stdout.write(self.style.SUCCESS(
            f"pushed={res['pushed']} failed={res['failed']} remaining={res['pending']}"))
