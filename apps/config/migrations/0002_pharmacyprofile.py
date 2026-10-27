from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('config', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PharmacyProfile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name_ar', models.CharField(default='صيدليات الرزيقي', max_length=200, verbose_name='الاسم بالعربية')),
                ('name_en', models.CharField(default='ElRezeiky Pharmacies', max_length=200, verbose_name='الاسم بالإنجليزية')),
                ('tagline_ar', models.CharField(blank=True, max_length=300, verbose_name='الشعار / التعريف')),
                ('website', models.CharField(blank=True, max_length=200, verbose_name='الموقع الإلكتروني')),
                ('whatsapp_number', models.CharField(blank=True, help_text='بدون + (مثل: 201055000468)', max_length=30, verbose_name='رقم واتساب الرئيسي')),
                ('call_center_numbers', models.TextField(blank=True, help_text='كل رقم في سطر منفصل', verbose_name='أرقام الاتصال')),
                ('extra_footer_ar', models.TextField(blank=True, verbose_name='نص تذييل إضافي')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'ملف الصيدلية',
                'verbose_name_plural': 'ملف الصيدلية',
            },
        ),
    ]
