"""Test helper: a valid public-guard body (challenge + solved nonce) for a form (N6)."""
import hashlib

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
