"""
API for SOFTECH permission inheritance (Stages B–D).

  GET  erp-permissions/me/        → caller's effective inherited module perms
  GET  erp-permissions/groups/    → derived perms for every SOFTECH group (review)
  GET  erp-permissions/systems/   → SOFTECH systems + screen counts (mapping aid)
  GET  erp-permissions/map/       → current system→module map
  POST erp-permissions/map/       → add a mapping {system, module, note}
  DEL  erp-permissions/map/<id>/  → remove a mapping
  POST erp-permissions/rebuild/   → re-seed (optional) + re-derive
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response

from .models import (
    ErpUserGroup, ErpScreen, SoftechSystemMap, ErpGroupModulePermission,
)
from .erp_permissions import (
    user_module_permissions, user_erp_group, derive_group_permissions, seed_system_map,
)


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        try:
            return request.user.staff_profile.role == 'admin'
        except Exception:
            return False


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_erp_permissions(request):
    """Caller's effective inherited permissions + their SOFTECH group."""
    grp = user_erp_group(request.user)
    return Response({
        'erp_group': {'usergroup': grp.usergroup, 'name': grp.name} if grp else None,
        'permissions': user_module_permissions(request.user),
    })


@api_view(['GET'])
@permission_classes([IsAdmin])
def groups_overview(request):
    """Derived module permissions for every SOFTECH group (for review)."""
    out = []
    for g in ErpUserGroup.objects.all().order_by('usergroup'):
        mods = {}
        for p in ErpGroupModulePermission.objects.filter(group=g):
            mods[p.module] = {
                'view': p.can_view, 'create': p.can_create, 'edit': p.can_edit,
                'delete': p.can_delete, 'export': p.can_export,
                'see_cost': p.can_see_cost, 'screens': p.screens_count,
            }
        out.append({'usergroup': g.usergroup, 'name': g.name,
                    'is_blocked': g.is_blocked, 'modules': mods})
    return Response(out)


@api_view(['GET'])
@permission_classes([IsAdmin])
def systems_overview(request):
    """SOFTECH systems with screen counts + sample names (mapping aid)."""
    from collections import defaultdict
    by_sys = defaultdict(lambda: {'screens': 0, 'sample': ''})
    for s in ErpScreen.objects.all():
        e = by_sys[s.system]
        e['screens'] += 1
        if not e['sample'] and (s.descr_en or s.descr_ar):
            e['sample'] = s.descr_en or s.descr_ar
    rows = [{'system': k, **v} for k, v in sorted(by_sys.items())]
    return Response(rows)


@api_view(['GET', 'POST'])
@permission_classes([IsAdmin])
def system_map(request):
    if request.method == 'POST':
        system = str(request.data.get('system', '')).strip().upper()
        module = str(request.data.get('module', '')).strip()
        note   = str(request.data.get('note', '')).strip()
        if not system or not module:
            return Response({'detail': 'system و module مطلوبان'}, status=400)
        obj, created = SoftechSystemMap.objects.get_or_create(
            system=system, django_module=module, defaults={'note': note})
        if not created:
            obj.note = note or obj.note
            obj.is_active = True
            obj.save()
        derive_group_permissions()  # re-derive immediately
        return Response({'id': obj.id, 'system': obj.system, 'module': obj.django_module,
                         'created': created}, status=201)
    rows = [{'id': m.id, 'system': m.system, 'module': m.django_module,
             'note': m.note, 'is_active': m.is_active}
            for m in SoftechSystemMap.objects.all().order_by('django_module', 'system')]
    return Response(rows)


@api_view(['DELETE'])
@permission_classes([IsAdmin])
def system_map_delete(request, pk):
    SoftechSystemMap.objects.filter(pk=pk).delete()
    derive_group_permissions()
    return Response(status=204)


@api_view(['POST'])
@permission_classes([IsAdmin])
def rebuild(request):
    seeded = seed_system_map(force=bool(request.data.get('reseed')))
    n = derive_group_permissions()
    return Response({'seeded': seeded, 'derived_rows': n})
