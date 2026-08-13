"""
apps/tasks/selectors.py — reusable task querysets shared across modules.

Single source of truth for "tasks allocated to a staff member" so the tasks
module's own `my_tasks` view and the personal-dashboard `my_tasks` widget stay
in lockstep and never drift. Import this instead of re-writing the assignee
filter anywhere else.
"""
from django.db.models import Count, Q

from .models import OperationalTask

# Statuses considered closed — excluded from the "active allocated" view.
DONE_STATUSES = ['completed', 'cancelled']


def tasks_for_staff(staff, *, include_done: bool = False):
    """
    OperationalTasks allocated to ``staff`` — as the primary assignee
    (``assigned_to``) OR via an extra ``TaskAssignment``.

    Returns a queryset annotated with subtask/item counts and ordered by
    due date then priority (soonest & most urgent first). Pass
    ``include_done=True`` to keep completed/cancelled tasks.
    """
    if staff is None:
        return OperationalTask.objects.none()
    qs = OperationalTask.objects.filter(
        Q(assigned_to=staff) | Q(assignments__staff=staff)
    )
    if not include_done:
        qs = qs.exclude(status__in=DONE_STATUSES)
    return (
        qs.distinct()
          .annotate(subtask_count=Count('subtasks'), item_count=Count('items'))
          .select_related('branch', 'assigned_to')
          .order_by('due_date', '-priority')
    )
