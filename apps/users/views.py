from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from .models import StaffProfile


class StaffProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    full_name = serializers.CharField(read_only=True)
    branch_name = serializers.CharField(read_only=True)
    branch_id = serializers.IntegerField(source='branch.id', read_only=True)

    class Meta:
        model = StaffProfile
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'full_name',
                  'role', 'branch_id', 'branch_name', 'softech_username', 'phone']


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get('username')
    password = request.data.get('password')

    user = authenticate(username=username, password=password)
    if not user:
        return Response({'error': 'بيانات الدخول غير صحيحة'}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.is_active:
        return Response({'error': 'الحساب غير مفعل'}, status=status.HTTP_403_FORBIDDEN)

    refresh = RefreshToken.for_user(user)
    profile = getattr(user, 'staff_profile', None)

    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': StaffProfileSerializer(profile).data if profile else {
            'username': user.username,
            'role': 'admin' if user.is_superuser else 'viewer',
        }
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_view(request):
    from rest_framework_simplejwt.views import TokenRefreshView
    return TokenRefreshView.as_view()(request._request)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    profile = getattr(request.user, 'staff_profile', None)
    if profile:
        return Response(StaffProfileSerializer(profile).data)
    return Response({
        'username': request.user.username,
        'role': 'admin' if request.user.is_superuser else 'viewer',
    })
