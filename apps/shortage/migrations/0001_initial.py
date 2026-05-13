import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('branches', '0001_initial'),
        ('catalog',  '0001_initial'),
        ('users',    '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShortageList',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status',       models.CharField(choices=[('open','مفتوحة'),('submitted','مُرسَلة'),('resolved','محلولة')], default='open', max_length=15, verbose_name='الحالة')),
                ('title',        models.CharField(blank=True, max_length=200, verbose_name='العنوان')),
                ('notes',        models.TextField(blank=True, verbose_name='ملاحظات')),
                ('source',       models.CharField(default='manual', max_length=30, verbose_name='المصدر')),
                ('source_image', models.ImageField(blank=True, null=True, upload_to='shortage_images/', verbose_name='صورة القائمة')),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
                ('branch',       models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shortage_lists', to='branches.branch', verbose_name='الفرع')),
                ('created_by',   models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='shortage_lists', to='users.staffprofile', verbose_name='أُنشئت بواسطة')),
            ],
            options={'verbose_name': 'قائمة نواقص', 'verbose_name_plural': 'قوائم النواقص', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='ShortageItem',
            fields=[
                ('id',              models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_name',        models.CharField(max_length=300, verbose_name='الاسم كما أُدخل')),
                ('quantity_needed', models.DecimalField(decimal_places=3, default=1, max_digits=10, verbose_name='الكمية المطلوبة')),
                ('unit',            models.CharField(blank=True, max_length=20, verbose_name='الوحدة')),
                ('notes',           models.CharField(blank=True, max_length=300, verbose_name='ملاحظات')),
                ('match_score',     models.FloatField(blank=True, null=True, verbose_name='نسبة التطابق')),
                ('is_confirmed',    models.BooleanField(default=False, verbose_name='مُأكَّد')),
                ('is_unmatched',    models.BooleanField(default=False, verbose_name='غير مطابق')),
                ('created_at',      models.DateTimeField(auto_now_add=True)),
                ('shortage_list',   models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='shortage.shortagelist', verbose_name='قائمة النواقص')),
                ('item',            models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='catalog.item', verbose_name='الصنف المطابق')),
            ],
            options={'verbose_name': 'صنف ناقص', 'verbose_name_plural': 'أصناف النواقص', 'ordering': ['raw_name']},
        ),
    ]
