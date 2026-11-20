# C23 — saved filters / default views per user on worklist screens.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0020_staffprofile_hr_code_and_more'),
        ('personal', '0004_server_wording'),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedView',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('screen', models.CharField(db_index=True, max_length=60, verbose_name='الشاشة')),
                ('name', models.CharField(max_length=80, verbose_name='اسم العرض')),
                ('filters', models.JSONField(blank=True, default=dict, verbose_name='الفلاتر')),
                ('is_default', models.BooleanField(default=False, verbose_name='افتراضي')),
                ('shared_role', models.CharField(blank=True, db_index=True, default='', max_length=30, verbose_name='مشترك مع دور')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_views', to='users.staffprofile', verbose_name='الموظف')),
            ],
            options={
                'verbose_name': 'عرض محفوظ',
                'verbose_name_plural': 'العروض المحفوظة',
                'ordering': ['screen', 'name', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='savedview',
            constraint=models.UniqueConstraint(fields=('staff', 'screen', 'name'), name='personal_savedview_unique_name'),
        ),
        migrations.AddConstraint(
            model_name='savedview',
            constraint=models.UniqueConstraint(condition=models.Q(('is_default', True)), fields=('staff', 'screen'), name='personal_savedview_one_default'),
        ),
    ]
