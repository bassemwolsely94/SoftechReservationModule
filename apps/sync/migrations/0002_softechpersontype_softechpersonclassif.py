# Generated 2026-05-19 — add SoftechPersonType and SoftechPersonClassif label caches
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sync', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SoftechPersonType',
            fields=[
                ('id',       models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ptcode',   models.CharField(db_index=True, max_length=10, unique=True, verbose_name='كود نوع الشخص')),
                ('ptdescr',  models.CharField(blank=True, max_length=150, verbose_name='وصف نوع الشخص (عربي)')),
                ('ptedescr', models.CharField(blank=True, max_length=150, verbose_name='وصف نوع الشخص (إنجليزي)')),
            ],
            options={
                'verbose_name':        'نوع الشخص (SOFTECH)',
                'verbose_name_plural': 'أنواع الأشخاص (SOFTECH)',
                'ordering':            ['ptcode'],
            },
        ),
        migrations.CreateModel(
            name='SoftechPersonClassif',
            fields=[
                ('id',             models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ptcode',         models.CharField(db_index=True, max_length=10, verbose_name='كود نوع الشخص')),
                ('ptclassifcode',  models.CharField(db_index=True, max_length=10, verbose_name='كود التصنيف')),
                ('ptclassifdescr', models.CharField(blank=True, max_length=150, verbose_name='وصف التصنيف (عربي)')),
            ],
            options={
                'verbose_name':        'تصنيف نوع الشخص (SOFTECH)',
                'verbose_name_plural': 'تصنيفات أنواع الأشخاص (SOFTECH)',
                'ordering':            ['ptclassifcode'],
            },
        ),
        migrations.AddConstraint(
            model_name='softechpersonclassif',
            constraint=models.UniqueConstraint(
                fields=['ptcode', 'ptclassifcode'],
                name='sync_softechpersonclassif_ptcode_ptclassifcode_uniq',
            ),
        ),
    ]
