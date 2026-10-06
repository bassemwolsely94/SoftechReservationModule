"""
catalog/tag_views.py — curated merchandising tags + subcategory tree.

Read: any authenticated staff. Write (create/edit/delete tags, assign to items):
gated on the RBAC `catalog`/edit action (admins bypass). Platform-native — never
touches SOFTECH.
"""
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import Category, Item, ItemTag


def _can_edit(request):
    p = getattr(request.user, 'staff_profile', None)
    if not (p and p.is_active):
        return False
    if p.role == 'admin':
        return True
    try:
        return p.can_do('catalog', 'edit')
    except Exception:
        return False


def _tag_dict(t):
    return {'id': t.id, 'slug': t.slug, 'name': t.name, 'name_ar': t.name_ar,
            'color': t.color, 'is_active': t.is_active, 'item_count': getattr(t, 'item_count', None)}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def tags_list_create(request):
    if request.method == 'GET':
        from django.db.models import Count
        qs = ItemTag.objects.all()
        if request.query_params.get('active') == '1':
            qs = qs.filter(is_active=True)
        qs = qs.annotate(item_count=Count('items'))
        return Response([_tag_dict(t) for t in qs])

    # POST — create
    if not _can_edit(request):
        return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
    name = (request.data.get('name') or '').strip()
    if not name:
        return Response({'detail': 'الاسم مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
    slug = (request.data.get('slug') or slugify(name, allow_unicode=True)).strip()[:50] or slugify(name)
    if ItemTag.objects.filter(slug=slug).exists():
        return Response({'detail': 'معرّف مكرر'}, status=status.HTTP_400_BAD_REQUEST)
    tag = ItemTag.objects.create(
        slug=slug, name=name, name_ar=(request.data.get('name_ar') or '').strip(),
        color=(request.data.get('color') or '').strip(),
        created_by=getattr(request.user, 'staff_profile', None),
    )
    return Response(_tag_dict(tag), status=status.HTTP_201_CREATED)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def tag_detail(request, tag_id):
    if not _can_edit(request):
        return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
    tag = get_object_or_404(ItemTag, pk=tag_id)
    if request.method == 'DELETE':
        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    for f in ('name', 'name_ar', 'color'):
        if f in request.data:
            setattr(tag, f, (request.data.get(f) or '').strip())
    if 'is_active' in request.data:
        tag.is_active = bool(request.data.get('is_active'))
    tag.save()
    return Response(_tag_dict(tag))


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def item_tag_assign(request, item_id, tag_id=None):
    if not _can_edit(request):
        return Response({'detail': 'غير مصرح'}, status=status.HTTP_403_FORBIDDEN)
    item = get_object_or_404(Item, pk=item_id)
    if request.method == 'DELETE':
        item.tags.remove(get_object_or_404(ItemTag, pk=tag_id))
        return Response(status=status.HTTP_204_NO_CONTENT)
    tid = request.data.get('tag_id')
    tag = get_object_or_404(ItemTag, pk=tid)
    item.tags.add(tag)
    return Response({'ok': True, 'tags': [_tag_dict(t) for t in item.tags.all()]}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quick_sell(request):
    """Per-branch top-sellers for the POS Quick-Sell grid. ?branch=&days=&limit="""
    from .quicksell import top_sellers, DEFAULT_DAYS, DEFAULT_LIMIT
    branch_id = request.query_params.get('branch')
    if not branch_id:
        p = getattr(request.user, 'staff_profile', None)
        branch_id = getattr(getattr(p, 'branch', None), 'id', None)
    if not branch_id:
        return Response({'detail': 'branch مطلوب'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        days = int(request.query_params.get('days', DEFAULT_DAYS))
        limit = int(request.query_params.get('limit', DEFAULT_LIMIT))
    except (TypeError, ValueError):
        days, limit = DEFAULT_DAYS, DEFAULT_LIMIT
    return Response({'branch': int(branch_id), 'days': days,
                     'results': top_sellers(int(branch_id), days=days, limit=limit)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def category_tree(request):
    """Two-level category tree (roots + their subcategories)."""
    cats = list(Category.objects.select_related('parent').all())
    by_parent = {}
    for c in cats:
        by_parent.setdefault(c.parent_id, []).append(c)

    def node(c):
        return {'id': c.id, 'softech_id': c.softech_id, 'name': c.name, 'name_ar': c.name_ar,
                'children': [node(ch) for ch in by_parent.get(c.id, [])]}

    roots = [node(c) for c in by_parent.get(None, [])]
    return Response(roots)
