"""
apps/tests/security/test_breakin_delta.py — round 2, R3 step 5: the break-in delta since 2026-11-03.

What was added since Batch 3 / W-3 that takes part in login, sessions or one-time codes
(git log --since=2026-11-03 over urls / routing / consumers / signing, reviewed 2026-11-05):

  route / token                                   existing coverage (reused, not rebuilt)
  ─────────────────────────────────────────────── ────────────────────────────────────────────────
  /api/public/counsel/<token>/ (+ opt-out)        test_counselling_public: tampered, expired,
    signed, salt CARD_SIGNING_SALT, max_age          other-salt → 404; opt-out idempotent; no
                                                     personal data; failed send has no page
  phone-alert «استلمت» tap (alert:<token>:ack)      test_phone_alerts: other phone ignored, unknown
                                                     token, duplicate tap is a no-op
  /api/public/challenge/, /api/public/health/     test_access_public_gate, test_public_guard
  WebSocket groups                                no new group since 2026-11-03 (only a
                                                     personal_group robustness fix in pbx);
                                                     test_access_ws_consumers covers N5
  every new STAFF route (counselling, finance/gl, below: anonymous refusal on every protected
    usage-print, stockcount/daily, phone-alerts,   route and method, whatever its age
    missed-sales, pic-analytics, forecasting)

This file adds the two gaps: anonymous callers on every protected route, and cross-purpose replay
of the new signed tokens (a token minted for one purpose never opens another).
"""
import logging

from django.core import signing
from django.db import transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .routes import Tripwire, handles
from .sweep import FEATURE_FLAGS_ON, METHODS, protected_routes

# 404 / 503 carry no data: commerce answers 503 while COMMERCE is switched off (before auth), and the
# two nested replacement action routes answer 404 to everyone (their pattern never reaches a view).
_REFUSED = {401, 403, 404, 405, 503}


def _code(client, method, path):
    try:
        with transaction.atomic():
            if method == 'GET':
                r = client.get(path)
            elif method == 'DELETE':
                r = client.delete(path)
            else:
                r = getattr(client, method.lower())(path, {}, format='json')
            transaction.set_rollback(True)
        return r.status_code
    except Exception as exc:          # noqa: BLE001
        return f'raised {type(exc).__name__}'


def _clear_cache():
    from django.core.cache import cache
    cache.clear()


class AnonymousRefusalTests(TestCase):
    """No protected route answers an anonymous caller, in either public-gate mode."""
    maxDiff = None

    def _sweep(self, mode):
        anon, out = APIClient(), {}
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with override_settings(PUBLIC_API_ENFORCEMENT=mode, RBAC_ENFORCEMENT='log', **FEATURE_FLAGS_ON), \
                    Tripwire():
                for path in protected_routes():
                    for m in METHODS:
                        if handles(path, m):
                            code = _code(anon, m, path)
                            if code not in _REFUSED:
                                out[f'{m} {path}'] = code
        finally:
            logging.disable(previous)
            _clear_cache()   # rolled-back requests still write the cache (locks, throttles)
        return out

    def test_anonymous_refused_everywhere_with_the_gate_off(self):
        """The views' own authentication, without the N6 public gate in front."""
        self.assertEqual(self._sweep('off'), {})

    def test_anonymous_refused_everywhere_with_the_gate_enforcing(self):
        self.assertEqual(self._sweep('enforce'), {})


class TokenReplayTests(TestCase):
    """A signed token is bound to its purpose (salt). Each new token type is minted with every
    OTHER known salt for the same object and must be refused by its own reader."""
    maxDiff = None

    def test_counsel_card_reader_refuses_other_purposes(self):
        from apps.counselling.cards import CARD_SIGNING_SALT
        from apps.delivery import views as delivery_views
        from apps.portal import tokens as portal_tokens
        others = {getattr(delivery_views, '_TRACK_SALT', 'delivery-track'),
                  getattr(portal_tokens, 'MAGIC_SALT', 'portal-magic'),
                  getattr(portal_tokens, 'SESSION_SALT', 'portal-session')} - {CARD_SIGNING_SALT}
        self.assertTrue(others)
        anon = APIClient()
        for salt in others:
            for payload in ({'s': 1}, {'oid': 1}, {'pic': 'X', 'k': 'magic', 'n': 'a'}):
                token = signing.dumps(payload, salt=salt)
                self.assertEqual(anon.get(f'/api/public/counsel/{token}/').status_code, 404, salt)
                self.assertIn(anon.post(f'/api/public/counsel/{token}/opt-out/', {}).status_code, (400, 404), salt)

    def test_card_token_does_not_open_the_delivery_tracker(self):
        from apps.counselling.cards import CARD_SIGNING_SALT
        token = signing.dumps({'oid': 1}, salt=CARD_SIGNING_SALT)
        r = APIClient().get(f'/api/delivery/track/{token}/')
        self.assertIn(r.status_code, (400, 403, 404))
