from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='SystemSetting',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key',         models.CharField(max_length=100, unique=True, verbose_name='المفتاح')),
                ('label',       models.CharField(max_length=200, verbose_name='التسمية')),
                ('description', models.TextField(blank=True, verbose_name='الوصف')),
                ('value',       models.TextField(blank=True, verbose_name='القيمة')),
                ('value_type',  models.CharField(
                    choices=[('string','نص'),('integer','رقم صحيح'),('decimal','رقم عشري'),('boolean','نعم / لا'),('json','JSON')],
                    default='string', max_length=10, verbose_name='النوع'
                )),
                ('category',    models.CharField(
                    choices=[('general','عام'),('reservations','الحجوزات'),('transfers','طلبات التحويل'),('notifications','الإشعارات'),('sync','المزامنة'),('vouchers','القسائم')],
                    default='general', max_length=30, verbose_name='الفئة'
                )),
                ('is_public',   models.BooleanField(default=False, verbose_name='متاح للقراءة العامة')),
                ('updated_at',  models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'إعداد النظام', 'verbose_name_plural': 'إعدادات النظام', 'ordering': ['category', 'key']},
        ),
        migrations.CreateModel(
            name='DropdownOption',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('dropdown_key', models.CharField(db_index=True, max_length=100, verbose_name='مفتاح القائمة')),
                ('label',        models.CharField(max_length=200, verbose_name='التسمية العربية')),
                ('label_en',     models.CharField(blank=True, max_length=200, verbose_name='التسمية الإنجليزية')),
                ('value',        models.CharField(max_length=100, verbose_name='القيمة')),
                ('icon',         models.CharField(blank=True, max_length=10, verbose_name='أيقونة')),
                ('color',        models.CharField(blank=True, max_length=30, verbose_name='لون (Tailwind class)')),
                ('order',        models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')),
                ('is_active',    models.BooleanField(default=True, verbose_name='مفعّل')),
                ('is_system',    models.BooleanField(default=False, verbose_name='ثابت (لا يمكن حذفه)')),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'خيار القائمة', 'verbose_name_plural': 'خيارات القوائم', 'ordering': ['dropdown_key', 'order', 'label']},
        ),
        migrations.AlterUniqueTogether(
            name='dropdownoption',
            unique_together={('dropdown_key', 'value')},
        ),
    ]
