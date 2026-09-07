"""
apps/loyalty/views.py
"""
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.loyalty.models import (
    LoyaltyAccount, LoyaltyTier, PointTransaction,
    RewardCatalog, RedemptionRequest, SoftechPointsLog,
)
from apps.loyalty.serializers import (
    LoyaltyAccountSerializer, LoyaltyTierSerializer,
    PointTransactionSerializer, RewardCatalogSerializer,
    RedemptionRequestSerializer, SoftechPointsLogSerializer,
)


class TierListView(generics.ListAPIView):
    serializer_class   = LoyaltyTierSerializer
    permission_classes = [IsAuthenticated]
    queryset           = LoyaltyTier.objects.order_by('order')


class AccountDetailView(generics.RetrieveAPIView):
    serializer_class   = LoyaltyAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        customer_id = self.kwargs['customer_id']
        account, _ = LoyaltyAccount.objects.get_or_create(
            customer_id=customer_id,
        )
        return account


class TransactionListView(generics.ListAPIView):
    serializer_class   = PointTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PointTransaction.objects.filter(
            account__customer_id=self.kwargs['customer_id']
        ).order_by('-created_at')[:100]


class AdjustPointsView(APIView):
    """
    Call-centre endpoint: adjust points for a customer.

    Two lanes depending on `adjust_type`:

    adjust_type = 'purchase'  (default)
        → Customer must be enrolled in SOFTECH purchase-points (picpoints=1)
        → INSERTs into SOFTECH picpoints table → tr_picpoints trigger fires
        → Updates softech_points_balance cache
        → Records SoftechPointsLog

    adjust_type = 'referral'
        → Available to ALL customers regardless of SOFTECH enrollment flag
        → Writes Django PointTransaction (IncentiveTransaction lane)
        → Updates points_balance / points_lifetime
        → Call centre redeems these as vouchers via the normal redemption flow

    POST {
        points:       int,
        reason:       str,
        adjust_type:  'purchase' | 'referral'   (default: 'purchase')
    }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, customer_id):
        from apps.loyalty.pic_bridge import (
            adjust_softech_points,
            is_softech_points_enrolled,
        )

        delta       = request.data.get('points')
        reason      = request.data.get('reason', '').strip()
        adjust_type = request.data.get('adjust_type', 'purchase').strip().lower()

        if adjust_type not in ('purchase', 'referral'):
            return Response(
                {'detail': "adjust_type يجب أن يكون 'purchase' أو 'referral'"},
                status=400,
            )

        if delta is None:
            return Response({'detail': 'points مطلوب'}, status=400)
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            return Response({'detail': 'points يجب أن يكون رقماً صحيحاً'}, status=400)
        if delta == 0:
            return Response({'detail': 'التغيير يجب أن يكون غير صفري'}, status=400)

        account, _ = LoyaltyAccount.objects.get_or_create(customer_id=customer_id)
        try:
            account = LoyaltyAccount.objects.select_related('customer').get(
                customer_id=customer_id
            )
        except LoyaltyAccount.DoesNotExist:
            return Response({'detail': 'الحساب غير موجود'}, status=404)

        customer = account.customer
        try:
            staff = request.user.staff_profile
        except Exception:
            staff = None
        operator = staff.user.username if staff and staff.user_id else 'CRM'

        # ── Lane A: referral points — Django only, no SOFTECH required ────────
        if adjust_type == 'referral':
            tx = account.add_points(
                points      = delta,
                reason      = reason or 'إحالة عميل',
                source_type = 'referral',
                notes       = f'تعديل يدوي من مركز الاتصال — المشغّل: {operator}',
            )
            return Response({
                'adjust_type':    'referral',
                'crm_points_balance': account.points_balance,
                'delta':          delta,
                'reason':         reason,
                'transaction_id': tx.pk,
            })

        # ── Lane B: purchase points — must go through SOFTECH ─────────────────
        softech_pic = customer.softech_pic
        if not softech_pic:
            return Response(
                {'detail': 'العميل لا يملك كود PIC — لا يمكن تعديل نقاط الشراء.'
                           ' استخدم adjust_type=referral لنقاط الإحالة.'},
                status=400,
            )

        enrolled = is_softech_points_enrolled(softech_pic)
        if not enrolled:
            return Response(
                {
                    'detail': (
                        'العميل غير مسجّل في برنامج نقاط SOFTECH (picpoints=0). '
                        'لا يمكن تعديل نقاط الشراء. '
                        'استخدم adjust_type=referral لمنح نقاط إحالة بدلاً من ذلك.'
                    ),
                    'enrolled': False,
                    'hint': 'adjust_type=referral',
                },
                status=400,
            )

        balance_before = account.softech_points_balance
        success        = True
        error_message  = ''
        balance_after  = balance_before

        try:
            balance_after = adjust_softech_points(
                softech_pic, delta, reason=reason, operator=operator
            )
        except Exception as exc:
            success       = False
            error_message = str(exc)

        # Immutable audit log for every SOFTECH write attempt
        SoftechPointsLog.objects.create(
            customer       = customer,
            softech_pic    = softech_pic,
            delta          = delta,
            reason         = reason,
            balance_before = balance_before,
            balance_after  = balance_after,
            success        = success,
            error_message  = error_message,
            created_by     = staff,
        )

        if not success:
            return Response({'detail': error_message}, status=502)

        account.softech_points_balance = balance_after
        account.save(update_fields=['softech_points_balance', 'updated_at'])

        return Response({
            'adjust_type':           'purchase',
            'softech_points_balance': balance_after,
            'delta':                 delta,
            'reason':                reason,
            'enrolled':              True,
        })


class SoftechBalanceView(APIView):
    """
    Branch staff endpoint: look up current SOFTECH points balance for a walk-in customer.

    GET /loyalty/customers/{id}/softech-balance/
        → reads live from SOFTECH (fresh, not cached)
        → updates softech_points_balance in Django
        → returns { softech_points_balance, softech_pic, customer_name }

    Used by branch staff at the counter when a customer asks for their balance.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, customer_id):
        from apps.loyalty.pic_bridge import (
            read_softech_points,
            is_softech_points_enrolled,
        )

        try:
            from apps.customers.models import Customer
            customer = Customer.objects.get(pk=customer_id)
        except Customer.DoesNotExist:
            return Response({'detail': 'العميل غير موجود'}, status=404)

        account, _ = LoyaltyAccount.objects.get_or_create(customer=customer)
        softech_pic = customer.softech_pic

        # CRM referral points — always available regardless of SOFTECH enrollment
        crm_balance = account.points_balance

        if not softech_pic:
            return Response({
                'softech_points_balance': 0,
                'crm_points_balance':     crm_balance,
                'softech_pic':            None,
                'enrolled':               False,
                'customer_name':          customer.name,
                'customer_phone':         customer.phone or '',
                'warning': 'العميل لا يملك كود PIC — نقاط الشراء غير متاحة',
            })

        # Live read from SOFTECH
        live_balance = read_softech_points(softech_pic)
        if live_balance is None:
            live_balance = account.softech_points_balance  # fall back to cached

        enrolled = is_softech_points_enrolled(softech_pic)

        # Update cached value if it changed
        if account.softech_points_balance != live_balance:
            account.softech_points_balance = live_balance
            account.save(update_fields=['softech_points_balance', 'updated_at'])

        return Response({
            'softech_points_balance': live_balance,
            'crm_points_balance':     crm_balance,
            'total_balance':          live_balance + crm_balance,
            'softech_pic':            softech_pic,
            'enrolled':               enrolled,
            'customer_name':          customer.name,
            'customer_phone':         customer.phone or '',
            # UI hint: if not enrolled, show referral points only + suggest referral adjust
            'purchase_points_blocked': not enrolled,
        })


class SoftechLogView(generics.ListAPIView):
    """Call-centre: history of SOFTECH point adjustments for a customer."""
    serializer_class   = SoftechPointsLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            SoftechPointsLog.objects
            .filter(customer_id=self.kwargs['customer_id'])
            .order_by('-created_at')[:50]
        )


class RewardCatalogView(generics.ListAPIView):
    serializer_class   = RewardCatalogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return RewardCatalog.objects.filter(is_active=True).order_by('points_cost')


class RedemptionListView(generics.ListAPIView):
    serializer_class   = RedemptionRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return RedemptionRequest.objects.filter(
            account__customer_id=self.kwargs['customer_id']
        ).order_by('-created_at')


class RedeemRewardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, customer_id):
        reward_id = request.data.get('reward_id')
        notes     = request.data.get('notes', '')

        try:
            account = LoyaltyAccount.objects.get(customer_id=customer_id)
            reward  = RewardCatalog.objects.get(pk=reward_id, is_active=True)
        except (LoyaltyAccount.DoesNotExist, RewardCatalog.DoesNotExist):
            return Response({'detail': 'الحساب أو المكافأة غير موجودة'}, status=404)

        if not reward.is_available:
            return Response({'detail': 'المكافأة غير متاحة حالياً'}, status=400)

        if account.points_balance < reward.points_cost:
            return Response(
                {'detail': f'رصيد غير كافٍ: متاح {account.points_balance} / مطلوب {reward.points_cost}'},
                status=400,
            )

        redemption = RedemptionRequest.objects.create(
            account=account,
            reward=reward,
            points_spent=reward.points_cost,
            notes=notes,
        )
        return Response(RedemptionRequestSerializer(redemption).data, status=201)


class ApproveRedemptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            redemption = RedemptionRequest.objects.get(pk=pk, status='pending')
        except RedemptionRequest.DoesNotExist:
            return Response({'detail': 'الطلب غير موجود أو ليس بانتظار الموافقة'}, status=404)

        try:
            staff = request.user.staff_profile
        except Exception:
            staff = None

        try:
            redemption.approve(by_staff=staff)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)

        return Response(RedemptionRequestSerializer(redemption).data)
