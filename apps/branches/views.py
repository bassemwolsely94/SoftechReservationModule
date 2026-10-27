"""
apps/branches/views.py

BranchViewSet       — read-only branch list (all authenticated users)
BranchSettingsView  — GET/PATCH settings for a branch (admin only)
"""
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Branch, BranchSettings
from .serializers import BranchSerializer, BranchSettingsSerializer


class BranchViewSet(viewsets.ModelViewSet):
    """
    GET  /api/branches/         → active branches (all authenticated)
    GET  /api/branches/?all=1   → all branches including inactive (admin only)
    PATCH /api/branches/{id}/   → update branch fields (admin only)
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = BranchSerializer
    pagination_class   = None  # Small lookup table — always return full list

    def get_queryset(self):
        show_all = self.request.query_params.get('all') in ('1', 'true', 'True')
        # Admins with ?all=1 → return every branch (including inactive)
        if show_all and self._is_admin():
            return Branch.objects.all().order_by('name')
        # Default: active branches only (used by all other parts of the app)
        return Branch.objects.filter(is_active=True).order_by('name')

    def _is_admin(self):
        profile = getattr(self.request.user, 'staff_profile', None)
        return bool(profile and profile.role == 'admin')

    def get_object(self):
        """
        For admin write/retrieve operations, bypass the is_active filter so
        inactive branches can be found and updated regardless of their state.
        This is necessary because PATCH /branches/{id}/ never sends ?all=1,
        but admins must still be able to reactivate an inactive branch.
        """
        if self._is_admin() and self.action in ('retrieve', 'update', 'partial_update'):
            from django.shortcuts import get_object_or_404
            obj = get_object_or_404(Branch, pk=self.kwargs['pk'])
            self.check_object_permissions(self.request, obj)
            return obj
        return super().get_object()

    def _require_admin(self):
        if not self._is_admin():
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('مخصص للمديرين فقط')

    def update(self, request, *args, **kwargs):
        self._require_admin()
        kwargs['partial'] = True   # always partial — never require full object
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._require_admin()
        return super().partial_update(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        self._require_admin()
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'حذف الفرع غير مسموح'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def branch_settings(request, branch_id):
    """
    GET  /api/branches/{id}/settings/  → current settings
    PATCH /api/branches/{id}/settings/ → update flags (admin only)
    """
    # Permission: only admins may modify
    if request.method == 'PATCH':
        profile = getattr(request.user, 'staff_profile', None)
        if not profile or profile.role != 'admin':
            return Response(
                {'detail': 'مخصص للمديرين فقط'},
                status=status.HTTP_403_FORBIDDEN,
            )

    try:
        branch = Branch.objects.get(pk=branch_id)
    except Branch.DoesNotExist:
        return Response({'detail': 'الفرع غير موجود'}, status=status.HTTP_404_NOT_FOUND)

    settings_obj = BranchSettings.for_branch(branch)

    if request.method == 'PATCH':
        serializer = BranchSettingsSerializer(
            settings_obj, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    return Response(BranchSettingsSerializer(settings_obj).data)
