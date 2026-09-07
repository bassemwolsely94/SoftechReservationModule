"""
apps/qa/models.py — Branch QA walk-through inspections.

A quality manager walks a branch ticking a checklist (cleanliness, expiry
spot-checks, labeling, fridge/cold-chain, etc.). Templates define the items;
each inspection records a pass/fail/na result + note per item and a computed
score. Inspections are the audit record.
"""
from django.db import models


class QAChecklistTemplate(models.Model):
    """Reusable checklist. `items` is a JSON list of {key, label} entries."""
    name      = models.CharField(max_length=120, verbose_name='الاسم')
    name_ar   = models.CharField(max_length=120, blank=True, verbose_name='الاسم بالعربي')
    items     = models.JSONField(default=list, verbose_name='البنود')   # [{key, label}]
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='مفعّل')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'قالب مراجعة جودة'
        verbose_name_plural = 'قوالب مراجعة الجودة'
        ordering = ['name']

    def __str__(self):
        return self.name_ar or self.name


class QAInspection(models.Model):
    """One branch walk-through against a template."""
    STATUS_CHOICES = [
        ('draft',     'مسودة'),
        ('submitted', 'مُرسَلة'),
    ]
    RESULT_CHOICES = [
        ('pass', 'مطابق'),
        ('fail', 'مخالفة'),
        ('na',   'لا ينطبق'),
    ]

    template   = models.ForeignKey(QAChecklistTemplate, on_delete=models.PROTECT,
                                   related_name='inspections', verbose_name='القالب')
    branch     = models.ForeignKey('branches.Branch', on_delete=models.PROTECT,
                                   related_name='qa_inspections', verbose_name='الفرع')
    inspector  = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='qa_inspections',
                                   verbose_name='المراجِع')
    status     = models.CharField(max_length=12, choices=STATUS_CHOICES, default='draft',
                                  db_index=True, verbose_name='الحالة')
    # Per-item results: [{key, label, result: pass|fail|na, note}]
    results    = models.JSONField(default=list, verbose_name='النتائج')
    score      = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True,
                                     verbose_name='النتيجة %')
    notes      = models.TextField(blank=True, verbose_name='ملاحظات عامة')
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = 'مراجعة جودة'
        verbose_name_plural = 'مراجعات الجودة'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['branch', 'status'])]

    def __str__(self):
        return f'QA {self.branch_id} — {self.get_status_display()} ({self.created_at:%Y-%m-%d})'

    def compute_score(self):
        """Score = passed / (passed + failed) × 100. 'na' items are excluded."""
        passed = sum(1 for r in self.results if r.get('result') == 'pass')
        failed = sum(1 for r in self.results if r.get('result') == 'fail')
        graded = passed + failed
        return round(passed / graded * 100, 1) if graded else None
