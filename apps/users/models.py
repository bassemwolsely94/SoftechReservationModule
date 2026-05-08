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
]

ACTION_CHOICES = [
    ('view',    'عرض'),
    ('create',  'إنشاء'),
    ('edit',    'تعديل'),
    ('delete',  'حذف'),
    ('approve', 'اعتماد'),
    ('export',  'تصدير'),
]


class StaffProfile(models.Model):
    user = models.OneToOneField(
        'auth.User', on_delete=models.CASCADE, related_name='staff_profile'
    )
    # Primary branch (kept for backward-compat + default scoping)
    branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True, on_delete=models.SET_NULL
    )
    softech_username = models.CharField(max_length=50, blank=True)
    softech_user_id  = models.CharField(max_length=50, blank=True)
    role     = models.CharField(max_length=20, choices=ROLE_CHOICES, default='salesperson')
    phone    = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    # Explicit global-access flag — overrides branch scoping without changing role
    has_global_access = models.BooleanField(
        default=False,
        verbose_name='وصول شامل لجميع الفروع',
        help_text='يتجاوز قيود الفرع بغض النظر عن الدور',
    )

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
    def branch_id(self):
        return self.branch_id if self.branch else None

    @property
    def can_see_all_branches(self):
        if self.has_global_access:
            return True
        return self.role in ('admin', 'call_center', 'purchasing')

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