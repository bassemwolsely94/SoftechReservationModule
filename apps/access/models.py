import ipaddress

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
    cidr = models.CharField('نطاق الشبكة (CIDR)', max_length=43)
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

    def save(self, *args, **kwargs):
        # the API, the seed command and the shell all store the same normalised form
        self.normalise_cidr()
        super().save(*args, **kwargs)
