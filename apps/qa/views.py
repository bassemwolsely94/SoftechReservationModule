from django.utils import timezone
from rest_framework import generics, mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import fridge as fridge_svc
from .models import FridgeReading, FridgeUnit, QAChecklistTemplate, QAInspection
from .serializers import (
    QAChecklistTemplateSerializer,
    QAInspectionListSerializer, QAInspectionDetailSerializer,
    QAInspectionCreateSerializer,
    FridgeReadingSerializer, FridgeUnitSerializer,
)

from core import branch_scope                                     # noqa: E402
from core.permissions import matrix_permission                     # noqa: E402
from core.permissions import RouteModulePermission  # round 2, owner answers 2026-11-05
from apps.users.roles import ROLES

# QA inspections sit in the `hr` module (as the middleware maps /api/qa/) — Batch 4, Z-9c: reads
# need view; writes need a grant beyond view, export included, because the quality manager —
# whose screen this is — holds hr view + export (viewer, view only, could create inspections).
_QA_WRITE = ('create', 'edit', 'approve', 'finalize', 'export')
# Every role holds hr for its own self-service, so the matrix alone let call center, purchasing,
# salesperson, delivery and viewer read (and the first four file) inspections. Only the roles the
# registry marks qa_inspections work them (UAT W2, owner 2026-11-19); the accountant stays out as
# before (owner 2026-11-06). The /m/qa tab shows the same roles.
_QA_EXCLUDED = tuple(r.key for r in ROLES if not r.qa_inspections)
QA = matrix_permission('hr', post=_QA_WRITE, edit=_QA_WRITE, delete=('edit', 'delete'),
                       exclude_roles=_QA_EXCLUDED)


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class QATemplateListView(generics.ListAPIView):
    """GET /api/qa/templates/ — active checklist templates."""
    permission_classes = [IsAuthenticated, QA]
    serializer_class   = QAChecklistTemplateSerializer
    queryset           = QAChecklistTemplate.objects.filter(is_active=True)


class QAInspectionViewSet(viewsets.ModelViewSet):
    """CRUD + submit for branch QA inspections."""
    permission_classes = [IsAuthenticated, QA, RouteModulePermission]

    def get_queryset(self):
        qs = QAInspection.objects.select_related('template', 'branch', 'inspector__user')
        # Batch 5: the one branch helper (all-branch roles see all; a branch role without a branch
        # used to see every branch — fail-closed now)
        qs = branch_scope.scope(qs, self.request.user)
        st = self.request.query_params.get('status')
        branch = self.request.query_params.get('branch')
        if st:
            qs = qs.filter(status=st)
        if branch:
            qs = qs.filter(branch_id=branch)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return QAInspectionListSerializer
        if self.action == 'create':
            return QAInspectionCreateSerializer
        return QAInspectionDetailSerializer

    def perform_create(self, serializer):
        branch_scope.check_branch_value(self.request.user, serializer)
        template = serializer.validated_data['template']
        # Pre-fill the results scaffold from the template items (unanswered).
        results = [
            {'key': it.get('key', str(i)), 'label': it.get('label', ''), 'result': '', 'note': ''}
            for i, it in enumerate(template.items or [])
        ]
        serializer.save(inspector=_profile(self.request), results=results, status='draft')

    def create(self, request, *args, **kwargs):
        # Return the FULL inspection (id + prefilled results) so the client can
        # navigate straight into the detail/fill screen — the create serializer
        # only declares template/branch.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            QAInspectionDetailSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        inspection = self.get_object()
        if inspection.status != 'draft':
            return Response({'detail': 'لا يمكن تعديل مراجعة مُرسَلة'}, status=status.HTTP_400_BAD_REQUEST)
        # Only results + notes are editable (PATCH).
        results = request.data.get('results')
        if results is not None:
            inspection.results = results
        if 'notes' in request.data:
            inspection.notes = request.data.get('notes', '')
        inspection.save(update_fields=['results', 'notes'])
        return Response(QAInspectionDetailSerializer(inspection).data)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        inspection = self.get_object()
        if inspection.status == 'submitted':
            return Response({'detail': 'المراجعة مُرسَلة بالفعل'}, status=status.HTTP_400_BAD_REQUEST)
        if 'results' in request.data:
            inspection.results = request.data['results']
        if 'notes' in request.data:
            inspection.notes = request.data.get('notes', '')
        inspection.score        = inspection.compute_score()
        inspection.status       = 'submitted'
        inspection.submitted_at = timezone.now()
        inspection.save(update_fields=['results', 'notes', 'score', 'status', 'submitted_at'])
        return Response(QAInspectionDetailSerializer(inspection).data)


# ── C31: fridge temperature log (P-53) ─────────────────────────────────────────────────────────
# Same gate as the inspections (QA: hr matrix, roles marked qa_inspections). A fridge's allowed range
# is set when it is registered and cannot be changed through the API (an admin-site change only),
# so a reading's in/out-of-range verdict cannot be rewritten afterwards. Readings are append-only.



class FridgeUnitViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                        mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """GET/POST /api/qa/fridges/, PATCH name / is_active. No delete (readings point at it)."""
    permission_classes = [IsAuthenticated, QA, RouteModulePermission]
    serializer_class = FridgeUnitSerializer

    def get_queryset(self):
        qs = branch_scope.scope(FridgeUnit.objects.select_related('branch'), self.request.user)
        branch = self.request.query_params.get('branch')
        if branch:
            qs = qs.filter(branch_id=branch)
        if self.request.query_params.get('active') == '1':
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        branch_scope.check_branch_value(self.request.user, serializer)
        serializer.save(created_by=_profile(self.request))

    def perform_update(self, serializer):
        if {'min_c', 'max_c', 'branch'} & set(self.request.data):
            raise ValidationError({'detail': 'نطاق الحرارة والفرع بيتحددوا عند التسجيل بس'})
        serializer.save()

    @action(detail=True, methods=['get'])
    def month(self, request, pk=None):
        """GET /api/qa/fridges/{id}/month/?month=YYYY-MM — the printable month sheet."""
        f = self.get_object()
        raw = request.query_params.get('month') or timezone.localdate().strftime('%Y-%m')
        try:
            year, mon = (int(x) for x in raw.split('-'))
            if not 1 <= mon <= 12 or not 2020 <= year <= 2100:
                raise ValueError
        except ValueError:
            return Response({'detail': 'الشهر لازم يكون YYYY-MM'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(fridge_svc.month_sheet(f, year, mon))


class FridgeReadingViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """GET/POST /api/qa/fridge-readings/ — append-only: no edit, no delete."""
    permission_classes = [IsAuthenticated, QA, RouteModulePermission]
    serializer_class = FridgeReadingSerializer

    def get_queryset(self):
        qs = branch_scope.scope(FridgeReading.objects.select_related('fridge', 'recorded_by'),
                                self.request.user, 'fridge__branch')
        p = self.request.query_params
        if p.get('fridge'):
            qs = qs.filter(fridge_id=p['fridge'])
        if p.get('day'):
            qs = qs.filter(day=p['day'])
        return qs.order_by('-day', '-slot')

    def perform_create(self, serializer):
        f = serializer.validated_data['fridge']
        if not branch_scope.allows(self.request.user, f.branch_id):
            raise PermissionDenied('لا يمكنك التسجيل على فرع خارج فروعك.')
        reading = FridgeReading(**serializer.validated_data, recorded_by=_profile(self.request))
        reading.out_of_range = reading.compute_out_of_range()
        reading.save()
        serializer.instance = reading
        if reading.out_of_range:
            fridge_svc.notify_out_of_range(reading)
