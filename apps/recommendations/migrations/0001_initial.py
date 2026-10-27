from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('catalog', '0019_variant_groups_bundles'),
        ('customers', '0015_customer_segment_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecommendationEngineRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('running', 'جارٍ'), ('success', 'ناجح'), ('failed', 'فاشل')], db_index=True, default='running', max_length=10)),
                ('pairs_generated', models.PositiveIntegerField(default=0)),
                ('invoices_scanned', models.PositiveIntegerField(default=0)),
                ('customers_scored', models.PositiveIntegerField(default=0)),
                ('error_message', models.TextField(blank=True)),
                ('min_support', models.FloatField(default=0.001)),
                ('min_confidence', models.FloatField(default=0.05)),
                ('lookback_days', models.PositiveIntegerField(default=365)),
            ],
            options={
                'verbose_name': 'تشغيل محرك التوصيات',
                'verbose_name_plural': 'تشغيلات محرك التوصيات',
                'ordering': ['-started_at'],
            },
        ),
        migrations.CreateModel(
            name='FrequentlyBoughtTogether',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('co_occurrences', models.PositiveIntegerField(default=0)),
                ('item_a_occurrences', models.PositiveIntegerField(default=0)),
                ('confidence', models.FloatField(db_index=True, default=0.0)),
                ('support', models.FloatField(default=0.0)),
                ('lift', models.FloatField(default=0.0)),
                ('score', models.FloatField(db_index=True, default=0.0)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fbt_pairs', to='recommendations.recommendationenginerun')),
                ('item_a', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fbt_as_anchor', to='catalog.item')),
                ('item_b', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fbt_as_recommendation', to='catalog.item')),
            ],
            options={
                'verbose_name': 'اقتران صنفين',
                'verbose_name_plural': 'اقترانات الأصناف',
                'ordering': ['-score'],
            },
        ),
        migrations.AddIndex(
            model_name='frequentlyboughttogether',
            index=models.Index(fields=['run', 'item_a', '-score'], name='rec_fbt_run_itema_score_idx'),
        ),
        migrations.AddIndex(
            model_name='frequentlyboughttogether',
            index=models.Index(fields=['run', 'item_b', '-score'], name='rec_fbt_run_itemb_score_idx'),
        ),
        migrations.AddConstraint(
            model_name='frequentlyboughttogether',
            constraint=models.UniqueConstraint(fields=['run', 'item_a', 'item_b'], name='uniq_fbt_pair_per_run'),
        ),
        migrations.CreateModel(
            name='CustomerRecommendation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.FloatField(db_index=True, default=0.0)),
                ('reason', models.CharField(blank=True, max_length=255)),
                ('is_chronic_related', models.BooleanField(default=False)),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='customer_recs', to='recommendations.recommendationenginerun')),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recommendations', to='customers.customer')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recommended_to', to='catalog.item')),
            ],
            options={
                'verbose_name': 'توصية عميل',
                'verbose_name_plural': 'توصيات العملاء',
                'ordering': ['-score'],
            },
        ),
        migrations.AddIndex(
            model_name='customerrecommendation',
            index=models.Index(fields=['run', 'customer', '-score'], name='rec_cust_run_customer_score_idx'),
        ),
        migrations.AddConstraint(
            model_name='customerrecommendation',
            constraint=models.UniqueConstraint(fields=['run', 'customer', 'item'], name='uniq_rec_per_customer_item_run'),
        ),
    ]
