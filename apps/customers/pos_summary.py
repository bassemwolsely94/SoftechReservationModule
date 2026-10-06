"""
customers/pos_summary.py — the compact Customer-360 payload for the POS
side-drawer.

Deliberately LIGHT and fast (the cashier opens it mid-sale without abandoning the
basket) — it is NOT the full patient-profile (`patient_profile.build_patient_profile`),
which stays the heavy view for the customer page. Reuses existing model fields +
LoyaltyAccount + CustomerHealthProfile; composes, never duplicates business logic.

Safety-first: clinical flags (allergies, pregnancy/lactation, chronic conditions)
are surfaced explicitly so an upsell can never bury them (rule 4).
"""
from django.db.models import Sum, Max, Count


def build_pos_summary(customer):
    return {
        'crm': _crm(customer),
        'health': _health(customer),
        'purchases': _purchases(customer),
        'reservations': _open_reservations(customer),
        'loyalty': _loyalty(customer),
    }


def _crm(c):
    return {
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'whatsapp_phone': c.whatsapp_phone or c.phone,
        'softech_pic': c.softech_pic,
        'is_guest': c.is_guest,
        'segment': c.segment,
        'segment_label': c.get_segment_display() if c.segment else '',
        'churn_segment': c.churn_segment,
        'churn_segment_label': c.get_churn_segment_display() if c.churn_segment else '',
        'ltv': float(c.ltv) if c.ltv is not None else None,
        'last_visit_date': c.last_visit_date.isoformat() if c.last_visit_date else None,
        'days_since_last_visit': c.days_since_last_visit,
        'purchase_count_90d': c.purchase_count_90d,
        'customer_type_label': c.customer_type_label,
        'discount_percent': float(c.discount_percent or 0),
    }


def _health(c):
    hp = getattr(c, 'health_profile', None)
    if not hp:
        # staff-entered free text fallback
        txt = (c.chronic_conditions or '').strip()
        return {'has_profile': False, 'is_chronic': bool(txt),
                'conditions': [txt] if txt else [], 'allergies': [],
                'pregnancy': False, 'lactation': False, 'pediatric': False,
                'polypharmacy': False, 'active_medication_count': 0}
    allergies = [a.get('name') if isinstance(a, dict) else a
                 for a in (hp.known_allergies or [])]
    return {
        'has_profile': True,
        'is_chronic': hp.is_chronic,
        'conditions': hp.detected_conditions,
        'allergies': [a for a in allergies if a],
        'pregnancy': hp.pregnancy_flag,
        'lactation': hp.lactation_flag,
        'pediatric': hp.pediatric_patient,
        'polypharmacy': hp.polypharmacy_flag,
        'active_medication_count': len(hp.active_medications or []),
    }


def _purchases(c):
    agg = c.purchases.aggregate(count=Count('id'), total=Sum('total_amount'), last=Max('invoice_date'))
    return {
        'total_count': agg['count'] or 0,
        'total_amount': float(agg['total'] or 0),
        'last_invoice_date': agg['last'].isoformat() if agg['last'] else None,
    }


def _open_reservations(c):
    from apps.reservations.models import Reservation
    open_states = ('pending', 'available', 'contacted', 'confirmed')
    qs = (Reservation.objects.filter(customer=c, status__in=open_states)
          .select_related('item').order_by('-created_at'))
    rows = [{
        'id': r.id, 'status': r.status, 'status_label': r.get_status_display(),
        'item_name': (r.item.name if r.item_id else r.manual_item_name),
    } for r in qs[:5]]
    return {'open_count': qs.count(), 'recent': rows}


def _loyalty(c):
    acct = getattr(c, 'loyalty_account', None) or getattr(c, 'loyaltyaccount', None)
    if not acct:
        from apps.loyalty.models import LoyaltyAccount
        acct = LoyaltyAccount.objects.filter(customer=c).first()
    if not acct:
        return {'enrolled': False, 'points_balance': 0, 'softech_points_balance': None}
    return {
        'enrolled': True,
        'points_balance': acct.points_balance,
        'softech_points_balance': acct.softech_points_balance,
    }
