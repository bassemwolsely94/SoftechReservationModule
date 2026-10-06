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
        _thread_local.ip = _get_client_ip(request)
        try:
            response = self.get_response(request)
        finally:
            _thread_local.profile = None
            _thread_local.ip = None
        return response


def get_current_user_profile():
    """Return the StaffProfile of the currently authenticated user, or None."""
    return getattr(_thread_local, 'profile', None)


def get_current_ip():
    """Return the IP address of the current request, or None."""
    return getattr(_thread_local, 'ip', None)


def _get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
