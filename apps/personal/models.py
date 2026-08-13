"""
apps/personal/models.py — Personal Dashboard (doc: personalized "who am I in
SOFTECH" 360° view).

Two models:

  SoftechIdentityClaim — links one app staff user to ONE SOFTECH identity they
      play: as a supplier (personsdata.ptcode='20'), as a customer / employee-
      client (personsdata / localcustomers phcode), or as a salesperson / ERP
      author (SOFTECH usercode). Self-service *claim* → admin *approval*.

      SECURITY SPINE: a widget may only read SOFTECH data through an APPROVED
      claim owned by the requesting user. A raw personcode is NEVER accepted
      from the client for a data fetch — only a widget id / approved-claim id.

  PersonalWidget — one placed, configurable widget on a user's /me dashboard.
      Layout (column/position/size) + per-widget config (period, filters).

Everything downstream is SELECT-only reporting over SOFTECH — no writeback.
"""
from django.db import models


class SoftechIdentityClaim(models.Model):
    KIND_SUPPLIER    = 'supplier'
    KIND_CUSTOMER    = 'customer'
    KIND_SALESPERSON = 'salesperson'
    KIND_CHOICES = [
        (KIND_SUPPLIER,    'مورد'),
        (KIND_CUSTOMER,    'عميل / موظف'),
        (KIND_SALESPERSON, 'مسئول بيع / مستخدم ERP'),
    ]

    STATUS_PENDING  = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING,  'قيد المراجعة'),
        (STATUS_APPROVED, 'معتمد'),
        (STATUS_REJECTED, 'مرفوض'),
    ]

    staff = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='softech_identities', verbose_name='الموظف',
    )
    kind = models.CharField(
        max_length=15, choices=KIND_CHOICES, db_index=True,
        verbose_name='نوع الهوية',
    )
    # personcode (supplier/customer) OR usercode (salesperson). For a customer
    # this is the personsdata.personcode == phcode (e.g. "01HD14"); for a
    # supplier the numeric personcode; for a salesperson the SOFTECH usercode.
    person_code = models.CharField(
        max_length=40, db_index=True, verbose_name='كود SOFTECH',
    )
    label = models.CharField(max_length=200, blank=True, verbose_name='الاسم في SOFTECH')
    # cached context from personsdata (ptcode / ptclassifcode / branch …)
    meta = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING,
        db_index=True, verbose_name='الحالة',
    )
    note = models.CharField(max_length=300, blank=True, verbose_name='ملاحظة الطلب')

    reviewed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_identity_claims', verbose_name='روجع بواسطة',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True, verbose_name='ملاحظة المراجعة')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'هوية SOFTECH شخصية'
        verbose_name_plural = 'هويات SOFTECH الشخصية'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['staff', 'kind', 'person_code'],
                name='uniq_identity_staff_kind_code',
            ),
        ]

    def __str__(self):
        return f'{self.staff_id}:{self.kind}:{self.person_code} [{self.status}]'

    @property
    def is_approved(self):
        return self.status == self.STATUS_APPROVED


class PersonalWidget(models.Model):
    SIZE_CHOICES = [
        ('sm', 'صغير'), ('md', 'متوسط'), ('lg', 'كبير'), ('xl', 'كامل العرض'),
    ]

    staff = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='personal_widgets', verbose_name='الموظف',
    )
    # maps to a provider key in apps.personal.providers.WIDGET_REGISTRY
    widget_type = models.CharField(max_length=40, db_index=True, verbose_name='نوع اللوحة')
    # The identity this widget draws from. Nullable: salesperson-scoped widgets
    # (my_sales / my_narrative / my_analytics) fall back to the staff's own
    # softech_user_id when no identity is bound.
    identity = models.ForeignKey(
        SoftechIdentityClaim, on_delete=models.CASCADE, null=True, blank=True,
        related_name='widgets', verbose_name='الهوية',
    )
    title  = models.CharField(max_length=120, blank=True, verbose_name='العنوان')
    config = models.JSONField(default=dict, blank=True, verbose_name='الإعدادات')

    # layout
    position = models.PositiveIntegerField(default=0, verbose_name='الترتيب')
    column   = models.PositiveSmallIntegerField(default=0, verbose_name='العمود')
    size     = models.CharField(max_length=10, choices=SIZE_CHOICES, default='md')
    enabled  = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'لوحة شخصية'
        verbose_name_plural = 'اللوحات الشخصية'
        ordering = ['column', 'position', 'id']

    def __str__(self):
        return f'{self.staff_id}:{self.widget_type}#{self.pk}'
