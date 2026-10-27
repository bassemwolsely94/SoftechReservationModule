"""
apps/portal/auth.py

Customer-scoped DRF authentication for the self-service portal.

Isolation guarantees:
  * A portal session token is NOT a JWT, so the global `JWTAuthentication` used
    by every staff API rejects it → staff endpoints are unreachable with a
    portal token.
  * Portal views set `authentication_classes = [PortalSessionAuthentication]`
    ONLY (overriding the global default) + `permission_classes = [IsPortalCustomer]`.
    A staff JWT is not a valid `portal-session` signed token → portal endpoints
    are unreachable with a staff JWT.

The authenticated principal wraps a single `Customer`; views must hard-scope all
queries to `request.user.customer` and never accept a customer id from the client.
"""
from rest_framework import authentication, exceptions, permissions

from apps.customers.models import Customer
from apps.portal.tokens import read_session_token

# Custom scheme keyword so it can never collide with the staff `Bearer` JWT.
AUTH_KEYWORD = 'Portal'


class PortalPrincipal:
    """
    Lightweight authenticated principal for a portal customer.

    Quacks like an authenticated user for DRF/permission checks but is NOT a
    Django `User`/`StaffProfile` — it carries no staff permissions.
    """

    is_authenticated = True
    is_staff = False
    is_active = True
    is_anonymous = False

    def __init__(self, customer: Customer):
        self.customer = customer

    @property
    def id(self):
        return self.customer.id

    def __str__(self):
        return f'PortalCustomer<{self.customer.softech_pic}>'


class PortalSessionAuthentication(authentication.BaseAuthentication):
    """Authenticate `Authorization: Portal <session-token>`."""

    keyword = AUTH_KEYWORD

    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()
        if not auth or auth[0].decode().lower() != self.keyword.lower():
            return None  # Not a portal request — let other auth (or none) handle it.
        if len(auth) != 2:
            raise exceptions.AuthenticationFailed('رأس التوثيق غير صالح')

        token = auth[1].decode()
        pic = read_session_token(token)
        if not pic:
            raise exceptions.AuthenticationFailed('انتهت الجلسة — سجّل الدخول مرة أخرى')

        customer = Customer.objects.filter(softech_pic=pic).first()
        if customer is None:
            raise exceptions.AuthenticationFailed('الحساب غير موجود')

        return (PortalPrincipal(customer), token)

    def authenticate_header(self, request):
        return self.keyword


class IsPortalCustomer(permissions.BasePermission):
    """Allow only an authenticated portal customer principal."""

    message = 'مطلوب تسجيل دخول العميل'

    def has_permission(self, request, view):
        return isinstance(getattr(request, 'user', None), PortalPrincipal)
