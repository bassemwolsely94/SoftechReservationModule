"""
JWT in httpOnly cookies for the staff SPA.

The access/refresh tokens used to live in localStorage, where any injected script
can read them. Now login / 2FA / refresh set them as httpOnly cookies the page's
JavaScript cannot touch; the SPA no longer stores tokens at all.

  • CookieJWTAuthentication: `Authorization: Bearer` keeps working (scripts,
    tests, any non-browser client); without it the access cookie is used.
  • CSRF: a cookie is sent by the browser automatically, so a cookie is only
    honoured on a write that also carries `X-Requested-With: XMLHttpRequest` — a
    header another site cannot add to a cross-site request. Without it the request
    is treated as anonymous. Cookies are SameSite=Strict as well.
  • The refresh cookie is scoped to /api/auth/ so it is never sent elsewhere.
  • AUTH_COOKIE_SECURE (default: on when the site is served over HTTPS) adds the
    Secure flag; leave it off only for plain-HTTP LAN deployments.
"""
from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication

ACCESS_COOKIE = 'erp_access'
REFRESH_COOKIE = 'erp_refresh'
REFRESH_COOKIE_PATH = '/api/auth/'
CSRF_HEADER = 'HTTP_X_REQUESTED_WITH'
_SAFE = ('GET', 'HEAD', 'OPTIONS')


def _cookie_kwargs():
    return {
        'httponly': True,
        'secure': bool(getattr(settings, 'AUTH_COOKIE_SECURE', False)),
        'samesite': 'Strict',
    }


def set_auth_cookies(response, access=None, refresh=None):
    jwt = settings.SIMPLE_JWT
    if access:
        response.set_cookie(ACCESS_COOKIE, str(access), path='/',
                            max_age=int(jwt['ACCESS_TOKEN_LIFETIME'].total_seconds()),
                            **_cookie_kwargs())
    if refresh:
        response.set_cookie(REFRESH_COOKIE, str(refresh), path=REFRESH_COOKIE_PATH,
                            max_age=int(jwt['REFRESH_TOKEN_LIFETIME'].total_seconds()),
                            **_cookie_kwargs())
    return response


def clear_auth_cookies(response):
    response.delete_cookie(ACCESS_COOKIE, path='/', samesite='Strict')
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite='Strict')
    return response


class CookieJWTAuthentication(JWTAuthentication):

    def authenticate(self, request):
        if self.get_header(request) is not None:
            return super().authenticate(request)
        raw = request.COOKIES.get(ACCESS_COOKIE)
        if not raw:
            return None
        if request.method not in _SAFE and request.META.get(CSRF_HEADER) != 'XMLHttpRequest':
            # Possible cross-site forgery: ignore the cookie (treat as anonymous).
            # Protected views then refuse; public ones (e.g. the "notify me" form a
            # logged-in staff browser may post with plain fetch) keep working.
            return None
        validated = self.get_validated_token(raw)
        return self.get_user(validated), validated


def user_from_request(request):
    """Header or cookie JWT → user, without the CSRF check (read-only callers
    such as the RBAC middleware). None when absent/invalid."""
    auth = CookieJWTAuthentication()
    try:
        if auth.get_header(request) is not None:
            result = auth.authenticate(request)
            return result[0] if result else None
        raw = request.COOKIES.get(ACCESS_COOKIE)
        if not raw:
            return None
        return auth.get_user(auth.get_validated_token(raw))
    except Exception:
        return None
