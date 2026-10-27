"""
apps.composition — SOFTECH active-ingredient reconciliation pipeline
====================================================================

This app owns the *reconciliation* layer between SOFTECH's dirty
``activeingredients`` master and our clean canonical taxonomy
(``chronic.ActiveIngredient`` / ``IngredientStrength`` / ``IngredientClass``).

It is deliberately READ-ONLY toward SOFTECH in this phase:
  • SoftechIngredientRaw / SoftechIngredientClassRaw — a verbatim mirror of the
    SOFTECH master (the "before" snapshot we reconcile from).
  • IngredientParseCandidate — the deterministic parser's PROPOSAL for each raw
    row, awaiting human review. Nothing is trusted or written back to SOFTECH
    until a candidate is approved (that destructive writeback is a later, gated
    phase — Track B).

Dependency direction is one-way: composition → chronic (never the reverse).
"""
from django.db import models


# ─────────────────────────────────────────────────────────────────────────────
# Verbatim SOFTECH mirror (the "before" snapshot)
# ─────────────────────────────────────────────────────────────────────────────

class SoftechIngredientClassRaw(models.Model):
    """Mirror of the SOFTECH 'Active Ingredient Class' taxonomy (Classes screen)."""
    softech_code = models.CharField(max_length=20, unique=True, verbose_name='الكود')
    name         = models.CharField(max_length=200, blank=True, verbose_name='الاسم')
    synced_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تصنيف مادة فعّالة (سوفتك خام)'
        verbose_name_plural = 'تصنيفات المواد الفعّالة (سوفتك خام)'
        ordering            = ['softech_code']

    def __str__(self):
        return f'{self.softech_code} — {self.name}'


class SoftechIngredientRaw(models.Model):
    """
    Verbatim mirror of one ``SOFTECHDB9.dbo.activeingredients`` row.

    ``extra`` holds any discovered-but-not-yet-modeled columns (clinical detail
    flags, etc.) so a sync never silently drops SOFTECH data we haven't mapped.
    """
    aicode      = models.IntegerField(unique=True, verbose_name='كود سوفتك')
    ainame      = models.CharField(max_length=300, db_index=True, verbose_name='الاسم في سوفتك')
    class_code  = models.CharField(max_length=20, blank=True, verbose_name='كود التصنيف')
    class_name  = models.CharField(max_length=200, blank=True, verbose_name='اسم التصنيف')
    item_count  = models.IntegerField(default=0, verbose_name='عدد الأصناف المرتبطة',
                                      help_text='كم صنف يشير لهذه المادة عبر itemsai')
    is_blocked  = models.BooleanField(default=False, verbose_name='محظور')
    extra       = models.JSONField(default=dict, blank=True, verbose_name='أعمدة إضافية')
    first_seen_at = models.DateTimeField(auto_now_add=True)
    synced_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'مادة فعّالة (سوفتك خام)'
        verbose_name_plural = 'المواد الفعّالة (سوفتك خام)'
        ordering            = ['ainame']

    def __str__(self):
        return f'[{self.aicode}] {self.ainame}'


# ─────────────────────────────────────────────────────────────────────────────
# Parser proposal (awaiting human review — never auto-applied)
# ─────────────────────────────────────────────────────────────────────────────

class IngredientParseCandidate(models.Model):
    """
    The deterministic parser's structured proposal for one raw SOFTECH row.

    A pharmacist reviews these to (a) confirm the molecule breakdown, (b) merge
    the dozens of "AMLODIPINE …" rows onto one canonical molecule, and only THEN
    is anything trusted. Rules 5/10: no fuzzy/auto decisions reach real data.
    """
    STATUS_PENDING      = 'pending'
    STATUS_APPROVED     = 'approved'
    STATUS_REJECTED     = 'rejected'
    STATUS_NEEDS_REVIEW = 'needs_review'
    STATUS_CHOICES = [
        (STATUS_PENDING,      'بانتظار المراجعة'),
        (STATUS_NEEDS_REVIEW, 'يحتاج مراجعة دقيقة'),
        (STATUS_APPROVED,     'معتمد'),
        (STATUS_REJECTED,     'مرفوض'),
    ]

    raw = models.OneToOneField(
        SoftechIngredientRaw, on_delete=models.CASCADE,
        related_name='candidate', verbose_name='السطر الخام',
    )
    # Snapshots kept for stability even if the raw row is later re-synced.
    raw_aicode = models.IntegerField(db_index=True, verbose_name='كود سوفتك')
    raw_ainame = models.CharField(max_length=300, verbose_name='الاسم الخام')

    parsed_components = models.JSONField(
        default=list, verbose_name='المكوّنات المُستخرَجة',
        help_text='[{molecule, salt, strength_value, strength_unit, raw_fragment}, ...]',
    )
    is_combination = models.BooleanField(default=False, verbose_name='تركيبة مركّبة')
    is_placeholder = models.BooleanField(default=False, verbose_name='قيمة عامة/فارغة')
    proposed_class_code = models.CharField(max_length=20, blank=True, verbose_name='كود التصنيف المقترح')
    proposed_class_name = models.CharField(max_length=200, blank=True, verbose_name='اسم التصنيف المقترح')
    confidence     = models.FloatField(default=0.0, db_index=True, verbose_name='درجة الثقة')
    parser_version = models.CharField(max_length=10, blank=True, verbose_name='إصدار المُحلّل')

    # ── Deterministic class proposal (INN-stem classifier — reviewed) ─────────
    proposed_class = models.ForeignKey(
        'chronic.IngredientClass', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='class_candidates',
        verbose_name='التصنيف الدوائي المقترح',
    )
    class_rule       = models.CharField(max_length=60, blank=True, verbose_name='قاعدة التصنيف')
    class_confidence = models.FloatField(default=0.0, verbose_name='ثقة التصنيف')

    status = models.CharField(max_length=15, choices=STATUS_CHOICES,
                              default=STATUS_PENDING, db_index=True, verbose_name='الحالة')
    # Set on approval (Track B wiring) — which canonical molecule(s) this maps to.
    canonical_ingredient = models.ForeignKey(
        'chronic.ActiveIngredient', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='parse_candidates',
        verbose_name='المادة المعتمدة',
    )
    # Non-drug disposition (cosmetics / medical supplies / infant formula) — the
    # ainame is a product description, not a molecule, so no ActiveIngredient is
    # created; the chosen non-drug class is kept in proposed_class.
    is_non_drug = models.BooleanField(default=False, db_index=True, verbose_name='غير دوائي')

    reviewed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_ingredient_candidates',
        verbose_name='راجعها',
    )
    reviewed_at  = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ المراجعة')
    review_notes = models.TextField(blank=True, verbose_name='ملاحظات المراجعة')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'اقتراح تحليل مادة فعّالة'
        verbose_name_plural = 'اقتراحات تحليل المواد الفعّالة'
        ordering            = ['-confidence', 'raw_ainame']
        indexes = [
            models.Index(fields=['status', 'confidence']),
            models.Index(fields=['is_combination', 'status']),
        ]

    def __str__(self):
        return f'{self.raw_ainame} → {self.get_status_display()}'

    @property
    def primary_molecule(self) -> str:
        for c in self.parsed_components:
            if c.get('molecule'):
                return c['molecule']
        return ''


# ─────────────────────────────────────────────────────────────────────────────
# Track A — item↔molecule search (materialized, rebuildable, no SOFTECH writes)
# ─────────────────────────────────────────────────────────────────────────────

class SoftechItemAI(models.Model):
    """Verbatim mirror of one ``itemsai`` link (item → active-ingredient)."""
    item_softech_id = models.CharField(max_length=20, db_index=True, verbose_name='كود الصنف')
    aicode          = models.IntegerField(db_index=True, verbose_name='كود المادة')
    is_blocked      = models.BooleanField(default=False, verbose_name='محظور')
    synced_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'ربط صنف بمادة (سوفتك خام)'
        verbose_name_plural = 'روابط الأصناف والمواد (سوفتك خام)'
        unique_together     = ('item_softech_id', 'aicode')
        indexes = [models.Index(fields=['aicode', 'item_softech_id'])]

    def __str__(self):
        return f'{self.item_softech_id} → AI {self.aicode}'


class ItemMoleculeIndex(models.Model):
    """
    Materialized search index: one row per (item × molecule).

    Built from ``SoftechItemAI`` → parse candidate → molecule(s). Uses the
    APPROVED canonical molecule when a candidate is reviewed, otherwise the
    parser's PROPOSED molecule (``source`` records which). Rebuilt any time by
    ``build_ingredient_search_index`` — it is a derived cache, never edited by
    hand and never written to SOFTECH.

    This is what powers "all medicines containing AMLODIPINE", "… at 5mg",
    "… in dosage form X", "… in class Y".
    """
    SOURCE_APPROVED = 'approved'
    SOURCE_PARSED   = 'parsed'

    item_softech_id = models.CharField(max_length=20, db_index=True, verbose_name='كود الصنف')
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE, null=True, blank=True,
        related_name='molecule_index', verbose_name='الصنف',
    )
    item_name = models.CharField(max_length=255, blank=True, verbose_name='اسم الصنف')
    aicode    = models.IntegerField(db_index=True, verbose_name='كود المادة')

    molecule  = models.CharField(max_length=200, db_index=True, verbose_name='المادة الفعّالة')
    active_ingredient = models.ForeignKey(
        'chronic.ActiveIngredient', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='item_index', verbose_name='المادة المعتمدة',
    )
    strength_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True,
                                         verbose_name='قيمة التركيز')
    strength_unit  = models.CharField(max_length=20, blank=True, db_index=True, verbose_name='وحدة التركيز')
    ingredient_class = models.ForeignKey(
        'chronic.IngredientClass', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='item_index', verbose_name='التصنيف الدوائي',
    )
    dosage_form = models.CharField(max_length=100, blank=True, db_index=True, verbose_name='الشكل الصيدلي')
    source      = models.CharField(max_length=10, default=SOURCE_PARSED, db_index=True, verbose_name='المصدر')
    built_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'فهرس صنف×مادة'
        verbose_name_plural = 'فهرس الأصناف والمواد'
        unique_together     = ('item_softech_id', 'aicode', 'molecule')
        indexes = [
            models.Index(fields=['molecule', 'strength_value', 'strength_unit']),
            models.Index(fields=['molecule', 'dosage_form']),
            models.Index(fields=['ingredient_class', 'dosage_form']),
        ]

    def __str__(self):
        s = f' {self.strength_value}{self.strength_unit}' if self.strength_value is not None else ''
        return f'{self.item_name} → {self.molecule}{s}'


class CandidateMolecule(models.Model):
    """
    The APPROVED mapping of one SOFTECH aicode → canonical molecule(s).

    Populated when a candidate is approved: a single-molecule row makes one link;
    a combination makes several (each with its own strength tier). This is the
    reviewed source of truth that (a) powers molecule/strength search now, and
    (b) tells the later Track B writeback which atomic rows to emit and how to
    re-point ``itemsai``.
    """
    candidate = models.ForeignKey(
        IngredientParseCandidate, on_delete=models.CASCADE,
        related_name='molecule_links', verbose_name='الاقتراح',
    )
    active_ingredient = models.ForeignKey(
        'chronic.ActiveIngredient', on_delete=models.CASCADE,
        related_name='candidate_links', verbose_name='المادة الفعّالة',
    )
    strength = models.ForeignKey(
        'chronic.IngredientStrength', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='candidate_links',
        verbose_name='التركيز',
    )
    salt_form  = models.CharField(max_length=60, blank=True, verbose_name='صورة الملح')
    is_primary = models.BooleanField(default=False, verbose_name='مادة رئيسية')

    class Meta:
        unique_together     = ('candidate', 'active_ingredient')
        verbose_name        = 'ربط اقتراح بمادة'
        verbose_name_plural = 'روابط الاقتراحات بالمواد'

    def __str__(self):
        return f'{self.candidate.raw_aicode} → {self.active_ingredient}'
