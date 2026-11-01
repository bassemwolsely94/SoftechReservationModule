"""
«من أين أتصل؟» (whoami) and the admin-only trusted-networks API (security N1, log only).
"""
from django.db import transaction
from django.db.models import Case, IntegerField, Prefetch, Value, When
from rest_framework import mixins, status as http, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from apps.audit.models import AuditLog
from apps.users.permissions import IsAdminRole

from . import devices as dev_api
from .models import Device, DeviceUser, TrustedNetwork
from .network import INTERNAL, request_network
from .serializers import DeviceSerializer, TrustedNetworkSerializer

_AUDITED = ('name', 'cidr', 'kind', 'branch_id', 'is_active', 'notes')


class WhoamiThrottle(SimpleRateThrottle):
    """60/min per client address, signed in or not (the badge calls it on every focus)."""
    scope = 'access_whoami'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([WhoamiThrottle])
def whoami(request):
    access = getattr(request._request, 'access', None)
    net = access.network if access is not None else request_network(request._request)
    site = net.site if net.zone == INTERNAL else None
    branch = site.branch if site is not None and site.branch_id else None
    device = None
    if access is not None and access.user_id is not None and access.device is not None:
        d = access.device
        device = {'status': d.status, 'status_label': dict(Device.STATUS_CHOICES).get(d.status, d.status),
                  'name': d.name}
    return Response({
        'device': device,
        'zone': net.zone,
        'ip': net.ip,
        'label': net.label_ar,
        'site': None if site is None else {
            'name': site.name,
            'kind': site.kind,
            'branch_label': (branch.name_ar or branch.name) if branch else None,
        },
    })


def _snapshot(tn):
    return {f: getattr(tn, f) for f in _AUDITED}


class TrustedNetworkViewSet(viewsets.ModelViewSet):
    serializer_class = TrustedNetworkSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    pagination_class = None
    queryset = TrustedNetwork.objects.select_related('branch').order_by('name', 'id')

    def _audit(self, op, old, new, obj):
        AuditLog.log('trusted_network_changed', user=self.request.user.staff_profile, obj=obj,
                     old_data=old, new_data=new, request=self.request._request, extra={'op': op})

    def perform_create(self, serializer):
        tn = serializer.save(updated_by=self.request.user.staff_profile)
        self._audit('create', None, _snapshot(tn), tn)

    def perform_update(self, serializer):
        old = _snapshot(serializer.instance)
        tn = serializer.save(updated_by=self.request.user.staff_profile)
        self._audit('update', old, _snapshot(tn), tn)

    def perform_destroy(self, instance):
        old = _snapshot(instance)
        # the row is gone after delete(), so log with a stand-in that still has the id and name
        label = TrustedNetwork(pk=instance.pk, name=instance.name, cidr=instance.cidr)
        instance.delete()
        self._audit('delete', old, None, label)


class DeviceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                    viewsets.GenericViewSet):
    """Admin device registry (N2). No create, no delete: a deleted row would revive its tokens
    (unknown device ids count as not revoked), so devices are retired instead."""
    serializer_class = DeviceSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    pagination_class = None
    http_method_names = ['get', 'patch', 'post', 'head', 'options']

    def get_queryset(self):
        from apps.catalog.wildcard import wq
        qs = (Device.objects.select_related('branch', 'owner__user', 'approved_by__user')
              .prefetch_related(Prefetch('device_users',
                                         queryset=DeviceUser.objects.select_related('user__user'))))
        p = self.request.query_params
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('kind'):
            qs = qs.filter(kind=p['kind'])
        if p.get('branch'):
            if not str(p['branch']).isdigit():
                raise ValidationError({'error': 'الفرع غير صحيح'})
            qs = qs.filter(branch_id=int(p['branch']))
        q = (p.get('q') or '').strip()
        if q:
            qs = qs.filter(wq(q, 'name', 'last_ip', 'first_ip', 'last_site',
                              'device_users__user__user__username', 'device_users__user__user__first_name', 'device_users__user__user__last_name',
                              'device_users__user__softech_username')).distinct()
        first = Case(When(status='pending', then=Value(0)), default=Value(1), output_field=IntegerField())
        return qs.order_by(first, '-first_seen', '-id')

    def perform_update(self, serializer):
        before = dev_api.snapshot(serializer.instance)
        device = serializer.save(updated_by=self.request.user.staff_profile)
        AuditLog.log('device_changed', user=self.request.user.staff_profile, obj=device,
                     changes={'before': before, 'after': dev_api.snapshot(device)},
                     request=self.request._request)
        dev_api.invalidate(device)

    def _change(self, request, status, need_note=False):
        device = self.get_object()
        note = str(request.data.get('note') or '').strip()
        if need_note and not note:
            return Response({'error': 'اكتب سبب الحظر'}, status=http.HTTP_400_BAD_REQUEST)
        try:
            dev_api.set_status(device, status, request.user.staff_profile, note, request=request)
        except dev_api.RetiredDevice:
            return Response({'error': dev_api.RETIRED_MESSAGE}, status=http.HTTP_400_BAD_REQUEST)
        device = self.get_queryset().get(pk=device.pk)
        return Response(self.get_serializer(device).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._change(request, 'approved')

    @action(detail=True, methods=['post'])
    def block(self, request, pk=None):
        return self._change(request, 'blocked', need_note=True)

    @action(detail=True, methods=['post'])
    def retire(self, request, pk=None):
        return self._change(request, 'retired')

    @action(detail=False, methods=['post'], url_path='bulk-approve')
    def bulk_approve(self, request):
        ids = request.data.get('ids')
        if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            return Response({'error': 'ids must be a list of numbers'}, status=http.HTTP_400_BAD_REQUEST)
        ids = set(ids)
        note = str(request.data.get('note') or '').strip()
        approved = 0
        with transaction.atomic():
            for device in Device.objects.filter(pk__in=ids, status='pending').select_related('owner'):
                dev_api.set_status(device, 'approved', request.user.staff_profile, note, request=request)
                approved += 1
        return Response({'approved': approved, 'skipped': len(ids) - approved})
