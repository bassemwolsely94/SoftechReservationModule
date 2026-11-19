"""Every response of the UAT copy carries `X-UAT-Copy: <database name>` (config.settings_uat only).

The UAT harness checks it before any login (frontend/uat/lib/guard.js), so a test run can never
reach a server that is not the restored copy — e.g. the office writer on :8000 behind a reused Vite.
"""
from django.conf import settings


class UatCopyMarker:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(settings, 'UAT_SETTINGS', False):
            response['X-UAT-Copy'] = settings.DATABASES['default']['NAME']
        return response
