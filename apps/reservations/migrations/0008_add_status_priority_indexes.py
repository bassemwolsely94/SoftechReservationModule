"""
Migration: reservations 0016  (logically after 0015 in this codebase)

Add targeted indexes to improve query performance:

  Reservation
  -----------
  • status (db_index=True)       — queries filtered by status alone were doing full scans
  • priority (db_index=True)     — dashboard urgent count, kanban priority filter
  • (status, -created_at)        — list view filtered by status + ordered by date
  • (branch, -created_at)        — branch-scoped list view

  ReservationActivity
  -------------------
  • is_deleted (db_index=True)   — chatter fetches filter is_deleted=False per reservation

Note: AlterField operations are idempotent. The compound AddIndex calls use
      CREATE INDEX IF NOT EXISTS so they are safe to run even if the index
      was already created from a worktree/development migration.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0015_reservation_order_source_fulfillment_images'),
    ]

    operations = [
        # ── Reservation field-level indexes ───────────────────────────────────
        migrations.AlterField(
            model_name='reservation',
            name='status',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('pending',   'قيد الانتظار — انتظار مخزون'),
                    ('available', 'المخزون متاح — اتصل بالعميل'),
                    ('contacted', 'تم التواصل — العميل على علم'),
                    ('confirmed', 'مؤكد — العميل قادم'),
                    ('fulfilled', 'تم التسليم — الصنف صُرف'),
                    ('cancelled', 'ملغي'),
                    ('expired',   'منتهي — لا استجابة'),
                ],
                default='pending',
                db_index=True,
            ),
        ),
        migrations.AlterField(
            model_name='reservation',
            name='priority',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('normal',  'عادي'),
                    ('urgent',  'عاجل'),
                    ('chronic', 'مريض مزمن'),
                ],
                default='normal',
                db_index=True,
            ),
        ),
        # ── Reservation compound indexes (IF NOT EXISTS — safe to re-run) ─────
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS res_status_createdat_idx
                    ON reservations_reservation (status, created_at DESC);
            """,
            reverse_sql='DROP INDEX IF EXISTS res_status_createdat_idx;',
        ),
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS res_branch_createdat_idx
                    ON reservations_reservation (branch_id, created_at DESC);
            """,
            reverse_sql='DROP INDEX IF EXISTS res_branch_createdat_idx;',
        ),
        # ── ReservationActivity ───────────────────────────────────────────────
        migrations.AlterField(
            model_name='reservationactivity',
            name='is_deleted',
            field=models.BooleanField(default=False, db_index=True, verbose_name='محذوف'),
        ),
    ]
