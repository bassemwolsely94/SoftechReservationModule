"""
Who is asking and from where, computed once per request (N1). Later batches add the device.
"""
import contextvars
from dataclasses import dataclass

from core.auth_cookies import user_from_request

from .network import EXTERNAL, NetworkInfo, request_network

access_context = contextvars.ContextVar('access_context', default=None)


@dataclass(frozen=True)
class AccessContext:
    network: NetworkInfo
    user_id: int | None
    role: str | None


def current():
    return access_context.get()


def _role(user):
    profile = getattr(user, 'staff_profile', None)
    if profile is not None:
        return profile.role
    return 'admin' if getattr(user, 'is_superuser', False) else None


def for_request(request):
    network = request_network(request)
    user = user_from_request(request)
    return AccessContext(network=network, user_id=user.pk if user else None,
                         role=_role(user) if user else None)


def fallback():
    """What a request is treated as when its context could not be worked out."""
    return AccessContext(network=NetworkInfo(zone=EXTERNAL, ip=None, site=None), user_id=None, role=None)
