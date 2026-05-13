"""
apps/customers/patient_profile.py

Phase 6: Patient Profile — unified view per customer.

Aggregates from all phases:
  Phase 1 → ERP transaction history (localcustomers + ERPTransaction)
  Phase 2 → Tags + CustomerLocations
  Phase 3 → Reservation history + chatter
  Phase 4 → Transfer requests (where customer was mentioned)
  Phase 5 → Follow-up tasks + ChronicMedicationProfile
  Demand  → DemandRequest history

No new models. Pure aggregation and serialization.
"""
from django.db.models import Sum, Count, Max, Q
from django.utils import timezone
from datetime import timedelta


def build_patient_profile(customer, request_user=None):
    """
    Build a complete patient profile dict for a given customer.
    All sections are non-fatal — a missing app/table returns empty data.
    """
    profile = {
        'customer':          _customer_section(customer),
        'contact':           _contact_section(customer),
        'erp_identity':      _erp_identity_section(customer),
        'purchase_summary':  _purchase_summary(customer),
        'recent_purchases':  _recent_purchases(customer),
        'chronic_profile':   _chronic_profile(customer),
        'active_followups':  _active_followups(customer),
        'reservations':      _reservations(customer),
        'demand_requests':   _demand_requests(customer),
        'tags':              _tags(customer),
        'locations':         _locations(customer),
        'erp_sales':         _erp_sales(customer),
        'generated_at':      timezone.now().isoformat(),
    }
    return profile


# ── Sections ──────────────────────────────────────────────────────────────────

def _customer_section(customer):
    return {
        'id':                   customer.id,
        'name':                 customer.name,
        'softech_id':           customer.softech_id,
        'softech_ptclassifcode': customer.softech_ptclassifcode,
        'customer_type_label':  customer.customer_type_label,
        'customer_type_color':  customer.customer_type_color,
        'discount_percent':     float(customer.discount_percent),
        'date_of_birth':        customer.date_of_birth.isoformat() if customer.date_of_birth else None,
        'chronic_conditions':   customer.chronic_conditions,
        'notes_softech':        customer.notes_softech,
        'created_at':           customer.created_at.isoformat(),
    }


def _contact_section(customer):
    return {
        'phone':        customer.phone,
        'phone_alt':    customer.phone_alt,
        'email':        customer.email,
        'address':      customer.address,
        'preferred_branch': (
            customer.preferred_branch.name_ar
            if customer.preferred_branch else None
        ),
        'whatsapp_url': _whatsapp(customer.phone),
    }


def _whatsapp(phone):
    if not phone:
        return None
    clean = phone.strip().replace(' ', '').replace('-', '')
    if clean.startswith('0'):
        clean = '20' + clean[1:]
    return f'https://wa.me/{clean}'


def _erp_identity_section(customer):
    """Link to ERP: localcustomers record if exists."""
    try:
        from apps.erp.models import LocalCustomer
        lc = LocalCustomer.objects.filter(
            Q(linked_customer=customer) |
            Q(phcode=customer.softech_id or '')
        ).select_related('branch').first()

        if lc:
            return {
                'found':        True,
                'phcode':       lc.phcode,
                'name':         lc.name,
                'phone':        lc.phone,
                'erp_branch':   lc.erp_branch_code,
                'customer_type': lc.customer_type,
                'is_active':    lc.is_active,
                'whatsapp_url': lc.whatsapp_url,
            }
    except Exception:
        pass
    return {'found': False, 'phcode': customer.softech_id}


def _purchase_summary(customer):
    """Summary KPIs from PurchaseHistory (existing legacy data)."""
    try:
        qs = customer.purchases.all()
        agg = qs.aggregate(
            total_count=Count('id'),
            total_spent=Sum('total_amount'),
            last_purchase=Max('invoice_date'),
        )
        sales_count   = qs.filter(doc_code='115').count()
        returns_count = qs.filter(doc_code='30').count()

        return {
            'total_invoices':   agg['total_count'] or 0,
            'sales_invoices':   sales_count,
            'return_invoices':  returns_count,
            'total_spent_egp':  float(agg['total_spent'] or 0),
            'last_purchase_at': (
                agg['last_purchase'].isoformat()
                if agg['last_purchase'] else None
            ),
        }
    except Exception:
        return {}


def _recent_purchases(customer, limit=10):
    """Last N purchase invoices with lines."""
    try:
        from apps.customers.serializers import PurchaseHistorySerializer
        purchases = customer.purchases.select_related('branch').prefetch_related(
            'lines__item'
        ).order_by('-invoice_date')[:limit]
        return PurchaseHistorySerializer(purchases, many=True).data
    except Exception:
        return []


def _chronic_profile(customer):
    """Chronic medications and refill status for this customer."""
    try:
        from apps.erp.models import ERPTransaction
        from apps.followups.models import ChronicMedicationProfile

        # Find items the customer has bought that have a chronic profile
        bought_item_ids = set(
            ERPTransaction.objects.filter(
                doccode='115',
                personsdata_customer=customer,
            ).values_list('lines__item_id', flat=True)
        )
        if not bought_item_ids and customer.softech_id:
            bought_item_ids = set(
                ERPTransaction.objects.filter(
                    doccode='115',
                    phcode=customer.softech_id or '',
                ).values_list('lines__item_id', flat=True)
            )

        profiles = ChronicMedicationProfile.objects.filter(
            item_id__in=bought_item_ids,
            is_chronic=True,
        ).select_related('item')

        result = []
        for p in profiles:
            # Get last sale of this item
            last_tx = ERPTransaction.objects.filter(
                doccode='115',
                lines__item=p.item,
            ).filter(
                Q(personsdata_customer=customer) |
                Q(phcode=customer.softech_id or '')
            ).order_by('-transaction_date').first()

            last_sale_date = last_tx.transaction_date.date() if last_tx else None
            refill_due = None
            days_until_refill = None
            if last_sale_date:
                from datetime import timedelta, date
                refill_due = last_sale_date + timedelta(days=p.expected_duration_days)
                days_until_refill = (refill_due - date.today()).days

            result.append({
                'item_id':              p.item_id,
                'item_name':            p.item.name,
                'item_softech_id':      p.item.softech_id,
                'expected_duration_days': p.expected_duration_days,
                'last_sale_date':       last_sale_date.isoformat() if last_sale_date else None,
                'refill_due':           refill_due.isoformat() if refill_due else None,
                'days_until_refill':    days_until_refill,
                'needs_refill_soon':    days_until_refill is not None and days_until_refill <= p.followup_before_days,
            })
        return result
    except Exception:
        return []


def _active_followups(customer):
    """Open follow-up tasks for this customer."""
    try:
        from apps.followups.serializers import FollowUpTaskListSerializer
        tasks = customer.followup_tasks.filter(
            status__in=('pending', 'called')
        ).select_related('item', 'branch', 'assigned_to__user').order_by('due_date')
        return FollowUpTaskListSerializer(tasks, many=True).data
    except Exception:
        return []


def _reservations(customer, limit=20):
    """Recent reservations for this customer."""
    try:
        from apps.reservations.serializers import ReservationListSerializer
        from apps.reservations.models import Reservation
        reservations = Reservation.objects.filter(Q(customer=customer) | Q(local_customer__phcode=customer.softech_id or '')).select_related('item', 'branch', 'assigned_to__user').order_by('-created_at')[:limit]
        return ReservationListSerializer(reservations, many=True).data
    except Exception:
        return []


def _demand_requests(customer, limit=10):
    """Recent demand requests linked to this customer."""
    try:
        from apps.demand.serializers import DemandRequestListSerializer
        from apps.demand.models import DemandRequest
        demands = DemandRequest.objects.filter(Q(customer=customer) | Q(local_customer__phcode=customer.softech_id or '')).select_related('branch', 'assigned_to__user').order_by('-created_at')[:limit]
        return DemandRequestListSerializer(demands, many=True).data
    except Exception:
        # Demand app may not be deployed
        return []


def _tags(customer):
    """All tags on this customer."""
    try:
        return [
            {
                'id':       ct.tag_id,
                'name':     ct.tag.name,
                'color':    ct.tag.color,
                'tag_type': ct.tag.tag_type,
                'notes':    ct.notes,
            }
            for ct in customer.tags.select_related('tag').all()
        ]
    except Exception:
        return []


def _locations(customer):
    """All active delivery locations."""
    try:
        from apps.customers.serializers import CustomerLocationListSerializer
        return CustomerLocationListSerializer(
            customer.locations.filter(is_active=True).order_by('-is_default'),
            many=True,
        ).data
    except Exception:
        return []


def _erp_sales(customer, limit=20):
    """Recent ERP sales (Phase 1) — richer than PurchaseHistory."""
    try:
        from apps.erp.models import ERPTransaction
        from apps.erp.serializers import ERPTransactionSerializer

        qs = ERPTransaction.objects.filter(
            doccode__in=['115', '30'],
        ).filter(
            Q(personsdata_customer=customer) |
            Q(phcode=customer.softech_id or '' or 'NOMATCH')
        ).select_related('branch').prefetch_related(
            'lines__item'
        ).order_by('-transaction_date')[:limit]

        return ERPTransactionSerializer(qs, many=True).data
    except Exception:
        return []




def build_timeline(customer, limit=50):
    """
    Returns a sorted list of all patient events in reverse chronological order.
    Each event has: {type, date, label, detail, color, icon}
    """
    events = []

    # ── ERP sales ─────────────────────────────────────────────────────────────
    try:
        from apps.erp.models import ERPTransaction
        from django.db.models import Q

        sales = ERPTransaction.objects.filter(
            doccode__in=['115', '30'],
        ).filter(
            Q(personsdata_customer=customer) |
            Q(phcode=customer.softech_id or 'NOMATCH')
        ).prefetch_related('lines__item').order_by('-transaction_date')[:30]

        for tx in sales:
            items_str = ', '.join([
                l.item.name if l.item else l.item_code
                for l in tx.lines.all()[:3]
            ])
            events.append({
                'type':   'erp_sale' if tx.doccode == '115' else 'erp_return',
                'date':   tx.transaction_date.isoformat(),
                'label':  'بيع في الصيدلية' if tx.doccode == '115' else 'مرتجع',
                'detail': items_str or tx.transaction_id,
                'amount': float(tx.total_amount),
                'color':  'green' if tx.doccode == '115' else 'orange',
                'icon':   '💊' if tx.doccode == '115' else '↩️',
                'ref':    tx.transaction_id,
            })
    except Exception:
        pass

    # ── Reservations ──────────────────────────────────────────────────────────
    try:
        from apps.reservations.models import Reservation
        reservations = Reservation.objects.filter(Q(customer=customer) | Q(local_customer__phcode=customer.softech_id or '')
        ).select_related('item', 'branch').order_by('-created_at')[:20]

        STATUS_COLORS = {
            'pending': 'gray', 'available': 'orange', 'contacted': 'blue',
            'confirmed': 'indigo', 'fulfilled': 'green',
            'cancelled': 'red', 'expired': 'red',
        }
        for r in reservations:
            events.append({
                'type':   'reservation',
                'date':   r.created_at.isoformat(),
                'label':  f'حجز — {r.get_status_display()}',
                'detail': f'{r.item.name} × {r.quantity_requested} — {r.branch.name_ar}',
                'color':  STATUS_COLORS.get(r.status, 'gray'),
                'icon':   '📋',
                'ref':    r.id,
                'status': r.status,
            })
    except Exception:
        pass

    # ── Demand requests ───────────────────────────────────────────────────────
    try:
        from apps.demand.models import DemandRequest
        demands = DemandRequest.objects.filter(Q(customer=customer) | Q(local_customer__phcode=customer.softech_id or '')
        ).select_related('branch').order_by('-created_at')[:10]

        for d in demands:
            events.append({
                'type':   'demand',
                'date':   d.created_at.isoformat(),
                'label':  f'طلب — {d.get_status_display()}',
                'detail': f'{d.demand_number} | {d.total_items} صنف',
                'color':  'red' if d.status == 'lost' else 'blue',
                'icon':   '🔍',
                'ref':    d.id,
                'status': d.status,
            })
    except Exception:
        pass

    # ── Follow-up tasks ───────────────────────────────────────────────────────
    try:
        from apps.followups.models import FollowUpTask
        tasks = FollowUpTask.objects.filter(
            Q(customer=customer) | Q(local_customer__phcode=customer.softech_id or '')
        ).select_related('item').order_by('-created_at')[:10]

        for t in tasks:
            events.append({
                'type':   'followup',
                'date':   t.created_at.isoformat(),
                'label':  f'متابعة — {t.get_status_display()}',
                'detail': f'{t.item.name if t.item else "—"} | استحقاق: {t.due_date}',
                'color':  'purple',
                'icon':   '📞',
                'ref':    t.id,
                'status': t.status,
            })
    except Exception:
        pass

    # ── Sort by date descending, limit ────────────────────────────────────────
    events.sort(key=lambda e: e['date'], reverse=True)
    return events[:limit]
