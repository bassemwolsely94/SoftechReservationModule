"""
apps/audit/middleware.py

Thin middleware that attaches the current request to thread-local storage
so AuditLog.log() can access the IP address without passing request everywhere.

Also provides a helper: get_current_request() for services that need it.
"""
import threading

_thread_locals = threading.local()


def get_current_request():
    return getattr(_thread_locals, 'request', None)


def get_current_user_profile():
    request = get_current_request()
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        return getattr(request.user, 'staff_profile', None)
    return None


class AuditMiddleware:
    """
    Stores the current request in thread-local storage.
    Add to MIDDLEWARE in settings.py (after AuthenticationMiddleware).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.request = request
        try:
            response = self.get_response(request)
        finally:
            _thread_locals.request = None
        return response
