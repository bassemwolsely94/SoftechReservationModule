from django.conf import settings
from django.db import connections


class CloseConnectionsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Skip connection cleanup during tests: Django's test runner wraps each
        # test in a transaction and relies on the connection staying open.
        # Calling close_if_unusable_or_obsolete() here can close the connection
        # mid-test (especially under Python 3.14) causing InterfaceError.
        if not getattr(settings, 'TESTING', False):
            for conn in connections.all():
                conn.close_if_unusable_or_obsolete()
        return response
