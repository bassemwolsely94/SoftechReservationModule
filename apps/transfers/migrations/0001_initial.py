from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('catalog', '0001_initial'),
        ('reservations', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TransferRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity_needed', models.DecimalField(decimal_places=3, max_digits=10, verbose_name='الكمية المطلوبة')),
                ('quantity_approved', models.DecimalField(blank=True, decimal_places=3, max_digits=10, null=True, verbose_name='الكمية المعتمدة')),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'مسودة'),
                        ('sent', 'مُرسَل — بانتظار الرد'),
                        ('accepted', 'مقبول بالكامل'),
                        ('partial', 'مقبول جزئياً'),
                        ('rejected', 'مرفوض'),
                        ('fulfilled', 'تم التنفيذ'),
                        ('cancelled', 'ملغي'),
                    ],
                    db_index=True, default='draft', max_length=20, verbose_name='الحالة'
                )),
                ('request_note', models.TextField(blank=True, verbose_name='ملاحظة الطلب')),
                ('rejection_reason', models.CharField(
                    blank=True,
                    choices=[
                        ('insufficient_stock', 'مخزون غير كافٍ'),
                        ('reserved_customers', 'مخزون محجوز لعملاء الفرع'),
                        ('item_on_order', 'الصنف قيد الأوردر'),
                        ('other', 'أخرى'),
                    ],
                    max_length=30, verbose_name='سبب الرفض'
                )),
                ('rejection_reason_text', models.TextField(blank=True, verbose_name='تفاصيل سبب الرفض')),
                ('response_note', models.TextField(blank=True, verbose_name='ملاحظة الرد')),
                ('flagged_no_sale', models.BooleanField(db_index=True, default=False, verbose_name='مُعلَّم: لا مبيعات بعد التحويل')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('responded_at', models.DateTimeField(blank=True, null=True)),
                ('fulfilled_at', models.DateTimeField(blank=True, null=True)),
                ('fulfillment_reservation', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='fulfilled_by_transfers',
                    to='reservations.reservation',
                    verbose_name='الحجز الذي تم تنفيذه'
                )),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='transfer_requests',
                    to='catalog.item',
                    verbose_name='الصنف'
                )),
                ('linked_reservation', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='transfer_requests',
                    to='reservations.reservation',
                    verbose_name='الحجز المرتبط'
                )),
                ('requested_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='transfer_requests_made',
                    to='users.staffprofile',
                    verbose_name='طُلب بواسطة'
                )),
                ('requesting_branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='outgoing_transfers',
                    to='branches.branch',
                    verbose_name='الفرع الطالب'
                )),
                ('responded_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='transfer_requests_responded',
                    to='users.staffprofile',
                    verbose_name='تم الرد بواسطة'
                )),
                ('source_branch', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='incoming_transfers',
                    to='branches.branch',
                    verbose_name='الفرع المصدر'
                )),
            ],
            options={
                'verbose_name': 'طلب تحويل',
                'verbose_name_plural': 'طلبات التحويل',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='transferrequest',
            index=models.Index(fields=['status', 'requesting_branch'], name='transfers_status_req_idx'),
        ),
        migrations.AddIndex(
            model_name='transferrequest',
            index=models.Index(fields=['status', 'source_branch'], name='transfers_status_src_idx'),
        ),
        migrations.AddIndex(
            model_name='transferrequest',
            index=models.Index(fields=['flagged_no_sale'], name='transfers_flagged_idx'),
        ),
        migrations.AddIndex(
            model_name='transferrequest',
            index=models.Index(fields=['created_at'], name='transfers_created_idx'),
        ),
    ]
