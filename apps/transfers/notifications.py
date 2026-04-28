"""
apps/transfers/notifications.py

Notification helpers for transfer request events.
All functions are wrapped in try/except — a notification failure
must NEVER crash the transfer itself.
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
    StaffProfile = apps.get_model('users', 'StaffProfile')
    return StaffProfile.objects.filter(
        branch=branch,
        is_active=True,
        role__in=('admin', 'pharmacist', 'salesperson', 'call_center'),
    )


def _purchasing_staff():
    StaffProfile = apps.get_model('users', 'StaffProfile')
    return StaffProfile.objects.filter(
        is_active=True,
        role__in=('admin', 'purchasing'),
    )


def _safe_create(Notification, recipient, title, body, notification_type, transfer):
    """Create a single notification, catching any field mismatch errors."""
    try:
        kwargs = {
            'recipient': recipient,
            'title': title,
            'is_read': False,
        }
        # Add optional fields only if the column exists on the model
        for field_name, value in [
            ('body', body or ''),
            ('notification_type', notification_type),
            ('transfer_request_id_ref', transfer.id),
        ]:
            if hasattr(Notification, field_name):
                try:
                    Notification._meta.get_field(field_name)
                    kwargs[field_name] = value
                except Exception:
                    pass
        Notification.objects.create(**kwargs)
    except Exception as e:
        logger.warning(f'Notification create failed (non-fatal): {e}')


def notify_source_branch_new_request(transfer):
    """Step 3: Notify ALL users at the source branch when a transfer is created."""
    try:
        Notification = _get_notification_model()
        if not Notification:
            return

        title = f'طلب تحويل جديد — {transfer.item.name}'
        body = (
            f'فرع {transfer.requesting_branch.name_ar or transfer.requesting_branch.name} '
            f'يطلب {transfer.quantity_needed} وحدة من الصنف: {transfer.item.name}. '
            f'يرجى مراجعة الطلب والرد.'
        )

        recipients = _branch_staff(transfer.source_branch)
        for staff in recipients:
            _safe_create(
                Notification, staff, title, body,
                'transfer_request', transfer
            )

        logger.info(
            f'Transfer #{transfer.id}: notified source branch {transfer.source_branch}'
        )
    except Exception as e:
        logger.warning(f'notify_source_branch_new_request failed (non-fatal): {e}')


def notify_requesting_branch_response(transfer):
    """Step 5: Notify the requesting branch when source branch responds."""
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
            f'رد على طلبك للصنف {transfer.item.name}: {status_text}.'
        )
        if transfer.status == 'partial' and transfer.quantity_approved:
            body += f' الكمية المعتمدة: {transfer.quantity_approved} وحدة.'
        if transfer.rejection_reason_text:
            body += f' السبب: {transfer.rejection_reason_text}'

        recipients = _branch_staff(transfer.requesting_branch)
        for staff in recipients:
            _safe_create(
                Notification, staff, title, body,
                'transfer_response', transfer
            )
    except Exception as e:
        logger.warning(f'notify_requesting_branch_response failed (non-fatal): {e}')


def notify_purchasing_rejection(transfer):
    """Step 5b: Notify purchasing dept when a transfer is rejected."""
    try:
        Notification = _get_notification_model()
        if not Notification:
            return

        title = 'طلب تحويل مرفوض — يحتاج مراجعة المشتريات'
        body = (
            f'فرع {transfer.requesting_branch.name_ar} طلب {transfer.quantity_needed} '
            f'وحدة من {transfer.item.name} من فرع '
            f'{transfer.source_branch.name_ar} وتم رفضه. '
            f'السبب: {transfer.get_rejection_reason_display() or "غير محدد"}. '
            f'يرجى مراجعة إمكانية الطلب من المستودع الرئيسي.'
        )

        recipients = _purchasing_staff()
        for staff in recipients:
            _safe_create(
                Notification, staff, title, body,
                'transfer_request', transfer
            )
    except Exception as e:
        logger.warning(f'notify_purchasing_rejection failed (non-fatal): {e}')


def notify_unfulfilled_flag(transfer):
    """Policy enforcement: notify purchasing when transfer has no sale after 14 days."""
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
            f'وحدة من الصنف {transfer.item.name} منذ {days} يوماً '
            f'ولم يُسجَّل أي مبيعات. يرجى المتابعة.'
        )

        recipients = _purchasing_staff()
        for staff in recipients:
            _safe_create(
                Notification, staff, title, body,
                'unfulfilled_transfer_flag', transfer
            )

        transfer.flagged_no_sale = True
        transfer.save(update_fields=['flagged_no_sale'])
    except Exception as e:
        logger.warning(f'notify_unfulfilled_flag failed (non-fatal): {e}')
