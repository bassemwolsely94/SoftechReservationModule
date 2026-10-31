"""
apps/trace/models.py

EDA track-and-trace foundation (P-58, docs/product-review/06_SPEC_P-58) — DORMANT
until settings.TRACK_TRACE_ENABLED. Captures pack identity (GS1 DataMatrix) on
receive and sale; reports nothing to EDA yet (guideline 804/2025 not read). Nothing
here touches SOFTECH.
"""
from django.db import models


class PackCode(models.Model):
    """One serialised pack: unique on (gtin, serial)."""
    STATUS_CHOICES = [
        ('received', 'مستلمة'), ('in_stock', 'في المخزون'), ('sold', 'مباعة'),
        ('returned', 'مرتجعة'), ('destroyed', 'معدومة'), ('unknown', 'غير معروفة'),
    ]
    gtin   = models.CharField(max_length=14, db_index=True)
    serial = models.CharField(max_length=20)
    batch  = models.CharField(max_length=20, blank=True)
    expiry = models.DateField(null=True, blank=True)
    item   = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='pack_codes')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='unknown')
    branch = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='+')
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['gtin', 'serial'], name='uniq_pack_gtin_serial')]
        verbose_name = 'عبوة مسلسلة'
        verbose_name_plural = 'العبوات المسلسلة'

    def __str__(self):
        return f'{self.gtin}/{self.serial} {self.status}'


class PackEvent(models.Model):
    """Append-only history of a pack (Rule 8). Never edited or deleted."""
    EVENT_CHOICES = [
        ('receive', 'استلام'), ('sell', 'بيع'), ('return_in', 'مرتجع عميل'),
        ('return_to_supplier', 'مرتجع لمورد'), ('destroy', 'إعدام'),
        ('transfer_out', 'تحويل صادر'), ('transfer_in', 'تحويل وارد'),
    ]
    pack    = models.ForeignKey(PackCode, on_delete=models.PROTECT, related_name='events')
    event   = models.CharField(max_length=20, choices=EVENT_CHOICES)
    doc_type = models.CharField(max_length=30, blank=True)     # invoice_line | pos_order_line | …
    doc_ref  = models.CharField(max_length=60, blank=True)
    branch  = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+')
    staff   = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+')
    at      = models.DateTimeField(auto_now_add=True, db_index=True)
    source  = models.CharField(max_length=10, choices=[('scan', 'مسح'), ('manual', 'يدوي')], default='scan')
    raw     = models.CharField(max_length=200, blank=True)
    # e.g. 'duplicate_receive' — the same serial received twice: flagged, never duplicated
    flag    = models.CharField(max_length=30, blank=True, db_index=True)
    # Reserved for EDA reporting once guideline 804/2025 is read — unused today.
    reported_to_eda_at = models.DateTimeField(null=True, blank=True)
    eda_response       = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['at', 'id']
        verbose_name = 'حركة عبوة'
        verbose_name_plural = 'حركات العبوات'

    def __str__(self):
        return f'{self.pack_id} {self.event} {self.at:%Y-%m-%d}'
