from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0005_customer_is_guest'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='softech_pic',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='الكود المركب: {كودالفرع}HD{رقمالعميل} — مثال: 01HD14 أو 130HD9969',
                max_length=30,
                verbose_name='كود العميل (PIC)',
            ),
            preserve_default=False,
        ),
    ]
