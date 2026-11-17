"""Fake adapter for tests only (never offered in any UI). Records every call in CALLS."""
from apps.marketplace.adapters.manual import ManualAdapter

CALLS: list = []
FAIL_NEXT = False  # set True to make the next network call raise once


def reset():
    global FAIL_NEXT
    CALLS.clear()
    FAIL_NEXT = False


def _record(method, *args):
    global FAIL_NEXT
    CALLS.append((method, args))
    if FAIL_NEXT:
        FAIL_NEXT = False
        raise RuntimeError('fake adapter failure')
    return {'ok': True, 'method': method}


class FakeAdapter(ManualAdapter):
    code = 'fake'

    def verify_webhook(self, request) -> bool:
        secret = (self.channel.credentials or {}).get('secret') if self.channel else None
        return bool(secret) and request.headers.get('X-Fake-Signature') == secret

    def push_stock(self, store, rows):
        return _record('push_stock', store, rows)

    def push_prices(self, store, rows):
        return _record('push_prices', store, rows)

    def send_status(self, order, status):
        return _record('send_status', order, status)
