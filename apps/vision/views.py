"""
apps/vision/views.py — visibility into the in-house OCR corpus (Phase 1).

Read-only stats so we can watch the owned, labelled dataset grow across sales +
purchasing, and see the engine mix + label rate that will drive P2 (the parallel
in-house recognizer) and P3 (handwriting fine-tune).
"""
from django.db.models import Count, Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from .models import OcrSample


def _staff(user):
    return getattr(user, 'staff_profile', None)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def corpus_stats(request):
    """Corpus size, module / engine mix, media split, and label rate."""
    sp = _staff(request.user)
    if not sp or sp.role not in ('admin', 'supervisor', 'purchasing', 'pharmacist'):
        return Response({'detail': 'غير مصرّح.'}, status=403)

    qs = OcrSample.objects.all()
    total = qs.count()
    # a labelled sample has at least one confirmation
    labelled = qs.exclude(confirmations=[]).count()

    def _by(field):
        return {r[field]: r['n'] for r in qs.values(field).annotate(n=Count('id')).order_by('-n')}

    from django.conf import settings
    from .inhouse import is_available
    trainable = qs.exclude(confirmations=[]).filter(media_type='image').count()
    return Response({
        'total': total,
        'labelled': labelled,
        'unlabelled': total - labelled,
        'label_rate': round(labelled / total, 3) if total else 0.0,
        'trainable_images': trainable,               # labelled image pairs ready for training
        'inhouse_configured': bool(getattr(settings, 'INHOUSE_OCR_MODEL_DIR', '')),
        'inhouse_ready': is_available(),             # a fine-tuned model is loaded + usable
        'by_module': _by('module'),
        'by_engine': _by('engine'),
        'by_media': _by('media_type'),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def corpus_accuracy(request):
    """
    In-house vs Gemini: over recent LABELLED samples that ran engines in parallel, how
    many human-confirmed items did each engine's readings resolve to (via the catalog)?
    Per-engine recall of the ground truth — the signal for when to trust the in-house path.
    """
    sp = _staff(request.user)
    if not sp or sp.role not in ('admin', 'supervisor', 'purchasing', 'pharmacist'):
        return Response({'detail': 'غير مصرّح.'}, status=403)

    from apps.shortage.matching import find_best_matches
    samples = list(OcrSample.objects.exclude(confirmations=[]).exclude(engine_readings={})
                   .order_by('-created_at')[:80])

    stats = {}
    for s in samples:
        confirmed = {c.get('item_id') for c in (s.confirmations or []) if c.get('item_id')}
        if not confirmed:
            continue
        for engine, readings in (s.engine_readings or {}).items():
            resolved = set()
            for r in (readings or []):
                reads = r.get('readings') or []
                if not reads:
                    continue
                q = (str(reads[0]) + ' ' + (r.get('strength') or '')).strip()
                m = find_best_matches(q, top_n=1)
                if m:
                    resolved.add(m[0]['item_id'])
            st = stats.setdefault(engine, {'confirmed': 0, 'covered': 0})
            st['confirmed'] += len(confirmed)
            st['covered'] += len(resolved & confirmed)

    results = [{
        'engine': e, 'confirmed': v['confirmed'], 'covered': v['covered'],
        'recall': round(v['covered'] / v['confirmed'], 3) if v['confirmed'] else 0.0,
    } for e, v in sorted(stats.items(), key=lambda x: -x[1]['confirmed'])]
    return Response({'sample_window': len(samples), 'results': results})
