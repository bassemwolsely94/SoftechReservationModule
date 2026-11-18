"""
Honour X-Idempotency-Key on the mobile offline-queue endpoints (full audit 2026-11-15, FE-1).

frontend/src/api/offlineQueue.js replays a queued POST with a stable `X-Idempotency-Key` when the network
dropped before the reply arrived. Nothing on the server read that header, so a write that had already
landed (a reservation, a demand record, a shortage line, a stock count) was created a second time.

Only the paths in QUEUED_PATHS are covered, only for POST, only when the header is present:
  • first request  → reserve (key, path) with status 0, run the view, keep the row on a 2xx (status set),
                     delete it on anything else (so a retry after a failure runs normally);
  • replay after a 2xx → that status with {"idempotent_replay": true} and no write (the queue only needs
                     the status to drop the item; no stored body, so nothing of another request leaks);
  • replay while the first still runs → 202 "processing".
Runs after ModuleAccessMiddleware, so a refused or anonymous request never reserves a key.
"""
import re

from django.db import IntegrityError, transaction
from django.http import JsonResponse

QUEUED_PATHS = (
    re.compile(r'^/api/demand/$'),
    re.compile(r'^/api/reservations/$'),
    re.compile(r'^/api/stockcount/daily/my/count/$'),
    re.compile(r'^/api/stockcount/sessions/\d+/count-item/$'),
    re.compile(r'^/api/shortage/lists/\d+/(add-item|bulk-import)/$'),
)
_KEY_OK = re.compile(r'^[A-Za-z0-9_.:-]{8,64}$')


def _covered(request):
    if request.method != 'POST' or not any(p.match(request.path) for p in QUEUED_PATHS):
        return None
    key = (request.headers.get('X-Idempotency-Key') or '').strip()
    return key if _KEY_OK.match(key) else None


class IdempotencyKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = _covered(request)
        if key is None:
            return self.get_response(request)
        from apps.config.models import IdempotentRequest
        try:
            with transaction.atomic():
                rec = IdempotentRequest.objects.create(key=key, path=request.path)
        except IntegrityError:
            prior = IdempotentRequest.objects.filter(key=key, path=request.path).first()
            if prior is None:                              # deleted between the two reads: just run it
                return self.get_response(request)
            if prior.status == 0:
                return JsonResponse({'detail': 'processing', 'idempotent_replay': True}, status=202)
            return JsonResponse({'detail': 'already processed', 'idempotent_replay': True}, status=prior.status)
        try:
            response = self.get_response(request)
        except Exception:
            IdempotentRequest.objects.filter(pk=rec.pk).delete()
            raise
        if 200 <= response.status_code < 300:
            user = getattr(request, 'user', None)
            IdempotentRequest.objects.filter(pk=rec.pk).update(
                status=response.status_code,
                user_id=user.pk if getattr(user, 'is_authenticated', False) else None)
        else:
            IdempotentRequest.objects.filter(pk=rec.pk).delete()
        return response
