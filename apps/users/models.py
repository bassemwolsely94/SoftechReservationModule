from django.db import models
from django.contrib.auth.models import User


ROLE_CHOICES = [
    ('admin',       'Admin — Full Access'),
    ('call_center', 'Call Center — All Branches'),
    ('pharmacist',  'Pharmacist — Own Branch'),
    ('salesperson', 'Sales Person — Own Branch'),
    ('purchasing',  'Purchasing — HQ Only'),
    ('delivery',    'Delivery'),
    ('viewer',      'Viewer — Read Only'),
]

# Canonical module identifiers used by ModulePermission
MODULE_CHOICES = [
    ('reservations', 'الحجوزات'),
    ('demand',       'طلبات العملاء / المبيعات المفقودة'),
    ('transfers',    'طلبات التحويل'),
    ('customers',    'العملاء'),
    ('catalog',      'كتالوج الأدوية'),
    ('dashboard',    'لوحة المتابعة'),
    ('sync',         'مزامنة البيانات'),
    ('purchasing',   'لوحة المشتريات'),
    ('chronic',      'الأدوية المزمنة'),
    ('admin',        'إدارة النظام'),
    ('users',        'إدارة المستخدمين'),
]

ACTION_CHOICES = [
    ('view',    'عرض'),
    ('create',  'إنشاء'),
    ('edit',    'تعديل'),
    ('delete',  'حذف'),
    ('approve', 'اعتماد'),
    ('export',  'تصدير'),
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
]


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
    role     = models.CharField(max_length=20, choices=ROLE_CHOICES, default='salesperson', verbose_name='الدور')
    phone    = models.CharField(max_length=20, blank=True, verbose_name='الهاتف')
    is_active = models.BooleanField(default=True, verbose_name='نشط')

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

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')

    class Meta:
        verbose_name = 'ملف الموظف'
        verbose_name_plural = 'ملفات الموظفين'

    def __str__(self):
        return f"{self.full_name} — {self.get_role_display()}"

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

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
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
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
