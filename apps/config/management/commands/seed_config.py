"""
python manage.py seed_config

Seeds default SystemSettings and DropdownOptions.
Safe to re-run — uses get_or_create so existing values are preserved.
"""
from django.core.management.base import BaseCommand
from apps.config.models import SystemSetting, DropdownOption


DEFAULT_SETTINGS = [
    # ── General ──────────────────────────────────────────────────────────────
    dict(key='pharmacy_name',         label='اسم الصيدلية',           value='صيدليات الرزيقي',    value_type='string',  category='general',       is_public=True),
    dict(key='support_phone',         label='رقم الدعم الفني',         value='',                  value_type='string',  category='general',       is_public=True),
    dict(key='default_currency',      label='العملة الافتراضية',       value='ج.م',               value_type='string',  category='general',       is_public=True),
    dict(key='items_per_page',        label='عدد السجلات في الصفحة',   value='25',                value_type='integer', category='general',       is_public=False),
    # ── Reservations ─────────────────────────────────────────────────────────
    dict(key='max_reservation_qty',   label='الحد الأقصى لكمية الحجز', value='100',               value_type='integer', category='reservations',  is_public=False),
    dict(key='auto_follow_up_days',   label='المتابعة التلقائية (أيام)', value='3',               value_type='integer', category='reservations',  is_public=False),
    dict(key='reservation_expiry_days',label='انتهاء الحجز (أيام)',     value='30',               value_type='integer', category='reservations',  is_public=False),
    # ── Transfers ─────────────────────────────────────────────────────────────
    dict(key='transfer_auto_approve', label='موافقة تلقائية على التحويل', value='false',          value_type='boolean', category='transfers',     is_public=False),
    dict(key='transfer_require_erp',  label='مطلوب مرجع ERP',          value='true',              value_type='boolean', category='transfers',     is_public=False),
    # ── Notifications ─────────────────────────────────────────────────────────
    dict(key='notify_on_new_reservation', label='إشعار عند حجز جديد', value='true',              value_type='boolean', category='notifications',  is_public=False),
    dict(key='notify_on_transfer_approved', label='إشعار عند موافقة التحويل', value='true',       value_type='boolean', category='notifications',  is_public=False),
    # ── Sync ─────────────────────────────────────────────────────────────────
    dict(key='sync_interval_minutes', label='دورة المزامنة (دقائق)',    value='60',               value_type='integer', category='sync',          is_public=False),
    dict(key='sync_batch_size',       label='حجم دفعة المزامنة',        value='5000',             value_type='integer', category='sync',          is_public=False),
    # ── Vouchers ─────────────────────────────────────────────────────────────
    dict(key='voucher_otp_expiry_minutes', label='انتهاء رمز OTP (دقائق)', value='3',            value_type='integer', category='vouchers',       is_public=False),
    dict(key='voucher_otp_length',    label='طول رمز OTP',              value='6',                value_type='integer', category='vouchers',       is_public=False),
]

DEFAULT_DROPDOWNS = [
    # reservation_channel
    dict(dropdown_key='reservation_channel', label='استلام من الفرع',  label_en='Pickup',        value='pickup',        icon='🏪', order=0, is_system=True),
    dict(dropdown_key='reservation_channel', label='توصيل للمنزل',     label_en='Home Delivery', value='home_delivery', icon='🚚', order=1, is_system=True),
    dict(dropdown_key='reservation_channel', label='تأمين',            label_en='Insurance',     value='insurance',     icon='🏥', order=2, is_system=True),
    dict(dropdown_key='reservation_channel', label='استفسار',          label_en='Inquiry',       value='inquiry',       icon='❓', order=3, is_system=True),
    # reservation_priority
    dict(dropdown_key='reservation_priority', label='عادي',            label_en='Normal',        value='normal',        icon='⚪', color='gray',   order=0, is_system=True),
    dict(dropdown_key='reservation_priority', label='مهم',             label_en='High',          value='high',          icon='🟡', color='yellow', order=1, is_system=True),
    dict(dropdown_key='reservation_priority', label='عاجل',            label_en='Urgent',        value='urgent',        icon='🔴', color='red',    order=2, is_system=True),
    # transfer_status (display labels only)
    dict(dropdown_key='transfer_status', label='مسودة',                label_en='Draft',         value='draft',         icon='📝', color='gray',   order=0, is_system=True),
    dict(dropdown_key='transfer_status', label='مُرسَل',               label_en='Submitted',     value='submitted',     icon='📤', color='blue',   order=1, is_system=True),
    dict(dropdown_key='transfer_status', label='موافق عليه',           label_en='Approved',      value='approved',      icon='✅', color='green',  order=2, is_system=True),
    dict(dropdown_key='transfer_status', label='مرفوض',                label_en='Rejected',      value='rejected',      icon='❌', color='red',    order=3, is_system=True),
    dict(dropdown_key='transfer_status', label='مكتمل',                label_en='Completed',     value='completed',     icon='🏁', color='teal',   order=4, is_system=True),
]


class Command(BaseCommand):
    help = 'Seed default system settings and dropdown options'

    def handle(self, *args, **options):
        created_s = 0
        for defaults in DEFAULT_SETTINGS:
            key = defaults.pop('key')
            _, created = SystemSetting.objects.get_or_create(key=key, defaults=defaults)
            if created:
                created_s += 1

        created_d = 0
        for defaults in DEFAULT_DROPDOWNS:
            key   = defaults.pop('dropdown_key')
            value = defaults.pop('value')
            _, created = DropdownOption.objects.get_or_create(
                dropdown_key=key, value=value, defaults=defaults
            )
            if created:
                created_d += 1

        self.stdout.write(self.style.SUCCESS(
            f'seed_config: {created_s} settings created, {created_d} dropdown options created. '
            'Existing values were preserved.'
        ))
