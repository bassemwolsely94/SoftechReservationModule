"""
apps/pbx/consumers.py

Real-time WebSocket push for PBX events.

AgentCallConsumer  — one WebSocket per agent browser tab
    URL:   /ws/pbx/agent/?token=<jwt>
    Group: pbx_agent_{extension_number}   (agent's own extension)
           pbx_all_agents                 (broadcast to all agents)

When an inbound call arrives (AMI bridge creates a CallSession), the bridge
calls push_incoming_call() which fires an 'incoming_call' event over the
agent's group.  The agent's browser receives:
  {
    "type": "incoming_call",
    "session_id": ...,
    "caller_id": "...",
    "queue": "...",
    "customer": { id, name, phone, last_purchases, open_vouchers, open_cases }
  }
"""
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

logger = logging.getLogger('elrezeiky.pbx')


class AgentCallConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.close(code=4001)
            return

        ext = await self._get_extension(user)
        self.extension = ext  # may be None if agent has no extension configured

        # Subscribe to the broadcast group (all agents see all calls)
        self.broadcast_group = 'pbx_all_agents'
        await self.channel_layer.group_add(self.broadcast_group, self.channel_name)

        # Also subscribe to agent-specific group if extension is mapped
        self.personal_group = None
        if ext:
            self.personal_group = f'pbx_agent_{ext.extension}'
            await self.channel_layer.group_add(self.personal_group, self.channel_name)

        await self.accept()
        await self.send(text_data=json.dumps({
            'type': 'connected',
            'extension': ext.extension if ext else None,
        }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.broadcast_group, self.channel_name)
        if self.personal_group:
            await self.channel_layer.group_discard(self.personal_group, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            if data.get('action') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception:
            pass

    # ── Channel layer message handlers ────────────────────────────────────────

    async def incoming_call(self, event):
        """Relay pbx.incoming_call group message to the WebSocket client."""
        await self.send(text_data=json.dumps(event))

    async def call_answered(self, event):
        await self.send(text_data=json.dumps(event))

    async def call_ended(self, event):
        await self.send(text_data=json.dumps(event))

    # ── DB helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _get_extension(self, user):
        try:
            from apps.pbx.models import AgentExtension
            return AgentExtension.objects.get(staff__user=user)
        except AgentExtension.DoesNotExist:
            return None
        except Exception as exc:
            logger.debug('_get_extension error for user %s: %s', user, exc)
            return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Push helpers called by ami_bridge.py (sync context via sync_to_async wrapper)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def push_incoming_call(session_pk: int):
    """
    Called from AMI bridge (sync Django ORM context) after a CallSession is created.
    Builds the customer context payload and fires it over the channel layer.
    """
    import asyncio
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    payload = _build_call_payload(session_pk)
    if not payload:
        return

    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    try:
        async_to_sync(channel_layer.group_send)(
            'pbx_all_agents',
            {'type': 'incoming_call', **payload},
        )
    except Exception as exc:
        logger.warning('push_incoming_call: channel_layer send failed: %s', exc)


def _build_call_payload(session_pk: int) -> dict | None:
    """Build the JSON payload for an incoming_call event."""
    try:
        from apps.pbx.models import CallSession, PBXQueue
        session = (
            CallSession.objects
            .select_related('customer', 'queue')
            .get(pk=session_pk)
        )
    except Exception:
        return None

    customer_data = None
    if session.customer:
        customer_data = _build_customer_context(session.customer)

    return {
        'type': 'incoming_call',
        'session_id':  session.pk,
        'unique_id':   session.unique_id,
        'caller_id':   session.caller_number,
        'queue':       session.queue.name if session.queue else None,
        'branch':      session.queue.branch.name_ar if (session.queue and session.queue.branch_id) else None,
        'started_at':  session.started_at.isoformat() if session.started_at else None,
        'customer':    customer_data,
    }


def _build_customer_context(customer) -> dict:
    """Collect CRM data useful to the agent during a live call."""
    from apps.customers.models import PurchaseHistory
    from apps.vouchers.models import Voucher

    # Last 5 purchases
    last_purchases = list(
        PurchaseHistory.objects
        .filter(customer=customer, doc_code='115')
        .order_by('-invoice_date')
        .values('invoice_number', 'invoice_date', 'total_amount', 'branch__name_ar')[:5]
    )
    for p in last_purchases:
        if p.get('invoice_date'):
            p['invoice_date'] = p['invoice_date'].isoformat()

    # Active / pending vouchers
    open_vouchers = list(
        Voucher.objects
        .filter(customer=customer, status__in=('active', 'partially_used'))
        .values('voucher_number', 'balance', 'expiry_date', 'voucher_type')[:10]
    )
    for v in open_vouchers:
        if v.get('expiry_date'):
            v['expiry_date'] = v['expiry_date'].isoformat()

    # Open follow-up cases
    open_cases = []
    try:
        from apps.followups.models import FollowupTask
        open_cases = list(
            FollowupTask.objects
            .filter(customer=customer, status__in=('pending', 'in_progress'))
            .order_by('-created_at')
            .values('id', 'title', 'due_date', 'priority', 'status')[:5]
        )
        for c in open_cases:
            if c.get('due_date'):
                c['due_date'] = c['due_date'].isoformat() if hasattr(c['due_date'], 'isoformat') else str(c['due_date'])
    except Exception:
        pass

    # Loyalty balance
    loyalty_balance = None
    try:
        from apps.loyalty.models import LoyaltyAccount
        acc = LoyaltyAccount.objects.filter(customer=customer).select_related('tier').first()
        if acc:
            loyalty_balance = {
                'points': acc.softech_points_balance,   # SOFTECH-authoritative balance
                'supplemental': acc.points_balance,     # referral / campaign points
                'tier': acc.tier.name_ar if acc.tier_id else 'برونزي',
            }
    except Exception:
        pass

    return {
        'id':             customer.pk,
        'name':           customer.name or '',
        'phone':          customer.phone or '',
        'segment':        customer.segment or '',
        'last_purchases': last_purchases,
        'open_vouchers':  open_vouchers,
        'open_cases':     open_cases,
        'loyalty':        loyalty_balance,
    }
