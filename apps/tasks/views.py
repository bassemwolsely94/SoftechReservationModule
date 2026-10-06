"""
apps/tasks/views.py
"""
import os
from django.db.models import Count, Q, Prefetch
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.notifications.models import Notification

from .models import (
    OperationalTask, TaskAssignment, TaskItem,
    TaskMessage, TaskAttachment, TaskSchedule, TaskAuditLog,
    STATUS_CHOICES, PRIORITY_CHOICES, TASK_TYPE_CHOICES, CATEGORY_CHOICES,
)
from .serializers import (
    TaskListSerializer, TaskDetailSerializer, TaskWriteSerializer,
    TaskAssignmentSerializer, TaskItemSerializer,
    TaskMessageSerializer, TaskAttachmentSerializer,
    TaskScheduleSerializer, TaskAuditLogSerializer,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_staff(request):
    """Safely get the StaffProfile for the requesting user."""
    try:
        return request.user.staff_profile
    except Exception:
        return None


def _log_audit(task, action, actor, field_name='', old_value='', new_value='', extra=None):
    TaskAuditLog.objects.create(
        task=task,
        action=action,
        actor=actor,
        field_name=field_name,
        old_value=str(old_value) if old_value else '',
        new_value=str(new_value) if new_value else '',
        extra=extra or {},
    )


def _add_system_message(task, body):
    TaskMessage.objects.create(
        task=task,
        author=None,
        message_type='system',
        body=body,
    )


def _notify_assignee(task, staff, actor_staff):
    """Send notification to newly assigned staff."""
    if not staff:
        return
    try:
        Notification.send_to_user(
            recipient=staff,
            notification_type='system',
            title=f'مهمة جديدة: {task.title}',
            body=f'تم تعيينك لمهمة "{task.title}" — {task.get_priority_display()} — موعد: '
                 f'{task.due_date.strftime("%Y-%m-%d") if task.due_date else "غير محدد"}',
            dedup_key=f'task-assign-{task.pk}-{staff.pk}',
        )
    except Exception:
        pass


def _notify_watchers(task, message, exclude_staff=None):
    """Notify all assignees (except actor) about a task update."""
    watchers = set()
    if task.assigned_to:
        watchers.add(task.assigned_to)
    for a in task.assignments.select_related('staff').all():
        watchers.add(a.staff)
    if exclude_staff:
        watchers.discard(exclude_staff)
    for staff in watchers:
        try:
            Notification.send_to_user(
                recipient=staff,
                notification_type='system',
                title=f'تحديث على مهمة: {task.task_number}',
                body=message,
                dedup_key=f'task-update-{task.pk}-{timezone.now().strftime("%Y%m%d%H%M")}',
            )
        except Exception:
            pass


# ── Task List / Create ─────────────────────────────────────────────────────────

class TaskListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TaskWriteSerializer
        return TaskListSerializer

    def get_queryset(self):
        qs = OperationalTask.objects.select_related(
            'assigned_to', 'branch', 'created_by',
        ).annotate(
            subtask_count=Count('subtasks', distinct=True),
            item_count=Count('items', distinct=True),
        )

        p = self.request.query_params

        # Filters
        if status_val := p.get('status'):
            qs = qs.filter(status=status_val)
        if priority := p.get('priority'):
            qs = qs.filter(priority=priority)
        if task_type := p.get('task_type'):
            qs = qs.filter(task_type=task_type)
        if category := p.get('category'):
            qs = qs.filter(category=category)
        if branch := p.get('branch'):
            qs = qs.filter(branch_id=branch)
        if assigned := p.get('assigned_to'):
            qs = qs.filter(assigned_to_id=assigned)
        if mine := p.get('mine'):
            staff = _get_staff(self.request)
            if staff:
                qs = qs.filter(
                    Q(assigned_to=staff) |
                    Q(assignments__staff=staff)
                ).distinct()
        if parent := p.get('parent'):
            qs = qs.filter(parent_task_id=parent)
        elif p.get('top_level') == '1':
            qs = qs.filter(parent_task__isnull=True)

        if overdue := p.get('overdue'):
            qs = qs.filter(due_date__lt=timezone.now()).exclude(
                status__in=['completed', 'cancelled']
            )

        if q := p.get('search'):
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(task_number__icontains=q) |
                Q(tags__icontains=q)
            )

        if date_from := p.get('date_from'):
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to := p.get('date_to'):
            qs = qs.filter(created_at__date__lte=date_to)
        if due_from := p.get('due_from'):
            qs = qs.filter(due_date__date__gte=due_from)
        if due_to := p.get('due_to'):
            qs = qs.filter(due_date__date__lte=due_to)

        # Ordering
        ordering = p.get('ordering', '-created_at')
        allowed = {'created_at', '-created_at', 'due_date', '-due_date',
                   'priority', '-priority', 'updated_at', '-updated_at'}
        if ordering in allowed:
            qs = qs.order_by(ordering)

        return qs

    def perform_create(self, serializer):
        staff = _get_staff(self.request)
        task = serializer.save(created_by=staff)
        _log_audit(task, 'created', staff)
        _add_system_message(task, f'تم إنشاء المهمة بواسطة {staff.full_name if staff else "النظام"}')
        if task.assigned_to:
            _notify_assignee(task, task.assigned_to, staff)

    def create(self, request, *args, **kwargs):
        ser = TaskWriteSerializer(data=request.data, context={'request': request})
        ser.is_valid(raise_exception=True)
        self.perform_create(ser)
        task = OperationalTask.objects.annotate(
            subtask_count=Count('subtasks'),
            item_count=Count('items'),
        ).get(pk=ser.instance.pk)
        return Response(TaskListSerializer(task, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)


# ── Task Retrieve / Update / Delete ───────────────────────────────────────────

class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return OperationalTask.objects.select_related(
            'assigned_to', 'branch', 'created_by', 'completed_by',
        ).prefetch_related(
            'assignments__staff',
            'items',
            'attachments__uploaded_by',
            'messages__author',
            'audit_logs__actor',
        )

    def get_serializer_class(self):
        if self.request.method in ('PATCH', 'PUT'):
            return TaskWriteSerializer
        return TaskDetailSerializer

    def perform_update(self, serializer):
        task = self.get_object()
        staff = _get_staff(self.request)
        old_status = task.status
        old_priority = task.priority
        old_assigned = task.assigned_to_id

        updated = serializer.save()

        if updated.status != old_status:
            _log_audit(task, 'status_changed', staff,
                       field_name='status', old_value=old_status, new_value=updated.status)
            _add_system_message(task,
                f'تغيرت الحالة من "{dict(STATUS_CHOICES).get(old_status)}" إلى "{updated.get_status_display()}"')
            _notify_watchers(task, f'تغيرت حالة المهمة إلى: {updated.get_status_display()}', staff)

        if updated.priority != old_priority:
            _log_audit(task, 'priority_changed', staff,
                       field_name='priority', old_value=old_priority, new_value=updated.priority)

        if updated.assigned_to_id != old_assigned:
            _log_audit(task, 'assigned', staff,
                       field_name='assigned_to', new_value=str(updated.assigned_to_id))
            if updated.assigned_to:
                _notify_assignee(task, updated.assigned_to, staff)

    def perform_destroy(self, instance):
        staff = _get_staff(self.request)
        _log_audit(instance, 'status_changed', staff,
                   field_name='status', old_value=instance.status, new_value='cancelled')
        instance.status = 'cancelled'
        instance.save(update_fields=['status'])


# ── Complete Task ──────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def task_complete(request, pk):
    try:
        task = OperationalTask.objects.get(pk=pk)
    except OperationalTask.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if task.status == 'completed':
        return Response({'detail': 'المهمة مكتملة بالفعل.'}, status=400)
    if task.status == 'cancelled':
        return Response({'detail': 'لا يمكن إكمال مهمة ملغاة.'}, status=400)

    staff = _get_staff(request)
    notes = request.data.get('notes', '')
    actual_hours = request.data.get('actual_hours')

    task.status = 'completed'
    task.completed_at = timezone.now()
    task.completed_by = staff
    if notes:
        task.completion_notes = notes
    if actual_hours:
        task.actual_hours = actual_hours
    task.save(update_fields=['status', 'completed_at', 'completed_by',
                             'completion_notes', 'actual_hours'])

    _log_audit(task, 'completed', staff)
    _add_system_message(task, f'تم إغلاق المهمة بواسطة {staff.full_name if staff else "النظام"}')
    _notify_watchers(task, f'تم اكتمال المهمة: {task.title}', staff)

    return Response(TaskDetailSerializer(task, context={'request': request}).data)


# ── Reopen Task ────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def task_reopen(request, pk):
    try:
        task = OperationalTask.objects.get(pk=pk)
    except OperationalTask.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if task.status not in ('completed', 'cancelled'):
        return Response({'detail': 'يمكن إعادة فتح المهام المكتملة أو الملغاة فقط.'}, status=400)

    staff = _get_staff(request)
    old_status = task.status
    task.status = 'open'
    task.completed_at = None
    task.completed_by = None
    task.save(update_fields=['status', 'completed_at', 'completed_by'])

    _log_audit(task, 'status_changed', staff,
               field_name='status', old_value=old_status, new_value='open')
    _add_system_message(task, f'تمت إعادة فتح المهمة بواسطة {staff.full_name if staff else "النظام"}')

    return Response({'detail': 'تمت إعادة الفتح.'})


# ── Assignments ────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def task_assignments(request, pk):
    try:
        task = OperationalTask.objects.get(pk=pk)
    except OperationalTask.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        ser = TaskAssignmentSerializer(task.assignments.select_related('staff'), many=True)
        return Response(ser.data)

    # POST — add assignment
    staff_id = request.data.get('staff')
    role = request.data.get('role', 'contributor')
    if not staff_id:
        return Response({'detail': 'staff مطلوب.'}, status=400)

    from apps.users.models import StaffProfile
    try:
        assignee = StaffProfile.objects.get(pk=staff_id)
    except StaffProfile.DoesNotExist:
        return Response({'detail': 'موظف غير موجود.'}, status=404)

    actor = _get_staff(request)
    assignment, created = TaskAssignment.objects.get_or_create(
        task=task, staff=assignee,
        defaults={'role': role, 'assigned_by': actor},
    )
    if not created:
        assignment.role = role
        assignment.save(update_fields=['role'])

    _log_audit(task, 'assigned', actor, new_value=assignee.full_name)
    _notify_assignee(task, assignee, actor)

    return Response(TaskAssignmentSerializer(assignment).data,
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def task_assignment_remove(request, pk, assignment_pk):
    try:
        assignment = TaskAssignment.objects.get(pk=assignment_pk, task_id=pk)
    except TaskAssignment.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    actor = _get_staff(request)
    staff_name = assignment.staff.full_name
    assignment.delete()
    _log_audit(
        OperationalTask.objects.get(pk=pk),
        'unassigned', actor, new_value=staff_name
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Items / Checklist ──────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def task_items(request, pk):
    try:
        task = OperationalTask.objects.get(pk=pk)
    except OperationalTask.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        return Response(TaskItemSerializer(task.items.all(), many=True).data)

    ser = TaskItemSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    item = ser.save(task=task)
    return Response(TaskItemSerializer(item).data, status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def task_item_detail(request, pk, item_pk):
    try:
        item = TaskItem.objects.get(pk=item_pk, task_id=pk)
    except TaskItem.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'DELETE':
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    ser = TaskItemSerializer(item, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)

    # Auto-set checked timestamp
    if request.data.get('is_checked') and not item.is_checked:
        item.checked_at = timezone.now()
        item.checked_by = _get_staff(request)
    elif 'is_checked' in request.data and not request.data['is_checked']:
        item.checked_at = None
        item.checked_by = None

    ser.save(checked_at=item.checked_at)
    return Response(TaskItemSerializer(item).data)


# ── Messages / Chatter ────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def task_messages(request, pk):
    try:
        task = OperationalTask.objects.get(pk=pk)
    except OperationalTask.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        msgs = task.messages.filter(is_deleted=False).select_related('author').order_by('created_at')
        return Response(TaskMessageSerializer(msgs, many=True).data)

    body = request.data.get('body', '').strip()
    if not body:
        return Response({'detail': 'النص مطلوب.'}, status=400)

    staff = _get_staff(request)
    msg = TaskMessage.objects.create(
        task=task,
        author=staff,
        message_type='comment',
        body=body,
    )
    _log_audit(task, 'comment_added', staff)
    _notify_watchers(
        task,
        f'{staff.full_name if staff else "مجهول"}: {body[:100]}',
        staff
    )
    return Response(TaskMessageSerializer(msg).data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def task_message_delete(request, pk, message_pk):
    try:
        msg = TaskMessage.objects.get(pk=message_pk, task_id=pk, message_type='comment')
    except TaskMessage.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    staff = _get_staff(request)
    # Only allow deletion by author or admin
    is_admin = request.user.is_staff or (staff and staff.role == 'admin')
    if staff and msg.author and msg.author != staff and not is_admin:
        return Response({'detail': 'لا يمكنك حذف تعليق شخص آخر.'}, status=403)

    msg.is_deleted = True
    msg.deleted_at = timezone.now()
    msg.save(update_fields=['is_deleted', 'deleted_at'])
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Attachments ────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def task_attachments(request, pk):
    try:
        task = OperationalTask.objects.get(pk=pk)
    except OperationalTask.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    if request.method == 'GET':
        return Response(
            TaskAttachmentSerializer(
                task.attachments.all(), many=True, context={'request': request}
            ).data
        )

    file_obj = request.FILES.get('file')
    if not file_obj:
        return Response({'detail': 'file مطلوب.'}, status=400)

    ext = os.path.splitext(file_obj.name)[1].lower()
    file_type = 'image' if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp') \
        else 'pdf' if ext == '.pdf' \
        else 'excel' if ext in ('.xls', '.xlsx', '.csv') \
        else 'other'

    staff = _get_staff(request)
    att = TaskAttachment.objects.create(
        task=task,
        uploaded_by=staff,
        file=file_obj,
        file_name=file_obj.name,
        file_type=file_type,
        file_size=file_obj.size,
    )
    _log_audit(task, 'attachment_added', staff, new_value=file_obj.name)
    return Response(
        TaskAttachmentSerializer(att, context={'request': request}).data,
        status=status.HTTP_201_CREATED
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def task_attachment_delete(request, pk, att_pk):
    try:
        att = TaskAttachment.objects.get(pk=att_pk, task_id=pk)
    except TaskAttachment.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    try:
        if att.file:
            att.file.delete(save=False)
    except Exception:
        pass
    att.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── My Tasks ──────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_tasks(request):
    staff = _get_staff(request)
    if not staff:
        return Response([])

    # Shared selector — same queryset the personal-dashboard "my_tasks" widget
    # uses (apps.tasks.selectors.tasks_for_staff), so the two never drift.
    from .selectors import tasks_for_staff
    qs = tasks_for_staff(staff)

    return Response(TaskListSerializer(qs, many=True).data)


# ── Dashboard / Stats ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def task_dashboard(request):
    p = request.query_params
    branch = p.get('branch')
    date_from = p.get('date_from')
    date_to = p.get('date_to')

    qs = OperationalTask.objects.all()
    if branch:
        qs = qs.filter(branch_id=branch)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    now = timezone.now()

    # Status counts
    status_counts = {}
    for s, _ in STATUS_CHOICES:
        status_counts[s] = qs.filter(status=s).count()

    # Priority counts (open tasks only)
    priority_counts = {}
    open_qs = qs.exclude(status__in=['completed', 'cancelled'])
    for pr, _ in PRIORITY_CHOICES:
        priority_counts[pr] = open_qs.filter(priority=pr).count()

    # Overdue
    overdue_count = open_qs.filter(due_date__lt=now).count()

    # By type
    type_counts = []
    for tt, label in TASK_TYPE_CHOICES:
        cnt = qs.filter(task_type=tt).count()
        if cnt:
            type_counts.append({'type': tt, 'label': label, 'count': cnt})

    # Completion rate (last 30 days)
    from datetime import timedelta
    cutoff = now - timedelta(days=30)
    recent = qs.filter(created_at__gte=cutoff)
    total_recent = recent.count()
    completed_recent = recent.filter(status='completed').count()
    completion_rate = round(completed_recent / total_recent * 100, 1) if total_recent else 0

    # Recent activity (last 10)
    recent_tasks = qs.order_by('-updated_at')[:10]
    recent_data = TaskListSerializer(recent_tasks, many=True).data

    # Upcoming due (next 7 days, not completed)
    due_soon = open_qs.filter(
        due_date__gte=now,
        due_date__lte=now + timedelta(days=7),
    ).order_by('due_date')[:10]
    due_soon_data = TaskListSerializer(due_soon, many=True).data

    # By branch
    from django.db.models import Count as DjCount
    by_branch = list(
        qs.exclude(branch__isnull=True)
        .values('branch__name')
        .annotate(total=DjCount('id'), open=DjCount('id', filter=Q(status='open')))
        .order_by('-total')[:10]
    )

    return Response({
        'status_counts': status_counts,
        'priority_counts': priority_counts,
        'overdue_count': overdue_count,
        'type_counts': type_counts,
        'completion_rate': completion_rate,
        'total_tasks': qs.count(),
        'recent_tasks': recent_data,
        'due_soon': due_soon_data,
        'by_branch': by_branch,
    })


# ── Audit Log ─────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def task_audit_logs(request, pk):
    try:
        task = OperationalTask.objects.get(pk=pk)
    except OperationalTask.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    logs = task.audit_logs.select_related('actor').order_by('-created_at')
    return Response(TaskAuditLogSerializer(logs, many=True).data)


# ── TaskSchedule ───────────────────────────────────────────────────────────────

class TaskScheduleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TaskScheduleSerializer

    def get_queryset(self):
        qs = TaskSchedule.objects.select_related('branch', 'assign_to')
        if branch := self.request.query_params.get('branch'):
            qs = qs.filter(Q(branch_id=branch) | Q(branch__isnull=True))
        if active := self.request.query_params.get('active'):
            qs = qs.filter(is_active=active == '1')
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=_get_staff(self.request))


class TaskScheduleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TaskScheduleSerializer
    queryset = TaskSchedule.objects.select_related('branch', 'assign_to')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def schedule_run_now(request, pk):
    """Manually trigger a schedule to generate its task immediately."""
    try:
        schedule = TaskSchedule.objects.get(pk=pk)
    except TaskSchedule.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)

    staff = _get_staff(request)
    from .scheduler import generate_task_from_schedule
    task = generate_task_from_schedule(schedule, created_by=staff)
    if task:
        return Response({'detail': 'تم إنشاء المهمة.', 'task_id': task.pk,
                        'task_number': task.task_number})
    return Response({'detail': 'تعذر إنشاء المهمة من هذا الجدول.'}, status=400)


# ── Filter options ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def task_filter_options(request):
    return Response({
        'statuses': [{'value': k, 'label': v} for k, v in STATUS_CHOICES],
        'priorities': [{'value': k, 'label': v} for k, v in PRIORITY_CHOICES],
        'task_types': [{'value': k, 'label': v} for k, v in TASK_TYPE_CHOICES],
        'categories': [{'value': k, 'label': v} for k, v in CATEGORY_CHOICES],
    })
