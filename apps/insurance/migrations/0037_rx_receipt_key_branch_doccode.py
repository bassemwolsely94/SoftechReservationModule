"""Audit S-8 / D-10 (owner-approved 2026-11-19): a claim prescription is identified by
(claim, branch, doccode, docnumber), not (claim, docnumber).

1. Add InsuranceClaimPrescription.softech_doccode (blank default).
2. Backfill it for existing rows from the local caches only — no SOFTECH access:
   MotalbaCache first, then CompaniesItemsCache, matching (branch, docnumber, docdate) and
   only where exactly one doccode fits. Office DB check (read-only, 2026-11-19): 19,744 rows;
   16,854 resolve from MotalbaCache, 2,878 more from CompaniesItemsCache, 12 stay blank.
3. Widen unique_together. Every existing row already satisfied the narrower
   (claim, docnumber) key (office DB: 0 duplicates), so the wider key cannot fail.
"""
from django.db import migrations, models

_BACKFILL = """
UPDATE insurance_insuranceclaimprescription p
   SET softech_doccode = sub.dc
  FROM (SELECT p2.id, MIN(c.doccode) AS dc
          FROM insurance_insuranceclaimprescription p2
          JOIN {cache} c
            ON c.branchcode = p2.softech_branchcode
           AND c.docnumber  = p2.softech_docnumber
           AND c.docdate    = p2.softech_docdate
         WHERE p2.softech_doccode = ''
         GROUP BY p2.id
        HAVING COUNT(DISTINCT c.doccode) = 1) sub
 WHERE p.id = sub.id
"""


class Migration(migrations.Migration):

    dependencies = [
        ('insurance', '0036_date_edit_motalba_old_dates'),
    ]

    operations = [
        migrations.AddField(
            model_name='insuranceclaimprescription',
            name='softech_doccode',
            field=models.CharField(blank=True, db_default='', default='', max_length=3, verbose_name='كود المستند'),
        ),
        migrations.RunSQL(_BACKFILL.format(cache='insurance_motalbacache'), migrations.RunSQL.noop),
        migrations.RunSQL(_BACKFILL.format(cache='insurance_companiesitemscache'), migrations.RunSQL.noop),
        migrations.AlterUniqueTogether(
            name='insuranceclaimprescription',
            unique_together={('claim', 'softech_branchcode', 'softech_doccode', 'softech_docnumber')},
        ),
    ]
