"""
apps/supply/tab_exports.py — Excel for the /supply tabs that had none (owner 2026-10-26):
«صندوق الإتاحة» (one supplier list + its analysis), «متابعة النواقص» (the case queue as filtered)
and «معدلات البيع» (one rate batch). Every sheet carries the «بيانات الصنف» block right after the
item's code + name (apps/catalog/item_columns.py — read live at export time). Read-only.
"""
from django.utils import timezone

from apps.catalog import item_columns as IC
from apps.purchasing.supply_exports import _book, _bytes, _notes, _sheet

STATE_LABELS = {'buy': 'مطلوب شراؤه', 'needs_match': 'يحتاج مطابقة', 'not_needed': 'غير مطلوب'}
FLAG_LABELS = {'unmatched': 'غير مطابق', 'low_confidence': 'مطابقة ضعيفة', 'urgent': 'عاجل',
               'vendor_code_conflict': 'كود المورد لصنف آخر', 'price_above_history': 'سعر أعلى من سابق'}


def _yes(v):
    return 'نعم' if v else ''


# ── «صندوق الإتاحة» — one supplier availability list ────────────────────────────
def availability_excel(batch, analysis) -> bytes:
    lines = analysis['lines']
    items = IC.load_items(ids=[r.get('item_id') for r in lines])
    rows = []
    for r in lines:
        best = r.get('historical_best') or {}
        rows.append([
            r['raw_text'], r.get('item_softech_id') or '', r.get('item_name') or '',
            *IC.item_cells(items.get(r.get('item_id'))),
            STATE_LABELS.get(r.get('state'), r.get('state') or ''),
            ' · '.join(FLAG_LABELS.get(f, f) for f in r.get('flags') or []),
            r.get('match_score'), _yes(r.get('is_confirmed')), _yes(r.get('main_supplier')),
            r.get('supplier_qty'), r.get('price'), r.get('discount_pct'), r.get('foc_qty'),
            r.get('quota'), str(r.get('expiry') or ''),
            r.get('required'), r.get('current_stock'), r.get('internal_cover'), r.get('residual_gap'),
            r.get('suggested_buy'), r.get('offer_effective_cost'), r.get('best_effective_cost'),
            best.get('effective_cost'), r.get('open_cases'), r.get('waiting_customers_qty'),
        ])
    wb = _book()
    _sheet(wb.active, 'الأسطر',
           ['سطر المورد', 'الكود', 'الصنف', *IC.ITEM_HEADS, 'الحالة', 'إشارات', 'درجة المطابقة', 'مؤكدة',
            'المورد الرئيسي للصنف؟', 'كمية المورد', 'السعر', 'الخصم %', 'البونص', 'الكوتة', 'الصلاحية',
            'المطلوب', 'الرصيد', 'تغطية من الفروع', 'الاحتياج المتبقي', 'الشراء المقترح',
            'تكلفة هذا العرض', 'أفضل تكلفة متاحة', 'أفضل تكلفة سابقة', 'حالات مفتوحة', 'كمية عملاء منتظرة'],
           rows, [40, 9, 34, *IC.ITEM_WIDTHS, 13, 22, 9, 7, 10, 9, 9, 8, 8, 8, 11,
                  9, 9, 10, 10, 10, 10, 10, 10, 9, 10],
           freeze='D2', item_block_at=4)
    sc = analysis.get('scope') or {}
    _notes(wb, [
        f'صندوق الإتاحة — قائمة #{batch.pk} · {getattr(batch, "supplier_name", "") or ""} — '
        f'{timezone.localtime():%Y-%m-%d %H:%M}',
        f'• {len(rows)} سطر' + ('' if sc.get('all', True) else ' — نطاق فروع محدد كما على الشاشة') + '.',
        '• المطلوب / الرصيد / الاحتياج المتبقي / الشراء المقترح = نفس تحليل الشاشة لحظة التصدير.',
        IC.ITEM_NOTE,
        '• للقراءة فقط — لا يكتب شيئاً في SOFTECH.',
    ])
    return _bytes(wb)


# ── «متابعة النواقص» — the case queue as filtered on screen ──────────────────────
def cases_excel(cases, *, filters=None) -> bytes:
    from apps.finance.recon_labels import branch_label as BL
    cases = list(cases)
    items = IC.load_items(ids=[c.item_id for c in cases])
    f2 = lambda v: round(float(v), 2) if v is not None else None
    dt = lambda v: timezone.localtime(v).strftime('%Y-%m-%d %H:%M') if v else ''
    rows = []
    for c in cases:
        it = c.item
        rows.append([
            it.softech_id if it else '', it.name if it else '', *IC.item_cells(items.get(c.item_id)),
            BL(c.branch.softech_branch_id) if c.branch_id else '', c.get_status_display(),
            _yes(c.is_urgent), f2(c.required_qty), f2(c.current_stock), f2(c.internal_cover),
            f2(c.residual_gap), f2(c.customer_demand), f2(c.scarcity_score), _yes(c.has_availability),
            (c.assigned_to.user.get_full_name() if c.assigned_to_id and c.assigned_to.user_id else ''),
            c.days_open, dt(c.first_detected_at), dt(c.last_evaluated_at), c.notes or '',
        ])
    wb = _book()
    _sheet(wb.active, 'الحالات',
           ['الكود', 'الصنف', *IC.ITEM_HEADS, 'الفرع', 'الحالة', 'عاجل', 'المطلوب', 'الرصيد',
            'تغطية من الفروع', 'الاحتياج المتبقي', 'طلب العملاء', 'الندرة', 'يوجد عرض', 'المسؤول',
            'أيام مفتوحة', 'أول رصد', 'آخر تقييم', 'ملاحظات'],
           rows, [9, 34, *IC.ITEM_WIDTHS, 22, 14, 7, 9, 9, 10, 10, 9, 8, 8, 16, 8, 16, 16, 30],
           freeze='C2', item_block_at=3)
    f = filters or {}
    _notes(wb, [
        f'متابعة النواقص — {timezone.localtime():%Y-%m-%d %H:%M}',
        '• الفلاتر: ' + (' · '.join(f'{k}: {v}' for k, v in f.items() if v) or 'بدون') + f' — {len(rows)} حالة.',
        '• الأرقام لقطة آخر تقييم لكل حالة (عمود «آخر تقييم»).',
        IC.ITEM_NOTE,
        '• للقراءة فقط — لا يكتب شيئاً في SOFTECH.',
    ])
    return _bytes(wb)


# ── «معدلات البيع» — one rate batch (SalesRatePush) ──────────────────────────────
def rate_push_excel(push) -> bytes:
    from apps.finance.recon_labels import branch_label as BL
    lines = list(push.lines.all().order_by('branchcode', 'itemcode'))
    items = IC.load_items(codes=[ln.itemcode for ln in lines])
    f3 = lambda v: round(float(v), 3) if v is not None else None
    rows = [[ln.itemcode, ln.item_name, *IC.item_cells(items.get(str(ln.itemcode))),
             BL(ln.branchcode), ln.storecode, f3(ln.old_rate), f3(ln.old_rate_hq), f3(ln.new_rate),
             _yes(ln.eligible), ln.reason or '', _yes(ln.written), _yes(ln.verified), ln.error or '']
            for ln in lines]
    wb = _book()
    _sheet(wb.active, 'المعدلات',
           ['الكود', 'الصنف', *IC.ITEM_HEADS, 'الفرع', 'المخزن', 'المعدل الحالي (الفرع)',
            'المعدل الحالي (نسخة الرئيسي)', 'المعدل الجديد', 'مؤهل', 'السبب', 'كُتب', 'تم التحقق', 'خطأ'],
           rows, [9, 34, *IC.ITEM_WIDTHS, 22, 7, 11, 11, 11, 7, 30, 7, 9, 30],
           freeze='C2', item_block_at=3)
    _notes(wb, [
        f'دفعة معدلات البيع #{push.pk} — {push.get_status_display()} · {push.get_method_display()} · '
        f'{push.get_target_display()}',
        f'• {len(rows)} سطر · تشغيل المحرك #{push.run_id or "—"} · أُنشئت {timezone.localtime(push.created_at):%Y-%m-%d %H:%M}.',
        '• «المعدل الحالي» = قيمة SOFTECH وقت إعداد الدفعة؛ «المعدل الجديد» = ما سيُكتب (أو كُتب) في monthlyqty.',
        IC.ITEM_NOTE,
        '• هذا الملف للمراجعة فقط — الكتابة في SOFTECH تتم من زر «تنفيذ» بعد الاعتماد.',
    ])
    return _bytes(wb)


def xlsx_response(data, filename):
    from django.http import HttpResponse
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp
