"""READ-ONLY daily check: customers whose SOFTECH status / lock / points flag differs between HQ and a
branch node (B7 step 2). Records CustomerStatusDrift rows; --notify alerts admin + supervisor.

    python manage.py check_customer_status_drift [--notify] [--host 192.168.4.11]
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'READ-ONLY: HQ vs branch-node differences in customers\' SOFTECH account flags (B7).'

    def add_arguments(self, parser):
        parser.add_argument('--notify', action='store_true')
        parser.add_argument('--host', action='append', default=[], help='only this node (repeatable)')

    def handle(self, *a, **o):
        from apps.customers import status_drift as SD
        r = SD.scan_locked(hosts=o['host'] or None)
        if r is None:
            self.stdout.write(self.style.WARNING('another check is running — skipped'))
            return
        self.stdout.write(f"HQ codes: {r['hq_codes']}")
        for label, info in r['nodes'].items():
            self.stdout.write(f'  {label}: {info}')
        self.stdout.write(f"open differences: {r['open']} · HQ stricter (branch still serves): {r['open_risk']}")
        text = SD.digest_text()
        if text:
            self.stdout.write(text)
        if o['notify']:
            self.stdout.write(f'notifications: {SD.notify(r)}')
