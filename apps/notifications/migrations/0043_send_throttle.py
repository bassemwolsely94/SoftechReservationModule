# Round 2, R5 (owner question 6): at most 1 automatic message per recipient per type per window.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0042_callback_overdue_alert'),
    ]

    operations = [
        migrations.CreateModel(
            name='SendThrottle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recipient_hash', models.CharField(max_length=64)),
                ('kind', models.CharField(max_length=80)),
                ('last_sent_at', models.DateTimeField()),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('recipient_hash', 'kind'),
                                                        name='send_throttle_recipient_kind_uniq')],
            },
        ),
        migrations.AlterField(
            model_name='phonealertattempt',
            name='result',
            field=models.CharField(choices=[('sent', 'sent'), ('dry_run', 'dry_run'), ('failed', 'failed'),
                                            ('delivered', 'delivered'), ('read', 'read'),
                                            ('throttled', 'throttled')], max_length=10),
        ),
    ]
