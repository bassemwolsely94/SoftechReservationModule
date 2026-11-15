"""P-05: every refill-reminder opt-out becomes a recorded withdrawal of the 'refill' purpose (WhatsApp and
call — the opt-out also kept those customers off outbound call lists), so the consent rule is the one place
that answers "may we contact them?". The RefillReminderOptOut rows are kept, untouched, as history."""
from django.db import migrations


def forward(apps, schema_editor):
    OptOut = apps.get_model('followups', 'RefillReminderOptOut')
    Consent = apps.get_model('customers', 'ContactConsent')
    rows = []
    for o in OptOut.objects.all().iterator():
        for channel in ('whatsapp', 'call'):
            rows.append(Consent(customer_id=o.customer_id, purpose='refill', channel=channel, granted=False,
                                source='migrated', note=f'refill opt-out ({o.source})'[:200],
                                recorded_by_id=o.created_by_id))
    Consent.objects.bulk_create(rows, batch_size=500)


def backward(apps, schema_editor):
    apps.get_model('customers', 'ContactConsent').objects.filter(source='migrated').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('customers', '0033_contact_consent'),
        ('followups', '0017_call_lists'),
    ]
    operations = [migrations.RunPython(forward, backward)]
