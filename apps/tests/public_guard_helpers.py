"""Test helper: a valid public-guard body (challenge + solved nonce) for a form (N6)."""
import hashlib
from unittest import mock

from core import public_guard


def solved(form, **fields):
    """Body = fields + a freshly issued, solved challenge + empty honeypot. Single-use."""
    ch = public_guard.issue_challenge(form)
    n = 0
    while public_guard.leading_zero_bits(
            hashlib.sha256(f"{ch['challenge']}:{n}".encode()).digest()) < ch['difficulty']:
        n += 1
    body = {'challenge': ch['challenge'], 'nonce': str(n), 'website': ''}
    body.update(fields)
    return body


def portal_send_inline(test):
    """Run the portal's magic-link send (core.threads.start_thread in apps.portal.views) inline for
    the rest of `test`, so assertions on the sender see it and the test DB connection is shared."""
    def _inline(target, *, args=(), kwargs=None, name=None, daemon=True):
        target(*args, **(kwargs or {}))
    p = mock.patch('apps.portal.views.start_thread', side_effect=_inline)
    started = p.start()
    test.addCleanup(p.stop)
    return started
