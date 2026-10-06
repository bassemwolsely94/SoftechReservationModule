from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0018_alter_item_branch_trans_alter_item_customer_trans_and_more'),
        ('users', '0001_initial'),
    ]

    operations = [
        # ── CatalogVariantGroup ──────────────────────────────────────────────
        migrations.CreateModel(
            name='CatalogVariantGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='الاسم (إنجليزي)')),
                ('name_ar', models.CharField(blank=True, max_length=255, verbose_name='الاسم (عربي)')),
                ('description', models.TextField(blank=True, verbose_name='وصف')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='variant_groups_created', to='users.staffprofile', verbose_name='أنشئ بواسطة')),
            ],
            options={
                'verbose_name': 'مجموعة متغيرات',
                'verbose_name_plural': 'مجموعات المتغيرات',
                'ordering': ['name'],
            },
        ),
        # ── VariantMember ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='VariantMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('variant_label', models.CharField(blank=True, help_text='مثل: 500mg، شراب، 10 أقراص', max_length=100, verbose_name='تسمية المتغير')),
                ('sort_order', models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='members', to='catalog.catalogvariantgroup', verbose_name='المجموعة')),
                ('item', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='variant_membership', to='catalog.item', verbose_name='الصنف')),
            ],
            options={
                'verbose_name': 'متغير',
                'verbose_name_plural': 'المتغيرات',
                'ordering': ['sort_order', 'variant_label'],
            },
        ),
        # ── ProductBundle ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductBundle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='اسم الباقة (إنجليزي)')),
                ('name_ar', models.CharField(blank=True, max_length=255, verbose_name='اسم الباقة (عربي)')),
                ('description', models.TextField(blank=True, verbose_name='وصف')),
                ('is_active', models.BooleanField(db_index=True, default=True, verbose_name='نشط')),
                ('discount_type', models.CharField(choices=[('pct', 'خصم نسبة مئوية'), ('fixed', 'خصم ثابت'), ('none', 'بدون خصم')], default='none', max_length=10, verbose_name='نوع الخصم')),
                ('discount_value', models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name='قيمة الخصم')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bundles_created', to='users.staffprofile', verbose_name='أنشئ بواسطة')),
            ],
            options={
                'verbose_name': 'باقة منتجات',
                'verbose_name_plural': 'باقات المنتجات',
                'ordering': ['name'],
            },
        ),
        # ── BundleItem ───────────────────────────────────────────────────────
        migrations.CreateModel(
            name='BundleItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(decimal_places=2, default=1, max_digits=8, verbose_name='الكمية')),
                ('bundle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='catalog.productbundle', verbose_name='الباقة')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bundle_memberships', to='catalog.item', verbose_name='الصنف')),
            ],
            options={
                'verbose_name': 'صنف في الباقة',
                'verbose_name_plural': 'أصناف الباقة',
                'unique_together': {('bundle', 'item')},
            },
        ),
    ]
