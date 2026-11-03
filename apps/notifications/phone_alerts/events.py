"""
Phone-alert event registry: key -> who is alerted and how to tell the matter is still open.

Adding another alertable event is a small code change here (each event needs its own recipient
rule and close test), not a setting.
"""
from dataclasses import dataclass
from typing import Callable, Optional

TRANSFER_CLOSED = {'sent_to_erp', 'completed', 'rejected', 'cancelled'}
TASK_CLOSED = {'completed', 'cancelled'}


@dataclass(frozen=True)
class Event:
    key: str
    label_ar: str
    source_model: str            # 'app_label.modelname'
    recipients: str              # 'owner' | 'person' | 'branch' | 'escalation'
    owner_kind: Optional[str]
    is_open: Callable            # obj -> bool; tolerant of a deleted source (None -> closed)


def _safe(fn):
    def wrapper(obj):
        if obj is None:
            return False
        try:
            return bool(fn(obj))
        except Exception:
            return False
    return wrapper


def _escalation_open(alert):
    """An escalation is open while the original alert is unacknowledged and its source is still open."""
    original = getattr(alert, 'escalation_of', None)
    if original is None or original.status in ('acknowledged', 'expired'):
        return False
    event = EVENTS.get(original.event)
    if event is None:
        return False
    return event.is_open(original.source)


EVENTS = {
    'reservation_sourcing': Event(
        'reservation_sourcing', 'حجز بانتظار التوفير', 'reservations.reservation',
        'owner', 'reservation_sourcing', _safe(lambda o: o.status == 'pending')),
    'transfer_hq_submitted': Event(
        'transfer_hq_submitted', 'تحويل جديد للمخزن الرئيسي', 'transfers.transferrequest',
        'owner', 'hq_transfer_dispatch', _safe(lambda o: o.status not in TRANSFER_CLOSED)),
    'transfer_status': Event(
        'transfer_status', 'تغيّر حالة تحويل', 'transfers.transferrequest',
        'person', None, _safe(lambda o: o.status not in TRANSFER_CLOSED)),
    'reservation_status_urgent': Event(
        'reservation_status_urgent', 'تغيّر حالة حجز عاجل', 'reservations.reservation',
        'branch', None, _safe(lambda o: o.is_active)),
    'task_assigned': Event(
        'task_assigned', 'مهمة جديدة', 'tasks.operationaltask',
        'person', None, _safe(lambda o: o.status not in TASK_CLOSED)),
    'task_status': Event(
        'task_status', 'تغيّر حالة مهمة', 'tasks.operationaltask',
        'person', None, _safe(lambda o: o.status not in TASK_CLOSED)),
    'escalation': Event(
        'escalation', 'تصعيد تنبيه لم يُستلم', 'notifications.phonealert',
        'escalation', None, _safe(_escalation_open)),
}

EVENT_CHOICES = [(k, e.label_ar) for k, e in EVENTS.items()]
