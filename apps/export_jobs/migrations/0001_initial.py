# Performance Stage 4 — the shared background export job.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users', '0060_alerts_module'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExportJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(max_length=40)),
                ('params', models.JSONField(blank=True, default=dict)),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('queued', 'في الانتظار'), ('running', 'جارٍ الإنشاء'), ('done', 'جاهز'), ('failed', 'فشل')], default='queued', max_length=10)),
                ('progress_pct', models.PositiveSmallIntegerField(default=0)),
                ('progress_msg', models.CharField(blank=True, default='', max_length=120)),
                ('file_name', models.CharField(blank=True, default='', max_length=200)),
                ('content_type', models.CharField(blank=True, default='', max_length=120)),
                ('data', models.BinaryField(blank=True, editable=False, null=True)),
                ('rows', models.JSONField(blank=True, default=dict)),
                ('error', models.CharField(blank=True, default='', max_length=255)),
                ('worker', models.CharField(blank=True, default='', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='users.staffprofile')),
            ],
            options={
                'verbose_name': 'ملف تصدير',
                'verbose_name_plural': 'ملفات التصدير',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['requested_by', 'kind', '-created_at'], name='exportjob_user_kind'),
                            models.Index(fields=['status', 'created_at'], name='exportjob_status_created')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('status__in', ['queued', 'running'])), fields=('requested_by', 'kind'), name='uniq_active_export_job')],
            },
        ),
    ]
