from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0024_itemalias'),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='no_more_use',
            field=models.BooleanField(
                default=False, db_index=True,
                verbose_name='امر التوريد (موقوف/غير مستخدم)',
                help_text="SOFTECH items.itemnomoreuse='1' — discontinued / order-only item.",
            ),
        ),
    ]
