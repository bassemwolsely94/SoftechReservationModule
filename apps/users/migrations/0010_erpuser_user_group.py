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
            # The column is already there — just ensure it accepts empty strings
            # by setting a DB-level default so the NOT NULL constraint won't fire
            # when the field is omitted in older code paths.
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        -- Column was created NOT NULL without a default in the worktree.
                        -- Give it a default so inserts that omit it don't fail.
                        ALTER TABLE "users_erpuser"
                            ALTER COLUMN "user_group" SET DEFAULT '';

                        -- Back-fill any existing NULL values (safety net).
                        UPDATE "users_erpuser"
                           SET "user_group" = ''
                         WHERE "user_group" IS NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
