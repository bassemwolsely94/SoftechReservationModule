"""
Prefix -> handler registry for WhatsApp quick-reply button payloads.

Features register the payload prefix they own (``refill:``, ``alert:``); the webhook calls
``dispatch`` and never needs to know the features. A handler is called as
``handler(wa_id=, payload=, context_wamid=, account=)`` and returns a short outcome string.
"""
_HANDLERS = {}


def register(prefix, handler):
    """Register ``handler`` for payloads starting with ``prefix`` (re-registering replaces)."""
    _HANDLERS[prefix] = handler


def dispatch(*, wa_id, payload, context_wamid='', account=None):
    """Route one tap to its feature. Returns ``'not_ours'`` when no registered prefix matches."""
    payload = payload or ''
    for prefix, handler in _HANDLERS.items():
        if payload.startswith(prefix):
            return handler(wa_id=wa_id, payload=payload, context_wamid=context_wamid, account=account)
    return 'not_ours'
