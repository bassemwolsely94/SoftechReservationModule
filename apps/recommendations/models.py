"""
apps/recommendations/models.py

Recommendation engine data models:

  RecommendationEngineRun — audit log for each FBT calculation run
  FrequentlyBoughtTogether — (item_a, item_b) pairs mined from purchase history
  CustomerRecommendation   — personalized per-customer item recommendations

All data is derived from PostgreSQL (PurchaseHistoryLine) using SELECT only.
SOFTECH / Sybase is never written to.
"""
from django.db import models


class RecommendationEngineRun(models.Model):
    """Audit log for each run of the FBT mining engine."""

    STATUS_CHOICES = [
        ('running', 'جارٍ'),
        ('success', 'ناجح'),
        ('failed',  'فاشل'),
    ]

    started_at     = models.DateTimeField(auto_now_add=True)
    finished_at    = models.DateTimeField(null=True, blank=True)
    status         = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running', db_index=True)
    pairs_generated   = models.PositiveIntegerField(default=0)
    invoices_scanned  = models.PositiveIntegerField(default=0)
    customers_scored  = models.PositiveIntegerField(default=0)
    error_message     = models.TextField(blank=True)
    min_support       = models.FloatField(default=0.001, help_text='Minimum support threshold used')
    min_confidence    = models.FloatField(default=0.05,  help_text='Minimum confidence threshold used')
    lookback_days     = models.PositiveIntegerField(default=365)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'تشغيل محرك التوصيات'
        verbose_name_plural = 'تشغيلات محرك التوصيات'

    def __str__(self):
        return f'Run {self.pk} — {self.status} @ {self.started_at:%Y-%m-%d %H:%M}'


class FrequentlyBoughtTogether(models.Model):
    """
    A pair of items (item_a, item_b) that are frequently purchased together.
    Populated by the FBT engine from PurchaseHistoryLine data.

    Semantics:
      confidence = P(item_b | item_a) = co_occurrences / item_a_occurrences
      support    = co_occurrences / total_invoices  (rarity filter)
      lift       = confidence / P(item_b)  (association strength vs. random)
    """
    run         = models.ForeignKey(
        RecommendationEngineRun,
        on_delete=models.CASCADE,
        related_name='fbt_pairs',
        verbose_name='تشغيل',
    )
    item_a      = models.ForeignKey(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='fbt_as_anchor',
        verbose_name='الصنف الأساسي',
    )
    item_b      = models.ForeignKey(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='fbt_as_recommendation',
        verbose_name='الصنف الموصى به',
    )
    co_occurrences     = models.PositiveIntegerField(default=0, verbose_name='تكرار الاقتران')
    item_a_occurrences = models.PositiveIntegerField(default=0, verbose_name='تكرار الصنف الأساسي')
    confidence         = models.FloatField(default=0.0, db_index=True, verbose_name='الثقة')
    support            = models.FloatField(default=0.0, verbose_name='الدعم')
    lift               = models.FloatField(default=0.0, verbose_name='الرفع')
    score              = models.FloatField(default=0.0, db_index=True,
                                           verbose_name='الدرجة المُركَّبة',
                                           help_text='confidence × log(co_occurrences+1) — used for ranking')

    class Meta:
        ordering = ['-score']
        verbose_name = 'اقتران صنفين'
        verbose_name_plural = 'اقترانات الأصناف'
        indexes = [
            models.Index(fields=['run', 'item_a', '-score']),
            models.Index(fields=['run', 'item_b', '-score']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['run', 'item_a', 'item_b'], name='uniq_fbt_pair_per_run'),
        ]

    def __str__(self):
        return f'{self.item_a.name} → {self.item_b.name} (conf={self.confidence:.2f})'


class CustomerRecommendation(models.Model):
    """
    Personalized recommendation: given a customer, suggest item_b.
    Derived from the customer's top purchased items + FBT rules.
    Re-generated on each engine run.
    """
    run         = models.ForeignKey(
        RecommendationEngineRun,
        on_delete=models.CASCADE,
        related_name='customer_recs',
        verbose_name='تشغيل',
    )
    customer    = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='recommendations',
        verbose_name='العميل',
    )
    item        = models.ForeignKey(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='recommended_to',
        verbose_name='الصنف الموصى به',
    )
    score       = models.FloatField(default=0.0, db_index=True, verbose_name='درجة التوصية')
    reason      = models.CharField(
        max_length=255, blank=True,
        verbose_name='سبب التوصية',
        help_text='e.g. "اشترى معه 73% من العملاء"',
    )
    is_chronic_related = models.BooleanField(
        default=False,
        verbose_name='مرتبط بمرض مزمن',
        help_text='True إذا كان الصنف لنفس المرض المزمن للعميل',
    )

    class Meta:
        ordering = ['-score']
        verbose_name = 'توصية عميل'
        verbose_name_plural = 'توصيات العملاء'
        indexes = [
            models.Index(fields=['run', 'customer', '-score']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['run', 'customer', 'item'], name='uniq_rec_per_customer_item_run'),
        ]

    def __str__(self):
        return f'{self.customer} → {self.item.name} ({self.score:.2f})'
