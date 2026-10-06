"""
Migration 0010 — Remove duplicate PurchaseHistory records from old sync runs
and normalize softech_invoice_id to use integer docnumbers.

Background
----------
Two different sync code versions produced incompatible softech_invoice_id formats
for the same SOFTECH invoices:

  OLD (wrong) format  →  "160-115-500123-20260510"  (docnumber as integer string)
  NEW (correct) format → "160-115-500123.0-20260510" (docnumber as float string)

Because the IDs differ, `bulk_create(update_conflicts=True)` could NOT deduplicate
them, so both records were stored.  The result: ~138,797 ghost records (old format)
coexisting with ~71,268 correct records (new format), producing ~2.5× revenue
inflation across all analytics dashboards.

The decimal-format records (71,268) match SOFTECH exactly:
  May 1–18 decimal count = 14,294  ←→  SOFTECH عمليات = 14,294  ✓
  May 1–18 decimal net revenue ≈ 4,753,160  ←→  SOFTECH = 4,753,160.51  ✓

Steps:
  1. Delete all non-decimal records (old format, 138,797 rows).
     ON CASCADE DELETE removes the linked PurchaseHistoryLine rows.
  2. Rename remaining decimal IDs "…NNN.0-DATE" → "…NNN-DATE" so all IDs
     use a clean integer format going forward.
     (All decimal IDs have exactly ".0-", never ".5-" or ".25-" — confirmed by audit.)
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0009_customer_order_branch_code_and_more'),
    ]

    operations = [
        # Step 1 — drop ghost records (old format, no decimal point in ID).
        # Delete lines first (FK is application-level CASCADE, not DB-level),
        # then delete the orphaned headers.
        migrations.RunSQL(
            sql="""
                DELETE FROM customers_purchasehistoryline
                WHERE purchase_id IN (
                    SELECT id FROM customers_purchasehistory
                    WHERE softech_invoice_id NOT LIKE '%.%'
                );
                DELETE FROM customers_purchasehistory
                WHERE softech_invoice_id NOT LIKE '%.%';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Step 2 — normalize remaining decimal IDs to integer format.
        # "branchcode-doccode-NNN.0-YYYYMMDD"  →  "branchcode-doccode-NNN-YYYYMMDD"
        # Uses regexp_replace to strip ".digits" immediately before the trailing
        # "-YYYYMMDD" (8-digit date) portion of the ID.
        migrations.RunSQL(
            sql=r"""
                UPDATE customers_purchasehistory
                SET softech_invoice_id =
                    regexp_replace(softech_invoice_id, '\.\d+(-\d{8})$', '\1')
                WHERE softech_invoice_id ~ '\.\d+-\d{8}$';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
