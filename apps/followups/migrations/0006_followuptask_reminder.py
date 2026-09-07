from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('followups', '0005_fix_erp_transaction_charfields'),
    ]

    operations = [
        migrations.AddField(
            model_name='followuptask',
            name='reminder_at',
            field=models.DateTimeField(
                blank=True, null=True, db_index=True,
                verbose_name='موعد التذكير',
            ),
        ),
        migrations.AddField(
            model_name='followuptask',
            name='reminder_sent',
            field=models.BooleanField(default=False, verbose_name='تم إرسال التذكير'),
        ),
    ]
