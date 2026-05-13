from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Branch
from .serializers import BranchSerializer


class BranchViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = BranchSerializer
    queryset = Branch.objects.filter(is_active=True).order_by('name')
    pagination_class = None  # Always return the full list — branches are a small lookup table
