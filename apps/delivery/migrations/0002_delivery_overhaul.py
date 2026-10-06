"""
apps/delivery/migrations/0002_delivery_overhaul.py

Complete delivery module overhaul — v2.

Changes:
  1. CustomerLocation: OneToOneField → ForeignKey + new address fields
  2. DeliveryDriver: new model
  3. DeliveryOrder: new fields (order_number, source_type, fees, payment, alt_phone, areas,
                                SLA, driver FK, statuses expanded to 14, new indexes)
  4. DeliveryOrderItem: new model
  5. DeliveryAssignment: OneToOneField → ForeignKey + is_current flag + driver FK
  6. DeliveryStatusLog: expand max_length + add source field
  7. CashCollection: new model
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delivery', '0001_initial'),
        ('branches', '0001_initial'),
        ('customers', '0007_pic_as_unique_key'),
        ('users', '0007_alter_rolemoduleaccess_id_alter_userbranchaccess_id'),
        ('catalog', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── 1. DeliveryDriver (new model) ─────────────────────────────────────
        migrations.CreateModel(
            name='DeliveryDriver',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=255, verbose_name='الاسم الكامل')),
                ('mobile', models.CharField(db_index=True, max_length=50, verbose_name='الجوال')),
                ('national_id', models.CharField(blank=True, max_length=30, verbose_name='رقم الهوية')),
                ('vehicle_type', models.CharField(
                    choices=[
                        ('motorcycle', 'دراجة نارية 🏍️'),
                        ('car', 'سيارة 🚗'),
                        ('bicycle', 'دراجة هوائية 🚲'),
                        ('on_foot', 'سير 🚶'),
                        ('van', 'ميكروباص 🚐'),
                    ],
                    default='motorcycle', max_length=15, verbose_name='نوع المركبة',
                )),
                ('vehicle_plate', models.CharField(blank=True, max_length=30, verbose_name='لوحة المركبة')),
                ('status', models.CharField(
                    choices=[
                        ('active', 'نشط ✅'),
                        ('inactive', 'غير نشط'),
                        ('suspended', 'موقوف 🔴'),
                    ],
                    db_index=True, default='active', max_length=12, verbose_name='الحالة',
                )),
                ('max_daily_orders', models.PositiveSmallIntegerField(default=20, verbose_name='الحد اليومي للطلبات')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='drivers', to='branches.branch', verbose_name='الفرع',
                )),
                ('staff_profile', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='driver_profile', to='users.staffprofile', verbose_name='ملف الموظف',
                )),
            ],
            options={
                'verbose_name': 'سائق توصيل',
                'verbose_name_plural': 'سائقو التوصيل',
                'ordering': ['full_name'],
            },
        ),
        migrations.AddIndex(
            model_name='deliverydriver',
            index=models.Index(fields=['status', 'branch'], name='del_driver_status_branch'),
        ),

        # ── 2. CustomerLocation: drop old OneToOne, create new FK-based table ─
        # Rename old table, create new one.
        # NOTE: existing location data is migrated — see data migration below.
        migrations.RenameModel(
            old_name='CustomerLocation',
            new_name='CustomerLocationLegacy',
        ),
        migrations.CreateModel(
            name='CustomerLocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(
                    choices=[
                        ('home', 'المنزل 🏠'),
                        ('work', 'العمل 🏢'),
                        ('relative', 'قريب 👨‍👩‍👧'),
                        ('temporary', 'مؤقت ⏳'),
                        ('hospital', 'مستشفى 🏥'),
                        ('other', 'أخرى'),
                    ],
                    default='home', max_length=15, verbose_name='نوع العنوان',
                )),
                ('label_custom', models.CharField(blank=True, max_length=50, verbose_name='تسمية مخصصة')),
                ('is_default', models.BooleanField(db_index=True, default=False, verbose_name='العنوان الافتراضي')),
                ('address_line', models.TextField(blank=True, verbose_name='العنوان التفصيلي')),
                ('building', models.CharField(blank=True, max_length=50, verbose_name='رقم / اسم المبنى')),
                ('floor', models.CharField(blank=True, max_length=10, verbose_name='الدور')),
                ('apartment', models.CharField(blank=True, max_length=20, verbose_name='رقم الشقة')),
                ('landmark', models.CharField(blank=True, max_length=200, verbose_name='علامة مميزة')),
                ('area', models.CharField(blank=True, max_length=100, verbose_name='المنطقة')),
                ('district', models.CharField(blank=True, max_length=100, verbose_name='الحي')),
                ('governorate', models.CharField(blank=True, max_length=100, verbose_name='المحافظة')),
                ('latitude', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name='خط العرض')),
                ('longitude', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name='خط الطول')),
                ('google_maps_url', models.CharField(blank=True, max_length=500, verbose_name='رابط خرائط جوجل')),
                ('location_accuracy', models.CharField(
                    choices=[
                        ('exact', 'دقيق — GPS مؤكد'),
                        ('approximate', 'تقريبي — عنوان نصي'),
                        ('unverified', 'غير مؤكد'),
                    ],
                    default='unverified', max_length=15, verbose_name='دقة الموقع',
                )),
                ('delivery_phone', models.CharField(blank=True, max_length=50, verbose_name='هاتف التوصيل')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات التوصيل')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='locations', to='customers.customer', verbose_name='العميل',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL, verbose_name='آخر تعديل بواسطة',
                )),
            ],
            options={
                'verbose_name': 'موقع العميل',
                'verbose_name_plural': 'مواقع العملاء',
                'ordering': ['-is_default', 'label'],
            },
        ),
        migrations.AddIndex(
            model_name='customerlocation',
            index=models.Index(fields=['customer', 'is_default'], name='del_loc_customer_default'),
        ),

        # ── Data migration: copy legacy location rows into new table ──────────
        migrations.RunSQL(
            sql="""
                INSERT INTO delivery_customerlocation
                    (customer_id, label, is_default, address_line, area, district,
                     latitude, longitude, google_maps_url, location_accuracy,
                     notes, created_at, updated_at, updated_by_id,
                     label_custom, building, floor, apartment, landmark, governorate, delivery_phone)
                SELECT
                    customer_id, 'home', TRUE, address_line, area, district,
                    latitude, longitude, google_maps_url, 'unverified',
                    notes, created_at, updated_at, updated_by_id,
                    '', '', '', '', '', '', ''
                FROM delivery_customerlocationlegacy
            """,
            reverse_sql="",  # irreversible data migration
        ),

        # ── Drop legacy table ─────────────────────────────────────────────────
        migrations.DeleteModel(name='CustomerLocationLegacy'),

        # ── 3. DeliveryOrder: add new fields ──────────────────────────────────
        migrations.AddField(
            model_name='deliveryorder',
            name='order_number',
            field=models.CharField(blank=True, db_index=True, max_length=20, unique=True,
                                   verbose_name='رقم الطلب', null=True),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='source_type',
            field=models.CharField(
                choices=[('call_center', 'كول سنتر 📞'), ('branch_pos', 'POS الفرع 🏪')],
                db_index=True, default='call_center', max_length=15, verbose_name='مصدر الطلب',
            ),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='softech_branch_code',
            field=models.CharField(blank=True, max_length=10, verbose_name='كود فرع SOFTECH'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='customer_phone_alt',
            field=models.CharField(blank=True, max_length=50, verbose_name='هاتف بديل'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='location',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='orders', to='delivery.customerlocation', verbose_name='موقع التوصيل',
            ),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='delivery_area',
            field=models.CharField(blank=True, max_length=100, verbose_name='المنطقة'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='delivery_district',
            field=models.CharField(blank=True, max_length=100, verbose_name='الحي'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='delivery_governorate',
            field=models.CharField(blank=True, max_length=100, verbose_name='المحافظة'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='delivery_landmark',
            field=models.CharField(blank=True, max_length=200, verbose_name='علامة مميزة'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='google_maps_url',
            field=models.CharField(blank=True, max_length=500, verbose_name='رابط خرائط جوجل'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='delivery_fees',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name='رسوم التوصيل'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='payment_method',
            field=models.CharField(
                choices=[
                    ('cash', 'كاش 💵'), ('visa', 'فيزا 💳'), ('insurance', 'تأمين 🏥'),
                    ('mixed', 'مختلط'), ('wallet', 'محفظة إلكترونية'), ('pending', 'لم يُحدد بعد'),
                ],
                default='pending', max_length=15, verbose_name='طريقة الدفع',
            ),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='collected_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True,
                                      verbose_name='المبلغ المحصَّل'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='assigned_driver',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='current_orders', to='delivery.deliverydriver',
                verbose_name='السائق المكلف',
            ),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='cancel_reason',
            field=models.TextField(blank=True, verbose_name='سبب الإلغاء'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='sla_due_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='موعد SLA'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='driver_accepted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت قبول السائق'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='closed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت الإغلاق'),
        ),
        # Alter status field: expand choices and max_length
        migrations.AlterField(
            model_name='deliveryorder',
            name='status',
            field=models.CharField(
                choices=[
                    ('created', 'جديد 🆕'),
                    ('pending_review', 'بانتظار المراجعة ⏳'),
                    ('preparing', 'جاري التحضير 🔧'),
                    ('ready', 'جاهز للتسليم 📦'),
                    ('assigned', 'تم التكليف 👤'),
                    ('driver_accepted', 'السائق قبل الطلب ✅'),
                    ('out_for_delivery', 'في الطريق 🚚'),
                    ('delivered', 'تم التسليم ✅'),
                    ('partial_delivery', 'تسليم جزئي ⚠️'),
                    ('customer_unavailable', 'العميل غير متاح 📵'),
                    ('failed', 'فشل التسليم ❌'),
                    ('returned', 'مُعاد 🔄'),
                    ('cancelled', 'ملغى 🚫'),
                    ('closed', 'مغلق 🔒'),
                ],
                db_index=True, default='created', max_length=25, verbose_name='الحالة',
            ),
        ),
        # Update existing 'pending' rows to 'created'
        migrations.RunSQL(
            sql="UPDATE delivery_deliveryorder SET status = 'created' WHERE status = 'pending'",
            reverse_sql="UPDATE delivery_deliveryorder SET status = 'pending' WHERE status = 'created'",
        ),
        # Update existing 'out' rows to 'out_for_delivery'
        migrations.RunSQL(
            sql="UPDATE delivery_deliveryorder SET status = 'out_for_delivery' WHERE status = 'out'",
            reverse_sql="UPDATE delivery_deliveryorder SET status = 'out' WHERE status = 'out_for_delivery'",
        ),
        # Populate order_number for existing rows
        migrations.RunSQL(
            sql="UPDATE delivery_deliveryorder SET order_number = CONCAT('DEL-', LPAD(id::text, 6, '0')) WHERE order_number IS NULL",
            reverse_sql="",
        ),
        # Make order_number NOT NULL after population
        migrations.AlterField(
            model_name='deliveryorder',
            name='order_number',
            field=models.CharField(blank=True, db_index=True, max_length=20, unique=True,
                                   verbose_name='رقم الطلب'),
        ),
        # Add new indexes
        migrations.AddIndex(
            model_name='deliveryorder',
            index=models.Index(fields=['customer', 'status'], name='del_order_customer_status'),
        ),
        migrations.AddIndex(
            model_name='deliveryorder',
            index=models.Index(fields=['assigned_driver'], name='del_order_driver'),
        ),
        migrations.AddIndex(
            model_name='deliveryorder',
            index=models.Index(fields=['source_type', 'status'], name='del_order_source_status'),
        ),

        # ── 4. DeliveryOrderItem (new model) ──────────────────────────────────
        migrations.CreateModel(
            name='DeliveryOrderItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('item_name', models.CharField(max_length=500, verbose_name='اسم الصنف')),
                ('item_code', models.CharField(blank=True, max_length=20, verbose_name='كود الصنف')),
                ('quantity', models.DecimalField(decimal_places=2, default=1, max_digits=10, verbose_name='الكمية')),
                ('unit_price', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='السعر')),
                ('line_total', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='الإجمالي')),
                ('delivered_quantity', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=10, null=True,
                    verbose_name='الكمية المسلَّمة',
                )),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('item', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='delivery_items', to='catalog.item', verbose_name='الصنف',
                )),
                ('order', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items', to='delivery.deliveryorder', verbose_name='طلب التوصيل',
                )),
            ],
            options={
                'verbose_name': 'صنف في طلب التوصيل',
                'verbose_name_plural': 'أصناف طلبات التوصيل',
                'ordering': ['id'],
            },
        ),

        # ── 5. DeliveryAssignment: OneToOneField → ForeignKey ─────────────────
        migrations.RemoveField(model_name='deliveryassignment', name='employee'),
        migrations.RemoveField(model_name='deliveryassignment', name='employee_name'),
        migrations.RemoveField(model_name='deliveryassignment', name='assigned_by'),
        migrations.AlterField(
            model_name='deliveryassignment',
            name='order',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='assignments', to='delivery.deliveryorder', verbose_name='طلب التوصيل',
            ),
        ),
        migrations.AddField(
            model_name='deliveryassignment',
            name='driver',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assignments', to='delivery.deliverydriver', verbose_name='السائق',
            ),
        ),
        migrations.AddField(
            model_name='deliveryassignment',
            name='driver_name',
            field=models.CharField(blank=True, max_length=255, verbose_name='اسم السائق'),
        ),
        migrations.AddField(
            model_name='deliveryassignment',
            name='is_current',
            field=models.BooleanField(db_index=True, default=True, verbose_name='تكليف حالي'),
        ),
        migrations.AddField(
            model_name='deliveryassignment',
            name='assigned_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_deliveries', to=settings.AUTH_USER_MODEL,
                verbose_name='كُلِّف بواسطة',
            ),
        ),

        # ── 6. DeliveryStatusLog: expand max_length + add source ──────────────
        migrations.AlterField(
            model_name='deliverystatuslog',
            name='from_status',
            field=models.CharField(max_length=25, verbose_name='من'),
        ),
        migrations.AlterField(
            model_name='deliverystatuslog',
            name='to_status',
            field=models.CharField(max_length=25, verbose_name='إلى'),
        ),
        migrations.AddField(
            model_name='deliverystatuslog',
            name='source',
            field=models.CharField(
                choices=[
                    ('manual', '👤 يدوي'), ('system', '⚙️ نظام'), ('api', '🔌 API'),
                    ('import', '📥 استيراد'), ('mobile', '📱 موبايل'),
                ],
                default='manual', max_length=10, verbose_name='مصدر التغيير',
            ),
        ),

        # ── 7. CashCollection (new model) ─────────────────────────────────────
        migrations.CreateModel(
            name='CashCollection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('expected_amount', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='المبلغ المتوقع')),
                ('collected_amount', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=12, null=True,
                    verbose_name='المبلغ المحصَّل',
                )),
                ('shortage_amount', models.DecimalField(
                    decimal_places=2, default=0, max_digits=12, verbose_name='مبلغ العجز',
                )),
                ('overage_amount', models.DecimalField(
                    decimal_places=2, default=0, max_digits=12, verbose_name='مبلغ الزيادة',
                )),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'بانتظار التحصيل ⏳'),
                        ('collected', 'تم التحصيل ✅'),
                        ('shortage', 'عجز نقدي ⚠️'),
                        ('overage', 'زيادة نقدية'),
                        ('waived', 'تم الإعفاء'),
                        ('disputed', 'خلاف 🔴'),
                    ],
                    db_index=True, default='pending', max_length=12, verbose_name='حالة التحصيل',
                )),
                ('collection_time', models.DateTimeField(blank=True, null=True, verbose_name='وقت التحصيل')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('collected_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='cash_collections', to=settings.AUTH_USER_MODEL,
                    verbose_name='حُصِّل بواسطة',
                )),
                ('order', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='cash_collection', to='delivery.deliveryorder',
                    verbose_name='طلب التوصيل',
                )),
            ],
            options={
                'verbose_name': 'تحصيل نقدي',
                'verbose_name_plural': 'التحصيلات النقدية',
            },
        ),
    ]
