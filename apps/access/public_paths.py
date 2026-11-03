"""
Paths under /api/ that an anonymous request (no signed-in staff user) may reach (N6).

Everything else under /api/ needs a signed-in user: PublicApiMiddleware refuses it (enforce) or
logs it (log). Each entry names the view behind it. A new anonymous view must be added here, and
`test_every_anonymous_view_is_listed` fails until it is. Prefer exact paths; a prefix is used only
where the URL carries a variable segment (a token or a pk) or the whole app is public by design.
"""

PUBLIC_PREFIXES = (
    # apps.users.views login_view / refresh_view / logout_view, apps.users.mfa verify/setup/enable 2FA
    # (the rest of /api/auth/ - me, change-password, 2fa/status - authenticate themselves)
    '/api/auth/',
    # apps.access.views.whoami (AllowAny, throttled; the badge calls it before login)
    '/api/access/whoami/',
    # apps.config.views.theme (GET public; the PUT checks admin itself) - see PUBLIC_GET_ONLY
    '/api/config/theme/',
    # core.csp.csp_report (browser CSP violation reports, no cookies sent)
    '/api/csp-report/',
    # apps.portal.views request_link / auth_exchange; portal customer sessions are not Django users
    # so every portal endpoint is anonymous to Django and checks its own session
    '/api/portal/',
    # apps.demand.views public_item_lookup / public_branches / public_demand_interest (notify page)
    '/api/demand/public/',
    # apps.delivery.views.delivery_public_track (signed token in the path)
    '/api/delivery/track/',
    # apps.access.public_views.challenge (N6 proof-of-work challenge, throttled), notify/*, track/<token>/
    '/api/public/',
    # apps.pbx.views.RecordingView (permission_classes=[]; signed ?t= token, <audio> cannot send JWT)
    '/api/pbx/recordings/',
    # apps.social.views.MetaGraphWebhookView (csrf_exempt; hub verify token + X-Hub-Signature-256)
    '/api/social/webhook/meta/',
    # apps.social.views.TelegramWebhookView (csrf_exempt; X-Telegram-Bot-Api-Secret-Token)
    '/api/social/webhook/telegram/',
    # apps.social.views.TikTokWebhookView (csrf_exempt placeholder; ignores the payload, answers 501)
    '/api/social/webhook/tiktok/',
    # apps.whatsapp.views.WebhookView (csrf_exempt; hub verify token + X-Hub-Signature-256)
    '/api/whatsapp/webhook/',
)

# Allowed for GET / HEAD / OPTIONS only; any other method needs a signed-in user.
PUBLIC_GET_ONLY = (
    '/api/config/theme/',
)

_SAFE = ('GET', 'HEAD', 'OPTIONS')


def is_public(path: str, method: str) -> bool:
    path = path or ''
    method = (method or 'GET').upper()
    for prefix in PUBLIC_GET_ONLY:
        if path.startswith(prefix):
            return method in _SAFE
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)
