"""
python manage.py scan_ap_anomalies [--party-type supplier|customer] [--personcode 4471]

Phase-C batch H — deeper anomaly / risk scan over the ingested reconciliation
mirror (duplicate invoices, over-allocation, statistical payment outliers). Emits
ReconException rows; READ-ONLY, writes nothing to SOFTECH. Risk flags, not proof.

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Deeper anomaly scan over the reconciliation mirror (risk flags only)'

    def add_arguments(self, parser):
        parser.add_argument('--party-type', default='', choices=['', 'supplier', 'customer'])
        parser.add_argument('--personcode', default='')

    def handle(self, *args, **o):
        from apps.finance import recon_anomalies
        c = recon_anomalies.scan(party_type=o['party_type'] or None,
                                 personcode=o['personcode'] or None)
        self.stdout.write(self.style.SUCCESS(
            f'Anomaly scan over {c["parties"]} parties — duplicate_invoice: '
            f'{c["duplicate_invoice"]}, overpayment: {c["overpayment"]}, outliers: {c["anomaly"]}'))
