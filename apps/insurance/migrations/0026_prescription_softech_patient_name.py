from django.db import migrations, models


def backfill_original_name(apps, schema_editor):
    """
    Seed softech_patient_name with the TRUE Softech original:
      * if the prescription's name was edited before, the earliest patient_edit
        audit's before.patient_name is the original;
      * otherwise the current patient_name IS the original (never edited).
    """
    Prescription = apps.get_model('insurance', 'InsuranceClaimPrescription')
    Audit = apps.get_model('insurance', 'InsuranceAuditEvent')

    # earliest patient_edit before-name per (claim_id, docnumber)
    originals = {}
    for ev in (Audit.objects
               .filter(action='patient_edit')
               .order_by('claim_id', 'target_ref', 'id')
               .values('claim_id', 'target_ref', 'before')):
        key = (ev['claim_id'], str(ev['target_ref'] or ''))
        if key in originals:
            continue  # keep the earliest only
        before = ev.get('before') or {}
        name = before.get('patient_name') if isinstance(before, dict) else None
        if name:
            originals[key] = name

    to_update = []
    for rx in Prescription.objects.all().only(
            'id', 'claim_id', 'softech_docnumber', 'patient_name', 'softech_patient_name'):
        if rx.softech_patient_name:
            continue
        key = (rx.claim_id, str(rx.softech_docnumber or ''))
        rx.softech_patient_name = originals.get(key) or rx.patient_name or ''
        to_update.append(rx)
    for i in range(0, len(to_update), 1000):
        Prescription.objects.bulk_update(to_update[i:i + 1000], ['softech_patient_name'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('insurance', '0025_patient_name_trgm_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='insuranceclaimprescription',
            name='softech_patient_name',
            field=models.CharField(blank=True, max_length=200,
                                   verbose_name='اسم المريض (سوفتك الأصلي)'),
        ),
        migrations.RunPython(backfill_original_name, noop),
    ]
