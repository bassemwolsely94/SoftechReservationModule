"""apps/insurance/views.py"""
import logging
from datetime import date, datetime

from django.utils import timezone
from django.db.models import Q, Count
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from .permissions import InsuranceModuleAccess
from rest_framework.response import Response

from .models import (
    InsuranceClient, InsuranceSubClient, InsuranceContract,
    InsuranceClaim, InsuranceClaimPrescription,
    InsuranceClaimAdjustment, InsuranceClaimManualRx,
    InsuranceClaimExclusion, InsuranceClaimSupplement,
    InsurancePayment, InsuranceDeduction,
)
from .serializers import (
    InsuranceClientSerializer, InsuranceClientListSerializer,
    InsuranceSubClientSerializer, InsuranceContractSerializer,
    InsuranceClaimListSerializer, InsuranceClaimDetailSerializer,
    InsuranceClaimSupplementSerializer, InsuranceClaimManualRxSerializer,
    InsuranceClaimAdjustmentSerializer, InsuranceClaimExclusionSerializer,
    InsurancePaymentSerializer, InsuranceDeductionSerializer,
    ImportClaimSerializer, AdjustPrescriptionSerializer,
    AddManualRxSerializer, ClaimStatusSerializer,
)
from .importer import (
    import_claim_from_softech, import_claim_by_motalbano,
    fetch_single_rx_from_softech,
    recalculate_claim_final_totals, InsuranceImportError,
)
from .audit import record_audit
from apps.catalog.wildcard import wq
from core.errors import public_error

logger = logging.getLogger('elrezeiky.insurance')


def _next_claim_number() -> str:
    """Generate next claim number: MT-YYYY-NNNNN"""
    year  = date.today().year
    prefix = f'MT-{year}-'
    last = (
        InsuranceClaim.objects
        .filter(claim_number__startswith=prefix)
        .order_by('-claim_number')
        .values_list('claim_number', flat=True)
        .first()
    )
    if last:
        try:
            n = int(last.split('-')[-1]) + 1
        except ValueError:
            n = 1
    else:
        n = 1
    return f'{prefix}{n:05d}'


class InsuranceClientViewSet(viewsets.ModelViewSet):
    permission_classes = [InsuranceModuleAccess]
    queryset = InsuranceClient.objects.prefetch_related('subclients__contracts').order_by('name')

    def get_serializer_class(self):
        if self.action == 'list':
            return InsuranceClientListSerializer
        return InsuranceClientSerializer

    @action(detail=False, methods=['get'], url_path='persons-from-softech')
    def persons_from_softech(self, request):
        """List all insurance/contract persons from Softech personsdata."""
        from .sybase_queries import QUERY_INSURANCE_PERSONS
        try:
            from config.sybase import get_sybase_connection
            conn   = get_sybase_connection()
            cursor = conn.cursor()
            cursor.execute(QUERY_INSURANCE_PERSONS)
            rows   = cursor.fetchall()
            data   = [
                {'personcode': r[0], 'name': r[1], 'ptcode': r[2], 'ptclassifcode': r[3]}
                for r in rows
            ]
            return Response(data)
        except Exception as e:
            return Response({'error': public_error(request, e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class InsuranceSubClientViewSet(viewsets.ModelViewSet):
    permission_classes = [InsuranceModuleAccess]
    serializer_class   = InsuranceSubClientSerializer
    queryset = InsuranceSubClient.objects.select_related('client').prefetch_related('contracts')

    def get_queryset(self):
        qs = super().get_queryset()
        client_id = self.request.query_params.get('client_id')
        if client_id:
            qs = qs.filter(client_id=client_id)
        return qs


class InsuranceContractViewSet(viewsets.ModelViewSet):
    permission_classes = [InsuranceModuleAccess]
    serializer_class   = InsuranceContractSerializer
    queryset = InsuranceContract.objects.select_related('subclient__client').order_by('-effective_from')

    def get_queryset(self):
        qs = super().get_queryset()
        subclient_id = self.request.query_params.get('subclient_id')
        if subclient_id:
            qs = qs.filter(subclient_id=subclient_id)
        return qs


class InsuranceClaimViewSet(viewsets.ModelViewSet):
    permission_classes = [InsuranceModuleAccess]
    queryset = InsuranceClaim.objects.select_related(
        'subclient__client', 'contract', 'created_by', 'imported_by'
    ).prefetch_related(
        'payments', 'deductions',
        # For detail view: prefetch prescriptions with adjustment + exclusion but NOT lines
        'prescriptions__adjustment',
        'prescriptions__exclusion',
        'supplements', 'manual_rx',
    ).order_by('-period_from', '-claim_number')

    def get_serializer_class(self):
        if self.action in ('retrieve',):
            return InsuranceClaimDetailSerializer
        return InsuranceClaimListSerializer

    @staticmethod
    def _locked_response(claim):
        """Return a 423 response if the claim is locked, else None."""
        if claim.is_locked:
            return Response(
                {'error': 'المطالبة مُقدَّمة ومقفلة — لا يمكن تعديل محتواها. '
                          'أي إضافة لاحقة تتم عبر ملحق (Supplement).',
                 'locked': True, 'status': claim.status},
                status=status.HTTP_423_LOCKED,
            )
        return None

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # Include item lines only when explicitly requested (?include_lines=1)
        ctx['include_lines'] = self.request.query_params.get('include_lines') == '1'
        return ctx

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        client_id    = params.get('client_id')
        subclient_id = params.get('subclient_id')
        status_val   = params.get('status')
        year         = params.get('year')

        if client_id:
            qs = qs.filter(subclient__client_id=client_id)
        if subclient_id:
            qs = qs.filter(subclient_id=subclient_id)
        if status_val:
            qs = qs.filter(status=status_val)
        if year:
            qs = qs.filter(period_from__year=year)

        return qs

    # ── Create claim (without import) ─────────────────────────────────────────
    def create(self, request, *args, **kwargs):
        subclient_id = request.data.get('subclient')
        if not subclient_id:
            return Response({'error': 'subclient مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            subclient = InsuranceSubClient.objects.get(pk=subclient_id)
        except InsuranceSubClient.DoesNotExist:
            return Response({'error': 'الفئة غير موجودة'}, status=status.HTTP_400_BAD_REQUEST)

        contract = None
        local_disc = imported_disc = tarsia_disc = 0
        contract_id = request.data.get('contract')
        if contract_id:
            try:
                contract = InsuranceContract.objects.get(pk=contract_id)
                local_disc    = contract.local_discount_pct
                imported_disc = contract.imported_discount_pct
                tarsia_disc   = contract.tarsia_discount_pct
            except InsuranceContract.DoesNotExist:
                pass

        staff = getattr(request.user, 'staff_profile', None)
        claim = InsuranceClaim.objects.create(
            claim_number              = _next_claim_number(),
            subclient                 = subclient,
            contract                  = contract,
            period_from               = request.data.get('period_from'),
            period_to                 = request.data.get('period_to'),
            softech_motalba_no        = request.data.get('softech_motalba_no', ''),
            applied_local_disc_pct    = local_disc,
            applied_imported_disc_pct = imported_disc,
            applied_tarsia_disc_pct   = tarsia_disc,
            notes                     = request.data.get('notes', ''),
            status                    = InsuranceClaim.STATUS_DRAFT,
            created_by                = staff,
        )
        return Response(InsuranceClaimDetailSerializer(claim, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)

    # ── Import prescriptions from Softech ─────────────────────────────────────
    @action(detail=True, methods=['get'], url_path='resync/preview')
    def resync_preview(self, request, pk=None):
        """Read-only diff of SOFTECH's current motalba vs this claim (new/removed/changed)."""
        claim = self.get_object()
        from .resync import preview_resync
        from .importer import InsuranceImportError
        try:
            return Response(preview_resync(claim, motalba_no=request.query_params.get('motalba_no')))
        except InsuranceImportError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'تعذّرت المزامنة: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['post'], url_path='resync/apply')
    def resync_apply(self, request, pk=None):
        """Apply the SOFTECH delta surgically. Body: {confirm, approved_change_ids:[rx_id]}."""
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        from .resync import apply_resync
        from .importer import InsuranceImportError
        try:
            res = apply_resync(
                claim,
                approved_change_ids=request.data.get('approved_change_ids') or [],
                confirm=bool(request.data.get('confirm')),
                user=request.user,
                motalba_no=request.data.get('motalba_no'),
            )
        except InsuranceImportError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(claim, 'resync', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'مزامنة تعديلات سوفتك: +{res["added"]} جديدة · '
                             f'{res["removed"]} محذوفة (استثناء) · {res["changed"]} مُعاد تجميدها')
        return Response(res)

    @action(detail=True, methods=['get'], url_path='resync/runs')
    def resync_runs(self, request, pk=None):
        """History of re-sync runs on this claim (for revert)."""
        claim = self.get_object()
        from .models import ResyncRun
        return Response([{
            'id': r.pk, 'status': r.status, 'added': r.added, 'removed': r.removed,
            'changed': r.changed, 'applied_at': r.applied_at.isoformat(),
            'reverted_at': r.reverted_at.isoformat() if r.reverted_at else None,
        } for r in ResyncRun.objects.filter(claim=claim)])

    @action(detail=True, methods=['post'], url_path='resync/runs/(?P<run_id>[0-9]+)/revert')
    def resync_revert(self, request, pk=None, run_id=None):
        """Undo a re-sync run (delete added, drop our exclusions, restore re-frozen)."""
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        from .models import ResyncRun
        from .resync import revert_resync
        from .importer import InsuranceImportError
        try:
            run = ResyncRun.objects.get(pk=run_id, claim=claim)
            res = revert_resync(run, user=request.user)
        except ResyncRun.DoesNotExist:
            return Response({'error': 'العملية غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        except InsuranceImportError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(claim, 'resync_revert', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'تراجع عن مزامنة سوفتك (عملية #{run_id})')
        return Response(res)

    @action(detail=True, methods=['post'], url_path='import-from-softech')
    def import_from_softech(self, request, pk=None):
        claim = self.get_object()

        if claim.status not in (InsuranceClaim.STATUS_DRAFT, InsuranceClaim.STATUS_READY):
            return Response(
                {'error': 'لا يمكن إعادة الاستيراد بعد تقديم المطالبة'},
                status=status.HTTP_400_BAD_REQUEST
            )

        ser = ImportClaimSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Resolve subclient → personcode list
        try:
            subclient = InsuranceSubClient.objects.get(pk=data['subclient_id'])
        except InsuranceSubClient.DoesNotExist:
            return Response({'error': 'الفئة غير موجودة'}, status=status.HTTP_400_BAD_REQUEST)

        personcodes = subclient.get_all_personcodes()
        if not personcodes:
            return Response(
                {'error': 'لا يوجد كود عميل في سوفتك لهذه الفئة'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update claim meta before import
        claim.subclient    = subclient
        claim.period_from  = data['period_from']
        claim.period_to    = data['period_to']
        claim.softech_motalba_no    = data.get('softech_motalba_no', '')
        claim.imported_personcodes  = ','.join(personcodes)
        claim.imported_branches     = ','.join(data.get('branchcodes', []))
        if data.get('contract_id'):
            try:
                contract = InsuranceContract.objects.get(pk=data['contract_id'])
                claim.contract = contract
                claim.applied_local_disc_pct    = contract.local_discount_pct
                claim.applied_imported_disc_pct = contract.imported_discount_pct
                claim.applied_tarsia_disc_pct   = contract.tarsia_discount_pct
            except InsuranceContract.DoesNotExist:
                pass
        claim.save()

        staff = getattr(request.user, 'staff_profile', None)

        try:
            summary = import_claim_from_softech(
                claim       = claim,
                personcodes = personcodes,
                period_from = data['period_from'],
                period_to   = data['period_to'],
                branchcodes = data.get('branchcodes') or None,
                user        = staff,
            )
        except InsuranceImportError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception('Insurance import failed for claim %s', claim.claim_number)
            return Response({'error': f'خطأ غير متوقع: {public_error(request, e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'message': 'تم الاستيراد بنجاح',
            'summary': summary,
            'claim':   InsuranceClaimListSerializer(claim, context={'request': request}).data,
        })

    # ── Quick-import: create claim + import in one call ───────────────────────
    @action(detail=False, methods=['post'], url_path='create-and-import')
    def create_and_import(self, request):
        ser = ImportClaimSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            subclient = InsuranceSubClient.objects.get(pk=data['subclient_id'])
        except InsuranceSubClient.DoesNotExist:
            return Response({'error': 'الفئة غير موجودة'}, status=status.HTTP_400_BAD_REQUEST)

        personcodes = subclient.get_all_personcodes()
        if not personcodes:
            return Response({'error': 'لا يوجد كود عميل في سوفتك'}, status=status.HTTP_400_BAD_REQUEST)

        local_disc = imported_disc = tarsia_disc = 0
        contract = None
        if data.get('contract_id'):
            try:
                contract = InsuranceContract.objects.get(pk=data['contract_id'])
                local_disc    = contract.local_discount_pct
                imported_disc = contract.imported_discount_pct
                tarsia_disc   = contract.tarsia_discount_pct
            except InsuranceContract.DoesNotExist:
                pass

        staff = getattr(request.user, 'staff_profile', None)
        motalbano_str = data.get('softech_motalba_no', '').strip()
        motalbano_int = None
        if motalbano_str:
            try:
                motalbano_int = int(motalbano_str)
            except ValueError:
                pass

        claim = InsuranceClaim.objects.create(
            claim_number              = _next_claim_number(),
            subclient                 = subclient,
            contract                  = contract,
            period_from               = data['period_from'],
            period_to                 = data['period_to'],
            softech_motalba_no        = motalbano_str,
            imported_personcodes      = ','.join(personcodes),
            imported_branches         = ','.join(data.get('branchcodes', [])),
            applied_local_disc_pct    = local_disc,
            applied_imported_disc_pct = imported_disc,
            applied_tarsia_disc_pct   = tarsia_disc,
            notes                     = data.get('notes', ''),
            status                    = InsuranceClaim.STATUS_DRAFT,
            created_by                = staff,
        )

        try:
            # PATH A: import by motalbano (preferred — uses motalba table directly)
            if motalbano_int:
                summary = import_claim_by_motalbano(
                    claim=claim, motalbano=motalbano_int, user=staff,
                )
            else:
                # PATH B: import by personcode + date range
                summary = import_claim_from_softech(
                    claim=claim, personcodes=personcodes,
                    period_from=data['period_from'], period_to=data['period_to'],
                    branchcodes=data.get('branchcodes') or None, user=staff,
                )
        except InsuranceImportError as e:
            claim.delete()
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            claim.delete()
            logger.exception('Insurance import failed')
            return Response({'error': f'خطأ غير متوقع: {public_error(request, e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({
            'message': 'تم إنشاء المطالبة والاستيراد بنجاح',
            'summary': summary,
            'claim':   InsuranceClaimDetailSerializer(claim, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

    # ── Create an EMPTY (manual-only) claim — no SOFTECH motalba/personcode ────
    @action(detail=False, methods=['post'], url_path='create-manual')
    def create_manual(self, request):
        """
        Create an empty draft claim WITHOUT importing from SOFTECH — for motalbas
        that have no published SOFTECH motalba (or a subclient with no personcode).
        Prescriptions are then collected via the detailed/simple manual-add flow.

        Body: { subclient_id, period_from, period_to, contract_id?, notes? }
        """
        d = request.data
        try:
            subclient = InsuranceSubClient.objects.get(pk=d.get('subclient_id'))
        except (InsuranceSubClient.DoesNotExist, ValueError, TypeError):
            return Response({'error': 'الفئة غير موجودة'}, status=status.HTTP_400_BAD_REQUEST)
        if not d.get('period_from') or not d.get('period_to'):
            return Response({'error': 'الفترة الزمنية مطلوبة (من/إلى)'},
                            status=status.HTTP_400_BAD_REQUEST)

        local_disc = imported_disc = tarsia_disc = 0
        contract = None
        if d.get('contract_id'):
            try:
                contract = InsuranceContract.objects.get(pk=d['contract_id'])
                local_disc    = contract.local_discount_pct
                imported_disc = contract.imported_discount_pct
                tarsia_disc   = contract.tarsia_discount_pct
            except InsuranceContract.DoesNotExist:
                pass

        staff = getattr(request.user, 'staff_profile', None)
        claim = InsuranceClaim.objects.create(
            claim_number              = _next_claim_number(),
            subclient                 = subclient,
            contract                  = contract,
            period_from               = d['period_from'],
            period_to                 = d['period_to'],
            softech_motalba_no        = '',
            imported_personcodes      = ','.join(subclient.get_all_personcodes()),
            applied_local_disc_pct    = local_disc,
            applied_imported_disc_pct = imported_disc,
            applied_tarsia_disc_pct   = tarsia_disc,
            notes                     = d.get('notes', ''),
            status                    = InsuranceClaim.STATUS_DRAFT,
            created_by                = staff,
        )
        recalculate_claim_final_totals(claim)
        return Response({
            'message': 'تم إنشاء مطالبة يدوية فارغة — أضف الروشتات عبر الإضافة اليدوية.',
            'claim':   InsuranceClaimDetailSerializer(claim, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

    # ── List motalbas for a subclient from Softech ────────────────────────────
    @action(detail=False, methods=['get'], url_path='list-motalbas')
    def list_motalbas(self, request):
        """
        List all motalbas in Softech for a given subclient.
        Allows user to pick a motalbano before creating a claim.
        Query param: subclient_id
        """
        subclient_id = request.query_params.get('subclient_id')
        if not subclient_id:
            return Response({'error': 'subclient_id مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            subclient = InsuranceSubClient.objects.get(pk=subclient_id)
        except InsuranceSubClient.DoesNotExist:
            return Response({'error': 'الفئة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        personcodes = subclient.get_all_personcodes()
        if not personcodes:
            return Response({'error': 'لا يوجد كود عميل في سوفتك'}, status=status.HTTP_400_BAD_REQUEST)

        # Query the motalba DETAIL table (motalbas header is empty — confirmed 2026-06-02)
        # motalbano is shared across personcodes — each result is unique to this personcode.
        from .sybase_queries import QUERY_MOTALBAS_BY_PERSONCODE
        results = []
        try:
            from config.sybase import get_sybase_connection
            conn = get_sybase_connection()
            seen_motalbanos = set()
            for personcode in personcodes:
                cursor = conn.cursor()
                cursor.execute(QUERY_MOTALBAS_BY_PERSONCODE, [personcode])
                rows = cursor.fetchall()
                for r in rows:
                    # r: [0]=motalbano, [1]=motalbasdate, [2]=motalbafdate,
                    #    [3]=rxcount, [4]=docvaluetotal
                    motno = int(str(r[0]).split('.')[0]) if r[0] else None
                    if motno and motno not in seen_motalbanos:
                        seen_motalbanos.add(motno)
                        results.append({
                            'motalbano':    motno,
                            'motfromdate':  str(r[1])[:10] if r[1] else None,
                            'mottodate':    str(r[2])[:10] if r[2] else None,
                            'rxcount':      int(r[3] or 0),
                            'docvaluetotal': float(r[4] or 0),
                            'personcode':   personcode,
                        })
        except Exception as e:
            return Response({'error': public_error(request, e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Sort by motalbano descending
        results.sort(key=lambda x: x['motalbano'] or 0, reverse=True)
        return Response(results)

    # ── Status change ─────────────────────────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='change-status')
    def change_status(self, request, pk=None):
        claim = self.get_object()
        ser   = ClaimStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data  = ser.validated_data

        old_status = claim.status
        claim.status = data['status']
        if data.get('submitted_at'):
            claim.submitted_at = data['submitted_at']
        elif data['status'] == InsuranceClaim.STATUS_SUBMITTED and not claim.submitted_at:
            claim.submitted_at = timezone.now()
        if data.get('expected_payment_date'):
            claim.expected_payment_date = data['expected_payment_date']
        if data.get('notes'):
            claim.notes = data['notes']
        claim.save()
        labels = dict(InsuranceClaim.STATUS_CHOICES)
        record_audit(claim, 'status_change', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'الحالة: {labels.get(old_status, old_status)} → {labels.get(claim.status, claim.status)}',
                     reason=data.get('notes', ''),
                     before={'status': old_status}, after={'status': claim.status})
        return Response(InsuranceClaimListSerializer(claim, context={'request': request}).data)

    # ── Fetch item lines for one prescription (lazy drill-down) ──────────────
    @action(detail=True, methods=['get'], url_path='prescriptions/(?P<rx_id>[0-9]+)/lines')
    def prescription_lines(self, request, pk=None, rx_id=None):
        claim = self.get_object()
        try:
            rx = claim.prescriptions.get(pk=rx_id)
        except InsuranceClaimPrescription.DoesNotExist:
            return Response({'error': 'الروشتة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        from .serializers import InsuranceClaimLineSerializer
        from .discrepancy import line_variance_map
        lines = list(rx.lines.all())
        data = InsuranceClaimLineSerializer(lines, many=True).data
        # Attach per-line variance (display-only drift vs current master — never
        # affects the frozen values used in exports).
        try:
            vmap = line_variance_map(claim, lines)
        except Exception:
            vmap = {}
        for row in data:
            row['variance'] = vmap.get(row.get('id'))
        return Response(data)

    @action(detail=True, methods=['get'], url_path='patient-name-suggest')
    def patient_name_suggest(self, request, pk=None):
        """
        Autocomplete a patient's full name from historical prescriptions of the SAME
        insurer (جهة / client) across all its sub-categories.  Returns the EXACT
        stored spelling (hamza preserved) ranked by ordered-token match, frequency
        and recency — so repeated محمد/أحمد tokens don't cause false merges.
        Query: ?q=<partial name>  (min 2 chars)
        """
        claim = self.get_object()
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response([])
        from django.db.models import Count, Max
        from .name_match import rank_candidates
        from .models import InsuranceClaimManualRx
        try:
            client_id = claim.subclient.client_id
        except Exception:
            client_id = None
        if not client_id:
            return Response([])

        # Narrow FIRST with a trigram-accelerated icontains on the longest typed
        # token (the pg_trgm GIN index makes ILIKE '%tok%' fast), so we only
        # aggregate + rank a small candidate set instead of the whole insurer.
        # Fall back to the last token, then the raw string.
        toks = [t for t in q.split() if t]
        probe = max(toks, key=len) if toks else q

        def _collect(model):
            base = (model.objects
                    .filter(claim__subclient__client_id=client_id)
                    .exclude(patient_name=''))
            qs = base.filter(patient_name__icontains=probe)
            rows = list(qs.values('patient_name')
                        .annotate(count=Count('id'), last=Max('softech_docdate'))[:2000])
            # widen once if the specific probe was too tight
            if len(rows) < 3 and toks and probe != toks[-1]:
                rows = list(base.filter(patient_name__icontains=toks[-1])
                            .values('patient_name')
                            .annotate(count=Count('id'), last=Max('softech_docdate'))[:2000])
            return rows

        agg = {}
        for model in (InsuranceClaimPrescription, InsuranceClaimManualRx):
            for row in _collect(model):
                nm = row['patient_name']
                e = agg.setdefault(nm, {'name': nm, 'count': 0, 'last_date': None})
                e['count'] += row['count']
                if row['last'] and (e['last_date'] is None or row['last'] > e['last_date']):
                    e['last_date'] = row['last']

        ranked = rank_candidates(q, list(agg.values()), limit=15)

        # Classify each hit relative to what's in the field, so the dropdown can
        # badge it: 'spelling' = same name, different exact spelling; 'complete' =
        # a longer superset that adds missing name parts (only when the field
        # already holds ≥2 fully-typed tokens, else it's just mid-typing noise).
        from .name_match import normalize_ar
        qt = normalize_ar(q).split()
        def _kind(name):
            dt = normalize_ar(name).split()
            if not qt or not dt:
                return None
            if dt == qt and name != q:
                return 'spelling'
            if len(qt) >= 2 and len(dt) > len(qt) and dt[:len(qt)] == qt:
                return 'complete'
            return None

        return Response([{
            'name':  r['name'],
            'count': r['count'],
            'last':  r['last_date'].isoformat() if r['last_date'] else None,
            'kind':  _kind(r['name']),
        } for r in ranked])

    def _entity_name_rows(self, claim):
        """Distinct historical names for the claim's insurer (client), each with a
        precomputed normalized token list — the shared pool for name suggestions."""
        from django.db.models import Count, Max
        from .name_match import normalize_ar
        from .models import InsuranceClaimManualRx
        client_id = claim.subclient.client_id
        agg = {}
        for model in (InsuranceClaimPrescription, InsuranceClaimManualRx):
            for row in (model.objects.filter(claim__subclient__client_id=client_id)
                        .exclude(patient_name='')
                        .values('patient_name')
                        .annotate(count=Count('id'), last=Max('softech_docdate'))):
                nm = row['patient_name']
                e = agg.setdefault(nm, {'name': nm, 'count': 0, 'last_date': None})
                e['count'] += row['count']
                if row['last'] and (e['last_date'] is None or row['last'] > e['last_date']):
                    e['last_date'] = row['last']
        rows = list(agg.values())
        for r in rows:
            r['ntokens'] = (normalize_ar(r['name']).split() if r['name'] else [])
        return rows

    @action(detail=True, methods=['get'], url_path='name-suggestions')
    def name_suggestions(self, request, pk=None):
        """
        Review list: for each non-excluded prescription, propose a SAFE name
        improvement (more-complete / spelling-fix) drawn from the insurer's history.
        Only returns rows that have an actionable suggestion or an ambiguous set.
        """
        claim = self.get_object()
        from .name_match import suggest_name_improvement
        from .models import InsuranceClaimExclusion
        rows = self._entity_name_rows(claim)
        excluded = set(InsuranceClaimExclusion.objects.filter(prescription__claim=claim)
                       .values_list('prescription_id', flat=True))
        out = []
        for rx in claim.prescriptions.all().order_by('softech_docdate', 'sequence'):
            if rx.id in excluded:
                continue
            imp = suggest_name_improvement(rx.patient_name or '', rows)
            if not imp:
                continue
            out.append({
                'rx_id':        rx.id,
                'docnumber':    rx.softech_docnumber,
                'date':         rx.softech_docdate.isoformat() if rx.softech_docdate else None,
                'branch':       rx.softech_branchcode,
                'current_name': rx.patient_name,
                'softech_name': rx.softech_patient_name,
                'suggestion':   imp.get('suggestion'),
                'type':         imp.get('type'),
                'count':        imp.get('count'),
                'options':      imp.get('options'),
            })
        return Response({'count': len(out), 'rows': out})

    @action(detail=True, methods=['post'], url_path='name-suggestions/apply')
    def apply_name_suggestions(self, request, pk=None):
        """
        Bulk-apply chosen patient names.  Body: { choices: {rx_id: name, ...} }.
        Name-only (print field) — no totals change; each stays individually
        revertible to the Softech original.  Audited.
        """
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        choices = request.data.get('choices') or {}
        if not isinstance(choices, dict) or not choices:
            return Response({'error': 'لا توجد اختيارات'}, status=status.HTTP_400_BAD_REQUEST)
        staff = getattr(request.user, 'staff_profile', None)
        by_id = {rx.id: rx for rx in claim.prescriptions.filter(pk__in=[int(k) for k in choices])}
        applied = 0
        for k, name in choices.items():
            rx = by_id.get(int(k))
            name = (name or '').strip()
            if not rx or not name or name == (rx.patient_name or ''):
                continue
            old = rx.patient_name
            rx.patient_name = name
            rx.save(update_fields=['patient_name'])
            record_audit(claim, 'patient_edit', actor=staff,
                         summary=f'تصحيح اسم (#{rx.softech_docnumber}): «{old}» → «{name}»',
                         target_type='prescription', target_ref=str(rx.softech_docnumber),
                         before={'patient_name': old}, after={'patient_name': name})
            applied += 1
        return Response({'applied': applied})

    @action(detail=True, methods=['patch'], url_path='prescriptions/(?P<rx_id>[0-9]+)/patient')
    def update_patient(self, request, pk=None, rx_id=None):
        """Fix / edit a prescription's patient name (DOES flow into the printed export)."""
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            rx = claim.prescriptions.get(pk=rx_id)
        except InsuranceClaimPrescription.DoesNotExist:
            return Response({'error': 'الروشتة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        # revert=True restores the original Softech name captured at import.
        if request.data.get('revert'):
            name = rx.softech_patient_name or rx.patient_name
        else:
            name = request.data.get('patient_name')
            if name is None:
                return Response({'error': 'patient_name required'}, status=status.HTTP_400_BAD_REQUEST)
        old_name = rx.patient_name
        rx.patient_name = (name or '').strip()
        rx.save(update_fields=['patient_name'])   # display/print field only — no totals change
        record_audit(claim, 'patient_edit', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'تعديل اسم المريض (#{rx.softech_docnumber}): «{old_name}» → «{rx.patient_name}»',
                     target_type='prescription', target_ref=str(rx.softech_docnumber),
                     before={'patient_name': old_name}, after={'patient_name': rx.patient_name})
        return Response({'id': rx.id, 'patient_name': rx.patient_name,
                         'softech_patient_name': rx.softech_patient_name})

    @action(detail=True, methods=['patch'],
            url_path='prescriptions/(?P<rx_id>[0-9]+)/lines/(?P<line_id>[0-9]+)')
    def edit_line(self, request, pk=None, rx_id=None, line_id=None):
        """
        SURGICAL edit of one prescription line — swap the item code (with the new
        item's price/classification) and/or change quantity/price.  Recomputes the
        line, then the prescription splits (delta only), then the claim totals.
        The original line is snapshotted on first edit so it can be reset.

        Body: { item_code?, quantity?, unit_price? }
        """
        from decimal import Decimal
        from .models import InsuranceClaimLine
        from .classifier import (classify_item, load_classification_overrides,
                                 powerquery_totals_from_splits)
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            line = InsuranceClaimLine.objects.get(pk=line_id, prescription__claim=claim,
                                                  prescription_id=rx_id)
        except InsuranceClaimLine.DoesNotExist:
            return Response({'error': 'البند غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        rx = line.prescription
        _audit_before = {'item_code': line.softech_itemcode, 'item_name': line.item_name,
                         'quantity': float(line.quantity or 0), 'unit_price': float(line.unit_price or 0),
                         'net': float(line.net_amount or 0)}
        Q = Decimal('0.01')
        rates = {
            'local':    Decimal(str(claim.applied_local_disc_pct    or 0)),
            'imported': Decimal(str(claim.applied_imported_disc_pct or 0)),
            'tarsia':   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
        }

        # Snapshot original values on first edit (for reset)
        if not line.is_manually_edited:
            line.original_json = {
                'softech_itemcode': line.softech_itemcode, 'item_name': line.item_name,
                'item_category': line.item_category, 'quantity': str(line.quantity),
                'unit_price': str(line.unit_price), 'line_total': str(line.line_total),
                'discount_pct': str(line.discount_pct), 'discount_amt': str(line.discount_amt),
                'net_amount': str(line.net_amount),
            }

        old_cat   = line.item_category
        old_total = Decimal(str(line.line_total or 0))

        d = request.data
        new_code = (d.get('item_code') or '').strip()
        # 1) Item swap — resolve the new item from the catalog
        if new_code and new_code != line.softech_itemcode:
            from apps.catalog.models import Item
            item = Item.objects.filter(softech_id=new_code).only(
                'softech_id', 'name', 'is_imported', 'store_classif', 'pack_price').first()
            if not item:
                return Response({'error': f'الصنف {new_code} غير موجود في الكتالوج'},
                                status=status.HTTP_400_BAD_REQUEST)
            line.softech_itemcode = new_code
            line.item_name        = item.name
            line.unit_price       = Decimal(str(item.pack_price or 0))
            line.item_category    = classify_item(
                imported_origin='1' if item.is_imported else '0',
                store_classif=item.store_classif, item_code=new_code,
                overrides=load_classification_overrides())
            line.softech_store_classif = item.store_classif or ''
            line.softech_imported_flag = bool(item.is_imported)

        # 2) Explicit quantity / unit-price overrides
        if d.get('quantity') not in (None, ''):
            line.quantity = Decimal(str(d['quantity']))
        if d.get('unit_price') not in (None, ''):
            line.unit_price = Decimal(str(d['unit_price']))

        # 3) Recompute this line
        qty = Decimal(str(line.quantity or 0))
        new_total = (Decimal(str(line.unit_price or 0)) * qty).quantize(Q)
        new_cat   = line.item_category
        rate      = rates.get('local' if new_cat == 'local' else
                              'imported' if new_cat == 'imported' else 'tarsia', Decimal('0'))
        line.line_total   = new_total
        line.discount_pct = rate
        line.discount_amt = (new_total * rate / 100).quantize(Q)
        line.net_amount   = new_total - line.discount_amt
        line.is_manually_edited = True
        line.save()

        # 4) Surgical prescription recompute — move the delta between buckets
        _CAT = {'local': 'local_before', 'imported': 'imported_before', 'tarsia': 'tarsia_before'}
        splits = {
            'local':    Decimal(str(rx.local_before    or 0)),
            'imported': Decimal(str(rx.imported_before or 0)),
            'tarsia':   Decimal(str(rx.tarsia_before   or 0)),
        }
        splits[old_cat] -= old_total
        splits[new_cat] += new_total
        t = powerquery_totals_from_splits(splits['local'], splits['imported'], splits['tarsia'],
                                          rates['local'], rates['imported'], rates['tarsia'])
        rx.local_before    = t['local_before']
        rx.imported_before = t['imported_before']
        rx.tarsia_before   = t['tarsia_before']
        rx.gross_before    = t['gross_before']
        rx.local_discount    = t['local_discount']
        rx.imported_discount = t['imported_discount']
        rx.tarsia_discount   = t['tarsia_discount']
        rx.total_discount  = t['total_discount']
        rx.net_after       = t['net_after']
        rx.save(update_fields=[
            'local_before', 'imported_before', 'tarsia_before', 'gross_before',
            'local_discount', 'imported_discount', 'tarsia_discount',
            'total_discount', 'net_after'])

        recalculate_claim_final_totals(claim)
        if rx.billing_group_id:
            rx.billing_group.refresh_totals()

        record_audit(claim, 'line_edit', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'تعديل بند (#{rx.softech_docnumber}): {_audit_before["item_code"]} → {line.softech_itemcode} · '
                             f'صافى البند {_audit_before["net"]} → {float(line.net_amount or 0)}',
                     target_type='line', target_ref=str(line.pk),
                     before=_audit_before,
                     after={'item_code': line.softech_itemcode, 'item_name': line.item_name,
                            'quantity': float(line.quantity or 0), 'unit_price': float(line.unit_price or 0),
                            'net': float(line.net_amount or 0)})
        from .serializers import InsuranceClaimLineSerializer
        return Response({'line': InsuranceClaimLineSerializer(line).data,
                         'rx_net_after': float(rx.net_after),
                         'claim_net_after': float(claim.final_net_after)})

    @action(detail=True, methods=['post'],
            url_path='prescriptions/(?P<rx_id>[0-9]+)/lines/(?P<line_id>[0-9]+)/reset')
    def reset_line(self, request, pk=None, rx_id=None, line_id=None):
        """Restore a manually-edited line to its original imported values."""
        from decimal import Decimal
        from .models import InsuranceClaimLine
        from .classifier import powerquery_totals_from_splits
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            line = InsuranceClaimLine.objects.get(pk=line_id, prescription__claim=claim,
                                                  prescription_id=rx_id)
        except InsuranceClaimLine.DoesNotExist:
            return Response({'error': 'البند غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if not line.is_manually_edited or not line.original_json:
            return Response({'error': 'البند غير مُعدَّل'}, status=status.HTTP_400_BAD_REQUEST)

        rx = line.prescription
        o  = line.original_json
        rates = {
            'local':    Decimal(str(claim.applied_local_disc_pct    or 0)),
            'imported': Decimal(str(claim.applied_imported_disc_pct or 0)),
            'tarsia':   Decimal(str(claim.applied_tarsia_disc_pct   or 0)),
        }
        old_cat   = line.item_category
        old_total = Decimal(str(line.line_total or 0))
        new_cat   = o['item_category']
        new_total = Decimal(str(o['line_total']))

        # Restore the line
        line.softech_itemcode = o['softech_itemcode']
        line.item_name        = o['item_name']
        line.item_category    = o['item_category']
        line.quantity         = Decimal(str(o['quantity']))
        line.unit_price       = Decimal(str(o['unit_price']))
        line.line_total       = new_total
        line.discount_pct     = Decimal(str(o['discount_pct']))
        line.discount_amt     = Decimal(str(o['discount_amt']))
        line.net_amount       = Decimal(str(o['net_amount']))
        line.is_manually_edited = False
        line.original_json      = None
        line.save()

        # Reverse the delta on the prescription
        splits = {
            'local':    Decimal(str(rx.local_before    or 0)),
            'imported': Decimal(str(rx.imported_before or 0)),
            'tarsia':   Decimal(str(rx.tarsia_before   or 0)),
        }
        splits[old_cat] -= old_total
        splits[new_cat] += new_total
        t = powerquery_totals_from_splits(splits['local'], splits['imported'], splits['tarsia'],
                                          rates['local'], rates['imported'], rates['tarsia'])
        for f in ('local_before', 'imported_before', 'tarsia_before', 'gross_before',
                  'local_discount', 'imported_discount', 'tarsia_discount',
                  'total_discount', 'net_after'):
            setattr(rx, f, t[f])
        rx.save()
        recalculate_claim_final_totals(claim)
        if rx.billing_group_id:
            rx.billing_group.refresh_totals()
        record_audit(claim, 'line_reset', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'استرجاع بند (#{rx.softech_docnumber}) إلى قيمه الأصلية: {line.softech_itemcode}',
                     target_type='line', target_ref=str(line.pk),
                     after={'claim_net': float(claim.final_net_after)})
        from .serializers import InsuranceClaimLineSerializer
        return Response({'line': InsuranceClaimLineSerializer(line).data,
                         'claim_net_after': float(claim.final_net_after)})

    @action(detail=True, methods=['post'],
            url_path='prescriptions/(?P<rx_id>[0-9]+)/lines/(?P<line_id>[0-9]+)/review')
    def review_line(self, request, pk=None, rx_id=None, line_id=None):
        """
        Record a MANUAL revision/sign-off on a flagged line (value mismatch vs
        SOFTECH, catalog drift, or a تصنيف خصم التعاقد adjustment the user
        approves).  Metadata only — never mutates the frozen financial values, so
        it is allowed on locked claims too (reviewing a delivered motalba).
        """
        from django.utils import timezone
        from .models import InsuranceClaimLine
        claim = self.get_object()
        try:
            line = InsuranceClaimLine.objects.get(pk=line_id, prescription__claim=claim,
                                                  prescription_id=rx_id)
        except InsuranceClaimLine.DoesNotExist:
            return Response({'error': 'البند غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        approved = bool(request.data.get('approved', True))
        note = (request.data.get('note') or '').strip()[:300]
        line.review_approved = approved
        line.review_note     = note
        if approved:
            line.reviewed_by = request.user if request.user.is_authenticated else None
            line.reviewed_at = timezone.now()
        else:
            line.reviewed_by = None
            line.reviewed_at = None
        line.save(update_fields=['review_approved', 'review_note', 'reviewed_by', 'reviewed_at'])
        record_audit(claim, 'line_review', actor=getattr(request.user, 'staff_profile', None),
                     summary=('اعتماد مراجعة بند' if approved else 'إلغاء اعتماد مراجعة بند')
                             + f' (#{line.prescription.softech_docnumber}): {line.softech_itemcode}'
                             + (f' — {note}' if note else ''),
                     target_type='line', target_ref=str(line.pk),
                     after={'review_approved': approved, 'note': note})
        from .serializers import InsuranceClaimLineSerializer
        return Response({'line': InsuranceClaimLineSerializer(line).data})

    @action(detail=True, methods=['get'], url_path='flagged-lines')
    def flagged_lines(self, request, pk=None):
        """
        READ-ONLY: every FLAGGED line across the motalba (non-excluded), for the
        manual-revision grid — value discrepancy vs SOFTECH, catalog drift, or a
        SOFTECH-classification mismatch — each with its current revision/approval
        state so staff can sort, filter, and sign off before delivery.
        """
        from .discrepancy import line_variance_map
        from .models import InsuranceClaimLine, InsuranceClaimExclusion
        claim = self.get_object()
        excluded_ids = set(
            InsuranceClaimExclusion.objects.filter(prescription__claim=claim)
            .values_list('prescription_id', flat=True))
        lines = list(
            InsuranceClaimLine.objects
            .filter(prescription__claim=claim)
            .exclude(prescription_id__in=excluded_ids)
            .select_related('prescription', 'reviewed_by'))
        vmap = line_variance_map(claim, lines)
        rows = []
        for ln in lines:
            v = vmap.get(ln.pk) or {}
            kinds = []
            if v.get('value_discrepancy'):    kinds.append('value')
            if v.get('discount_discrepancy'): kinds.append('discount')
            if v.get('has_variance'):         kinds.append('drift')
            if v.get('softech_class_mismatch'): kinds.append('softech_class')
            if not kinds:
                continue
            rows.append({
                'line_id':        ln.pk,
                'prescription_id': ln.prescription_id,
                'docnumber':      ln.prescription.softech_docnumber,
                'branchcode':     ln.prescription.softech_branchcode,
                'docdate':        ln.prescription.softech_docdate.isoformat() if ln.prescription.softech_docdate else None,
                'patient_name':   ln.prescription.patient_name,
                'itemcode':       ln.softech_itemcode,
                'item_name':      ln.item_name,
                'item_category':  ln.item_category,
                'quantity':       float(ln.quantity or 0),
                'unit_price':     float(ln.unit_price or 0),
                'line_total':     float(ln.line_total or 0),
                'discount_amt':   float(ln.discount_amt or 0),
                'net_amount':     float(ln.net_amount or 0),
                'flags':          kinds,
                'value_discrepancy':    v.get('value_discrepancy', False),
                'discount_discrepancy': v.get('discount_discrepancy', False),
                'softech_line_net':     v.get('softech_line_net'),
                'softech_net_diff':     v.get('softech_net_diff'),
                'has_variance':         v.get('has_variance', False),
                'softech_class_mismatch': v.get('softech_class_mismatch', False),
                'softech_raw_category_label': v.get('softech_raw_category_label'),
                'current_category_label':     v.get('current_category_label'),
                'current_unit_price':         v.get('current_unit_price'),
                'net_delta':                  v.get('net_delta'),
                'review_approved': ln.review_approved,
                'review_note':     ln.review_note,
                'reviewed_by':     ln.reviewed_by.get_username() if ln.reviewed_by else None,
                'reviewed_at':     ln.reviewed_at.isoformat() if ln.reviewed_at else None,
            })
        return Response({
            'count':          len(rows),
            'pending_count':  sum(1 for r in rows if not r['review_approved']),
            'value_count':    sum(1 for r in rows if r['value_discrepancy']),
            'lines':          rows,
        })

    # ── SOFTECH re-price writeback (gated) ────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='softech-reprice/preview')
    def softech_reprice_preview(self, request, pk=None):
        """READ-ONLY: full old→new diff for a receipt re-price on HQ + branch."""
        from .reprice_service import build_preview, RepriceError
        d = request.data
        try:
            pv = build_preview(str(d['docnumber']), str(d['branch']),
                               d.get('prices') or {}, d.get('doccode', '115'))
            return Response(pv)
        except RepriceError as e:
            return Response({'detail': str(e)}, status=400)
        except KeyError:
            return Response({'detail': 'docnumber, branch, prices مطلوبة'}, status=400)
        except Exception as e:
            return Response({'detail': f'تعذّر الاتصال بسوفتك: {public_error(request, e)}'}, status=502)

    @action(detail=True, methods=['get'], url_path='softech-reprice/receipt-lines')
    def softech_reprice_receipt_lines(self, request, pk=None):
        """READ-ONLY: the item lines on a receipt, to pick from (docno + branch)."""
        from .reprice_service import list_receipt_lines
        docno = request.query_params.get('docno'); branch = request.query_params.get('branch')
        if not docno or not branch:
            return Response({'detail': 'docno و branch مطلوبان'}, status=400)
        try:
            return Response({'lines': list_receipt_lines(str(docno), str(branch),
                                                          request.query_params.get('doccode', '115'))})
        except Exception as e:
            return Response({'detail': f'تعذّر جلب البنود: {public_error(request, e)}'}, status=502)

    @action(detail=True, methods=['get'], url_path='softech-reprice/item-receipts')
    def softech_reprice_item_receipts(self, request, pk=None):
        """The claim's receipts that contain an item code — batch re-price candidates."""
        from .reprice_service import find_item_receipts
        claim = self.get_object()
        code = request.query_params.get('itemcode')
        if not code:
            return Response({'detail': 'itemcode مطلوب'}, status=400)
        return Response(find_item_receipts(claim, code))

    @action(detail=True, methods=['post'], url_path='softech-reprice/apply-batch')
    def softech_reprice_apply_batch(self, request, pk=None):
        """GATED: apply one new price for an item across several receipts (each its own run)."""
        from .reprice_service import apply_batch, RepriceError
        claim = self.get_object()
        d = request.data
        try:
            res = apply_batch(claim, str(d['itemcode']), d['new_price'],
                              d.get('receipts') or [], user=request.user, confirm=bool(d.get('confirm')))
            record_audit(claim, 'other', actor=getattr(request.user, 'staff_profile', None),
                         summary=f"تعديل سعر صنف {d['itemcode']} فى {res['applied']} إيصال (دفعة)",
                         target_type='item', target_ref=str(d['itemcode']))
            return Response(res)
        except RepriceError as e:
            return Response({'detail': str(e)}, status=400)
        except KeyError:
            return Response({'detail': 'itemcode, new_price, receipts مطلوبة'}, status=400)

    @action(detail=True, methods=['post'], url_path='softech-reprice/apply')
    def softech_reprice_apply(self, request, pk=None):
        """GATED write to SOFTECH (flag + confirm + draft-only + branch reachable)."""
        from .reprice_service import apply_reprice, RepriceError
        claim = self.get_object()
        d = request.data
        try:
            res = apply_reprice(claim, str(d['docnumber']), str(d['branch']),
                                d.get('prices') or {}, user=request.user,
                                confirm=bool(d.get('confirm')), doccode=d.get('doccode', '115'))
            record_audit(claim, 'other', actor=getattr(request.user, 'staff_profile', None),
                         summary=f"تعديل سعر سوفتك للإيصال #{d['docnumber']} (Δ{res['net_delta']})",
                         target_type='receipt', target_ref=str(d['docnumber']),
                         after={'run_id': res['run_id'], 'net_delta': res['net_delta']})
            return Response(res)
        except RepriceError as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['post'], url_path='softech-reprice/runs/(?P<run_id>[0-9]+)/rebalance')
    def softech_reprice_rebalance(self, request, pk=None, run_id=None):
        """GATED: shift personnewbal by the run's net Δ across the contract client's
        chain (all doc types, all branches). confirm=false → read-only footprint."""
        from .reprice_service import rebalance_run, rebalance_preview, RepriceError
        from .models import SoftechRepriceRun
        claim = self.get_object()
        try:
            run = SoftechRepriceRun.objects.get(pk=run_id, claim=claim)
            if not request.data.get('confirm'):
                return Response(rebalance_preview(run))
            res = rebalance_run(run, user=request.user, confirm=True)
            record_audit(claim, 'other', actor=getattr(request.user, 'staff_profile', None),
                         summary=f'إعادة ضبط رصيد التعاقد {run.cust_branch_code} ({res.get("updated")} صف)',
                         target_type='receipt', target_ref=run.docnumber)
            return Response(res)
        except SoftechRepriceRun.DoesNotExist:
            return Response({'detail': 'العملية غير موجودة'}, status=404)
        except RepriceError as e:
            return Response({'detail': str(e)}, status=400)

    @action(detail=True, methods=['get'], url_path='softech-date/preview')
    def softech_date_preview(self, request, pk=None):
        """Read-only: current printed date of a receipt + branch reachability."""
        claim = self.get_object()
        from .date_service import date_preview
        from .reprice_service import RepriceError
        docno = (request.query_params.get('docno') or '').strip()
        branch = (request.query_params.get('branch') or '').strip()
        new_date = (request.query_params.get('new_date') or '').strip()
        if not docno or not branch:
            return Response({'error': 'أدخل رقم الإيصال والفرع'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(date_preview(docno, branch, new_date or '', doccode=request.query_params.get('doccode', '115')))
        except RepriceError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'تعذّرت المعاينة: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)

    @action(detail=True, methods=['post'], url_path='softech-date/apply')
    def softech_date_apply(self, request, pk=None):
        """Set a receipt's printed date on HQ + branch (gated, revertible)."""
        claim = self.get_object()
        from .date_service import apply_date_edit
        from .reprice_service import RepriceError
        d = request.data
        try:
            res = apply_date_edit(claim, str(d.get('docno', '')).strip(), str(d.get('branch', '')).strip(),
                                  d.get('new_date'), user=request.user, confirm=bool(d.get('confirm')),
                                  doccode=str(d.get('doccode', '115')))
        except RepriceError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(claim, 'softech_date_edit', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'تعديل تاريخ إيصال سوفتك #{d.get("docno")}: {res["old_date"]} → {res["new_date"]}',
                     target_type='receipt', target_ref=str(d.get('docno')))
        return Response(res)

    @action(detail=True, methods=['get'], url_path='softech-date/runs')
    def softech_date_runs(self, request, pk=None):
        claim = self.get_object()
        from .models import SoftechDateEditRun
        return Response([{
            'id': r.pk, 'docnumber': r.docnumber, 'branch': r.branchcode, 'status': r.status,
            'old_date': r.old_date.isoformat(), 'new_date': r.new_date.isoformat(),
            'applied_at': r.applied_at.isoformat(),
            'reverted_at': r.reverted_at.isoformat() if r.reverted_at else None,
            'error': r.error,
        } for r in SoftechDateEditRun.objects.filter(claim=claim)])

    @action(detail=True, methods=['post'], url_path='softech-date/runs/(?P<run_id>[0-9]+)/revert')
    def softech_date_revert(self, request, pk=None, run_id=None):
        claim = self.get_object()
        from .models import SoftechDateEditRun
        from .date_service import revert_date_edit
        from .reprice_service import RepriceError
        try:
            run = SoftechDateEditRun.objects.get(pk=run_id, claim=claim)
            res = revert_date_edit(run, user=request.user)
        except SoftechDateEditRun.DoesNotExist:
            return Response({'error': 'العملية غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        except RepriceError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(claim, 'softech_date_revert', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'استرجاع تاريخ إيصال سوفتك #{run.docnumber} إلى {res["restored_date"]}',
                     target_type='receipt', target_ref=run.docnumber)
        return Response(res)

    @action(detail=True, methods=['get'], url_path='softech-reprice/runs')
    def softech_reprice_runs(self, request, pk=None):
        from .models import SoftechRepriceRun
        claim = self.get_object()
        runs = SoftechRepriceRun.objects.filter(claim=claim)
        return Response([{
            'id': r.pk, 'docnumber': r.docnumber, 'branch': r.branchcode,
            'status': r.status, 'net_delta': str(r.net_delta), 'nodes': r.nodes,
            'new_prices': r.new_prices, 'cust_branch_code': r.cust_branch_code,
            'rebalanced': r.rebalanced, 'applied_at': r.applied_at.isoformat(),
            'reverted_at': r.reverted_at.isoformat() if r.reverted_at else None,
            'error': r.error,
        } for r in runs])

    @action(detail=True, methods=['get'], url_path='softech-reprice/runs/export')
    def softech_reprice_runs_export(self, request, pk=None):
        """Export the SOFTECH re-price runs log (incl. failed modifications) as Excel.
        Optional ?status=failed to export only the failed modifications."""
        from .models import SoftechRepriceRun
        from .export import generate_reprice_runs_excel
        claim = self.get_object()
        runs = SoftechRepriceRun.objects.filter(claim=claim).select_related('applied_by')
        status_f = request.query_params.get('status')
        if status_f:
            runs = runs.filter(status=status_f)
        return generate_reprice_runs_excel(runs, claim_number=claim.claim_number)

    @action(detail=True, methods=['post'], url_path='softech-reprice/runs/(?P<run_id>[0-9]+)/revert')
    def softech_reprice_revert(self, request, pk=None, run_id=None):
        from .reprice_service import revert_run, RepriceError
        from .models import SoftechRepriceRun
        claim = self.get_object()
        try:
            run = SoftechRepriceRun.objects.get(pk=run_id, claim=claim)
            res = revert_run(run, user=request.user)
            record_audit(claim, 'revert_apply', actor=getattr(request.user, 'staff_profile', None),
                         summary=f'تراجع عن تعديل سعر سوفتك للإيصال #{run.docnumber}',
                         target_type='receipt', target_ref=run.docnumber)
            return Response(res)
        except SoftechRepriceRun.DoesNotExist:
            return Response({'detail': 'العملية غير موجودة'}, status=404)
        except RepriceError as e:
            return Response({'detail': str(e)}, status=400)

    # ── Adjust / Remove adjustment ────────────────────────────────────────────
    # POST  → save adjustment  |  DELETE → remove adjustment
    @action(detail=True, methods=['post', 'delete'],
            url_path='prescriptions/(?P<rx_id>[0-9]+)/adjust',
            url_name='prescription-adjust')
    def prescription_adjust(self, request, pk=None, rx_id=None):
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            rx = claim.prescriptions.get(pk=rx_id)
        except InsuranceClaimPrescription.DoesNotExist:
            return Response({'error': 'الروشتة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'DELETE':
            try:
                rx.adjustment.delete()
            except InsuranceClaimAdjustment.DoesNotExist:
                pass
            recalculate_claim_final_totals(claim)
            record_audit(claim, 'rx_adjust', actor=getattr(request.user, 'staff_profile', None),
                         summary=f'إزالة تعديل روشتة #{rx.softech_docnumber}',
                         target_type='prescription', target_ref=str(rx.softech_docnumber))
            return Response(status=status.HTTP_204_NO_CONTENT)

        # POST — save adjustment
        ser = AdjustPrescriptionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        staff = getattr(request.user, 'staff_profile', None)
        _net_before = float(rx.net_after or 0)
        adj, _ = InsuranceClaimAdjustment.objects.update_or_create(
            prescription=rx,
            defaults={
                'local_before':    data.get('local_before'),
                'imported_before': data.get('imported_before'),
                'tarsia_before':   data.get('tarsia_before'),
                'net_override':    data.get('net_override'),
                'reason':          data['reason'],
                'adjusted_by':     staff,
            }
        )
        recalculate_claim_final_totals(claim)
        record_audit(claim, 'rx_adjust', actor=staff,
                     summary=f'تعديل قيم روشتة #{rx.softech_docnumber}',
                     target_type='prescription', target_ref=str(rx.softech_docnumber),
                     reason=data.get('reason', ''),
                     before={'net': _net_before},
                     after={'net_override': float(data['net_override']) if data.get('net_override') is not None else None})
        return Response(InsuranceClaimAdjustmentSerializer(adj).data)

    # ── Exclude / Re-include prescription ─────────────────────────────────────
    # POST  → exclude  |  DELETE → re-include
    @action(detail=True, methods=['post', 'delete'],
            url_path='prescriptions/(?P<rx_id>[0-9]+)/exclude',
            url_name='prescription-exclude')
    def prescription_exclude(self, request, pk=None, rx_id=None):
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            rx = claim.prescriptions.get(pk=rx_id)
        except InsuranceClaimPrescription.DoesNotExist:
            return Response({'error': 'الروشتة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'DELETE':
            # Re-include guard: a receipt may be ACTIVELY billed in at most ONE
            # claim.  Refuse to un-exclude if it is non-excluded in another
            # overlapping-period claim (unless force=True) — the mirror of the
            # add-receipt double-billing guard.
            if not bool(request.data.get('force')):
                from .importer import find_duplicate_receipt
                actives = find_duplicate_receipt(
                    claim, rx.softech_docnumber, rx.softech_branchcode)
                if actives:
                    names = '، '.join(f"{d['claim_number']} ({d['status_label']})" for d in actives)
                    return Response({
                        'error': f'لا يمكن إعادة إدراج الفاتورة #{rx.softech_docnumber} — فهى مُدرجة '
                                 f'فعلياً (غير مستثناة) فى مطالبة أخرى: {names}. استثنِها من هناك أولاً، '
                                 f'أو أكِّد إذا كانت مرتجعة وأُعيد صرفها.',
                        'active_in': actives, 'needs_confirmation': True,
                    }, status=status.HTTP_409_CONFLICT)
            try:
                rx.exclusion.delete()
            except InsuranceClaimExclusion.DoesNotExist:
                pass
            recalculate_claim_final_totals(claim)
            record_audit(claim, 'rx_exclude', actor=getattr(request.user, 'staff_profile', None),
                         summary=f'إعادة إدراج روشتة #{rx.softech_docnumber} (صافى {float(rx.net_after or 0)})',
                         target_type='prescription', target_ref=str(rx.softech_docnumber),
                         after={'excluded': False})
            return Response(status=status.HTTP_204_NO_CONTENT)

        # POST — exclude
        staff = getattr(request.user, 'staff_profile', None)
        excl, created = InsuranceClaimExclusion.objects.get_or_create(
            prescription=rx,
            defaults={'reason': request.data.get('reason', ''), 'excluded_by': staff}
        )
        recalculate_claim_final_totals(claim)
        record_audit(claim, 'rx_exclude', actor=staff,
                     summary=f'استثناء روشتة #{rx.softech_docnumber} (صافى {float(rx.net_after or 0)})',
                     target_type='prescription', target_ref=str(rx.softech_docnumber),
                     reason=request.data.get('reason', ''), after={'excluded': True})
        return Response(InsuranceClaimExclusionSerializer(excl).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    # ── Look up single Rx from Softech (for manual add) ───────────────────────
    @action(detail=True, methods=['get'], url_path='lookup-rx')
    def lookup_rx(self, request, pk=None):
        claim     = self.get_object()
        docnumber = request.query_params.get('docnumber', '').strip()
        if not docnumber:
            return Response({'error': 'أدخل رقم الفاتورة'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rx_data = fetch_single_rx_from_softech(docnumber, claim)
        except InsuranceImportError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        # Same-month double-billing warning (does NOT block the lookup).
        from .importer import find_duplicate_receipt
        rx_data['duplicate_in'] = find_duplicate_receipt(
            claim, docnumber, rx_data.get('softech_branchcode'))
        return Response(rx_data)

    # ── Add manual Rx ─────────────────────────────────────────────────────────
    @action(detail=True, methods=['post'], url_path='manual-rx')
    def add_manual_rx(self, request, pk=None):
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        ser   = AddManualRxSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data  = ser.validated_data

        try:
            rx_data = fetch_single_rx_from_softech(
                data['softech_docnumber'], claim,
                branchcode=data.get('branchcode') or None,
            )
        except InsuranceImportError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Optional patient-name override (exact ID-card spelling) — applies to both
        # simple (totals-only) and detailed (full prescription) creation paths.
        # Keep the TRUE Softech-fetched name so a detailed rx can still revert to it.
        _orig_softech_name = (rx_data.get('patient_name') or '')
        _pname = (data.get('patient_name') or '').strip()
        if _pname:
            rx_data['patient_name'] = _pname

        # ── Same-month double-billing guard ───────────────────────────────────
        # Block adding a receipt that already sits in another overlapping-period,
        # non-rejected claim — unless the caller explicitly confirms (force=True),
        # e.g. a legitimately-returned receipt.  Different month / rejected peers
        # are not flagged.
        if not bool(request.data.get('force')):
            from .importer import find_duplicate_receipt
            dups = find_duplicate_receipt(
                claim, data['softech_docnumber'], data.get('branchcode') or None)
            if dups:
                names = '، '.join(f"{d['claim_number']} ({d['status_label']})" for d in dups)
                return Response({
                    'error': f'الفاتورة {data["softech_docnumber"]} مضافة بالفعل في مطالبة '
                             f'أخرى بنفس الشهر: {names}. أكِّد الإضافة إذا كانت مرتجعة وأُعيد صرفها.',
                    'duplicate_in': dups, 'needs_confirmation': True,
                }, status=status.HTTP_409_CONFLICT)

        # ── Auto-derive placement from the transaction date ───────────────────
        # If the caller didn't explicitly choose a position, place the Rx by its
        # actual docdate relative to the claim period:
        #   within [period_from, period_to] → that exact day  (position='date')
        #   before period_from              → ملحق سابق        (position='before')
        #   after  period_to                → ملحق لاحق        (position='after')
        position   = data.get('position')
        print_date = data.get('print_date')
        docdate    = rx_data['softech_docdate']
        if not position:
            if docdate and claim.period_from and docdate < claim.period_from:
                position, print_date = InsuranceClaimManualRx.POSITION_BEFORE, None
            elif docdate and claim.period_to and docdate > claim.period_to:
                position, print_date = InsuranceClaimManualRx.POSITION_AFTER, None
            else:
                position, print_date = InsuranceClaimManualRx.POSITION_DATE, docdate
        elif position == InsuranceClaimManualRx.POSITION_DATE and not print_date:
            # Explicit "specific day" but no date supplied → use the docdate
            print_date = docdate

        staff = getattr(request.user, 'staff_profile', None)

        # ── DETAILED mode ─────────────────────────────────────────────────────
        # Create a REAL prescription (with item lines) so it appears in
        # أصناف المطالبة / فحص الفروقات / فصل الأسماء and is per-line editable.
        mode = (request.data.get('mode') or 'simple').strip()
        if mode == 'detailed':
            from .importer import create_manual_prescription
            from .serializers import InsuranceClaimPrescriptionSerializer
            try:
                rx = create_manual_prescription(
                    claim, rx_data, position=position, print_date=print_date,
                    reason=data.get('reason', ''), user=staff,
                )
            except InsuranceImportError as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            # Preserve the TRUE Softech original name for revert (creation copied the
            # override into softech_patient_name).
            if _orig_softech_name and rx.softech_patient_name != _orig_softech_name:
                rx.softech_patient_name = _orig_softech_name
                rx.save(update_fields=['softech_patient_name'])
            record_audit(claim, 'manual_add', actor=staff,
                         summary=f'إضافة يدوية تفصيلية #{rx.softech_docnumber} ({rx.patient_name}) · '
                                 f'صافى {float(rx.net_after or 0)} · {rx.lines.count()} صنف',
                         target_type='prescription', target_ref=str(rx.softech_docnumber),
                         reason=data.get('reason', ''),
                         after={'net': float(rx.net_after or 0), 'mode': 'detailed', 'position': position})
            return Response(
                {**InsuranceClaimPrescriptionSerializer(rx).data,
                 'mode': 'detailed', 'is_manual': True,
                 'warning': rx_data.get('original_client_warning', '')},
                status=status.HTTP_201_CREATED,
            )

        # ── SIMPLE mode (totals-only manual Rx — unchanged) ───────────────────
        mrx = InsuranceClaimManualRx.objects.create(
            claim             = claim,
            softech_docnumber = rx_data['softech_docnumber'],
            softech_docdate   = rx_data['softech_docdate'],
            softech_branchcode= rx_data['softech_branchcode'],
            softech_personcode= rx_data['softech_personcode'],
            patient_name      = rx_data['patient_name'],
            softech_patient_name = _orig_softech_name or rx_data['patient_name'],
            original_client_warning = rx_data['original_client_warning'],
            local_before      = rx_data['local_before'],
            imported_before   = rx_data['imported_before'],
            tarsia_before     = rx_data['tarsia_before'],
            gross_before      = rx_data['gross_before'],
            local_discount    = rx_data['local_discount'],
            imported_discount = rx_data['imported_discount'],
            tarsia_discount   = rx_data['tarsia_discount'],
            total_discount    = rx_data['total_discount'],
            net_after         = rx_data['net_after'],
            position          = position,
            print_date        = print_date,
            reason            = data.get('reason', ''),
            added_by          = staff,
        )
        recalculate_claim_final_totals(claim)
        record_audit(claim, 'manual_add', actor=staff,
                     summary=f'إضافة يدوية (إجمالى) #{mrx.softech_docnumber} ({mrx.patient_name}) · '
                             f'صافى {float(mrx.net_after or 0)}',
                     target_type='manual_rx', target_ref=str(mrx.softech_docnumber),
                     reason=data.get('reason', ''),
                     after={'net': float(mrx.net_after or 0), 'mode': 'simple', 'position': position})
        return Response(InsuranceClaimManualRxSerializer(mrx).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='manual-prescription/(?P<rx_id>[0-9]+)')
    def delete_manual_prescription(self, request, pk=None, rx_id=None):
        """Hard-delete a DETAILED manual addition (is_manual prescription only).
        Imported prescriptions can never be deleted this way."""
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            rx = claim.prescriptions.get(pk=rx_id)
        except InsuranceClaimPrescription.DoesNotExist:
            return Response({'error': 'الروشتة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        if not rx.is_manual:
            return Response({'error': 'يُسمح بحذف الروشتات المضافة يدوياً فقط.'},
                            status=status.HTTP_400_BAD_REQUEST)
        _doc, _net = rx.softech_docnumber, float(rx.net_after or 0)
        rx.delete()
        recalculate_claim_final_totals(claim)
        record_audit(claim, 'manual_delete', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'حذف إضافة يدوية تفصيلية #{_doc} (صافى {_net})',
                     target_type='prescription', target_ref=str(_doc), before={'net': _net})
        return Response({'deleted': True, 'claim_net_after': float(claim.final_net_after)})

    @action(detail=True, methods=['patch', 'delete'], url_path='manual-rx/(?P<mrx_id>[0-9]+)')
    def update_or_remove_manual_rx(self, request, pk=None, mrx_id=None):
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked

        if request.method == 'DELETE':
            InsuranceClaimManualRx.objects.filter(pk=mrx_id, claim=claim).delete()
            recalculate_claim_final_totals(claim)
            return Response(status=status.HTTP_204_NO_CONTENT)

        # PATCH — edit a manually-added receipt (split / net / patient / exclude)
        try:
            mrx = InsuranceClaimManualRx.objects.get(pk=mrx_id, claim=claim)
        except InsuranceClaimManualRx.DoesNotExist:
            return Response({'error': 'الروشتة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)

        from decimal import Decimal
        from .classifier import powerquery_totals_from_splits
        d = request.data
        Q = Decimal('0.01')
        def _dec(v, cur):
            if v is None or v == '':
                return Decimal(str(cur or 0))
            return Decimal(str(v)).quantize(Q)

        # revert=True → restore the original Softech patient name
        if d.get('revert'):
            mrx.patient_name = mrx.softech_patient_name or mrx.patient_name
        # Simple text/meta fields
        for f in ('patient_name', 'reason', 'position'):
            if f in d and d[f] is not None:
                setattr(mrx, f, d[f])
        if 'print_date' in d:
            mrx.print_date = d['print_date'] or None
        if 'is_excluded' in d:
            want_excluded = bool(d['is_excluded'])
            # Re-include guard (mirror of the add-receipt double-billing guard):
            # only allow un-excluding if the receipt is not actively billed elsewhere.
            if mrx.is_excluded and not want_excluded and not bool(d.get('force')) and mrx.softech_docnumber:
                from .importer import find_duplicate_receipt
                actives = find_duplicate_receipt(
                    claim, mrx.softech_docnumber, mrx.softech_branchcode)
                if actives:
                    names = '، '.join(f"{a['claim_number']} ({a['status_label']})" for a in actives)
                    return Response({
                        'error': f'لا يمكن إعادة إدراج الفاتورة #{mrx.softech_docnumber} — فهى مُدرجة '
                                 f'فعلياً فى مطالبة أخرى: {names}. استثنِها من هناك أولاً.',
                        'active_in': actives, 'needs_confirmation': True,
                    }, status=status.HTTP_409_CONFLICT)
            mrx.is_excluded = want_excluded

        # Financial edit — recompute from the (possibly edited) splits, unless a
        # net_override is supplied (then split the discount proportionally).
        touched_money = any(k in d for k in ('local_before', 'imported_before', 'tarsia_before', 'net_override'))
        if touched_money:
            lb = _dec(d.get('local_before'),    mrx.local_before)
            ib = _dec(d.get('imported_before'), mrx.imported_before)
            tb = _dec(d.get('tarsia_before'),   mrx.tarsia_before)
            gb = (lb + ib + tb).quantize(Q)
            net_override = d.get('net_override')
            if net_override not in (None, ''):
                net = Decimal(str(net_override)).quantize(Q)
                disc = (gb - net).quantize(Q)
                ld = (disc * lb / gb).quantize(Q) if gb else Decimal('0')
                idd = (disc * ib / gb).quantize(Q) if gb else Decimal('0')
                td = (disc - ld - idd).quantize(Q)
            else:
                t = powerquery_totals_from_splits(
                    lb, ib, tb,
                    claim.applied_local_disc_pct, claim.applied_imported_disc_pct,
                    claim.applied_tarsia_disc_pct)
                ld, idd, td = t['local_discount'], t['imported_discount'], t['tarsia_discount']
                disc, net = t['total_discount'], t['net_after']
            mrx.local_before, mrx.imported_before, mrx.tarsia_before = lb, ib, tb
            mrx.gross_before = gb
            mrx.local_discount, mrx.imported_discount, mrx.tarsia_discount = ld, idd, td
            mrx.total_discount, mrx.net_after = disc, net
            mrx.is_manually_edited = True

        mrx.save()
        recalculate_claim_final_totals(claim)
        # Keep any billing-group totals in sync if this rx is assigned
        if mrx.billing_group_id:
            mrx.billing_group.refresh_totals()
        return Response(InsuranceClaimManualRxSerializer(mrx).data)

    # ── Supplements ───────────────────────────────────────────────────────────
    @action(detail=True, methods=['get', 'post'], url_path='supplements')
    def supplements(self, request, pk=None):
        claim = self.get_object()
        if request.method == 'GET':
            sups = claim.supplements.all()
            return Response(InsuranceClaimSupplementSerializer(sups, many=True).data)

        locked = self._locked_response(claim)
        if locked:
            return locked

        # Normalise incoming data:
        #  • empty print_date string ('') → None (DRF DateField rejects '')
        #  • auto-compute gross/discount/net from the before-values using the
        #    claim's applied discount rates, so the user only enters محلى/مستورد/
        #    ترسية قبل الخصم and we derive the rest consistently.
        payload = {k: v for k, v in request.data.items()}
        if payload.get('print_date') in ('', None):
            payload['print_date'] = None

        from decimal import Decimal as _D
        def _d(v):
            try:
                return _D(str(v or 0))
            except Exception:
                return _D('0')
        lb, ib, tb = _d(payload.get('local_before')), _d(payload.get('imported_before')), _d(payload.get('tarsia_before'))
        gross = lb + ib + tb
        ld = (lb * _d(claim.applied_local_disc_pct)    / 100).quantize(_D('0.01'))
        idd = (ib * _d(claim.applied_imported_disc_pct) / 100).quantize(_D('0.01'))
        td = (tb * _d(claim.applied_tarsia_disc_pct)   / 100).quantize(_D('0.01'))
        disc = ld + idd + td
        payload['gross_before']      = str(gross)
        payload['local_discount']    = str(ld)
        payload['imported_discount'] = str(idd)
        payload['tarsia_discount']   = str(td)
        payload['total_discount']    = str(disc)
        payload['net_after']         = str(gross - disc)

        ser = InsuranceClaimSupplementSerializer(data=payload)
        ser.is_valid(raise_exception=True)
        staff = getattr(request.user, 'staff_profile', None)
        sup = ser.save(claim=claim, created_by=staff)
        recalculate_claim_final_totals(claim)
        return Response(InsuranceClaimSupplementSerializer(sup).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['put', 'patch', 'delete'],
            url_path='supplements/(?P<sup_id>[0-9]+)')
    def supplement_detail(self, request, pk=None, sup_id=None):
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            sup = claim.supplements.get(pk=sup_id)
        except InsuranceClaimSupplement.DoesNotExist:
            return Response({'error': 'الملحق غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'DELETE':
            sup.delete()
            recalculate_claim_final_totals(claim)
            return Response(status=status.HTTP_204_NO_CONTENT)

        touched_money = any(k in request.data for k in ('local_before', 'imported_before', 'tarsia_before'))
        ser = InsuranceClaimSupplementSerializer(sup, data=request.data, partial=(request.method == 'PATCH'))
        ser.is_valid(raise_exception=True)
        sup = ser.save()

        # Recompute gross/discount/net from the (possibly edited) before-values
        # using the claim's rates — keeps the supplement internally consistent.
        from decimal import Decimal as _D
        def _d(v):
            try:
                return _D(str(v or 0))
            except Exception:
                return _D('0')
        lb, ib, tb = _d(sup.local_before), _d(sup.imported_before), _d(sup.tarsia_before)
        ld  = (lb * _d(claim.applied_local_disc_pct)    / 100).quantize(_D('0.01'))
        idd = (ib * _d(claim.applied_imported_disc_pct) / 100).quantize(_D('0.01'))
        td  = (tb * _d(claim.applied_tarsia_disc_pct)   / 100).quantize(_D('0.01'))
        sup.gross_before     = lb + ib + tb
        sup.local_discount   = ld
        sup.imported_discount = idd
        sup.tarsia_discount  = td
        sup.total_discount   = ld + idd + td
        sup.net_after        = sup.gross_before - sup.total_discount
        if touched_money:
            sup.is_manually_edited = True
        sup.save(update_fields=[
            'gross_before', 'local_discount', 'imported_discount',
            'tarsia_discount', 'total_discount', 'net_after', 'is_manually_edited',
        ])
        recalculate_claim_final_totals(claim)
        if sup.billing_group_id:
            sup.billing_group.refresh_totals()
        record_audit(claim, 'supplement', actor=getattr(request.user, 'staff_profile', None),
                     summary=f'ملحق «{sup.label}» ({sup.get_supplement_type_display() if hasattr(sup, "get_supplement_type_display") else sup.supplement_type}) · صافى {float(sup.net_after or 0)}',
                     target_type='supplement', target_ref=str(sup.pk),
                     after={'net': float(sup.net_after or 0)})
        return Response(InsuranceClaimSupplementSerializer(sup).data)

    # ── Payments ──────────────────────────────────────────────────────────────
    @action(detail=True, methods=['get', 'post'], url_path='payments')
    def payments(self, request, pk=None):
        claim = self.get_object()
        if request.method == 'GET':
            return Response(InsurancePaymentSerializer(claim.payments.all(), many=True).data)
        ser = InsurancePaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        staff = getattr(request.user, 'staff_profile', None)
        pmt = ser.save(claim=claim, recorded_by=staff)
        record_audit(claim, 'payment', actor=staff,
                     summary=f'تحصيل دفعة: {float(getattr(pmt, "amount", 0) or 0)}',
                     target_type='payment', target_ref=str(pmt.pk),
                     after={'amount': float(getattr(pmt, 'amount', 0) or 0)})
        return Response(InsurancePaymentSerializer(pmt).data, status=status.HTTP_201_CREATED)

    # ── Deductions ────────────────────────────────────────────────────────────
    @action(detail=True, methods=['get', 'post'], url_path='deductions')
    def deductions(self, request, pk=None):
        claim = self.get_object()
        if request.method == 'GET':
            return Response(InsuranceDeductionSerializer(claim.deductions.all(), many=True).data)
        ser = InsuranceDeductionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        staff = getattr(request.user, 'staff_profile', None)
        ded = ser.save(claim=claim, recorded_by=staff)
        record_audit(claim, 'deduction', actor=staff,
                     summary=f'خصم/استقطاع: {float(getattr(ded, "amount", 0) or 0)} — {getattr(ded, "reason_detail", "") or getattr(ded, "reason_code", "")}',
                     target_type='deduction', target_ref=str(ded.pk),
                     reason=getattr(ded, 'reason_detail', '') or '',
                     after={'amount': float(getattr(ded, 'amount', 0) or 0)})
        return Response(InsuranceDeductionSerializer(ded).data, status=status.HTTP_201_CREATED)

    # ── Discover motalbas from Softech across all clients / date range ────────
    @action(detail=False, methods=['get'], url_path='discover-motalbas')
    def discover_motalbas(self, request):
        """
        Query Softech for all motalbas within a date range, for all configured
        subclients (or a specific one).  Returns each motalba annotated with its
        import status: imported / not_imported.

        Query params:
          date_from      YYYY-MM-DD  (required)
          date_to        YYYY-MM-DD  (required)
          subclient_id   int         (optional — filter to one subclient)
        """
        date_from    = request.query_params.get('date_from', '').strip()
        date_to      = request.query_params.get('date_to', '').strip()
        subclient_id = request.query_params.get('subclient_id')

        if not date_from or not date_to:
            return Response(
                {'error': 'date_from و date_to مطلوبان (YYYY-MM-DD)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from .sybase_queries import (
            QUERY_DISCOVER_MOTALBAS_BY_PC_DATERANGE,
            QUERY_DISCOVER_MOTALBAS_BY_DATERANGE,
        )

        # Build subclient map: personcode → subclient info
        sc_qs = InsuranceSubClient.objects.select_related('client').filter(is_active=True)
        if subclient_id:
            sc_qs = sc_qs.filter(pk=subclient_id)

        # personcode → subclient (pick first match; a personcode may appear in one sc)
        pc_to_sc: dict[str, InsuranceSubClient] = {}
        for sc in sc_qs:
            for pc in sc.get_all_personcodes():
                if pc not in pc_to_sc:
                    pc_to_sc[pc] = sc

        if not pc_to_sc:
            return Response({'results': []})

        # Build set of already-imported (subclient_id, motalbano) pairs
        existing = set(
            InsuranceClaim.objects
            .filter(subclient__in=list({sc.id for sc in pc_to_sc.values()}))
            .values_list('subclient_id', 'softech_motalba_no')
        )

        try:
            from config.sybase import get_sybase_connection
            conn = get_sybase_connection()
        except Exception as e:
            return Response({'error': f'فشل الاتصال بسوفتك: {public_error(request, e)}'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Build personcode → personname map from personsdata so that
        # unconfigured personcodes still show their real Arabic company name
        # instead of the bare numeric code.
        personname_map: dict[str, str] = {}
        try:
            from .sybase_queries import QUERY_ALL_PERSONNAMES
            pn_cursor = conn.cursor()
            pn_cursor.execute(QUERY_ALL_PERSONNAMES)
            for pr in pn_cursor.fetchall():
                code = str(pr[0] or '').strip()
                name = str(pr[1] or '').strip()
                if code and name:
                    personname_map[code] = name
        except Exception as e:
            logger.warning('personname map load failed: %s', e)
            # Non-fatal — fall back to showing personcode
            try:
                conn = get_sybase_connection()
            except Exception:
                logger.debug('personname map: SOFTECH reconnect failed', exc_info=True)

        results = []
        seen = set()  # (personcode, motalbano)

        # Build a reverse map: personcode → subclient (for enriching raw results)
        all_existing_claims = {
            (str(c['subclient_id']), c['softech_motalba_no']): c
            for c in InsuranceClaim.objects.values(
                'id', 'claim_number', 'status', 'final_net_after',
                'subclient_id', 'softech_motalba_no'
            )
        }

        def _make_row(r, sc, personcode):
            motalbano = int(str(r[1]).split('.')[0]) if r[1] else None
            if not motalbano:
                return None
            key = (personcode, motalbano)
            if key in seen:
                return None
            seen.add(key)

            cl_key = (str(sc.id), str(motalbano)) if sc else None
            ec = all_existing_claims.get(cl_key) if cl_key else None
            is_imported = ec is not None

            # Resolve Softech company name from personsdata for unconfigured codes
            softech_name = personname_map.get(personcode, '')
            fallback_label = softech_name or personcode

            return {
                'personcode':        personcode,
                'softech_personname': softech_name,
                'motalbano':         motalbano,
                'motfromdate':       str(r[2])[:10] if r[2] else None,
                'mottodate':         str(r[3])[:10] if r[3] else None,
                'rxcount':           int(r[4] or 0),
                'docvaluetotal':     float(r[5] or 0),
                'subclient_id':      sc.id if sc else None,
                'subclient_name':    sc.name if sc else None,
                'client_name':       sc.client.name if sc else fallback_label,
                'client_name_short': (sc.client.name_short or sc.client.name) if sc else fallback_label,
                'configured':        sc is not None,
                'status':            'imported' if is_imported else 'not_imported',
                'existing_claim':    {
                    'id':           ec['id'],
                    'claim_number': ec['claim_number'],
                    'status':       ec['status'],
                } if ec else None,
            }

        if subclient_id and pc_to_sc:
            # Specific subclient requested — query only its personcodes
            for pc, sc in pc_to_sc.items():
                try:
                    cursor = conn.cursor()
                    cursor.execute(QUERY_DISCOVER_MOTALBAS_BY_PC_DATERANGE,
                                   [pc, date_from, date_to])
                    rows = cursor.fetchall()
                except Exception as e:
                    logger.warning('discover query failed pc=%s: %s', pc, e)
                    try:
                        conn = get_sybase_connection()
                    except Exception:
                        logger.debug('discover: SOFTECH reconnect failed', exc_info=True)
                    continue
                for r in rows:
                    row = _make_row(r, sc, str(r[0]).strip() if r[0] else '')
                    if row:
                        results.append(row)
        else:
            # No specific subclient — query ALL personcodes from Softech motalba table.
            # This finds motalbas for ALL insurance companies, configured or not.
            # Build a fast reverse map: personcode → subclient for enrichment.
            all_scs = list(InsuranceSubClient.objects.select_related('client').all())
            pc_map: dict[str, InsuranceSubClient] = {}
            for sc in all_scs:
                for pc in sc.get_all_personcodes():
                    if pc not in pc_map:
                        pc_map[pc] = sc

            try:
                cursor = conn.cursor()
                cursor.execute(QUERY_DISCOVER_MOTALBAS_BY_DATERANGE,
                               [date_from, date_to])
                rows = cursor.fetchall()
                for r in rows:
                    pc     = str(r[0]).strip() if r[0] else ''
                    sc_match = pc_map.get(pc)
                    row = _make_row(r, sc_match, pc)
                    if row:
                        results.append(row)
            except Exception as e:
                return Response({'error': f'خطأ في الاستعلام: {public_error(request, e)}'},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        results.sort(key=lambda x: x['motalbano'], reverse=True)
        return Response({'results': results, 'total': len(results)})

    # ── Bulk import selected motalbas from Softech ─────────────────────────────
    @action(detail=False, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request):
        """
        Import multiple motalbas at once.

        Body: { "items": [ { "subclient_id": 1, "motalbano": 117, "contract_id": 1 }, … ] }

        Each item is imported independently; errors on individual items are
        collected and returned without stopping the remaining imports.
        """
        items = request.data.get('items', [])
        if not items:
            return Response({'error': 'items مطلوب'}, status=status.HTTP_400_BAD_REQUEST)

        staff = getattr(request.user, 'staff_profile', None)
        results = []

        for item in items:
            subclient_id = item.get('subclient_id')
            motalbano    = item.get('motalbano')
            contract_id  = item.get('contract_id')

            if not subclient_id or not motalbano:
                results.append({'motalbano': motalbano, 'status': 'error',
                                 'error': 'subclient_id و motalbano مطلوبان'})
                continue

            try:
                subclient = InsuranceSubClient.objects.get(pk=subclient_id)
            except InsuranceSubClient.DoesNotExist:
                results.append({'motalbano': motalbano, 'status': 'error',
                                 'error': 'الفئة غير موجودة'})
                continue

            # Check if already imported
            existing = InsuranceClaim.objects.filter(
                subclient=subclient, softech_motalba_no=str(motalbano)
            ).first()
            if existing:
                results.append({
                    'motalbano':    motalbano,
                    'status':       'already_imported',
                    'claim_number': existing.claim_number,
                    'claim_id':     existing.id,
                })
                continue

            # Resolve contract and discount rates
            contract       = None
            local_disc = imported_disc = tarsia_disc = 0
            if contract_id:
                try:
                    contract = InsuranceContract.objects.get(pk=contract_id)
                except InsuranceContract.DoesNotExist:
                    pass
            if not contract:
                contract = subclient.contracts.order_by('-effective_from').first()
            if contract:
                local_disc    = contract.local_discount_pct
                imported_disc = contract.imported_discount_pct
                tarsia_disc   = contract.tarsia_discount_pct

            claim = InsuranceClaim.objects.create(
                claim_number              = _next_claim_number(),
                subclient                 = subclient,
                contract                  = contract,
                period_from               = '2000-01-01',
                period_to                 = '2099-12-31',
                softech_motalba_no        = str(motalbano),
                imported_personcodes      = ','.join(subclient.get_all_personcodes()),
                applied_local_disc_pct    = local_disc,
                applied_imported_disc_pct = imported_disc,
                applied_tarsia_disc_pct   = tarsia_disc,
                status                    = InsuranceClaim.STATUS_DRAFT,
                created_by                = staff,
            )

            try:
                from .importer import import_claim_by_motalbano, InsuranceImportError
                summary = import_claim_by_motalbano(
                    claim=claim, motalbano=int(motalbano), user=staff,
                )
                claim.refresh_from_db()
                results.append({
                    'motalbano':    motalbano,
                    'status':       'imported',
                    'claim_number': claim.claim_number,
                    'claim_id':     claim.id,
                    'rx_count':     claim.snapshot_rx_count,
                    'net_after':    float(claim.final_net_after),
                })
            except InsuranceImportError as e:
                claim.delete()
                results.append({'motalbano': motalbano, 'status': 'error', 'error': str(e)})
            except Exception as e:
                logger.exception('bulk_import failed motalbano=%s', motalbano)
                claim.delete()
                results.append({'motalbano': motalbano, 'status': 'error',
                                 'error': f'خطأ غير متوقع: {e}'})

        imported_count = sum(1 for r in results if r['status'] == 'imported')
        error_count    = sum(1 for r in results if r['status'] == 'error')

        return Response({
            'imported': imported_count,
            'errors':   error_count,
            'results':  results,
        }, status=status.HTTP_200_OK)

    # ── Generate invoice dataset (for print / export) ─────────────────────────
    @action(detail=True, methods=['get'], url_path='invoice-dataset')
    def invoice_dataset(self, request, pk=None):
        """
        Returns the final invoice dataset for template rendering.
        Includes: active prescriptions (adjusted, not excluded) + supplements + manual_rx
        Organized by print date for template rendering.
        """
        claim = self.get_object()
        from .invoice_builder import build_invoice_dataset
        dataset = build_invoice_dataset(claim)
        return Response(dataset)

    @action(detail=True, methods=['get'], url_path='export/excel')
    def export_excel(self, request, pk=None):
        """Export the claim's Excel workbook (optionally a flat, custom-sorted layout)."""
        claim    = self.get_object()
        p        = request.query_params
        template = p.get('template', 'all')
        layout   = p.get('layout', 'daily')      # 'daily' | 'flat'
        sort_by  = p.get('sort_by', 'patient_name')
        sort_dir = p.get('sort_dir', 'asc')
        from .export import generate_excel
        return generate_excel(claim, template=template, layout=layout,
                              sort_by=sort_by, sort_dir=sort_dir)

    @action(detail=True, methods=['get'], url_path='export/statistical')
    def export_statistical(self, request, pk=None):
        """Government monthly-statistics listing (الاحصائية الشهرية للصيدلية)."""
        claim = self.get_object()
        from .export import generate_statistical_excel
        return generate_statistical_excel(claim)

    @action(detail=True, methods=['get'], url_path='cover-letter')
    def cover_letter(self, request, pk=None):
        """Official cover letter (خطاب تقديم) as a Word .docx."""
        claim = self.get_object()
        from .letter import generate_cover_letter
        return generate_cover_letter(claim)

    @action(detail=True, methods=['get'], url_path='submission-package')
    def submission_package(self, request, pk=None):
        """ZIP bundle: cover letter (.docx) + full workbook (.xlsx)."""
        claim = self.get_object()
        from .letter import generate_submission_package
        return generate_submission_package(claim)

    # ── PRE-FLIGHT READINESS VALIDATION (before اصدار مطالبة) ─────────────────
    @action(detail=True, methods=['get'], url_path='readiness')
    def readiness(self, request, pk=None):
        """Run pre-flight checks and return a readiness report + health score."""
        claim = self.get_object()
        from .validation import validate_claim_readiness
        return Response(validate_claim_readiness(claim))

    @action(detail=True, methods=['get'], url_path='omissions')
    def omissions(self, request, pk=None):
        """Find motalba receipts not yet imported into this claim (missed revenue)."""
        claim = self.get_object()
        from .validation import find_claim_omissions
        return Response(find_claim_omissions(claim))

    # ── VALUE DISCREPANCY (frozen snapshot vs current master classification) ──
    @action(detail=True, methods=['get'], url_path='discrepancy')
    def discrepancy(self, request, pk=None):
        """
        Re-classify the claim's frozen lines against current item master data
        and report where category / discount / net would differ if re-imported.
        Read-only — does not touch the snapshot.
        """
        claim = self.get_object()
        from .discrepancy import compute_claim_discrepancy
        return Response(compute_claim_discrepancy(claim))

    @action(detail=True, methods=['get'], url_path='discrepancy-export')
    def discrepancy_export(self, request, pk=None):
        """Export the value-discrepancy report as a styled Excel file."""
        claim = self.get_object()
        from .discrepancy import compute_claim_discrepancy
        from .export import generate_discrepancy_excel
        report = compute_claim_discrepancy(claim)
        return generate_discrepancy_excel(report, claim_number=claim.claim_number)

    @action(detail=True, methods=['post'], url_path='apply-current-master')
    def apply_current_master(self, request, pk=None):
        """
        Re-freeze the claim's lines + totals to current item master data.
        Body (optional): { apply_price: bool=true, apply_category: bool=true }
        """
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        from .discrepancy import apply_current_master
        staff = getattr(request.user, 'staff_profile', None)
        apply_price    = request.data.get('apply_price', True)
        apply_category = request.data.get('apply_category', True)
        raw_ids        = request.data.get('line_ids', None)
        line_ids = None
        if raw_ids is not None:
            try:
                line_ids = {int(x) for x in raw_ids}
            except (TypeError, ValueError):
                return Response({'error': 'line_ids يجب أن تكون أرقاماً'},
                                status=status.HTTP_400_BAD_REQUEST)
            if not line_ids:
                return Response({'error': 'لم يتم تحديد أي بند'},
                                status=status.HTTP_400_BAD_REQUEST)
        try:
            result = apply_current_master(
                claim, apply_price=bool(apply_price), apply_category=bool(apply_category),
                line_ids=line_ids, user=staff,
            )
        except Exception as exc:  # surface the real cause instead of a bare 500
            import logging, traceback
            logging.getLogger('insurance').error(
                'apply_current_master failed (claim=%s, lines=%s): %s\n%s',
                claim.pk, (len(line_ids) if line_ids else 'all'), exc,
                traceback.format_exc(),
            )
            return Response(
                {'error': f'تعذّر تطبيق التحديث: {public_error(request, exc)}',
                 'detail': public_error(request, exc), 'error_type': type(exc).__name__},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        scope = f'{len(line_ids)} بند محدد' if line_ids else 'كل البنود'
        what = ' + '.join([x for x in ['تصنيف' if apply_category else '', 'سعر' if apply_price else ''] if x])
        skipped_note = (f' · تم تخطى {result.get("skipped_count")} بند لتعذّر معالجته'
                        if result.get('skipped_count') else '')
        record_audit(claim, 'apply_master', actor=staff,
                     summary=f'تطبيق بيانات الكتالوج ({what}) على {scope}: {result.get("lines_updated",0)} بند{skipped_note} · '
                             f'الصافى {result.get("net_before")} → {result.get("net_after")}',
                     before={'net': result.get('net_before')}, after={'net': result.get('net_after')},
                     meta={'run_id': result.get('run_id'), 'lines_updated': result.get('lines_updated'),
                           'skipped': result.get('skipped')})
        return Response(result)

    @action(detail=True, methods=['get'], url_path='overrides-preview')
    def overrides_preview(self, request, pk=None):
        """Preview which lines the active item corrections would change (read-only)."""
        claim = self.get_object()
        from .discrepancy import preview_overrides_for_claim
        return Response(preview_overrides_for_claim(claim))

    @action(detail=True, methods=['post'], url_path='apply-overrides')
    def apply_overrides(self, request, pk=None):
        """Apply active item-classification corrections to this draft claim (audited, revertible)."""
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        from .discrepancy import apply_overrides_to_claim
        staff = getattr(request.user, 'staff_profile', None)
        res = apply_overrides_to_claim(claim, user=staff)
        record_audit(claim, 'apply_overrides', actor=staff,
                     summary=f'تطبيق تصويبات التصنيف: {res.get("lines_updated",0)} بند · '
                             f'الصافى {res.get("net_before")} → {res.get("net_after")}',
                     before={'net': res.get('net_before')}, after={'net': res.get('net_after')})
        return Response(res)

    @action(detail=True, methods=['get'], url_path='claim-items')
    def claim_items(self, request, pk=None):
        """One row per dispensed item in the motalba with its applied discount (for revision)."""
        claim = self.get_object()
        from .discrepancy import claim_items_for_revision
        return Response(claim_items_for_revision(claim))

    @action(detail=True, methods=['get'], url_path='prescriptions-by-item')
    def prescriptions_by_item(self, request, pk=None):
        """Prescription ids in this claim that contain an item matching `q`
        (by item name or code).  Powers الروشتات search-by-item."""
        claim = self.get_object()
        from .models import InsuranceClaimLine
        q = (request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'prescription_ids': [], 'matched_items': []})
        lines = (InsuranceClaimLine.objects
                 .filter(prescription__claim=claim)
                 .filter(wq(q, 'item_name') | Q(softech_itemcode__icontains=q)))
        rx_ids = sorted(set(lines.values_list('prescription_id', flat=True)))
        matched = sorted({(ln.softech_itemcode, ln.item_name) for ln in lines})[:20]
        return Response({
            'prescription_ids': rx_ids,
            'matched_items': [{'code': c, 'name': n} for c, n in matched],
        })

    @action(detail=True, methods=['get'], url_path='review-items')
    def review_items(self, request, pk=None):
        """List dual-origin (review) items present in this claim, for per-motalba decision."""
        claim = self.get_object()
        from .discrepancy import review_items_for_claim
        return Response(review_items_for_claim(claim))

    @action(detail=True, methods=['get'], url_path='separation-matches')
    def separation_matches(self, request, pk=None):
        """Prescriptions whose patient name matches an active separation list (for فصل)."""
        claim = self.get_object()
        from .separation import find_separation_matches
        list_id = request.query_params.get('list_id') or None
        return Response(find_separation_matches(claim, sep_list_id=list_id))

    @action(detail=True, methods=['get'], url_path='audit-log')
    def audit_log(self, request, pk=None):
        """Activity trail for this claim — every material change (who/what/when/
        why/before→after).  Optional ?action= filter, ?limit= (default 300)."""
        claim = self.get_object()
        qs = claim.audit_events.select_related('actor').all()
        act = request.query_params.get('action')
        if act:
            qs = qs.filter(action=act)
        try:
            limit = min(int(request.query_params.get('limit', 300)), 1000)
        except (TypeError, ValueError):
            limit = 300
        from .models import InsuranceAuditEvent as _AE
        labels = dict(_AE.ACTIONS)
        rows = [{
            'id':           e.pk,
            'action':       e.action,
            'action_label': labels.get(e.action, e.action),
            'at':           e.at.isoformat(),
            'actor':        e.actor_name or (str(e.actor) if e.actor else None),
            'target_type':  e.target_type,
            'target_ref':   e.target_ref,
            'summary':      e.summary,
            'reason':       e.reason,
            'before':       e.before,
            'after':        e.after,
            'meta':         e.meta,
        } for e in qs[:limit]]
        return Response({'count': len(rows), 'events': rows})

    @action(detail=True, methods=['post'], url_path='bulk-exclude')
    def bulk_exclude(self, request, pk=None):
        """Exclude many prescriptions at once (used to separate flagged names)."""
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        from .models import InsuranceClaimExclusion
        ids = request.data.get('prescription_ids', [])
        reason = (request.data.get('reason') or 'فصل — قائمة الأسماء').strip()
        if not ids:
            return Response({'error': 'prescription_ids required'}, status=status.HTTP_400_BAD_REQUEST)
        staff = getattr(request.user, 'staff_profile', None)
        n = 0
        for rx in claim.prescriptions.filter(id__in=ids):
            _, created = InsuranceClaimExclusion.objects.get_or_create(
                prescription=rx, defaults={'reason': reason, 'excluded_by': staff})
            n += 1 if created else 0
        recalculate_claim_final_totals(claim)
        record_audit(claim, 'bulk_exclude', actor=staff,
                     summary=f'استبعاد جماعي (فصل): {n} روشتة — {reason}',
                     reason=reason, meta={'count': n, 'prescription_ids': list(ids)[:200]},
                     after={'claim_net': float(claim.final_net_after)})
        return Response({'excluded': n, 'claim_net_after': float(claim.final_net_after)})

    @action(detail=True, methods=['post'], url_path='mark-reviewed')
    def mark_reviewed(self, request, pk=None):
        """Set the separation-review flag on prescriptions (does NOT change totals)."""
        claim = self.get_object()
        ids = request.data.get('prescription_ids', [])
        reviewed = bool(request.data.get('reviewed', True))
        if not ids:
            return Response({'error': 'prescription_ids required'}, status=status.HTTP_400_BAD_REQUEST)
        n = claim.prescriptions.filter(id__in=ids).update(separation_reviewed=reviewed)
        return Response({'updated': n, 'reviewed': reviewed})

    @action(detail=True, methods=['post'], url_path='apply-review-decision')
    def apply_review_decision(self, request, pk=None):
        """Set one dual-origin item's category FOR THIS MOTALBA (audited, revertible).

        Body: { item_code: str, category: 'local'|'imported'|'tarsia' }
        """
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        item_code = (request.data.get('item_code') or '').strip()
        category  = (request.data.get('category') or '').strip()
        if not item_code or not category:
            return Response({'error': 'مطلوب كود الصنف والتصنيف'}, status=status.HTTP_400_BAD_REQUEST)
        from .discrepancy import apply_review_decision
        staff = getattr(request.user, 'staff_profile', None)
        result = apply_review_decision(claim, item_code, category, user=staff)
        if result.get('error'):
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        record_audit(claim, 'apply_review', actor=staff,
                     summary=f'تصنيف صنف مزدوج {item_code} → {category}: {result.get("lines_updated",0)} بند · '
                             f'الصافى {result.get("net_before")} → {result.get("net_after")}',
                     target_type='item', target_ref=item_code,
                     before={'net': result.get('net_before')}, after={'net': result.get('net_after')})
        return Response(result)

    @action(detail=True, methods=['get'], url_path='apply-history')
    def apply_history(self, request, pk=None):
        """List apply-current-master runs for this claim (most recent first)."""
        claim = self.get_object()
        runs = claim.apply_runs.select_related('applied_by', 'reverted_by').all()
        data = [{
            'id':                    r.pk,
            'applied_at':            r.applied_at.isoformat(),
            'applied_by':            str(r.applied_by) if r.applied_by else None,
            'apply_price':           r.apply_price,
            'apply_category':        r.apply_category,
            'scoped':                r.scope_line_ids is not None,
            'scope_count':           len(r.scope_line_ids) if r.scope_line_ids else 0,
            'lines_updated':         r.lines_updated,
            'prescriptions_updated': r.prescriptions_updated,
            'net_before':            float(r.net_before),
            'net_after':             float(r.net_after),
            'net_delta':             float(r.net_after - r.net_before),
            'reverted':              r.reverted,
            'reverted_at':           r.reverted_at.isoformat() if r.reverted_at else None,
            'reverted_by':           str(r.reverted_by) if r.reverted_by else None,
        } for r in runs]
        return Response(data)

    @action(detail=True, methods=['post'], url_path='apply-runs/(?P<run_id>[0-9]+)/revert')
    def revert_apply(self, request, pk=None, run_id=None):
        """Undo a specific apply-current-master run — restores pre-apply values."""
        claim = self.get_object()
        locked = self._locked_response(claim)
        if locked:
            return locked
        try:
            run = claim.apply_runs.get(pk=run_id)
        except Exception:
            return Response({'error': 'العملية غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        from .discrepancy import revert_apply_run
        staff = getattr(request.user, 'staff_profile', None)
        result = revert_apply_run(run, user=staff)
        if result.get('error'):
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        record_audit(claim, 'revert_apply', actor=staff,
                     summary=f'تراجع عن تطبيق #{run_id}: {result.get("lines_restored",0)} بند · '
                             f'الصافى {result.get("net_before")} → {result.get("net_after")}',
                     target_type='apply_run', target_ref=str(run_id),
                     before={'net': result.get('net_before')}, after={'net': result.get('net_after')})
        return Response(result)

    # ── PIVOT / CROSS-TAB ANALYSIS ─────────────────────────────────────────────
    @action(detail=False, methods=['get'], url_path='pivot-config')
    def pivot_config(self, request):
        """Return whitelisted dimensions + measures for the pivot UI selectors."""
        from .pivot import available_config
        source = request.query_params.get('source', 'prescriptions')
        return Response(available_config(source))

    @action(detail=False, methods=['get'], url_path='pivot')
    def pivot(self, request):
        """
        Generic pivot / cross-tab over claim prescriptions or item lines.

        Query params:
          source       prescriptions | lines      (default: prescriptions)
          row          dimension key               (required)
          col          dimension key               (optional → cross-tab)
          measure      measure key                 (default: net)
          claim_id     filter to one claim         (optional)
          client_id    filter to one insurer       (optional)
          subclient_id filter to one sub-client     (optional)
          date_from / date_to  YYYY-MM-DD          (optional)
        """
        from .pivot import build_pivot, build_pivot_multi
        p = request.query_params
        filters = {
            'claim_id':     p.get('claim_id'),
            'client_id':    p.get('client_id'),
            'subclient_id': p.get('subclient_id'),
            'date_from':    p.get('date_from') or None,
            'date_to':      p.get('date_to') or None,
        }
        flt = {k: v for k, v in filters.items() if v}
        source  = p.get('source', 'prescriptions')
        measure = p.get('measure', 'net')
        # Multi-dimension mode when the client sends comma-separated `rows`/`cols`
        rows_raw = p.get('rows')
        cols_raw = p.get('cols')
        try:
            if rows_raw is not None or cols_raw is not None:
                rows = [x for x in (rows_raw or '').split(',') if x]
                cols = [x for x in (cols_raw or '').split(',') if x]
                result = build_pivot_multi(source=source, rows=rows, cols=cols,
                                           measure=measure, filters=flt)
                result['multi'] = True
            else:
                result = build_pivot(source=source, row=p.get('row'),
                                     col=p.get('col') or None, measure=measure, filters=flt)
                result['multi'] = False
            return Response(result)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='pivot-export')
    def pivot_export(self, request):
        """Export the same pivot/cross-tab as a styled Excel file (single or multi-dim)."""
        from .pivot import build_pivot, build_pivot_multi
        from .export import generate_pivot_excel
        p = request.query_params
        filters = {
            'claim_id':     p.get('claim_id'),
            'client_id':    p.get('client_id'),
            'subclient_id': p.get('subclient_id'),
            'date_from':    p.get('date_from') or None,
            'date_to':      p.get('date_to') or None,
        }
        flt = {k: v for k, v in filters.items() if v}
        source  = p.get('source', 'prescriptions')
        measure = p.get('measure', 'net')
        rows_raw = p.get('rows')
        cols_raw = p.get('cols')
        try:
            if rows_raw is not None or cols_raw is not None:
                rows = [x for x in (rows_raw or '').split(',') if x]
                cols = [x for x in (cols_raw or '').split(',') if x]
                result = build_pivot_multi(source=source, rows=rows, cols=cols,
                                           measure=measure, filters=flt)
                parts = [d['label'] for d in result['row_dims']]
                if result['col_dims']:
                    parts.append('×_' + '_'.join(d['label'] for d in result['col_dims']))
                title = 'تحليل_' + '_'.join(parts) + f"_{result['measure_label']}"
            else:
                result = build_pivot(source=source, row=p.get('row'),
                                     col=p.get('col') or None, measure=measure, filters=flt)
                title = f"تحليل_{result['row_label']}"
                if result.get('col_label'):
                    title += f"_×_{result['col_label']}"
                title += f"_{result['measure_label']}"
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return generate_pivot_excel(result, title=title)


# ═══════════════════════════════════════════════════════════════════════════════
# CACHE SYNC — Manual trigger
# ═══════════════════════════════════════════════════════════════════════════════

from rest_framework.views import APIView


class InsuranceCacheSyncView(APIView):
    """
    POST /api/insurance/sync-cache/
    Trigger an on-demand sync of motalba + companiesitems caches.
    Returns sync stats.
    """
    permission_classes = [InsuranceModuleAccess]

    def post(self, request):
        from .sync import sync_insurance_cache
        try:
            result = sync_insurance_cache()
            return Response(result, status=status.HTTP_200_OK)
        except Exception as exc:
            return Response({'status': 'error', 'error': public_error(request, exc)},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request):
        """Return cache stats (row counts + last synced date)."""
        from .models import MotalbaCache, CompaniesItemsCache
        from django.db.models import Max, Count
        m_stats = MotalbaCache.objects.aggregate(rows=Count('id'), latest=Max('synced_at'))
        c_stats = CompaniesItemsCache.objects.aggregate(rows=Count('id'), latest=Max('synced_at'))
        return Response({
            'motalba':        {'rows': m_stats['rows'], 'last_synced': m_stats['latest']},
            'companiesitems': {'rows': c_stats['rows'], 'last_synced': c_stats['latest']},
        })


# ═══════════════════════════════════════════════════════════════════════════════
# PARENT CLIENT — عميل أب
# ═══════════════════════════════════════════════════════════════════════════════

from rest_framework import serializers as drf_serializers


class InsuranceExportProfileViewSet(viewsets.ModelViewSet):
    """CRUD for print/export profiles (تخصيص طباعة المطالبات)."""
    permission_classes = [InsuranceModuleAccess]
    from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        from .models import InsuranceExportProfile
        qs = InsuranceExportProfile.objects.select_related('subclient').all()
        sub = self.request.query_params.get('subclient_id')
        if sub:
            qs = qs.filter(subclient_id=sub)
        return qs

    def get_serializer_class(self):
        from .serializers import InsuranceExportProfileSerializer
        return InsuranceExportProfileSerializer


class InsurancePivotTemplateViewSet(viewsets.ModelViewSet):
    """CRUD for saved pivot/analysis templates."""
    permission_classes = [InsuranceModuleAccess]

    def get_queryset(self):
        from .models import InsurancePivotTemplate
        return InsurancePivotTemplate.objects.all()

    def get_serializer_class(self):
        from .models import InsurancePivotTemplate

        class _Serializer(drf_serializers.ModelSerializer):
            class Meta:
                model = InsurancePivotTemplate
                fields = ['id', 'name', 'source', 'row_dim', 'col_dim',
                          'measure', 'is_shared', 'created_at']
        return _Serializer

    def perform_create(self, serializer):
        serializer.save(created_by=getattr(self.request.user, 'staff_profile', None))


class InsuranceItemClassificationOverrideViewSet(viewsets.ModelViewSet):
    """
    CRUD for item-classification corrections (تصويبات تصنيف الأصناف).

    Fixes items wrongly defined as مستورد/محلى in the catalog master so they get
    the correct discount before the motalba is issued.  Global by item code.
    """
    permission_classes = [InsuranceModuleAccess]

    def get_queryset(self):
        from .models import InsuranceItemClassificationOverride
        qs = InsuranceItemClassificationOverride.objects.select_related('created_by').all()
        q = self.request.query_params.get('search')
        if q:
            qs = qs.filter(Q(item_code__icontains=q) | wq(q, 'item_name'))
        active = self.request.query_params.get('active')
        if active in ('true', '1'):
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_class(self):
        from .serializers import InsuranceItemClassificationOverrideSerializer
        return InsuranceItemClassificationOverrideSerializer

    def _fill_item_name(self, serializer):
        """Auto-fill item_name from the catalog if the user left it blank."""
        code = (serializer.validated_data.get('item_code') or '').strip()
        if code and not (serializer.validated_data.get('item_name') or '').strip():
            try:
                from apps.catalog.models import Item
                item = Item.objects.filter(softech_id=code).only('name').first()
                if item:
                    serializer.validated_data['item_name'] = item.name
            except Exception:
                logger.debug('item_name auto-fill failed for code %s', code, exc_info=True)

    def perform_create(self, serializer):
        self._fill_item_name(serializer)
        serializer.save(created_by=getattr(self.request.user, 'staff_profile', None))

    def perform_update(self, serializer):
        self._fill_item_name(serializer)
        serializer.save()

    @action(detail=False, methods=['get'], url_path='catalog-lookup')
    def catalog_lookup(self, request):
        """Look up an item code in the catalog: name + CURRENT (master) classification."""
        code = (request.query_params.get('code') or '').strip()
        if not code:
            return Response({'error': 'مطلوب كود الصنف'}, status=status.HTTP_400_BAD_REQUEST)
        from apps.catalog.models import Item
        from .classifier import classify_item, load_classification_overrides
        item = Item.objects.filter(softech_id=code).only(
            'softech_id', 'name', 'is_imported', 'store_classif', 'pack_price').first()
        if not item:
            return Response({'found': False, 'item_code': code})
        current = classify_item(
            imported_origin='1' if item.is_imported else '0',
            store_classif=item.store_classif, item_code=code,
            overrides=load_classification_overrides(),
        )
        return Response({
            'found':            True,
            'item_code':        code,
            'item_name':        item.name,
            'is_imported':      item.is_imported,
            'current_category': current,
            'pack_price':       float(item.pack_price or 0),
        })

    @action(detail=True, methods=['get'], url_path='affected-claims')
    def affected_claims(self, request, pk=None):
        """List non-issued claims whose frozen lines contain this item (candidates to fix)."""
        from .models import (
            InsuranceClaimLine, InsuranceClaim, InsuranceItemClassificationOverride,
        )
        ov = self.get_object()
        rows = (InsuranceClaimLine.objects
                .filter(softech_itemcode=ov.item_code)
                .exclude(prescription__claim__status__in=[
                    InsuranceClaim.STATUS_PAID, InsuranceClaim.STATUS_CANCELLED])
                .values('prescription__claim_id',
                        'prescription__claim__claim_number',
                        'prescription__claim__status')
                .annotate(lines=Count('id')))
        agg = {}
        for r in rows:
            cid = r['prescription__claim_id']
            if cid not in agg:
                agg[cid] = {
                    'claim_id':     cid,
                    'claim_number': r['prescription__claim__claim_number'],
                    'status':       r['prescription__claim__status'],
                    'lines':        0,
                }
            agg[cid]['lines'] += r['lines']
        return Response(sorted(agg.values(), key=lambda x: x['claim_number']))


class InsuranceSeparationListViewSet(viewsets.ModelViewSet):
    """
    CRUD for name separation lists (قوائم فصل الأسماء) + their names.

    A list holds employee/patient names that must be pulled out of the motalbas
    they appear in and billed separately (e.g. شركة الخدمات الطبية).
    """
    permission_classes = [InsuranceModuleAccess]

    def get_queryset(self):
        from .models import InsuranceSeparationList
        return InsuranceSeparationList.objects.prefetch_related('names').order_by('label')

    def get_serializer_class(self):
        from .serializers import InsuranceSeparationListSerializer
        return InsuranceSeparationListSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=getattr(self.request.user, 'staff_profile', None))

    @action(detail=True, methods=['get', 'post'], url_path='names')
    def names(self, request, pk=None):
        """GET = list names; POST = bulk-add names (one per line in `names_text`, or `names` list)."""
        from .models import InsuranceSeparationName
        from .serializers import InsuranceSeparationNameSerializer
        sep = self.get_object()
        if request.method == 'GET':
            return Response(InsuranceSeparationNameSerializer(
                sep.names.all().order_by('name'), many=True).data)
        raw = request.data.get('names_text') or ''
        items = request.data.get('names') or [l.strip() for l in raw.splitlines()]
        added, skipped = 0, 0
        for nm in items:
            nm = (nm or '').strip()
            if not nm:
                continue
            _, created = InsuranceSeparationName.objects.get_or_create(sep_list=sep, name=nm)
            added += 1 if created else 0
            skipped += 0 if created else 1
        return Response({'added': added, 'skipped': skipped,
                         'total': sep.names.filter(is_active=True).count()})

    @action(detail=True, methods=['patch', 'delete'], url_path='names/(?P<name_id>[0-9]+)')
    def name_detail(self, request, pk=None, name_id=None):
        """PATCH = rename / toggle a name; DELETE = remove it."""
        from .models import InsuranceSeparationName
        from .serializers import InsuranceSeparationNameSerializer
        if request.method == 'DELETE':
            InsuranceSeparationName.objects.filter(pk=name_id, sep_list_id=pk).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            obj = InsuranceSeparationName.objects.get(pk=name_id, sep_list_id=pk)
        except InsuranceSeparationName.DoesNotExist:
            return Response({'error': 'الاسم غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        if 'name' in request.data:
            new_name = (request.data.get('name') or '').strip()
            if not new_name:
                return Response({'error': 'الاسم مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
            obj.name = new_name
        if 'is_active' in request.data:
            obj.is_active = bool(request.data['is_active'])
        obj.save()   # re-normalizes via model.save()
        return Response(InsuranceSeparationNameSerializer(obj).data)

    @action(detail=True, methods=['post'], url_path='move-names')
    def move_names(self, request, pk=None):
        """Move names to another list. Body: { name_ids: [...], target_list_id }."""
        from .models import InsuranceSeparationName, InsuranceSeparationList
        target_id = request.data.get('target_list_id')
        ids = request.data.get('name_ids', [])
        if not target_id or not ids:
            return Response({'error': 'target_list_id و name_ids مطلوبان'}, status=status.HTTP_400_BAD_REQUEST)
        if not InsuranceSeparationList.objects.filter(pk=target_id).exists():
            return Response({'error': 'القائمة الهدف غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
        n = InsuranceSeparationName.objects.filter(pk__in=ids, sep_list_id=pk).update(sep_list_id=target_id)
        return Response({'moved': n})


class InsuranceParentClientViewSet(viewsets.ModelViewSet):
    """CRUD for parent clients (عملاء آباء)."""
    permission_classes = [InsuranceModuleAccess]

    class _Serializer(drf_serializers.ModelSerializer):
        clients_count = drf_serializers.SerializerMethodField()

        def get_clients_count(self, obj):
            return obj.clients.count()

        class Meta:
            from .models import InsuranceParentClient
            model  = InsuranceParentClient
            fields = ['id', 'name', 'name_short', 'softech_personcode',
                      'notes', 'is_active', 'clients_count', 'created_at']

    def get_serializer_class(self):
        return self._Serializer

    def get_queryset(self):
        from .models import InsuranceParentClient
        return InsuranceParentClient.objects.prefetch_related('clients').order_by('name')


# ═══════════════════════════════════════════════════════════════════════════════
# BILLING GROUPS — تقسيم المطالبة
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceClaimBillingGroupViewSet(viewsets.ModelViewSet):
    """
    CRUD for billing groups + prescription assignment.

    List/create:  /api/insurance/claims/{claim_id}/billing-groups/
    Detail:       /api/insurance/billing-groups/{id}/
    Auto-assign:  POST /api/insurance/billing-groups/{id}/auto-assign/
    Assign rx:    POST /api/insurance/billing-groups/{id}/assign-rx/
    Export group: GET  /api/insurance/billing-groups/{id}/export/
    """
    permission_classes = [InsuranceModuleAccess]

    class _Serializer(drf_serializers.ModelSerializer):
        class Meta:
            from .models import InsuranceClaimBillingGroup
            model  = InsuranceClaimBillingGroup
            fields = [
                'id', 'claim', 'code', 'name', 'description',
                'filter_relative_degree', 'filter_dept_name',
                'filter_hi_type_code', 'filter_patient_no_prefix',
                'rx_count', 'gross_before', 'total_discount', 'net_after',
                'sort_order', 'created_at',
            ]
            read_only_fields = ['rx_count', 'gross_before', 'total_discount', 'net_after']

    def get_serializer_class(self):
        return self._Serializer

    def get_queryset(self):
        from .models import InsuranceClaimBillingGroup
        qs = InsuranceClaimBillingGroup.objects.select_related('claim')
        claim_id = self.kwargs.get('claim_pk') or self.request.query_params.get('claim_id')
        if claim_id:
            qs = qs.filter(claim_id=claim_id)
        return qs.order_by('sort_order', 'code')

    @staticmethod
    def _group_locked(group):
        """423 if the group's claim is locked (submitted/…); else None."""
        if group.claim.is_locked:
            return Response(
                {'error': 'المطالبة مقفلة (مُقدَّمة/مدفوعة) — لا يمكن تعديل فئات الفوترة.',
                 'locked': True, 'status': group.claim.status},
                status=status.HTTP_423_LOCKED)
        return None

    @action(detail=True, methods=['post'], url_path='auto-assign')
    def auto_assign(self, request, pk=None):
        """Auto-assign unassigned prescriptions matching filter rules."""
        group = self.get_object()
        locked = self._group_locked(group)
        if locked:
            return locked
        count = group.auto_assign_prescriptions()
        return Response({'assigned': count, 'group': group.name})

    @action(detail=True, methods=['post'], url_path='assign-rx')
    def assign_rx(self, request, pk=None):
        """
        Manually assign prescriptions, manual Rx and/or supplements to this group.
        Body: {"prescription_ids": [...], "manual_rx_ids": [...], "supplement_ids": [...]}
        """
        from .models import InsuranceClaimManualRx, InsuranceClaimSupplement
        group = self.get_object()
        locked = self._group_locked(group)
        if locked:
            return locked
        ids   = request.data.get('prescription_ids', [])
        mids  = request.data.get('manual_rx_ids', [])
        sids  = request.data.get('supplement_ids', [])
        if not ids and not mids and not sids:
            return Response({'error': 'prescription_ids, manual_rx_ids or supplement_ids required'}, status=400)
        updated = 0
        if ids:
            updated += InsuranceClaimPrescription.objects.filter(
                claim=group.claim, id__in=ids).update(billing_group=group)
        if mids:
            updated += InsuranceClaimManualRx.objects.filter(
                claim=group.claim, id__in=mids).update(billing_group=group)
        if sids:
            updated += InsuranceClaimSupplement.objects.filter(
                claim=group.claim, id__in=sids).update(billing_group=group)
        group.refresh_totals()
        return Response({'updated': updated})

    @action(detail=True, methods=['post'], url_path='unassign-rx')
    def unassign_rx(self, request, pk=None):
        """Remove prescriptions / manual Rx / supplements from this group (billing_group=null)."""
        from .models import InsuranceClaimManualRx, InsuranceClaimSupplement
        group = self.get_object()
        locked = self._group_locked(group)
        if locked:
            return locked
        ids   = request.data.get('prescription_ids', [])
        mids  = request.data.get('manual_rx_ids', [])
        sids  = request.data.get('supplement_ids', [])
        unassigned = 0
        # If nothing specified, unassign everything in the group.
        if not ids and not mids and not sids:
            unassigned += InsuranceClaimPrescription.objects.filter(
                claim=group.claim, billing_group=group).update(billing_group=None)
            unassigned += InsuranceClaimManualRx.objects.filter(
                claim=group.claim, billing_group=group).update(billing_group=None)
            unassigned += InsuranceClaimSupplement.objects.filter(
                claim=group.claim, billing_group=group).update(billing_group=None)
        else:
            if ids:
                unassigned += InsuranceClaimPrescription.objects.filter(
                    claim=group.claim, billing_group=group, id__in=ids).update(billing_group=None)
            if mids:
                unassigned += InsuranceClaimManualRx.objects.filter(
                    claim=group.claim, billing_group=group, id__in=mids).update(billing_group=None)
            if sids:
                unassigned += InsuranceClaimSupplement.objects.filter(
                    claim=group.claim, billing_group=group, id__in=sids).update(billing_group=None)
        group.refresh_totals()
        return Response({'unassigned': unassigned})

    @action(detail=True, methods=['get'], url_path='export')
    def export(self, request, pk=None):
        """Export this billing group as a separate Excel invoice."""
        group    = self.get_object()
        template = request.query_params.get('template', 'all')
        from .export import generate_excel
        return generate_excel(group.claim, template=template, billing_group=group)

    @action(detail=False, methods=['post'], url_path='refresh-all')
    def refresh_all(self, request):
        """Recalculate totals for all groups in a claim."""
        claim_id = request.data.get('claim_id')
        if not claim_id:
            return Response({'error': 'claim_id required'}, status=400)
        from .models import InsuranceClaimBillingGroup
        for grp in InsuranceClaimBillingGroup.objects.filter(claim_id=claim_id):
            grp.refresh_totals()
        return Response({'ok': True})
