# Fold Arabic-Indic / Persian digits in the learned spellings, matching the new
# apps.shortage.matching._normalize ("اوميز ١٠" == "اوميز 10"). Rows that become identical
# are merged (use_count summed) so the unique (normalized, vendor_code, item) holds.

from django.db import migrations

_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def fold(apps, schema_editor):
    ItemAlias = apps.get_model('catalog', 'ItemAlias')
    for a in ItemAlias.objects.all().order_by('id'):
        folded = a.normalized.translate(_DIGITS)
        if folded == a.normalized:
            continue
        twin = ItemAlias.objects.filter(normalized=folded, vendor_code=a.vendor_code,
                                        item_id=a.item_id).exclude(pk=a.pk).first()
        if twin:
            twin.use_count += a.use_count
            twin.save(update_fields=['use_count'])
            a.delete()
        else:
            a.normalized = folded
            a.save(update_fields=['normalized'])


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0039_alias_learning'),
    ]

    operations = [
        migrations.RunPython(fold, migrations.RunPython.noop),
    ]
