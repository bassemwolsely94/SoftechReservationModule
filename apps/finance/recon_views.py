"""
apps/finance/recon_views.py — read-only API for the A/P–A/R reconciliation module
(Phase-C batch 4). Dashboard KPIs, candidate/exception/party lists, the workbench
3-pane payload, and a per-party حصر ledger.

All endpoints are READ-ONLY and require IsAuthenticated. Approval actions (which
create Allocations) are Phase E; SOFTECH write-back is Phase G (gated). Nothing
here mutates the mirror or SOFTECH.

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from decimal import Decimal

from django.db.models import Count, Sum, F, Max
from rest_framework import filters, generics
from apps.catalog.wildcard import WildcardSearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    ReconParty, APInvoice, Payment, Allocation, ReconciliationRun,
    MatchCandidate, ReconException,
)
from .recon_serializers import (
    ReconPartySerializer, APInvoiceSerializer, PaymentSerializer,
    AllocationSerializer, MatchCandidateSerializer, ReconExceptionSerializer,
    ReconciliationRunSerializer,
)
from . import recon_actions
from .views import _is_admin_or_pharmacist
from core.errors import public_error


def _scope(request, qs, party_path='party'):
    """Apply the shared filters (recon_filters: party_type, multi-select suppliers,
    document date range, document value range) + optional branch."""
    from . import recon_filters as RF
    kind = {ReconParty: 'party', APInvoice: 'invoice', Payment: 'payment',
            MatchCandidate: 'candidate', ReconException: 'exception',
            Allocation: 'allocation'}.get(qs.model)
    if kind is not None:
        qs = RF.apply(qs, RF.parse(request.query_params), kind)
        br = request.query_params.get('branch')
        if br and kind in ('invoice', 'payment'):
            qs = qs.filter(branchcode=br)
        return qs
    return _scope_legacy(request, qs, party_path)


def _scope_legacy(request, qs, party_path='party'):
    """Apply the common party_type / personcode / branch filters."""
    pt   = request.query_params.get('party_type')
    pc   = request.query_params.get('personcode')
    br   = request.query_params.get('branch')
    if pt:
        qs = qs.filter(**{f'{party_path}__party_type' if party_path else 'party_type': pt})
    if pc:
        qs = qs.filter(**{f'{party_path}__softech_personcode' if party_path else 'softech_personcode': pc})
    if br:
        qs = qs.filter(branchcode=br)
    return qs


def _sum(qs, field):
    return qs.aggregate(s=Sum(field))['s'] or Decimal('0')


# ── 1. dashboard KPIs ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reconciliation_dashboard(request):
    inv = _scope(request, APInvoice.objects.all())
    pay = _scope(request, Payment.objects.all())
    alloc = Allocation.objects.filter(payment__in=pay, invoice__in=inv)
    cand = _scope(request, MatchCandidate.objects.all())
    exc  = _scope(request, ReconException.objects.all())

    total_inv = inv.count()
    fully     = inv.filter(doc_value__lte=F('doc_value_pay')).count()   # outstanding ≤ 0

    data = {
        'invoices': {
            'count': total_inv,
            'value': _sum(inv, 'doc_value'),
            'fully_settled': fully,
            'not_fully_settled': total_inv - fully,
        },
        'payments': {
            'count': pay.count(),
            'value': _sum(pay, 'amount'),
            'unallocated_count': pay.filter(is_unallocated=True).count(),
            'unallocated_value': _sum(pay.filter(is_unallocated=True), 'amount'),
        },
        'allocations': {
            'count': alloc.count(),
            'value': _sum(alloc, 'amount'),
            'by_origin': dict(alloc.values_list('origin').annotate(n=Count('id'))),
        },
        'candidates': {
            'total': cand.count(),
            'by_confidence': dict(cand.values_list('confidence_class').annotate(n=Count('id'))),
            'by_status': dict(cand.values_list('status').annotate(n=Count('id'))),
            'proposed_value': _sum(cand.filter(status=MatchCandidate.STATUS_PROPOSED), 'proposed_amount'),
        },
        'exceptions': {
            'total': exc.filter(status='open').count(),
            'by_type': dict(exc.filter(status='open').values_list('exception_type').annotate(n=Count('id'))),
            'by_severity': dict(exc.filter(status='open').values_list('severity').annotate(n=Count('id'))),
        },
        'latest_run': ReconciliationRunSerializer(
            ReconciliationRun.objects.order_by('-started_at').first()
        ).data if ReconciliationRun.objects.exists() else None,
    }
    return Response(data)


# ── 2. lists ──────────────────────────────────────────────────────────────────

class ReconPartyListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ReconPartySerializer
    filter_backends    = [WildcardSearchFilter, filters.OrderingFilter]
    search_fields      = ['softech_personcode', 'name']
    ordering_fields    = ['softech_personcode', 'softech_balance']

    def get_queryset(self):
        return _scope(self.request, ReconParty.objects.all(), party_path='')


class InvoiceListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = APInvoiceSerializer
    filter_backends    = [WildcardSearchFilter, filters.OrderingFilter]
    search_fields      = ['docnumber', 'docnumber2']
    ordering_fields    = ['docdate', 'doc_value']
    ordering           = ['-docdate']

    def get_queryset(self):
        qs = _scope(self.request, APInvoice.objects.select_related('party'))
        if self.request.query_params.get('unsettled') == '1':
            qs = qs.filter(doc_value__gt=F('doc_value_pay'))   # outstanding > 0
        return qs


class PaymentListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = PaymentSerializer
    filter_backends    = [WildcardSearchFilter, filters.OrderingFilter]
    search_fields      = ['cheqsno', 'cheqno', 'ourcheqsno', 'note']
    ordering_fields    = ['voucher_date', 'amount']
    ordering           = ['-voucher_date']

    def get_queryset(self):
        qs = _scope(self.request, Payment.objects.select_related('party'))
        if self.request.query_params.get('unallocated') == '1':
            qs = qs.filter(is_unallocated=True)
        return qs


class ReconPagination(PageNumberPagination):
    """50 rows by default; the grid may ask for up to 500 (?page_size=)."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500


class StableOrdering(filters.OrderingFilter):
    """Column sort from the grid (?ordering=-invoice__doc_value) + id tie-break so
    paging over equal values never repeats or skips a row."""
    # a date column also orders by SOFTECH's entry timestamp within the same day
    TIME_TIEBREAK = {'invoice__docdate': 'invoice__trans_time',
                     'payment__voucher_date': 'payment__trans_time'}

    def get_ordering(self, request, queryset, view):
        o = super().get_ordering(request, queryset, view)
        if not o:
            return o
        out = []
        for f in o:
            out.append(f)
            t = self.TIME_TIEBREAK.get(f.lstrip('-'))
            if t:
                out.append(('-' if f.startswith('-') else '') + t)
        return [*out, 'id']


def _candidate_qs(request):
    """Candidates in scope — shared by the grid, the grouped review view and actions."""
    qs = _scope(request, MatchCandidate.objects.select_related(
        'party', 'invoice', 'payment', 'decided_by__user').prefetch_related(
        'evidence', 'allocations', 'invoice__allocations',      # → «المتبقي (محسوب)»
        'invoice__returned_by__return_invoice__allocations',    # → returns bound, «الصافي بعد المرتجع»
        'invoice__bound_receipts'))
    p = request.query_params
    for param, field in (('confidence_class', 'confidence_class'),
                         ('status', 'status'), ('invoice', 'invoice_id'),
                         ('payment', 'payment_id'), ('run', 'run_id'),
                         ('strategy', 'strategy'), ('group', 'group_key')):
        val = p.get(param)
        if val:
            qs = qs.filter(**{field: val})
    if p.get('held') == '1':      # the deep-revision queue
        qs = qs.filter(status=MatchCandidate.STATUS_PROPOSED,
                       decision_note__startswith=recon_actions.HOLD_PREFIX)
    if p.get('written_review') == '1':   # written, now needs a look
        qs = qs.filter(status=MatchCandidate.STATUS_WRITTEN,
                       decision_note__startswith=recon_actions.WRITTEN_REVIEW_PREFIX)
    return qs


class CandidateListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = MatchCandidateSerializer
    pagination_class   = ReconPagination
    filter_backends    = [StableOrdering]
    ordering_fields    = ['confidence_score', 'created_at', 'group_key', 'proposed_amount',
                          'invoice__docdate', 'invoice__doc_value', 'invoice__docnumber',
                          'payment__voucher_date', 'payment__amount', 'party__name',
                          'party__softech_personcode']
    ordering           = ['-confidence_score', 'group_key']

    def get_queryset(self):
        return _candidate_qs(self.request)

    def list(self, request, *args, **kwargs):
        # every row carries its rivals (other vouchers on the same invoice) and the invoice
        # its voucher's reference names when that is a different one (recon_rivals)
        resp = super().list(request, *args, **kwargs)
        from . import recon_rivals
        recon_rivals.annotate(resp.data.get('results', []))
        return resp


class ExceptionListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ReconExceptionSerializer
    pagination_class   = ReconPagination
    filter_backends    = [StableOrdering]
    ordering_fields    = ['created_at', 'anomaly_score', 'severity', 'exception_type',
                          'invoice__docdate', 'invoice__doc_value', 'payment__voucher_date',
                          'payment__amount', 'party__name']
    ordering           = ['-created_at']

    def get_queryset(self):
        qs = _scope(self.request, ReconException.objects.select_related('party', 'invoice', 'payment')
                    .prefetch_related('invoice__allocations', 'invoice__returned_by__return_invoice__allocations',
                                      'invoice__bound_receipts'))
        for param, field in (('exception_type', 'exception_type'),
                             ('severity', 'severity'), ('status', 'status')):
            val = self.request.query_params.get(param)
            if val:
                qs = qs.filter(**{field: val})
        return qs


class ReconRunListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class   = ReconciliationRunSerializer
    ordering           = ['-started_at']

    def get_queryset(self):
        return ReconciliationRun.objects.all()


# ── 3. workbench (3-pane payload) ─────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reconciliation_workbench(request):
    """
    ?invoice=<id>  → the invoice + its candidate payments (with evidence)
    ?payment=<id>  → the payment + its candidate invoices (with evidence)
    """
    inv_id = request.query_params.get('invoice')
    pay_id = request.query_params.get('payment')
    if inv_id:
        try:
            inv = APInvoice.objects.select_related('party').get(pk=inv_id)
        except APInvoice.DoesNotExist:
            return Response({'detail': 'invoice not found'}, status=404)
        cands = MatchCandidate.objects.filter(invoice=inv).select_related(
            'payment').prefetch_related('evidence').order_by('-confidence_score')
        return Response({
            'focus': 'invoice',
            'invoice': APInvoiceSerializer(inv).data,
            'candidates': MatchCandidateSerializer(cands, many=True).data,
            'existing_allocations': AllocationSerializer(inv.allocations.all(), many=True).data,
        })
    if pay_id:
        try:
            pay = Payment.objects.select_related('party').get(pk=pay_id)
        except Payment.DoesNotExist:
            return Response({'detail': 'payment not found'}, status=404)
        cands = MatchCandidate.objects.filter(payment=pay).select_related(
            'invoice').prefetch_related('evidence').order_by('-confidence_score')
        return Response({
            'focus': 'payment',
            'payment': PaymentSerializer(pay).data,
            'candidates': MatchCandidateSerializer(cands, many=True).data,
            'existing_allocations': AllocationSerializer(pay.allocations.all(), many=True).data,
        })
    return Response({'detail': 'pass ?invoice=<id> or ?payment=<id>'}, status=400)


# ── 4. per-party حصر ledger (lightweight; full reconstruction = Phase F) ──────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def party_ledger(request, personcode):
    try:
        party = ReconParty.objects.get(softech_personcode=personcode)
    except ReconParty.DoesNotExist:
        return Response({'detail': 'party not found'}, status=404)

    from . import recon_balances
    invoices = party.invoices.all()
    payments = party.payments.all()
    allocations = Allocation.objects.filter(payment__party=party)

    return Response({
        'party': ReconPartySerializer(party).data,
        'equation': recon_balances.reconciliation_equation(party),
        'counts': {
            'invoices': invoices.count(),
            'payments': payments.count(),
            'allocations': allocations.count(),
            'unallocated_payments': payments.filter(is_unallocated=True).count(),
        },
        'linked_value': _sum(allocations, 'amount'),
        'unlinked_payment_value': _sum(payments.filter(is_unallocated=True), 'amount'),
        'open_exceptions': ReconExceptionSerializer(
            party.exceptions.filter(status='open'), many=True).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def party_timeline(request, personcode):
    """حصر chronological ledger: signed events + running owed balance + equation."""
    from . import recon_balances
    try:
        party = ReconParty.objects.get(softech_personcode=personcode)
    except ReconParty.DoesNotExist:
        return Response({'detail': 'party not found'}, status=404)
    data = recon_balances.build_ledger_timeline(party)
    data['party'] = ReconPartySerializer(party).data
    return Response(data)


# ── 5. approval ACTIONS (Phase E) — mirror mutations only, NO SOFTECH write ────

def _guard_write(request):
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'صلاحية غير كافية لاعتماد التسويات'}, status=403)
    return None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_candidate_view(request, pk):
    denied = _guard_write(request)
    if denied:
        return denied
    try:
        cand = MatchCandidate.objects.get(pk=pk)
    except MatchCandidate.DoesNotExist:
        return Response({'detail': 'candidate not found'}, status=404)
    try:
        alloc = recon_actions.approve_candidate(
            cand, amount=request.data.get('amount'), user=_staff(request))
    except recon_actions.ReconActionError as e:
        return Response({'detail': str(e)}, status=400)
    cand.refresh_from_db()   # action reloads its own row under select_for_update
    return Response({'allocation': AllocationSerializer(alloc).data,
                     'candidate': MatchCandidateSerializer(cand).data}, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_candidate_view(request, pk):
    denied = _guard_write(request)
    if denied:
        return denied
    try:
        cand = MatchCandidate.objects.get(pk=pk)
    except MatchCandidate.DoesNotExist:
        return Response({'detail': 'candidate not found'}, status=404)
    try:
        cand = recon_actions.reject_candidate(
            cand, note=request.data.get('note', ''), user=_staff(request))
    except recon_actions.ReconActionError as e:
        return Response({'detail': str(e)}, status=400)
    return Response(MatchCandidateSerializer(cand).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_approve_view(request):
    """
    Approve every PROPOSED candidate in a confidence class at once (default: all
    HIGH), creating the mirror allocations — NO SOFTECH write. Bounded per call
    (`limit`, default 2000, highest-confidence first); the response's `remaining`
    tells the client whether to call again to drain the rest.
    """
    denied = _guard_write(request)
    if denied:
        return denied
    conf = request.data.get('confidence_class', '' if request.data.get('group') else 'high')
    if conf == '' and not (request.data.get('group') or request.data.get('strategy')):
        return Response({'detail': 'حدد مستوى الثقة أو المجموعة'}, status=400)
    if conf not in ('', 'high', 'medium', 'low'):
        return Response({'detail': 'confidence_class غير صالح'}, status=400)
    try:
        limit = int(request.data.get('limit', 2000))
    except (TypeError, ValueError):
        limit = 2000
    limit = max(1, min(limit, 5000))
    res = recon_actions.bulk_approve(
        party_type=request.data.get('party_type') or None,
        personcode=request.data.get('personcode') or None,
        confidence_class=conf, user=_staff(request), limit=limit,
        strategy=request.data.get('strategy') or None,
        group_key=request.data.get('group') or None,
        f=_body_filters(request),
    )
    return Response(res, status=200)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_reject_view(request):
    """Reject a whole review group (or a strategy/confidence slice) at once."""
    denied = _guard_write(request)
    if denied:
        return denied
    try:
        res = recon_actions.bulk_reject(
            user=_staff(request), note=request.data.get('note', ''),
            party_type=request.data.get('party_type') or None,
            personcode=request.data.get('personcode') or None,
            confidence_class=request.data.get('confidence_class') or None,
            strategy=request.data.get('strategy') or None,
            group_key=request.data.get('group') or None,
            f=_body_filters(request))
    except recon_actions.ReconActionError as e:
        return Response({'detail': str(e)}, status=400)
    return Response(res)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def candidate_groups_view(request):
    """Grouped review: every candidate under its invoice (?by=invoice) or voucher
    (?by=payment), with capacity/excess, existing links and duplicate flags.
    ?only=multi|over|all · ?gorder=-excess|-n|-pending|date|-date|value|-value."""
    from . import recon_groups as G
    from .recon_serializers import APInvoiceSerializer, PaymentSerializer
    qs = _candidate_qs(request)
    p = request.query_params
    try:
        page = max(1, int(p.get('page', 1)))
        size = max(1, min(int(p.get('page_size', 20)), 100))
    except ValueError:
        page, size = 1, 20
    built = G.build_groups(qs, by=p.get('by', 'invoice'), only=p.get('only', 'multi'),
                           order=p.get('gorder', '-excess'), page=page, page_size=size)
    payload = G.group_payload(
        built, qs,
        serialize_candidate=lambda c: MatchCandidateSerializer(c).data,
        serialize_invoice=lambda o: APInvoiceSerializer(o).data,
        serialize_payment=lambda o: PaymentSerializer(o).data)
    from . import recon_rivals
    recon_rivals.annotate([c for g in payload['results'] for c in g['candidates']])
    return Response(payload)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def selection_action_view(request):
    """Apply one action to the rows ticked in the grid / a group.
    approve | reject | review → mirror only (admin/pharmacist);
    reverse → undo OUR SOFTECH writes for the ticked written rows (admin, gated).
    `reject_ids` with approve = «approve these, dismiss the rest of the group»."""
    action = request.data.get('action')
    ids = request.data.get('ids') or []
    note = request.data.get('note', '')
    if not isinstance(ids, list) or not ids:
        return Response({'detail': 'لم يتم تحديد أي صف'}, status=400)
    if action == 'reverse':
        return _reverse_selection(request, ids, note)
    denied = _guard_write(request)
    if denied:
        return denied
    try:
        res = recon_actions.selection_action(ids, action, user=_staff(request), note=note)
        rej = request.data.get('reject_ids') or []
        if action == 'approve' and rej:
            r2 = recon_actions.selection_action(rej, 'reject', user=_staff(request),
                                                note=note or 'استُبعد لصالح سند آخر في نفس المجموعة')
            res['rejected'] = r2['done']
            for k, v in r2['errors'].items():
                res['errors'][k] = res['errors'].get(k, 0) + v
    except (recon_actions.ReconActionError, ValueError, TypeError) as e:
        return Response({'detail': str(e)}, status=400)
    return Response(res)


def _reverse_selection(request, ids, note):
    from . import recon_writer as W
    if not _is_admin(request.user):
        return Response({'detail': 'صلاحية غير كافية للكتابة في SOFTECH'}, status=403)
    if not W.writer_enabled():
        return Response({'detail': 'الكتابة في SOFTECH معطّلة (AP_RECONCILE_WRITER_ENABLED)'}, status=400)
    allocs = list(Allocation.objects.filter(
        candidate_id__in=[int(i) for i in ids][:200], origin=Allocation.ORIGIN_WRITTEN)
        .select_related('payment', 'invoice', 'invoice__party', 'candidate'))
    from config.sybase import get_sybase_connection
    try:
        conn = get_sybase_connection()
    except Exception as e:
        return Response({'detail': f'تعذّر الاتصال بـ SOFTECH الرئيسي: {public_error(request, e)}'}, status=503)
    done, errors = 0, {}
    try:
        for a in allocs:
            try:
                W.reverse_allocation(a, user=_staff(request), conn=conn,
                                     note=note or 'عكس بعد المراجعة (تحديد متعدد)')
                done += 1
            except W.ReconWriteIntegrityError as e:
                return Response({'detail': f'توقف للحفاظ على سلامة البيانات: {e}', 'done': done}, status=409)
            except W.ReconWriteError as e:
                k = str(e).split('(')[0].strip()[:80]
                errors[k] = errors.get(k, 0) + 1
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return Response({'done': done, 'failed': sum(errors.values()), 'errors': errors,
                     'not_written': len(ids) - len(allocs)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def manual_allocate_view(request):
    denied = _guard_write(request)
    if denied:
        return denied
    try:
        payment = Payment.objects.get(pk=request.data.get('payment'))
        invoice = APInvoice.objects.get(pk=request.data.get('invoice'))
    except (Payment.DoesNotExist, APInvoice.DoesNotExist, ValueError, TypeError):
        return Response({'detail': 'payment/invoice not found'}, status=404)
    try:
        alloc = recon_actions.manual_allocate(
            payment, invoice, request.data.get('amount'), user=_staff(request))
    except recon_actions.ReconActionError as e:
        return Response({'detail': str(e)}, status=400)
    return Response(AllocationSerializer(alloc).data, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def undo_allocation_view(request, pk):
    denied = _guard_write(request)
    if denied:
        return denied
    try:
        alloc = Allocation.objects.get(pk=pk)
    except Allocation.DoesNotExist:
        return Response({'detail': 'allocation not found'}, status=404)
    try:
        recon_actions.undo_allocation(alloc, user=_staff(request))
    except recon_actions.ReconActionError as e:
        return Response({'detail': str(e)}, status=400)
    return Response(status=204)


def _staff(request):
    return getattr(request.user, 'staff_profile', None)


def _is_admin(user) -> bool:
    """SOFTECH write-back is the most restricted action — admin/superuser only."""
    try:
        return user.is_superuser or user.staff_profile.role == 'admin'
    except Exception:
        return bool(getattr(user, 'is_superuser', False))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def write_allocation_softech(request, pk):
    """
    GATED write-back of one approved Allocation to SOFTECH (records the missing
    chequestrans link + syncs stktransm). Returns a DRY-RUN plan unless
    AP_RECONCILE_WRITER_ENABLED is on — the button is safe to use now.
    """
    from . import recon_writer
    if not _is_admin(request.user):
        return Response({'detail': 'صلاحية غير كافية للكتابة في SOFTECH'}, status=403)
    try:
        alloc = Allocation.objects.select_related('payment', 'invoice').get(pk=pk)
    except Allocation.DoesNotExist:
        return Response({'detail': 'allocation not found'}, status=404)
    try:
        res = recon_writer.push_allocation(alloc, dry_run=False, user=_staff(request))
    except recon_writer.ReconWriteError as e:
        return Response({'detail': str(e)}, status=400)
    if res.get('written') and not res.get('already_present'):
        from config.sybase import get_sybase_connection
        try:                                        # the date-order re-chain after the write
            conn = get_sybase_connection()
            try:
                res['rechain'] = recon_writer.rechain_after_write({alloc.invoice_id}, conn=conn,
                                                                   user=_staff(request))
            finally:
                conn.close()
        except Exception as e:                      # the write stands; re-chain retried later
            res['rechain'] = {'errors': {str(e)[:80]: 1}}
    return Response(res)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reverse_allocation_softech(request, pk):
    """Undo an allocation WE wrote to SOFTECH, then reject its candidate (admin, gated)."""
    from . import recon_writer
    if not _is_admin(request.user):
        return Response({'detail': 'صلاحية غير كافية للكتابة في SOFTECH'}, status=403)
    try:
        alloc = Allocation.objects.select_related('payment', 'invoice', 'invoice__party').get(pk=pk)
    except Allocation.DoesNotExist:
        return Response({'detail': 'allocation not found'}, status=404)
    try:
        res = recon_writer.reverse_allocation(alloc, user=_staff(request),
                                              note=request.data.get('note', ''))
    except recon_writer.ReconWriteError as e:
        return Response({'detail': str(e)}, status=400)
    return Response(res)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unpaid_export(request):
    from . import recon_reports as R
    from django.http import HttpResponse
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'صلاحية غير كافية'}, status=403)
    from . import recon_filters as RF
    data = R.build_unpaid_xlsx(request.query_params.get('party_type', 'supplier'),
                               f=RF.parse(request.query_params, 'supplier'))
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="unpaid_supplier_invoices.xlsx"'
    return resp


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def review_export(request):
    from . import recon_reports as R
    from django.http import HttpResponse
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'صلاحية غير كافية'}, status=403)
    from . import recon_filters as RF
    data = R.build_review_xlsx(request.query_params.get('party_type', 'supplier'),
                               f=RF.parse(request.query_params, 'supplier'))
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="reconciliation_review.xlsx"'
    return resp


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_write_softech(request):
    """Write APPROVED allocations to SOFTECH in bounded batches over one connection
    (admin only; the page loops on `remaining`). Validation failures are skipped
    and counted; an integrity failure stops the batch (409)."""
    from collections import Counter
    from . import recon_writer as W
    if not _is_admin(request.user):
        return Response({'detail': 'صلاحية غير كافية للكتابة في SOFTECH'}, status=403)
    if not W.writer_enabled():
        return Response({'detail': 'الكتابة في SOFTECH معطّلة (AP_RECONCILE_WRITER_ENABLED)'}, status=400)
    try:
        limit = max(1, min(int(request.data.get('limit', 200)), 300))
    except (TypeError, ValueError):
        limit = 200
    qs = (Allocation.objects.filter(origin=Allocation.ORIGIN_APPROVED)
          .select_related('payment', 'invoice', 'invoice__party', 'candidate')
          .order_by('payment__voucher_date', 'payment_id'))
    for param, field in (('confidence_class', 'candidate__confidence_class'),
                         ('strategy', 'candidate__strategy'),
                         ('group', 'candidate__group_key'),
                         ('personcode', 'invoice__party__softech_personcode')):
        val = request.data.get(param)
        if val:
            qs = qs.filter(**{field: val})
    qs = _apply_body_filters(qs, request, 'allocation')
    cand_ids = [int(x) for x in (request.data.get('candidate_ids') or []) if str(x).isdigit()]
    if cand_ids:                                   # only the rows ticked in the grid
        qs = qs.filter(candidate_id__in=cand_ids)
    skip_ids = [int(x) for x in (request.data.get('skip_ids') or []) if str(x).isdigit()]
    if skip_ids:                                   # rows already skipped this session
        qs = qs.exclude(id__in=skip_ids)
    total = qs.count()
    batch = list(qs[:limit])
    from config.sybase import get_sybase_connection
    try:
        conn = get_sybase_connection()
    except Exception as e:
        return Response({'detail': f'تعذّر الاتصال بـ SOFTECH الرئيسي: {public_error(request, e)}'}, status=503)
    stats, reasons, skipped = Counter(), Counter(), []
    written_value = Decimal('0')
    touched = set()
    rechain = {}
    try:
        for alloc in batch:
            try:
                res = W.push_allocation(alloc, dry_run=False, user=_staff(request), conn=conn)
            except W.ReconWriteIntegrityError as e:
                return Response({'detail': f'توقف للحفاظ على سلامة البيانات: {e}',
                                 **stats, 'reasons': dict(reasons)}, status=409)
            except W.ReconWriteError as e:
                stats['skipped'] += 1
                skipped.append(alloc.id)
                reasons[str(e).split('(')[0].strip()[:70]] += 1
                continue
            if res.get('already_present'):
                stats['already_present'] += 1
            else:
                stats['written'] += 1
                written_value += alloc.amount
                touched.add(alloc.invoice_id)
        # every write round ends with the date-order re-chain of «مبلغ مستحق»
        rechain = W.rechain_after_write(touched, conn=conn, user=_staff(request))
    finally:
        try:
            conn.close()
        except Exception:
            pass
    done = stats['written'] + stats['already_present'] + stats['skipped']
    return Response({'written': stats['written'], 'already_present': stats['already_present'],
                     'skipped': stats['skipped'], 'skipped_ids': skipped,
                     'written_value': str(written_value), 'reasons': dict(reasons),
                     'rechained': rechain.get('invoices', 0), 'now_closed': rechain.get('now_closed', 0),
                     'remaining': max(0, total - done)})


def _sort_rows(rows, ordering, allowed) -> bool:
    """Grid column sort for report rows (lists of dicts): ?ordering=-doc_value.
    Blank values sort last either way. Returns False when no valid ordering given."""
    if not ordering or ordering.lstrip('-') not in allowed:
        return False
    field, rev = ordering.lstrip('-'), ordering.startswith('-')
    present = [r for r in rows if r.get(field) not in (None, '')]
    blank = [r for r in rows if r.get(field) in (None, '')]
    present.sort(key=lambda r: r[field], reverse=rev)
    rows[:] = present + blank
    return True


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unpaid_report(request):
    """Totals + supplier summary + unpaid invoice rows for the finance department."""
    from . import recon_reports as R
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'صلاحية غير كافية'}, status=403)
    pt = request.query_params.get('party_type', 'supplier')
    from . import recon_filters as RF
    f = RF.parse(request.query_params, 'supplier')
    rows = R.unpaid_invoices(pt, f=f)
    summary = R.supplier_summary(rows, pt, f=f)
    status_f = request.query_params.get('status', 'uncovered')
    if status_f == 'uncovered':
        rows = [r for r in rows if r['unpaid_uncovered'] > R.TOL]
    elif status_f == 'review':
        rows = [r for r in rows if r['under_review'] > R.TOL]
    totals = {k: sum((x[k] for x in summary), Decimal('0'))
              for k in ('open_in_softech', 'matched', 'under_review', 'unpaid_uncovered',
                        'open_returns', 'net_payable')}
    totals.update(suppliers=len(summary), invoices=sum(x['invoices'] for x in summary),
                  unpaid_invoices=sum(x['unpaid_invoices'] for x in summary))
    try:
        cap = max(1, min(int(request.query_params.get('limit', 300)), 3000))
    except ValueError:
        cap = 300
    if not _sort_rows(rows, request.query_params.get('ordering'),
                      ('docdate', 'entered_at', 'doc_value', 'paid_in_softech', 'unpaid_uncovered',
                       'under_review', 'remaining_calc', 'supplier', 'docnumber', 'branchcode')):
        rows.sort(key=lambda r: r['unpaid_uncovered'] + r['under_review'], reverse=True)
    return Response({'totals': totals, 'suppliers': summary[:200],
                     'rows': rows[:cap], 'row_count': len(rows)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def partial_report(request):
    """Invoices paid part-way (with the vouchers that paid them) + part-used vouchers."""
    from . import recon_reports as R
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'صلاحية غير كافية'}, status=403)
    from . import recon_filters as RF
    inv_rows, pay_rows = R.partial_payments(request.query_params.get('party_type', 'supplier'),
                                            f=RF.parse(request.query_params, 'supplier'))
    if not _sort_rows(inv_rows, request.query_params.get('inv_ordering'),
                      ('docdate', 'entered_at', 'doc_value', 'paid', 'remaining', 'supplier')):
        inv_rows.sort(key=lambda r: r['remaining'], reverse=True)
    if not _sort_rows(pay_rows, request.query_params.get('pay_ordering'),
                      ('voucher_date', 'entered_at', 'amount', 'allocated', 'unallocated', 'supplier')):
        pay_rows.sort(key=lambda r: r['unallocated'], reverse=True)
    return Response({
        'totals': {'invoices': len(inv_rows),
                   'invoices_paid': sum((r['paid'] for r in inv_rows), Decimal('0')),
                   'invoices_remaining': sum((r['remaining'] for r in inv_rows), Decimal('0')),
                   'vouchers': len(pay_rows),
                   'vouchers_unallocated': sum((r['unallocated'] for r in pay_rows), Decimal('0'))},
        'invoices': inv_rows[:300], 'vouchers': pay_rows[:200]})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def partial_export(request):
    from . import recon_reports as R
    from django.http import HttpResponse
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'صلاحية غير كافية'}, status=403)
    from . import recon_filters as RF
    data = R.build_partial_xlsx(request.query_params.get('party_type', 'supplier'),
                                f=RF.parse(request.query_params, 'supplier'))
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="partial_payments.xlsx"'
    return resp


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def returns_chains_export(request):
    """Open returns owed by suppliers, purchases paid although returned, and the
    مدفوعات → مقبوضات → مدفوعات correction chains (doc 23 §17)."""
    from . import recon_reports as R
    from django.http import HttpResponse
    if not _is_admin_or_pharmacist(request.user):
        return Response({'detail': 'صلاحية غير كافية'}, status=403)
    from . import recon_filters as RF
    data = R.build_returns_chains_xlsx(request.query_params.get('party_type', 'supplier'),
                                       f=RF.parse(request.query_params, 'supplier'))
    resp = HttpResponse(data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = 'attachment; filename="returns_and_correction_chains.xlsx"'
    return resp



def _body_filters(request):
    """Filters sent with a bulk POST (same keys as the GET filters)."""
    from . import recon_filters as RF
    f = RF.parse(request.data)
    return f if (f.personcodes or f.any_doc_filter) else None


def _apply_body_filters(qs, request, kind):
    from . import recon_filters as RF
    f = _body_filters(request)
    return RF.apply(qs, f, kind) if f else qs


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def supplier_options(request):
    """Every party of a type (code + name + SOFTECH balance) for the multi-select."""
    pt = request.query_params.get('party_type', 'supplier')
    rows = (ReconParty.objects.filter(party_type=pt).order_by('name')
            .values('softech_personcode', 'name', 'softech_balance'))
    return Response([{'code': r['softech_personcode'], 'name': r['name'] or '',
                      'balance': r['softech_balance']} for r in rows])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def invoice_lines_view(request, pk):
    """Item lines of one invoice/return — live from SOFTECH, only on demand."""
    from . import recon_lines
    try:
        inv = APInvoice.objects.get(pk=pk)
    except APInvoice.DoesNotExist:
        return Response({'detail': 'invoice not found'}, status=404)
    try:
        return Response(recon_lines.invoice_lines(inv))
    except Exception as e:
        return Response({'detail': f'تعذّر قراءة الأصناف من SOFTECH: {public_error(request, e)}'}, status=503)
