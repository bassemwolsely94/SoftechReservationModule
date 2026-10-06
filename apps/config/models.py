from django.db import models


class SystemSetting(models.Model):
    """
    Global key-value store for platform-wide configuration.
    e.g.  pharmacy_name, default_sync_interval, max_reservation_qty …
    """
    TYPES = [
        ('string',  'نص'),
        ('integer', 'رقم صحيح'),
        ('decimal', 'رقم عشري'),
        ('boolean', 'نعم / لا'),
        ('json',    'JSON'),
    ]

    CATEGORIES = [
        ('general',       'عام'),
        ('reservations',  'الحجوزات'),
        ('transfers',     'طلبات التحويل'),
        ('notifications', 'الإشعارات'),
        ('sync',          'المزامنة'),
        ('vouchers',      'القسائم'),
    ]

    key         = models.CharField(max_length=100, unique=True, verbose_name='المفتاح')
    label       = models.CharField(max_length=200, verbose_name='التسمية')
    description = models.TextField(blank=True, verbose_name='الوصف')
    value       = models.TextField(blank=True, verbose_name='القيمة')
    value_type  = models.CharField(max_length=10, choices=TYPES, default='string', verbose_name='النوع')
    category    = models.CharField(max_length=30, choices=CATEGORIES, default='general', verbose_name='الفئة')
    is_public   = models.BooleanField(default=False, verbose_name='متاح للقراءة العامة')
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'إعداد النظام'
        verbose_name_plural = 'إعدادات النظام'
        ordering            = ['category', 'key']

    def __str__(self):
        return f'{self.key} = {self.value}'

    # ── helper ────────────────────────────────────────────────────────────────
    @classmethod
    def get(cls, key, default=None):
        """
        Fetch a setting's typed value by key, or `default` if missing/unparsable.

        NOTE: several callers (e.g. apps/transits) already call
        SystemSetting.get(...) inside try/except — before this method existed
        those calls raised AttributeError and silently used their defaults.
        """
        row = cls.objects.filter(key=key).only('value', 'value_type').first()
        if row is None:
            return default
        val = row.typed_value()
        return default if val is None else val

    def typed_value(self):
        """Return value cast to the declared type."""
        if self.value_type == 'integer':
            try:
                return int(self.value)
            except (ValueError, TypeError):
                return 0
        if self.value_type == 'decimal':
            try:
                return float(self.value)
            except (ValueError, TypeError):
                return 0.0
        if self.value_type == 'boolean':
            return self.value.lower() in ('true', '1', 'yes')
        if self.value_type == 'json':
            import json
            try:
                return json.loads(self.value)
            except Exception:
                return None
        return self.value   # string


class DropdownOption(models.Model):
    """
    Configurable dropdown options shown throughout the platform.
    e.g.  dropdown_key='reservation_channel' → [pickup, home_delivery, …]
    """
    dropdown_key = models.CharField(max_length=100, verbose_name='مفتاح القائمة',
                                    db_index=True)
    label        = models.CharField(max_length=200, verbose_name='التسمية العربية')
    label_en     = models.CharField(max_length=200, blank=True, verbose_name='التسمية الإنجليزية')
    value        = models.CharField(max_length=100, verbose_name='القيمة')
    icon         = models.CharField(max_length=10, blank=True, verbose_name='أيقونة')
    color        = models.CharField(max_length=30, blank=True, verbose_name='لون (Tailwind class)')
    order        = models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')
    is_active    = models.BooleanField(default=True, verbose_name='مفعّل')
    is_system    = models.BooleanField(default=False,
                                       verbose_name='ثابت (لا يمكن حذفه)')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'خيار القائمة'
        verbose_name_plural = 'خيارات القوائم'
        ordering            = ['dropdown_key', 'order', 'label']
        unique_together     = [('dropdown_key', 'value')]

    def __str__(self):
        return f'[{self.dropdown_key}] {self.label} ({self.value})'


class PharmacyProfile(models.Model):
    """
    Singleton model (pk=1) — pharmacy chain contact details.
    Used in printed receipts, WhatsApp messages, and customer-facing footers.
    """
    name_ar             = models.CharField(max_length=200, default='صيدليات الرزيقي',
                                           verbose_name='الاسم بالعربية')
    name_en             = models.CharField(max_length=200, default='ElRezeiky Pharmacies',
                                           verbose_name='الاسم بالإنجليزية')
    tagline_ar          = models.CharField(max_length=300, blank=True,
                                           verbose_name='الشعار / التعريف')
    website             = models.CharField(max_length=200, blank=True,
                                           verbose_name='الموقع الإلكتروني')
    whatsapp_number     = models.CharField(max_length=30, blank=True,
                                           verbose_name='رقم واتساب الرئيسي',
                                           help_text='بدون + (مثل: 201055000468)')
    call_center_numbers = models.TextField(blank=True,
                                           verbose_name='أرقام الاتصال',
                                           help_text='كل رقم في سطر منفصل')
    extra_footer_ar     = models.TextField(blank=True,
                                           verbose_name='نص تذييل إضافي')
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'ملف الصيدلية'
        verbose_name_plural = 'ملف الصيدلية'

    def __str__(self):
        return self.name_ar

    # ── singleton accessor ────────────────────────────────────────────────────
    @classmethod
    def get(cls):
        """Return the singleton profile, creating it with defaults if absent."""
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            'name_ar':             'صيدليات الرزيقي',
            'name_en':             'ElRezeiky Pharmacies',
            'tagline_ar':          'نحن هنا لخدمتكم',
            'website':             '',
            'whatsapp_number':     '201055000468',
            'call_center_numbers': '01055000468',
            'extra_footer_ar':     '',
        })
        return obj

    def call_center_list(self):
        """Return a clean list of call center numbers (newline-separated)."""
        return [n.strip() for n in self.call_center_numbers.splitlines() if n.strip()]
