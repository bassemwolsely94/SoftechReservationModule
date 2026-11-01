"""
Seed the trusted-network list (security N1): one /24 per branch whose SOFTECH db_host is a
192.168.x.y address (closed branches excluded), plus the ZeroTier staff VPN. Dry run unless --apply; idempotent; never
touches a row whose cidr already exists.
"""
import ipaddress

from django.core.management.base import BaseCommand

from apps.access.models import TrustedNetwork
from apps.branches.models import Branch

ZEROTIER_CIDR = '10.50.50.0/24'
LAN = ipaddress.ip_network('192.168.0.0/16')


class Command(BaseCommand):
    help = 'Seed trusted networks from branch db_host values (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='write the rows (default: only list them)')

    def _wanted(self):
        seen = set()
        for b in Branch.objects.with_local_db().exclude(kind=Branch.KIND_CLOSED).order_by('softech_branch_id'):
            try:
                addr = ipaddress.ip_address((b.db_host or '').strip())
            except ValueError:
                continue
            if addr.version != 4 or addr not in LAN:
                continue
            cidr = str(ipaddress.ip_network(f'{addr}/24', strict=False))
            if cidr in seen:
                continue
            seen.add(cidr)
            yield {'cidr': cidr, 'name': b.name_ar or b.name, 'kind': 'branch_lan', 'branch': b}
        yield {'cidr': ZEROTIER_CIDR, 'name': 'ZeroTier', 'kind': 'staff_vpn', 'branch': None}

    def handle(self, *args, **opts):
        apply = opts['apply']
        existing = set(TrustedNetwork.objects.values_list('cidr', flat=True))
        made = skipped = 0
        for row in self._wanted():
            if row['cidr'] in existing:
                skipped += 1
                self.stdout.write(f'exists  {row["cidr"]}  (left as it is)')
                continue
            made += 1
            self.stdout.write(f'{"create" if apply else "would create"}  {row["cidr"]}  {row["name"]}')
            if apply:
                TrustedNetwork.objects.create(notes='seed_trusted_networks', **row)
        verb = 'created' if apply else 'would create'
        self.stdout.write(f'{verb} {made}, left {skipped} existing' + ('' if apply else '  (dry run, use --apply)'))
