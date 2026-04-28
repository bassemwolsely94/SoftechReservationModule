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


class StaffProfile(models.Model):
    user = models.OneToOneField(
        'auth.User', on_delete=models.CASCADE, related_name='staff_profile'
    )
    branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True, on_delete=models.SET_NULL
    )
    softech_username = models.CharField(max_length=50, blank=True)
    softech_user_id  = models.CharField(max_length=50, blank=True)
    role     = models.CharField(max_length=20, choices=ROLE_CHOICES, default='salesperson')
    phone    = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

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
        return self.role in ('admin', 'call_center', 'purchasing')

    @property
    def is_call_center(self):
        return self.role == 'call_center'

    @property
    def is_admin(self):
        return self.role == 'admin'