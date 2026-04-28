from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        # Adjust this to match your latest reservation migration number
        ('reservations', '0003_reservation_image'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReservationActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('activity_type', models.CharField(
                    choices=[
                        ('note', '📝 ملاحظة'),
                        ('call_made', '📞 مكالمة أُجريت'),
                        ('customer_replied', '💬 رد العميل'),
                        ('stock_checked', '🔍 تم فحص المخزون'),
                        ('status_changed', '🔄 تغيير الحالة'),
                        ('transfer_requested', '🔀 طلب تحويل مخزون'),
                        ('transfer_replied', '↩️ رد على طلب تحويل'),
                        ('item_dispensed', '✅ تم صرف الصنف'),
                        ('reminder_sent', '🔔 تم إرسال تذكير'),
                        ('image_attached', '🖼️ تم إرفاق صورة'),
                        ('assigned', '👤 تم التعيين'),
                        ('mention', '@ذِكر'),
                    ],
                    default='note',
                    max_length=30,
                )),
                ('message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('attachment', models.ImageField(blank=True, null=True, upload_to='reservation_activities/%Y/%m/')),
                ('transfer_request_id_ref', models.IntegerField(
                    blank=True, null=True,
                    help_text='ID of related TransferRequest (loose reference to avoid circular import)',
                )),
                ('created_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reservation_activities',
                    to='users.staffprofile',
                )),
                ('mentioned_users', models.ManyToManyField(
                    blank=True,
                    related_name='mentioned_in_activities',
                    to='users.staffprofile',
                )),
                ('reservation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='activities',
                    to='reservations.reservation',
                )),
            ],
            options={
                'verbose_name': 'نشاط الحجز',
                'verbose_name_plural': 'أنشطة الحجز',
                'ordering': ['created_at'],
            },
        ),
    ]
