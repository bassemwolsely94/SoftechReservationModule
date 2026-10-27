"""
apps/tasks/scheduler.py

Auto-generates recurring tasks from TaskSchedule records.
Call run_due_schedules() from a management command or cron job.
"""
import logging
from django.db.models import Q
from django.utils import timezone
from django.utils.timezone import localtime

logger = logging.getLogger(__name__)


def generate_task_from_schedule(schedule, created_by=None):
    """
    Create a single OperationalTask from a TaskSchedule template.
    Returns the created task or None.
    """
    from .models import OperationalTask
    from datetime import timedelta

    now = localtime(timezone.now())
    branch_name = schedule.branch.name if schedule.branch else 'جميع الفروع'

    title = (
        schedule.title_template
        .replace('{date}', now.strftime('%Y-%m-%d'))
        .replace('{branch}', branch_name)
    )
    description = (
        schedule.description_template
        .replace('{date}', now.strftime('%Y-%m-%d'))
        .replace('{branch}', branch_name)
    )

    due = now + timedelta(days=schedule.advance_days)

    task = OperationalTask.objects.create(
        title=title,
        description=description,
        task_type=schedule.task_type,
        category=schedule.category,
        priority=schedule.priority,
        branch=schedule.branch,
        assigned_to=schedule.assign_to,
        due_date=due,
        estimated_hours=schedule.estimated_hours,
        recurrence=schedule.frequency,
        schedule=schedule,
        created_by=created_by,
    )

    schedule.last_run_at = timezone.now()
    schedule.next_run_at = _calc_next_run(schedule)
    schedule.save(update_fields=['last_run_at', 'next_run_at'])

    logger.info(f'[TaskScheduler] Created task {task.task_number} from schedule "{schedule.name}"')
    return task


def _calc_next_run(schedule):
    from datetime import timedelta
    now = timezone.now()
    if schedule.frequency == 'daily':
        return now + timedelta(days=1)
    elif schedule.frequency == 'weekly':
        return now + timedelta(weeks=1)
    elif schedule.frequency == 'monthly':
        return now + timedelta(days=30)
    return None


def run_due_schedules():
    """
    Check all active schedules and generate tasks for those that are due.
    Call this from a management command or cron job.
    """
    from .models import TaskSchedule

    now = timezone.now()
    due_schedules = TaskSchedule.objects.filter(
        is_active=True,
    ).filter(
        Q(next_run_at__isnull=True) | Q(next_run_at__lte=now)
    ).select_related('branch', 'assign_to')

    created = 0
    for schedule in due_schedules:
        try:
            task = generate_task_from_schedule(schedule)
            if task:
                created += 1
        except Exception as e:
            logger.error(f'[TaskScheduler] Error processing schedule {schedule.pk}: {e}')

    logger.info(f'[TaskScheduler] Generated {created} tasks from {due_schedules.count()} due schedules')
    return created
