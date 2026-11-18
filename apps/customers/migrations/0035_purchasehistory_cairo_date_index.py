"""
Full project audit 2026-11-15, PERF-2: the sales mirror had no index usable by date filters.

Every `invoice_date__date…` lookup (113 call sites: dashboard, freshness bar, analytics, forecasting,
follow-ups…) compiles to `(invoice_date AT TIME ZONE 'Africa/Cairo')::date`, so a plain invoice_date
index would not be used. This expression index matches that SQL exactly; doc_code (115 sale / 30 return)
is the second column most of them add. `timezone(text, timestamptz)` is IMMUTABLE, so it is indexable.

CONCURRENTLY: the table is ~1.7M rows / 1.1 GB and written every few minutes by the sales sync; a plain
CREATE INDEX would block those writes while it builds. Hence atomic = False.
"""
from django.db import migrations

INDEX = 'customers_ph_cairo_date_doc_idx'


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('customers', '0034_consent_from_refill_opt_outs'),
    ]

    operations = [
        migrations.RunSQL(
            sql=(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON customers_purchasehistory '
                 "(((invoice_date AT TIME ZONE 'Africa/Cairo')::date), doc_code)"),
            reverse_sql=f'DROP INDEX CONCURRENTLY IF EXISTS {INDEX}',
        ),
    ]
