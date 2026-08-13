"""
apps/personal/views.py — Personal Dashboard API.

Surface
    persons/search/                 GET   search personsdata to claim an identity
    identities/                     GET   my claims / POST create a claim
    identities/<id>/                DELETE remove my own claim
    identities/pending/             GET   admin: pending review queue
    identities/<id>/review/         POST  admin: approve / reject
    widgets/catalog/                GET   available widget types
    widgets/                        GET my widgets / POST add a widget
    widgets/<id>/                   PATCH update / DELETE remove
    widgets/layout/                 POST  bulk reorder
    widgets/<id>/data/              GET   live (cached) data for a widget

SECURITY: widget data is only ever fetched through resolve_person_key(), which
requires an APPROVED SoftechIdentityClaim OWNED by the caller (supplier/customer
widgets) — a raw personcode is never accepted from the client. Salesperson
widgets fall back to the caller's own StaffProfile.softech_user_id.
"""
from django.core.cache import cache
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import SoftechIdentityClaim, PersonalWidget
from .serializers import IdentityClaimSerializer, PersonalWidgetSerializer
from .providers import WIDGET_REGISTRY, catalog
from . import queries


# ── helpers ───────────────────────────────────────────────────────────────────

def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _is_admin(profile):
    return bool(profile) and getattr(profile, 'role', None) == 'admin'


class PersonalError(Exception):
    def __init__(self, detail, status=400):
        self.detail = detail
        self.status = status


def resolve_person_key(widget: PersonalWidget, profile) -> str:
    """
    Return the AUTHORISED SOFTECH code a widget may read, or raise PersonalError.

    supplier/customer widgets → require an approved, owned claim of the matching
        kind bound to the widget.
    salesperson widgets       → the bound approved salesperson claim's code, else
        the caller's own softech_user_id (self — always allowed).
    """
    meta = WIDGET_REGISTRY.get(widget.widget_type)
    if not meta:
        raise PersonalError('نوع لوحة غير معروف', 400)
    kind = meta['kind']

    if kind == 'self':
        # bound to the requesting staff directly — no SOFTECH code, no claim
        return None

    if kind == 'salesperson':
        ident = widget.identity
        if ident and ident.staff_id == profile.id and ident.kind == 'salesperson' and ident.is_approved:
            return ident.person_code
        usercode = (profile.softech_user_id or '').strip() or (profile.softech_username or '').strip()
        if not usercode:
            raise PersonalError('لا يوجد كود مستخدم SOFTECH مرتبط بحسابك', 409)
        return usercode

    # supplier / customer — an approved owned claim is MANDATORY
    ident = widget.identity
    if not ident:
        raise PersonalError('هذه اللوحة تحتاج هوية مرتبطة', 409)
    if ident.staff_id != profile.id:
        raise PersonalError('غير مصرّح', 403)
    if ident.kind != kind:
        raise PersonalError('نوع الهوية لا يطابق نوع اللوحة', 400)
    if not ident.is_approved:
        raise PersonalError('الهوية لم تُعتمد بعد', 403)
    return ident.person_code


# ══════════════════════════════════════════════════════════════════════════════
# PERSON SEARCH
# ══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def persons_search(request):
    q    = request.query_params.get('q', '')
    kind = request.query_params.get('kind') or None
    if kind and kind not in ('supplier', 'customer'):
        kind = None
    if len((q or '').strip()) < 2:
        return Response({'results': []})
    results = queries.search_persons(q, kind=kind, limit=25)
    if results and results[0].get('_error'):
        return Response({'detail': 'تعذّر البحث في SOFTECH', 'error': results[0]['_error']}, status=502)
    return Response({'results': results})


# ══════════════════════════════════════════════════════════════════════════════
# IDENTITY CLAIMS
# ══════════════════════════════════════════════════════════════════════════════

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def identities(request):
    profile = _profile(request)
    if not profile:
        return Response({'detail': 'لا يوجد ملف موظف'}, status=403)

    if request.method == 'GET':
        qs = SoftechIdentityClaim.objects.filter(staff=profile)
        return Response({'results': IdentityClaimSerializer(qs, many=True).data})

    # POST — create a claim (self-service; starts pending)
    kind = (request.data.get('kind') or '').strip()
    person_code = str(request.data.get('person_code') or '').strip()
    note = (request.data.get('note') or '').strip()
    if kind not in dict(SoftechIdentityClaim.KIND_CHOICES):
        return Response({'detail': 'نوع هوية غير صالح'}, status=400)
    if not person_code:
        return Response({'detail': 'كود SOFTECH مطلوب'}, status=400)

    # Resolve a display label from personsdata only when the client didn't send
    # one (the /me search UI already supplies it). This avoids a live SOFTECH
    # round-trip on the common path — and keeps the endpoint fast/offline-safe.
    label = (request.data.get('label') or '').strip()
    meta = {}
    if not label and kind in ('supplier', 'customer'):
        person = queries.get_person(person_code)
        if person:
            label = person.get('name') or ''
            meta = {'ptcode': person.get('ptcode'), 'ptclassifcode': person.get('ptclassifcode')}

    try:
        claim = SoftechIdentityClaim.objects.create(
            staff=profile, kind=kind, person_code=person_code,
            label=label, note=note, meta=meta,
            status=SoftechIdentityClaim.STATUS_PENDING,
        )
    except IntegrityError:
        return Response({'detail': 'لديك بالفعل طلب/هوية بنفس الكود والنوع'}, status=409)
    return Response(IdentityClaimSerializer(claim).data, status=201)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def identity_detail(request, pk):
    profile = _profile(request)
    claim = get_object_or_404(SoftechIdentityClaim, pk=pk)
    if claim.staff_id != profile.id and not _is_admin(profile):
        return Response({'detail': 'غير مصرّح'}, status=403)
    claim.delete()
    return Response(status=204)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def identities_pending(request):
    """Admin review queue — all pending claims across staff."""
    profile = _profile(request)
    if not _is_admin(profile):
        return Response({'detail': 'مخصص للمديرين'}, status=403)
    qs = SoftechIdentityClaim.objects.filter(
        status=SoftechIdentityClaim.STATUS_PENDING
    ).select_related('staff__user')
    return Response({'results': IdentityClaimSerializer(qs, many=True).data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def identity_review(request, pk):
    """Admin approve / reject a pending identity claim."""
    profile = _profile(request)
    if not _is_admin(profile):
        return Response({'detail': 'مخصص للمديرين'}, status=403)
    claim = get_object_or_404(SoftechIdentityClaim, pk=pk)
    action = (request.data.get('action') or '').strip()
    if action not in ('approve', 'reject'):
        return Response({'detail': 'action يجب أن يكون approve أو reject'}, status=400)
    claim.status = (
        SoftechIdentityClaim.STATUS_APPROVED if action == 'approve'
        else SoftechIdentityClaim.STATUS_REJECTED
    )
    claim.reviewed_by = profile
    claim.reviewed_at = timezone.now()
    claim.review_note = (request.data.get('note') or '').strip()
    claim.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note', 'updated_at'])
    return Response(IdentityClaimSerializer(claim).data)


# ══════════════════════════════════════════════════════════════════════════════
# WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def widgets_catalog(request):
    return Response({'results': catalog()})


def _owned_identity_or_400(profile, identity_id, widget_type):
    """Validate that a bound identity is owned by the caller and kind-compatible."""
    if identity_id in (None, '', 0):
        return None, None
    ident = SoftechIdentityClaim.objects.filter(pk=identity_id, staff=profile).first()
    if not ident:
        return None, Response({'detail': 'الهوية غير موجودة أو ليست لك'}, status=400)
    kind = WIDGET_REGISTRY.get(widget_type, {}).get('kind')
    if kind and ident.kind != kind:
        return None, Response({'detail': 'نوع الهوية لا يطابق نوع اللوحة'}, status=400)
    return ident, None


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def widgets(request):
    profile = _profile(request)
    if not profile:
        return Response({'detail': 'لا يوجد ملف موظف'}, status=403)

    if request.method == 'GET':
        qs = PersonalWidget.objects.filter(staff=profile).select_related('identity')
        return Response({'results': PersonalWidgetSerializer(qs, many=True).data})

    # POST — add a widget
    widget_type = (request.data.get('widget_type') or '').strip()
    if widget_type not in WIDGET_REGISTRY:
        return Response({'detail': 'نوع لوحة غير معروف'}, status=400)
    ident, err = _owned_identity_or_400(profile, request.data.get('identity'), widget_type)
    if err:
        return err
    widget = PersonalWidget.objects.create(
        staff=profile,
        widget_type=widget_type,
        identity=ident,
        title=(request.data.get('title') or '').strip(),
        config=request.data.get('config') or {},
        size=request.data.get('size') or 'md',
        column=int(request.data.get('column') or 0),
        position=int(request.data.get('position') or 0),
    )
    return Response(PersonalWidgetSerializer(widget).data, status=201)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def widget_detail(request, pk):
    profile = _profile(request)
    widget = get_object_or_404(PersonalWidget, pk=pk)
    if widget.staff_id != profile.id:
        return Response({'detail': 'غير مصرّح'}, status=403)

    if request.method == 'DELETE':
        widget.delete()
        return Response(status=204)

    data = request.data
    if 'identity' in data:
        ident, err = _owned_identity_or_400(profile, data.get('identity'), widget.widget_type)
        if err:
            return err
        widget.identity = ident
    for field in ('title', 'config', 'size', 'column', 'position', 'enabled'):
        if field in data:
            setattr(widget, field, data[field])
    widget.save()
    # invalidate cached data
    cache.delete(f'personal:widget:{widget.id}:data')
    return Response(PersonalWidgetSerializer(widget).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def widgets_layout(request):
    """Bulk reorder — body: [{id, column, position, size?}]."""
    profile = _profile(request)
    items = request.data if isinstance(request.data, list) else request.data.get('items', [])
    ids = [it.get('id') for it in items if it.get('id')]
    owned = {w.id: w for w in PersonalWidget.objects.filter(staff=profile, id__in=ids)}
    updated = []
    for it in items:
        w = owned.get(it.get('id'))
        if not w:
            continue
        if 'column' in it:   w.column = int(it['column'] or 0)
        if 'position' in it: w.position = int(it['position'] or 0)
        if 'size' in it:     w.size = it['size'] or w.size
        w.save(update_fields=['column', 'position', 'size', 'updated_at'])
        updated.append(w.id)
    return Response({'updated': updated})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def widget_data(request, pk):
    """Live (cached) data payload for a single widget."""
    profile = _profile(request)
    if not profile:
        return Response({'detail': 'لا يوجد ملف موظف'}, status=403)
    widget = get_object_or_404(PersonalWidget, pk=pk)
    if widget.staff_id != profile.id:
        return Response({'detail': 'غير مصرّح'}, status=403)

    meta = WIDGET_REGISTRY.get(widget.widget_type)
    if not meta:
        return Response({'detail': 'نوع لوحة غير معروف'}, status=400)

    try:
        person_key = resolve_person_key(widget, profile)
    except PersonalError as e:
        return Response({'detail': e.detail}, status=e.status)

    cache_key = f'personal:widget:{widget.id}:data'
    refresh = request.query_params.get('refresh') in ('1', 'true', 'yes')
    # Heavy live SOFTECH scans cache longer; fast mirror widgets (tasks, sales)
    # refresh sooner so allocated-task changes surface quickly.
    default_ttl = 300 if meta['source'] == 'softech_live' else 60
    cfg = widget.config if isinstance(widget.config, dict) else {}
    ttl = int(cfg.get('cache_ttl', default_ttl))

    if not refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return Response({**cached, '_cached': True})

    try:
        payload = meta['fetch'](person_key, widget.config or {}, profile)
    except Exception as e:  # provider-level failure — never 500 the dashboard
        return Response({'detail': 'تعذّر جلب البيانات', 'error': str(e)[:200]}, status=502)

    envelope = {
        'widget_type': widget.widget_type,
        'source':      meta['source'],
        'generated_at': timezone.now().isoformat(),
        'data':        payload,
    }
    if meta['source'] == 'softech_live' and isinstance(payload, dict) and payload.get('error'):
        # don't cache a live error — let the next call retry
        return Response({**envelope, '_cached': False})
    cache.set(cache_key, envelope, ttl)
    return Response({**envelope, '_cached': False})
