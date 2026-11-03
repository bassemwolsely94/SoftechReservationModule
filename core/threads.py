"""
Threads that keep the request's context (N4).

A bare Thread starts with an empty contextvars context, so the SOFTECH gate would see neither who
asked (apps.access.context) nor under which load scope (apps.sync.softech_load). Every thread or
pool task started from request code goes through here instead: the context is copied in the
caller's thread, at call time, and each task runs in its own copy (a Context cannot be entered
twice at once).
"""
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor


def start_thread(target, *, args=(), kwargs=None, name=None, daemon=True) -> threading.Thread:
    """Start `target` on a new thread inside a copy of the caller's context; returns the
    already-started thread."""
    ctx = contextvars.copy_context()
    kwargs = kwargs or {}

    def _run():
        return ctx.run(target, *args, **kwargs)

    t = threading.Thread(target=_run, name=name, daemon=daemon)
    t.start()
    return t


class ContextThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor whose tasks run in the context of whoever submitted them."""

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)
