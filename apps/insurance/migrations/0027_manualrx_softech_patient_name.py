from django.db import migrations, models


def backfill(apps, schema_editor):
    """Seed InsuranceClaimManualRx.softech_patient_name: earliest manual_edit
    audit before-name if the name was edited, else the current name."""
    ManualRx = apps.get_model('insurance', 'InsuranceClaimManualRx')
    Audit = apps.get_model('insurance', 'InsuranceAuditEvent')

    originals = {}
    for ev in (Audit.objects
               .filter(action='manual_edit')
               .order_by('claim_id', 'target_ref', 'id')
               .values('claim_id', 'target_ref', 'before')):
        key = (ev['claim_id'], str(ev['target_ref'] or ''))
        if key in originals:
            continue
        before = ev.get('before') or {}
        name = before.get('patient_name') if isinstance(before, dict) else None
        if name:
            originals[key] = name

    to_update = []
    for m in ManualRx.objects.all().only(
            'id', 'claim_id', 'softech_docnumber', 'patient_name', 'softech_patient_name'):
        if m.softech_patient_name:
            continue
        key = (m.claim_id, str(m.softech_docnumber or ''))
        m.softech_patient_name = originals.get(key) or m.patient_name or ''
        to_update.append(m)
    for i in range(0, len(to_update), 1000):
        ManualRx.objects.bulk_update(to_update[i:i + 1000], ['softech_patient_name'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('insurance', '0026_prescription_softech_patient_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='insuranceclaimmanualrx',
            name='softech_patient_name',
            field=models.CharField(blank=True, max_length=200,
                                   verbose_name='اسم المريض (سوفتك الأصلي)'),
        ),
        migrations.RunPython(backfill, noop),
    ]
