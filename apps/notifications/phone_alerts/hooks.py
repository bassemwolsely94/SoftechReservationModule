"""
Glue between the workflows (reservations, transfers, tasks) and ``dispatch.fire``.

Workflows call the ``on_*`` helpers once per real transition; the serializer mixins apply the
server-side rule for the requester's «نبّه على الموبايل» toggle and expose the alert status.
Nothing here ever raises into the workflow (``fire`` swallows failures by default).
"""
from django.contrib.contenttypes.models import ContentType

from .dispatch import fire
from .models import PhoneAlert, PhoneAlertPolicy


# ── fire helpers ─────────────────────────────────────────────────────────────

def on_reservation_created(reservation, actor=None):
    if reservation.status == 'pending':
        fire('reservation_sourcing', reservation, actor=actor)


def on_reservation_status(reservation, actor=None):
    """Call once per real status change."""
    if reservation.priority == 'urgent':
        fire('reservation_status_urgent', reservation, actor=actor)


def on_transfer_submitted(transfer, actor=None):
    """The submit transition: an HQ supplier alerts the dispatcher; a branch supplier does not."""
    if transfer.supplying_branch_id and transfer.supplying_branch.is_hq:
        fire('transfer_hq_submitted', transfer, actor=actor)


def on_transfer_status(transfer, actor=None):
    """Every status change after submission."""
    fire('transfer_status', transfer, actor=actor)


def on_task_assigned(task, actor=None, only_staff=None):
    """``only_staff``: alert just the newly assigned person(s) (StaffProfile pks)."""
    fire('task_assigned', task, actor=actor, only_staff=only_staff)


def on_task_status(task, actor=None):
    fire('task_status', task, actor=actor)


# ── toggle rule ──────────────────────────────────────────────────────────────

def apply_policy(event_keys, requested):
    """Stored value of the one per-record toggle, coerced across ALL the model's events:
    True if any policy is 'always'; False only if every event is never/absent; else as ticked."""
    if isinstance(event_keys, str):
        event_keys = (event_keys,)
    modes = []
    for key in event_keys:
        policy = PhoneAlertPolicy.for_event(key)
        modes.append(policy.mode if policy is not None else 'never')
    if 'always' in modes:
        return True
    if all(m == 'never' for m in modes):
        return False
    return bool(requested)


class PhoneAlertWriteMixin:
    """For write serializers with a ``phone_alert`` field: coerce it by the model's event policies.

    Set ``phone_alert_events`` on the serializer (every event the record can raise).
    """
    phone_alert_events = ()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance is None or 'phone_alert' in attrs:
            attrs['phone_alert'] = apply_policy(self.phone_alert_events, attrs.get('phone_alert', False))
        return attrs


# ── read-only status / remark ────────────────────────────────────────────────

def alert_info(model, ids):
    """{source_id: (status, remark)} — latest alert per source ('acknowledged' wins), one query."""
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    ct = ContentType.objects.get_for_model(model)
    rows = (PhoneAlert.objects.filter(source_ct=ct, source_id__in=ids, kind='alert')
            .exclude(event='escalation').order_by('-created_at', '-pk')
            .only('source_id', 'status', 'remark', 'created_at'))
    out = {}
    for a in rows:                                      # newest first
        current = out.get(a.source_id)
        if current is None or (a.status == 'acknowledged' and current[0] != 'acknowledged'):
            out[a.source_id] = (a.status, a.remark or '')
    return out


class PhoneAlertStatusMixin:
    """Provides get_phone_alert_status / get_phone_alert_remark for same-named SerializerMethodFields.

    Inside a list serializer the whole page is resolved with one query (cached on the parent).
    """
    phone_alert_model = None

    def _alert_cache(self):
        parent = getattr(self, 'parent', None)
        holder = parent if parent is not None else self
        cache = getattr(holder, '_phone_alert_cache', None)
        if cache is None:
            ids = []
            instance = getattr(parent, 'instance', None)
            if instance is not None and not hasattr(instance, 'pk'):   # many=True: page / queryset / manager
                if hasattr(instance, 'all'):
                    instance = instance.all()
                ids = [o.pk for o in instance]
            cache = {'map': alert_info(self.phone_alert_model, ids), 'ids': set(ids)}
            holder._phone_alert_cache = cache
        return cache

    def _alert_for(self, obj):
        cache = self._alert_cache()
        if obj.pk not in cache['ids']:               # single object (detail) or an unexpected row
            cache['map'].update(alert_info(self.phone_alert_model, [obj.pk]))
            cache['ids'].add(obj.pk)
        return cache['map'].get(obj.pk)

    def get_phone_alert_status(self, obj):
        info = self._alert_for(obj)
        return info[0] if info else None

    def get_phone_alert_remark(self, obj):
        info = self._alert_for(obj)
        return info[1] if info else ''
