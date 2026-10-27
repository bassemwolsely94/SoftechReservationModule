"""
Idempotent migration — safe to run even when the shared DB already has some
of these objects created from an earlier worktree run.

Strategy:
  * CreateModel  → SeparateDatabaseAndState + RunSQL "CREATE TABLE IF NOT EXISTS"
  * RenameField  → SeparateDatabaseAndState + RunSQL conditional DO-block
  * AddField     → SeparateDatabaseAndState + RunSQL "ADD COLUMN IF NOT EXISTS"
  * AlterField (choices only) → no SQL generated; keep normal operation
  * M2M tables   → RunSQL "CREATE TABLE IF NOT EXISTS"
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('branches', '0001_initial'),
        ('users', '0007_alter_rolemoduleaccess_id_alter_userbranchaccess_id'),
    ]

    operations = [

        # ── 1. ERPUser table ───────────────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='ERPUser',
                    fields=[
                        ('id',          models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('username',    models.CharField(db_index=True, max_length=50, unique=True, verbose_name='اسم المستخدم')),
                        ('user_id',     models.CharField(blank=True, db_index=True, max_length=50, verbose_name='رقم المستخدم في ERP')),
                        ('full_name',   models.CharField(blank=True, max_length=150, verbose_name='الاسم الكامل')),
                        ('branch_code', models.CharField(blank=True, max_length=20, verbose_name='كود الفرع')),
                        ('is_active',   models.BooleanField(default=True, verbose_name='نشط')),
                        ('synced_at',   models.DateTimeField(auto_now=True, verbose_name='آخر مزامنة')),
                    ],
                    options={
                        'verbose_name': 'مستخدم ERP',
                        'verbose_name_plural': 'مستخدمو ERP',
                        'ordering': ['username'],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        -- Create table (no-op if already exists from worktree)
                        CREATE TABLE IF NOT EXISTS "users_erpuser" (
                            "id"          bigserial    NOT NULL PRIMARY KEY,
                            "username"    varchar(50)  NOT NULL UNIQUE,
                            "user_id"     varchar(50)  NOT NULL DEFAULT '',
                            "full_name"   varchar(150) NOT NULL DEFAULT '',
                            "branch_code" varchar(20)  NOT NULL DEFAULT '',
                            "is_active"   boolean      NOT NULL DEFAULT true,
                            "synced_at"   timestamptz  NOT NULL DEFAULT now()
                        );

                        -- Add any columns that the older worktree version may have omitted
                        ALTER TABLE "users_erpuser"
                            ADD COLUMN IF NOT EXISTS "user_id"     varchar(50)  NOT NULL DEFAULT '';
                        ALTER TABLE "users_erpuser"
                            ADD COLUMN IF NOT EXISTS "full_name"   varchar(150) NOT NULL DEFAULT '';
                        ALTER TABLE "users_erpuser"
                            ADD COLUMN IF NOT EXISTS "branch_code" varchar(20)  NOT NULL DEFAULT '';

                        -- Indexes (idempotent)
                        CREATE INDEX IF NOT EXISTS "users_erpuser_username_like"
                            ON "users_erpuser" ("username" varchar_pattern_ops);
                        CREATE INDEX IF NOT EXISTS "users_erpuser_user_id_idx"
                            ON "users_erpuser" ("user_id");
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 2. Rename has_global_access → access_all_branches ─────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name='staffprofile',
                    old_name='has_global_access',
                    new_name='access_all_branches',
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        DO $$
                        BEGIN
                            -- Only rename if old name exists AND new name does not yet exist
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'users_staffprofile'
                                  AND column_name = 'has_global_access'
                            ) AND NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'users_staffprofile'
                                  AND column_name = 'access_all_branches'
                            ) THEN
                                ALTER TABLE "users_staffprofile"
                                    RENAME COLUMN "has_global_access" TO "access_all_branches";
                            END IF;
                        END $$;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3a. erp_user FK ───────────────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffprofile',
                    name='erp_user',
                    field=models.OneToOneField(
                        blank=True, null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='staff_profile',
                        to='users.erpuser',
                        verbose_name='مستخدم ERP',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "users_staffprofile"
                            ADD COLUMN IF NOT EXISTS "erp_user_id" bigint
                            CONSTRAINT "users_staffprofile_erp_user_id_fk"
                            REFERENCES "users_erpuser"("id")
                            DEFERRABLE INITIALLY DEFERRED;
                        CREATE UNIQUE INDEX IF NOT EXISTS "users_staffprofile_erp_user_id_uniq"
                            ON "users_staffprofile" ("erp_user_id")
                            WHERE "erp_user_id" IS NOT NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3b. can_see_all_customers ─────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffprofile',
                    name='can_see_all_customers',
                    field=models.BooleanField(
                        default=False,
                        verbose_name='يرى جميع العملاء',
                        help_text='يسمح له برؤية عملاء الفروع الأخرى',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "users_staffprofile" ADD COLUMN IF NOT EXISTS "can_see_all_customers" boolean NOT NULL DEFAULT false;',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3c. can_see_customer_phone ────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffprofile',
                    name='can_see_customer_phone',
                    field=models.BooleanField(default=True, verbose_name='يرى رقم هاتف العميل'),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "users_staffprofile" ADD COLUMN IF NOT EXISTS "can_see_customer_phone" boolean NOT NULL DEFAULT true;',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3d. created_at ────────────────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffprofile',
                    name='created_at',
                    field=models.DateTimeField(auto_now_add=True, null=True, verbose_name='تاريخ الإنشاء'),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "users_staffprofile" ADD COLUMN IF NOT EXISTS "created_at" timestamptz NULL;',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3e. updated_at ────────────────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffprofile',
                    name='updated_at',
                    field=models.DateTimeField(auto_now=True, verbose_name='آخر تعديل'),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "users_staffprofile" ADD COLUMN IF NOT EXISTS "updated_at" timestamptz NOT NULL DEFAULT now();',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3f. allowed_branches M2M ──────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffprofile',
                    name='allowed_branches',
                    field=models.ManyToManyField(
                        blank=True,
                        related_name='staff_allowed',
                        to='branches.branch',
                        verbose_name='فروع إضافية مسموح بها',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS "users_staffprofile_allowed_branches" (
                            "id"              bigserial NOT NULL PRIMARY KEY,
                            "staffprofile_id" bigint    NOT NULL REFERENCES "users_staffprofile"("id") DEFERRABLE INITIALLY DEFERRED,
                            "branch_id"       bigint    NOT NULL REFERENCES "branches_branch"("id") DEFERRABLE INITIALLY DEFERRED,
                            CONSTRAINT "users_staffprofile_allowed_uniq" UNIQUE ("staffprofile_id", "branch_id")
                        );
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3g. restricted_branches M2M ───────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='staffprofile',
                    name='restricted_branches',
                    field=models.ManyToManyField(
                        blank=True,
                        related_name='staff_restricted',
                        to='branches.branch',
                        verbose_name='فروع محظورة',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS "users_staffprofile_restricted_branches" (
                            "id"              bigserial NOT NULL PRIMARY KEY,
                            "staffprofile_id" bigint    NOT NULL REFERENCES "users_staffprofile"("id") DEFERRABLE INITIALLY DEFERRED,
                            "branch_id"       bigint    NOT NULL REFERENCES "branches_branch"("id") DEFERRABLE INITIALLY DEFERRED,
                            CONSTRAINT "users_staffprofile_restricted_uniq" UNIQUE ("staffprofile_id", "branch_id")
                        );
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),

        # ── 3h. AlterField access_all_branches (update verbose_name/help_text) -
        # AlterField on a BooleanField generates no SQL — safe to leave as-is.
        migrations.AlterField(
            model_name='staffprofile',
            name='access_all_branches',
            field=models.BooleanField(
                default=False,
                help_text='يتجاوز قيود الفرع بغض النظر عن الدور',
                verbose_name='وصول شامل لجميع الفروع',
            ),
        ),

        # ── 4. Add 'users' module to RoleModuleAccess choices ─────────────────
        # AlterField on a CharField choices= generates NO SQL — pure state change.
        migrations.AlterField(
            model_name='rolemoduleaccess',
            name='module',
            field=models.CharField(
                choices=[
                    ('reservations', 'الحجوزات'),
                    ('demand',       'طلبات العملاء / المبيعات المفقودة'),
                    ('transfers',    'طلبات التحويل'),
                    ('customers',    'العملاء'),
                    ('catalog',      'كتالوج الأدوية'),
                    ('dashboard',    'لوحة المتابعة'),
                    ('sync',         'مزامنة البيانات'),
                    ('purchasing',   'لوحة المشتريات'),
                    ('chronic',      'الأدوية المزمنة'),
                    ('admin',        'إدارة النظام'),
                    ('users',        'إدارة المستخدمين'),
                ],
                db_index=True,
                max_length=30,
            ),
        ),

        # ── 5. UserActivityLog table ───────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='UserActivityLog',
                    fields=[
                        ('id',         models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('action',     models.CharField(
                            choices=[
                                ('login_success',       'دخول ناجح'),
                                ('login_failed',        'محاولة دخول فاشلة'),
                                ('password_changed',    'تغيير كلمة المرور'),
                                ('password_reset',      'إعادة تعيين كلمة المرور بواسطة المدير'),
                                ('role_changed',        'تغيير الدور'),
                                ('branch_changed',      'تغيير الفرع'),
                                ('activated',           'تفعيل الحساب'),
                                ('deactivated',         'تعطيل الحساب'),
                                ('permissions_changed', 'تغيير الصلاحيات'),
                                ('created',             'إنشاء المستخدم'),
                            ],
                            max_length=30,
                            verbose_name='الإجراء',
                        )),
                        ('old_value',  models.JSONField(blank=True, null=True, verbose_name='القيمة القديمة')),
                        ('new_value',  models.JSONField(blank=True, null=True, verbose_name='القيمة الجديدة')),
                        ('note',       models.TextField(blank=True, verbose_name='ملاحظة')),
                        ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='عنوان IP')),
                        ('created_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت الحدث')),
                        ('changed_by', models.ForeignKey(
                            blank=True, null=True,
                            on_delete=django.db.models.deletion.SET_NULL,
                            related_name='user_audit_actions',
                            to='users.staffprofile',
                            verbose_name='بواسطة',
                        )),
                        ('target_user', models.ForeignKey(
                            blank=True, null=True,
                            on_delete=django.db.models.deletion.SET_NULL,
                            related_name='user_activity_logs',
                            to='users.staffprofile',
                            verbose_name='المستخدم المستهدف',
                        )),
                    ],
                    options={
                        'verbose_name': 'سجل نشاط المستخدم',
                        'verbose_name_plural': 'سجلات نشاط المستخدمين',
                        'ordering': ['-created_at'],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS "users_useractivitylog" (
                            "id"          bigserial    NOT NULL PRIMARY KEY,
                            "action"      varchar(30)  NOT NULL,
                            "old_value"   jsonb        NULL,
                            "new_value"   jsonb        NULL,
                            "note"        text         NOT NULL DEFAULT '',
                            "ip_address"  inet         NULL,
                            "created_at"  timestamptz  NOT NULL DEFAULT now(),
                            "changed_by_id"  bigint    NULL REFERENCES "users_staffprofile"("id") DEFERRABLE INITIALLY DEFERRED,
                            "target_user_id" bigint    NULL REFERENCES "users_staffprofile"("id") DEFERRABLE INITIALLY DEFERRED
                        );
                        CREATE INDEX IF NOT EXISTS "users_useractivitylog_created_at_idx"
                            ON "users_useractivitylog" ("created_at" DESC);
                        CREATE INDEX IF NOT EXISTS "users_useractivitylog_changed_by_id_idx"
                            ON "users_useractivitylog" ("changed_by_id");
                        CREATE INDEX IF NOT EXISTS "users_useractivitylog_target_user_id_idx"
                            ON "users_useractivitylog" ("target_user_id");
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
