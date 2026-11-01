import ipaddress
import uuid

from django.core.exceptions import ValidationError
from django.db import models


class TrustedNetwork(models.Model):
    """A network we recognise (branch LAN, staff VPN, server). Log-only in N1: it names the
    site a request came from; nothing is refused because of it."""

    KIND_CHOICES = [
        ('branch_lan', 'شبكة فرع'),
        ('staff_vpn', 'VPN الموظفين'),
        ('server', 'سيرفر'),
    ]

    name = models.CharField('الاسم', max_length=120)
    cidr = models.CharField('نطاق الشبكة (CIDR)', max_length=43, unique=True)
    kind = models.CharField('النوع', max_length=20, choices=KIND_CHOICES)
    branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True, on_delete=models.PROTECT,
        related_name='trusted_networks', verbose_name='الفرع',
    )
    is_active = models.BooleanField('مفعّل', default=True)
    notes = models.TextField('ملاحظات', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='آخر تعديل بواسطة',
    )

    class Meta:
        verbose_name = 'شبكة موثوقة'
        verbose_name_plural = 'الشبكات الموثوقة'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.cidr})'

    def normalise_cidr(self):
        """Store the network address (192.168.3.7/24 -> 192.168.3.0/24); ValidationError if not a CIDR."""
        try:
            self.cidr = str(ipaddress.ip_network((self.cidr or '').strip(), strict=False))
        except ValueError:
            raise ValidationError({'cidr': 'نطاق الشبكة غير صحيح (مثال: 192.168.3.0/24)'})

    def clean(self):
        self.normalise_cidr()

    # NOTE: only save() normalises the CIDR. QuerySet.update() and bulk_create() bypass it, so
    # never use them on this model (a non-normalised value would defeat the unique check).
    def save(self, *args, **kwargs):
        # the API, the seed command and the shell all store the same normalised form
        self.normalise_cidr()
        super().save(*args, **kwargs)


class Device(models.Model):
    """A browser/device that has signed in (N2). Identified by an httpOnly cookie whose value is
    never stored - only its sha256. Pending/unknown devices are never refused in N2; only
    blocked/retired ones are."""

    KIND_CHOICES = [
        ('branch_pc', 'جهاز فرع'),
        ('personal_laptop', 'لابتوب شخصي'),
        ('phone', 'موبايل'),
        ('rider_phone', 'موبايل طيار'),
        ('kiosk', 'كشك'),
    ]
    STATUS_CHOICES = [
        ('pending', 'بانتظار الاعتماد'),
        ('approved', 'معتمد'),
        ('blocked', 'محظور'),
        ('retired', 'متقاعد'),
    ]

    public_id = models.UUIDField('المعرّف', default=uuid.uuid4, unique=True, editable=False)
    secret_hash = models.CharField(max_length=64, unique=True, editable=False)
    name = models.CharField('الاسم', max_length=120, blank=True)
    kind = models.CharField('النوع', max_length=20, choices=KIND_CHOICES, default='personal_laptop')
    status = models.CharField('الحالة', max_length=10, choices=STATUS_CHOICES, default='pending', db_index=True)
    branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True, on_delete=models.PROTECT,
        related_name='devices', verbose_name='الفرع',
    )
    owner = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='owned_devices', verbose_name='المالك',
    )
    allowed_roles = models.JSONField('الأدوار المسموحة', default=list, blank=True)  # stored only; enforced in N3
    first_ip = models.GenericIPAddressField('أول IP', null=True, blank=True)
    last_ip = models.GenericIPAddressField('آخر IP', null=True, blank=True)
    first_network = models.CharField(max_length=10, blank=True, verbose_name='أول شبكة')
    last_network = models.CharField(max_length=10, blank=True, verbose_name='آخر شبكة')
    last_site = models.CharField(max_length=120, blank=True, verbose_name='آخر موقع')
    user_agent = models.CharField('المتصفح', max_length=300, blank=True)
    first_seen = models.DateTimeField('أول ظهور', auto_now_add=True)
    last_seen = models.DateTimeField('آخر ظهور', null=True, blank=True)
    approved_by = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='اعتمد بواسطة',
    )
    approved_at = models.DateTimeField('وقت الاعتماد', null=True, blank=True)
    status_note = models.CharField('ملاحظة الحالة', max_length=200, blank=True)
    updated_by = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='آخر تعديل بواسطة',
    )

    class Meta:
        verbose_name = 'جهاز'
        verbose_name_plural = 'الأجهزة'
        ordering = ['status', '-first_seen']

    def __str__(self):
        return f'{self.name or self.public_id} ({self.status})'


class DeviceUser(models.Model):
    """Which staff have signed in on a device. A shared branch PC is ONE device, many rows."""

    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='device_users')
    user = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE, related_name='device_links')
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    mfa_remembered_at = models.DateTimeField(null=True, blank=True)
    mfa_remembered_epoch = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = [('device', 'user')]
