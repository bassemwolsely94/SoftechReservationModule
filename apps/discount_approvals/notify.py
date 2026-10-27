"""Notification helpers for the pricing-approvals module.

Reuses apps.notifications (WebSocket + persistence + dedup). Never raises —
a notification failure must not break the approval transaction.
"""
import logging

logger = logging.getLogger('elrezeiky.discount_approvals')


def _fields_summary(req):
    from .models import FIELD_LABELS
    return '، '.join(f'{FIELD_LABELS.get(k, k)}: {v}' for k, v in req.new_values.items())


def notify_admins_new_request(req):
    """Notify all admins that a new pricing request is pending review."""
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
        admins = StaffProfile.objects.filter(role='admin', is_active=True)
        title = '🏷️ طلب تعديل سعر جديد'
        body = f'{req.item.name} — {_fields_summary(req)} (بواسطة {req.requested_by.get_full_name() or req.requested_by.username})'
        for sp in admins:
            Notification.send_to_user(
                sp, 'system', title, body,
                dedup_key=f'pricing_req_new_{req.id}',
            )
    except Exception as exc:
        logger.debug(f'notify_admins_new_request skipped: {exc}')


def notify_requester_decision(req, decision):
    """Notify the requester their request was approved/executed or rejected."""
    try:
        from apps.notifications.models import Notification
        sp = getattr(req.requested_by, 'staff_profile', None)
        if not sp:
            return
        if decision == 'executed':
            title = '✅ تم اعتماد طلب التعديل'
            body  = f'{req.item.name} — {_fields_summary(req)} — نُفّذ في Softech وسيُنشر للفروع.'
        elif decision == 'rejected':
            title = '❌ تم رفض طلب التعديل'
            body  = f'{req.item.name} — {_fields_summary(req)}' + (f' — {req.review_notes}' if req.review_notes else '')
        else:
            title = 'ℹ️ تحديث طلب التعديل'
            body  = f'{req.item.name} — {req.get_status_display()}'
        Notification.send_to_user(sp, 'system', title, body, dedup_key=f'pricing_req_dec_{req.id}_{decision}')
    except Exception as exc:
        logger.debug(f'notify_requester_decision skipped: {exc}')


def notify_admins_replication_gaps(scan):
    """Notify admins when a replication scan finds gaps."""
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile
        if not scan.items_with_gaps:
            return
        admins = StaffProfile.objects.filter(role='admin', is_active=True)
        title = '⚠️ فجوات في النسخ المتماثل'
        down = f' — فروع متوقفة: {", ".join(scan.branches_down)}' if scan.branches_down else ''
        body = f'{scan.items_with_gaps} صنف لم يصل لبعض الفروع خلال آخر {scan.days_window} يوم{down}'
        for sp in admins:
            Notification.send_to_user(sp, 'system', title, body, dedup_key=f'repl_scan_{scan.id}')
    except Exception as exc:
        logger.debug(f'notify_admins_replication_gaps skipped: {exc}')
