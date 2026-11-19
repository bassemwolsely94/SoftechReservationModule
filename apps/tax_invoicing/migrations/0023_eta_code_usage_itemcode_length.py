from django.db import migrations, models


class Migration(migrations.Migration):
    """EtaCodeUsage.itemcode as long as item_code: long EGS tails (two codes joined) were cut to 10 characters.
    The next eta_codes.match (after each fetch) writes them whole."""

    dependencies = [('tax_invoicing', '0022_egs_sheet_whole_workbook')]

    operations = [
        migrations.AlterField(
            model_name='etacodeusage',
            name='itemcode',
            field=models.CharField(blank=True, db_index=True, default='', max_length=100),
        ),
    ]
