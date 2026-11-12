"""
Thread-local middleware that stores the currently authenticated StaffProfile
so serializers and helpers can call get_current_user_profile() without
requiring the request object to be threaded through every call.
"""
import threading

_thread_local = threading.local()


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        profile = None
        if request.user and request.user.is_authenticated:
            profile = getattr(request.user, 'staff_profile', None)
        _thread_local.profile = profile
        _thread_local.request = request
        _thread_local.ip = _get_client_ip(request)
        try:
            response = self.get_response(request)
        finally:
            _thread_local.profile = None
            _thread_local.request = None
            _thread_local.ip = None
        return response


def get_current_user_profile():
    """Return the StaffProfile of the currently authenticated user, or None.

    API requests authenticate by JWT inside the DRF view, after this middleware ran, so request.user was still
    anonymous here. DRF then sets the authenticated user on the underlying request, so it is read from there
    when no profile was captured up front."""
    profile = getattr(_thread_local, 'profile', None)
    if profile is not None:
        return profile
    request = getattr(_thread_local, 'request', None)
    user = getattr(request, 'user', None) if request is not None else None
    if user is not None and getattr(user, 'is_authenticated', False):
        return getattr(user, 'staff_profile', None)
    return None


def get_current_ip():
    """Return the IP address of the current request, or None."""
    return getattr(_thread_local, 'ip', None)


def _get_client_ip(request):
    # Not the first X-Forwarded-For entry — the client writes that one (A-6).
    from core.client_ip import client_ip
    return client_ip(request)
