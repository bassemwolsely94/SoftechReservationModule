"""
apps/replacement/actions.py — human decisions on a reconstructed case (Phase 0).

Only link-level decisions exist in Phase 0 (no SOFTECH writes, no money movement):
  • confirm / reject a proposed voucher → product-receipt link
  • acknowledge / resolve an exception
Each decision is audited, recorded on the lineage edge (decided_by) so the reconstruction
never overrides it, and immediately re-runs the case so the ledger reclassifies through
compensating entries (append-only).
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.lineage.models import DocumentEdge as Edge

from . import reconstruct as R
from .models import CaseDocument as CD, CaseException as X, ReplacementCase as RC


def _voucher_edge(cd: CD) -> Edge:
    if cd.role != CD.ROLE_PRODUCT_SALE or not cd.parent_id:
        raise ValidationError('هذا الإجراء متاح لروابط فواتير منتجات البدل فقط.')
    edge = Edge.objects.filter(from_ref=cd.parent.document, to_ref=cd.document,
                               relation=Edge.REL_FUNDED_BY).first()
    if not edge:
        raise ValidationError('لا توجد علاقة مستندات لهذا الرابط.')
    return edge


@transaction.atomic
def decide_link(case: RC, casedoc_id: int, *, confirm: bool, user, note='', request=None) -> RC:
    cd = CD.objects.select_for_update(of=('self',)).select_related('parent__document', 'document').get(
        pk=casedoc_id, case=case)
    edge = _voucher_edge(cd)
    before = {'status': cd.status, 'edge': edge.status}
    edge.status = Edge.STATUS_CONFIRMED if confirm else Edge.STATUS_REJECTED
    edge.decided_by, edge.decided_at, edge.decision_note = user, timezone.now(), (note or '')[:300]
    edge.save(update_fields=['status', 'decided_by', 'decided_at', 'decision_note', 'updated_at'])
    if not confirm:
        cd.status, cd.origin = CD.STATUS_REJECTED, 'manual'
        cd.save(update_fields=['status', 'origin', 'updated_at'])
    AuditLog.log('replacement_link_confirmed' if confirm else 'replacement_link_rejected',
                 user=user, obj=case, old_data=before,
                 new_data={'status': edge.status, 'receipt': str(cd.document), 'voucher': str(cd.parent.document)},
                 extra={'correlation_id': str(case.correlation_id), 'casedoc': cd.pk},
                 note=(note or '')[:255], request=request)
    if case.purchase_invoice_id:
        R.reconstruct_invoice(case.purchase_invoice, tabdeel=R.tabdeel_pics(), user=user)
    case.refresh_from_db()
    return case


@transaction.atomic
def decide_exception(case: RC, exception_id: int, *, status: str, user, note='', request=None) -> X:
    if status not in (X.STATUS_ACK, X.STATUS_RESOLVED):
        raise ValidationError('حالة غير صالحة.')
    if status == X.STATUS_RESOLVED and not (note or '').strip():
        raise ValidationError('يجب كتابة سبب الحل.')
    exc = X.objects.select_for_update().get(pk=exception_id, case=case)
    before = exc.status
    exc.status, exc.resolution = status, (note or '')[:2000]
    if status == X.STATUS_RESOLVED:
        exc.resolved_by, exc.resolved_at = user, timezone.now()
    else:
        exc.owner = exc.owner or user
    exc.save()
    R.recount_exceptions(case)
    case.save(update_fields=['open_exceptions', 'max_severity', 'updated_at'])
    AuditLog.log('replacement_exception_resolved', user=user, obj=case,
                 old_data={'status': before}, new_data={'status': status, 'type': exc.exception_type},
                 extra={'correlation_id': str(case.correlation_id), 'exception': exc.pk},
                 note=(note or '')[:255], request=request)
    return exc
