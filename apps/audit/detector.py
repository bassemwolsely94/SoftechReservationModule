"""
apps/audit/detector.py

Anti-abuse detection engine.
Runs periodically (daily via management command or scheduler).
Analyses AuditLog patterns and creates AbuseFlag records.

Thresholds are conservative by default — the goal is to surface
patterns for human review, not to block users automatically.
"""
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q

from .models import AuditLog, AbuseFlag

logger = logging.getLogger('elrezeiky.audit')


# ── Thresholds (adjust per pharmacy policy) ───────────────────────────────────

THRESHOLDS = {
    'frequent_cancellations': {
        'action':     'reservation_cancelled',
        'count':      5,
        'window_h':   24,
        'severity':   'warning',
        'description': '{name} ألغى {count} حجوزات خلال {h} ساعة',
    },
    'frequent_status_changes': {
        'action':     'reservation_status_changed',
        'count':      20,
        'window_h':   4,
        'severity':   'info',
        'description': '{name} غيّر حالة {count} حجوزات خلال {h} ساعة',
    },
    'frequent_edits': {
        'action':     'reservation_updated',
        'count':      15,
        'window_h':   2,
        'severity':   'warning',
        'description': '{name} عدّل {count} حجوزات خلال {h} ساعة',
    },
    'frequent_transfer_rejections': {
        'action':     'transfer_rejected',
        'count':      10,
        'window_h':   24,
        'severity':   'info',
        'description': '{name} رفض {count} طلبات تحويل خلال {h} ساعة',
    },
    'bulk_deletions': {
        'action':     'demand_status_changed',
        'count':      10,
        'window_h':   1,
        'severity':   'critical',
        'description': '{name} غيّر حالة {count} طلبات خلال {h} ساعة',
    },
}


def run_abuse_detection(window_hours=24):
    """
    Main entry point. Run all detectors and create AbuseFlag records.
    Returns total flags created.
    """
    total = 0
    total += _detect_pattern_flags(window_hours)
    total += _detect_after_hours(window_hours)
    logger.info(f'Anti-abuse scan complete: {total} new flags')
    return total


def _detect_pattern_flags(window_hours):
    """Detect count-based patterns from AuditLog."""
    created = 0
    cutoff  = timezone.now() - timedelta(hours=window_hours)

    for flag_type, cfg in THRESHOLDS.items():
        # Find users who exceeded the threshold in the window
        offenders = (
            AuditLog.objects
            .filter(action=cfg['action'], created_at__gte=cutoff)
            .exclude(user__isnull=True)
            .values('user', 'user_name', 'user_role')
            .annotate(count=Count('id'))
            .filter(count__gte=cfg['count'])
        )

        for row in offenders:
            count    = row['count']
            staff_id = row['user']
            name     = row['user_name'] or f'User#{staff_id}'
            h        = cfg['window_h']

            # Skip if already flagged recently for the same reason
            recent = AbuseFlag.objects.filter(
                staff_id=staff_id,
                flag_type=flag_type,
                detected_at__gte=cutoff,
                status__in=('open', 'reviewed'),
            ).exists()
            if recent:
                continue

            description = cfg['description'].format(
                name=name, count=count, h=h
            )

            # Gather evidence log IDs
            log_ids = list(
                AuditLog.objects
                .filter(action=cfg['action'], created_at__gte=cutoff, user_id=staff_id)
                .values_list('id', flat=True)[:50]
            )

            try:
                from apps.users.models import StaffProfile
                staff = StaffProfile.objects.get(pk=staff_id)
            except Exception:
                continue

            AbuseFlag.objects.create(
                staff=staff,
                flag_type=flag_type,
                severity=cfg['severity'],
                description=description,
                count=count,
                window_hours=h,
                evidence={'audit_log_ids': log_ids},
            )
            created += 1

            # Notify admins
            _notify_admins(
                title=f'⚠️ نشاط مشبوه — {name}',
                body=description,
            )

            logger.warning(
                f'AbuseFlag created: {flag_type} | {name} | count={count}'
            )

    return created


def _detect_after_hours(window_hours=24):
    """
    Detect activity outside business hours (before 8am or after 10pm Cairo time).
    Only flags if count exceeds threshold.
    """
    created = 0
    AFTER_HOURS_THRESHOLD = 20
    cutoff  = timezone.now() - timedelta(hours=window_hours)

    try:
        import pytz
        cairo = pytz.timezone('Africa/Cairo')

        # Get all logs in window
        logs = AuditLog.objects.filter(
            created_at__gte=cutoff
        ).exclude(user__isnull=True).values('user', 'user_name', 'created_at')

        # Group by user and count after-hours entries
        from collections import defaultdict
        user_after_hours = defaultdict(list)

        for log in logs:
            dt_cairo = log['created_at'].astimezone(cairo)
            hour = dt_cairo.hour
            if hour < 8 or hour >= 22:  # before 8am or after 10pm
                user_after_hours[log['user']].append(log['user_name'])

        for user_id, name_list in user_after_hours.items():
            if len(name_list) < AFTER_HOURS_THRESHOLD:
                continue

            name = name_list[0] or f'User#{user_id}'

            recent = AbuseFlag.objects.filter(
                staff_id=user_id,
                flag_type='after_hours_activity',
                detected_at__gte=cutoff,
            ).exists()
            if recent:
                continue

            try:
                from apps.users.models import StaffProfile
                staff = StaffProfile.objects.get(pk=user_id)
            except Exception:
                continue

            AbuseFlag.objects.create(
                staff=staff,
                flag_type='after_hours_activity',
                severity='info',
                description=f'{name} نفّذ {len(name_list)} إجراء خارج أوقات العمل خلال {window_hours} ساعة',
                count=len(name_list),
                window_hours=window_hours,
            )
            created += 1

    except Exception as e:
        logger.warning(f'After-hours detection failed (non-fatal): {e}')

    return created


def _notify_admins(title, body):
    """Send in-app notification to all admins (non-fatal)."""
    try:
        from apps.notifications.models import Notification
        Notification.send_to_admins(
            notification_type='system',
            title=title,
            body=body,
        )
    except Exception:
        pass


# ── ERP mismatch detection ────────────────────────────────────────────────────

def detect_erp_mismatches(days=7):
    """
    Find fulfilled reservations where ERP validation found no matching sale.
    These are potential inventory leaks or recording errors.
    """
    try:
        from apps.reservations.models import Reservation
        from django.utils import timezone as tz
        cutoff = tz.now() - timedelta(days=days)

        # Fulfilled reservations not ERP-validated
        unvalidated = Reservation.objects.filter(
            status='fulfilled',
            is_erp_validated=False,
            updated_at__gte=cutoff,
        ).select_related('created_by', 'customer', 'item', 'branch')

        for r in unvalidated:
            if not r.created_by:
                continue

            existing = AbuseFlag.objects.filter(
                staff=r.created_by,
                flag_type='erp_mismatch',
                description__icontains=str(r.id),
            ).exists()
            if existing:
                continue

            AbuseFlag.objects.create(
                staff=r.created_by,
                flag_type='erp_mismatch',
                severity='warning',
                description=(
                    f'حجز #{r.id} ({r.item.name} لـ {r.customer.name}) '
                    f'مُسلَّم ولم يُعثر على بيع مطابق في الـ ERP'
                ),
                count=1,
                evidence={'reservation_id': r.id},
            )

            AuditLog.log(
                'reservation_erp_validated',
                user=r.created_by,
                obj=r,
                note='ERP validation mismatch — sale not found',
            )

        count = unvalidated.count()
        if count:
            logger.info(f'ERP mismatch detection: {count} unvalidated fulfilled reservations')
        return count
    except Exception as e:
        logger.warning(f'ERP mismatch detection failed (non-fatal): {e}')
        return 0
