"""
apps/tax_invoicing/views.py — mounted at /api/tax-invoicing/ (doc 36).

  GET  me/                               what this user may do
  GET  claims/                           finalized claims and their invoice status
  POST claims/<id>/invoice/              open the claim's invoice, or create its draft
  GET  documents/                        history (?status=&type=&q=)
  GET  documents/<id>/?view=all          review data; view=all needs `approve`, display only
  POST documents/<id>/revalidate/ · refresh-source/ · presentation/
  POST documents/<id>/approve/ · reopen/ · preview/ · submit/ · reconcile/ · notes/
  POST documents/<id>/lines/<lid>/review/
  POST reviews/<id>/decide/
  GET  exceptions/                       every unresolved SKU and the drafts it holds up
  GET|POST items/   PATCH items/<id>/    POST items/import/ (preview unless commit=1)
  GET|POST bases/   POST bases/<id>/deactivate/
  GET|PATCH issuer/    GET|POST buyers/
Every rule is enforced in services.py or here; the screen only hides what the user cannot do.
"""
import datetime as dt
import logging

from django.conf import settings
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.insurance.models import InsuranceClaim, InsuranceClient
from config.writers import writer_allowed
from core.errors import public_error
from core.permissions import _get_profile, matrix_allows, matrix_permission

from . import item_import, receipts, services, signing, submission
from .models import (TaxBuyerProfile, TaxChannelRule, TaxDocument, TaxDocumentLine, TaxExclusionBasis,
                     TaxIssuerProfile, TaxItemProfile, TaxLineReview, TaxReceipt, TaxReceiptBranchConfig, TaxReceiptLine, TaxSigningJob)

logger = logging.getLogger('elrezeiky.tax_invoicing')
MODULE = 'tax_invoicing'
VIEWER = matrix_permission(MODULE)
CREATOR = matrix_permission(MODULE, get=('view',), post=('create',))
EDITOR = matrix_permission(MODULE, get=('view',), post=('edit',), edit=('edit',))
APPROVER = matrix_permission(MODULE, post=('approve',))
SENDER = matrix_permission(MODULE, post=('finalize',), edit=('finalize',))
MAX_LIST = 300


def _can(request, action):
    return matrix_allows(_get_profile(request), MODULE, action)


def _refuse(exc):
    body = {'detail': str(exc)}
    if isinstance(exc, services.TaxBlocked):
        body['issues'] = exc.issues
    return Response(body, status=status.HTTP_400_BAD_REQUEST)


def _stamp(user):
    return getattr(user, 'username', '') if user else ''


# ── Serialising ────────────────────────────────────────────────────────────────────────────────

def doc_row(d):
    return {'id': d.id, 'internal_id': d.internal_id, 'doc_type': d.doc_type, 'doc_type_label': d.get_doc_type_display(),
            'status': d.status, 'status_label': d.get_status_display(), 'claim_id': d.claim_id,
            'claim_number': d.claim.claim_number, 'client': str(d.claim.client),
            'source_claim_total': str(d.source_claim_total), 'total_amount': str(d.total_amount),
            'vat_amount': str(d.vat_amount), 'eta_uuid': d.eta_uuid, 'original_id': d.original_id,
            'original_internal_id': d.original.internal_id if d.original_id else '',
            'created_at': d.created_at, 'approved_at': d.approved_at}


def line_row(l):
    return {'id': l.id, 'docnumber': l.source_docnumber, 'docdate': l.source_docdate, 'branch': l.source_branchcode,
            'itemcode': l.softech_itemcode, 'item_name': l.item_name, 'quantity': str(l.quantity),
            'gross': str(l.source_gross), 'discount': str(l.source_discount), 'net': str(l.source_net),
            'softech_line_net': None if l.softech_line_net is None else str(l.softech_line_net),
            'status': l.status, 'status_label': l.get_status_display(), 'reason': l.status_reason,
            'code_type': l.code_type, 'eta_code': l.eta_code, 'tax_treatment': l.tax_treatment,
            'vat_rate': str(l.vat_rate), 'net_ex_vat': str(l.net_ex_vat), 'vat_amount': str(l.vat_amount),
            'total_incl_vat': str(l.total_incl_vat)}


def review_row(r):
    return {'id': r.id, 'line_id': r.line_id, 'itemcode': r.softech_itemcode, 'category': r.category,
            'category_label': r.get_category_display(), 'state': r.state, 'state_label': r.get_state_display(),
            'reason': r.reason, 'supporting_reference': r.supporting_reference,
            'basis': str(r.basis) if r.basis else '', 'effect_net': str(r.effect_net), 'effect_vat': str(r.effect_vat),
            'effect_gross': str(r.effect_gross), 'requested_by': _stamp(r.requested_by), 'requested_at': r.requested_at,
            'reviewed_by': _stamp(r.reviewed_by), 'reviewed_at': r.reviewed_at, 'review_note': r.review_note}


def item_row(p):
    return {'id': p.id, 'itemcode': p.softech_itemcode, 'item_name': p.item_name, 'code_type': p.code_type,
            'eta_code': p.eta_code, 'coding_status': p.coding_status, 'coding_status_label': p.get_coding_status_display(),
            'unit_type': p.unit_type, 'tax_treatment': p.tax_treatment, 'tax_treatment_label': p.get_tax_treatment_display(),
            'vat_rate': str(p.vat_rate), 'treatment_reference': p.treatment_reference,
            'source_vat_code': p.source_vat_code,
            'source_vat_rate': None if p.source_vat_rate is None else str(p.source_vat_rate),
            'gpc_code': p.gpc_code, 'item_name_ar': p.item_name_ar, 'active_from': p.active_from,
            'treatment_confirmed_at': p.treatment_confirmed_at, 'treatment_confirmed_by': _stamp(p.treatment_confirmed_by),
            'list_status': p.list_status, 'list_status_label': p.get_list_status_display(),
            'listed_reason': p.listed_reason, 'disposition': p.disposition, 'disposition_label': p.get_disposition_display()}


# ── Who am I ───────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def me(request):
    return Response({'can_create': _can(request, 'create'), 'can_edit': _can(request, 'edit'),
                     'can_approve': _can(request, 'approve'), 'can_view_all_lines': _can(request, 'approve'),
                     'can_finalize': _can(request, 'finalize'), 'submit_enabled': writer_allowed(submission.FLAG),
                     'receipt_submit_enabled': writer_allowed(receipts.FLAG),
                     'document_statuses': [{'key': k, 'label': v} for k, v in TaxDocument.STATUS_CHOICES],
                     'line_statuses': [{'key': k, 'label': v} for k, v in TaxDocumentLine.STATUS_CHOICES],
                     'receipt_statuses': [{'key': k, 'label': v} for k, v in TaxReceipt.STATUS_CHOICES]})


# ── Claims ─────────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def claims(request):
    qs = InsuranceClaim.objects.filter(status__in=services.FINALIZED_CLAIM_STATUSES).select_related('subclient__client')
    q = (request.query_params.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(claim_number__icontains=q) | Q(softech_motalba_no__icontains=q) | Q(subclient__client__name__icontains=q))
    qs = list(qs.order_by('-period_to', '-id')[:MAX_LIST])
    invoices = {d.claim_id: d for d in TaxDocument.objects.filter(doc_type='i', claim__in=qs)}
    return Response([{'id': c.id, 'claim_number': c.claim_number, 'softech_motalba_no': c.softech_motalba_no,
                      'client': str(c.client), 'client_id': c.client.id, 'period_from': c.period_from,
                      'period_to': c.period_to, 'claim_status': c.status, 'final_net_after': str(c.final_net_after),
                      'invoice_id': invoices[c.id].id if c.id in invoices else None,
                      'invoice_status': invoices[c.id].status if c.id in invoices else '',
                      'invoice_status_label': invoices[c.id].get_status_display() if c.id in invoices else '',
                      'internal_id': invoices[c.id].internal_id if c.id in invoices else ''} for c in qs])


@api_view(['POST'])
@permission_classes([IsAuthenticated, CREATOR])
def claim_invoice(request, pk):
    claim = get_object_or_404(InsuranceClaim, pk=pk)
    try:
        doc, created = services.open_or_create_invoice(claim, request.user)
    except services.TaxRuleError as exc:
        return _refuse(exc)
    return Response({'id': doc.id, 'internal_id': doc.internal_id, 'created': created},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated, matrix_permission('insurance')])
def claim_fiscal_status(request, pk):
    """Read-only status on the claim screen. Mounted under /api/insurance/, so insurance staff see
    it without holding the tax module."""
    claim = get_object_or_404(InsuranceClaim, pk=pk)
    rows = TaxDocument.objects.filter(claim=claim).order_by('id')
    return Response({'claim_id': claim.id, 'documents': [
        {'id': d.id, 'internal_id': d.internal_id, 'doc_type': d.doc_type, 'doc_type_label': d.get_doc_type_display(),
         'status': d.status, 'status_label': d.get_status_display(), 'eta_uuid': d.eta_uuid,
         'total_amount': str(d.total_amount)} for d in rows]})


# ── Documents ──────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def documents(request):
    qs = TaxDocument.objects.select_related('claim__subclient__client', 'original')
    if request.query_params.get('status'):
        qs = qs.filter(status=request.query_params['status'])
    if request.query_params.get('type'):
        qs = qs.filter(doc_type=request.query_params['type'])
    q = (request.query_params.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(internal_id__icontains=q) | Q(claim__claim_number__icontains=q) | Q(eta_uuid__icontains=q))
    return Response([doc_row(d) for d in qs[:MAX_LIST]])


def _detail(request, doc):
    show_all = request.query_params.get('view') == 'all'
    if show_all and not _can(request, 'approve'):
        return Response({'detail': 'عرض كل بنود المصدر لمن يملك صلاحية المراجعة'}, status=status.HTTP_403_FORBIDDEN)
    issuer = TaxIssuerProfile.load()
    lines = doc.lines.all()
    visible = lines if show_all else lines.filter(status=TaxDocumentLine.ST_APPROVED)
    mode, mode_reason = services.fiscal_mode(doc, issuer)
    live = doc.status == TaxDocument.DRAFT
    body = doc_row(doc)
    body.update({
        'view': 'all' if show_all else 'approved',
        'lines': [line_row(l) for l in visible],
        # Counts and totals are the same in both views.
        'counts': services.counts(doc),
        'reconciliation': services.reconciliation(doc, issuer),
        'totals': {'sales': str(doc.total_sales), 'discount': str(doc.total_discount), 'net': str(doc.net_amount),
                   'vat': str(doc.vat_amount), 'total': str(doc.total_amount)},
        'blockers': services.blockers(doc, issuer) if live else [],
        'affected_skus': services.affected_skus(doc),
        'reviews': [review_row(r) for r in doc.line_reviews.select_related('requested_by', 'reviewed_by', 'basis')],
        'presentation_mode': doc.presentation_mode, 'fiscal_mode': mode, 'fiscal_mode_reason': mode_reason,
        'payload_hash': doc.payload_hash, 'date_time_issued': doc.date_time_issued, 'reason': doc.reason,
        'eta_long_id': doc.eta_long_id, 'eta_submission_uuid': doc.eta_submission_uuid,
        'eta_status_reason': doc.eta_status_reason, 'eta_checked_at': doc.eta_checked_at,
        'source_refreshed_at': doc.source_refreshed_at,
        'source_summary': {k: len(doc.source_snapshot.get(k) or []) for k in
                           ('prescriptions', 'lines', 'excluded_prescriptions', 'supplements', 'manual_rx')},
        'attempts': [{'id': a.id, 'state': a.state, 'state_label': a.get_state_display(), 'http_status': a.http_status,
                      'error': a.error, 'started_at': a.started_at, 'finished_at': a.finished_at} for a in doc.attempts.all()[:20]],
        'events': [{'id': e.id, 'action': e.action, 'actor': _stamp(e.actor), 'reason': e.reason, 'before': e.before,
                    'after': e.after, 'created_at': e.created_at} for e in doc.events.select_related('actor')[:100]],
        'notes': [doc_row(n) for n in doc.notes.select_related('claim__subclient__client', 'original')],
    })
    return Response(body)


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def document_detail(request, pk):
    doc = get_object_or_404(TaxDocument.objects.select_related('claim__subclient__client', 'original'), pk=pk)
    return _detail(request, doc)


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def document_print(request, pk):
    """Customer-facing layout: one summary line when the buyer is on summary, with no patient or
    internal data. The item breakdown stays on the review screen."""
    doc = get_object_or_404(TaxDocument.objects.select_related('claim__subclient__client', 'original'), pk=pk)
    issuer = TaxIssuerProfile.load()
    buyer = TaxBuyerProfile.objects.filter(client=doc.claim.client).first()
    on = [l for l in doc.lines.all() if l.on_invoice]
    if doc.presentation_mode == TaxBuyerProfile.MODE_SUMMARY and doc.doc_type == TaxDocument.TYPE_INVOICE:
        rows = [{'description': f'{issuer.summary_description or "مطالبة مالية"} — {doc.claim.claim_number}',
                 'quantity': '1', 'net': str(doc.net_amount), 'vat': str(doc.vat_amount), 'total': str(doc.total_amount)}]
    else:
        rows = [{'description': l.item_name or l.softech_itemcode, 'quantity': str(l.quantity), 'net': str(l.net_ex_vat),
                 'vat': str(l.vat_amount), 'total': str(l.total_incl_vat)} for l in on]
    return Response({
        'internal_id': doc.internal_id, 'doc_type_label': doc.get_doc_type_display(), 'status': doc.status,
        'status_label': doc.get_status_display(), 'is_official': doc.status == TaxDocument.VALID,
        'date_time_issued': doc.date_time_issued, 'eta_uuid': doc.eta_uuid, 'eta_long_id': doc.eta_long_id,
        'issuer': {'name': issuer.name, 'tax_id': issuer.tax_id, 'street': issuer.street, 'region_city': issuer.region_city},
        'buyer': {'name': buyer.legal_name if buyer else str(doc.claim.client), 'tax_id': buyer.tax_id if buyer else '',
                  'street': buyer.street if buyer else ''},
        'claim_number': doc.claim.claim_number, 'period_from': doc.claim.period_from, 'period_to': doc.claim.period_to,
        'original_internal_id': doc.original.internal_id if doc.original_id else '', 'reason': doc.reason, 'rows': rows,
        'no_vat_due': doc.vat_amount == 0,
        'totals': {'net': str(doc.net_amount), 'vat': str(doc.vat_amount), 'total': str(doc.total_amount)},
    })


def _document_action(pk, fn):
    get_object_or_404(TaxDocument, pk=pk)
    try:
        doc = fn()
    except services.TaxRuleError as exc:
        return _refuse(exc)
    return Response(doc_row(TaxDocument.objects.select_related('claim__subclient__client', 'original').get(pk=doc.pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, CREATOR])
def revalidate(request, pk):
    return _document_action(pk, lambda: services.revalidate(TaxDocument.objects.get(pk=pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def refresh_source(request, pk):
    return _document_action(pk, lambda: services.refresh_source(TaxDocument.objects.get(pk=pk), request.user,
                                                                request.data.get('reason')))


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def presentation(request, pk):
    mode = request.data.get('mode')
    if mode not in dict(TaxBuyerProfile.MODE_CHOICES):
        return Response({'detail': 'طريقة عرض غير معروفة'}, status=status.HTTP_400_BAD_REQUEST)

    def change():
        doc = TaxDocument.objects.get(pk=pk)
        if doc.status != TaxDocument.DRAFT or doc.doc_type != TaxDocument.TYPE_INVOICE:
            raise services.TaxRuleError('تتغير طريقة العرض في مسودة الفاتورة فقط')
        with transaction.atomic():
            services.audit('presentation_changed', document=doc, actor=request.user,
                           before={'mode': doc.presentation_mode}, after={'mode': mode})
            doc.presentation_mode = mode
            doc.save()
            services.revalidate(doc)
        return doc
    return _document_action(pk, change)


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def approve(request, pk):
    return _document_action(pk, lambda: services.approve(pk, request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def reopen(request, pk):
    return _document_action(pk, lambda: services.reopen(pk, request.user, request.data.get('reason')))


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def preview(request, pk):
    doc = get_object_or_404(TaxDocument, pk=pk)
    try:
        return Response(submission.preview(doc))
    except services.TaxRuleError as exc:
        return _refuse(exc)


@api_view(['POST'])
@permission_classes([IsAuthenticated, SENDER])
def submit(request, pk):
    """Dry run unless dry_run is explicitly false."""
    doc = get_object_or_404(TaxDocument, pk=pk)
    if request.data.get('dry_run', True) is not False:
        try:
            return Response(submission.preview(doc))
        except services.TaxRuleError as exc:
            return _refuse(exc)
    try:
        doc = submission.submit(pk, request.user, request.data.get('confirm') or '')
    except services.TaxRuleError as exc:
        return _refuse(exc)
    except Exception as exc:
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(doc_row(TaxDocument.objects.select_related('claim__subclient__client', 'original').get(pk=doc.pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, SENDER])
def reconcile(request, pk):
    return _document_action(pk, lambda: submission.reconcile(pk, request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def notes(request, pk):
    get_object_or_404(TaxDocument, pk=pk)
    try:
        note = services.create_note(pk, request.user, request.data.get('type'), request.data.get('reason'),
                                    request.data.get('items') or [])
    except services.TaxRuleError as exc:
        return _refuse(exc)
    return Response({'id': note.id, 'internal_id': note.internal_id}, status=status.HTTP_201_CREATED)


# ── Line review ────────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated, CREATOR])
def line_review(request, pk, line_id):
    line = get_object_or_404(TaxDocumentLine.objects.select_related('document'), pk=line_id, document_id=pk)
    d = request.data
    try:
        review = services.request_review(line, request.user, d.get('category'), d.get('reason'),
                                         supporting_reference=d.get('supporting_reference'), basis_id=d.get('basis_id'))
    except services.TaxRuleError as exc:
        return _refuse(exc)
    return Response(review_row(review), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def decide_review(request, pk):
    get_object_or_404(TaxLineReview, pk=pk)
    try:
        review = services.decide_review(pk, request.user, bool(request.data.get('accept')), request.data.get('note'))
    except services.TaxRuleError as exc:
        return _refuse(exc)
    return Response(review_row(review))


# ── Exceptions: SKU → drafts ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def exceptions(request):
    rows = {}
    qs = (TaxDocumentLine.objects.filter(document__status=TaxDocument.DRAFT,
                                         status__in=[TaxDocumentLine.ST_UNCODED, TaxDocumentLine.ST_PENDING])
          .select_related('document__claim'))
    for l in qs[:20000]:
        r = rows.setdefault(l.softech_itemcode, {'itemcode': l.softech_itemcode, 'item_name': l.item_name,
                                                 'status': l.status, 'reason': l.status_reason, 'lines': 0, 'drafts': {}})
        r['lines'] += 1
        r['drafts'][l.document_id] = {'id': l.document_id, 'internal_id': l.document.internal_id,
                                      'claim_number': l.document.claim.claim_number}
    held = {}
    for code, n in (TaxReceiptLine.objects.filter(receipt__status=TaxReceipt.HELD).exclude(status__in=['approved', 'exempt'])
                    .values_list('itemcode').annotate(n=Count('id'))):
        held[code] = n
        rows.setdefault(code, {'itemcode': code, 'item_name': '', 'status': 'held', 'reason': 'إيصالات محجوزة', 'lines': 0, 'drafts': {}})
    for row in rows.values():
        row['held_receipt_lines'] = held.get(row['itemcode'], 0)
    profiles = {p.softech_itemcode: p.id for p in TaxItemProfile.objects.filter(softech_itemcode__in=list(rows))}
    return Response(sorted(({**r, 'drafts': list(r['drafts'].values()), 'profile_id': profiles.get(r['itemcode'])}
                            for r in rows.values()), key=lambda r: -r['lines']))


# ── Item mapping: coding · VAT classification · disposition ────────────────────────────────────

_TREATMENT_FIELDS = ('tax_treatment', 'vat_rate', 'treatment_reference')
_DISPOSITION_FIELDS = ('disposition',)
_CODING_FIELDS = ('code_type', 'eta_code', 'coding_status', 'unit_type', 'item_name', 'list_status', 'listed_reason')


def _apply_item(request, p, data):
    """Coding needs `edit`. Tax treatment and disposition are the accountant's: `approve`."""
    from decimal import Decimal, InvalidOperation
    touched_treatment = any(f in data for f in _TREATMENT_FIELDS)
    touched_disposition = any(f in data for f in _DISPOSITION_FIELDS)
    if (touched_treatment or touched_disposition) and not _can(request, 'approve'):
        return Response({'detail': 'المعاملة الضريبية وقرار الإدراج للمحاسب'}, status=status.HTTP_403_FORBIDDEN)
    before = item_row(p) if p.pk else {}
    for f in _CODING_FIELDS:
        if f in data:
            setattr(p, f, (data.get(f) or '').strip())
    if p.code_type and p.code_type not in ('GS1', 'EGS'):
        return Response({'detail': 'نوع الكود GS1 أو EGS'}, status=status.HTTP_400_BAD_REQUEST)
    if p.coding_status not in dict(TaxItemProfile.CODE_STATUS_CHOICES):
        return Response({'detail': 'حالة كود غير معروفة'}, status=status.HTTP_400_BAD_REQUEST)
    if p.coding_status == TaxItemProfile.CODE_APPROVED and not (p.eta_code and p.code_type):
        return Response({'detail': 'الكود المعتمد يحتاج الكود ونوعه'}, status=status.HTTP_400_BAD_REQUEST)
    if p.list_status not in dict(TaxItemProfile.LIST_CHOICES):
        return Response({'detail': 'قائمة غير معروفة'}, status=status.HTTP_400_BAD_REQUEST)
    if touched_treatment:
        treatment = data.get('tax_treatment', p.tax_treatment)
        if treatment not in dict(TaxItemProfile.TREATMENT_CHOICES):
            return Response({'detail': 'معاملة ضريبية غير معروفة'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rate = Decimal(str(data.get('vat_rate', p.vat_rate)))
        except InvalidOperation:
            return Response({'detail': 'نسبة غير صحيحة'}, status=status.HTTP_400_BAD_REQUEST)
        if treatment == TaxItemProfile.TREATMENT_TAXABLE and not (0 < rate <= 100):
            return Response({'detail': 'الصنف الخاضع يحتاج نسبة ضريبة'}, status=status.HTTP_400_BAD_REQUEST)
        if treatment in (TaxItemProfile.TREATMENT_EXEMPT, TaxItemProfile.TREATMENT_ZERO) \
                and not (data.get('treatment_reference', p.treatment_reference) or '').strip():
            return Response({'detail': 'اذكر مرجع الإعفاء أو النسبة الصفرية'}, status=status.HTTP_400_BAD_REQUEST)
        p.tax_treatment = treatment
        p.vat_rate = rate if treatment == TaxItemProfile.TREATMENT_TAXABLE else Decimal('0')
        p.treatment_reference = (data.get('treatment_reference', p.treatment_reference) or '').strip()
        p.treatment_confirmed_at = None if treatment == TaxItemProfile.TREATMENT_UNCLASSIFIED else timezone.now()
        p.treatment_confirmed_by = None if treatment == TaxItemProfile.TREATMENT_UNCLASSIFIED else request.user
    if touched_disposition:
        if data['disposition'] not in dict(TaxItemProfile.DISPOSITION_CHOICES):
            return Response({'detail': 'قرار غير معروف'}, status=status.HTTP_400_BAD_REQUEST)
        p.disposition = data['disposition']
    elif p.list_status == TaxItemProfile.LIST_BLACK and p.disposition == TaxItemProfile.DISP_INCLUDE and not before:
        p.disposition = TaxItemProfile.DISP_REVIEW
    if not p.item_id:
        from apps.catalog.models import Item
        p.item = Item.objects.filter(softech_id=p.softech_itemcode).first()
        p.item_name = p.item_name or (p.item.name if p.item else '')
    with transaction.atomic():
        p.save()
        services.audit('item_mapping_changed', actor=request.user, entity='item', entity_id=p.softech_itemcode,
                       reason=str(data.get('reason') or ''), before=before, after=item_row(p))
        n = services.revalidate_drafts_for_items({p.softech_itemcode})
    return Response({**item_row(p), 'revalidated_drafts': n}, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, EDITOR])
def items(request):
    if request.method == 'POST':
        code = (request.data.get('itemcode') or '').strip()
        if not code or len(code) > 10:
            return Response({'detail': 'كود الصنف مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        p = TaxItemProfile.objects.filter(softech_itemcode=code).first() or TaxItemProfile(softech_itemcode=code)
        return _apply_item(request, p, request.data)
    qs = TaxItemProfile.objects.select_related('treatment_confirmed_by')
    for param, field in (('coding_status', 'coding_status'), ('treatment', 'tax_treatment'),
                         ('list', 'list_status'), ('disposition', 'disposition')):
        if request.query_params.get(param):
            qs = qs.filter(**{field: request.query_params[param]})
    q = (request.query_params.get('q') or '').strip()
    if q:
        qs = qs.filter(Q(softech_itemcode__icontains=q) | Q(item_name__icontains=q) | Q(eta_code__icontains=q))
    return Response([item_row(p) for p in qs[:MAX_LIST]])


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, EDITOR])
def item_detail(request, pk):
    return _apply_item(request, get_object_or_404(TaxItemProfile, pk=pk), request.data)


def _workbook_step(request, step):
    f = request.FILES.get('file')
    if f is None or not f.name.lower().endswith('.xlsx'):
        return Response({'detail': 'ارفع ملف Excel بصيغة xlsx'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(step(f))
    except services.TaxRuleError as exc:
        return _refuse(exc)
    except ValueError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated, EDITOR])
@parser_classes([MultiPartParser, FormParser])
def items_import_inspect(request):
    header_row = int(request.data.get('header_row') or 1)
    return _workbook_step(request, lambda f: item_import.inspect_workbook(f, header_row=header_row))


@api_view(['POST'])
@permission_classes([IsAuthenticated, EDITOR])
@parser_classes([MultiPartParser, FormParser])
def items_import_preview(request):
    return _workbook_step(request, lambda f: item_import.preview(f, request.data.get('options')))


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
@parser_classes([MultiPartParser, FormParser])
def items_import_apply(request):
    return _workbook_step(request, lambda f: item_import.apply(f, request.data.get('options'), request.user,
                                                               request.data.get('preview_hash') or ''))


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def items_confirm_vat(request):
    """The accountant confirms a treatment for everything the workbook marks with one VAT code."""
    d = request.data
    code, treatment, reference = (d.get('vat_code') or '').strip(), d.get('tax_treatment'), (d.get('treatment_reference') or '').strip()
    if treatment not in (TaxItemProfile.TREATMENT_TAXABLE, TaxItemProfile.TREATMENT_EXEMPT, TaxItemProfile.TREATMENT_ZERO):
        return Response({'detail': 'معاملة ضريبية غير معروفة'}, status=status.HTTP_400_BAD_REQUEST)
    if not code or not reference:
        return Response({'detail': 'كود الضريبة والمرجع مطلوبان'}, status=status.HTTP_400_BAD_REQUEST)
    qs = TaxItemProfile.objects.filter(source_vat_code=code, treatment_confirmed_at__isnull=True)
    now = timezone.now()
    with transaction.atomic():
        codes, n = [], 0
        for p in qs.iterator():
            p.tax_treatment = treatment
            p.vat_rate = (p.source_vat_rate or 0) if treatment == TaxItemProfile.TREATMENT_TAXABLE else 0
            p.treatment_reference, p.treatment_confirmed_at, p.treatment_confirmed_by = reference, now, request.user
            p.save()
            codes.append(p.softech_itemcode)
            n += 1
        services.audit('items_vat_confirmed', actor=request.user, entity='item_vat', entity_id=code, reason=reference,
                       after={'tax_treatment': treatment, 'items': n})
        services.revalidate_drafts_for_items(set(codes))
    return Response({'confirmed': n})


# ── Exclusion bases ────────────────────────────────────────────────────────────────────────────

def _basis_row(b):
    return {'id': b.id, 'kind': b.kind, 'title': b.title, 'reference_number': b.reference_number, 'issued_by': b.issued_by,
            'document_url': b.document_url, 'applies_to': b.applies_to, 'is_active': b.is_active,
            'created_by': _stamp(b.created_by), 'created_at': b.created_at}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, SENDER])
def bases(request):
    if request.method == 'GET':
        return Response([_basis_row(b) for b in TaxExclusionBasis.objects.select_related('created_by')])
    d = request.data
    fields = {k: (d.get(k) or '').strip() for k in ('title', 'reference_number', 'issued_by', 'document_url', 'applies_to')}
    fields['kind'] = d.get('kind') or TaxExclusionBasis.KIND_EXCLUSION
    if fields['kind'] not in dict(TaxExclusionBasis.KIND_CHOICES):
        return Response({'detail': 'نوع الأساس غير معروف'}, status=status.HTTP_400_BAD_REQUEST)
    if not (fields['title'] and fields['reference_number'] and fields['issued_by'] and fields['applies_to']):
        return Response({'detail': 'العنوان ورقم المرجع والجهة ونطاق التطبيق مطلوبة'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        b = TaxExclusionBasis.objects.create(created_by=request.user, **fields)
        services.audit('basis_created', actor=request.user, entity='basis', entity_id=b.pk, after=_basis_row_plain(b))
    return Response(_basis_row(b), status=status.HTTP_201_CREATED)


def _basis_row_plain(b):
    return {'title': b.title, 'reference_number': b.reference_number, 'issued_by': b.issued_by, 'applies_to': b.applies_to}


@api_view(['POST'])
@permission_classes([IsAuthenticated, SENDER])
def basis_deactivate(request, pk):
    b = get_object_or_404(TaxExclusionBasis, pk=pk)
    with transaction.atomic():
        b.is_active = False
        b.save(update_fields=['is_active'])
        services.audit('basis_deactivated', actor=request.user, entity='basis', entity_id=b.pk,
                       reason=str(request.data.get('reason') or ''))
    return Response(_basis_row(b))


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def basis_options(request):
    """Active bases to choose from when asking for an exclusion. Names only."""
    return Response([{'id': b.id, 'kind': b.kind, 'label': str(b)} for b in TaxExclusionBasis.objects.filter(is_active=True)])


# ── Issuer and buyers ──────────────────────────────────────────────────────────────────────────

_ISSUER_TEXT = ('name', 'tax_id', 'activity_code', 'branch_id', 'country', 'governate', 'region_city', 'street',
                'building_number', 'default_unit_type', 'vat_tax_type', 'subtype_taxable', 'subtype_exempt',
                'subtype_zero_rated', 'summary_code_type', 'summary_item_code', 'summary_description', 'summary_treatment')


def _issuer_row(i):
    row = {f: getattr(i, f) for f in _ISSUER_TEXT}
    row.update(prices_include_vat=i.prices_include_vat, vat_basis_confirmed_at=i.vat_basis_confirmed_at,
               vat_basis_confirmed_by=_stamp(i.vat_basis_confirmed_by),
               summary_vat_rate=None if i.summary_vat_rate is None else str(i.summary_vat_rate),
               summary_validated_at=i.summary_validated_at, summary_validated_by=_stamp(i.summary_validated_by),
               reconcile_tolerance=str(i.reconcile_tolerance), exclusion_second_person=i.exclusion_second_person)
    return row


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated, SENDER])
def issuer(request):
    i = TaxIssuerProfile.load()
    if request.method == 'GET':
        return Response(_issuer_row(i))
    d = request.data
    before = _issuer_row(i)
    for f in _ISSUER_TEXT:
        if f in d:
            setattr(i, f, (d.get(f) or '').strip())
    if 'prices_include_vat' in d:
        i.prices_include_vat = bool(d['prices_include_vat'])
    if 'vat_basis_confirmed' in d:
        i.vat_basis_confirmed_at = timezone.now() if d['vat_basis_confirmed'] else None
        i.vat_basis_confirmed_by = request.user if d['vat_basis_confirmed'] else None
    if 'summary_vat_rate' in d:
        i.summary_vat_rate = d['summary_vat_rate'] if d['summary_vat_rate'] not in ('', None) else None
    if 'reconcile_tolerance' in d:
        i.reconcile_tolerance = d['reconcile_tolerance']
    if 'exclusion_second_person' in d:
        i.exclusion_second_person = bool(d['exclusion_second_person'])
    if 'summary_validated' in d:
        i.summary_validated_at = timezone.now() if d['summary_validated'] else None
        i.summary_validated_by = request.user if d['summary_validated'] else None
    with transaction.atomic():
        i.save()
        i.refresh_from_db()
        services.audit('issuer_changed', actor=request.user, entity='issuer', entity_id=1, before=_json_safe(before),
                       after=_json_safe(_issuer_row(i)))
        for doc in TaxDocument.objects.filter(status=TaxDocument.DRAFT):
            services.revalidate(doc)
    return Response(_issuer_row(i))


def _json_safe(row):
    return {k: (str(v) if v is not None and not isinstance(v, (str, bool, int)) else v) for k, v in row.items()}


_BUYER_TEXT = ('receiver_type', 'tax_id', 'legal_name', 'country', 'governate', 'region_city', 'street',
               'building_number', 'presentation_mode')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, EDITOR])
def buyers(request):
    if request.method == 'GET':
        rows = {b.client_id: b for b in TaxBuyerProfile.objects.select_related('zero_vat_basis')}
        def basis(c):
            b = rows[c.id].zero_vat_basis if c.id in rows else None
            return {'zero_vat_basis_id': b.id if b else None, 'zero_vat_basis': str(b) if b else ''}
        return Response([{'client_id': c.id, 'client': str(c), **basis(c),
                          **({f: getattr(rows[c.id], f) for f in _BUYER_TEXT} if c.id in rows else {'presentation_mode': 'summary'})}
                         for c in InsuranceClient.objects.filter(is_active=True)[:MAX_LIST]])
    d = request.data
    client = get_object_or_404(InsuranceClient, pk=d.get('client_id'))
    b = TaxBuyerProfile.objects.filter(client=client).first() or TaxBuyerProfile(client=client)
    before = {f: getattr(b, f) for f in _BUYER_TEXT} if b.pk else {}
    for f in _BUYER_TEXT:
        if f in d:
            setattr(b, f, (d.get(f) or '').strip())
    if 'zero_vat_basis_id' in d:
        if not _can(request, 'finalize'):
            return Response({'detail': 'تسجيل عدم استحقاق الضريبة يحتاج صلاحية الاعتماد النهائي'}, status=status.HTTP_403_FORBIDDEN)
        basis = None
        if d['zero_vat_basis_id']:
            basis = TaxExclusionBasis.objects.filter(pk=d['zero_vat_basis_id'], is_active=True, kind=TaxExclusionBasis.KIND_ZERO_VAT).first()
            if basis is None:
                return Response({'detail': 'لا يوجد أساس عدم استحقاق ضريبة ساري بهذا الرقم'}, status=status.HTTP_400_BAD_REQUEST)
        b.zero_vat_basis = basis
    if b.presentation_mode not in dict(TaxBuyerProfile.MODE_CHOICES):
        return Response({'detail': 'طريقة عرض غير معروفة'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        b.save()
        services.audit('buyer_changed', actor=request.user, entity='buyer', entity_id=client.id, before=before,
                       after={f: getattr(b, f) for f in _BUYER_TEXT})
        for doc in TaxDocument.objects.filter(status=TaxDocument.DRAFT, claim__subclient__client=client):
            services.revalidate(doc)
    return Response({'client_id': client.id, **{f: getattr(b, f) for f in _BUYER_TEXT}})


# ── Signing ────────────────────────────────────────────────────────────────────────────────────

def _cert_row(c):
    if c is None:
        return None
    return {'passed': c.passed, 'subject': c.subject, 'issuer': c.issuer, 'thumbprint': c.thumbprint, 'not_after': c.not_after,
            'detail': c.detail, 'created_at': c.created_at, 'requested_by': _stamp(c.requested_by)}


@api_view(['GET'])
@permission_classes([IsAuthenticated, matrix_permission(MODULE, get=('finalize',), post=('finalize',))])
def signing_status(request):
    signer = signing.get_signer()
    ready, why = True, ''
    try:
        signing.assert_ready_for_live(signer)
    except signing.SigningUnavailable as exc:
        ready, why = False, str(exc)
    last_job = TaxSigningJob.objects.order_by('-created_at', '-id').first()
    return Response({'signer': type(signer).__name__, 'is_mock': signer.is_mock, 'ready_for_live': ready, 'why_not': why,
                     'certification': _cert_row(signing.latest_certification()),
                     'pending_jobs': TaxSigningJob.objects.filter(status__in=[TaxSigningJob.PENDING, TaxSigningJob.CLAIMED]).count(),
                     'last_job_status': last_job.status if last_job else '',
                     'agent_configured': len(str(getattr(settings, 'TAX_SIGNING_AGENT_TOKEN', '') or '')) >= 32})


@api_view(['POST'])
@permission_classes([IsAuthenticated, SENDER])
def signing_smoke_test(request):
    job = signing.start_smoke_test(request.user)
    services.audit('signing_smoke_requested', actor=request.user, entity='signing', entity_id=job.pk)
    return Response({'job_id': job.id}, status=status.HTTP_201_CREATED)


def _agent_allowed(request):
    return signing.agent_token_ok(request.headers.get('X-Tax-Agent-Token', ''))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])  # gate: shared agent token, checked below; the agent has no user session
def agent_next_job(request):
    if not _agent_allowed(request):
        return Response({'detail': 'forbidden'}, status=status.HTTP_403_FORBIDDEN)
    with transaction.atomic():
        job = TaxSigningJob.objects.select_for_update(skip_locked=True).filter(status=TaxSigningJob.PENDING).first()
        if job is None:
            return Response({'job': None})
        job.status, job.claimed_at = TaxSigningJob.CLAIMED, timezone.now()
        job.save(update_fields=['status', 'claimed_at'])
    return Response({'job': {'id': job.id, 'kind': job.kind, 'canonical_text': job.canonical_text, 'sha256': job.canonical_sha256}})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])  # gate: shared agent token, checked below
def agent_job_result(request, pk):
    if not _agent_allowed(request):
        return Response({'detail': 'forbidden'}, status=status.HTTP_403_FORBIDDEN)
    with transaction.atomic():
        job = TaxSigningJob.objects.select_for_update().filter(pk=pk, status=TaxSigningJob.CLAIMED).first()
        if job is None:
            return Response({'detail': 'no such claimed job'}, status=status.HTTP_404_NOT_FOUND)
        signature = request.data.get('signature') or ''
        if signature:
            job.status, job.signature = TaxSigningJob.SIGNED, signature
        else:
            job.status, job.error = TaxSigningJob.FAILED, str(request.data.get('error') or 'no signature')[:1000]
        job.finished_at = timezone.now()
        job.save()
        if job.kind == TaxSigningJob.KIND_SMOKE:
            row = signing.record_smoke_result(job)
            services.audit('signing_smoke_result', actor=job.requested_by, entity='signing', entity_id=job.pk,
                           after={'passed': row.passed, 'thumbprint': row.thumbprint, 'detail': row.detail})
    return Response({'ok': True})


# ── E-receipts ─────────────────────────────────────────────────────────────────────────────────

def _receipt_row(r):
    return {'id': r.id, 'branch': r.softech_branchcode, 'doccode': r.doccode, 'docnumber': r.docnumber, 'docdate': r.docdate,
            'channel': r.channel, 'sold_at': r.sold_at, 'source_value': str(r.source_value), 'status': r.status,
            'status_label': r.get_status_display(), 'hold_reasons': r.hold_reasons, 'net_amount': str(r.net_amount),
            'vat_amount': str(r.vat_amount), 'total_amount': str(r.total_amount), 'uuid': r.uuid, 'eta_reason': r.eta_reason}


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def receipts_summary(request):
    return Response({'branches': receipts.summary_by_branch(),
                     'statuses': [{'key': k, 'label': v} for k, v in TaxReceipt.STATUS_CHOICES]})


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def receipts_list(request):
    qs = TaxReceipt.objects.all()
    for param, field in (('branch', 'softech_branchcode'), ('status', 'status'), ('channel', 'channel'),
                         ('from', 'docdate__gte'), ('to', 'docdate__lte')):
        if request.query_params.get(param):
            try:
                qs = qs.filter(**{field: request.query_params[param]})
            except (ValueError, ValidationError):
                return Response({'detail': 'تاريخ غير صحيح'}, status=status.HTTP_400_BAD_REQUEST)
    response = Response([_receipt_row(r) for r in qs[:MAX_LIST]])
    response['X-Total-Count'] = qs.count()
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def receipt_detail(request, pk):
    r = get_object_or_404(TaxReceipt, pk=pk)
    return Response({**_receipt_row(r), 'previous_uuid': r.previous_uuid, 'payload_text': r.payload_text, 'lines': [
        {'itemcode': l.itemcode, 'item_name': l.item_name, 'quantity': str(l.quantity), 'total': str(l.total),
         'source_vat_rate': str(l.source_vat_rate), 'vat_rate': str(l.vat_rate), 'status': l.status,
         'status_label': dict(TaxDocumentLine.STATUS_CHOICES).get(l.status, l.status), 'reason': l.status_reason,
         'eta_code': l.eta_code, 'net_ex_vat': str(l.net_ex_vat), 'vat_amount': str(l.vat_amount)} for l in r.lines.all()]})


@api_view(['POST'])
@permission_classes([IsAuthenticated, CREATOR])
def receipts_import(request):
    try:
        day = dt.date.fromisoformat(str(request.data.get('date')))
    except ValueError:
        return Response({'detail': 'تاريخ غير صحيح'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        return Response(receipts.import_branch_day(str(request.data.get('branch') or ''), day, request.user))
    except services.TaxRuleError as exc:
        return _refuse(exc)
    except Exception as exc:
        return Response({'detail': public_error(request, exc)}, status=status.HTTP_502_BAD_GATEWAY)


def _branch_action(fn):
    try:
        return Response(fn())
    except services.TaxRuleError as exc:
        return _refuse(exc)


@api_view(['POST'])
@permission_classes([IsAuthenticated, APPROVER])
def receipts_issue(request, branch):
    return _branch_action(lambda: receipts.issue_next(branch, request.user))


@api_view(['POST'])
@permission_classes([IsAuthenticated, SENDER])
def receipts_submit(request, branch):
    """Dry run unless dry_run is explicitly false."""
    if request.data.get('dry_run', True) is not False:
        return Response(receipts.preview_batch(branch))
    return _branch_action(lambda: receipts.submit_branch(branch, request.user, request.data.get('confirm') or ''))


@api_view(['POST'])
@permission_classes([IsAuthenticated, SENDER])
def receipts_reconcile(request, branch):
    return _branch_action(lambda: receipts.reconcile_branch(branch, request.user))


_CONFIG_TEXT = ('seller_branch_code', 'device_serial', 'pos_os_version', 'pos_model_framework', 'client_id', 'secret_env',
                'preshared_key_env', 'activity_code', 'governate', 'region_city', 'street', 'building_number', 'payment_method')


def _config_row(c):
    return {'branch': c.softech_branchcode, 'is_enabled': c.is_enabled, 'has_chain': bool(c.last_uuid),
            **{f: getattr(c, f) for f in _CONFIG_TEXT}}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, matrix_permission(MODULE, get=('view',), post=('finalize',))])
def receipt_configs(request):
    if request.method == 'GET':
        return Response([_config_row(c) for c in TaxReceiptBranchConfig.objects.all()])
    code = str(request.data.get('branch') or '').strip()
    if not code or len(code) > 5:
        return Response({'detail': 'كود الفرع مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
    c = TaxReceiptBranchConfig.objects.filter(softech_branchcode=code).first() or TaxReceiptBranchConfig(softech_branchcode=code)
    before = _config_row(c) if c.pk else {}
    for f in _CONFIG_TEXT:
        if f in request.data:
            setattr(c, f, str(request.data.get(f) or '').strip())
    if 'is_enabled' in request.data:
        c.is_enabled = bool(request.data['is_enabled'])
    with transaction.atomic():
        c.save()
        services.audit('receipt_config_changed', actor=request.user, entity='receipt_branch', entity_id=code,
                       before=before, after=_config_row(c))
    return Response(_config_row(c))


@api_view(['GET'])
@permission_classes([IsAuthenticated, VIEWER])
def channels_seen(request):
    """Channels on imported sales, with their counts and current rule, so no code is typed from memory."""
    rules = {r.ptclassifcode: r for r in TaxChannelRule.objects.all()}
    rows = TaxReceipt.objects.values('channel').annotate(documents=Count('id'), value=Sum('source_value')).order_by('-documents')
    return Response([{'channel': r['channel'], 'documents': r['documents'], 'value': str(r['value'] or 0),
                      'label': rules[r['channel']].label if r['channel'] in rules else '',
                      'mode': rules[r['channel']].mode if r['channel'] in rules else TaxChannelRule.MODE_UNDECIDED} for r in rows])


def _rule_row(r):
    return {'ptclassifcode': r.ptclassifcode, 'label': r.label, 'mode': r.mode, 'mode_label': r.get_mode_display(), 'note': r.note,
            'confirmed_by': _stamp(r.confirmed_by), 'confirmed_at': r.confirmed_at}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, APPROVER])
def channel_rules(request):
    if request.method == 'GET':
        return Response([_rule_row(r) for r in TaxChannelRule.objects.select_related('confirmed_by')])
    code = str(request.data.get('ptclassifcode') or '').strip()
    mode = request.data.get('mode')
    if not code or mode not in dict(TaxChannelRule.MODE_CHOICES):
        return Response({'detail': 'القناة والقرار مطلوبان'}, status=status.HTTP_400_BAD_REQUEST)
    r = TaxChannelRule.objects.filter(ptclassifcode=code).first() or TaxChannelRule(ptclassifcode=code)
    before = _rule_row(r) if r.pk else {}
    r.mode, r.label = mode, str(request.data.get('label', r.label) or '')[:100]
    r.note = str(request.data.get('note', r.note) or '')[:300]
    r.confirmed_by, r.confirmed_at = request.user, timezone.now()
    with transaction.atomic():
        r.save()
        services.audit('channel_rule_changed', actor=request.user, entity='channel', entity_id=code,
                       before=_json_safe(before), after=_json_safe(_rule_row(r)))
        n = receipts.reevaluate_channel(code)
    return Response({**_rule_row(r), 'reevaluated': n})
