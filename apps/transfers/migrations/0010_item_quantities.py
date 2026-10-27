from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0009_add_source_recommendation_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='transferrequestitem',
            name='approved_quantity',
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=10,
                null=True, verbose_name='الكمية المعتمدة',
            ),
        ),
        migrations.AddField(
            model_name='transferrequestitem',
            name='received_quantity',
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=10,
                null=True, verbose_name='الكمية المستلمة فعلياً',
            ),
        ),
    ]
