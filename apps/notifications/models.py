"""
apps/notifications/models.py

Notification     — one row per (event × recipient); always HIGH priority.
NotificationLog  — full delivery + read audit trail.
ChatterMessage   — threaded comment on any platform record (@mention support).

Real-time:  Django Channels WebSocket group  notifications_user_{profile_id}
Dedup:      dedup_key suppresses identical unread alerts within 5 minutes
Anti-noise: BranchSettings.notifications_enabled gates branch-wide sends
Persistence: notifications persist until the user explicitly clears them;
             offline users receive all notifications on next login.
"""
import json
import logging
import re

from django.conf import settings
from django.db import models
from django.utils import timezone

logger = logging.getLogger('elrezeiky.notifications')

PRIORITY_HIGH    = 'high'
PRIORITY_CHOICES = [('high', 'عاجل')]


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        # ── Reservation ───────────────────────────────────────────────────────
        ('stock_available',           '📦 مخزون متاح'),
        ('reservation_assigned',      '👤 حجز مُعيَّن'),
        ('reservation_created',       '➕ حجز جديد'),
        ('reservation_status',        '🔄 تغيير حالة حجز'),
        ('call_logged',               '📞 تحديث نشاط حجز'),
        ('follow_up_due',             '📅 متابعة مستحقة اليوم'),
        ('followup',                  '💊 متابعة صرف مزمن'),
        ('churn_alert',               '⚠️ تنبيه انقطاع عميل'),
        ('weekly_summary',            '📊 ملخص أسبوعي'),
        ('monthly_report',            '📈 تقرير شهري'),
        # ── Transfer ─────────────────────────────────────────────────────────
        ('transfer_request',          '🔀 طلب تحويل جديد'),
        ('transfer_response',         '↩️ رد على طلب تحويل'),
        ('unfulfilled_transfer_flag', '⚠️ تحويل غير مُصرَّف'),
        # ── Transit (In Transit monitoring) ──────────────────────────────────
        ('transit_issued',            '🚛 تحويل صادر'),
        ('transit_approaching_cancel','⏳ مهلة إلغاء قاربت'),
        ('transit_overdue',           '🟠 تحويل متأخر'),
        ('transit_critical',          '🚨 تحويل حرج'),
        ('transit_received',          '✅ تحويل مستلم'),
        ('transit_cancelled',         '↩️ تحويل ملغي'),
        # ── Demand / Lost Sales ───────────────────────────────────────────────
        ('demand_created',            '🆕 طلب جديد'),
        ('demand_assigned',           '👤 طلب مُعيَّن'),
        ('demand_status',             '🔄 تغيير حالة طلب'),
        ('demand_follow_up',          '📅 متابعة طلب'),
        ('demand_back_in_stock',      '🔔 صنف مطلوب عاد للمخزون'),
        ('demand_sla_breach',         '⏰ تجاوز SLA طلب'),
        # ── Chatter ───────────────────────────────────────────────────────────
        ('chatter_mention',           '💬 ذِكر في تعليق'),
        ('mention',                   '@ ذِكر'),
        # ── Delivery ──────────────────────────────────────────────────────────
        ('delivery_new',              '🚚 طلب توصيل جديد'),
        ('delivery_status',           '📦 تغيير حالة توصيل'),
        ('delivery_sla_alert',        '⏰ تجاوز SLA توصيل'),
        ('delivery_cash_variance',    '💰 عجز نقدي توصيل'),
        ('delivery_csat',             '⭐ تقييم عميل'),
        # ── System ────────────────────────────────────────────────────────────
        ('system',                    '⚙️ نظام'),
        ('branch_connectivity',       '🔌 اتصال فرع'),
        # ── Personal ──────────────────────────────────────────────────────────
        ('personal_reminder',         '⏰ تذكير شخصي'),
        # ── Internal broadcast ────────────────────────────────────────────────
        ('announcement',              '📢 إعلان داخلي'),
    ]

    # ── Notification category (priority-tier routing) ─────────────────────────
    # Three surfaces in the UI, derived from the category:
    #   • Main bell 🔔  — actionable, high-priority events. CRITICAL (delivery,
    #     reservations) and HIGH (transfers) tiers fire a sound + visual alarm;
    #     'global' rides the bell silently.
    #   • Monitoring 📡 — high-frequency SLA / in-transit / routine-status feed.
    #     Quiet (no alarm, kept OUT of the bell) so the siren stays meaningful.
    #   • Settings ⚙️   — system + branch-connectivity. Quiet cog feed.
    #   • demand / followups — quiet in-module feeds (sidebar hint + module bell).
    CATEGORY_GLOBAL       = 'global'
    CATEGORY_DEMAND       = 'demand'
    CATEGORY_FOLLOWUPS    = 'followups'
    CATEGORY_DELIVERY     = 'delivery'
    CATEGORY_TRANSFERS    = 'transfers'
    CATEGORY_RESERVATIONS = 'reservations'
    CATEGORY_MONITORING   = 'monitoring'
    CATEGORY_SETTINGS     = 'settings'
    CATEGORY_REPORTS      = 'reports'
    CATEGORY_MENTIONS     = 'mentions'
    CATEGORY_CHOICES = [
        (CATEGORY_GLOBAL,       'عام'),
        (CATEGORY_DEMAND,       'الطلب الضائع'),
        (CATEGORY_FOLLOWUPS,    'المتابعات'),
        (CATEGORY_DELIVERY,     'التوصيل'),
        (CATEGORY_TRANSFERS,    'التحويلات'),
        (CATEGORY_RESERVATIONS, 'الحجوزات'),
        (CATEGORY_MONITORING,   'المراقبة'),
        (CATEGORY_SETTINGS,     'النظام والإعدادات'),
        (CATEGORY_REPORTS,      'التقارير الدورية'),
        (CATEGORY_MENTIONS,     'الإشارات'),
    ]
    # Categories kept OUT of the main bell, each with its own quiet surface:
    # demand/followups = module feeds; monitoring = 📡; settings = ⚙️;
    # reports = 📊 (periodic digests); mentions = 💬 (personal @-mentions).
    MODULE_CATEGORIES = (
        CATEGORY_DEMAND, CATEGORY_FOLLOWUPS,
        CATEGORY_MONITORING, CATEGORY_SETTINGS,
        CATEGORY_REPORTS, CATEGORY_MENTIONS,
    )
    # Alarm tiers — drive sound (double-beep vs single-beep) + visual alarm on the
    # bell. Only ACTIONABLE "new" events alarm; routine/monitor types do not.
    ALARM_CRITICAL_TYPES = {
        'delivery_new', 'delivery_cash_variance',
        'reservation_created', 'reservation_assigned', 'stock_available',
    }
    ALARM_HIGH_TYPES = {
        'transfer_request', 'transfer_response', 'unfulfilled_transfer_flag',
        'churn_alert',   # customer about to leave — actionable, time-sensitive
        # Personal @-mentions alarm too, but stay in the quiet 💬 mentions feed
        # (out of the bell) — the front-end fires the alarm on alarm_tier even
        # for quiet-feed categories.
        'mention', 'chatter_mention',
        # A reminder the user set for themselves should actively alert.
        'personal_reminder',
        # Demand-intake SLA breach (TD-C003) — alarms even though it rides the
        # quiet demand module feed (same pattern as mentions above).
        'demand_sla_breach',
    }
    # notification_type → category. Anything not listed is 'global'.
    TYPE_CATEGORY = {
        'demand_created':       CATEGORY_DEMAND,
        'demand_assigned':      CATEGORY_DEMAND,
        'demand_status':        CATEGORY_DEMAND,
        'demand_follow_up':     CATEGORY_DEMAND,
        'demand_back_in_stock': CATEGORY_DEMAND,
        'demand_sla_breach':    CATEGORY_DEMAND,
        'followup':             CATEGORY_FOLLOWUPS,
        # ── Reservations: actionable → bell (CRITICAL alarm) ──────────────────
        'reservation_created':  CATEGORY_RESERVATIONS,
        'reservation_assigned': CATEGORY_RESERVATIONS,
        'stock_available':      CATEGORY_RESERVATIONS,
        # ── Delivery: actionable → bell (CRITICAL alarm) ──────────────────────
        'delivery_new':            CATEGORY_DELIVERY,
        'delivery_cash_variance':  CATEGORY_DELIVERY,
        # ── Transfers: actionable → bell (HIGH alarm) ─────────────────────────
        'transfer_request':           CATEGORY_TRANSFERS,
        'transfer_response':          CATEGORY_TRANSFERS,
        'unfulfilled_transfer_flag':  CATEGORY_TRANSFERS,
        # ── Monitoring: high-frequency SLA / transit / routine status (quiet) ─
        'reservation_status':         CATEGORY_MONITORING,
        'call_logged':                CATEGORY_MONITORING,
        'follow_up_due':              CATEGORY_MONITORING,
        'delivery_status':            CATEGORY_MONITORING,
        'delivery_sla_alert':         CATEGORY_MONITORING,
        'delivery_csat':              CATEGORY_MONITORING,
        'transit_issued':             CATEGORY_MONITORING,
        'transit_approaching_cancel': CATEGORY_MONITORING,
        'transit_overdue':            CATEGORY_MONITORING,
        'transit_critical':           CATEGORY_MONITORING,
        'transit_received':           CATEGORY_MONITORING,
        'transit_cancelled':          CATEGORY_MONITORING,
        # ── Settings / system → cog feed ──────────────────────────────────────
        'system':               CATEGORY_SETTINGS,
        'branch_connectivity':  CATEGORY_SETTINGS,
        # ── Periodic digests → 📊 reports feed (quiet) ────────────────────────
        'weekly_summary':       CATEGORY_REPORTS,
        'monthly_report':       CATEGORY_REPORTS,
        # ── Personal @-mentions → 💬 mentions feed (quiet) ────────────────────
        'mention':              CATEGORY_MENTIONS,
        'chatter_mention':      CATEGORY_MENTIONS,
        # ── Customer churn risk → rides the bell as a HIGH alarm ──────────────
        'churn_alert':          CATEGORY_GLOBAL,
        # ── Personal reminder (snooze return / custom reminder) → bell ────────
        'personal_reminder':    CATEGORY_GLOBAL,
        # ── Internal announcement → bell ──────────────────────────────────────
        'announcement':         CATEGORY_GLOBAL,
    }

    recipient = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='notifications', verbose_name='المستلم',
        db_index=True,
    )
    notification_type = models.CharField(
        max_length=40, choices=NOTIFICATION_TYPES, default='system',
        db_index=True, verbose_name='نوع الإشعار',
    )
    # Derived from notification_type in save() — drives global-vs-module routing.
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_GLOBAL,
        db_index=True, verbose_name='التصنيف',
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES,
        default=PRIORITY_HIGH, verbose_name='الأولوية',
    )
    title   = models.CharField(max_length=255, verbose_name='العنوان')
    body    = models.TextField(blank=True, verbose_name='نص الإشعار')
    is_read = models.BooleanField(default=False, db_index=True, verbose_name='مقروء')

    # Snooze: while snoozed_until is in the future the notification is hidden from
    # the bell/counts; a 1-min worker clears it when due and re-pushes (re-alarm).
    snoozed_until = models.DateTimeField(null=True, blank=True, db_index=True,
                                         verbose_name='مؤجَّل حتى')
    snooze_count  = models.PositiveSmallIntegerField(default=0, verbose_name='عدد مرات التأجيل')

    # Deduplication: same unread key within DEDUP_WINDOW_SECONDS → suppressed
    dedup_key            = models.CharField(max_length=200, blank=True, db_index=True,
                                             verbose_name='مفتاح التكرار')
    DEDUP_WINDOW_SECONDS = 300  # 5 minutes

    # ── Linked domain objects ─────────────────────────────────────────────────
    reservation = models.ForeignKey(
        'reservations.Reservation', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='notifications',
    )
    transfer_request_id_ref = models.IntegerField(null=True, blank=True)
    demand_id_ref           = models.IntegerField(null=True, blank=True)
    chatter_message_id_ref  = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'إشعار'
        verbose_name_plural = 'الإشعارات'
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['notification_type', '-created_at']),
            models.Index(fields=['recipient', 'dedup_key', 'is_read']),
        ]

    def __str__(self):
        return f'[{self.get_notification_type_display()}] {self.title} → {self.recipient}'

    def save(self, *args, **kwargs):
        # Category is always derived from the type map (deterministic routing).
        self.category = self.TYPE_CATEGORY.get(self.notification_type, self.CATEGORY_GLOBAL)
        super().save(*args, **kwargs)

    @property
    def type_icon(self):
        label = dict(self.NOTIFICATION_TYPES).get(self.notification_type, '')
        return label.split(' ')[0] if label else '🔔'

    @property
    def alarm_tier(self):
        """'critical' | 'high' | '' — drives the front-end sound + visual alarm.
        Only actionable bell events alarm; monitoring/settings/quiet never do."""
        if self.notification_type in self.ALARM_CRITICAL_TYPES:
            return 'critical'
        if self.notification_type in self.ALARM_HIGH_TYPES:
            return 'high'
        return ''

    @property
    def push_url(self):
        """Best-effort deep link for a Web Push click → opens the mobile record."""
        if self.reservation_id:
            return f'/m/reservations/{self.reservation_id}'
        if self.demand_id_ref:
            return f'/m/demand/{self.demand_id_ref}'
        return '/m/notifications'

    # ── Real-time WebSocket push ───────────────────────────────────────────────

    def push_realtime(self, event_name: str = 'new_notification'):
        """Push to recipient's open WebSocket. Never raises — WS failure must not
        break the calling DB transaction.

        event_name: 'new_notification' (default) or 'pending_notification' for
                    offline catch-up messages sent on reconnect.
        """
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            from .serializers import NotificationSerializer
            channel_layer = get_channel_layer()
            if channel_layer is None:
                return
            payload          = dict(NotificationSerializer(self).data)
            payload['event'] = event_name
            async_to_sync(channel_layer.group_send)(
                f'notifications_user_{self.recipient_id}',
                {'type': 'notification.message', 'data': payload},
            )
        except Exception as exc:
            logger.debug('WS push skipped for notif %s: %s', self.pk, exc)

    # ── Deduplication ─────────────────────────────────────────────────────────

    @classmethod
    def _is_duplicate(cls, recipient, dedup_key: str, once: bool = False) -> bool:
        if not dedup_key:
            return False
        qs = cls.objects.filter(recipient=recipient, dedup_key=dedup_key)
        if once:
            # The dedup_key already encodes its own time bucket (e.g. a per-day or
            # per-hour suffix), so ANY prior use — read or unread, any age — means
            # this bucket was already alerted. This makes a scheduled job that runs
            # more often than its key granularity (e.g. every 15 min with a per-day
            # key) notify once per bucket instead of once per run. Backed by the
            # (recipient, dedup_key, is_read) index.
            return qs.exists()
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(seconds=cls.DEDUP_WINDOW_SECONDS)
        return qs.filter(is_read=False, created_at__gte=cutoff).exists()

    # ── Branch notifications gate ─────────────────────────────────────────────

    @staticmethod
    def _branch_allows(staff) -> bool:
        try:
            from apps.branches.models import BranchSettings
            if staff.branch_id:
                return BranchSettings.for_branch(staff.branch).notifications_enabled
        except Exception:
            pass
        return True

    # ── Factory helpers ───────────────────────────────────────────────────────

    @classmethod
    def send_to_user(cls, staff, notification_type, title, body='',
                     reservation=None, transfer_id=None, demand_id=None,
                     dedup_key='', chatter_id=None, bypass_role_gate=False,
                     dedup_once=False):
        """Create + deliver one notification to a single staff member.
        Returns the Notification or None if suppressed.

        bypass_role_gate=True skips the per-role generation gate — used for
        user-initiated personal items (e.g. their own reminders) that must
        always reach the owner regardless of role notifier settings.

        dedup_once=True treats the dedup_key as already time-bucketed (it carries
        its own per-day/per-hour suffix): the notification is suppressed if that
        exact key was EVER used for this recipient, not just within the 5-min
        window. Use for scheduled alerts that re-scan on a short interval.
        """
        if not getattr(staff, 'enable_notifications', True):
            return None
        if not cls._branch_allows(staff):
            return None
        # Per-role generation suppression: if this notifier is OFF for the
        # recipient's role, don't create the row at all (admins bypass).
        if not bypass_role_gate:
            category = cls.TYPE_CATEGORY.get(notification_type, cls.CATEGORY_GLOBAL)
            if not RoleNotificationAccess.can_generate(getattr(staff, 'role', None), category):
                return None
        if cls._is_duplicate(staff, dedup_key, once=dedup_once):
            logger.debug('Notif dedup suppressed: %s → %s', dedup_key, staff)
            return None

        notif = cls.objects.create(
            recipient               = staff,
            notification_type       = notification_type,
            priority                = PRIORITY_HIGH,
            title                   = title,
            body                    = body,
            dedup_key               = dedup_key or '',
            reservation             = reservation,
            transfer_request_id_ref = transfer_id,
            demand_id_ref           = demand_id,
            chatter_message_id_ref  = chatter_id,
        )
        NotificationLog.objects.create(notification=notif, recipient=staff)
        notif.push_realtime()
        # Best-effort Web Push (VAPID) — never let a transport failure break the
        # calling DB transaction. No-ops silently when VAPID keys aren't set.
        try:
            send_web_push(staff, title, body or '', notif.push_url)
        except Exception as exc:
            logger.debug('Web Push skipped for notif %s: %s', notif.pk, exc)
        return notif

    @classmethod
    def send_to_branch(cls, branch, notification_type, title, body='',
                       reservation=None, transfer_id=None, demand_id=None,
                       exclude_roles=None, dedup_key='', include_admins=True,
                       dedup_once=False):
        """
        Notify ALL active staff at a branch (respects branch notification gate).

        include_admins=True (default): also notifies global admins (branch=None
        or role='admin') so HQ staff always see branch activity.
        """
        from apps.users.models import StaffProfile
        from apps.branches.models import BranchSettings
        try:
            if not BranchSettings.for_branch(branch).notifications_enabled:
                return 0
        except Exception:
            pass

        # Branch staff — select_related('branch') so _branch_allows() doesn't
        # trigger a separate DB query per staff member (eliminates N+1)
        qs = StaffProfile.objects.filter(
            branch=branch, is_active=True
        ).select_related('branch')
        if exclude_roles:
            qs = qs.exclude(role__in=exclude_roles)

        # Global admins (branch=None) — always kept in the loop
        admin_qs = StaffProfile.objects.none()
        if include_admins:
            admin_qs = StaffProfile.objects.filter(
                role='admin', is_active=True
            ).select_related('branch').exclude(branch=branch)  # avoid double-notify branch-assigned admins

        from itertools import chain
        count = 0
        seen_ids = set()
        for staff in chain(qs, admin_qs):
            if staff.pk in seen_ids:
                continue
            seen_ids.add(staff.pk)
            n = cls.send_to_user(
                staff, notification_type, title, body,
                reservation=reservation, transfer_id=transfer_id,
                demand_id=demand_id, dedup_key=dedup_key,
                dedup_once=dedup_once,
            )
            if n:
                count += 1
        return count

    @classmethod
    def send_to_roles(cls, roles, notification_type, title, body='',
                      reservation=None, transfer_id=None, demand_id=None,
                      branch=None, dedup_key='', dedup_once=False):
        from apps.users.models import StaffProfile
        # select_related('branch') eliminates N+1 — _branch_allows() accesses
        # staff.branch on every iteration without it
        qs = StaffProfile.objects.filter(
            role__in=roles, is_active=True
        ).select_related('branch')
        if branch:
            qs = qs.filter(branch=branch)
        count = 0
        for staff in qs:
            n = cls.send_to_user(
                staff, notification_type, title, body,
                reservation=reservation, transfer_id=transfer_id,
                demand_id=demand_id, dedup_key=dedup_key,
                dedup_once=dedup_once,
            )
            if n:
                count += 1
        return count

    @classmethod
    def send_to_admins(cls, notification_type, title, body='',
                       reservation=None, transfer_id=None, demand_id=None,
                       dedup_key=''):
        return cls.send_to_roles(
            roles=['admin', 'purchasing'],
            notification_type=notification_type,
            title=title, body=body,
            reservation=reservation,
            transfer_id=transfer_id,
            demand_id=demand_id,
            dedup_key=dedup_key,
        )

    @classmethod
    def send_to_call_center(cls, notification_type, title, body='',
                            reservation=None, transfer_id=None, demand_id=None,
                            dedup_key=''):
        """Notify all active call-center staff (and admins who monitor all branches)."""
        return cls.send_to_roles(
            roles=['call_center', 'admin'],
            notification_type=notification_type,
            title=title, body=body,
            reservation=reservation,
            transfer_id=transfer_id,
            demand_id=demand_id,
            dedup_key=dedup_key,
        )


# ── Notification delivery log ─────────────────────────────────────────────────

class NotificationLog(models.Model):
    """
    Full audit trail for every notification.
    Answers: who received it, when was it delivered, when (if ever) was it read.
    """
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE,
        related_name='logs', verbose_name='الإشعار',
    )
    recipient = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='notification_logs', verbose_name='المستلم',
    )
    delivered_at = models.DateTimeField(auto_now_add=True, db_index=True,
                                         verbose_name='وقت التسليم')
    read_at      = models.DateTimeField(null=True, blank=True, db_index=True,
                                         verbose_name='وقت القراءة')

    class Meta:
        unique_together     = ('notification', 'recipient')
        verbose_name        = 'سجل إشعار'
        verbose_name_plural = 'سجلات الإشعارات'
        indexes = [
            models.Index(fields=['recipient', 'read_at']),
            models.Index(fields=['recipient', 'delivered_at']),
            models.Index(fields=['notification', 'delivered_at']),
        ]

    def __str__(self):
        status = f'قُرئ {self.read_at:%Y-%m-%d %H:%M}' if self.read_at else 'لم يُقرأ'
        return f'{self.recipient} ← notif#{self.notification_id} [{status}]'

    def mark_read_now(self):
        if not self.read_at:
            self.read_at = timezone.now()
            self.save(update_fields=['read_at'])


# ════════════════════════════════════════════════════════════════════════════
# Web Push (VAPID) — browser push subscriptions + delivery helper
# ════════════════════════════════════════════════════════════════════════════
#
# Lets the in-app bell stay "alive" even when the tab/app is closed. Each row is
# one browser push endpoint a staff member has granted. We persist the W3C Push
# subscription (endpoint + p256dh + auth keys) and fan a notification out to all
# of a recipient's endpoints via `send_web_push`.
#
# NOTE (iOS): Safari only delivers Web Push to an INSTALLED PWA (Add to Home
# Screen) on iOS/iPadOS 16.4+. Desktop Chrome/Firefox/Edge and Android Chrome
# work in a normal browser tab.

class PushSubscription(models.Model):
    recipient = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='push_subscriptions', verbose_name='المستلم', db_index=True,
    )
    # The push service endpoint URL is the unique identity of a subscription.
    endpoint   = models.URLField(max_length=500, unique=True, verbose_name='نقطة النهاية')
    p256dh     = models.CharField(max_length=255, verbose_name='مفتاح p256dh')
    auth       = models.CharField(max_length=255, verbose_name='مفتاح auth')
    user_agent = models.CharField(max_length=300, blank=True, verbose_name='متصفح/جهاز')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Consecutive delivery failures. Reset to 0 on any successful push. When this
    # crosses PUSH_MAX_FAILURES the subscription is pruned, so a permanently
    # broken endpoint (e.g. VAPID key mismatch → HTTP 400) can't be retried — and
    # log-spammed — forever. 404/410 (Gone) still prune immediately regardless.
    failure_count = models.PositiveSmallIntegerField(default=0, verbose_name='عدد الإخفاقات المتتالية')

    class Meta:
        verbose_name        = 'اشتراك إشعارات المتصفح'
        verbose_name_plural = 'اشتراكات إشعارات المتصفح'
        indexes = [models.Index(fields=['recipient', 'created_at'])]

    def __str__(self):
        return f'push#{self.pk} → {self.recipient} ({self.endpoint[:40]}…)'

    @property
    def subscription_info(self):
        """Shape expected by pywebpush."""
        return {
            'endpoint': self.endpoint,
            'keys': {'p256dh': self.p256dh, 'auth': self.auth},
        }


def send_web_push(staff, title, body='', url='/m/notifications'):
    """
    Best-effort Web Push fan-out to every endpoint a staff member has subscribed.

    No-ops silently when VAPID keys aren't configured (e.g. CI / tests) or when
    pywebpush isn't installed. Dead endpoints (404/410 Gone) are pruned. Never
    raises — callers treat push as a fire-and-forget side effect.

    Returns the number of endpoints successfully pushed.
    """
    private_key = getattr(settings, 'WEBPUSH_VAPID_PRIVATE_KEY', '') or ''
    admin_email = getattr(settings, 'WEBPUSH_VAPID_ADMIN_EMAIL', '') or ''
    if not private_key:
        return 0
    if not getattr(staff, 'enable_browser_push', False):
        return 0

    try:
        from pywebpush import webpush, WebPushException
    except Exception:
        logger.debug('pywebpush not installed — Web Push disabled')
        return 0

    payload = json.dumps({'title': title, 'body': body or '', 'url': url})
    vapid_claims = {'sub': f'mailto:{admin_email}' if admin_email else 'mailto:admin@elrezeiky.com'}

    sent = 0
    for sub in staff.push_subscriptions.all():
        try:
            webpush(
                subscription_info=sub.subscription_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=dict(vapid_claims),  # webpush mutates the claims dict
            )
            sent += 1
            # Success — clear any accumulated failure streak.
            if sub.failure_count:
                PushSubscription.objects.filter(pk=sub.pk).update(failure_count=0)
        except WebPushException as exc:
            status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
            _handle_push_failure(sub, exc, status_code)
        except Exception as exc:
            _handle_push_failure(sub, exc, None)
    return sent


# Prune a subscription after this many consecutive failures. Guards against a
# permanently broken endpoint (VAPID key mismatch → HTTP 400, corrupted keys,
# etc.) being retried — and flooding the log — on every notification. A pruned
# subscription is self-healing: the browser re-subscribes with the current VAPID
# key on next login via initPush().
PUSH_MAX_FAILURES = 5


def _handle_push_failure(sub, exc, status_code):
    """
    Record a push delivery failure and prune the subscription when it is clearly
    dead. Keeps the log quiet: a flapping endpoint warns once (on prune), not on
    every retry.

    - 404 / 410 (Gone): the push service says the subscription no longer exists →
      prune immediately.
    - Anything else (e.g. 400 from a stale/mismatched VAPID key): count it, and
      prune once the consecutive-failure streak crosses PUSH_MAX_FAILURES. A lone
      transient 429/5xx blip therefore never removes a healthy subscription.
    """
    if status_code in (404, 410):
        sub.delete()
        logger.info('Pruned dead push subscription %s (HTTP %s)', sub.pk, status_code)
        return

    new_count = (sub.failure_count or 0) + 1
    PushSubscription.objects.filter(pk=sub.pk).update(failure_count=new_count)
    if new_count >= PUSH_MAX_FAILURES:
        sub.delete()
        logger.warning(
            'Pruned push subscription %s after %s consecutive failures '
            '(last HTTP %s): %s', sub.pk, new_count, status_code, exc,
        )
    else:
        # Don't spam a warning on every retry — the prune above is the signal.
        logger.debug('Web Push failed for sub %s (HTTP %s, streak %s): %s',
                     sub.pk, status_code, new_count, exc)


# ── Chatter ───────────────────────────────────────────────────────────────────

_MENTION_RE = re.compile(r'@([\w؀-ۿ]+)')  # ASCII + Arabic word chars


class ChatterMessage(models.Model):
    """
    Threaded comment attached to any platform record.
    @username  → sends notification to that staff member
    @branchname → sends notification to all staff in that branch
    """
    model_name = models.CharField(
        max_length=100, db_index=True, verbose_name='النموذج',
        help_text='e.g. reservation | invoice | transfer',
    )
    record_id = models.PositiveIntegerField(db_index=True, verbose_name='معرف السجل')
    author    = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='chatter_messages', verbose_name='المرسل',
    )
    message   = models.TextField(verbose_name='الرسالة')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # ── Attachment ────────────────────────────────────────────────────────────
    FILE_TYPE_CHOICES = [
        ('image', 'صورة'),
        ('voice', 'صوت'),
        ('doc',   'مستند'),
    ]
    attachment = models.FileField(
        upload_to='chatter/%Y/%m/',
        blank=True, null=True,
        verbose_name='مرفق',
    )
    file_type = models.CharField(
        max_length=10,
        choices=FILE_TYPE_CHOICES,
        blank=True,
        verbose_name='نوع المرفق',
    )
    # Dedicated voice note — kept SEPARATE from `attachment` so one message can
    # carry an image (attachment) AND a voice note at the same time, matching
    # reservations.ReservationActivity and transfers.TransferRequestMessage.
    voice_note = models.FileField(
        upload_to='chatter_voices/%Y/%m/',
        blank=True, null=True,
        verbose_name='ملاحظة صوتية',
        help_text='ملاحظة صوتية (WebRTC أو ملف صوتي) — مستقلة عن المرفق',
    )
    is_internal = models.BooleanField(
        default=True,
        verbose_name='داخلي فقط',
        help_text='إذا كان False فهو مرئي للعميل أيضاً',
    )

    class Meta:
        ordering            = ['created_at']
        verbose_name        = 'رسالة دردشة'
        verbose_name_plural = 'رسائل الدردشة'
        indexes = [
            models.Index(fields=['model_name', 'record_id', 'created_at']),
        ]

    def __str__(self):
        return f'{self.author} @ {self.model_name}/{self.record_id}'

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            self._process_mentions()
            self._push_chatter_realtime()

    def _process_mentions(self):
        from apps.users.models import StaffProfile
        from apps.branches.models import Branch
        from django.db.models import Q

        mentioned = set(_MENTION_RE.findall(self.message))
        preview   = self.message[:200]

        for handle in mentioned:
            # ── @username ──────────────────────────────────────────────────────
            try:
                staff = StaffProfile.objects.select_related('user').get(
                    user__username__iexact=handle
                )
                if staff != self.author:
                    Notification.send_to_user(
                        staff             = staff,
                        notification_type = 'chatter_mention',
                        title             = f'ذكرك {self.author.full_name} في تعليق',
                        body              = preview,
                        chatter_id        = self.pk,
                        dedup_key         = f'cm_{self.pk}_{staff.pk}',
                    )
                continue
            except StaffProfile.DoesNotExist:
                pass

            # ── @branch_name ───────────────────────────────────────────────────
            try:
                branch = Branch.objects.get(
                    Q(name__iexact=handle) | Q(name_ar__iexact=handle)
                )
                Notification.send_to_branch(
                    branch            = branch,
                    notification_type = 'chatter_mention',
                    title             = f'ذكر الفرع «{branch.display_name}» — {self.author.full_name}',
                    body              = preview,
                    dedup_key         = f'cm_b_{self.pk}_{branch.pk}',
                )
            except Branch.DoesNotExist:
                pass

    def _push_chatter_realtime(self):
        """Broadcast to all clients watching chatter_{model}_{record_id}."""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            from .serializers import ChatterMessageSerializer
            channel_layer = get_channel_layer()
            if channel_layer is None:
                return
            payload          = dict(ChatterMessageSerializer(self).data)
            payload['event'] = 'new_chatter'
            async_to_sync(channel_layer.group_send)(
                f'chatter_{self.model_name}_{self.record_id}',
                {'type': 'chatter.message', 'data': payload},
            )
        except Exception as exc:
            logger.debug('Chatter WS push skipped: %s', exc)


# ════════════════════════════════════════════════════════════════════════════
# Per-role notification visibility ("which notifiers appear to which role")
# ════════════════════════════════════════════════════════════════════════════

class RoleNotificationAccess(models.Model):
    """
    Admin-controlled per-role behaviour for each notification category/feed.

    Two flags give three effective modes (see .mode):
      • SHOW  — generate=True,  is_allowed=True   → created, appears, alarms
      • MUTE  — generate=True,  is_allowed=False  → created/recorded, but hidden
      • OFF   — generate=False                    → not created at all for the role

    Resolution:
      • admin role        → always SHOW (bypass)
      • explicit row      → use its flags
      • no row            → generate (default True); visibility INHERITS the
                            module 'view' permission (non-breaking default)

    Visibility is enforced in notifications.views (_can_view_category); generation
    suppression is enforced in Notification.send_to_user (per recipient).
    """
    from apps.users.models import ROLE_CHOICES as _ROLE_CHOICES

    role       = models.CharField(max_length=20, choices=_ROLE_CHOICES, db_index=True)
    category   = models.CharField(max_length=20, choices=Notification.CATEGORY_CHOICES, db_index=True)
    is_allowed = models.BooleanField(default=True, verbose_name='يظهر')
    generate   = models.BooleanField(default=True, verbose_name='يُنشأ',
                                     help_text='عند الإيقاف لا تُنشأ إشعارات هذه الفئة لهذا الدور')
    updated_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('role', 'category')
        verbose_name        = 'إعداد إشعار للدور'
        verbose_name_plural = 'إعدادات الإشعارات للأدوار'
        ordering = ['role', 'category']

    def __str__(self):
        return f'{self.mode} | {self.role} | {self.category}'

    @property
    def mode(self):
        if not self.generate:
            return 'off'
        return 'show' if self.is_allowed else 'mute'

    # ── Generation-suppression resolver (cached; tiny table) ──────────────────
    _GEN_CACHE = {'map': None, 'ts': 0.0}
    _GEN_TTL   = 30  # seconds

    @classmethod
    def _generation_map(cls):
        """{(role, category): generate_bool} — cached briefly (per process)."""
        import time
        now = time.time()
        c = cls._GEN_CACHE
        if c['map'] is None or now - c['ts'] > cls._GEN_TTL:
            c['map'] = {(r, cat): g for r, cat, g in
                        cls.objects.values_list('role', 'category', 'generate')}
            c['ts'] = now
        return c['map']

    @classmethod
    def can_generate(cls, role, category):
        """False only when an explicit row has generate=False (admin always True)."""
        if role == 'admin':
            return True
        return cls._generation_map().get((role, category), True)

    @classmethod
    def _bust_cache(cls):
        cls._GEN_CACHE['map'] = None

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        type(self)._bust_cache()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        type(self)._bust_cache()


# ════════════════════════════════════════════════════════════════════════════
# Personal reminders  ("remind me later" — private, lightweight)
# Distinct from the operational FollowUpTask system: these are per-user notes
# that simply fire a Notification at remind_at. A 1-min scheduler worker fires
# due reminders; no assignment, no workflow, no audit trail.
# ════════════════════════════════════════════════════════════════════════════

class PersonalReminder(models.Model):
    owner      = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='personal_reminders', db_index=True, verbose_name='صاحب التذكير',
    )
    title      = models.CharField(max_length=255, verbose_name='العنوان')
    note       = models.TextField(blank=True, verbose_name='ملاحظة')
    remind_at  = models.DateTimeField(db_index=True, verbose_name='وقت التذكير')
    is_fired   = models.BooleanField(default=False, db_index=True, verbose_name='تم التذكير')
    fired_at   = models.DateTimeField(null=True, blank=True)

    # Optional deep-link — mirrors Notification so the fired alert can navigate.
    reservation             = models.ForeignKey(
        'reservations.Reservation', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='personal_reminders',
    )
    demand_id_ref           = models.IntegerField(null=True, blank=True)
    transfer_request_id_ref = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['remind_at']
        verbose_name        = 'تذكير شخصي'
        verbose_name_plural = 'تذكيرات شخصية'
        indexes = [models.Index(fields=['owner', 'is_fired', 'remind_at'])]

    def __str__(self):
        return f'⏰ {self.title} → {self.owner} @ {self.remind_at:%Y-%m-%d %H:%M}'

    def fire(self):
        """Create the reminder Notification for the owner and mark fired. Idempotent."""
        if self.is_fired:
            return None
        notif = Notification.send_to_user(
            self.owner, 'personal_reminder',
            title=self.title or 'تذكير',
            body=self.note,
            reservation=self.reservation,
            demand_id=self.demand_id_ref,
            transfer_id=self.transfer_request_id_ref,
            dedup_key=f'reminder_{self.pk}',
            bypass_role_gate=True,   # a user's own reminder always reaches them
        )
        self.is_fired = True
        self.fired_at = timezone.now()
        self.save(update_fields=['is_fired', 'fired_at'])
        return notif


# ════════════════════════════════════════════════════════════════════════════
# Internal announcements / broadcast (HQ → branches, with read-acknowledgement)
# ════════════════════════════════════════════════════════════════════════════

class Announcement(models.Model):
    PRIORITY_NORMAL = 'normal'
    PRIORITY_HIGH   = 'high'
    PRIORITY_CHOICES = [(PRIORITY_NORMAL, 'عادي'), (PRIORITY_HIGH, 'هام')]

    title  = models.CharField(max_length=255, verbose_name='العنوان')
    body   = models.TextField(verbose_name='المحتوى')
    author = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                               null=True, related_name='announcements', verbose_name='الكاتب')
    # Audience filters — empty list means "everyone".
    audience_roles      = models.JSONField(default=list, blank=True, verbose_name='الأدوار المستهدفة')
    audience_branch_ids = models.JSONField(default=list, blank=True, verbose_name='الفروع المستهدفة')
    priority   = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_NORMAL)
    is_pinned  = models.BooleanField(default=False, verbose_name='مثبّت')
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name='ينتهي في')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-is_pinned', '-created_at']
        verbose_name        = 'إعلان داخلي'
        verbose_name_plural = 'الإعلانات الداخلية'

    def __str__(self):
        return f'📢 {self.title}'

    def audience_staff(self):
        """StaffProfiles this announcement targets (role ∩ branch filters; empty = all)."""
        from apps.users.models import StaffProfile
        qs = StaffProfile.objects.filter(is_active=True)
        if self.audience_roles:
            qs = qs.filter(role__in=self.audience_roles)
        if self.audience_branch_ids:
            qs = qs.filter(branch_id__in=self.audience_branch_ids)
        return qs

    def fan_out(self):
        """Send a bell notification to every targeted staff member."""
        count = 0
        for staff in self.audience_staff().select_related('branch'):
            n = Notification.send_to_user(
                staff, 'announcement',
                title=f'📢 {self.title}',
                body=(self.body or '')[:280],
                dedup_key=f'ann_{self.pk}_{staff.pk}',
            )
            if n:
                count += 1
        return count


class AnnouncementRead(models.Model):
    """One row per staff member who has acknowledged an announcement."""
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name='reads')
    staff        = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE,
                                     related_name='announcement_reads')
    read_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('announcement', 'staff')
        verbose_name        = 'تأكيد قراءة إعلان'
        verbose_name_plural = 'تأكيدات قراءة الإعلانات'

    def __str__(self):
        return f'{self.staff} ✓ {self.announcement_id}'
