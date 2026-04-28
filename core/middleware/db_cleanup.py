from django.db import connections

class CloseConnectionsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        for conn in connections.all():
            conn.close_if_unusable_or_obsolete()
        return response