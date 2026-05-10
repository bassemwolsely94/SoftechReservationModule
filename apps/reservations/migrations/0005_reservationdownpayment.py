import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0004_reservationactivity'),
        ('users', '0005_alter_staffprofile_role'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReservationDownpayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('payment_method', models.CharField(
                    choices=[
                        ('cash', 'نقدي'),
                        ('card', 'بطاقة'),
                        ('transfer', 'تحويل بنكي'),
                        ('other', 'أخرى'),
                    ],
                    default='cash',
                    max_length=10,
                )),
                ('reference_number', models.CharField(blank=True, max_length=100)),
                ('notes', models.TextField(blank=True)),
                ('received_at', models.DateTimeField(auto_now_add=True)),
                ('reservation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='downpayments',
                    to='reservations.reservation',
                )),
                ('received_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to='users.staffprofile',
                )),
            ],
            options={
                'verbose_name': 'دفعة مقدمة',
                'verbose_name_plural': 'الدفعات المقدمة',
                'ordering': ['-received_at'],
            },
        ),
    ]
