"""
apps/notifications/send_limits.py — at most one automatic message per recipient per type per window.

Round 2, R5, owner question 6 (default approved 2026-11-05): one recipient gets at most 1 automatic
message of each type per 10 minutes (``SEND_MIN_INTERVAL_SECONDS``, default 600). Every sender
calls ``claim(kind, recipient)`` right before it sends and sends only when it returns True:

    phone alerts + call-back alerts   kind = 'phone_alert:<event>'   (phone_alerts.sender)
    morning brief / expiry worklist   kind = 'phone_alert:<event>'   (same path)
    insights narrative texts          kind = 'insights:<domain>:<period>'
    counselling card                  kind = 'counsel_card'

The claim is one atomic UPDATE / INSERT on ``SendThrottle`` (unique recipient+kind), so two
processes racing for the same number can't both win. A claimed slot is used even if the send then
fails, unless the sender gives it back with ``release`` because nothing reached the person.
Only a hash of the number is stored.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone


def interval() -> timedelta:
    return timedelta(seconds=int(getattr(settings, 'SEND_MIN_INTERVAL_SECONDS', 600)))


def recipient_hash(recipient) -> str:
    """One hash per phone however it was written (01012345678 / +20 10… / 0020…)."""
    from core.sms import sms_number
    digits = ''.join(ch for ch in str(recipient or '') if ch.isdigit())
    key = sms_number(digits) if digits else str(recipient or '')
    return hashlib.sha256(key.encode()).hexdigest()


def release(kind: str, recipient, claimed_at) -> None:
    """Give the slot back after a send that reached nobody (provider error, no fallback).
    Only this caller's own claim is cleared — a later claim by someone else stays."""
    from .phone_alerts.models import SendThrottle
    SendThrottle.objects.filter(recipient_hash=recipient_hash(recipient), kind=str(kind)[:80],
                                last_sent_at=claimed_at).delete()


def claim(kind: str, recipient, now=None) -> bool:
    """True when this caller may send ``kind`` to ``recipient`` now (and the slot is taken)."""
    from .phone_alerts.models import SendThrottle
    now = now or timezone.now()
    h, kind = recipient_hash(recipient), str(kind)[:80]
    if SendThrottle.objects.filter(recipient_hash=h, kind=kind,
                                   last_sent_at__lte=now - interval()).update(last_sent_at=now):
        return True
    try:
        with transaction.atomic():
            SendThrottle.objects.create(recipient_hash=h, kind=kind, last_sent_at=now)
        return True
    except IntegrityError:          # a row exists and is inside the window (or a racer just won)
        return False
