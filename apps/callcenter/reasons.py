"""
C12 (P-49) — call reason + outcome rules (deterministic, no AI).

The call-centre screen shows four one-tap reason chips (owner-approved: order, availability,
refill, complaint) and an outcome chip row. The server suggests a reason from what is already
open for the caller; the agent always confirms with a tap — nothing is saved on a guess.
"""
from django.db.models import Count, Q

PRIMARY_PURPOSES = ('new_order', 'demand', 'refill', 'complaint')
UNTAGGED_PURPOSES = ('pending', 'general')


def suggest_purpose(lookup: dict):
    """Pick the likeliest reason from a lookup payload, or None (no chip preselected).

    Order matters: an open complaint case beats a due refill, which beats an open order.
    """
    if lookup.get('open_cases'):
        return 'complaint'
    if lookup.get('open_followups'):
        return 'refill'
    if lookup.get('open_reservations') or lookup.get('active_demands'):
        return 'new_order'
    return None


def reason_stats(qs) -> dict:
    """Share of calls with a real reason, and how calls ended (dashboard)."""
    agg = qs.aggregate(total=Count('id'),
                       tagged=Count('id', filter=~Q(purpose__in=UNTAGGED_PURPOSES)),
                       pending=Count('id', filter=Q(purpose='pending')),
                       with_outcome=Count('id', filter=~Q(outcome='')))
    total = agg['total'] or 0
    return {
        'reason_tagged': agg['tagged'],
        'reason_pending': agg['pending'],
        'reason_tagged_pct': round(agg['tagged'] / total * 100, 1) if total else 0.0,
        'with_outcome': agg['with_outcome'],
        'by_outcome': list(qs.exclude(outcome='').values('outcome')
                           .annotate(count=Count('id')).order_by('-count')),
    }
