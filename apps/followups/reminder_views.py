"""
apps/followups/reminder_views.py — review screen API for WhatsApp refill reminders (B1).

  GET  /api/followups/refill-reminders/          summary (30 d) + latest reminders
  GET  /api/followups/refill-reminders/preview/  who the next run would message, and why others are skipped
  POST /api/followups/refill-reminders/run/      run now (admin / supervisor) — gated by
                                                 REFILL_REMINDER_SEND_ENABLED; off ⇒ counts only, nothing sent
Phones are masked; permissions enforced here (follow-ups view; run = admin / supervisor).
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from . import refill_reminders as RR

RUN_ROLES = ('admin', 'supervisor')


def _profile(request):
    p = getattr(request.user, 'staff_profile', None)
    return p if (p and p.is_active) else None


class CanViewReminders(BasePermission):
    def has_permission(self, request, view):
        p = _profile(request)
        if not p:
            return False
        if p.role in ('admin', 'supervisor', 'call_center', 'quality_manager'):
            return True
        try:
            return p.can_do('followups', 'view')
        except Exception:
            return False


@api_view(['GET'])
@permission_classes([CanViewReminders])
def overview(request):
    from .models import RefillReminder
    rows = (RefillReminder.objects.select_related('customer', 'branch', 'task__item')
            .order_by('-created_at')[:200])
    p = _profile(request)
    return Response({
        **RR.summary(),
        'send_enabled': RR.send_enabled(),
        'can_run': p.role in RUN_ROLES,
        'rows': [{'id': r.pk, 'task_id': r.task_id, 'customer': r.customer.name, 'phone': RR.mask(r.phone),
                  'branch': (r.branch.name_ar or r.branch.name) if r.branch_id else '',
                  'item': r.task.item.name if r.task.item_id else '', 'due_date': r.due_date.isoformat(),
                  'status': r.status, 'status_label': r.get_status_display(), 'error': r.error[:200],
                  'reply_choice': r.reply_choice, 'reply_label': r.get_reply_choice_display() if r.reply_choice else '',
                  'reservation_id': r.reservation_id,
                  'sent_at': r.sent_at.isoformat() if r.sent_at else None,
                  'replied_at': r.replied_at.isoformat() if r.replied_at else None} for r in rows],
    })


@api_view(['GET'])
@permission_classes([CanViewReminders])
def preview(request):
    return Response(RR.preview())


@api_view(['POST'])
@permission_classes([CanViewReminders])
def run_now(request):
    p = _profile(request)
    if p.role not in RUN_ROLES:
        return Response({'detail': 'التشغيل للمدير أو المشرف فقط'}, status=status.HTTP_403_FORBIDDEN)
    return Response(RR.run())
