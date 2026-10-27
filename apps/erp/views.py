"""
apps/erp/views.py — Read-only API for ERP transaction layer.

All writes happen through sync/tasks.py, never through the API.
"""
from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import ERPTransaction, LocalCustomer
from .serializers import (
    ERPTransactionSerializer,
    LocalCustomerSerializer,
    LocalCustomerListSerializer,
)


class ERPTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API for ERP transactions.
    Used by: reservation validation, transfer validation, patient profile.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = ERPTransactionSerializer
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['doccode', 'branch', 'phcode']
    search_fields      = ['transaction_id', 'phcode', 'reference_number', 'lines__item_code']
    ordering_fields    = ['transaction_date', 'total_amount']
    ordering           = ['-transaction_date']

    def get_queryset(self):
        return ERPTransaction.objects.select_related(
            'branch', 'local_customer', 'personsdata_customer',
        ).prefetch_related('lines__item')

    @action(detail=False, methods=['get'], url_path='by-phcode')
    def by_phcode(self, request):
        """
        GET /api/erp/transactions/by-phcode/?phcode=140HD515&doccode=115
        Returns all transactions for a customer PIC code.
        """
        phcode  = request.query_params.get('phcode', '').strip()
        doccode = request.query_params.get('doccode', '').strip()

        if not phcode:
            return Response({'detail': 'phcode مطلوب'}, status=400)

        qs = self.get_queryset().filter(phcode=phcode)
        if doccode:
            qs = qs.filter(doccode=doccode)

        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                ERPTransactionSerializer(page, many=True).data
            )
        return Response(ERPTransactionSerializer(qs, many=True).data)

    @action(detail=False, methods=['get'], url_path='validate-sale')
    def validate_sale(self, request):
        """
        GET /api/erp/transactions/validate-sale/?phcode=X&transaction_id=Y
        Used by reservation module to validate a doccode=115 sale.
        Returns: {valid: bool, transaction: {...} | null}
        """
        phcode         = request.query_params.get('phcode', '').strip()
        transaction_id = request.query_params.get('transaction_id', '').strip()

        if not phcode or not transaction_id:
            return Response({'detail': 'phcode و transaction_id مطلوبان'}, status=400)

        tx = ERPTransaction.objects.filter(
            transaction_id=transaction_id,
            phcode=phcode,
            doccode='115',
        ).select_related('branch').prefetch_related('lines__item').first()

        return Response({
            'valid':       bool(tx),
            'transaction': ERPTransactionSerializer(tx).data if tx else None,
        })

    @action(detail=False, methods=['get'], url_path='validate-transfer')
    def validate_transfer(self, request):
        """
        GET /api/erp/transactions/validate-transfer/?transaction_id=X
        Used by transfer module to validate doccodes 25 or 125.
        Returns: {valid: bool, doccode: str, transaction: {...} | null}
        """
        transaction_id = request.query_params.get('transaction_id', '').strip()

        if not transaction_id:
            return Response({'detail': 'transaction_id مطلوب'}, status=400)

        tx = ERPTransaction.objects.filter(
            transaction_id=transaction_id,
            doccode__in=['25', '125'],
        ).select_related('branch').prefetch_related('lines__item').first()

        return Response({
            'valid':       bool(tx),
            'doccode':     tx.doccode if tx else None,
            'transaction': ERPTransactionSerializer(tx).data if tx else None,
        })


class LocalCustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API for PIC/delivery customers from localcustomers.
    """
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['is_active', 'customer_type', 'branch']
    search_fields      = ['phcode', 'name', 'phone', 'phone_alt']
    ordering           = ['name']

    def get_queryset(self):
        return LocalCustomer.objects.select_related('branch', 'linked_customer')

    def get_serializer_class(self):
        if self.action == 'list':
            return LocalCustomerListSerializer
        return LocalCustomerSerializer

    @action(detail=False, methods=['get'], url_path='lookup')
    def lookup(self, request):
        """
        GET /api/erp/local-customers/lookup/?phone=01012345678
        GET /api/erp/local-customers/lookup/?phcode=140HD515
        Fast lookup for demand + reservation modules.
        """
        phone  = request.query_params.get('phone', '').strip()
        phcode = request.query_params.get('phcode', '').strip()

        if phcode:
            lc = LocalCustomer.objects.filter(phcode=phcode).select_related(
                'branch', 'linked_customer'
            ).first()
        elif phone:
            tail = phone.replace(' ', '')[-9:]
            lc = LocalCustomer.objects.filter(
                phone__endswith=tail
            ).select_related('branch', 'linked_customer').first()
        else:
            return Response({'detail': 'phone أو phcode مطلوب'}, status=400)

        return Response({
            'found':    bool(lc),
            'customer': LocalCustomerSerializer(lc).data if lc else None,
        })
