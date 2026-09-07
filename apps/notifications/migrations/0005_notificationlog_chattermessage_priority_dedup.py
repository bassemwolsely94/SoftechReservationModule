"""
Migration: notifications 0005

Adds everything introduced by the notification system redesign:
  - Notification.priority     — always 'high'; CharField with choices
  - Notification.dedup_key    — CharField for 5-min deduplication window
  - Notification.chatter_message_id_ref — IntegerField link to ChatterMessage
  - Update NOTIFICATION_TYPES choices to include chatter_mention
  - NotificationLog model    — delivery + read audit trail
  - ChatterMessage model     — threaded @mention comments on any record
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0004_notification_demand_id_ref_and_types'),
        ('users', '0011_staffprofile_notification_prefs'),
        ('reservations', '0001_initial'),
    ]

    operations = [
        # ── Notification: priority ────────────────────────────────────────────
        migrations.AddField(
            model_name='notification',
            name='priority',
            field=models.CharField(
                choices=[('high', 'عاجل')],
                default='high',
                max_length=10,
                verbose_name='الأولوية',
            ),
        ),

        # ── Notification: dedup_key ───────────────────────────────────────────
        migrations.AddField(
            model_name='notification',
            name='dedup_key',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                max_length=200,
                verbose_name='مفتاح التكرار',
            ),
            preserve_default=False,
        ),

        # ── Notification: chatter_message_id_ref ─────────────────────────────
        migrations.AddField(
            model_name='notification',
            name='chatter_message_id_ref',
            field=models.IntegerField(blank=True, null=True),
        ),

        # ── Update notification_type choices (add chatter_mention) ────────────
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(
                choices=[
                    ('stock_available',           '📦 مخزون متاح'),
                    ('reservation_assigned',      '👤 حجز مُعيَّن'),
                    ('reservation_created',       '➕ حجز جديد'),
                    ('reservation_status',        '🔄 تغيير حالة حجز'),
                    ('follow_up_due',             '📅 متابعة مستحقة اليوم'),
                    ('weekly_summary',            '📊 ملخص أسبوعي'),
                    ('monthly_report',            '📈 تقرير شهري'),
                    ('transfer_request',          '🔀 طلب تحويل جديد'),
                    ('transfer_response',         '↩️ رد على طلب تحويل'),
                    ('unfulfilled_transfer_flag', '⚠️ تحويل غير مُصرَّف'),
                    ('demand_created',            '🆕 طلب جديد'),
                    ('demand_assigned',           '👤 طلب مُعيَّن'),
                    ('demand_status',             '🔄 تغيير حالة طلب'),
                    ('demand_follow_up',          '📅 متابعة طلب'),
                    ('chatter_mention',           '💬 ذِكر في تعليق'),
                    ('mention',                   '@ ذِكر'),
                    ('system',                    '⚙️ نظام'),
                ],
                db_index=True,
                default='system',
                max_length=40,
                verbose_name='نوع الإشعار',
            ),
        ),

        # ── Add composite indexes ─────────────────────────────────────────────
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['recipient', 'is_read', '-created_at'],
                name='notif_recip_read_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['notification_type', '-created_at'],
                name='notif_type_created_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['recipient', 'dedup_key', 'is_read'],
                name='notif_dedup_idx',
            ),
        ),

        # ── NotificationLog ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='NotificationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notification', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='logs',
                    to='notifications.notification',
                    verbose_name='الإشعار',
                )),
                ('recipient', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notification_logs',
                    to='users.staffprofile',
                    verbose_name='المستلم',
                )),
                ('delivered_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت التسليم')),
                ('read_at',      models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='وقت القراءة')),
            ],
            options={
                'verbose_name':        'سجل إشعار',
                'verbose_name_plural': 'سجلات الإشعارات',
            },
        ),
        migrations.AlterUniqueTogether(
            name='notificationlog',
            unique_together={('notification', 'recipient')},
        ),
        migrations.AddIndex(
            model_name='notificationlog',
            index=models.Index(fields=['recipient', 'read_at'],      name='nlog_recip_read_idx'),
        ),
        migrations.AddIndex(
            model_name='notificationlog',
            index=models.Index(fields=['recipient', 'delivered_at'], name='nlog_recip_delivered_idx'),
        ),
        migrations.AddIndex(
            model_name='notificationlog',
            index=models.Index(fields=['notification', 'delivered_at'], name='nlog_notif_delivered_idx'),
        ),

        # ── ChatterMessage ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ChatterMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('model_name', models.CharField(
                    db_index=True,
                    max_length=100,
                    verbose_name='النموذج',
                    help_text='e.g. reservation | invoice | transfer',
                )),
                ('record_id', models.PositiveIntegerField(db_index=True, verbose_name='معرف السجل')),
                ('author', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='chatter_messages',
                    to='users.staffprofile',
                    verbose_name='المرسل',
                )),
                ('message',    models.TextField(verbose_name='الرسالة')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name':        'رسالة دردشة',
                'verbose_name_plural': 'رسائل الدردشة',
                'ordering':            ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='chattermessage',
            index=models.Index(
                fields=['model_name', 'record_id', 'created_at'],
                name='chatter_model_record_idx',
            ),
        ),
    ]
