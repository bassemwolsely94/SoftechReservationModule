"""
apps/delivery/migrations/0001_initial.py
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('customers', '0007_pic_as_unique_key'),
        ('users', '0007_alter_rolemoduleaccess_id_alter_userbranchaccess_id'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── CustomerLocation ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='CustomerLocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('latitude', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name='خط العرض')),
                ('longitude', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name='خط الطول')),
                ('address_line', models.TextField(blank=True, verbose_name='العنوان التفصيلي')),
                ('area', models.CharField(blank=True, max_length=100, verbose_name='المنطقة')),
                ('district', models.CharField(blank=True, max_length=100, verbose_name='الحي')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('google_maps_url', models.CharField(blank=True, max_length=500, verbose_name='رابط خرائط جوجل')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')),
                ('customer', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='location',
                    to='customers.customer',
                    verbose_name='العميل',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='آخر تعديل بواسطة',
                )),
            ],
            options={
                'verbose_name': 'موقع العميل',
                'verbose_name_plural': 'مواقع العملاء',
            },
        ),

        # ── DeliveryOrder ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='DeliveryOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('softech_doc_ref', models.CharField(blank=True, db_index=True, max_length=100, verbose_name='مرجع SOFTECH')),
                ('customer_name', models.CharField(max_length=255, verbose_name='اسم العميل')),
                ('customer_phone', models.CharField(blank=True, max_length=50, verbose_name='هاتف العميل')),
                ('delivery_address', models.TextField(blank=True, verbose_name='عنوان التوصيل')),
                ('delivery_lat', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name='خط العرض')),
                ('delivery_lng', models.DecimalField(blank=True, decimal_places=7, max_digits=10, null=True, verbose_name='خط الطول')),
                ('items_count', models.IntegerField(default=0, verbose_name='عدد الأصناف')),
                ('total_value', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='إجمالي القيمة')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'انتظار'),
                        ('assigned', 'تم التكليف'),
                        ('out', 'في الطريق'),
                        ('delivered', 'تم التسليم'),
                        ('failed', 'فشل التسليم'),
                        ('cancelled', 'ملغى'),
                    ],
                    db_index=True, default='pending', max_length=15, verbose_name='الحالة',
                )),
                ('ordered_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='وقت الطلب')),
                ('assigned_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت التكليف')),
                ('dispatched_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت الإرسال')),
                ('delivered_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت التسليم')),
                ('failed_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت الفشل')),
                ('failure_reason', models.CharField(blank=True, max_length=500, verbose_name='سبب الفشل')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')),
                ('branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='delivery_orders',
                    to='branches.branch',
                    verbose_name='الفرع',
                )),
                ('customer', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='delivery_orders',
                    to='customers.customer',
                    verbose_name='العميل',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_deliveries',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='أنشأ بواسطة',
                )),
            ],
            options={
                'verbose_name': 'طلب توصيل',
                'verbose_name_plural': 'طلبات التوصيل',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='deliveryorder',
            index=models.Index(fields=['status', 'branch'], name='del_order_status_branch'),
        ),
        migrations.AddIndex(
            model_name='deliveryorder',
            index=models.Index(fields=['ordered_at'], name='del_order_ordered_at'),
        ),

        # ── DeliveryAssignment ────────────────────────────────────────────────
        migrations.CreateModel(
            name='DeliveryAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('employee_name', models.CharField(max_length=255, verbose_name='اسم الموظف')),
                ('assigned_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت التكليف')),
                ('vehicle', models.CharField(blank=True, max_length=100, verbose_name='المركبة')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('order', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='assignment',
                    to='delivery.deliveryorder',
                    verbose_name='طلب التوصيل',
                )),
                ('employee', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='delivery_assignments',
                    to='users.staffprofile',
                    verbose_name='الموظف',
                )),
                ('assigned_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='assigned_deliveries',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='كُلِّف بواسطة',
                )),
            ],
            options={
                'verbose_name': 'تكليف توصيل',
                'verbose_name_plural': 'تكليفات التوصيل',
                'ordering': ['-assigned_at'],
            },
        ),

        # ── DeliveryStatusLog ─────────────────────────────────────────────────
        migrations.CreateModel(
            name='DeliveryStatusLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('from_status', models.CharField(max_length=15, verbose_name='من')),
                ('to_status', models.CharField(max_length=15, verbose_name='إلى')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('recorded_at', models.DateTimeField(auto_now_add=True, verbose_name='وقت التسجيل')),
                ('order', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='status_logs',
                    to='delivery.deliveryorder',
                    verbose_name='طلب التوصيل',
                )),
                ('recorded_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='سُجِّل بواسطة',
                )),
            ],
            options={
                'verbose_name': 'سجل حالة التوصيل',
                'verbose_name_plural': 'سجلات حالات التوصيل',
                'ordering': ['recorded_at'],
            },
        ),
    ]
