from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog', '0005_alter_item_phcode'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── EnrichmentBatch ────────────────────────────────────────────────────
        migrations.CreateModel(
            name='EnrichmentBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=200, verbose_name='اسم الدفعة')),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'في الانتظار'), ('running', 'جارٍ التشغيل'),
                        ('success', 'اكتمل'), ('failed', 'فشل'), ('cancelled', 'ملغي'),
                    ],
                    db_index=True, default='pending', max_length=15,
                )),
                ('scope_type', models.CharField(
                    choices=[
                        ('all', 'كل الكتالوج'), ('category', 'تصنيف محدد'),
                        ('supplier', 'مورد محدد'), ('selected', 'أصناف محددة'),
                        ('low_score', 'أقل من حد الاكتمال'),
                    ],
                    default='all', max_length=15,
                )),
                ('scope_params', models.JSONField(blank=True, default=dict)),
                ('auto_publish_threshold', models.FloatField(default=0.9)),
                ('total_items', models.PositiveIntegerField(default=0)),
                ('processed_items', models.PositiveIntegerField(default=0)),
                ('suggestions_generated', models.PositiveIntegerField(default=0)),
                ('auto_published', models.PositiveIntegerField(default=0)),
                ('error_count', models.PositiveIntegerField(default=0)),
                ('error_log', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='enrichment_batches',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'verbose_name': 'دفعة إثراء', 'verbose_name_plural': 'دفعات الإثراء', 'ordering': ['-created_at']},
        ),

        # ── ItemEnrichment ─────────────────────────────────────────────────────
        migrations.CreateModel(
            name='ItemEnrichment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name_ar', models.CharField(blank=True, max_length=255, verbose_name='الاسم العربي')),
                ('brand_name', models.CharField(blank=True, max_length=255, verbose_name='الاسم التجاري')),
                ('manufacturer_ar', models.CharField(blank=True, max_length=255, verbose_name='الشركة المصنعة (عربي)')),
                ('manufacturer_en', models.CharField(blank=True, max_length=255, verbose_name='الشركة المصنعة (إنجليزي)')),
                ('country_ar', models.CharField(blank=True, max_length=100, verbose_name='بلد المنشأ (عربي)')),
                ('country_en', models.CharField(blank=True, max_length=100, verbose_name='بلد المنشأ (إنجليزي)')),
                ('dosage_form_ar', models.CharField(blank=True, max_length=100, verbose_name='الشكل الدوائي (عربي)')),
                ('dosage_form_en', models.CharField(blank=True, max_length=100, verbose_name='الشكل الدوائي (إنجليزي)')),
                ('atc_code', models.CharField(blank=True, max_length=20, verbose_name='كود ATC')),
                ('strength', models.CharField(blank=True, max_length=100, verbose_name='التركيز / القوة')),
                ('volume', models.CharField(blank=True, max_length=50, verbose_name='الحجم')),
                ('pack_size_label', models.CharField(blank=True, max_length=100, verbose_name='حجم العبوة')),
                ('indication_ar', models.TextField(blank=True, verbose_name='الاستخدامات (عربي)')),
                ('indication_en', models.TextField(blank=True, verbose_name='الاستخدامات (إنجليزي)')),
                ('contraindication_ar', models.TextField(blank=True, verbose_name='موانع الاستخدام')),
                ('warning_ar', models.TextField(blank=True, verbose_name='التحذيرات')),
                ('pregnancy_category', models.CharField(blank=True, max_length=10, verbose_name='فئة الحمل')),
                ('age_range', models.CharField(blank=True, max_length=100, verbose_name='الفئة العمرية')),
                ('storage_condition', models.CharField(blank=True, max_length=200, verbose_name='شروط التخزين')),
                ('administration_route_ar', models.CharField(blank=True, max_length=100, verbose_name='طريقة الاستخدام')),
                ('dosage_ar', models.CharField(blank=True, max_length=200, verbose_name='الجرعة')),
                ('frequency_ar', models.CharField(blank=True, max_length=100, verbose_name='التكرار')),
                ('duration_ar', models.CharField(blank=True, max_length=100, verbose_name='مدة العلاج')),
                ('side_effects_ar', models.TextField(blank=True, verbose_name='الآثار الجانبية (عربي)')),
                ('side_effects_en', models.TextField(blank=True, verbose_name='الآثار الجانبية (إنجليزي)')),
                ('drug_interactions_ar', models.TextField(blank=True, verbose_name='التفاعلات الدوائية')),
                ('rx_otc', models.CharField(
                    blank=True, max_length=10,
                    choices=[('rx', 'يحتاج وصفة طبية (Rx)'), ('otc', 'بدون وصفة (OTC)'), ('cd', 'مخدرات/تحكم (CD)')],
                    verbose_name='وصفة طبية',
                )),
                ('image_url', models.URLField(blank=True, max_length=500, verbose_name='صورة المنتج')),
                ('image_secondary_url', models.URLField(blank=True, max_length=500, verbose_name='صورة ثانوية')),
                ('seo_desc_ar', models.TextField(blank=True, verbose_name='وصف SEO (عربي)')),
                ('seo_desc_en', models.TextField(blank=True, verbose_name='وصف SEO (إنجليزي)')),
                ('medical_keywords_ar', models.TextField(blank=True, verbose_name='الكلمات الطبية (عربي)')),
                ('medical_keywords_en', models.TextField(blank=True, verbose_name='الكلمات الطبية (إنجليزي)')),
                ('completeness_score', models.FloatField(db_index=True, default=0.0, verbose_name='نسبة الاكتمال %')),
                ('is_published', models.BooleanField(db_index=True, default=False, verbose_name='منشور')),
                ('last_enriched_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('enriched_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='enriched_items',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('item', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='enrichment',
                    to='catalog.item',
                    verbose_name='الصنف',
                )),
            ],
            options={'verbose_name': 'إثراء صنف', 'verbose_name_plural': 'إثراء الأصناف', 'ordering': ['completeness_score']},
        ),

        # ── EnrichmentSuggestion ───────────────────────────────────────────────
        migrations.CreateModel(
            name='EnrichmentSuggestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('field_name', models.CharField(db_index=True, max_length=60)),
                ('suggested_value', models.TextField()),
                ('current_value', models.TextField(blank=True)),
                ('source', models.CharField(
                    choices=[
                        ('softech', 'بيانات SOFTECH'), ('chronic_module', 'وحدة الأدوية المزمنة'),
                        ('supplier_catalog', 'كتالوج المورد'), ('manual', 'إدخال يدوي'),
                        ('ai_extract', 'استخراج ذكاء اصطناعي'), ('ocr', 'استخراج OCR'),
                        ('previous_approval', 'موافقة سابقة'), ('rule_engine', 'محرك القواعد'),
                    ],
                    max_length=30,
                )),
                ('confidence', models.FloatField(default=0.5)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'في الانتظار'), ('approved', 'موافق عليه'),
                        ('rejected', 'مرفوض'), ('edited', 'تم التعديل'),
                    ],
                    db_index=True, default='pending', max_length=15,
                )),
                ('approved_value', models.TextField(blank=True)),
                ('notes', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='suggestions',
                    to='enrichment.enrichmentbatch',
                )),
                ('enrichment', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='suggestions',
                    to='enrichment.itemenrichment',
                )),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='enrichment_suggestions',
                    to='catalog.item',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reviewed_suggestions',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'verbose_name': 'اقتراح إثراء', 'verbose_name_plural': 'اقتراحات الإثراء', 'ordering': ['-confidence', 'field_name']},
        ),
        migrations.AddIndex(
            model_name='enrichmentsuggestion',
            index=models.Index(fields=['item', 'status'], name='enr_sug_item_status_idx'),
        ),
        migrations.AddIndex(
            model_name='enrichmentsuggestion',
            index=models.Index(fields=['item', 'field_name', 'status'], name='enr_sug_item_field_idx'),
        ),
        migrations.AddIndex(
            model_name='enrichmentsuggestion',
            index=models.Index(fields=['batch', 'status'], name='enr_sug_batch_status_idx'),
        ),

        # ── EnrichmentApprovalLog ──────────────────────────────────────────────
        migrations.CreateModel(
            name='EnrichmentApprovalLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('field_name', models.CharField(max_length=60)),
                ('source', models.CharField(
                    choices=[
                        ('softech', 'بيانات SOFTECH'), ('chronic_module', 'وحدة الأدوية المزمنة'),
                        ('supplier_catalog', 'كتالوج المورد'), ('manual', 'إدخال يدوي'),
                        ('ai_extract', 'استخراج ذكاء اصطناعي'), ('ocr', 'استخراج OCR'),
                        ('previous_approval', 'موافقة سابقة'), ('rule_engine', 'محرك القواعد'),
                    ],
                    max_length=30,
                )),
                ('confidence_at_review', models.FloatField()),
                ('outcome', models.CharField(
                    choices=[('approved', 'موافق'), ('rejected', 'مرفوض'), ('edited', 'تم التعديل')],
                    max_length=10,
                )),
                ('accepted_value', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='enrichment_approvals',
                    to='catalog.item',
                )),
                ('reviewer', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'verbose_name': 'سجل موافقة إثراء', 'verbose_name_plural': 'سجلات موافقات الإثراء', 'ordering': ['-reviewed_at']},
        ),
        migrations.AddIndex(
            model_name='enrichmentapprovallog',
            index=models.Index(fields=['field_name', 'source', 'outcome'], name='enr_log_field_source_idx'),
        ),
    ]
