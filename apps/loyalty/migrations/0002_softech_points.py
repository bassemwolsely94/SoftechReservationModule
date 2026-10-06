from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('loyalty', '0001_initial'),
        ('customers', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='loyaltyaccount',
            name='softech_points_balance',
            field=models.IntegerField(
                default=0,
                help_text='الرصيد الفعلي في SOFTECH — المصدر الأساسي للرصيد.',
                verbose_name='رصيد النقاط (SOFTECH)',
            ),
        ),
        migrations.CreateModel(
            name='SoftechPointsLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('softech_pic', models.CharField(db_index=True, max_length=30, verbose_name='PIC')),
                ('delta', models.IntegerField(
                    help_text='موجب = إضافة، سالب = خصم',
                    verbose_name='تغيير النقاط',
                )),
                ('reason', models.CharField(blank=True, max_length=255, verbose_name='السبب')),
                ('balance_before', models.IntegerField(default=0, verbose_name='الرصيد قبل')),
                ('balance_after', models.IntegerField(default=0, verbose_name='الرصيد بعد')),
                ('success', models.BooleanField(default=True, verbose_name='نجح')),
                ('error_message', models.TextField(blank=True, verbose_name='رسالة الخطأ')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='softech_points_logs',
                    to='customers.customer',
                    verbose_name='العميل',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='users.staffprofile',
                    verbose_name='بواسطة',
                )),
            ],
            options={
                'verbose_name': 'سجل تعديل SOFTECH',
                'verbose_name_plural': 'سجلات تعديل SOFTECH',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='softechpointslog',
            index=models.Index(fields=['softech_pic', 'created_at'], name='loyalty_sof_pic_created_idx'),
        ),
    ]
