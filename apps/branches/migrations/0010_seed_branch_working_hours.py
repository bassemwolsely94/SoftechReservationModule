"""Branch working hours given by the owner on 2026-10-26 (doc 32, check 9). Editable afterwards
in Settings → branches; this only fills branches whose hours are still empty."""
from django.db import migrations

CALL_CENTER_DOCS = ['110', '125', '170']   # transfers to branches + expense issues (owner, 2026-10-26)

HOURS = {
    '160': {'is_24h': True, 'working_hours': []},
    '130': {'working_hours': [{'from': '08:00', 'to': '01:00'}]},
    '140': {'working_hours': [{'from': '08:00', 'to': '01:00'}]},
    '150': {'working_hours': [{'from': '08:00', 'to': '01:00'}]},
    '170': {'working_hours': [{'from': '08:00', 'to': '00:30'}]},
    # HQ: warehouse mainly 08:00–18:00, overtime until 21:00; the call center (09:00–24:00)
    # dispenses orders from the HQ server to every branch.
    '100': {'working_hours': [
        {'from': '08:00', 'to': '21:00', 'label': 'المخزن الرئيسي'},
        {'from': '09:00', 'to': '24:00', 'label': 'الكول سنتر', 'doccodes': CALL_CENTER_DOCS},
    ]},
}


def seed(apps, schema_editor):
    Branch = apps.get_model('branches', 'Branch')
    BranchSettings = apps.get_model('branches', 'BranchSettings')
    for code, values in HOURS.items():
        b = Branch.objects.filter(softech_branch_id=code).first()
        if b is None:
            continue
        s, _ = BranchSettings.objects.get_or_create(branch=b)
        if s.is_24h or s.working_hours:
            continue
        s.is_24h = values.get('is_24h', False)
        s.working_hours = values['working_hours']
        s.save(update_fields=['is_24h', 'working_hours'])


class Migration(migrations.Migration):
    dependencies = [('branches', '0009_branchsettings_is_24h_branchsettings_working_hours')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
