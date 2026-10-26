"""
apps/pbx/linking.py

One CallLog per PBX call: match the agent's manual save to the CallSession the
PBX is tracking, so the agent's notes and the PBX's duration/recording/transcript
land on the same row.
"""
from datetime import timedelta

from django.utils import timezone

MATCH_WINDOW = timedelta(hours=2)


def _tail(number: str) -> str:
    digits = ''.join(ch for ch in (number or '') if ch.isdigit())
    return digits[-9:]


def find_session_for_agent_call(profile, phone: str, session_id=None):
    """
    The CallSession an agent's save belongs to, or None.
    Only sessions on the agent's own extension that no agent has claimed yet
    (no CallLog, or the PBX's own auto-created one).
    """
    from apps.pbx.models import AgentExtension, CallSession

    ext = AgentExtension.objects.filter(staff=profile).first() if profile else None
    if ext is None:
        return None

    qs = (CallSession.objects
          .filter(agent=ext, started_at__gte=timezone.now() - MATCH_WINDOW)
          .select_related('call_log'))
    unclaimed = [s for s in (qs.filter(pk=session_id) if session_id else qs.order_by('-started_at')[:20])
                 if s.call_log is None or s.call_log.source == 'pbx']

    tail = _tail(phone)
    for s in unclaimed:
        if session_id or (tail and tail in (_tail(s.caller_number), _tail(s.destination_ext))):
            return s
    return None
