"""
apps/campaigns/migrations/0001_initial.py
"""
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog', '0019_variant_groups_bundles'),
        ('customers', '0015_customer_segment_fields'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='WhatsAppCampaign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='اسم الحملة')),
                ('description', models.TextField(blank=True, verbose_name='وصف')),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'مسودة'),
                        ('pending_approval', 'بانتظار الموافقة'),
                        ('approved', 'معتمدة'),
                        ('scheduled', 'مجدولة'),
                        ('running', 'جارية'),
                        ('paused', 'موقوفة'),
                        ('completed', 'مكتملة'),
                        ('cancelled', 'ملغاة'),
                        ('rejected', 'مرفوضة'),
                    ],
                    db_index=True,
                    default='draft',
                    max_length=20,
                    verbose_name='الحالة',
                )),
                ('message_template', models.TextField(
                    help_text='متغيرات: {{customer_name}}, {{item_name}}, {{branch_name}}',
                    verbose_name='نص الرسالة',
                )),
                ('target_filter', models.JSONField(blank=True, default=dict, verbose_name='فلتر الجمهور')),
                ('scheduled_at', models.DateTimeField(
                    blank=True, null=True,
                    verbose_name='موعد الإرسال',
                    help_text='فارغ = إرسال يدوي فور الموافقة',
                )),
                ('estimated_reach', models.PositiveIntegerField(default=0, verbose_name='الوصول المقدَّر')),
                ('messages_queued', models.PositiveIntegerField(default=0, verbose_name='رسائل في الانتظار')),
                ('messages_sent', models.PositiveIntegerField(default=0, verbose_name='رسائل مُرسَلة')),
                ('messages_delivered', models.PositiveIntegerField(default=0, verbose_name='رسائل مُسلَّمة')),
                ('messages_failed', models.PositiveIntegerField(default=0, verbose_name='رسائل فاشلة')),
                ('rejection_reason', models.TextField(blank=True, verbose_name='سبب الرفض')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('queued_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('approved_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='campaigns_approved',
                    to='users.staffprofile',
                    verbose_name='اعتمد بواسطة',
                )),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='campaigns_created',
                    to='users.staffprofile',
                    verbose_name='أنشئ بواسطة',
                )),
                ('featured_item', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='campaigns',
                    to='catalog.item',
                    verbose_name='الصنف المميز',
                )),
                ('rejected_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='campaigns_rejected',
                    to='users.staffprofile',
                    verbose_name='رفض بواسطة',
                )),
            ],
            options={
                'verbose_name': 'حملة واتساب',
                'verbose_name_plural': 'حملات واتساب',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='CampaignMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone_number', models.CharField(max_length=30, verbose_name='رقم الهاتف')),
                ('customer_name', models.CharField(blank=True, max_length=255, verbose_name='اسم العميل')),
                ('message_text', models.TextField(verbose_name='نص الرسالة المُخصَّص')),
                ('whatsapp_url', models.TextField(blank=True, verbose_name='رابط واتساب')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'في الانتظار'),
                        ('sent', 'مُرسَلة'),
                        ('delivered', 'مُسلَّمة'),
                        ('failed', 'فاشلة'),
                        ('opted_out', 'مرفوضة من العميل'),
                        ('skipped', 'تم التخطي'),
                    ],
                    db_index=True,
                    default='pending',
                    max_length=10,
                    verbose_name='حالة التسليم',
                )),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('failed_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('campaign', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='messages',
                    to='campaigns.whatsappcampaign',
                    verbose_name='الحملة',
                )),
                ('customer', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='campaign_messages',
                    to='customers.customer',
                    verbose_name='العميل',
                )),
            ],
            options={
                'verbose_name': 'رسالة حملة',
                'verbose_name_plural': 'رسائل الحملات',
                'ordering': ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='campaignmessage',
            index=models.Index(fields=['campaign', 'status'], name='campaigns_c_campaig_idx'),
        ),
        migrations.AddIndex(
            model_name='campaignmessage',
            index=models.Index(fields=['campaign', 'customer'], name='campaigns_c_custome_idx'),
        ),
    ]
