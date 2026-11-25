"""Delivery checker — did yesterday's voucher OTPs and portal login links reach the customers? (read-only)

    python manage.py check_message_delivery                 # yesterday
    python manage.py check_message_delivery --day 2026-11-24 --notify
Lists what failed, got no receipt, or was never handed to WhatsApp (phones masked, never an OTP), the delivery
rate, and whether our webhook is receiving Meta's receipts at all. Runs daily at 07:10 with --notify
(MESSAGE_DELIVERY_CHECK_ENABLED). apps/whatsapp/delivery.py.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Delivery checker for voucher OTPs and portal login links (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--day', default='', help='YYYY-MM-DD (default: yesterday)')
        parser.add_argument('--notify', action='store_true', help='send the in-app notice when something did not arrive')

    def handle(self, *a, **o):
        from apps.whatsapp import delivery
        try:
            day = dt.date.fromisoformat(o['day']) if o['day'] else None
        except ValueError:
            raise CommandError('--day must be YYYY-MM-DD')
        rep = delivery.report(day)
        self.stdout.write(delivery.digest_text(rep))
        if o['notify']:
            self.stdout.write(f'notified: {delivery.notify(rep)}')
