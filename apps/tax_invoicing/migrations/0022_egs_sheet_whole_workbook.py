from django.db import migrations, models


def mark_whole(apps, schema_editor):
    """Seeds and fetched copies are the owner's own file; builds so far re-saved it (not whole)."""
    Version = apps.get_model('tax_invoicing', 'TaxEgsSheetVersion')
    Version.objects.filter(source__in=['seed', 'fetch']).update(whole_workbook=True)


class Migration(migrations.Migration):

    dependencies = [
        ('tax_invoicing', '0021_agent_file_job'),
    ]

    operations = [
        migrations.AddField(
            model_name='taxegssheetversion',
            name='whole_workbook',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunPython(mark_whole, migrations.RunPython.noop),
    ]
