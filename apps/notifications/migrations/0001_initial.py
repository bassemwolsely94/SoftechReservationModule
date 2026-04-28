from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('reservations', '0001_initial'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification_type', models.CharField(
                    choices=[
                        ('stock_available', '📦 مخزون متاح'),
                        ('reservation_assigned', '👤 حجز مُعيَّن'),
                        ('reservation_created', '➕ حجز جديد'),
                        ('reservation_status', '🔄 تغيير حالة حجز'),
                        ('follow_up_due', '📅 متابعة مستحقة اليوم'),
                        ('weekly_summary', '📊 ملخص أسبوعي'),
                        ('monthly_report', '📈 تقرير شهري'),
                        ('mention', '@ ذِكر'),
                        ('transfer_request', '🔀 طلب تحويل جديد'),
                        ('transfer_response', '↩️ رد على طلب تحويل'),
                        ('unfulfilled_transfer_flag', '⚠️ تحويل غير مُصرَّف'),
                        ('system', '⚙️ نظام'),
                    ],
                    db_index=True, default='system', max_length=40,
                    verbose_name='نوع الإشعار'
                )),
                ('title', models.CharField(max_length=255, verbose_name='العنوان')),
                ('body', models.TextField(blank=True, verbose_name='نص الإشعار')),
                ('is_read', models.BooleanField(db_index=True, default=False, verbose_name='مقروء')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('transfer_request_id_ref', models.IntegerField(
                    blank=True, null=True, verbose_name='معرّف طلب التحويل'
                )),
                ('recipient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications',
                    to='users.staffprofile',
                    verbose_name='المستلم',
                )),
                ('reservation', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='notifications',
                    to='reservations.reservation',
                    verbose_name='الحجز المرتبط',
                )),
            ],
            options={
                'verbose_name': 'إشعار',
                'verbose_name_plural': 'الإشعارات',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['recipient', 'is_read', '-created_at'],
                name='notif_recipient_unread_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['notification_type', '-created_at'],
                name='notif_type_idx',
            ),
        ),
    ]
