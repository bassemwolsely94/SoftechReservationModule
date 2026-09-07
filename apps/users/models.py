from django.db import models
from django.contrib.auth.models import User


ROLE_CHOICES = [
    ('admin',           'Admin — Full Access'),
    ('call_center',     'Call Center — All Branches'),
    ('pharmacist',      'Pharmacist — Own Branch'),
    ('salesperson',     'Sales Person — Own Branch'),
    ('purchasing',      'Purchasing — HQ Only'),
    ('delivery',        'Delivery'),
    ('viewer',          'Viewer — Read Only'),
    ('supervisor',      'Supervisor — Call Center Supervisor'),
    ('quality_manager', 'Quality Manager — QA & Scoring'),
]

# Canonical module identifiers used by RoleModuleAccess
MODULE_CHOICES = [
    # ── Core Operations ──────────────────────────────────────────────────────
    ('reservations', 'الحجوزات'),
    ('demand',       'الطلب الضائع / المبيعات المفقودة'),
    ('transfers',    'طلبات التحويل'),
    ('followups',    'متابعة المزمن'),
    ('delivery',     'توصيل الطلبات'),
    # ── Customers & CRM ──────────────────────────────────────────────────────
    ('customers',    'العملاء'),
    ('chronic',      'الأدوية المزمنة'),
    ('campaigns',    'حملات واتساب'),
    ('vouchers',     'القسائم'),
    # ── Inventory ─────────────────────────────────────────────────────────────
    ('catalog',      'كتالوج الأدوية'),
    ('stockcount',   'الجرد الفعلي'),
    ('shortage',     'النواقص'),
    # ── Purchasing & Finance ──────────────────────────────────────────────────
    ('purchasing',   'ذكاء المشتريات'),
    ('invoices',     'فواتير الموردين'),
    ('incentives',   'الحوافز'),
    ('cheques',      'تخطيط الشيكات'),
    ('finance',      'الذكاء المالي'),
    # ── Call Center ───────────────────────────────────────────────────────────
    ('callcenter',   'مركز الاتصال'),
    # ── Human Resources ───────────────────────────────────────────────────────
    ('hr',           'الموارد البشرية'),
    ('approvals',    'صندوق الموافقات'),
    # ── Analytics & Reporting ─────────────────────────────────────────────────
    ('analytics',    'التحليلات والتقارير'),
    # ── System & Admin ────────────────────────────────────────────────────────
    ('dashboard',    'لوحة المتابعة'),
    ('audit',        'المراجعة والأمان'),
    ('sync',         'مزامنة البيانات'),
    ('settings',     'الإعدادات'),
    ('users',        'إدارة المستخدمين'),
    ('admin',        'إدارة النظام'),
]

ACTION_CHOICES = [
    ('view',     'عرض'),
    ('create',   'إنشاء'),
    ('edit',     'تعديل'),
    ('delete',   'حذف'),
    ('approve',  'اعتماد'),
    ('export',   'تصدير'),
    ('assign',   'تعيين'),
    ('finalize', 'إغلاق / إنهاء'),
]

USER_ACTIVITY_ACTION_CHOICES = [
    ('login_success',       'دخول ناجح'),
    ('login_failed',        'محاولة دخول فاشلة'),
    ('password_changed',    'تغيير كلمة المرور'),
    ('password_reset',      'إعادة تعيين كلمة المرور بواسطة المدير'),
    ('role_changed',        'تغيير الدور'),
    ('branch_changed',      'تغيير الفرع'),
    ('activated',           'تفعيل الحساب'),
    ('deactivated',         'تعطيل الحساب'),
    ('permissions_changed', 'تغيير الصلاحيات'),
    ('created',             'إنشاء المستخدم'),
    ('mfa_enabled',         'تفعيل المصادقة الثنائية'),
    ('mfa_disabled',        'إيقاف المصادقة الثنائية'),
    ('mfa_verified',        'اجتياز المصادقة الثنائية'),
    ('mfa_failed',          'فشل المصادقة الثنائية'),
]

# Roles that must pass 2FA at login once enforcement is switched on
# (config SystemSetting key 'security.mfa_enforced'). These are the approval-
# and pricing-capable roles reachable from outside the pharmacy network.
MFA_REQUIRED_ROLES = frozenset({'admin', 'supervisor', 'purchasing'})


class ERPUser(models.Model):
    """
    Local cache of SOFTECH ERP user records.
    Populated by the sync management command.
    Used to validate that a username exists in SOFTECH before creating a local account.
    """
    username    = models.CharField(max_length=50, unique=True, db_index=True, verbose_name='اسم المستخدم')
    user_id     = models.CharField(max_length=50, blank=True, db_index=True, verbose_name='رقم المستخدم في ERP')
    full_name   = models.CharField(max_length=150, blank=True, verbose_name='الاسم الكامل')
    branch_code = models.CharField(max_length=20, blank=True, verbose_name='كود الفرع')
    user_group  = models.CharField(max_length=50, blank=True, default='', verbose_name='مجموعة المستخدم')
    is_active   = models.BooleanField(default=True, verbose_name='نشط')
    synced_at   = models.DateTimeField(auto_now=True, verbose_name='آخر مزامنة')

    class Meta:
        verbose_name = 'مستخدم ERP'
        verbose_name_plural = 'مستخدمو ERP'
        ordering = ['username']

    def __str__(self):
        return f'{self.username} ({self.full_name})'


class StaffProfile(models.Model):
    user = models.OneToOneField(
        'auth.User', on_delete=models.CASCADE, related_name='staff_profile'
    )
    # Primary branch (kept for backward-compat + default scoping)
    branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True, on_delete=models.SET_NULL,
        verbose_name='الفرع الأساسي'
    )
    # Link to SOFTECH ERP user record
    erp_user = models.OneToOneField(
        ERPUser, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='staff_profile', verbose_name='مستخدم ERP'
    )
    softech_username = models.CharField(max_length=50, blank=True, verbose_name='اسم المستخدم في SOFTECH')
    softech_user_id  = models.CharField(max_length=50, blank=True, db_index=True, verbose_name='رقم المستخدم في SOFTECH')
    # HR employee code (كود الموارد البشرية) — the HR department's own code,
    # distinct from the SOFTECH user id. Unique among non-empty values.
    hr_code  = models.CharField(max_length=30, blank=True, default='', db_index=True, verbose_name='كود الموارد البشرية')
    role     = models.CharField(max_length=20, choices=ROLE_CHOICES, default='salesperson', verbose_name='الدور')
    phone    = models.CharField(max_length=20, blank=True, verbose_name='الهاتف')
    is_active = models.BooleanField(default=True, verbose_name='نشط')

    # Opt-in: also push the weekly near-expiry worklist to this manager on WhatsApp
    # (in addition to the in-app notification). Requires `phone` set + the feature
    # flag `expiry_worklist_whatsapp_enabled`. Off by default (outward messaging).
    notify_expiry_worklist_wa = models.BooleanField(
        default=False, verbose_name='إشعار قائمة الصلاحيات عبر واتساب',
    )

    # Branch access flags
    access_all_branches = models.BooleanField(
        default=False,
        verbose_name='وصول شامل لجميع الفروع',
        help_text='يتجاوز قيود الفرع بغض النظر عن الدور',
    )
    # Extra branches granted beyond the primary branch (via UserBranchAccess)
    allowed_branches = models.ManyToManyField(
        'branches.Branch',
        blank=True,
        related_name='staff_allowed',
        verbose_name='فروع إضافية مسموح بها',
    )
    restricted_branches = models.ManyToManyField(
        'branches.Branch',
        blank=True,
        related_name='staff_restricted',
        verbose_name='فروع محظورة',
    )

    # ── Notification preferences ───────────────────────────────────────────────
    enable_notifications = models.BooleanField(
        default=True, verbose_name='تفعيل الإشعارات',
    )
    enable_sound = models.BooleanField(
        default=True, verbose_name='تفعيل الصوت',
    )
    enable_browser_push = models.BooleanField(
        default=False, verbose_name='إشعارات المتصفح',
    )
    # Personal per-category mute (on top of role-level notifier visibility).
    # A list of notification category keys this user has hidden for themselves.
    muted_notification_categories = models.JSONField(
        default=list, blank=True, verbose_name='فئات إشعارات مكتومة',
    )

    # Customer data visibility
    can_see_all_customers = models.BooleanField(
        default=False,
        verbose_name='يرى جميع العملاء',
        help_text='يسمح له برؤية عملاء الفروع الأخرى',
    )
    can_see_customer_phone = models.BooleanField(
        default=True,
        verbose_name='يرى رقم هاتف العميل',
    )

    # Grants the right to WRITE the SOFTECH document remarks field
    # (stktransm.comments) from the personal dashboard. This is an ERP write —
    # admins always have it; other users only if explicitly granted.
    can_edit_erp_comments = models.BooleanField(
        default=False,
        verbose_name='تعديل ملاحظات مستندات SOFTECH',
        help_text='يسمح بالكتابة في حقل الملاحظات على مستندات SOFTECH (كتابة فعلية للـ ERP)',
    )

    # ── Two-factor authentication (TOTP) ──────────────────────────────────────
    # Approval-capable roles (see MFA_REQUIRED_ROLES) must pass a TOTP check at
    # login once enforcement is switched on. `mfa_secret` holds the base32 shared
    # secret; `mfa_backup_codes` holds *hashed* one-time recovery codes.
    mfa_enabled      = models.BooleanField(default=False, verbose_name='المصادقة الثنائية مفعّلة')
    mfa_secret       = models.CharField(max_length=64, blank=True, default='', verbose_name='سر TOTP')
    mfa_backup_codes = models.JSONField(default=list, blank=True, verbose_name='رموز الاسترجاع (مجزّأة)')
    mfa_confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ تفعيل المصادقة الثنائية')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')

    class Meta:
        verbose_name = 'ملف الموظف'
        verbose_name_plural = 'ملفات الموظفين'
        constraints = [
            models.UniqueConstraint(
                fields=['hr_code'],
                condition=~models.Q(hr_code=''),
                name='uniq_staffprofile_hr_code_nonblank',
            ),
        ]

    def __str__(self):
        return f"{self.full_name} — {self.get_role_display()}"

    @property
    def full_name(self):
        # Prefer the real name; many staff have no first/last set but DO have a
        # human SOFTECH username (e.g. "Aya Samy"), which beats the numeric login.
        return (
            self.user.get_full_name()
            or (self.softech_username or '').strip()
            or self.user.username
        )

    @property
    def branch_name(self):
        if self.branch:
            return self.branch.name_ar or self.branch.name
        if self.role in ('admin', 'call_center', 'purchasing'):
            return 'المركز الرئيسي'
        return ''

    @property
    def can_see_all_branches(self):
        if self.access_all_branches:
            return True
        return self.role in ('admin', 'call_center', 'purchasing')

    # Backward-compat alias
    @property
    def has_global_access(self):
        return self.access_all_branches

    @property
    def accessible_branch_ids(self):
        """Return set of branch PKs this user may access, or None for all."""
        if self.can_see_all_branches:
            return None  # None signals "unrestricted"
        ids = set(self.extra_branches.values_list('branch_id', flat=True))
        if self.branch_id:
            ids.add(self.branch_id)
        return ids

    @property
    def is_call_center(self):
        return self.role == 'call_center'

    @property
    def is_admin(self):
        return self.role == 'admin'

    def can_do(self, module: str, action: str) -> bool:
        """
        Check whether this user's role has a RoleModuleAccess entry granting
        the given action on the given module.
        Falls back to True for admins if no entries exist yet (safe default during migration).
        """
        if self.role == 'admin':
            return True
        return RoleModuleAccess.objects.filter(
            role=self.role, module=module, action=action, is_allowed=True
        ).exists()


class UserActivityLog(models.Model):
    """Audit trail for all user management and authentication events."""
    target_user = models.ForeignKey(
        StaffProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='user_activity_logs', verbose_name='المستخدم المستهدف'
    )
    changed_by = models.ForeignKey(
        StaffProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='user_audit_actions', verbose_name='بواسطة'
    )
    action     = models.CharField(max_length=30, choices=USER_ACTIVITY_ACTION_CHOICES, verbose_name='الإجراء')
    old_value  = models.JSONField(null=True, blank=True, verbose_name='القيمة القديمة')
    new_value  = models.JSONField(null=True, blank=True, verbose_name='القيمة الجديدة')
    note       = models.TextField(blank=True, verbose_name='ملاحظة')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='عنوان IP')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت الحدث', db_index=True)

    class Meta:
        verbose_name = 'سجل نشاط المستخدم'
        verbose_name_plural = 'سجلات نشاط المستخدمين'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_action_display()} — {self.target_user} — {self.created_at:%Y-%m-%d %H:%M}'


class UserBranchAccess(models.Model):
    """Many-to-many: a user may be explicitly granted access to additional branches."""
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name='extra_branches'
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE, related_name='extra_staff_access'
    )
    granted_by = models.ForeignKey(
        StaffProfile, on_delete=models.SET_NULL, null=True,
        related_name='granted_branch_access'
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('staff', 'branch')
        verbose_name = 'وصول إضافي للفرع'
        verbose_name_plural = 'وصول إضافي للفروع'

    def __str__(self):
        return f'{self.staff.full_name} → {self.branch}'


class RoleModuleAccess(models.Model):
    """
    Dynamic RBAC: per-role, per-module, per-action grant.
    Admins manage these rows through the admin UI.
    When a role has NO entries for a module, access defaults to DENIED
    (except for admins, which bypass this table entirely).
    """
    role   = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    module = models.CharField(max_length=30, choices=MODULE_CHOICES, db_index=True)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)  # max 'finalize' = 8 chars
    is_allowed = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        StaffProfile, on_delete=models.SET_NULL, null=True, blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('role', 'module', 'action')
        verbose_name = 'صلاحية دور'
        verbose_name_plural = 'صلاحيات الأدوار'
        ordering = ['role', 'module', 'action']

    def __str__(self):
        allowed = '✅' if self.is_allowed else '❌'
        return f'{allowed} {self.get_role_display()} | {self.get_module_display()} | {self.get_action_display()}'


# ════════════════════════════════════════════════════════════════════════════
# SOFTECH permission mirror (Stage A — read-only reference data)
#
# Mirrors the SOFTECH authorization model so Django can later DERIVE effective
# module permissions from each user's ERP group:
#   usergroups → ErpUserGroup
#   mitems     → ErpScreen          (528 screens / functions, grouped by system)
#   mglevels   → ErpGroupPermission (group × screen × 12 action flags)
# Synced by apps/sync (sync_erp_permissions) — never written by the app.
# ════════════════════════════════════════════════════════════════════════════

class ErpUserGroup(models.Model):
    """SOFTECH usergroups — the user types (Administrator, Accountant, …)."""
    usergroup  = models.IntegerField(unique=True, db_index=True, verbose_name='كود المجموعة')
    name       = models.CharField(max_length=60, blank=True, verbose_name='اسم المجموعة')
    is_blocked = models.BooleanField(default=False, verbose_name='محظورة')
    synced_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['usergroup']
        verbose_name = 'مجموعة مستخدمي ERP'
        verbose_name_plural = 'مجموعات مستخدمي ERP'

    def __str__(self):
        return f'{self.usergroup} — {self.name}'


class ErpScreen(models.Model):
    """SOFTECH mitems — catalog of screens/functions grouped into systems."""
    mitemname  = models.CharField(max_length=20, unique=True, db_index=True, verbose_name='كود الشاشة')
    descr_ar   = models.CharField(max_length=120, blank=True, verbose_name='الوصف')
    descr_en   = models.CharField(max_length=120, blank=True, verbose_name='Description')
    system     = models.CharField(max_length=4, blank=True, db_index=True, verbose_name='النظام')
    subsystem  = models.CharField(max_length=20, blank=True, verbose_name='النظام الفرعي')
    item_order = models.IntegerField(default=0)
    synced_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['system', 'subsystem', 'item_order', 'mitemname']
        verbose_name = 'شاشة ERP'
        verbose_name_plural = 'شاشات ERP'

    def __str__(self):
        return f'[{self.system}] {self.mitemname} — {self.descr_en or self.descr_ar}'


class ErpGroupPermission(models.Model):
    """
    SOFTECH mglevels — per (group × screen) action grants. Each flag is a
    distinct SOFTECH capability on that screen for that group.
    """
    group        = models.ForeignKey(ErpUserGroup, on_delete=models.CASCADE,
                                      related_name='permissions', verbose_name='المجموعة')
    mitemname    = models.CharField(max_length=20, db_index=True, verbose_name='كود الشاشة')

    can_enable   = models.BooleanField(default=False)  # mitemenable — accessible at all
    can_show     = models.BooleanField(default=False)  # mitemshow   — visible in menu
    can_retrieve = models.BooleanField(default=False)  # mitemretrieve — view / query
    can_save     = models.BooleanField(default=False)  # mitemsave   — create / edit
    can_datain   = models.BooleanField(default=False)  # mitemdatain — data entry
    can_print    = models.BooleanField(default=False)  # mitemprint
    can_scan     = models.BooleanField(default=False)  # mitemscan
    can_data     = models.BooleanField(default=False)  # mitemdata
    can_money    = models.BooleanField(default=False)  # mitemmoney  — see/handle money
    can_cost     = models.BooleanField(default=False)  # mitemcost   — see cost prices
    can_brmb     = models.BooleanField(default=False)  # mitembrmb   — branch/multi-branch
    can_scanedit = models.BooleanField(default=False)  # mitemscanedit
    synced_at    = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('group', 'mitemname')
        indexes = [models.Index(fields=['group', 'mitemname'])]
        verbose_name = 'صلاحية مجموعة ERP'
        verbose_name_plural = 'صلاحيات مجموعات ERP'

    def __str__(self):
        return f'G{self.group_id}·{self.mitemname}'


# ════════════════════════════════════════════════════════════════════════════
# SOFTECH permission INHERITANCE (Stages B–D)
#
# Bundle chosen by the business:
#   • SOFTECH is the source of truth — derived nightly; Django overrides reset.
#   • Smart flag→action: retrieve/show→view, save→edit+create, print→export,
#     money/cost→a "see financial fields" gate.
#   • Collapse to 6 actions (+ see_cost).
#   • Native modules (reservations, demand, pricing-approvals, analytics) stay
#     governed by Django role and are NOT mapped here.
# ════════════════════════════════════════════════════════════════════════════

class SoftechSystemMap(models.Model):
    """
    Maps a SOFTECH system (mitems.mitemsys) to a platform module. A platform
    module may be fed by several SOFTECH systems (e.g. customers ⇐ AR + …).
    Seeded with defaults, editable by admins.
    """
    system        = models.CharField(max_length=4, db_index=True, verbose_name='نظام Softech')
    django_module = models.CharField(max_length=40, db_index=True, verbose_name='وحدة المنصة')
    note          = models.CharField(max_length=120, blank=True)
    is_active     = models.BooleanField(default=True)

    class Meta:
        unique_together = ('system', 'django_module')
        ordering = ['django_module', 'system']
        verbose_name = 'ربط نظام Softech بوحدة'
        verbose_name_plural = 'ربط أنظمة Softech بالوحدات'

    def __str__(self):
        return f'{self.system} → {self.django_module}'


class ErpGroupModulePermission(models.Model):
    """
    DERIVED: effective platform permissions for a SOFTECH user group on a module,
    computed by aggregating ErpGroupPermission over the screens of the mapped
    SOFTECH systems. Rebuilt nightly (SOFTECH authoritative).
    """
    group       = models.ForeignKey(ErpUserGroup, on_delete=models.CASCADE,
                                     related_name='module_permissions')
    module      = models.CharField(max_length=40, db_index=True)
    can_view    = models.BooleanField(default=False)
    can_create  = models.BooleanField(default=False)
    can_edit    = models.BooleanField(default=False)
    can_delete  = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    can_export  = models.BooleanField(default=False)
    can_see_cost = models.BooleanField(default=False)   # money/cost financial gate
    screens_count = models.PositiveIntegerField(default=0)  # how many screens fed this
    derived_at  = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('group', 'module')
        ordering = ['group', 'module']
        verbose_name = 'صلاحية وحدة مشتقّة'
        verbose_name_plural = 'صلاحيات الوحدات المشتقّة'

    def __str__(self):
        return f'G{self.group_id}·{self.module}'
