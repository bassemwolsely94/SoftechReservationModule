from django.utils import timezone
from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import QAChecklistTemplate, QAInspection
from .serializers import (
    QAChecklistTemplateSerializer,
    QAInspectionListSerializer, QAInspectionDetailSerializer,
    QAInspectionCreateSerializer,
)

# Roles that see all branches' inspections; others are scoped to their branch.
_ALL_BRANCH_ROLES = {'admin', 'quality_manager', 'supervisor'}


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


class QATemplateListView(generics.ListAPIView):
    """GET /api/qa/templates/ — active checklist templates."""
    permission_classes = [IsAuthenticated]
    serializer_class   = QAChecklistTemplateSerializer
    queryset           = QAChecklistTemplate.objects.filter(is_active=True)


class QAInspectionViewSet(viewsets.ModelViewSet):
    """CRUD + submit for branch QA inspections."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = QAInspection.objects.select_related('template', 'branch', 'inspector__user')
        profile = _profile(self.request)
        if profile and profile.role not in _ALL_BRANCH_ROLES and profile.branch_id:
            qs = qs.filter(branch_id=profile.branch_id)
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
