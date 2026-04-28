from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Branch


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'softech_branch_id', 'code', 'name', 'name_ar',
                  'address', 'phone', 'is_active']
