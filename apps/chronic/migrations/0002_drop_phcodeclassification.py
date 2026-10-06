"""
Drop the PhcodeClassification model.

stktransm.phcode = customer personcode (e.g. 04HD1006 = branch-HD-serial),
NOT a pharmaceutical ATC code. Items are classified directly per-item by
linking them to an ActiveIngredient via ItemIngredientMap.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('chronic', '0001_chronic_module_and_purchase_history_erp_fields'),
    ]

    operations = [
        migrations.DeleteModel(name='PhcodeClassification'),
    ]
