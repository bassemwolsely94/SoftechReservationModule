from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0022_supplierinvoice_dup_check_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='supplierinvoice',
            name='source_sha256',
            field=models.CharField(blank=True, db_index=True, default='', editable=False, max_length=64,
                                   verbose_name='بصمة الملف'),
        ),
        migrations.AddField(
            model_name='invoicebatch',
            name='source_sha256',
            field=models.CharField(blank=True, db_index=True, default='', editable=False, max_length=64,
                                   verbose_name='بصمة الملف'),
        ),
    ]
