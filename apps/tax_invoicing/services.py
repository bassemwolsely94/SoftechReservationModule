"""
apps/tax_invoicing/services.py — draft, line classification, reconciliation, approval, notes. Doc 36.

Business rules live here, so the views and the screen cannot differ from them:
  • A blocked line blocks the document. There is no path that uploads only the approved subset.
  • The filter on the review screen is display only: nothing in this file reads it.
  • An exclusion takes a written reason, an active documented basis, and a second person.
"""
import json
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.insurance.models import (InsuranceClaim, InsuranceClaimAdjustment, InsuranceClaimSupplement)

from . import fiscal
from .models import (TaxAuditEvent, TaxBuyerProfile, TaxDocument, TaxDocumentLine, TaxExclusionBasis,
                     TaxIssuerProfile, TaxItemProfile, TaxLineReview, TaxSequence)

ZERO = Decimal('0')
FINALIZED_CLAIM_STATUSES = InsuranceClaim.LOCKED_STATUSES
EDITABLE = (TaxDocument.DRAFT,)
DOCUMENT_VERSION = '1.0'


class TaxRuleError(Exception):
    """A rule refused the action. The message is written for the user."""


class TaxBlocked(TaxRuleError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('المستند محجوب: ' + '؛ '.join(i['message'] for i in issues))


def audit(action, *, document=None, actor=None, reason='', before=None, after=None, entity='document', entity_id=''):
    return TaxAuditEvent.objects.create(
        document=document, action=action, actor=actor, reason=reason, before=before or {}, after=after or {},
        entity=entity, entity_id=str(entity_id or (document.pk if document else '')))


def set_status(doc, new, actor=None, reason=''):
    if new not in TaxDocument.TRANSITIONS.get(doc.status, []):
        raise TaxRuleError(f'لا يمكن الانتقال من {doc.get_status_display()} إلى {new}')
    old, doc.status = doc.status, new
    doc.save()
    audit('status_change', document=doc, actor=actor, reason=reason, before={'status': old}, after={'status': new})


def next_internal_id(doc_type, year):
    seq, _ = TaxSequence.objects.select_for_update().get_or_create(doc_type=doc_type, year=year)
    seq.last_number += 1
    seq.save(update_fields=['last_number'])
    prefix = {'i': 'INV', 'c': 'CN', 'd': 'DN'}[doc_type]
    return f'{prefix}-{year}-{seq.last_number:06d}'


# ── Source snapshot ────────────────────────────────────────────────────────────────────────────

def _money(v):
    return str(v if v is not None else ZERO)


def build_snapshot(claim):
    """The claim as it stands: SOFTECH references, lines, discounts, totals. No patient names,
    because a fiscal document has no use for them."""
    rx_rows, line_rows, excluded = [], [], []
    for rx in claim.prescriptions.select_related('exclusion').prefetch_related('lines').all():
        exclusion = getattr(rx, 'exclusion', None)
        try:
            override = rx.adjustment.net_override
        except InsuranceClaimAdjustment.DoesNotExist:
            override = None
        if exclusion is not None:
            excluded.append({'id': rx.id, 'docnumber': rx.softech_docnumber, 'branch': rx.softech_branchcode,
                             'net_after': _money(rx.net_after), 'reason': exclusion.reason})
            continue
        rx_rows.append({'id': rx.id, 'docnumber': rx.softech_docnumber, 'docdate': str(rx.softech_docdate),
                        'branch': rx.softech_branchcode, 'personcode': rx.softech_personcode,
                        'gross_before': _money(rx.gross_before), 'total_discount': _money(rx.total_discount),
                        'net_after': _money(rx.net_after), 'net_override': None if override is None else _money(override),
                        'softech_net': None if rx.softech_net is None else _money(rx.softech_net)})
        for l in rx.lines.all():
            line_rows.append({'id': l.id, 'rx': rx.id, 'docnumber': rx.softech_docnumber,
                              'docdate': str(rx.softech_docdate), 'branch': rx.softech_branchcode,
                              'itemcode': l.softech_itemcode, 'item_name': l.item_name, 'quantity': _money(l.quantity),
                              'unit_price': _money(l.unit_price), 'gross': _money(l.line_total),
                              'discount': _money(l.discount_amt), 'net': _money(l.net_amount),
                              'softech_line_net': None if l.softech_line_net is None else _money(l.softech_line_net)})
    supplements = [{'id': s.id, 'type': s.supplement_type, 'gross_before': _money(s.gross_before),
                    'total_discount': _money(s.total_discount), 'net_after': _money(s.net_after)}
                   for s in claim.supplements.filter(is_excluded=False).exclude(
                       supplement_type=InsuranceClaimSupplement.SUPPLEMENT_STANDALONE)]
    manual = [{'id': m.id, 'docnumber': m.softech_docnumber, 'gross_before': _money(m.gross_before),
               'total_discount': _money(m.total_discount), 'net_after': _money(m.net_after)}
              for m in claim.manual_rx.filter(is_excluded=False)]
    return {
        'claim': {'id': claim.id, 'number': claim.claim_number, 'softech_motalba_no': claim.softech_motalba_no,
                  'status': claim.status, 'period_from': str(claim.period_from), 'period_to': str(claim.period_to),
                  'client_id': claim.client.id, 'client_name': str(claim.client),
                  'final_gross_before': _money(claim.final_gross_before),
                  'final_total_discount': _money(claim.final_total_discount),
                  'final_net_after': _money(claim.final_net_after)},
        'prescriptions': rx_rows, 'lines': line_rows, 'excluded_prescriptions': excluded,
        'supplements': supplements, 'manual_rx': manual,
    }


def snapshot_hash(snapshot):
    body = {k: v for k, v in snapshot.items() if k != 'claim'}
    body['claim'] = {k: v for k, v in snapshot['claim'].items() if k != 'status'}
    return fiscal.sha256_hex(json.dumps(body, sort_keys=True, ensure_ascii=False))


def _apply_lines(doc, snapshot):
    """Make the document's lines match the snapshot, keyed by source line."""
    existing = {l.source_line_id: l for l in doc.lines.all()}
    keep = set()
    for row in snapshot['lines']:
        keep.add(row['id'])
        values = dict(
            source_docnumber=row['docnumber'], source_docdate=row['docdate'], source_branchcode=row['branch'],
            softech_itemcode=row['itemcode'], item_name=row['item_name'], quantity=Decimal(row['quantity']),
            unit_price=Decimal(row['unit_price']), source_gross=Decimal(row['gross']),
            source_discount=Decimal(row['discount']), source_net=Decimal(row['net']),
            softech_line_net=None if row['softech_line_net'] is None else Decimal(row['softech_line_net']))
        line = existing.get(row['id'])
        if line is None:
            TaxDocumentLine.objects.create(document=doc, source_line_id=row['id'], **values)
        else:
            for k, v in values.items():
                setattr(line, k, v)
            line.save()
    for sid, line in existing.items():
        if sid not in keep:
            line.delete()


def open_or_create_invoice(claim, actor):
    """(document, created). One claim has one original invoice, and reopening returns it."""
    existing = TaxDocument.objects.filter(claim=claim, doc_type=TaxDocument.TYPE_INVOICE).first()
    if existing:
        return existing, False
    if claim.status not in FINALIZED_CLAIM_STATUSES:
        raise TaxRuleError('المطالبة لم تُقدَّم بعد؛ تُصدر الفاتورة الضريبية بعد إقفال المطالبة في التأمين')
    snapshot = build_snapshot(claim)
    buyer = TaxBuyerProfile.objects.filter(client=claim.client).first()
    try:
        with transaction.atomic():
            doc = TaxDocument.objects.create(
                doc_type=TaxDocument.TYPE_INVOICE, claim=claim, created_by=actor,
                internal_id=next_internal_id(TaxDocument.TYPE_INVOICE, timezone.now().year),
                source_snapshot=snapshot, source_hash=snapshot_hash(snapshot),
                source_claim_total=claim.final_net_after,
                presentation_mode=buyer.presentation_mode if buyer else TaxBuyerProfile.MODE_SUMMARY)
            _apply_lines(doc, snapshot)
            audit('draft_created', document=doc, actor=actor, after={'claim': claim.claim_number,
                                                                     'source_hash': doc.source_hash})
            revalidate(doc)
    except IntegrityError:
        # Two people pressed at once: the database let one through. Open that one.
        return TaxDocument.objects.get(claim=claim, doc_type=TaxDocument.TYPE_INVOICE), False
    return doc, True


def refresh_source(doc, actor, reason):
    """Take the claim's current content into an unapproved draft. The first snapshot is kept."""
    if doc.status not in EDITABLE or doc.doc_type != TaxDocument.TYPE_INVOICE:
        raise TaxRuleError('يمكن تحديث المصدر في المسودة فقط')
    if not (reason or '').strip():
        raise TaxRuleError('اكتب سبب تحديث المصدر')
    snapshot = build_snapshot(doc.claim)
    new_hash = snapshot_hash(snapshot)
    with transaction.atomic():
        before = {'source_hash': doc.source_hash, 'claim_total': str(doc.source_claim_total)}
        _apply_lines(doc, snapshot)
        doc.source_hash = new_hash
        doc.source_claim_total = doc.claim.final_net_after
        doc.source_refreshed_at = timezone.now()
        doc.save()
        audit('source_refreshed', document=doc, actor=actor, reason=reason, before=before,
              after={'source_hash': new_hash, 'claim_total': str(doc.source_claim_total)})
        revalidate(doc)
    return doc


# ── Classification ─────────────────────────────────────────────────────────────────────────────

def classify(line_review, profile, *, is_note=False):
    """(status, reason) for one line. Evaluated per line, never per sale."""
    L = TaxDocumentLine
    if line_review is not None and line_review.state == TaxLineReview.ACCEPTED \
            and line_review.category == TaxLineReview.CAT_EXCLUSION:
        return L.ST_EXCLUDED, f'مستبعد: {line_review.reason} ({line_review.basis})'
    if line_review is not None and line_review.state == TaxLineReview.OPEN:
        return L.ST_PENDING, f'بانتظار قرار المحاسب: {line_review.get_category_display()}'
    if profile is None or profile.coding_status == TaxItemProfile.CODE_MISSING:
        return L.ST_UNCODED, 'الصنف بدون كود لدى المصلحة'
    if profile.coding_status == TaxItemProfile.CODE_REJECTED:
        return L.ST_UNCODED, 'كود الصنف مرفوض من المصلحة'
    if profile.coding_status == TaxItemProfile.CODE_PENDING:
        return L.ST_PENDING, 'كود الصنف قيد الاعتماد لدى المصلحة'
    if not profile.eta_code or not profile.code_type:
        return L.ST_UNCODED, 'الكود أو نوعه غير مسجل'
    decided = line_review is not None and line_review.state in (TaxLineReview.ACCEPTED, TaxLineReview.DECLINED)
    if profile.disposition != TaxItemProfile.DISP_INCLUDE and not decided:
        origin = 'صنف في القائمة السوداء' if profile.list_status == TaxItemProfile.LIST_BLACK else 'الصنف'
        return L.ST_PENDING, f'{origin} يحتاج مراجعة المحاسب: {profile.listed_reason or "بدون سبب مسجل"}'
    if profile.tax_treatment == TaxItemProfile.TREATMENT_UNCLASSIFIED or not profile.treatment_confirmed_at:
        return L.ST_PENDING, 'المعاملة الضريبية للصنف غير مؤكدة'
    if profile.tax_treatment in (TaxItemProfile.TREATMENT_EXEMPT, TaxItemProfile.TREATMENT_ZERO):
        return L.ST_EXEMPT, profile.get_tax_treatment_display()
    return L.ST_APPROVED, ''


def _latest_reviews(doc):
    """line pk → its review that counts: an open one, else the most recent decision."""
    out = {}
    for r in doc.line_reviews.order_by('requested_at', 'id'):
        if r.line_id is None:
            continue
        if r.line_id in out and out[r.line_id].state == TaxLineReview.OPEN:
            continue
        out[r.line_id] = r
    return out


def revalidate(doc):
    """Recompute every line of a draft from the item's current mapping, then the totals."""
    if doc.status not in EDITABLE:
        return doc
    issuer = TaxIssuerProfile.load()
    lines = list(doc.lines.all())
    profiles = {p.softech_itemcode: p for p in
                TaxItemProfile.objects.filter(softech_itemcode__in={l.softech_itemcode for l in lines})}
    reviews = _latest_reviews(doc)
    # Zero VAT at claim level only with a written determination recorded on this buyer.
    buyer = TaxBuyerProfile.objects.filter(client=doc.claim.client).select_related('zero_vat_basis').first()
    zero_basis = buyer.zero_vat_basis if buyer and buyer.zero_vat_basis_id and buyer.zero_vat_basis.is_active \
        and buyer.zero_vat_basis.kind == TaxExclusionBasis.KIND_ZERO_VAT else None
    for line in lines:
        p = profiles.get(line.softech_itemcode)
        line.status, line.status_reason = classify(reviews.get(line.pk), p)
        line.code_type = p.code_type if p else ''
        line.eta_code = p.eta_code if p else ''
        line.unit_type = (p.unit_type if p else '') or issuer.default_unit_type
        line.tax_treatment = p.tax_treatment if p else TaxItemProfile.TREATMENT_UNCLASSIFIED
        line.vat_rate = p.vat_rate if p and p.tax_treatment == TaxItemProfile.TREATMENT_TAXABLE else ZERO
        if zero_basis is not None and line.on_invoice:
            line.tax_treatment, line.vat_rate = TaxItemProfile.TREATMENT_ZERO, ZERO
            line.status = TaxDocumentLine.ST_EXEMPT
            line.status_reason = f'بدون ضريبة بموجب {zero_basis}'
        net, vat = fiscal.split_vat(line.source_net, line.vat_rate, issuer.prices_include_vat)
        line.net_ex_vat, line.vat_amount, line.total_incl_vat = net, vat, fiscal.q5(net + vat)
        line.save()
    t = fiscal_totals(doc, issuer)
    doc.total_sales, doc.total_discount = t['sales_total'], t['discount']
    doc.net_amount, doc.vat_amount, doc.total_amount = t['net'], t['vat'], t['total']
    doc.save()
    return doc


# ── Fiscal lines: where a single summary line is allowed ───────────────────────────────────────

def _subtype(issuer, treatment):
    return {TaxItemProfile.TREATMENT_TAXABLE: issuer.subtype_taxable,
            TaxItemProfile.TREATMENT_EXEMPT: issuer.subtype_exempt,
            TaxItemProfile.TREATMENT_ZERO: issuer.subtype_zero_rated}.get(treatment, '')


def fiscal_mode(doc, issuer=None):
    """('summary' | 'detailed', why). The customer's printed invoice may still be one line: this
    decides what ETA receives. Summary needs a validated rule that covers every line on it."""
    issuer = issuer or TaxIssuerProfile.load()
    if doc.doc_type != TaxDocument.TYPE_INVOICE:
        return 'detailed', 'الإشعار يتبع بنود الفاتورة الأصلية'
    if doc.presentation_mode != TaxBuyerProfile.MODE_SUMMARY:
        return 'detailed', 'المشتري مضبوط على التفصيل'
    if not (issuer.summary_validated_at and issuer.summary_item_code and issuer.summary_code_type
            and issuer.summary_treatment and issuer.summary_vat_rate is not None):
        return 'detailed', 'لا توجد قاعدة تجميع معتمدة، فتذهب البنود تفصيلياً للمصلحة'
    on = [l for l in doc.lines.all() if l.on_invoice]
    if not all(l.tax_treatment == issuer.summary_treatment and l.vat_rate == issuer.summary_vat_rate for l in on):
        return 'detailed', 'البنود بمعاملات ضريبية مختلفة لا تغطيها قاعدة التجميع، فتذهب تفصيلياً للمصلحة'
    return 'summary', 'سطر واحد وفق قاعدة التجميع المعتمدة'


def build_fiscal_lines(doc, issuer=None):
    issuer = issuer or TaxIssuerProfile.load()
    on = [l for l in doc.lines.all() if l.on_invoice]
    common = dict(prices_include_vat=issuer.prices_include_vat, tax_type=issuer.vat_tax_type)
    mode, _ = fiscal_mode(doc, issuer)
    if mode == 'summary' and on:
        return [fiscal.fiscal_line(
            description=issuer.summary_description or 'مطالبة مالية', code_type=issuer.summary_code_type,
            eta_code=issuer.summary_item_code, unit_type=issuer.default_unit_type, internal_code=doc.internal_id,
            quantity=1, gross=sum((l.source_gross for l in on), ZERO), net=sum((l.source_net for l in on), ZERO),
            rate=issuer.summary_vat_rate, subtype=_subtype(issuer, issuer.summary_treatment), **common)]
    return [fiscal.fiscal_line(
        description=l.item_name or l.softech_itemcode, code_type=l.code_type, eta_code=l.eta_code,
        unit_type=l.unit_type, internal_code=l.softech_itemcode, quantity=l.quantity,
        gross=l.source_gross, net=l.source_net, rate=l.vat_rate, subtype=_subtype(issuer, l.tax_treatment), **common)
        for l in on if l.quantity > 0]


def fiscal_totals(doc, issuer=None):
    return fiscal.totals(build_fiscal_lines(doc, issuer))


# ── Reconciliation ─────────────────────────────────────────────────────────────────────────────

def reconciliation(doc, issuer=None):
    """Source claim total, proposed invoice total, and the difference by line and reason."""
    issuer = issuer or TaxIssuerProfile.load()
    if doc.doc_type != TaxDocument.TYPE_INVOICE:
        return {'source_total': None, 'proposed_total': str(doc.total_amount), 'difference': '0', 'rows': [],
                'unexplained': '0', 'within_tolerance': True}
    snap = doc.source_snapshot
    rows = []

    def add(kind, label, amount, ref='', reason=''):
        amount = Decimal(str(amount))
        if amount:
            rows.append({'kind': kind, 'label': label, 'amount': str(amount), 'ref': ref, 'reason': reason})

    lines = list(doc.lines.all())
    by_rx = {}
    for row in snap.get('lines', []):
        by_rx[row['rx']] = by_rx.get(row['rx'], ZERO) + Decimal(row['net'])
    rx_total = ZERO
    for rx in snap.get('prescriptions', []):
        effective = Decimal(rx['net_override'] if rx['net_override'] is not None else rx['net_after'])
        rx_total += effective
        add('rx_vs_lines', 'صافى الروشتة يختلف عن مجموع بنودها', effective - by_rx.get(rx['id'], ZERO),
            ref=rx['docnumber'], reason='تعديل صافى يدوى' if rx['net_override'] is not None else '')
    no_lines = ZERO
    for m in snap.get('manual_rx', []):
        no_lines += Decimal(m['net_after'])
        add('no_lines', 'إضافة يدوية بدون بنود أصناف', m['net_after'], ref=m['docnumber'])
    for s in snap.get('supplements', []):
        no_lines += Decimal(s['net_after'])
        add('no_lines', 'ملحق بدون بنود أصناف', s['net_after'], ref=str(s['id']))
    source_total = doc.source_claim_total
    add('claim_formula', 'فرق معادلة إجمالى المطالبة', source_total - rx_total - no_lines)

    excluded = unresolved = ZERO
    for l in lines:
        if l.status == TaxDocumentLine.ST_EXCLUDED:
            excluded += l.source_net
            add('excluded', 'بند مستبعد', l.source_net, ref=f'{l.source_docnumber} / {l.softech_itemcode}',
                reason=l.status_reason)
        elif not l.on_invoice:
            unresolved += l.source_net
            add('unresolved', 'بند لم يُحسم بعد', l.source_net, ref=f'{l.source_docnumber} / {l.softech_itemcode}',
                reason=l.status_reason)
    proposed = fiscal_totals(doc, issuer)['total']
    if issuer.prices_include_vat:
        on_source = sum((l.source_net for l in lines if l.on_invoice), ZERO)
        add('vat_rounding', 'تقريب فصل الضريبة', on_source - proposed)
        difference = source_total - proposed
        unexplained = difference - excluded - unresolved
    else:
        vat = fiscal_totals(doc, issuer)['vat']
        add('vat_added', 'ضريبة مضافة فوق الأسعار', -vat)
        difference = source_total - proposed
        unexplained = difference + vat - excluded - unresolved
    return {'source_total': str(source_total), 'proposed_total': str(proposed), 'difference': str(difference),
            'excluded_total': str(excluded), 'unresolved_total': str(unresolved), 'rows': rows,
            'unexplained': str(fiscal.q5(unexplained)),
            'within_tolerance': abs(unexplained) <= issuer.reconcile_tolerance}


# ── Readiness ──────────────────────────────────────────────────────────────────────────────────

def _issue(code, message, **extra):
    return {'code': code, 'message': message, **extra}


def issuer_gaps(issuer, treatments):
    gaps = []
    for field, label in (('name', 'اسم الممول'), ('tax_id', 'رقم التسجيل الضريبي'), ('activity_code', 'كود النشاط'),
                         ('governate', 'المحافظة'), ('region_city', 'المدينة'), ('street', 'الشارع'),
                         ('building_number', 'رقم المبنى'), ('vat_tax_type', 'نوع الضريبة')):
        if not getattr(issuer, field):
            gaps.append(label)
    if not issuer.vat_basis_confirmed_at:
        gaps.append('تأكيد المحاسب: هل الأسعار شاملة الضريبة')
    for t in treatments:
        if not _subtype(issuer, t):
            gaps.append(f'النوع الفرعى للضريبة لمعاملة {t}')
    return gaps


def blockers(doc, issuer=None):
    """Everything standing between this document and approval. Empty means it may be approved."""
    issuer = issuer or TaxIssuerProfile.load()
    out = []
    lines = list(doc.lines.all())
    if not lines:
        out.append(_issue('no_lines', 'لا توجد بنود في المستند'))
    uncoded = sorted({l.softech_itemcode for l in lines if l.status == TaxDocumentLine.ST_UNCODED})
    if uncoded:
        out.append(_issue('uncoded', f'{len(uncoded)} صنف بدون كود معتمد، راجع يدوياً ثم رمّز الصنف', skus=uncoded))
    pending = sorted({l.softech_itemcode for l in lines if l.status == TaxDocumentLine.ST_PENDING})
    if pending:
        out.append(_issue('pending', f'{len(pending)} صنف ينتظر مراجعة أو تأكيد المعاملة الضريبية', skus=pending))
    bad_qty = sorted({l.softech_itemcode for l in lines if l.on_invoice and l.quantity <= 0})
    if bad_qty:
        out.append(_issue('quantity', 'بنود بكمية غير موجبة', skus=bad_qty))
    if any(l.get('discount', ZERO) < 0 for l in build_fiscal_lines(doc, issuer)):
        out.append(_issue('negative_discount', 'بند صافيه أكبر من إجماليه، راجع المصدر'))

    gaps = issuer_gaps(issuer, {l.tax_treatment for l in lines if l.on_invoice})
    if gaps:
        out.append(_issue('issuer', 'بيانات ناقصة: ' + '، '.join(gaps)))

    buyer = TaxBuyerProfile.objects.filter(client=doc.claim.client).first()
    if buyer is None or not buyer.tax_id or not buyer.legal_name or not buyer.governate or not buyer.street:
        out.append(_issue('buyer', 'بيانات المشتري الضريبية ناقصة', client_id=doc.claim.client.id))
    elif buyer.tax_id == issuer.tax_id:
        out.append(_issue('buyer', 'رقم المشتري الضريبي هو نفس رقم الممول'))

    if doc.doc_type == TaxDocument.TYPE_INVOICE:
        if doc.claim.status not in FINALIZED_CLAIM_STATUSES:
            out.append(_issue('claim_status', 'المطالبة لم تعد مقفلة في التأمين'))
        if snapshot_hash(build_snapshot(doc.claim)) != doc.source_hash:
            out.append(_issue('source_changed', 'المطالبة تغيرت بعد الاستيراد؛ حدّث المصدر وراجع الفرق'))
        rec = reconciliation(doc, issuer)
        if not rec['within_tolerance']:
            out.append(_issue('unreconciled', f'فرق غير مفسر بين المطالبة والفاتورة: {rec["unexplained"]} ج.م'))
    return out


def counts(doc):
    out = {s: 0 for s, _ in TaxDocumentLine.STATUS_CHOICES}
    for status in doc.lines.values_list('status', flat=True):
        out[status] += 1
    out['unresolved'] = out[TaxDocumentLine.ST_UNCODED] + out[TaxDocumentLine.ST_PENDING]
    out['total'] = sum(out[s] for s, _ in TaxDocumentLine.STATUS_CHOICES)
    return out


def affected_skus(doc):
    rows = {}
    for l in doc.lines.exclude(status__in=[TaxDocumentLine.ST_APPROVED, TaxDocumentLine.ST_EXEMPT]):
        r = rows.setdefault(l.softech_itemcode, {'itemcode': l.softech_itemcode, 'item_name': l.item_name,
                                                 'status': l.status, 'reason': l.status_reason, 'lines': 0,
                                                 'net': ZERO})
        r['lines'] += 1
        r['net'] += l.source_net
    return [{**r, 'net': str(r['net'])} for r in rows.values()]


# ── Approval ───────────────────────────────────────────────────────────────────────────────────

def build_payload_text(doc, issued_utc, issuer=None):
    issuer = issuer or TaxIssuerProfile.load()
    buyer = TaxBuyerProfile.objects.get(client=doc.claim.client)
    references = [doc.original.eta_uuid] if doc.original_id else None
    return fiscal.to_text(fiscal.document_json(
        doc_type=doc.doc_type, internal_id=doc.internal_id, issued_utc=issued_utc, issuer=issuer, buyer=buyer,
        lines=build_fiscal_lines(doc, issuer), version=DOCUMENT_VERSION, references=references))


def approve(doc_id, actor):
    with transaction.atomic():
        doc = TaxDocument.objects.select_for_update().get(pk=doc_id)
        if doc.status != TaxDocument.DRAFT:
            raise TaxRuleError('تُعتمد المسودة فقط')
        revalidate(doc)
        issuer = TaxIssuerProfile.load()
        issues = blockers(doc, issuer)
        if issues:
            raise TaxBlocked(issues)
        issued = timezone.now()
        doc.payload_text = build_payload_text(doc, issued, issuer)
        doc.payload_hash = fiscal.sha256_hex(doc.payload_text)
        doc.date_time_issued = issued
        doc.signed_payload_text = ''
        doc.eta_uuid = doc.eta_long_id = doc.eta_submission_uuid = doc.eta_status_reason = ''
        doc.approved_by, doc.approved_at = actor, issued
        set_status(doc, TaxDocument.APPROVED, actor, reason='اعتماد المستند')
        audit('payload_frozen', document=doc, actor=actor, after={'payload_hash': doc.payload_hash,
                                                                  'total': str(doc.total_amount)})
    return doc


def reopen(doc_id, actor, reason):
    if not (reason or '').strip():
        raise TaxRuleError('اكتب سبب إعادة الفتح')
    with transaction.atomic():
        doc = TaxDocument.objects.select_for_update().get(pk=doc_id)
        if doc.status not in (TaxDocument.APPROVED, TaxDocument.INVALID, TaxDocument.REJECTED):
            raise TaxRuleError('لا يمكن إعادة فتح هذا المستند؛ بعد قبول المصلحة تكون التعديلات بإشعار دائن أو مدين')
        doc.payload_text = doc.payload_hash = doc.signed_payload_text = ''
        doc.date_time_issued = None
        set_status(doc, TaxDocument.DRAFT, actor, reason=reason)
        revalidate(doc)
    return doc


# ── Line review ────────────────────────────────────────────────────────────────────────────────

def request_review(line, actor, category, reason, *, supporting_reference='', basis_id=None):
    doc = line.document
    if doc.status not in EDITABLE:
        raise TaxRuleError('تُراجع البنود في المسودة فقط')
    if category not in dict(TaxLineReview.CATEGORY_CHOICES):
        raise TaxRuleError('تصنيف غير معروف')
    if not (reason or '').strip():
        raise TaxRuleError('اكتب السبب')
    if line.reviews.filter(state=TaxLineReview.OPEN).exists():
        raise TaxRuleError('هذا البند عليه مراجعة مفتوحة')
    basis = None
    if basis_id:
        basis = TaxExclusionBasis.objects.filter(pk=basis_id).first()
        if basis is None:
            raise TaxRuleError('الأساس غير موجود')
    with transaction.atomic():
        review = TaxLineReview.objects.create(
            line=line, document=doc, source_line_id=line.source_line_id, softech_itemcode=line.softech_itemcode,
            category=category, reason=reason.strip(), supporting_reference=(supporting_reference or '').strip(),
            basis=basis, requested_by=actor, effect_net=line.net_ex_vat, effect_vat=line.vat_amount,
            effect_gross=line.total_incl_vat)
        audit('review_requested', document=doc, actor=actor, reason=reason, entity='line', entity_id=line.pk,
              after={'category': category, 'item': line.softech_itemcode, 'net': str(line.net_ex_vat),
                     'vat': str(line.vat_amount), 'gross': str(line.total_incl_vat)})
        revalidate(doc)
    return review


def decide_review(review_id, actor, accept, note=''):
    """Accepting an exclusion needs a reason, an active documented basis and a second person.
    If any is missing it refuses, so the line stays unresolved and the draft stays blocked."""
    with transaction.atomic():
        review = TaxLineReview.objects.select_for_update().select_related('document', 'line', 'basis').get(pk=review_id)
        doc = review.document
        if review.state != TaxLineReview.OPEN:
            raise TaxRuleError('تم البت في هذه المراجعة')
        if doc.status not in EDITABLE:
            raise TaxRuleError('تُراجع البنود في المسودة فقط')
        if accept and review.category == TaxLineReview.CAT_EXCLUSION:
            if TaxIssuerProfile.load().exclusion_second_person and review.requested_by_id == getattr(actor, 'pk', None):
                raise TaxRuleError('يبت في طلب الاستبعاد شخص غير من طلبه')
            if review.basis is None or not review.basis.is_active or review.basis.kind != TaxExclusionBasis.KIND_EXCLUSION:
                raise TaxRuleError('لا يمكن قبول الاستبعاد بدون أساس استبعاد موثق ساري')
            if not review.supporting_reference:
                raise TaxRuleError('لا يمكن قبول الاستبعاد بدون مرجع داعم')
        if not accept and not (note or '').strip():
            raise TaxRuleError('اكتب سبب الرفض')
        review.state = TaxLineReview.ACCEPTED if accept else TaxLineReview.DECLINED
        review.reviewed_by, review.reviewed_at, review.review_note = actor, timezone.now(), (note or '').strip()
        review.save()
        audit('review_decided', document=doc, actor=actor, reason=note, entity='line', entity_id=review.line_id or '',
              after={'category': review.category, 'state': review.state,
                     'basis': str(review.basis) if review.basis else '', 'net': str(review.effect_net),
                     'vat': str(review.effect_vat), 'gross': str(review.effect_gross)})
        revalidate(doc)
    return review


def revalidate_drafts_for_items(itemcodes):
    docs = TaxDocument.objects.filter(status=TaxDocument.DRAFT, lines__softech_itemcode__in=list(itemcodes)).distinct()
    for doc in docs:
        revalidate(doc)
    from .receipts import revalidate_for_items
    revalidate_for_items(itemcodes)
    return docs.count()


# ── Credit and debit notes ─────────────────────────────────────────────────────────────────────

def create_note(original_id, actor, note_type, reason, items):
    """A note after ETA accepted the invoice. `items`: [{line_id, amount}] where amount is on the
    same basis as the source line's net. The original's payload and totals are never touched."""
    if note_type not in (TaxDocument.TYPE_CREDIT, TaxDocument.TYPE_DEBIT):
        raise TaxRuleError('نوع الإشعار غير معروف')
    if not (reason or '').strip():
        raise TaxRuleError('اكتب سبب الإشعار')
    if not items:
        raise TaxRuleError('حدد البنود والمبالغ')
    with transaction.atomic():
        original = TaxDocument.objects.select_for_update().get(pk=original_id)
        if original.status != TaxDocument.VALID or not original.eta_uuid or original.doc_type != TaxDocument.TYPE_INVOICE:
            raise TaxRuleError('يصدر الإشعار على فاتورة قبلتها المصلحة فقط')
        note = TaxDocument.objects.create(
            doc_type=note_type, claim=original.claim, original=original, reason=reason.strip(), created_by=actor,
            internal_id=next_internal_id(note_type, timezone.now().year),
            presentation_mode=TaxBuyerProfile.MODE_DETAILED,
            source_snapshot={'original': original.internal_id, 'original_uuid': original.eta_uuid,
                             'items': [{'line_id': i.get('line_id'), 'amount': str(i.get('amount'))} for i in items]})
        for item in items:
            try:
                amount = Decimal(str(item.get('amount')))
            except Exception as exc:
                raise TaxRuleError('مبلغ غير صحيح') from exc
            if amount <= 0:
                raise TaxRuleError('مبلغ الإشعار يجب أن يكون موجباً')
            source = original.lines.filter(pk=item.get('line_id')).first()
            if source is None or not source.on_invoice:
                raise TaxRuleError('البند ليس من بنود الفاتورة الأصلية')
            if note_type == TaxDocument.TYPE_CREDIT:
                credited = sum((a.source_net for a in source.adjustments.filter(
                    document__doc_type=TaxDocument.TYPE_CREDIT).exclude(document=note)), ZERO)
                if amount + credited > source.source_net:
                    raise TaxRuleError(f'الإشعار الدائن يتجاوز قيمة البند {source.softech_itemcode}')
            TaxDocumentLine.objects.create(
                document=note, adjusts_line=source, source_docnumber=source.source_docnumber,
                source_docdate=source.source_docdate, source_branchcode=source.source_branchcode,
                softech_itemcode=source.softech_itemcode, item_name=source.item_name, quantity=Decimal('1'),
                unit_price=amount, source_gross=amount, source_discount=ZERO, source_net=amount,
                status=source.status, status_reason=source.status_reason, code_type=source.code_type,
                eta_code=source.eta_code, unit_type=source.unit_type, tax_treatment=source.tax_treatment,
                vat_rate=source.vat_rate)
        issuer = TaxIssuerProfile.load()
        for line in note.lines.all():
            net, vat = fiscal.split_vat(line.source_net, line.vat_rate, issuer.prices_include_vat)
            line.net_ex_vat, line.vat_amount, line.total_incl_vat = net, vat, fiscal.q5(net + vat)
            line.save()
        t = fiscal_totals(note, issuer)
        note.total_sales, note.total_discount = t['sales_total'], t['discount']
        note.net_amount, note.vat_amount, note.total_amount = t['net'], t['vat'], t['total']
        note.save()
        audit('note_created', document=note, actor=actor, reason=reason,
              after={'original': original.internal_id, 'original_uuid': original.eta_uuid, 'type': note_type,
                     'amount': str(note.total_amount)})
    return note
