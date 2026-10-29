"""
apps/pbx/extensions.py

Live SIP registration status per extension (read-only in Issabel), merged with
our AgentExtension mapping and current calls. chan_sip → SIPpeers;
PJSIP → PJSIPShowEndpoints + PJSIPShowContacts.
"""
import re

from django.conf import settings

_RTT = re.compile(r'\((\d+)\s*ms\)')


def _sip_peers(client) -> dict:
    out = {}
    for e in client.action_list({'Action': 'SIPpeers'}, 'PeerlistComplete'):
        name = e.get('ObjectName', '')
        status = e.get('Status', '')
        ip = e.get('IPaddress', '')
        ip = '' if ip in ('-none-', '(null)') else ip
        m = _RTT.search(status)
        online = status.startswith('OK') or (status.lower().startswith('unmonitored') and bool(ip))
        out[name] = {'online': online, 'status': status or '—', 'ip': ip,
                     'port': e.get('IPport', ''), 'rtt_ms': int(m.group(1)) if m else None,
                     'user_agent': ''}
    return out


def _pjsip(client) -> dict:
    out = {}
    for e in client.action_list({'Action': 'PJSIPShowEndpoints'}, 'EndpointListComplete'):
        name = e.get('ObjectName', '')
        out[name] = {'online': e.get('DeviceState', '') not in ('Unavailable', 'Invalid', ''),
                     'status': e.get('DeviceState', '—'), 'ip': '', 'port': '',
                     'rtt_ms': None, 'user_agent': ''}
    for c in client.action_list({'Action': 'PJSIPShowContacts'}, 'ContactListComplete'):
        name = c.get('Endpoint') or c.get('Aor', '')
        row = out.setdefault(name, {'online': False, 'status': '—', 'ip': '', 'port': '',
                                    'rtt_ms': None, 'user_agent': ''})
        via = c.get('ViaAddr', '') or ''
        uri_host = re.search(r'@([\d.]+):?(\d*)', c.get('Uri', ''))
        row['ip'] = via or (uri_host.group(1) if uri_host else '')
        row['port'] = c.get('ViaPort', '') or (uri_host.group(2) if uri_host else '')
        row['user_agent'] = c.get('UserAgent', '')
        usec = c.get('RoundtripUsec', '')
        row['rtt_ms'] = int(int(usec) / 1000) if usec.isdigit() and int(usec) > 0 else row['rtt_ms']
        if c.get('Status') in ('Reachable', 'Avail'):
            row['online'], row['status'] = True, 'Reachable'
        elif c.get('Status'):
            row['status'] = c['Status']
    return out


def fetch_registrations() -> tuple[dict, str]:
    """→ ({peer_name: {...}}, tech). Raises AMIActionError / OSError on failure."""
    from apps.pbx.actions import AMIActionClient
    tech = getattr(settings, 'AMI_CHANNEL_TECH', 'SIP').upper()
    with AMIActionClient(timeout=8) as client:
        return (_pjsip(client) if tech == 'PJSIP' else _sip_peers(client)), tech


def extension_status() -> dict:
    """
    Merge PBX registrations with our mapping. Persists last_status/last_ip so the
    last known state survives when the PBX is unreachable.
    """
    from apps.pbx.models import AgentExtension, CallSession

    error, regs, tech = '', {}, getattr(settings, 'AMI_CHANNEL_TECH', 'SIP').upper()
    try:
        regs, tech = fetch_registrations()
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'

    on_call = set(CallSession.objects.filter(
        state__in=['ringing', 'answered', 'queued', 'on_hold', 'transferred'],
        agent__isnull=False).values_list('agent__extension', flat=True))

    rows, seen = [], set()
    for ext in AgentExtension.objects.select_related('staff__user', 'staff__branch'):
        peer = ext.sip_peer or ext.extension
        reg = regs.get(peer) or regs.get(ext.extension)
        seen.update({peer, ext.extension})
        if reg is not None and (ext.last_status != reg['status'] or (reg['ip'] and ext.last_ip != reg['ip'])):
            AgentExtension.objects.filter(pk=ext.pk).update(
                last_status=reg['status'][:50], last_ip=(reg['ip'] or ext.last_ip)[:50])
        rows.append(_row(ext.extension, reg, ext, ext.extension in on_call, live=not error))

    for name, reg in regs.items():
        if name not in seen:
            rows.append(_row(name, reg, None, False, live=True))

    rows.sort(key=lambda r: (r['problem'] is None, r['extension'].zfill(8)))
    online = sum(1 for r in rows if r['online'])
    return {'tech': tech, 'error': error, 'rows': rows,
            'summary': {'total': len(rows), 'online': online, 'offline': len(rows) - online,
                        'unmapped': sum(1 for r in rows if r['mapping'] is None),
                        'on_call': sum(1 for r in rows if r['on_call'])}}


def _row(extension, reg, ext, on_call, live):
    mapping = None
    if ext is not None:
        staff = ext.staff
        mapping = {
            'id': ext.id, 'type': ext.extension_type, 'type_label': ext.get_extension_type_display(),
            'staff_id': staff.id if staff else None,
            'staff_name': staff.full_name if staff else None,
            'staff_role': staff.role if staff else None,
            'branch': (staff.branch.name_ar if staff and staff.branch_id else None),
            'is_active': ext.is_active, 'sip_peer': ext.sip_peer,
        }

    online = bool(reg and reg['online'])
    problem = None
    if live and reg is None:
        problem = 'غير موجودة في السنترال — رقم التحويلة أو SIP Peer خطأ، أو حُذفت من Issabel'
    elif live and not online and mapping and mapping['staff_id']:
        problem = 'الموظف مرتبط لكن الهاتف غير مسجّل — الجهاز/السوفت فون مطفأ أو غير متصل بالشبكة أو كلمة سر SIP خاطئة'
    elif reg and reg['rtt_ms'] and reg['rtt_ms'] > 300:
        problem = f'استجابة بطيئة ({reg["rtt_ms"]} ms) — جودة الصوت قد تتأثر'
    elif mapping is None and online:
        problem = 'متصلة لكن غير مرتبطة بموظف — لن تظهر مكالماتها لأحد'
    elif mapping and mapping['type'] == 'agent' and not mapping['staff_id']:
        problem = 'تحويلة مركز اتصال بدون موظف'

    return {
        'extension': extension, 'online': online, 'on_call': on_call,
        'status': reg['status'] if reg else (ext.last_status if ext else '—'),
        'ip': (reg['ip'] if reg else '') or (ext.last_ip if ext else ''),
        'rtt_ms': reg['rtt_ms'] if reg else None,
        'user_agent': reg['user_agent'] if reg else '',
        'in_pbx': reg is not None, 'live': live,
        'mapping': mapping, 'problem': problem,
    }
