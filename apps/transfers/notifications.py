"""
apps/transfers/notifications.py

Notification helpers for transfer request events.
All functions are wrapped in try/except — a notification failure
must NEVER crash the transfer itself.

Uses Notification.send_to_user() throughout so that:
  - NotificationLog row is created (audit trail)
  - push_realtime() fires → WebSocket delivery + REST polling fallback
  - dedup_key prevents duplicate unread alerts within 5 minutes
  - branch notification gate (BranchSettings.notifications_enabled) is honoured
"""
import logging
from django.apps import apps

logger = logging.getLogger('elrezeiky.transfers')


def _get_notification_model():
    try:
        return apps.get_model('notifications', 'Notification')
    except LookupError:
        return None


def _branch_staff(branch):
    """Active staff at a specific branch."""
    StaffProfile = apps.get_model('users', 'StaffProfile')
    return StaffProfile.objects.filter(
        branch=branch,
        is_active=True,
        role__in=('pharmacist', 'salesperson', 'call_center'),
    )


def _global_staff(roles):
    """Active staff with global access (no branch restriction)."""
    StaffProfile = apps.get_model('users', 'StaffProfile')
    return StaffProfile.objects.filter(
        is_active=True,
        role__in=roles,
    )


def notify_source_branch_new_request(transfer):
    """Notify ALL users at the source branch + admins when a transfer is requested."""
    try:
        Notification = _get_notification_model()
        if not Notification:
            return

        title = f'طلب تحويل جديد — {transfer.item.name}'
        body = (
            f'فرع {transfer.requesting_branch.name_ar or transfer.requesting_branch.name} '
            f'يطلب {transfer.quantity_needed} وحدة. يرجى مراجعة الطلب والرد.'
        )
        dedup = f'tr_new_{transfer.id}'

        # Branch staff at the source branch
        for staff in _branch_staff(transfer.source_branch):
            Notification.send_to_user(
                staff=staff,
                notification_type='transfer_request',
                title=title,
                body=body,
                transfer_id=transfer.id,
                dedup_key=f'{dedup}_{staff.pk}',
            )

        # Admins + purchasing (always in the loop)
        for staff in _global_staff(['admin', 'purchasing']):
            if staff.branch == transfer.source_branch:
                continue  # already covered above
            Notification.send_to_user(
                staff=staff,
                notification_type='transfer_request',
                title=title,
                body=body,
                transfer_id=transfer.id,
                dedup_key=f'{dedup}_adm_{staff.pk}',
            )

        logger.info(f'Transfer #{transfer.id}: notified source branch {transfer.source_branch}')
    except Exception as e:
        logger.warning(f'notify_source_branch_new_request failed (non-fatal): {e}')


def notify_requesting_branch_response(transfer):
    """Notify the requesting branch + admins when source branch responds."""
    try:
        Notification = _get_notification_model()
        if not Notification:
            return

        status_labels = {
            'accepted': 'تم القبول الكامل ✅',
            'partial':  'تم القبول الجزئي ⚠️',
            'rejected': 'تم الرفض ❌',
        }
        status_text = status_labels.get(transfer.status, transfer.get_status_display())

        title = f'رد على طلب التحويل — {transfer.item.name}'
        body = (
            f'فرع {transfer.source_branch.name_ar or transfer.source_branch.name} '
            f'رد على طلبك: {status_text}.'
        )
        if transfer.status == 'partial' and transfer.quantity_approved:
            body += f' الكمية المعتمدة: {transfer.quantity_approved} وحدة.'
        if getattr(transfer, 'rejection_reason_text', None):
            body += f' السبب: {transfer.rejection_reason_text}'

        dedup = f'tr_resp_{transfer.id}'

        for staff in _branch_staff(transfer.requesting_branch):
            Notification.send_to_user(
                staff=staff,
                notification_type='transfer_response',
                title=title,
                body=body,
                transfer_id=transfer.id,
                dedup_key=f'{dedup}_{staff.pk}',
            )

        # Admins
        for staff in _global_staff(['admin']):
            if staff.branch == transfer.requesting_branch:
                continue
            Notification.send_to_user(
                staff=staff,
                notification_type='transfer_response',
                title=title,
                body=body,
                transfer_id=transfer.id,
                dedup_key=f'{dedup}_adm_{staff.pk}',
            )
    except Exception as e:
        logger.warning(f'notify_requesting_branch_response failed (non-fatal): {e}')


def notify_purchasing_rejection(transfer):
    """Notify purchasing dept + admins when a transfer is rejected."""
    try:
        Notification = _get_notification_model()
        if not Notification:
            return

        title = 'طلب تحويل مرفوض — يحتاج مراجعة المشتريات'
        body = (
            f'فرع {transfer.requesting_branch.name_ar} طلب {transfer.quantity_needed} '
            f'وحدة من {transfer.item.name} وتم رفضه. '
            f'السبب: {getattr(transfer, "rejection_reason_text", "") or "غير محدد"}.'
        )
        dedup = f'tr_rej_{transfer.id}'

        for staff in _global_staff(['admin', 'purchasing']):
            Notification.send_to_user(
                staff=staff,
                notification_type='transfer_request',
                title=title,
                body=body,
                transfer_id=transfer.id,
                dedup_key=f'{dedup}_{staff.pk}',
            )
    except Exception as e:
        logger.warning(f'notify_purchasing_rejection failed (non-fatal): {e}')


def notify_unfulfilled_flag(transfer):
    """Notify purchasing + admins when transferred stock has no sale after 14 days."""
    try:
        Notification = _get_notification_model()
        if not Notification:
            return

        from django.utils import timezone
        days = (timezone.now() - transfer.responded_at).days if transfer.responded_at else '?'

        title = f'تحذير: مخزون محوَّل غير مُصرَّف — {transfer.item.name}'
        body = (
            f'فرع {transfer.requesting_branch.name_ar} طلب '
            f'{transfer.quantity_approved or transfer.quantity_needed} '
            f'وحدة من {transfer.item.name} منذ {days} يوماً ولم يُسجَّل أي مبيعات.'
        )
        dedup = f'tr_flag_{transfer.id}'

        for staff in _global_staff(['admin', 'purchasing']):
            Notification.send_to_user(
                staff=staff,
                notification_type='unfulfilled_transfer_flag',
                title=title,
                body=body,
                transfer_id=transfer.id,
                dedup_key=f'{dedup}_{staff.pk}',
            )

        transfer.flagged_no_sale = True
        transfer.save(update_fields=['flagged_no_sale'])
    except Exception as e:
        logger.warning(f'notify_unfulfilled_flag failed (non-fatal): {e}')
