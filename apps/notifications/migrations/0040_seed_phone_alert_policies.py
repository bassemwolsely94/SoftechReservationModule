from django.db import migrations

V1_EVENTS = [
    'reservation_sourcing', 'transfer_hq_submitted', 'transfer_status',
    'reservation_status_urgent', 'task_assigned', 'task_status', 'escalation',
]


def seed(apps, schema_editor):
    Policy = apps.get_model('notifications', 'PhoneAlertPolicy')
    for key in V1_EVENTS:
        Policy.objects.get_or_create(event=key, defaults={
            'mode': 'always' if key == 'escalation' else 'optional',
            'remind_after_min': 15, 'escalate_after_min': 30, 'max_reminders': 2,
        })


class Migration(migrations.Migration):
    dependencies = [('notifications', '0039_phonealert_phonealertattempt_phonealertpolicy_and_more')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
