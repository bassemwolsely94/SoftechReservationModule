"""
python manage.py seed_config

Seeds default SystemSettings and DropdownOptions.
Safe to re-run — uses get_or_create so existing values are preserved.
"""
from django.core.management.base import BaseCommand
from apps.config.models import SystemSetting, DropdownOption


DEFAULT_SETTINGS = [
    # ━━ Delivery geofencing ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='delivery_geofence_enabled', label='تفعيل التحقق الجغرافي للتوصيل',
         description='يلزم السائق بأن يكون داخل نطاق الفرع عند الاستلام وعند عنوان العميل عند التسليم',
         value='true', value_type='boolean', category='delivery', is_public=False),
    dict(key='delivery_pickup_radius_m',  label='نطاق الاستلام من الفرع (متر)',
         description='أقصى مسافة مسموحة بين السائق والفرع عند الاستلام',
         value='200', value_type='integer', category='delivery', is_public=False),
    dict(key='delivery_dropoff_radius_m', label='نطاق التسليم للعميل (متر)',
         description='أقصى مسافة مسموحة بين السائق وعنوان التسليم المسجَّل عند التسليم',
         value='300', value_type='integer', category='delivery', is_public=False),
    dict(key='delivery_driver_fee_base', label='أجر التوصيل الأساسي (ج.م)',
         description='المبلغ الثابت لكل عملية توصيل قبل احتساب المسافة',
         value='10', value_type='decimal', category='delivery', is_public=False),
    dict(key='delivery_driver_fee_per_km', label='أجر التوصيل لكل كم (ج.م)',
         description='يُضاف لكل كيلومتر من الفرع حتى نقطة التسليم',
         value='3', value_type='decimal', category='delivery', is_public=False),

    # ━━ General ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='pharmacy_name',         label='اسم الصيدلية',                 description='يظهر في التقارير والإيصالات',
         value='صيدليات الرزيقي',    value_type='string',  category='general', is_public=True),
    dict(key='pharmacy_name_en',      label='Pharmacy Name (English)',       description='Used in English-mode receipts',
         value='ElRezeiky Pharmacies',value_type='string',  category='general', is_public=True),
    dict(key='support_phone',         label='رقم الدعم الفني',              description='يظهر في الإيصالات وصفحة المساعدة',
         value='',                    value_type='string',  category='general', is_public=True),
    dict(key='support_email',         label='البريد الإلكتروني',            description='للتواصل الداخلي',
         value='',                    value_type='string',  category='general', is_public=True),
    dict(key='default_currency',      label='العملة الافتراضية',            description='رمز العملة المعروض في الأسعار',
         value='ج.م',                value_type='string',  category='general', is_public=True),
    dict(key='timezone',              label='المنطقة الزمنية',              description='مثال: Africa/Cairo',
         value='Africa/Cairo',        value_type='string',  category='general', is_public=False),
    dict(key='items_per_page',        label='عدد السجلات في الصفحة',        description='عدد النتائج الافتراضي في الجداول',
         value='25',                  value_type='integer', category='general', is_public=False),
    dict(key='date_format',           label='تنسيق التاريخ',                description='مثال: DD/MM/YYYY',
         value='DD/MM/YYYY',          value_type='string',  category='general', is_public=True),
    dict(key='ui_language',           label='لغة الواجهة',                  description='ar = عربي | en = English',
         value='ar',                  value_type='string',  category='general', is_public=True),

    # ━━ Reservations ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='max_reservation_qty',   label='الحد الأقصى لكمية الحجز',     description='أعلى كمية يمكن حجزها في طلب واحد',
         value='100',                 value_type='integer', category='reservations', is_public=False),
    dict(key='min_reservation_qty',   label='الحد الأدنى لكمية الحجز',     description='أقل كمية مسموح بها لطلب الحجز',
         value='1',                   value_type='integer', category='reservations', is_public=False),
    dict(key='auto_follow_up_days',   label='المتابعة التلقائية (أيام)',    description='عدد الأيام قبل إرسال تذكير المتابعة',
         value='3',                   value_type='integer', category='reservations', is_public=False),
    dict(key='reservation_expiry_days',label='انتهاء الحجز (أيام)',         description='الحجز يُلغى تلقائياً بعد هذا العدد من الأيام',
         value='30',                  value_type='integer', category='reservations', is_public=False),
    dict(key='allow_past_date_reservation', label='السماح بتاريخ استلام ماضٍ', description='السماح بإدخال تاريخ الطلب في الماضي',
         value='false',               value_type='boolean', category='reservations', is_public=False),
    dict(key='reservation_require_phone', label='رقم الهاتف إلزامي',       description='منع إنشاء حجز بدون رقم هاتف',
         value='true',                value_type='boolean', category='reservations', is_public=False),
    dict(key='show_price_on_reservation', label='عرض السعر عند الحجز',     description='إظهار سعر العبوة عند إدخال الصنف',
         value='true',                value_type='boolean', category='reservations', is_public=False),

    # ━━ Demand / Lost Sales ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='demand_suggest_order_value_threshold',
         label='حد قيمة اقتراح الشراء (ج.م)',
         description='يُقترح الصنف للشراء إذا تجاوزت قيمة بيعه الضائع هذا الحد (أو فُقد 3 مرات).',
         value='1000',                value_type='integer', category='demand', is_public=False),
    dict(key='demand_auto_whatsapp_enabled',
         label='إرسال واتساب تلقائي عند عودة الصنف للمخزون',
         description='عند التفعيل، يُرسل النظام رسالة واتساب تلقائياً للعميل عند توفر صنفه المطلوب (يحترم رفض التواصل).',
         value='false',               value_type='boolean', category='demand', is_public=False),
    dict(key='demand_restock_whatsapp_template',
         label='قالب واتساب لعودة الصنف للمخزون',
         description='اسم قالب Meta المعتمد (متغيران: اسم الصنف، الفرع). اتركه فارغاً لإرسال رسالة نصية بسيطة.',
         value='',                    value_type='string',  category='demand', is_public=False),
    dict(key='demand_recovery_escalation_hours',
         label='ساعات تصعيد الاسترداد المتأخر',
         description='فرصة الاسترداد التي لم يتم التواصل بشأنها خلال هذه المدة تُصعَّد للمشرف.',
         value='24',                  value_type='integer', category='demand', is_public=False),

    # ━━ Transfers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='transfer_auto_approve', label='موافقة تلقائية على التحويل',  description='تجاوز مرحلة المراجعة وقبول التحويل فوراً',
         value='false',               value_type='boolean', category='transfers', is_public=False),
    dict(key='transfer_require_erp',  label='مطلوب مرجع ERP عند التنفيذ', description='يمنع تسجيل التنفيذ بدون رقم مستند ERP',
         value='true',                value_type='boolean', category='transfers', is_public=False),
    dict(key='transfer_max_quantity', label='أقصى كمية في طلب التحويل',   description='0 = بلا حد أقصى',
         value='0',                   value_type='integer', category='transfers', is_public=False),
    dict(key='transfer_expiry_days',  label='انتهاء طلب التحويل (أيام)',   description='الطلب يُلغى تلقائياً إذا لم يُنفَّذ',
         value='14',                  value_type='integer', category='transfers', is_public=False),
    dict(key='transfer_allow_cross_region', label='السماح بالتحويل بين المناطق', description='تفعيل طلبات التحويل بين الفروع في مناطق مختلفة',
         value='true',                value_type='boolean', category='transfers', is_public=False),
    dict(key='transfer_sla_hours', label='مهلة استجابة طلب التحويل (ساعة)',
         description='إذا لم يستجب الفرع المصدر خلال هذا العدد من الساعات، يُرسَل تنبيه للإدارة',
         value='24',                  value_type='integer', category='transfers', is_public=False),
    dict(key='transit_alert_max_days', label='أقصى عمر لتنبيهات التحويلات قيد النقل (يوم)',
         description='التحويلات العالقة قيد النقل لأكثر من هذه المدة تُعتبر بيانات قديمة/مهملة ويتوقف إرسال تنبيهاتها المتكررة. اضبطه على قيمة كبيرة جداً لتعطيل الحد.',
         value='21',                  value_type='integer', category='transfers', is_public=False),
    dict(key='replenishment_price_threshold', label='حد سعر الغوالي (ج.م)',
         description='الصنف الذي يبلغ سعر جمهوره هذا الحد أو أكثر يذهب لمنطقة الغوالي في ورقة التجميع. '
                     'مناطق التجميع وقواعدها تُدار من شاشة /pick-zones (جداول PickZone).',
         value='500', value_type='integer', category='transfers', is_public=False),

    # ━━ Notifications ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='notify_on_new_reservation',    label='إشعار عند حجز جديد',         description='',
         value='true',               value_type='boolean', category='notifications', is_public=False),
    dict(key='notify_on_transfer_approved',  label='إشعار عند موافقة التحويل',   description='',
         value='true',               value_type='boolean', category='notifications', is_public=False),
    dict(key='notify_on_transfer_dispatched',label='إشعار عند تسليم التحويل',    description='إشعار للمستلم عند توصيل البضاعة',
         value='true',               value_type='boolean', category='notifications', is_public=False),
    dict(key='notify_on_low_stock',          label='إشعار عند نقص المخزون',      description='إشعار المسؤولين عند فجوة عالية الأولوية',
         value='true',               value_type='boolean', category='notifications', is_public=False),
    dict(key='notification_retention_days',  label='مدة الاحتفاظ بالإشعارات (أيام)', description='يتم حذف الإشعارات القديمة تلقائياً',
         value='30',                 value_type='integer', category='notifications', is_public=False),
    dict(key='notification_sound',           label='صوت الإشعارات',              description='تشغيل صوت عند وصول إشعار جديد',
         value='true',               value_type='boolean', category='notifications', is_public=False),

    # ━━ Sync ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='sync_interval_minutes',  label='دورة المزامنة (دقائق)',         description='الفترة بين كل عملية مزامنة تلقائية',
         value='60',                  value_type='integer', category='sync', is_public=False),
    dict(key='sync_batch_size',        label='حجم دفعة المزامنة',             description='عدد السجلات في كل دفعة SOFTECH',
         value='5000',                value_type='integer', category='sync', is_public=False),
    dict(key='sync_lookback_days',     label='نطاق المزامنة الزمني (أيام)',   description='عدد الأيام الماضية في المزامنة التدريجية',
         value='10',                  value_type='integer', category='sync', is_public=False),
    dict(key='sync_auto_trigger',      label='مزامنة تلقائية مجدولة',        description='تشغيل المزامنة تلقائياً بدون تدخل يدوي',
         value='false',               value_type='boolean', category='sync', is_public=False),
    dict(key='sync_notify_on_failure', label='إشعار عند فشل المزامنة',       description='إرسال إشعار للمديرين عند خطأ في المزامنة',
         value='true',                value_type='boolean', category='sync', is_public=False),

    # ━━ Vouchers ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    dict(key='voucher_otp_expiry_minutes', label='انتهاء رمز OTP (دقائق)',   description='مدة صلاحية رمز التأكيد',
         value='3',                   value_type='integer', category='vouchers', is_public=False),
    dict(key='voucher_otp_length',    label='طول رمز OTP',                   description='عدد أرقام رمز التأكيد',
         value='6',                   value_type='integer', category='vouchers', is_public=False),
    dict(key='voucher_max_value',     label='الحد الأقصى لقيمة القسيمة (ج.م)', description='0 = بلا حد',
         value='0',                   value_type='decimal', category='vouchers', is_public=False),
    dict(key='voucher_allow_partial', label='السماح بالاستخدام الجزئي',     description='استخدام جزء من قيمة القسيمة في كل مرة',
         value='true',                value_type='boolean', category='vouchers', is_public=False),
    dict(key='voucher_expiry_days',   label='انتهاء صلاحية القسيمة (أيام)', description='0 = لا تنتهي',
         value='365',                 value_type='integer', category='vouchers', is_public=False),

    # ━━ Delivery ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # F4 — Free Delivery Threshold
    dict(key='delivery_free_above',
         label='التوصيل مجاني فوق (ج.م)',
         description='إذا تجاوزت قيمة الطلب هذا المبلغ يصبح التوصيل مجاناً — 0 لتعطيل الميزة',
         value='500',                 value_type='decimal', category='general', is_public=True),
    dict(key='delivery_default_fee',
         label='رسوم التوصيل الافتراضية (ج.م)',
         description='تُطبَّق عندما لا يوجد سعر مخصص للمنطقة',
         value='20',                  value_type='decimal', category='general', is_public=True),
    # F8 — SLA Alerts
    dict(key='delivery_sla_preparing_mins',
         label='مهلة التحضير (دقائق)',
         description='تنبيه المدير إذا لم يخرج الطلب للتوصيل خلال هذه المدة من التحضير',
         value='30',                  value_type='integer', category='general', is_public=False),
    dict(key='delivery_sla_dispatch_mins',
         label='مهلة التوصيل (دقائق)',
         description='تنبيه المدير إذا مضى هذا الوقت منذ خروج السائق بدون تأكيد التسليم',
         value='90',                  value_type='integer', category='general', is_public=False),
    dict(key='delivery_sla_unassigned_mins',
         label='مهلة التكليف (دقائق)',
         description='تنبيه المدير إذا ظل الطلب بدون سائق لهذه المدة',
         value='20',                  value_type='integer', category='general', is_public=False),
    dict(key='delivery_sla_max_age_hours',
         label='أقصى عمر لتنبيهات مهلة التوصيل (ساعة)',
         description='لا تُرسَل تنبيهات المهلة للطلبات الأقدم من هذه المدة — تُعتبر بيانات قديمة/مهملة وليست حالة تحتاج تدخلاً. اضبطه على قيمة كبيرة جداً لتعطيل الحد.',
         value='48',                  value_type='integer', category='general', is_public=False),
    dict(key='delivery_sync_full_lookback_days',
         label='نافذة المزامنة الكاملة لطلبات التوصيل (يوم)',
         description='المزامنة الكاملة (--full) لا تُنشئ طلبات توصيل جديدة من مستندات SOFTECH أقدم من هذه المدة. يمنع استيراد التاريخ القديم (طلبات بحالة NULL) كطلبات "جديدة" معلَّقة. تحديثات الطلبات الموجودة لا تتأثر.',
         value='30',                  value_type='integer', category='general', is_public=False),
    # F14 — CSAT
    dict(key='delivery_csat_enabled',
         label='تفعيل استبيان الرضا بعد التوصيل',
         description='إرسال رسالة واتساب للتقييم بعد كل توصيل ناجح',
         value='true',                value_type='boolean', category='general', is_public=False),
    dict(key='delivery_csat_delay_mins',
         label='تأخير إرسال استبيان الرضا (دقائق)',
         description='انتظر هذه المدة بعد التسليم قبل إرسال رسالة التقييم',
         value='30',                  value_type='integer', category='general', is_public=False),
    dict(key='delivery_pharmacy_name',
         label='اسم الصيدلية في رسائل التوصيل',
         description='يظهر في رسائل واتساب المرسلة للعملاء',
         value='صيدليات الرزيقي',    value_type='string',  category='general', is_public=True),
]

DEFAULT_DROPDOWNS = [
    # reservation_channel (fulfillment method)
    dict(dropdown_key='reservation_channel',   label='استلام من الفرع',   label_en='Pickup',        value='pickup',        icon='🏪', order=0, is_system=True),
    dict(dropdown_key='reservation_channel',   label='توصيل للمنزل',      label_en='Home Delivery', value='home_delivery', icon='🚚', order=1, is_system=True),
    dict(dropdown_key='reservation_channel',   label='تأمين',             label_en='Insurance',     value='insurance',     icon='🏥', order=2, is_system=True),
    dict(dropdown_key='reservation_channel',   label='استفسار',           label_en='Inquiry',       value='inquiry',       icon='❓', order=3, is_system=True),

    # reservation_fulfillment_method — used in the new reservation form
    dict(dropdown_key='reservation_fulfillment_method', label='استلام من الفرع',  label_en='Pickup',   value='pickup',   icon='🏪', order=0, is_system=True),
    dict(dropdown_key='reservation_fulfillment_method', label='توصيل للمنزل',     label_en='Delivery', value='delivery', icon='🚚', order=1, is_system=True),

    # reservation_order_source — where the reservation request came from
    dict(dropdown_key='reservation_order_source', label='كول سنتر — واتساب',  label_en='CC WhatsApp',     value='cc_whatsapp',     icon='💬', order=0, is_system=True),
    dict(dropdown_key='reservation_order_source', label='كول سنتر — مكالمة',  label_en='CC Call',         value='cc_call',         icon='📞', order=1, is_system=True),
    dict(dropdown_key='reservation_order_source', label='الفرع — واتساب',      label_en='Branch WhatsApp', value='branch_whatsapp', icon='🏪', order=2, is_system=True),
    dict(dropdown_key='reservation_order_source', label='الفرع — مكالمة',      label_en='Branch Call',     value='branch_call',     icon='☎️', order=3, is_system=True),
    dict(dropdown_key='reservation_order_source', label='طلب إلكتروني',         label_en='Online',          value='online',          icon='🌐', order=4, is_system=True),
    dict(dropdown_key='reservation_order_source', label='زيارة الفرع',          label_en='Walk-in',         value='walk_in',         icon='🚶', order=5, is_system=False),

    # reservation_priority
    dict(dropdown_key='reservation_priority', label='عادي',           label_en='Normal',  value='normal',  icon='⚪', color='gray',   order=0, is_system=True),
    dict(dropdown_key='reservation_priority', label='عاجل',           label_en='Urgent',  value='urgent',  icon='🔴', color='red',    order=1, is_system=True),
    dict(dropdown_key='reservation_priority', label='مريض مزمن',     label_en='Chronic', value='chronic', icon='💊', color='purple', order=2, is_system=True),
    dict(dropdown_key='reservation_priority', label='مهم',            label_en='High',    value='high',    icon='🟡', color='yellow', order=3, is_system=False),

    # transfer_status (display labels only)
    dict(dropdown_key='transfer_status', label='مسودة',      label_en='Draft',      value='draft',      icon='📝', color='gray',  order=0, is_system=True),
    dict(dropdown_key='transfer_status', label='مُرسَل',      label_en='Submitted',  value='submitted',  icon='📤', color='blue',  order=1, is_system=True),
    dict(dropdown_key='transfer_status', label='موافق عليه', label_en='Approved',   value='approved',   icon='✅', color='green', order=2, is_system=True),
    dict(dropdown_key='transfer_status', label='مرفوض',      label_en='Rejected',   value='rejected',   icon='❌', color='red',   order=3, is_system=True),
    dict(dropdown_key='transfer_status', label='مكتمل',      label_en='Completed',  value='completed',  icon='🏁', color='teal',  order=4, is_system=True),
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
