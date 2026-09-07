"""
apps/pbx/models.py

Issabel PBX / Asterisk AMI Integration.

Models:
  AgentExtension  — maps Asterisk extension to StaffProfile
  PBXQueue        — Asterisk queue definition
  PBXEvent        — raw AMI event log (immutable)
  CallSession     — one per call leg (bridges AMI → CallLog)

Integration:
  - PBXEvent is IMMUTABLE — raw AMI events are never edited
  - CallSession → creates apps.callcenter.CallLog on call completion
  - AgentExtension → maps Asterisk extension → StaffProfile
  - Inbound: auto-search customer by CallerID → populate CallLog.customer
  - Recording files: stored path from Asterisk monitor directory

AMI bridge lives in apps/pbx/ami_bridge.py (async Channels worker).
"""
from django.db import models
from django.utils import timezone


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AgentExtension — Asterisk extension ↔ StaffProfile mapping
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AgentExtension(models.Model):

    TYPE_AGENT   = 'agent'
    TYPE_BRANCH  = 'branch'
    TYPE_HQ      = 'hq'
    TYPE_GATEWAY = 'gateway'
    TYPE_OTHER   = 'other'

    EXTENSION_TYPE_CHOICES = [
        (TYPE_AGENT,   'عامل مركز اتصال'),
        (TYPE_BRANCH,  'تحويلة فرع'),
        (TYPE_HQ,      'موظف إداري (المقر الرئيسي)'),
        (TYPE_GATEWAY, 'بوابة خارجية (GoIP/Trunk)'),
        (TYPE_OTHER,   'أخرى'),
    ]

    # Gateway sub-type — only meaningful when extension_type == 'gateway'
    GATEWAY_MOBILE   = 'mobile'
    GATEWAY_LANDLINE = 'landline'
    GATEWAY_SIP      = 'sip'
    GATEWAY_OTHER    = 'other_gw'

    GATEWAY_TYPE_CHOICES = [
        (GATEWAY_MOBILE,   'خط موبايل (GoIP/GSM)'),
        (GATEWAY_LANDLINE, 'خط أرضي (Grandstream/PSTN)'),
        (GATEWAY_SIP,      'SIP Trunk'),
        (GATEWAY_OTHER,    'بوابة أخرى'),
    ]

    extension   = models.CharField(
        max_length=20, unique=True, db_index=True,
        verbose_name='رقم التحويلة',
        help_text='رقم التحويلة في Asterisk (e.g. "201", "SIP/201")',
    )
    extension_type = models.CharField(
        max_length=10, choices=EXTENSION_TYPE_CHOICES,
        default=TYPE_OTHER, db_index=True,
        verbose_name='نوع التحويلة',
    )
    # Nullable — extensions not yet assigned to a user
    staff       = models.OneToOneField(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pbx_extension',
        verbose_name='الموظف',
    )
    # SIP peer name in Asterisk (may differ from extension number)
    sip_peer    = models.CharField(
        max_length=50, blank=True,
        verbose_name='SIP Peer',
    )
    queue_name  = models.CharField(
        max_length=50, blank=True,
        verbose_name='اسم القائمة',
        help_text='الـ queue الافتراضية لهذا العميل في Asterisk',
    )
    # Last known registration status from AMI SIPpeers
    last_status = models.CharField(
        max_length=50, blank=True,
        verbose_name='آخر حالة',
        help_text='e.g. OK (25 ms), UNKNOWN, UNREACHABLE',
    )
    last_ip     = models.CharField(
        max_length=50, blank=True,
        verbose_name='آخر IP مسجّل',
    )
    # ── Gateway-specific fields (only used when extension_type == 'gateway') ──
    gateway_type = models.CharField(
        max_length=12,
        choices=GATEWAY_TYPE_CHOICES,
        blank=True, default='',
        verbose_name='نوع البوابة',
        help_text='موبايل (GoIP) أو أرضي (Grandstream) — فقط للتحويلات من نوع gateway',
    )
    # Prefix that the PBX *prepends* to caller numbers on this gateway.
    # We strip it before storing the clean phone number.
    # e.g. if GoIP adds "0" → set call_prefix="0"
    call_prefix = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name='بادئة الرقم',
        help_text='البادئة التي يضيفها الـ PBX لأرقام المتصلين على هذه البوابة (مثل 0 أو 00 أو +2)',
    )
    # Suffix appended by the PBX (rare but supported)
    call_suffix = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name='لاحقة الرقم',
        help_text='اللاحقة التي يضيفها الـ PBX (نادرة — اتركها فارغة إن لم توجد)',
    )

    is_active   = models.BooleanField(default=True, verbose_name='نشط')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تحويلة'
        verbose_name_plural = 'التحويلات'
        ordering            = ['extension']

    def __str__(self):
        user = self.staff.full_name if self.staff else '(غير مُعيَّن)'
        return f'ext {self.extension} [{self.get_extension_type_display()}] → {user}'

    @property
    def is_registered(self) -> bool:
        return self.last_status.startswith('OK')

    @property
    def is_gateway(self) -> bool:
        return self.extension_type == self.TYPE_GATEWAY

    def normalize_number(self, raw: str) -> str:
        """
        Strip any PBX-added prefix / suffix from a caller number received
        on this gateway so the clean E.164-ish number is stored.
        e.g.  raw='001234567890', call_prefix='00' → '1234567890'
        """
        num = (raw or '').strip()
        if self.call_prefix and num.startswith(self.call_prefix):
            num = num[len(self.call_prefix):]
        if self.call_suffix and num.endswith(self.call_suffix):
            num = num[:-len(self.call_suffix)]
        return num or raw


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PBXQueue — Asterisk queue definition
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PBXQueue(models.Model):

    name        = models.CharField(
        max_length=50, unique=True,
        verbose_name='اسم القائمة',
    )
    description = models.CharField(max_length=255, blank=True, verbose_name='الوصف')
    branch      = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pbx_queues',
        verbose_name='الفرع',
    )
    is_active   = models.BooleanField(default=True)

    class Meta:
        verbose_name        = 'قائمة PBX'
        verbose_name_plural = 'قوائم PBX'

    def __str__(self):
        return self.name


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PBXEvent — raw AMI event (IMMUTABLE)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PBXEvent(models.Model):
    """
    One row per Asterisk AMI event received by the bridge.
    IMMUTABLE — never edit or delete; these are the raw audit trail.
    """

    # Common AMI event types we care about
    EVENT_TYPE_CHOICES = [
        ('Newchannel',      'قناة جديدة'),
        ('Hangup',          'إغلاق المكالمة'),
        ('Bridge',          'ربط'),
        ('AgentCalled',     'عامل مُتصل'),
        ('AgentConnect',    'اتصال عامل'),
        ('AgentComplete',   'اكتمال عامل'),
        ('QueueCallerJoin', 'عميل دخل القائمة'),
        ('QueueCallerLeave','عميل غادر القائمة'),
        ('QueueCallerAbandon','عميل أهمل القائمة'),
        ('MusicOnHold',     'انتظار موسيقى'),
        ('DTMFBegin',       'DTMF'),
        ('VarSet',          'متغير'),
        ('Cdr',             'CDR'),
        ('Other',           'أخرى'),
    ]

    event_type      = models.CharField(
        max_length=30, choices=EVENT_TYPE_CHOICES,
        default='Other', db_index=True,
        verbose_name='نوع الحدث',
    )
    # Raw AMI payload as-received
    payload         = models.JSONField(verbose_name='البيانات الخام')

    # Extracted key fields (for fast lookup without JSON parse)
    unique_id       = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='UniqueID',
        help_text='Asterisk UniqueID for the call leg',
    )
    linked_id       = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='LinkedID',
        help_text='Shared across bridged legs',
    )
    channel         = models.CharField(max_length=100, blank=True)
    caller_id_num   = models.CharField(max_length=50, blank=True, db_index=True)
    caller_id_name  = models.CharField(max_length=100, blank=True)
    extension       = models.CharField(max_length=50, blank=True)
    queue_name      = models.CharField(max_length=50, blank=True, db_index=True)

    received_at     = models.DateTimeField(auto_now_add=True, db_index=True)

    # Linked to the CallSession that was built from this event
    session         = models.ForeignKey(
        'CallSession',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='events',
        verbose_name='جلسة المكالمة',
    )

    class Meta:
        ordering = ['-received_at']
        verbose_name        = 'حدث AMI'
        verbose_name_plural = 'أحداث AMI'
        indexes = [
            models.Index(fields=['unique_id', 'received_at']),
            models.Index(fields=['linked_id', 'event_type']),
            models.Index(fields=['caller_id_num', 'received_at']),
        ]

    def __str__(self):
        return f'[{self.event_type}] {self.caller_id_num} → {self.extension} @ {self.received_at:%H:%M:%S}'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('PBXEvent is immutable — cannot edit')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('PBXEvent is immutable — cannot delete')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CallSession — one per call, bridges AMI → CallLog
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CallSession(models.Model):
    """
    Aggregates AMI events for a single call into a structured session.
    On hangup, the bridge creates a callcenter.CallLog from this session.
    """

    STATE_CHOICES = [
        ('ringing',    'يرن'),
        ('answered',   'أُجيب'),
        ('queued',     'في القائمة'),
        ('on_hold',    'قيد الانتظار'),
        ('transferred','محوَّل'),
        ('completed',  'مكتمل'),
        ('abandoned',  'أُهمل'),
        ('no_answer',  'لا رد'),
        ('busy',       'مشغول'),
        ('failed',     'فشل'),
    ]

    DIRECTION_CHOICES = [
        ('inbound',  'وارد'),
        ('outbound', 'صادر'),
        ('internal', 'داخلي'),
    ]

    # Asterisk identifiers
    unique_id       = models.CharField(
        max_length=50, unique=True, db_index=True,
        verbose_name='UniqueID',
    )
    linked_id       = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='LinkedID',
    )

    direction       = models.CharField(
        max_length=10, choices=DIRECTION_CHOICES,
        default='inbound', verbose_name='الاتجاه',
    )
    state           = models.CharField(
        max_length=12, choices=STATE_CHOICES,
        default='ringing', db_index=True, verbose_name='الحالة',
    )

    # Caller details
    caller_number   = models.CharField(max_length=50, db_index=True, verbose_name='رقم المتصل')
    caller_name     = models.CharField(max_length=100, blank=True)

    # Destination
    destination_ext = models.CharField(max_length=50, blank=True, verbose_name='رقم المقصد')
    queue           = models.ForeignKey(
        PBXQueue,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sessions',
        verbose_name='القائمة',
    )
    agent           = models.ForeignKey(
        AgentExtension,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sessions',
        verbose_name='العامل',
    )

    # Timing
    started_at      = models.DateTimeField(default=timezone.now, db_index=True)
    answered_at     = models.DateTimeField(null=True, blank=True)
    ended_at        = models.DateTimeField(null=True, blank=True)

    # Duration in seconds (calculated on completion)
    wait_seconds    = models.PositiveIntegerField(default=0, verbose_name='وقت الانتظار')
    talk_seconds    = models.PositiveIntegerField(default=0, verbose_name='وقت الحديث')

    # Recording
    recording_path  = models.CharField(
        max_length=500, blank=True,
        verbose_name='مسار التسجيل',
        help_text='Full path on Asterisk server, e.g. /var/spool/asterisk/monitor/...',
    )
    recording_url   = models.URLField(blank=True, verbose_name='رابط التسجيل')

    # Auto-matched customer
    customer        = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pbx_sessions',
        verbose_name='العميل',
    )

    # Resulting CallLog (created on session completion)
    call_log        = models.OneToOneField(
        'callcenter.CallLog',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pbx_session',
        verbose_name='سجل المكالمة',
    )

    # CDR data (populated from Asterisk CDR table or CdrEvent)
    cdr_disposition = models.CharField(max_length=20, blank=True)
    cdr_userfield   = models.CharField(max_length=255, blank=True)

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name        = 'جلسة مكالمة PBX'
        verbose_name_plural = 'جلسات مكالمات PBX'
        indexes = [
            models.Index(fields=['caller_number', 'started_at']),
            models.Index(fields=['state', 'started_at']),
            models.Index(fields=['agent', 'started_at']),
        ]

    def __str__(self):
        return (
            f'[{self.get_direction_display()}] {self.caller_number} '
            f'→ ext {self.destination_ext} @ {self.started_at:%H:%M:%S} '
            f'[{self.get_state_display()}]'
        )

    @property
    def total_seconds(self) -> int:
        return self.wait_seconds + self.talk_seconds

    def _try_match_customer(self):
        if self.customer_id or not self.caller_number:
            return
        try:
            from apps.customers.models import Customer
            tail = self.caller_number.strip().replace(' ', '')[-9:]
            c = (
                Customer.objects.filter(phone__endswith=tail).first()
                or Customer.objects.filter(phone_alt__endswith=tail).first()
            )
            if c:
                self.customer = c
        except Exception:
            pass

    def complete(self, state: str = 'completed'):
        """
        Called by the AMI bridge on Hangup.
        Calculates durations, matches customer, creates CallLog.
        """
        self.state = state
        self.ended_at = timezone.now()

        if self.answered_at:
            self.wait_seconds = max(
                0, int((self.answered_at - self.started_at).total_seconds())
            )
            self.talk_seconds = max(
                0, int((self.ended_at - self.answered_at).total_seconds())
            )
        else:
            self.wait_seconds = max(
                0, int((self.ended_at - self.started_at).total_seconds())
            )

        self._try_match_customer()
        self.save()

        # Create callcenter.CallLog
        self._create_call_log()

    def _create_call_log(self):
        """Build a callcenter.CallLog from this session."""
        try:
            from apps.callcenter.models import CallLog

            direction_map = {
                'inbound': 'inbound',
                'outbound': 'outbound',
                'internal': 'outbound',
            }
            status_map = {
                'completed':  'answered',
                'abandoned':  'no_answer',
                'no_answer':  'no_answer',
                'busy':       'busy',
                'failed':     'no_answer',
            }
            staff = self.agent.staff if self.agent else None
            branch = staff.branch if staff and hasattr(staff, 'branch') else None

            log = CallLog.objects.create(
                phone_number=self.caller_number,
                customer=self.customer,
                caller_name=self.caller_name,
                direction=direction_map.get(self.direction, 'inbound'),
                status=status_map.get(self.state, 'answered'),
                duration_seconds=self.talk_seconds,
                handled_by=staff,
                branch=branch,
                recording_url=self.recording_url,
                called_at=self.started_at,
            )
            self.call_log = log
            self.save(update_fields=['call_log', 'updated_at'])
        except Exception as exc:
            import logging
            logging.getLogger('elrezeiky.pbx').warning(
                f'CallSession._create_call_log failed for session {self.unique_id}: {exc}'
            )
