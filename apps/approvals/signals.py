"""
apps/approvals/signals.py
=========================
Post-save signal on ApprovalRequest.

When a request transitions to a TERMINAL state (approved / rejected),
this fires an `approval_outcome` Django signal that interested apps can
listen to without creating circular imports.

Registration pattern (in each app's apps.py ready()):

    from apps.approvals.signals import register_outcome_handler

    register_outcome_handler('hr.LeaveRequest', my_callback)
    register_outcome_handler('batches.StockBatch', my_callback)

    def my_callback(approval_request, outcome: str) -> None:
        ...

The registry uses lazy "app_label.ModelName" strings to avoid ContentType
DB queries at app startup time (before migrations have run).
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import Signal, receiver

logger = logging.getLogger('elrezeiky.approvals')

# Public signal — other apps can also listen directly if they prefer
approval_outcome = Signal()   # kwargs: approval_request, outcome ('approved'|'rejected')

# Registry: "app_label.ModelName" (lowercased) → list[callable]
# Resolved lazily to ContentType IDs on first dispatch.
_pending_registrations: list[tuple[str, callable]] = []
_resolved_registry: dict[int, list] = {}   # content_type_id → [handler, ...]
_registry_resolved = False


def register_outcome_handler(model_label: str, handler: callable) -> None:
    """
    Register a callback for when an ApprovalRequest linked to the given model
    reaches a terminal state.

    model_label: "app_label.ModelName", e.g. "hr.LeaveRequest"
    handler signature: (approval_request, outcome: str) -> None

    Call this from AppConfig.ready() — resolution is deferred until first dispatch
    so it's safe to call before migrations have run.
    """
    global _registry_resolved
    _pending_registrations.append((model_label.lower(), handler))
    _registry_resolved = False   # force re-resolve on next dispatch
    logger.debug('Queued approval outcome handler for %s: %s', model_label, handler.__qualname__)


def _resolve_registry():
    """Resolve all pending app_label.ModelName strings to ContentType IDs."""
    global _registry_resolved
    from django.contrib.contenttypes.models import ContentType

    for label, handler in _pending_registrations:
        try:
            app_label, model_name = label.split('.')
            ct = ContentType.objects.get(app_label=app_label, model=model_name)
            _resolved_registry.setdefault(ct.pk, [])
            if handler not in _resolved_registry[ct.pk]:
                _resolved_registry[ct.pk].append(handler)
        except Exception as exc:
            logger.debug('Could not resolve content type for %s: %s', label, exc)

    _registry_resolved = True


@receiver(post_save, sender='approvals.ApprovalRequest')
def _on_approval_request_saved(sender, instance, created, **kwargs):
    """
    Fires whenever an ApprovalRequest is saved.
    Dispatches to registered handlers only when the request just moved to a
    TERMINAL state (approved / rejected) — identified by completed_at being set.
    """
    from apps.approvals.models import ApprovalRequest

    if instance.status not in (ApprovalRequest.STATUS_APPROVED, ApprovalRequest.STATUS_REJECTED):
        return

    # Only fire once: completed_at is set exactly when the request closes.
    if not instance.completed_at:
        return

    outcome = 'approved' if instance.status == ApprovalRequest.STATUS_APPROVED else 'rejected'

    # Lazy-resolve the registry on first dispatch
    if not _registry_resolved:
        try:
            _resolve_registry()
        except Exception:
            logger.exception('Failed to resolve approval outcome registry')

    # 1. Dispatch to registered handlers
    for handler in _resolved_registry.get(instance.content_type_id, []):
        try:
            handler(instance, outcome)
        except Exception:
            logger.exception(
                'Approval outcome handler %s failed for request #%s (outcome=%s)',
                handler.__qualname__, instance.pk, outcome,
            )

    # 2. Fire the public Django signal for any other listener
    try:
        approval_outcome.send(
            sender=sender,
            approval_request=instance,
            outcome=outcome,
        )
    except Exception:
        logger.exception('approval_outcome signal dispatch failed for request #%s', instance.pk)
