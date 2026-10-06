"""
apps/pbx/ami_bridge.py

Asterisk Manager Interface (AMI) bridge for Issabel PBX.

Connects to the Asterisk AMI TCP socket, listens for call events in real time,
and creates PBXEvent + CallSession records in Django.

Configuration (required in .env):
    AMI_HOST      — Asterisk server IP (default: 127.0.0.1)
    AMI_PORT      — AMI port (default: 5038)
    AMI_USER      — AMI username
    AMI_SECRET    — AMI password

Run as a standalone management command:
    python manage.py run_ami_bridge

The bridge runs inside a Django Channels worker (async).

AMI event flow:
  Newchannel          → create CallSession (state=ringing)
  AgentCalled         → link agent extension
  AgentConnect        → update answered_at
  Hangup              → call CallSession.complete()
  QueueCallerAbandon  → CallSession.complete(state='abandoned')
  Cdr                 → store CDR fields on CallSession
"""
import asyncio
import logging
import re
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('elrezeiky.pbx.ami')

# Sessions in-flight: unique_id → CallSession PK
_active_sessions: dict[str, int] = {}

# In-memory extension registry — populated at startup and refreshed periodically.
# Keyed by extension string.  Values: 'agent' | 'branch' | 'gateway' | 'other'
_extension_registry: dict[str, str] = {}
# Set of gateway extension names (goip4, grandstream, etc.)
_gateway_extensions: set[str] = set()
# Gateway metadata for number normalisation: ext → {'type': 'mobile'|'landline', 'prefix': '0', 'suffix': ''}
_gateway_meta: dict[str, dict] = {}


def _load_extension_registry():
    """
    Load AgentExtension records into the in-memory registry.
    Called at bridge startup and after sync_pbx_extensions runs.
    Thread-safe for reads (GIL); writes happen only at startup/reload.
    """
    global _extension_registry, _gateway_extensions, _gateway_meta
    try:
        from apps.pbx.models import AgentExtension
        registry = {}
        gateways = set()
        gw_meta = {}
        for ae in AgentExtension.objects.filter(is_active=True).values(
            'extension', 'extension_type', 'gateway_type', 'call_prefix', 'call_suffix'
        ):
            registry[ae['extension']] = ae['extension_type']
            if ae['extension_type'] == 'gateway':
                gateways.add(ae['extension'])
                gw_meta[ae['extension']] = {
                    'type':   ae['gateway_type'],
                    'prefix': ae['call_prefix'] or '',
                    'suffix': ae['call_suffix'] or '',
                }
        _extension_registry = registry
        _gateway_extensions = gateways
        _gateway_meta       = gw_meta
        logger.info(
            'Extension registry loaded: %d extensions (%d gateways: %s)',
            len(registry), len(gateways),
            ', '.join(f"{e}[{m['type']}]" for e, m in gw_meta.items()),
        )
    except Exception as exc:
        logger.warning('Failed to load extension registry: %s', exc)


def _normalize_caller_num(caller_num: str, gateway_ext: str) -> str:
    """
    Strip any PBX-added prefix/suffix from the caller number based on
    which gateway the call arrived on.

    goip4 (mobile) might add '0' prefix → strip it to get the clean number.
    grandstream (landline) might add '9' access prefix → strip it.
    """
    meta = _gateway_meta.get(gateway_ext)
    if not meta:
        return caller_num
    num = (caller_num or '').strip()
    prefix = meta['prefix']
    suffix = meta['suffix']
    if prefix and num.startswith(prefix):
        num = num[len(prefix):]
    if suffix and num.endswith(suffix):
        num = num[:-len(suffix)]
    return num or caller_num


class AMIConnection:
    """Asyncio-based AMI TCP client."""

    def __init__(self, host: str, port: int, user: str, secret: str):
        self.host   = host
        self.port   = port
        self.user   = user
        self.secret = secret
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        # Read AMI banner
        banner = await self._reader.readline()
        logger.info('AMI banner: %s', banner.decode().strip())
        # Login
        await self._send_action({
            'Action': 'Login',
            'Username': self.user,
            'Secret': self.secret,
        })
        response = await self._read_event()
        if response.get('Response') != 'Success':
            raise ConnectionError(f'AMI login failed: {response}')
        logger.info('AMI login successful as %s', self.user)

    async def _send_action(self, fields: dict):
        lines = ''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n'
        self._writer.write(lines.encode())
        await self._writer.drain()

    async def _read_event(self) -> dict:
        """Read one AMI event block (terminated by blank line)."""
        event: dict = {}
        while True:
            raw = await self._reader.readline()
            line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
            if not line:
                break
            if ':' in line:
                key, _, val = line.partition(':')
                event[key.strip()] = val.strip()
        return event

    async def listen(self, handler):
        """Continuously read AMI events and call handler(event)."""
        while True:
            try:
                event = await self._read_event()
                if event:
                    await handler(event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error('AMI read error: %s', exc)
                await asyncio.sleep(5)

    async def close(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()


# ── Event handler ─────────────────────────────────────────────────────────────

async def handle_event(event: dict):
    """
    Dispatch AMI event to the appropriate handler.
    Runs in asyncio context — uses sync_to_async for Django ORM calls.
    """
    event_type = event.get('Event', 'Other')

    # Persist raw event
    await _save_raw_event(event, event_type)

    dispatch = {
        'Newchannel':           _on_newchannel,
        'AgentCalled':          _on_agent_called,
        'AgentConnect':         _on_agent_connect,
        'AgentComplete':        _on_agent_complete,
        'Hangup':               _on_hangup,
        'QueueCallerJoin':      _on_queue_join,
        'QueueCallerAbandon':   _on_queue_abandon,
        'Cdr':                  _on_cdr,
    }
    handler = dispatch.get(event_type)
    if handler:
        try:
            await handler(event)
        except Exception as exc:
            logger.warning('AMI handler %s failed: %s', event_type, exc)


async def _save_raw_event(event: dict, event_type: str):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import PBXEvent

    @sync_to_async
    def _create():
        PBXEvent.objects.create(
            event_type=event_type if event_type in dict(PBXEvent.EVENT_TYPE_CHOICES) else 'Other',
            payload=event,
            unique_id=event.get('Uniqueid', ''),
            linked_id=event.get('Linkedid', ''),
            channel=event.get('Channel', ''),
            caller_id_num=event.get('CallerIDNum', '') or event.get('CallerID', ''),
            caller_id_name=event.get('CallerIDName', ''),
            extension=event.get('Exten', '') or event.get('DestExten', ''),
            queue_name=event.get('Queue', ''),
        )

    try:
        await _create()
    except Exception as exc:
        logger.debug('PBXEvent persist failed: %s', exc)


async def _on_newchannel(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession, PBXQueue

    unique_id  = event.get('Uniqueid', '')
    linked_id  = event.get('Linkedid', '')
    caller_num = event.get('CallerIDNum', '') or event.get('CallerID', '')
    caller_name = event.get('CallerIDName', '')
    exten      = event.get('Exten', '')
    channel    = event.get('Channel', '')

    if not unique_id or unique_id in _active_sessions:
        return

    direction = _classify_call(channel, exten, caller_num)

    # Strip gateway prefix/suffix so we store the clean customer number
    if direction == 'inbound' and _is_gateway_channel(channel):
        gw_peer = _extract_extension(channel)
        caller_num = _normalize_caller_num(caller_num, gw_peer)

    # Skip internal extension-to-extension calls — not relevant to the CRM
    if direction == 'internal':
        logger.debug(
            'Skipping internal call: %s → %s (uid=%s)', caller_num, exten, unique_id
        )
        return

    @sync_to_async
    def _create():
        session = CallSession.objects.create(
            unique_id=unique_id,
            linked_id=linked_id,
            direction=direction,
            state='ringing',
            caller_number=caller_num,
            caller_name=caller_name or '',
            destination_ext=exten,
            started_at=timezone.now(),
        )
        _active_sessions[unique_id] = session.pk
        return session.pk

    pk = await _create()
    logger.debug('CallSession created pk=%d uid=%s caller=%s', pk, unique_id, caller_num)

    # Push incoming call context to agent browsers via WebSocket
    if direction == 'inbound':
        try:
            from asgiref.sync import sync_to_async
            from apps.pbx.consumers import push_incoming_call
            await sync_to_async(push_incoming_call)(pk)
        except Exception as ws_exc:
            logger.debug('WebSocket push_incoming_call failed (non-fatal): %s', ws_exc)


async def _on_agent_called(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession, AgentExtension

    linked_id   = event.get('Linkedid', '')
    agent_ext   = _extract_extension(event.get('AgentCalled', '') or event.get('Extension', ''))
    queue_name  = event.get('Queue', '')

    @sync_to_async
    def _update():
        sessions = CallSession.objects.filter(linked_id=linked_id).exclude(state='completed')
        for session in sessions:
            changed = []
            if agent_ext:
                try:
                    ae = AgentExtension.objects.get(extension=agent_ext)
                    session.agent = ae
                    changed.append('agent')
                except AgentExtension.DoesNotExist:
                    pass
            if queue_name and not session.queue_id:
                from apps.pbx.models import PBXQueue
                q = PBXQueue.objects.filter(name=queue_name).first()
                if q:
                    session.queue = q
                    changed.append('queue')
            if changed:
                session.save(update_fields=changed + ['updated_at'])

    await _update()


async def _on_agent_connect(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession

    linked_id = event.get('Linkedid', '')

    @sync_to_async
    def _update():
        CallSession.objects.filter(
            linked_id=linked_id, answered_at__isnull=True
        ).update(answered_at=timezone.now(), state='answered')

    await _update()


async def _on_agent_complete(event: dict):
    # AgentComplete fires when the agent hangs up — treated same as Hangup
    await _on_hangup(event)


async def _on_hangup(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession

    unique_id = event.get('Uniqueid', '')
    cause_txt = event.get('Cause-txt', '')

    state = 'completed'
    if 'no answer' in cause_txt.lower():
        state = 'no_answer'
    elif 'busy' in cause_txt.lower():
        state = 'busy'

    pk = _active_sessions.pop(unique_id, None)

    @sync_to_async
    def _complete():
        qs = CallSession.objects.filter(unique_id=unique_id).exclude(state='completed')
        if pk:
            qs = qs | CallSession.objects.filter(pk=pk)
        session = qs.first()
        if session:
            session.complete(state=state)
            return session.pk
        return None

    completed_pk = await _complete()

    # Notify agent browsers that the call ended
    if completed_pk:
        try:
            from apps.pbx.consumers import push_incoming_call
            from asgiref.sync import sync_to_async
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()
            if channel_layer:
                await channel_layer.group_send(
                    'pbx_all_agents',
                    {
                        'type': 'call_ended',
                        'session_id': completed_pk,
                        'state': state,
                        'unique_id': unique_id,
                    },
                )
        except Exception as ws_exc:
            logger.debug('call_ended WebSocket push failed (non-fatal): %s', ws_exc)


async def _on_queue_join(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession, PBXQueue

    linked_id  = event.get('Linkedid', '')
    queue_name = event.get('Queue', '')

    @sync_to_async
    def _update():
        q = PBXQueue.objects.filter(name=queue_name).first()
        if q:
            CallSession.objects.filter(
                linked_id=linked_id
            ).update(queue=q, state='queued')

    await _update()


async def _on_queue_abandon(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession

    linked_id = event.get('Linkedid', '')

    @sync_to_async
    def _complete():
        for session in CallSession.objects.filter(linked_id=linked_id).exclude(state='completed'):
            session.complete(state='abandoned')

    await _complete()


async def _on_cdr(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession

    unique_id    = event.get('UniqueID', '') or event.get('Uniqueid', '')
    disposition  = event.get('Disposition', '')
    userfield    = event.get('UserField', '')
    recording    = event.get('Filename', '')

    @sync_to_async
    def _update():
        CallSession.objects.filter(unique_id=unique_id).update(
            cdr_disposition=disposition,
            cdr_userfield=userfield,
            recording_path=recording,
        )

    await _update()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_extension(channel_or_ext: str) -> str:
    """
    Extract extension from an Asterisk channel string.
      'SIP/201-00000001'   → '201'
      'SIP/goip4-00000001' → 'goip4'
      '201'                → '201'
    """
    # SIP/NAME-hexsuffix pattern
    match = re.match(r'^(?:SIP|PJSIP|IAX2)/([^-]+)', channel_or_ext)
    if match:
        return match.group(1)
    # Plain number
    match = re.search(r'(\d+)', channel_or_ext)
    if match:
        return match.group(1)
    return channel_or_ext


def _is_extension_internal(ext: str) -> bool:
    """True if this extension is a known local SIP peer (agent/branch/hq/other — not gateway)."""
    return ext in _extension_registry and _extension_registry[ext] != 'gateway'


def _is_gateway_channel(channel: str) -> bool:
    """True if this channel belongs to a gateway (GoIP, Grandstream, DAHDI, trunk)."""
    # DAHDI = PSTN line
    if channel.startswith('DAHDI/'):
        return True
    # SIP/goip4-..., SIP/grandstream-...
    peer = _extract_extension(channel)
    if peer in _gateway_extensions:
        return True
    # Trunk keyword fallback
    if re.search(r'trunk|gsm|pstn|goip|grandstream', channel, re.IGNORECASE):
        return True
    return False


def _classify_call(channel: str, exten: str, caller_num: str) -> str:
    """
    Classify a new channel as 'inbound', 'outbound', or 'internal'.

    Rules (in priority order):
      1. Channel is from a gateway peer  → inbound (external caller coming in)
      2. DAHDI channel                   → inbound
      3. Exten is s/h/i/t (Asterisk IVR contexts) → inbound
      4. Caller is a known internal ext AND destination is also internal → internal
      5. Caller is a known internal ext dialling out  → outbound
      6. Default                         → inbound
    """
    peer = _extract_extension(channel)

    # Gateway channel → inbound
    if _is_gateway_channel(channel):
        return 'inbound'

    # Classic Asterisk inbound IVR context landing extensions
    if re.match(r'^[shit]$', exten or ''):
        return 'inbound'

    # Both sides are internal → internal
    dest_ext = _extract_extension(exten) if exten else ''
    caller_is_internal = _is_extension_internal(caller_num) or _is_extension_internal(peer)
    dest_is_internal   = _is_extension_internal(dest_ext)

    if caller_is_internal and dest_is_internal:
        return 'internal'

    if caller_is_internal:
        return 'outbound'

    return 'inbound'


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_bridge():
    """
    Main coroutine — connects to AMI and listens forever.
    Reconnects on connection loss after a 10-second backoff.
    Called by: python manage.py run_ami_bridge
    """
    import os
    host   = os.environ.get('AMI_HOST', getattr(settings, 'AMI_HOST', '127.0.0.1'))
    port   = int(os.environ.get('AMI_PORT', getattr(settings, 'AMI_PORT', 5038)))
    user   = os.environ.get('AMI_USER', getattr(settings, 'AMI_USER', ''))
    secret = os.environ.get('AMI_SECRET', getattr(settings, 'AMI_SECRET', ''))

    if not user or not secret:
        logger.error('AMI_USER / AMI_SECRET not configured — bridge cannot start')
        return

    while True:
        # Load extension registry before connecting
        from asgiref.sync import sync_to_async
        await sync_to_async(_load_extension_registry)()

        ami = AMIConnection(host, port, user, secret)
        try:
            await ami.connect()
            logger.info('AMI bridge connected to %s:%d', host, port)
            await ami.listen(handle_event)
        except Exception as exc:
            logger.error('AMI bridge disconnected: %s — reconnecting in 10s', exc)
            await asyncio.sleep(10)
        finally:
            await ami.close()
