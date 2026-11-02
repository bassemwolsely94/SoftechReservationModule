"""
«من أين أتصل؟» (whoami) and the admin-only trusted-networks API (security N1, log only).
"""
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from apps.audit.models import AuditLog
from apps.users.permissions import IsAdminRole

from .models import TrustedNetwork
from .network import INTERNAL, request_network
from .serializers import TrustedNetworkSerializer

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
    return Response({
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
