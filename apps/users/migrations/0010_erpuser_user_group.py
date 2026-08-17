"""
Migration 0010 — ERPUser.user_group

The DB column already exists (created by the worktree with NOT NULL and no
default).  We need two things:
  1. Django model state: AddField so Django knows about user_group.
  2. DB: set a column default of '' so existing / new rows without an explicit
     value satisfy the NOT NULL constraint.

SeparateDatabaseAndState keeps both in sync without trying to CREATE a column
that already exists.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0009_alter_staffprofile_options_alter_staffprofile_branch_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Tell Django's ORM that user_group exists on ERPUser
            state_operations=[
                migrations.AddField(
                    model_name='erpuser',
                    name='user_group',
                    field=models.CharField(
                        blank=True, default='', max_length=50,
                        verbose_name='مجموعة المستخدم',
                    ),
                ),
            ],
            # In production the column was created by the worktree without a default.
            # In a fresh test database the column does not exist yet.
            # Use a DO block to handle both cases idempotently.
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'users_erpuser'
                                  AND column_name = 'user_group'
                            ) THEN
                                -- Fresh DB (e.g. test runner): create the column.
                                ALTER TABLE "users_erpuser"
                                    ADD COLUMN "user_group" VARCHAR(50) NOT NULL DEFAULT '';
                            ELSE
                                -- Production DB: column already exists, just set the default.
                                ALTER TABLE "users_erpuser"
                                    ALTER COLUMN "user_group" SET DEFAULT '';
                                UPDATE "users_erpuser"
                                   SET "user_group" = ''
                                 WHERE "user_group" IS NULL;
                            END IF;
                        END $$;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
