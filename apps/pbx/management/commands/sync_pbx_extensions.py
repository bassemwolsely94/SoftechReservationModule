"""
python manage.py sync_pbx_extensions

Connects to Issabel AMI, fetches all SIP peers, and upserts them
into AgentExtension.  Existing user assignments are preserved.

Run once after setup, then optionally on a cron to keep statuses fresh.
Gateway devices (goip*, grandstream, trunk*) are automatically typed
as 'gateway'.  Everything else defaults to 'other' until an admin
assigns it to a user and sets the type.
"""
import socket
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.pbx.models import AgentExtension


GATEWAY_KEYWORDS = ('goip', 'grandstream', 'trunk', 'gateway', 'gsm', 'pstn')


def _is_gateway(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in GATEWAY_KEYWORDS)


def _fetch_sip_peers(host, port, user, secret) -> list[dict]:
    """Connect to AMI and return list of SIP peer dicts."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((host, port))
    s.recv(1024)  # banner

    login = f'Action: Login\r\nUsername: {user}\r\nSecret: {secret}\r\nEvents: off\r\n\r\n'
    s.sendall(login.encode())
    time.sleep(0.8)
    resp = s.recv(2048).decode()
    if 'Success' not in resp:
        s.close()
        raise ConnectionError(f'AMI login failed: {resp.strip()}')

    s.sendall(b'Action: SIPpeers\r\nActionID: sync1\r\n\r\n')
    data = b''
    s.settimeout(3)
    for _ in range(30):
        try:
            chunk = s.recv(8192)
            if not chunk:
                break
            data += chunk
            if b'EventList: Complete' in data:
                break
        except socket.timeout:
            break

    s.sendall(b'Action: Logoff\r\n\r\n')
    s.close()

    # Parse peer blocks
    peers = []
    current = {}
    for line in data.decode(errors='replace').split('\n'):
        line = line.strip()
        if line.startswith('ObjectName:'):
            current['name'] = line.split(':', 1)[1].strip()
        elif line.startswith('Status:'):
            current['status'] = line.split(':', 1)[1].strip()
        elif line.startswith('IPaddress:'):
            current['ip'] = line.split(':', 1)[1].strip()
        elif line == '' and current.get('name'):
            peers.append(current)
            current = {}

    return peers


class Command(BaseCommand):
    help = 'Sync SIP extensions from Issabel AMI into AgentExtension table'

    def handle(self, *args, **options):
        host   = getattr(settings, 'AMI_HOST',   '127.0.0.1')
        port   = int(getattr(settings, 'AMI_PORT', 5038))
        user   = getattr(settings, 'AMI_USER',   '')
        secret = getattr(settings, 'AMI_SECRET', '')

        self.stdout.write(f'Connecting to AMI at {host}:{port} ...')
        try:
            peers = _fetch_sip_peers(host, port, user, secret)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Failed: {exc}'))
            return

        self.stdout.write(f'Found {len(peers)} SIP peers.')
        self.stdout.write('')

        created = updated = skipped = 0

        for peer in peers:
            name   = peer['name']
            status = peer.get('status', '')
            ip     = peer.get('ip', '')
            if ip == '-none-':
                ip = ''

            ext_type = AgentExtension.TYPE_GATEWAY if _is_gateway(name) else AgentExtension.TYPE_OTHER

            obj, is_new = AgentExtension.objects.get_or_create(
                extension=name,
                defaults={
                    'extension_type': ext_type,
                    'sip_peer':       name,
                    'last_status':    status,
                    'last_ip':        ip,
                    'is_active':      True,
                },
            )

            if is_new:
                created += 1
                flag = '+ NEW'
            else:
                # Update status/ip but preserve type and staff assignment
                changed = []
                if obj.last_status != status:
                    obj.last_status = status
                    changed.append('last_status')
                if obj.last_ip != ip:
                    obj.last_ip = ip
                    changed.append('last_ip')
                # Auto-type gateways even if record already existed as 'other'
                if ext_type == AgentExtension.TYPE_GATEWAY and obj.extension_type == AgentExtension.TYPE_OTHER:
                    obj.extension_type = ext_type
                    changed.append('extension_type')
                if changed:
                    obj.save(update_fields=changed + ['updated_at'])
                    updated += 1
                    flag = '~ UPD'
                else:
                    skipped += 1
                    flag = '  ---'

            reg = 'ONLINE' if status.startswith('OK') else ('UNREACHABLE' if 'UNREACHABLE' in status else 'offline')
            user_label = obj.staff.full_name if obj.staff else '(unassigned)'
            self.stdout.write(
                f'  {flag}  ext={name:<12} type={obj.extension_type:<8} '
                f'{reg:<12} ip={ip or "-":<18} user={user_label}'
            )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done — {created} created, {updated} updated, {skipped} unchanged.'
        ))
        self.stdout.write('')

        # Summary: unassigned extensions that need a user
        unassigned = AgentExtension.objects.filter(
            staff__isnull=True,
            extension_type__in=[AgentExtension.TYPE_AGENT, AgentExtension.TYPE_OTHER],
        ).count()
        if unassigned:
            self.stdout.write(self.style.WARNING(
                f'{unassigned} extensions still unassigned to a user.\n'
                'Go to Admin → PBX → Extensions to assign users and set types.'
            ))
