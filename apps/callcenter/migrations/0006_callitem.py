from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('callcenter', '0005_caseevent_attachment'),
        ('catalog', '0018_alter_item_branch_trans_alter_item_customer_trans_and_more'),
        ('reservations', '0017_reservation_erp_receipt_customer'),
        ('transfers', '0008_erp_match_user_transtime'),
    ]

    operations = [
        migrations.CreateModel(
            name='CallItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('manual_item_name', models.CharField(blank=True, help_text='يُستخدم عندما لا يوجد الصنف في الكتالوج', max_length=255, verbose_name='اسم الصنف (يدوي)')),
                ('manual_item_code', models.CharField(blank=True, max_length=20, verbose_name='كود SOFTECH (يدوي)')),
                ('quantity', models.DecimalField(decimal_places=2, default=1, max_digits=10, verbose_name='الكمية')),
                ('notes', models.TextField(blank=True, verbose_name='ملاحظات')),
                ('converted_to', models.CharField(choices=[('none', 'لم يُحوَّل'), ('reservation', 'حجز'), ('transfer', 'طلب نقل')], db_index=True, default='none', max_length=15, verbose_name='حُوِّل إلى')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('call_log', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='callcenter.calllog', verbose_name='المكالمة')),
                ('item', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='call_items', to='catalog.item', verbose_name='الصنف من الكتالوج')),
                ('converted_reservation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='source_call_items', to='reservations.reservation', verbose_name='الحجز المُنشأ')),
                ('converted_transfer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='source_call_items', to='transfers.transferrequest', verbose_name='طلب النقل المُنشأ')),
            ],
            options={
                'verbose_name': 'صنف مكالمة',
                'verbose_name_plural': 'أصناف المكالمات',
                'ordering': ['created_at'],
            },
        ),
    ]
