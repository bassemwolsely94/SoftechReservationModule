"""
catalog/search_views.py — the single universal-search endpoint powering the POS
search box and (Phase-1) the Ctrl+K command palette.

GET /api/search/universal?q=<text>&branch=<id>&types=items,customers&limit=8

Staff-only (JWT). Read-only. All matching logic + the exact-identity safety rule
live in catalog/universal.py; this view is a thin HTTP wrapper.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .universal import universal_search, TYPES, DEFAULT_LIMIT

MAX_LIMIT = 25


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def universal_search_view(request):
    q = request.query_params.get('q', '')

    branch_id = request.query_params.get('branch') or None
    if branch_id:
        try:
            branch_id = int(branch_id)
        except (TypeError, ValueError):
            branch_id = None

    try:
        limit = min(int(request.query_params.get('limit', DEFAULT_LIMIT)), MAX_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(limit, 1)

    types_param = request.query_params.get('types')
    types = None
    if types_param:
        requested = [t.strip() for t in types_param.split(',') if t.strip()]
        types = [t for t in requested if t in TYPES] or None

    results = universal_search(q, branch_id=branch_id, limit=limit, types=types)
    total = sum(len(v) for v in results.values())
    return Response({'query': q.strip(), 'count': total, 'results': results})
