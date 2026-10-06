from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0018_add_walk_in_order_source'),
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReservationLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('manual_item_name', models.CharField(blank=True, max_length=500)),
                ('quantity_requested', models.DecimalField(decimal_places=2, default=1, max_digits=10)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    to='catalog.item',
                )),
                ('reservation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lines',
                    to='reservations.reservation',
                )),
            ],
            options={
                'verbose_name': 'صنف في الحجز',
                'verbose_name_plural': 'أصناف الحجز',
                'ordering': ['created_at'],
            },
        ),
    ]
