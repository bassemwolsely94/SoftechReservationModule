"""
apps/product_experience/migrations/0001_initial.py
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import apps.product_experience.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog',  '0005_alter_item_phcode'),
        ('branches', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── ProductMapping ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductMapping',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',         models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                  related_name='mappings', to='catalog.item')),
                ('softech_id',   models.CharField(db_index=True, max_length=6)),
                ('external_code', models.CharField(blank=True, max_length=50)),
                ('barcode',      models.CharField(blank=True, db_index=True, max_length=30)),
                ('is_primary',   models.BooleanField(default=True)),
                ('sync_status',  models.CharField(
                    choices=[('synced','متزامن'),('pending','في الانتظار'),('error','خطأ')],
                    default='synced', max_length=10)),
                ('last_synced',  models.DateTimeField(blank=True, null=True)),
                ('notes',        models.CharField(blank=True, max_length=255)),
            ],
            options={'verbose_name': 'خريطة منتج', 'verbose_name_plural': 'خرائط المنتجات',
                     'ordering': ['-is_primary']},
        ),
        migrations.AlterUniqueTogether(
            name='productmapping',
            unique_together={('item', 'external_code')},
        ),
        migrations.AddIndex(
            model_name='productmapping',
            index=models.Index(fields=['barcode'], name='pe_mapping_barcode_idx'),
        ),

        # ── ProductMedia ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductMedia',
            fields=[
                ('id',          models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',        models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                 related_name='media', to='catalog.item')),
                ('media_type',  models.CharField(choices=[('image','صورة'),('video','فيديو'),
                                 ('pdf','ملف PDF'),('manual','نشرة / دليل')],
                                 default='image', max_length=10)),
                ('file',        models.FileField(upload_to=apps.product_experience.models._media_path)),
                ('thumbnail',   models.ImageField(blank=True,
                                 upload_to=apps.product_experience.models._thumb_path)),
                ('alt_text',    models.CharField(blank=True, max_length=255)),
                ('order',       models.PositiveSmallIntegerField(db_index=True, default=0)),
                ('is_primary',  models.BooleanField(db_index=True, default=False)),
                ('source',      models.CharField(
                    choices=[('manual_upload','رفع يدوي'),('erp_sync','مزامنة ERP'),
                             ('ai_generated','توليد آلي')],
                    default='manual_upload', max_length=20)),
                ('approved',    models.BooleanField(db_index=True, default=False)),
                ('uploaded_by', models.ForeignKey(blank=True, null=True,
                                 on_delete=django.db.models.deletion.SET_NULL,
                                 related_name='uploaded_media',
                                 to=settings.AUTH_USER_MODEL)),
                ('created_at',  models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'وسائط منتج', 'verbose_name_plural': 'وسائط المنتجات',
                     'ordering': ['order', '-is_primary', '-created_at']},
        ),
        migrations.AddIndex(
            model_name='productmedia',
            index=models.Index(fields=['item', 'is_primary'], name='pe_media_item_primary_idx'),
        ),
        migrations.AddIndex(
            model_name='productmedia',
            index=models.Index(fields=['item', 'approved', 'order'], name='pe_media_item_approved_idx'),
        ),

        # ── ProductContent ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductContent',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',             models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                      related_name='content', to='catalog.item')),
                ('display_name_ar',  models.CharField(blank=True, max_length=300,
                                      verbose_name='الاسم التجاري (عربي)')),
                ('display_name_en',  models.CharField(blank=True, max_length=300,
                                      verbose_name='الاسم التجاري (إنجليزي)')),
                ('short_description', models.TextField(blank=True, verbose_name='وصف مختصر')),
                ('long_description',  models.TextField(blank=True, verbose_name='وصف تفصيلي')),
                ('instructions',     models.TextField(blank=True, verbose_name='تعليمات الاستخدام')),
                ('storage',          models.TextField(blank=True, verbose_name='شروط التخزين')),
                ('usage',            models.TextField(blank=True, verbose_name='طريقة الاستخدام')),
                ('contraindications', models.TextField(blank=True, verbose_name='موانع الاستخدام')),
                ('benefits',         models.TextField(blank=True, verbose_name='الفوائد والاستخدامات')),
                ('marketing_text',   models.TextField(blank=True, verbose_name='النص التسويقي')),
                ('keywords',         models.TextField(blank=True, verbose_name='الكلمات المفتاحية')),
                ('faq',              models.JSONField(blank=True, default=list,
                                      verbose_name='الأسئلة الشائعة')),
                ('adherence_icons',  models.JSONField(blank=True, default=list,
                                      verbose_name='أيقونات الالتزام')),
                ('whatsapp_preview', models.TextField(blank=True, verbose_name='معاينة واتساب')),
                ('last_updated_by',  models.ForeignKey(blank=True, null=True,
                                      on_delete=django.db.models.deletion.SET_NULL,
                                      related_name='updated_contents',
                                      to=settings.AUTH_USER_MODEL)),
                ('updated_at',       models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'محتوى منتج', 'verbose_name_plural': 'محتويات المنتجات'},
        ),

        # ── ProductAttribute ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductAttribute',
            fields=[
                ('id',                   models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',                 models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                          related_name='attributes', to='catalog.item')),
                ('strength',             models.CharField(blank=True, max_length=100,
                                          verbose_name='التركيز / القوة')),
                ('concentration',        models.CharField(blank=True, max_length=100,
                                          verbose_name='التركيز للسوائل')),
                ('prescription_required', models.BooleanField(blank=True, null=True, default=None,
                                           verbose_name='يحتاج وصفة طبية')),
                ('special_warnings',     models.TextField(blank=True, verbose_name='تحذيرات خاصة')),
                ('flavor',               models.CharField(blank=True, max_length=100, verbose_name='النكهة')),
                ('color',                models.CharField(blank=True, max_length=100, verbose_name='اللون')),
                ('size',                 models.CharField(blank=True, max_length=50, verbose_name='الحجم / الوزن')),
                ('pack_size_label',      models.CharField(blank=True, max_length=100,
                                          verbose_name='مواصفات العبوة')),
                ('count_per_pack',       models.PositiveSmallIntegerField(blank=True, null=True,
                                          verbose_name='العدد في العبوة')),
                ('temperature_storage',  models.CharField(
                    blank=True, max_length=20,
                    choices=[('room','حفظ بدرجة حرارة الغرفة (أقل من 25°م)'),
                             ('cool','حفظ في مكان بارد (8-15°م)'),
                             ('refrigerated','حفظ في الثلاجة (2-8°م)'),
                             ('frozen','حفظ مجمداً (أقل من -18°م)')],
                    verbose_name='درجة حرارة التخزين')),
                ('shelf_life_months',    models.PositiveSmallIntegerField(blank=True, null=True,
                                          verbose_name='مدة الصلاحية (شهور)')),
                ('updated_at',           models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'خصائص منتج', 'verbose_name_plural': 'خصائص المنتجات'},
        ),

        # ── ProductSEO ────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductSEO',
            fields=[
                ('id',             models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',           models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                    related_name='seo', to='catalog.item')),
                ('slug',           models.SlugField(allow_unicode=True, max_length=250, unique=True)),
                ('title_ar',       models.CharField(blank=True, max_length=200,
                                    verbose_name='عنوان الصفحة (عربي)')),
                ('title_en',       models.CharField(blank=True, max_length=200,
                                    verbose_name='عنوان الصفحة (إنجليزي)')),
                ('description_ar', models.TextField(blank=True, max_length=320,
                                    verbose_name='وصف الصفحة (عربي)')),
                ('description_en', models.TextField(blank=True, max_length=320,
                                    verbose_name='وصف الصفحة (إنجليزي)')),
                ('keywords',       models.TextField(blank=True, verbose_name='كلمات مفتاحية')),
                ('canonical',      models.URLField(blank=True, verbose_name='الرابط الأصلي')),
                ('og_image',       models.ImageField(blank=True,
                                    upload_to=apps.product_experience.models._og_path,
                                    verbose_name='صورة المشاركة')),
                ('updated_at',     models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'SEO المنتج', 'verbose_name_plural': 'SEO المنتجات'},
        ),

        # ── ProductExperience ─────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductExperience',
            fields=[
                ('id',               models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',             models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                      related_name='experience', to='catalog.item')),
                ('views',            models.PositiveIntegerField(default=0)),
                ('shares',           models.PositiveIntegerField(default=0)),
                ('wishlist_adds',    models.PositiveIntegerField(default=0)),
                ('reservations',     models.PositiveIntegerField(default=0)),
                ('refills',          models.PositiveIntegerField(default=0)),
                ('call_requests',    models.PositiveIntegerField(default=0)),
                ('popularity_score', models.FloatField(db_index=True, default=0.0)),
                ('last_interaction', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('updated_at',       models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'تجربة منتج', 'verbose_name_plural': 'تجارب المنتجات',
                     'ordering': ['-popularity_score']},
        ),

        # ── ProductRelation ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='ProductRelation',
            fields=[
                ('id',            models.BigAutoField(auto_created=True, primary_key=True)),
                ('from_item',     models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                   related_name='relations_from', to='catalog.item')),
                ('to_item',       models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                   related_name='relations_to', to='catalog.item')),
                ('relation_type', models.CharField(
                    choices=[('frequently_bought','غالباً ما يشترى معه'),
                             ('recommended','موصى به'),('substitute','بديل'),
                             ('refill','إعادة طلب'),('companion','مكمل'),
                             ('starter_pack','حزمة البداية')],
                    db_index=True, max_length=20)),
                ('order',      models.PositiveSmallIntegerField(default=0)),
                ('is_active',  models.BooleanField(db_index=True, default=True)),
                ('added_by',   models.ForeignKey(blank=True, null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                to=settings.AUTH_USER_MODEL)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'علاقة منتج', 'verbose_name_plural': 'علاقات المنتجات',
                     'ordering': ['relation_type', 'order']},
        ),
        migrations.AlterUniqueTogether(
            name='productrelation',
            unique_together={('from_item', 'to_item', 'relation_type')},
        ),

        # ── ProductAvailabilityCache ──────────────────────────────────────────
        migrations.CreateModel(
            name='ProductAvailabilityCache',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',         models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                  related_name='availability_cache', to='catalog.item')),
                ('branch',       models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                  related_name='product_availability', to='branches.branch')),
                ('status',       models.CharField(
                    choices=[('available','متاح'),('limited','كميات محدودة'),
                             ('unavailable','غير متاح')],
                    db_index=True, default='unavailable', max_length=15)),
                ('last_checked', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'توافر المنتج', 'verbose_name_plural': 'توافر المنتجات'},
        ),
        migrations.AlterUniqueTogether(
            name='productavailabilitycache',
            unique_together={('item', 'branch')},
        ),
        migrations.AddIndex(
            model_name='productavailabilitycache',
            index=models.Index(fields=['item', 'status'], name='pe_avail_item_status_idx'),
        ),

        # ── ProductReview (disabled) ──────────────────────────────────────────
        migrations.CreateModel(
            name='ProductReview',
            fields=[
                ('id',            models.BigAutoField(auto_created=True, primary_key=True)),
                ('item',          models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                   related_name='reviews', to='catalog.item')),
                ('customer_name', models.CharField(blank=True, max_length=100)),
                ('rating',        models.PositiveSmallIntegerField(default=5)),
                ('title',         models.CharField(blank=True, max_length=200)),
                ('body',          models.TextField(blank=True)),
                ('is_approved',   models.BooleanField(default=False)),
                ('is_active',     models.BooleanField(default=False)),
                ('created_at',    models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'مراجعة منتج (معطل)',
                     'verbose_name_plural': 'مراجعات المنتجات (معطلة)',
                     'ordering': ['-created_at']},
        ),
    ]
