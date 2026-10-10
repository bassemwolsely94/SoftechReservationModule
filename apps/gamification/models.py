"""
apps/gamification/models.py — التحفيز بالألعاب (Gamification).

Recognition only (no money): staff earn points for the work they already do in the
platform and in SOFTECH, climb levels with titles, collect badges, keep a "clean day"
streak (nothing left behind), and are ranked within their branch and across the network.

Design rules
  * The engine READS existing records (sales mirror, reservations, transfers, demand,
    stock count, tasks, ISR …). It never changes them and never touches SOFTECH.
  * PointEvent is an append-only ledger. Each event names its source record
    (`source_key`), and (staff, rule, source_key) is UNIQUE, so re-running the engine
    can never award the same work twice.
  * Levels use lifetime XP = sum of POSITIVE points only, so penalties never drop a
    level; penalties only affect the period ranking (net points).
  * Rules, levels and badges are data, edited by admins; every edit is recorded in
    GamificationChange (who / what / before / after / why).
"""
from django.db import models


CATEGORY_CHOICES = [
    ('sales',        'المبيعات'),
    ('reservations', 'الحجوزات'),
    ('demand',       'الطلب الضائع والمتابعة'),
    ('transfers',    'التحويلات وطلبات الفروع'),
    ('inventory',    'المخزون والجرد والنواقص'),
    ('tasks',        'المهام'),
    ('discipline',   'الالتزام (لا تترك شيئاً خلفك)'),
    ('manual',       'تقدير يدوي'),
]


class PointRule(models.Model):
    """One way to earn (or lose) points. `key` is referenced by the engine collectors."""
    key = models.SlugField(max_length=50, unique=True, verbose_name='المفتاح')
    name_ar = models.CharField(max_length=150, verbose_name='الاسم (عربي)')
    name_en = models.CharField(max_length=150, verbose_name='الاسم (إنجليزي)')
    desc_ar = models.CharField(max_length=300, blank=True, verbose_name='الشرح (عربي)')
    desc_en = models.CharField(max_length=300, blank=True, verbose_name='الشرح (إنجليزي)')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, db_index=True,
                                verbose_name='الفئة')
    # Points per occurrence (negative = penalty). For value rules: points per `unit_value`.
    points = models.IntegerField(verbose_name='النقاط')
    unit_value = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='قيمة الوحدة (جنيه)',
        help_text='لقواعد القيمة فقط: نقطة لكل هذا المبلغ (مثلاً 500 جنيه مبيعات)',
    )
    cash_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=1, verbose_name='مضاعف الكاش',
        help_text='يُضرب في نقاط مبيعات الكاش (قناة 91)',
    )
    daily_cap = models.IntegerField(
        null=True, blank=True, verbose_name='الحد اليومي',
        help_text='أقصى نقاط (أو خصم) من هذه القاعدة للموظف في اليوم — فارغ = بلا حد',
    )
    grace_hours = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='مهلة (ساعات)',
        help_text='للقواعد الزمنية: الرد السريع خلال هذه المهلة',
    )
    roles = models.JSONField(default=list, blank=True, verbose_name='الأدوار',
                             help_text='فارغ = كل الأدوار')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='مفعّلة')
    sort = models.PositiveIntegerField(default=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'قاعدة نقاط'
        verbose_name_plural = 'قواعد النقاط'
        ordering = ['category', 'sort', 'key']

    def __str__(self):
        return f'{self.name_ar} ({self.points:+d})'

    @property
    def is_penalty(self):
        return self.points < 0

    def applies_to(self, role):
        return not self.roles or role in self.roles


class Level(models.Model):
    number = models.PositiveIntegerField(unique=True, verbose_name='المستوى')
    min_xp = models.PositiveIntegerField(unique=True, verbose_name='الحد الأدنى للخبرة')
    title_ar = models.CharField(max_length=80, verbose_name='اللقب (عربي)')
    title_en = models.CharField(max_length=80, verbose_name='اللقب (إنجليزي)')
    icon = models.CharField(max_length=8, default='⭐')
    color = models.CharField(max_length=20, default='slate')

    class Meta:
        verbose_name = 'مستوى'
        verbose_name_plural = 'المستويات'
        ordering = ['number']

    def __str__(self):
        return f'{self.number} — {self.title_ar}'


class Badge(models.Model):
    CRITERIA_RULE_COUNT = 'rule_count'   # N events of `rule_key`
    CRITERIA_STREAK     = 'streak'       # best clean-day streak ≥ N
    CRITERIA_XP         = 'xp'           # lifetime XP ≥ N
    CRITERIA_CHOICES = [
        (CRITERIA_RULE_COUNT, 'عدد مرات قاعدة'),
        (CRITERIA_STREAK,     'سلسلة أيام نظيفة'),
        (CRITERIA_XP,         'إجمالي الخبرة'),
    ]
    key = models.SlugField(max_length=50, unique=True)
    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    desc_ar = models.CharField(max_length=300, blank=True)
    desc_en = models.CharField(max_length=300, blank=True)
    icon = models.CharField(max_length=8, default='🏅')
    criteria = models.CharField(max_length=20, choices=CRITERIA_CHOICES)
    rule_key = models.SlugField(max_length=50, blank=True)
    threshold = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    sort = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = 'شارة'
        verbose_name_plural = 'الشارات'
        ordering = ['sort', 'key']

    def __str__(self):
        return self.name_ar


class PointEvent(models.Model):
    """Append-only points ledger. Never updated or deleted by the app."""
    staff = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE,
                              related_name='point_events', verbose_name='الموظف')
    rule_key = models.SlugField(max_length=50, db_index=True, verbose_name='القاعدة')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, db_index=True)
    points = models.IntegerField(verbose_name='النقاط')
    day = models.DateField(db_index=True, verbose_name='اليوم')
    occurred_at = models.DateTimeField(verbose_name='وقت العمل')
    source_key = models.CharField(max_length=120, verbose_name='المصدر',
                                  help_text='مرجع السجل الذي استحق النقاط — يمنع الاحتساب مرتين')
    branch = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='+')
    meta = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+',
                                   help_text='للتقدير اليدوي فقط')
    reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'حركة نقاط'
        verbose_name_plural = 'سجل النقاط'
        ordering = ['-occurred_at']
        constraints = [
            models.UniqueConstraint(fields=['staff', 'rule_key', 'source_key'],
                                    name='uniq_gamification_event_source'),
        ]
        indexes = [
            models.Index(fields=['staff', 'day']),
            models.Index(fields=['day', 'category']),
        ]

    def __str__(self):
        return f'{self.staff_id} {self.rule_key} {self.points:+d} {self.day}'


class PlayerProfile(models.Model):
    """Cached per-staff totals, rebuilt from the ledger by the engine."""
    staff = models.OneToOneField('users.StaffProfile', on_delete=models.CASCADE,
                                 related_name='player')
    xp = models.PositiveIntegerField(default=0, verbose_name='الخبرة')
    net_points = models.IntegerField(default=0, verbose_name='صافي النقاط')
    level = models.ForeignKey(Level, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='+')
    current_streak = models.PositiveIntegerField(default=0)
    best_streak = models.PositiveIntegerField(default=0)
    last_clean_day = models.DateField(null=True, blank=True)
    last_scored_day = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ملف لاعب'
        verbose_name_plural = 'ملفات اللاعبين'


class DailyScore(models.Model):
    """Per staff per day — the basis for streaks and for the executive reports."""
    staff = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE,
                              related_name='daily_scores')
    day = models.DateField(db_index=True)
    branch = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='+')
    earned = models.IntegerField(default=0)
    lost = models.IntegerField(default=0)
    net = models.IntegerField(default=0, db_index=True)
    events = models.PositiveIntegerField(default=0)
    clean_day = models.BooleanField(default=False)
    left_behind = models.PositiveIntegerField(default=0,
                                              help_text='عدد البنود المتأخرة عند إغلاق اليوم')
    finalized = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['staff', 'day'], name='uniq_gamification_daily'),
        ]
        ordering = ['-day']


class StaffBadge(models.Model):
    staff = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE,
                              related_name='badges')
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name='holders')
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['staff', 'badge'], name='uniq_gamification_badge'),
        ]
        ordering = ['-earned_at']


class LevelHistory(models.Model):
    """Every promotion (ترقية) — shown on the profile and in the executive report."""
    staff = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE,
                              related_name='level_history')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='+')
    xp = models.PositiveIntegerField(default=0)
    reached_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['staff', 'level'], name='uniq_gamification_level_once'),
        ]
        ordering = ['-reached_at']


class GamificationChange(models.Model):
    """Audit of every admin edit (rule / level / badge / manual award / recompute)."""
    actor = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                              null=True, related_name='+')
    action = models.CharField(max_length=30)
    target = models.CharField(max_length=120)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
