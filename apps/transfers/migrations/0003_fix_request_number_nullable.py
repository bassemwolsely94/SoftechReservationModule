"""
Empty migration — exists only to resolve the leaf-node conflict between
0003_fix_branch_indexes and an older version of this file.
The actual schema fix is in 0004_fix_request_number_nullable.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('transfers', '0003_fix_branch_indexes'),
    ]

    operations = []
