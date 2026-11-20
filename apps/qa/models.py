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


# ── C31 (audit doc 08, P-53): fridge temperature log ───────────────────────────────────────────
#
# EDA inspectors ask for the fridge log on every visit. Each branch fridge gets two readings a day
# (morning, evening): the current temperature, the min/max since the last reading, and the reader's
# initials. A reading outside the fridge's range, or a missing one, raises an in-app alert to the
# branch. Readings are the audit record: one per fridge per slot, never edited or deleted via the API.

class FridgeUnit(models.Model):
    branch    = models.ForeignKey('branches.Branch', on_delete=models.PROTECT,
                                  related_name='fridge_units', verbose_name='الفرع')
    name      = models.CharField(max_length=80, verbose_name='اسم الثلاجة')
    min_c     = models.DecimalField(max_digits=4, decimal_places=1, default=2,
                                    verbose_name='أقل درجة مسموحة °م')
    max_c     = models.DecimalField(max_digits=4, decimal_places=1, default=8,
                                    verbose_name='أعلى درجة مسموحة °م')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='مفعّلة')
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', verbose_name='أضافها')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'ثلاجة'
        verbose_name_plural = 'الثلاجات'
        ordering = ['branch_id', 'name']
        constraints = [models.UniqueConstraint(fields=['branch', 'name'], name='qa_fridge_branch_name_uniq')]

    def __str__(self):
        return f'{self.name} ({self.branch_id})'


class FridgeReading(models.Model):
    SLOT_AM = 'am'
    SLOT_PM = 'pm'
    SLOT_CHOICES = [(SLOT_AM, 'صباحاً'), (SLOT_PM, 'مساءً')]

    fridge      = models.ForeignKey(FridgeUnit, on_delete=models.PROTECT, related_name='readings',
                                    verbose_name='الثلاجة')
    day         = models.DateField(db_index=True, verbose_name='اليوم')
    slot        = models.CharField(max_length=2, choices=SLOT_CHOICES, verbose_name='الفترة')
    temp_c      = models.DecimalField(max_digits=4, decimal_places=1, verbose_name='الدرجة الحالية °م')
    min_seen_c  = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                      verbose_name='أقل درجة منذ آخر قراءة')
    max_seen_c  = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True,
                                      verbose_name='أعلى درجة منذ آخر قراءة')
    initials    = models.CharField(max_length=20, verbose_name='توقيع (الأحرف الأولى)')
    note        = models.CharField(max_length=300, blank=True, verbose_name='ملاحظة / الإجراء')
    out_of_range = models.BooleanField(default=False, db_index=True, verbose_name='خارج النطاق')
    recorded_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', verbose_name='سجّلها')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'قراءة ثلاجة'
        verbose_name_plural = 'قراءات الثلاجات'
        ordering = ['-day', 'slot']
        constraints = [models.UniqueConstraint(fields=['fridge', 'day', 'slot'], name='qa_fridge_reading_slot_uniq')]

    def compute_out_of_range(self):
        """Any of the three values outside the fridge's [min_c, max_c] (deterministic, inclusive)."""
        lo, hi = self.fridge.min_c, self.fridge.max_c
        vals = [v for v in (self.temp_c, self.min_seen_c, self.max_seen_c) if v is not None]
        return any(v < lo or v > hi for v in vals)
