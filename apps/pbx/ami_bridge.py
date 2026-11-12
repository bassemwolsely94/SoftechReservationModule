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
  Dial (Begin)        → outbound: the dialled customer number (or mark ext↔ext internal)
  Join / AgentCalled  → link the queue
  AgentConnect        → answered_at + the agent who answered (Member)
  Bridge (Link)       → answered_at (outbound calls have no AgentConnect)
  Hangup              → CallSession.complete() — completed only if answered
  QueueCallerAbandon  → CallSession.complete(state='abandoned')
Every event is matched on its own Uniqueid (AMI 1.3 has no Linkedid) — see _sessions_for.
Reports do NOT read these sessions: call history comes from the PBX CDR (apps/pbx/cdr.py).
  Cdr                 → store CDR fields on CallSession
"""
import asyncio
import logging
import re
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('elrezeiky.pbx.ami')

# A session in one of these states is finished — later events must not touch it.
TERMINAL_STATES = ('completed', 'abandoned', 'no_answer', 'busy', 'failed')

# Raw events worth keeping. Issabel emits ~50 VarSet/Newexten/RTCP/PeerStatus lines per
# call (98% of PBXEvent rows); they carry nothing the CRM or a call replay needs.
PERSISTED_EVENTS = frozenset({
    'Newchannel', 'Hangup', 'Dial', 'Bridge', 'AgentCalled', 'AgentConnect', 'AgentComplete',
    'Join', 'Leave', 'QueueCallerJoin', 'QueueCallerLeave', 'QueueCallerAbandon', 'Cdr',
})

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

    Returns the Egyptian national number (apps/pbx/cdr.py national_number): the gateway's
    prefix/suffix is only stripped when the raw number is not already national, so a real
    leading 0 is never lost; line prefixes 81-85 / 91-95 are removed.
    """
    from apps.pbx.cdr import inbound_number
    from apps.pbx.cdr import digits_only, split_line_prefix
    out = inbound_number(caller_num, _gateway_meta.get(gateway_ext))
    # a short code that normalised to '' is stored without its line prefix, never raw
    return out or split_line_prefix(digits_only(caller_num))[1] or caller_num


class AMILoginError(ConnectionError):
    pass


HEARTBEAT_SECONDS = 30
_last_event_touch = 0.0


async def _record_status(**fields):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import PBXBridgeStatus
    try:
        await sync_to_async(PBXBridgeStatus.record)(**fields)
    except Exception as exc:
        logger.warning('bridge status write failed: %s', exc)


async def _touch_last_event():
    """Throttled: at most one DB write per heartbeat interval."""
    global _last_event_touch
    import time
    from django.utils import timezone
    if time.monotonic() - _last_event_touch >= HEARTBEAT_SECONDS:
        _last_event_touch = time.monotonic()
        await _record_status(last_event_at=timezone.now())


async def _heartbeat(ami):
    from django.utils import timezone
    while True:
        await ami._send_action({'Action': 'Ping'})
        await _record_status(state='connected', last_heartbeat_at=timezone.now())
        await asyncio.sleep(HEARTBEAT_SECONDS)


class AMIConnection:
    """Asyncio-based AMI TCP client."""

    banner = ''

    def __init__(self, host: str, port: int, user: str, secret: str):
        self.host   = host
        self.port   = port
        self.user   = user
        self.secret = secret
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self):
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=10)
        # Read AMI banner
        banner = await self._reader.readline()
        self.banner = banner.decode(errors='replace').strip()
        logger.info('AMI banner: %s', self.banner)
        # Login
        await self._send_action({
            'Action': 'Login',
            'Username': self.user,
            'Secret': self.secret,
        })
        response = await self._read_event()
        if response.get('Response') != 'Success':
            raise AMILoginError(response.get('Message', '') or str(response))
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
            if not raw:
                # EOF: Asterisk closed the socket — must reconnect, not spin
                raise ConnectionError('AMI closed the connection (EOF)')
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
            except (ConnectionError, OSError):
                raise  # run_bridge reconnects
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
    if 'Event' not in event:
        return  # action responses (e.g. heartbeat Ping) aren't PBX events

    event_type = event.get('Event', 'Other')
    await _touch_last_event()

    if event_type in PERSISTED_EVENTS:
        await _save_raw_event(event, event_type)

    dispatch = {
        'Newchannel':           _on_newchannel,
        'AgentCalled':          _on_agent_called,
        'AgentConnect':         _on_agent_connect,
        'AgentComplete':        _on_agent_complete,
        'Hangup':               _on_hangup,
        'Dial':                 _on_dial,
        'Bridge':               _on_bridge,
        'Join':                 _on_queue_join,          # AMI 1.3 name
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
        # Outbound: the channel is the agent's own phone — that's the agent. The customer
        # number arrives with the Dial event (_on_dial); until then caller_number holds
        # the extension, which is never used to match a customer.
        agent = _agent_for(channel) if direction == 'outbound' else None
        session = CallSession.objects.create(
            unique_id=unique_id,
            linked_id=linked_id,
            direction=direction,
            state='ringing',
            caller_number=caller_num,
            caller_name=caller_name or '',
            destination_ext=exten,
            agent=agent,
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


def _sessions_for(event: dict, *uid_keys):
    """Open CallSessions this event belongs to.

    Issabel's AMI 1.3 sends NO Linkedid, so matching on linked_id='' used to hit EVERY
    open session at once (one AgentConnect "answered" them all, one QueueCallerAbandon
    "abandoned" them all). Match on the event's own Uniqueid (= the caller channel's id
    for queue events); Linkedid is used only when the PBX actually sends one."""
    from django.db.models import Q
    from apps.pbx.models import CallSession
    uids = {event.get(k, '') for k in (uid_keys or ('Uniqueid',))} - {''}
    linked = event.get('Linkedid', '')
    if not uids and not linked:
        return CallSession.objects.none()
    cond = Q(unique_id__in=uids) if uids else Q()
    if linked:
        cond |= Q(linked_id=linked)
    return CallSession.objects.filter(cond).exclude(state__in=TERMINAL_STATES)


def _agent_for(member: str):
    """'SIP/15' / 'Local/18@from-queue/n' / '15' → AgentExtension or None."""
    from apps.pbx.models import AgentExtension
    from apps.pbx.cdr import peer_of
    ext = peer_of(member) or _extract_extension(member or '')
    return AgentExtension.objects.filter(extension=ext).first() if ext else None


async def _on_agent_called(event: dict):
    # Ring-all queues ring several agents per call, so the agent is NOT taken from here
    # (AgentConnect names the one who actually answered). Only the queue is linked.
    from asgiref.sync import sync_to_async
    from apps.pbx.models import PBXQueue

    queue_name = event.get('Queue', '')

    @sync_to_async
    def _update():
        q = PBXQueue.objects.filter(name=queue_name).first() if queue_name else None
        if q:
            _sessions_for(event).filter(queue__isnull=True).update(queue=q)

    await _update()


async def _on_agent_connect(event: dict):
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _update():
        agent = _agent_for(event.get('Member', '') or event.get('Interface', ''))
        fields = {'answered_at': timezone.now(), 'state': 'answered'}
        if agent:
            fields['agent'] = agent
        _sessions_for(event).filter(answered_at__isnull=True).update(**fields)

    await _update()


async def _on_agent_complete(event: dict):
    # AgentComplete fires when the agent hangs up — treated same as Hangup
    await _on_hangup(event)


async def _on_dial(event: dict):
    """Dial Begin on an outbound session: learn WHO was dialled (Newchannel only knows the
    agent's extension). A gateway destination → the customer number; an internal one →
    the session is an ext↔ext call and is dropped from the CRM flow."""
    if event.get('SubEvent', 'Begin') != 'Begin':
        return
    from asgiref.sync import sync_to_async
    from apps.pbx.cdr import outbound_number

    dest = event.get('Destination', '')
    dialstring = event.get('Dialstring', '') or event.get('DialString', '')

    @sync_to_async
    def _update():
        qs = _sessions_for(event, 'UniqueID', 'Uniqueid').filter(direction='outbound')
        if _is_gateway_channel(dest) or (not dest and '/' in dialstring):
            number = outbound_number(dialstring.split('/')[-1])
            if number:
                qs.update(caller_number=number[:50], destination_ext=dialstring[:50])
        elif _is_extension_internal(_extract_extension(dest) or dialstring):
            qs.update(direction='internal', destination_ext=dialstring[:50])

    await _update()


async def _on_bridge(event: dict):
    """Bridge Link = both sides are talking → the call was answered (outbound calls get no
    AgentConnect, so this is their only answer signal)."""
    if event.get('Bridgestate', 'Link') != 'Link':
        return
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _update():
        _sessions_for(event, 'Uniqueid1', 'Uniqueid2').filter(answered_at__isnull=True).update(
            answered_at=timezone.now(), state='answered')

    await _update()


def _final_state(session, cause_txt: str) -> str:
    cause = (cause_txt or '').lower()
    if session.answered_at:
        return 'completed'
    if 'busy' in cause:
        return 'busy'
    if session.direction == 'inbound' and 'no answer' not in cause:
        return 'abandoned'      # caller hung up before any agent picked up
    return 'no_answer'


async def _on_hangup(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession

    unique_id = event.get('Uniqueid', '')
    cause_txt = event.get('Cause-txt', '')
    pk = _active_sessions.pop(unique_id, None)

    @sync_to_async
    def _complete():
        qs = CallSession.objects.filter(unique_id=unique_id).exclude(state__in=TERMINAL_STATES)
        if pk:
            qs = qs | CallSession.objects.filter(pk=pk).exclude(state__in=TERMINAL_STATES)
        session = qs.first()
        if session:
            state = _final_state(session, cause_txt)
            session.complete(state=state)
            return session.pk, state
        return None, None

    completed_pk, state = await _complete()

    # Notify agent browsers that the call ended
    if completed_pk:
        try:
            from channels.layers import get_channel_layer

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
    from apps.pbx.models import PBXQueue

    queue_name = event.get('Queue', '')

    @sync_to_async
    def _update():
        q = PBXQueue.objects.filter(name=queue_name).first()
        fields = {'state': 'queued'}
        if q:
            fields['queue'] = q
        _sessions_for(event).filter(answered_at__isnull=True).update(**fields)

    await _update()


async def _on_queue_abandon(event: dict):
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _complete():
        for session in _sessions_for(event):
            session.complete(state='abandoned')

    await _complete()


async def _on_cdr(event: dict):
    from asgiref.sync import sync_to_async
    from apps.pbx.models import CallSession

    unique_id    = event.get('UniqueID', '') or event.get('Uniqueid', '')
    disposition  = event.get('Disposition', '')
    userfield    = event.get('UserField', '')
    # Issabel puts the MixMonitor file in RecordingFile; older builds used Filename
    recording    = (event.get('RecordingFile') or event.get('Recordingfile')
                    or event.get('Filename') or '')

    @sync_to_async
    def _update():
        fields = {'cdr_disposition': disposition, 'cdr_userfield': userfield}
        if recording:   # never wipe a path found earlier
            from apps.pbx.recordings import relative_path
            from django.utils import timezone
            fields['recording_path'] = relative_path(recording, timezone.localtime()) or recording[:500]
        CallSession.objects.filter(unique_id=unique_id).update(**fields)

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

    from django.utils import timezone

    if not user or not secret:
        logger.error('AMI_USER / AMI_SECRET not configured — bridge cannot start')
        await _record_status(state='not_configured', host=host, port=port,
                             last_error='AMI_USER / AMI_SECRET غير مضبوطة في env',
                             last_error_at=timezone.now())
        return

    reconnects = 0
    while True:
        # Load extension registry before connecting
        from asgiref.sync import sync_to_async
        await sync_to_async(_load_extension_registry)()

        ami = AMIConnection(host, port, user, secret)
        heartbeat = None
        await _record_status(state='connecting', host=host, port=port)
        try:
            await ami.connect()
            logger.info('AMI bridge connected to %s:%d', host, port)
            now = timezone.now()
            await _record_status(state='connected', banner=ami.banner[:100],
                                 connected_since=now, last_heartbeat_at=now,
                                 reconnect_count=reconnects)
            heartbeat = asyncio.create_task(_heartbeat(ami))
            await ami.listen(handle_event)
        except AMILoginError as exc:
            # Wrong credentials won't fix themselves — back off longer
            logger.error('AMI login failed: %s — retrying in 60s', exc)
            await _record_status(state='auth_failed', last_error=f'Login: {exc}',
                                 last_error_at=timezone.now())
            await asyncio.sleep(60)
        except Exception as exc:
            reason = f'{type(exc).__name__}: {exc}'.rstrip(': ')
            if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                reason += f' — {host}:{port} did not answer (network / VPN / firewall)'
            logger.error('AMI bridge disconnected: %s — reconnecting in 10s', reason)
            await _record_status(state='disconnected',
                                 last_error=f'{type(exc).__name__}: {exc}'[:500],
                                 last_error_at=timezone.now())
            await asyncio.sleep(10)
        finally:
            if heartbeat:
                heartbeat.cancel()
            try:
                await ami.close()
            except Exception:
                pass  # socket already broken
        reconnects += 1
