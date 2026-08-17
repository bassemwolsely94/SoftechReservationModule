"""
apps/transits/models.py

Transfers In Transit — SOFTECH Monitoring & Orchestration Layer.

PURPOSE:
  This module is a READ-ONLY monitoring layer over SOFTECH's inter-branch
  transfer records (doccode='125'). It provides visibility into transfers
  that have been issued by the supplying branch but not yet received by the
  requesting branch.

RULES:
  - NEVER write to SOFTECH. All writes go to local tables only.
  - InTransitTransfer is a CACHE of SOFTECH data, refreshed by the sync job.
  - Notes and audit events are LOCAL ONLY — never synced back to ERP.
  - Priority and status are CALCULATED fields, not stored in ERP.

DATA FLOW:
  SOFTECH stktransm (doccode='125') → sync job → InTransitTransfer
  InTransitTransfer + local metadata → API → Frontend
"""
import datetime
import logging
from django.db import models
from django.utils import timezone

logger = logging.getLogger('elrezeiky.transits')


# ── Priority thresholds (days in transit) ─────────────────────────────────────
PRIORITY_GREEN    = 0   # 0-2 days
PRIORITY_YELLOW   = 3   # 3-4 days
PRIORITY_ORANGE   = 5   # 5-6 days
PRIORITY_RED      = 7   # 7-9 days
PRIORITY_CRITICAL = 10  # 10+ days

CANCELLATION_WINDOW_DAYS = 5  # SOFTECH allows cancellation for ~4-6 days


def _compute_priority(issue_date) -> str:
    """Compute priority level from issue date."""
    if not issue_date:
        return 'green'
    if isinstance(issue_date, datetime.datetime):
        issue_date = issue_date.date()
    days = (datetime.date.today() - issue_date).days
    if days >= PRIORITY_CRITICAL:
        return 'critical'
    if days >= PRIORITY_RED:
        return 'red'
    if days >= PRIORITY_ORANGE:
        return 'orange'
    if days >= PRIORITY_YELLOW:
        return 'yellow'
    return 'green'


QTY_TOLERANCE = 0.001   # below this, a quantity diff is treated as zero


def compute_reconciliation(sent_items: list, received_items: list) -> dict:
    """
    Compare the issued (doccode 125) line items against the received
    (doccode 25) line items and return a structured discrepancy report.

    Both inputs are lists of dicts shaped like items_snapshot entries:
        {itemcode, itemname, qty, extended_cost, ...}

    Returns a dict:
        {
          missing_items: [...]   # issued but not received (or received qty 0)
          extra_items:   [...]   # received but never issued
          qty_diffs:     [...]   # in both, but quantities differ
          sent_value, received_value, value_diff,
          qty_diff_total,        # count of lines that don't match
          has_discrepancy: bool,
        }

    Pure function — no DB access, no side effects. Safe to unit-test.
    """
    def _index(items):
        idx = {}
        for it in (items or []):
            code = str(it.get('itemcode') or '').strip()
            if not code:
                continue
            cur = idx.setdefault(code, {
                'itemcode': code,
                'itemname': it.get('itemname') or code,
                'qty': 0.0,
                'extended_cost': 0.0,
            })
            try:
                cur['qty'] += float(it.get('qty') or 0)
            except (TypeError, ValueError):
                pass
            try:
                cur['extended_cost'] += float(it.get('extended_cost') or 0)
            except (TypeError, ValueError):
                pass
        return idx

    sent_idx = _index(sent_items)
    recv_idx = _index(received_items)

    missing_items, extra_items, qty_diffs = [], [], []

    for code, s in sent_idx.items():
        r = recv_idx.get(code)
        if r is None or r['qty'] <= QTY_TOLERANCE:
            missing_items.append({
                'itemcode': code, 'itemname': s['itemname'],
                'sent_qty': round(s['qty'], 3),
                'received_qty': round(r['qty'], 3) if r else 0.0,
            })
        elif abs(s['qty'] - r['qty']) > QTY_TOLERANCE:
            qty_diffs.append({
                'itemcode': code, 'itemname': s['itemname'],
                'sent_qty': round(s['qty'], 3),
                'received_qty': round(r['qty'], 3),
                'diff': round(r['qty'] - s['qty'], 3),
            })

    for code, r in recv_idx.items():
        if code not in sent_idx:
            extra_items.append({
                'itemcode': code, 'itemname': r['itemname'],
                'received_qty': round(r['qty'], 3),
            })

    sent_value = round(sum(s['extended_cost'] for s in sent_idx.values()), 2)
    received_value = round(sum(r['extended_cost'] for r in recv_idx.values()), 2)

    qty_diff_total = len(missing_items) + len(extra_items) + len(qty_diffs)
    return {
        'checked_at': timezone.now().isoformat(),
        'missing_items': missing_items,
        'extra_items': extra_items,
        'qty_diffs': qty_diffs,
        'sent_value': sent_value,
        'received_value': received_value,
        'value_diff': round(received_value - sent_value, 2),
        'qty_diff_total': qty_diff_total,
        'has_discrepancy': qty_diff_total > 0,
    }


class InTransitTransfer(models.Model):
    """
    Local cache of a SOFTECH inter-branch transfer (doccode='125') that has been
    issued by the supplying branch but not yet fully received.

    SOURCE OF TRUTH: SOFTECH stktransm + stktrans.
    This model is refreshed by the sync job every 15 minutes.
    Local-only fields (notes, force_close_reason, manually_received) are never
    touched by the sync job.
    """

    TRANSIT_STATUS = [
        ('in_transit',       'قيد النقل'),
        ('received',         'مستلم'),
        ('erp_mismatch',     '⚠️ تباين مع ERP (125≠25)'),
        ('cancelled',        'ملغي في ERP'),
        ('expired_pending',  'انتهت مهلة الإلغاء — معلق'),
        ('force_closed',     'مغلق قسراً'),
    ]

    PRIORITY_CHOICES = [
        ('green',    '🟢 طازج (0-2 يوم)'),
        ('yellow',   '🟡 تحت المراقبة (3-4 أيام)'),
        ('orange',   '🟠 يحتاج متابعة (5-6 أيام)'),
        ('red',      '🔴 طارئ (7-9 أيام)'),
        ('critical', '🚨 حرج (10+ أيام)'),
    ]

    # ── ERP identity (immutable after first sync) ─────────────────────────────
    # NOTE: SOFTECH document numbers are a sequence PER (branch, doc-type) —
    # NOT globally unique. Identity = (docnumber, supplying branch).
    erp_doc_number = models.CharField(
        max_length=50, db_index=True,
        verbose_name='رقم المستند (ERP)',
        help_text='stktransm.docnumber — فريد فقط ضمن تسلسل الفرع المصدر',
    )
    erp_doc_code = models.CharField(
        max_length=10, default='125',
        verbose_name='كود نوع المستند',
        help_text='دائماً 125 = صرف تبادل بين الفروع',
    )
    erp_supplying_branch_code = models.CharField(
        max_length=20, db_index=True,
        verbose_name='كود فرع المصدر (ERP)',
    )
    erp_receiving_branch_code = models.CharField(
        max_length=20, blank=True,
        verbose_name='كود فرع المستلم (ERP)',
        help_text='stktransm.cust_branch_code — الوجهة المسجلة على مستند الصرف 125',
    )
    erp_receipt_doc_number = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم مستند الاستلام (25)',
        help_text='docnumber الخاص بمستند الاستلام لدى الفرع المستلم — '
                  'يرتبط بالصرف عبر docnumber2',
    )
    erp_user_code = models.CharField(
        max_length=20, blank=True,
        verbose_name='كود المستخدم (ERP)',
        help_text='من أصدر المستند في SOFTECH',
    )
    erp_store_code = models.CharField(
        max_length=20, blank=True,
        verbose_name='كود المخزن (ERP)',
    )

    # ── Dates ─────────────────────────────────────────────────────────────────
    issue_date = models.DateField(
        verbose_name='تاريخ الإصدار',
        help_text='stktransm.docdate',
    )
    erp_received_date = models.DateField(
        null=True, blank=True,
        verbose_name='تاريخ الاستلام (ERP)',
        help_text='docdate لمستند الاستلام (doccode=25) لدى الفرع المستلم',
    )
    cancellation_expires_at = models.DateField(
        null=True, blank=True,
        verbose_name='انتهاء مهلة الإلغاء',
    )

    # ── Resolved branches (from local Branch model) ───────────────────────────
    supplying_branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='supplying_transits',
        verbose_name='فرع المصدر',
    )
    receiving_branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='receiving_transits',
        verbose_name='فرع المستلم',
    )

    # ── Link to originating transfer request (if created through our system) ──
    linked_request = models.ForeignKey(
        'transfers.TransferRequest',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='in_transit_records',
        verbose_name='طلب التحويل المرتبط',
    )

    # ── Financial summary ─────────────────────────────────────────────────────
    doc_value = models.DecimalField(
        max_digits=14, decimal_places=2,
        null=True, blank=True,
        verbose_name='قيمة المستند (ERP)',
    )
    item_count = models.PositiveIntegerField(
        default=0,
        verbose_name='عدد الأصناف',
    )
    total_quantity = models.DecimalField(
        max_digits=14, decimal_places=3,
        null=True, blank=True,
        verbose_name='إجمالي الكميات',
    )

    # ── Items snapshot ────────────────────────────────────────────────────────
    # Stored as JSON so the detail page doesn't need another SOFTECH hit.
    # Schema: [{itemcode, itemname, qty, unit_cost, extended_cost,
    #           batch, expiry, near_expiry}]
    items_snapshot = models.JSONField(
        default=list, blank=True,
        verbose_name='بيانات الأصناف',
    )

    # ── ERP reconciliation (doccode 125 issued  ↔  doccode 25 received) ────────
    # received_items_snapshot mirrors items_snapshot but for the receiving-branch
    # (doccode 25) side, captured once the document is received in SOFTECH.
    # reconciliation is the computed diff (see compute_reconciliation()).
    received_items_snapshot = models.JSONField(
        default=list, blank=True,
        verbose_name='بيانات الأصناف المستلمة (25)',
    )
    reconciliation = models.JSONField(
        default=dict, blank=True,
        verbose_name='مطابقة 125↔25',
        help_text='{checked_at, missing_items, extra_items, qty_diffs, '
                  'sent_value, received_value, value_diff, qty_diff_total}',
    )
    has_discrepancy = models.BooleanField(
        default=False, db_index=True,
        verbose_name='يوجد تباين مع ERP',
    )

    # ── Computed status & priority ────────────────────────────────────────────
    transit_status = models.CharField(
        max_length=20,
        choices=TRANSIT_STATUS,
        default='in_transit',
        db_index=True,
        verbose_name='حالة النقل',
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='green',
        db_index=True,
        verbose_name='مستوى الأولوية',
    )
    days_in_transit = models.PositiveIntegerField(
        default=0,
        verbose_name='أيام النقل',
    )
    cancellation_available = models.BooleanField(
        default=True,
        verbose_name='الإلغاء ممكن',
        help_text='True ما دام في نطاق مهلة SOFTECH (~5 أيام)',
    )

    # ── Alert tracking ────────────────────────────────────────────────────────
    alert_notification_count = models.PositiveIntegerField(
        default=0,
        verbose_name='عدد التنبيهات المُرسَلة',
    )
    last_alert_sent_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='آخر تنبيه مُرسَل',
    )
    last_alert_level = models.CharField(
        max_length=10, blank=True,
        verbose_name='مستوى آخر تنبيه',
    )

    # ── Local-only fields (NEVER synced to SOFTECH) ───────────────────────────
    internal_notes = models.TextField(
        blank=True,
        verbose_name='ملاحظات داخلية',
    )
    manually_received_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='تم تسجيل الاستلام يدوياً في',
    )
    manually_received_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='received_transits',
        verbose_name='سجّل الاستلام',
    )
    force_close_reason = models.TextField(
        blank=True,
        verbose_name='سبب الإغلاق القسري',
    )
    force_closed_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='force_closed_transits',
        verbose_name='أغلق قسراً بواسطة',
    )

    # ── Sync metadata ─────────────────────────────────────────────────────────
    first_seen_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='أول ظهور في النظام',
    )
    last_synced_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='آخر مزامنة مع ERP',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تحويل قيد النقل'
        verbose_name_plural = 'التحويلات قيد النقل'
        ordering = ['-issue_date', '-erp_doc_number']
        unique_together = [('erp_doc_number', 'erp_supplying_branch_code')]
        indexes = [
            models.Index(fields=['transit_status', 'priority']),
            models.Index(fields=['supplying_branch', 'transit_status']),
            models.Index(fields=['receiving_branch', 'transit_status']),
            models.Index(fields=['issue_date']),
        ]

    def __str__(self):
        return (
            f'TT-{self.erp_doc_number} | '
            f'{self.erp_supplying_branch_code}→{self.erp_receiving_branch_code} | '
            f'{self.get_transit_status_display()}'
        )

    # ── Computed helpers ──────────────────────────────────────────────────────

    def refresh_computed_fields(self):
        """
        Recompute days_in_transit, priority, cancellation_available.
        Call before save() in the sync job.
        Does NOT call save() itself.
        """
        today = datetime.date.today()

        # Days in transit
        if self.erp_received_date:
            self.days_in_transit = (self.erp_received_date - self.issue_date).days
        elif self.transit_status == 'in_transit':
            self.days_in_transit = (today - self.issue_date).days
        # else: keep whatever was stored

        # Priority (only meaningful while in transit)
        if self.transit_status == 'in_transit':
            self.priority = _compute_priority(self.issue_date)
        elif self.transit_status == 'received':
            self.priority = 'green'
        elif self.transit_status == 'erp_mismatch':
            # Received but quantities/value don't reconcile — surface as urgent.
            self.priority = 'red'
        elif self.transit_status == 'critical':
            self.priority = 'critical'

        # Cancellation window
        if not self.cancellation_expires_at:
            self.cancellation_expires_at = (
                self.issue_date + datetime.timedelta(days=CANCELLATION_WINDOW_DAYS)
            )
        self.cancellation_available = (
            self.transit_status == 'in_transit'
            and today <= self.cancellation_expires_at
        )

    @property
    def priority_color(self) -> str:
        return {
            'green':    '#10b981',
            'yellow':   '#f59e0b',
            'orange':   '#f97316',
            'red':      '#ef4444',
            'critical': '#7f1d1d',
        }.get(self.priority, '#9ca3af')

    @property
    def priority_label_ar(self) -> str:
        labels = {
            'green':    'طازج',
            'yellow':   'تحت المراقبة',
            'orange':   'يحتاج متابعة',
            'red':      'طارئ',
            'critical': 'حرج',
        }
        return labels.get(self.priority, self.priority)

    @property
    def has_near_expiry(self) -> bool:
        """True if any item in the snapshot expires within 45 days."""
        today = datetime.date.today()
        cutoff = today + datetime.timedelta(days=45)
        for item in (self.items_snapshot or []):
            exp = item.get('expiry')
            if exp:
                try:
                    if isinstance(exp, str):
                        exp = datetime.date.fromisoformat(exp)
                    if exp <= cutoff:
                        return True
                except (ValueError, TypeError):
                    pass
        return False

    def apply_reconciliation(self, received_items: list):
        """
        Store the received-side (doccode 25) snapshot, recompute the 125↔25
        diff and update has_discrepancy. Does NOT call save() — the caller
        decides when to persist (so this can run inside the sync upsert).

        Returns the reconciliation dict.
        """
        self.received_items_snapshot = received_items or []
        recon = compute_reconciliation(self.items_snapshot, received_items)
        self.reconciliation = recon
        self.has_discrepancy = recon['has_discrepancy']
        return recon


class PickZone(models.Model):
    """
    Warehouse pick zone (منطقة تجميع) for the replenishment picking sheet.

    The pick path = zones ordered by sort_key ascending. An item lands in a
    zone via (highest precedence first):
      1. explicit ItemPickOverride
      2. fridge logic (catalog requires_fridge flag OR 'FRIDGE' in the name)
         → the zone flagged is_fridge_zone
      3. price >= SystemSetting 'replenishment_price_threshold'
         → the zone flagged is_price_zone
      4. PickZoneRule keyword rules, by priority
      5. the zone flagged is_fallback (غير مصنف)
    Fully managed from the frontend (/pick-zones).

    PER-LOCATION CONFIGS: branch=NULL rows form the DEFAULT config. A branch
    with its own zones gets its own layout; branches without one fall back to
    the default.

    TWO PURPOSES per (branch) location — kept strictly separate:
      • picking  (تجميع)  — the SUPPLYING warehouse's walk order; used by the
        picking sheet (ورقة التجميع), classified by the order's source branch.
      • stocking (ترصيص)  — the DESTINATION branch's shelf order; used by the
        stocking sheet (ورقة الترصيص, classified by the order's receiving
        branch) and by stock-count sheets (counting walk = shelf walk).
    A stocking config that doesn't exist falls back: default stocking →
    the location's picking config → default picking.
    """
    PURPOSE_CHOICES = [
        ('picking',  '🚚 تجميع — مسار مخزن المصدر'),
        ('stocking', '🗄️ ترصيص — أرفف الفرع المستلم'),
    ]

    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='pick_zones',
        verbose_name='المخزن / الفرع',
        help_text='فارغ = الإعداد الافتراضي لكل المواقع التي لا تملك إعداداً خاصاً',
    )
    purpose = models.CharField(
        max_length=10, choices=PURPOSE_CHOICES, default='picking',
        db_index=True,
        verbose_name='الغرض',
        help_text='تجميع = مسار مخزن المصدر؛ ترصيص = ترتيب أرفف الفرع (يُستخدم أيضاً للجرد)',
    )
    name = models.CharField(
        max_length=100,
        verbose_name='اسم المنطقة',
    )
    sort_key = models.PositiveSmallIntegerField(
        default=100, db_index=True,
        verbose_name='ترتيب مسار التجميع',
        help_text='الأصغر يُجمَّع أولاً',
    )
    location = models.CharField(
        max_length=120, blank=True,
        verbose_name='الموقع / الرف بالمخزن',
        help_text='يظهر بجوار اسم المنطقة في ورقة التجميع',
    )
    color = models.CharField(max_length=20, blank=True, verbose_name='لون')
    is_active = models.BooleanField(default=True, verbose_name='مفعّلة')
    is_price_zone = models.BooleanField(
        default=False, verbose_name='منطقة الغوالي',
        help_text='تستقبل الأصناف التي يبلغ سعرها حد الغوالي أو أكثر',
    )
    is_fridge_zone = models.BooleanField(
        default=False, verbose_name='منطقة الثلاجة',
        help_text='تستقبل أصناف الثلاجة (علامة الكتالوج أو كلمة FRIDGE بالاسم)',
    )
    is_fallback = models.BooleanField(
        default=False, verbose_name='منطقة غير المصنف',
        help_text='تستقبل الأصناف التي لا تطابق أي قاعدة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'منطقة تجميع'
        verbose_name_plural = 'مناطق التجميع'
        ordering = ['sort_key', 'name']
        unique_together = [('branch', 'purpose', 'name')]

    def __str__(self):
        scope = self.branch.name if self.branch_id else 'افتراضي'
        return f'[{scope}/{self.purpose}] {self.sort_key}. {self.name}'

    @property
    def sheet_label(self) -> str:
        """Zone caption on the printed sheets — name + warehouse location."""
        return f'{self.name} — {self.location}' if self.location else self.name


class PickZoneRule(models.Model):
    """
    Classification rule. Two matching modes:
      • match_field='name'  — ANY keyword appears in the UPPERCASE item name
      • any other field     — the item's master-table column value is IN the
        `keywords` list (exact code match, values picked from the catalog
        lookup sub-tables: itemshape / itemstree / itemsfamily / …)
    Rules evaluate in priority order (ascending) — the first hit wins, so
    order matters (e.g. TAB must outrank CREAM for 'CREAM 10TAB').
    """

    # value → (catalog Item code column, label column) — see export.MATCH_FIELDS
    MATCH_FIELD_CHOICES = [
        ('name',          'اسم الصنف (كلمات)'),
        ('shape',         'شكل الصنف'),
        ('medicine_type', 'نوع الدواء'),
        ('family',        'عائلة الصنف'),
        ('producer',      'الشركة المنتجة'),
        ('origin',        'بلد المنشأ'),
        ('unit',          'وحدة العبوة'),
    ]

    zone = models.ForeignKey(
        PickZone, on_delete=models.CASCADE,
        related_name='rules', verbose_name='المنطقة',
    )
    match_field = models.CharField(
        max_length=20, choices=MATCH_FIELD_CHOICES, default='name',
        verbose_name='نوع المطابقة',
        help_text='اسم الصنف = بحث كلمات؛ الباقي = مطابقة قيمة عمود جدول الأصناف',
    )
    keywords = models.JSONField(
        default=list, verbose_name='الكلمات / القيم',
        help_text='كلمات للبحث بالاسم، أو قيم (أكواد) عمود الأصناف — أي تطابق واحد يكفي',
    )
    priority = models.PositiveSmallIntegerField(
        default=100, db_index=True,
        verbose_name='أولوية التقييم',
        help_text='الأصغر يُقيَّم أولاً — أول تطابق يفوز',
    )
    is_active = models.BooleanField(default=True, verbose_name='مفعّلة')
    note = models.CharField(max_length=200, blank=True, verbose_name='ملاحظة')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'قاعدة تصنيف'
        verbose_name_plural = 'قواعد التصنيف'
        ordering = ['priority', 'id']

    def __str__(self):
        return f'[{self.priority}] {", ".join(self.keywords or [])} → {self.zone.name}'


class ItemPickOverride(models.Model):
    """
    Explicit per-item zone assignment — beats every rule. Used to reclassify
    uncategorized items or pin any item to a zone/location, with an optional
    free-text tag.

    PER-LOCATION: branch=NULL is the default override; a branch-specific row
    wins over the default one when exporting from that branch.
    """
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='item_pick_overrides',
        verbose_name='المخزن / الفرع',
        help_text='فارغ = تخصيص افتراضي لكل المواقع',
    )
    purpose = models.CharField(
        max_length=10, choices=PickZone.PURPOSE_CHOICES, default='picking',
        db_index=True,
        verbose_name='الغرض',
        help_text='تخصيص التجميع مستقل عن تخصيص الترصيص — لكل غرض تخصيصه',
    )
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='pick_overrides', verbose_name='الصنف',
    )
    zone = models.ForeignKey(
        PickZone, on_delete=models.CASCADE,
        related_name='item_overrides', verbose_name='المنطقة',
    )
    tag = models.CharField(
        max_length=100, blank=True,
        verbose_name='وسم / موقع خاص',
        help_text='مثال: رف A3 — يظهر في ملاحظات ورقة التجميع',
    )
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pick_overrides', verbose_name='بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تخصيص صنف لمنطقة'
        verbose_name_plural = 'تخصيصات الأصناف'
        ordering = ['-updated_at']
        unique_together = [('branch', 'purpose', 'item')]

    def __str__(self):
        return f'{self.item} → {self.zone.name}'


class InTransitNote(models.Model):
    """
    Internal note on an in-transit transfer.
    LOCAL ONLY — never written to SOFTECH.
    """

    NOTE_TYPES = [
        ('note',   '📝 ملاحظة'),
        ('system', '⚙️ نظام'),
        ('alert',  '🔔 تنبيه'),
    ]

    transfer = models.ForeignKey(
        InTransitTransfer,
        on_delete=models.CASCADE,
        related_name='notes',
        verbose_name='التحويل',
    )
    note_type = models.CharField(
        max_length=10, choices=NOTE_TYPES, default='note',
        verbose_name='نوع الملاحظة',
    )
    body = models.TextField(verbose_name='نص الملاحظة')
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transit_notes',
        verbose_name='بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name        = 'ملاحظة تحويل'
        verbose_name_plural = 'ملاحظات التحويلات'

    def __str__(self):
        return f'[{self.transfer.erp_doc_number}] {self.body[:60]}'

    @classmethod
    def log_system(cls, transfer, body: str):
        """Create a system-generated note."""
        return cls.objects.create(
            transfer=transfer,
            note_type='system',
            body=body,
            created_by=None,
        )


class InTransitAuditEvent(models.Model):
    """
    Immutable audit trail for every action performed on an in-transit transfer.
    Every row is append-only — never modified after creation.
    """

    ACTION_CHOICES = [
        ('viewed',          '👁️ عُرض'),
        ('note_added',      '📝 أُضيفت ملاحظة'),
        ('alert_sent',      '🔔 أُرسل تنبيه'),
        ('received',        '✅ سُجِّل الاستلام'),
        ('cancel_requested','↩️ طُلب الإلغاء'),
        ('force_closed',    '🔒 أُغلق قسراً'),
        ('synced',          '🔄 مزامنة ERP'),
        ('printed',         '🖨️ طُبع'),
        ('exported',        '📤 صُدِّر'),
        ('linked',          '🔗 رُبط بطلب'),
    ]

    transfer = models.ForeignKey(
        InTransitTransfer,
        on_delete=models.CASCADE,
        related_name='audit_events',
        verbose_name='التحويل',
    )
    action = models.CharField(
        max_length=30, choices=ACTION_CHOICES,
        db_index=True,
        verbose_name='الإجراء',
    )
    actor = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transit_audit_events',
        verbose_name='المُنفِّذ',
    )
    detail = models.TextField(blank=True, verbose_name='تفاصيل')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'حدث مراجعة'
        verbose_name_plural = 'سجل المراجعة'

    def __str__(self):
        return f'[{self.transfer.erp_doc_number}] {self.get_action_display()} @ {self.created_at:%Y-%m-%d %H:%M}'

    @classmethod
    def log(cls, transfer, action: str, actor=None, detail: str = ''):
        """Convenience method — create an audit event."""
        try:
            cls.objects.create(
                transfer=transfer,
                action=action,
                actor=actor,
                detail=detail,
            )
        except Exception as exc:
            logger.warning('InTransitAuditEvent.log failed (non-fatal): %s', exc)
