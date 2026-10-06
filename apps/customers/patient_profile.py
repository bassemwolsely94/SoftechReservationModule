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
        'intelligence':      _intelligence_section(customer),   # churn + segment scores
        'erp_identity':      _erp_identity_section(customer),
        'purchase_summary':  _purchase_summary(customer),
        'recent_purchases':  _recent_purchases(customer),
        'health_profile':    _structured_health_profile(customer),  # new: structured conditions
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
        'id':                    customer.id,
        'name':                  customer.name,
        'softech_id':            customer.softech_id,
        'softech_pic':           customer.softech_pic,
        'softech_ptclassifcode': customer.softech_ptclassifcode,
        'customer_type_label':   customer.customer_type_label,
        'customer_type_color':   customer.customer_type_color,
        'discount_percent':      float(customer.discount_percent),
        'date_of_birth':         customer.date_of_birth.isoformat() if customer.date_of_birth else None,
        'chronic_conditions':    customer.chronic_conditions,   # free-text (legacy)
        'notes_softech':         customer.notes_softech,
        'created_at':            customer.created_at.isoformat(),
        # CRM scores
        'segment':               customer.segment,
        'ltv':                   float(customer.ltv or 0),
        'last_visit_date':       customer.last_visit_date.isoformat() if customer.last_visit_date else None,
        'days_since_last_visit': customer.days_since_last_visit,
        'purchase_count_90d':    customer.purchase_count_90d,
    }


def _intelligence_section(customer):
    """CRM + Churn intelligence scores for the customer."""
    return {
        'segment':               customer.segment,
        'churn_score':           float(customer.churn_score or 0),
        'churn_score_pct':       round(float(customer.churn_score or 0) * 100, 1),
        'churn_segment':         customer.churn_segment,
        'churn_segment_label': {
            'low':      '✅ منخفض — عميل مستقر',
            'medium':   '⚠️ متوسط — مراقبة',
            'high':     '🔴 مرتفع — تدخل مطلوب',
            'critical': '🚨 حرج — على وشك الانقطاع',
        }.get(customer.churn_segment, '—'),
        'churn_updated_at':      customer.churn_updated_at.isoformat() if customer.churn_updated_at else None,
        'complaint_risk_score':  customer.complaint_risk_score,
        'ltv':                   float(customer.ltv or 0),
        'days_since_last_visit': customer.days_since_last_visit,
        'purchase_count_90d':    customer.purchase_count_90d,
    }


def _structured_health_profile(customer):
    """
    Returns the CustomerHealthProfile (auto-computed from chronic purchases).
    Falls back gracefully if the profile hasn't been built yet.
    """
    try:
        hp = customer.health_profile
        return {
            'exists':              True,
            'detected_conditions': hp.detected_conditions,
            'condition_confidence': hp.condition_confidence,
            'has_diabetes':        hp.has_diabetes,
            'has_hypertension':    hp.has_hypertension,
            'has_cardiovascular':  hp.has_cardiovascular,
            'has_thyroid':         hp.has_thyroid,
            'has_cholesterol':     hp.has_cholesterol,
            'has_asthma':          hp.has_asthma,
            'has_psychiatric':     hp.has_psychiatric,
            'has_epilepsy':        hp.has_epilepsy,
            'has_osteoporosis':    hp.has_osteoporosis,
            'has_renal':           hp.has_renal,
            'has_oncology':        hp.has_oncology,
            'has_gerd':            hp.has_gerd,
            'has_anemia':          hp.has_anemia,
            'has_anticoagulant':   hp.has_anticoagulant,
            'has_immunosuppressant': hp.has_immunosuppressant,
            'pregnancy_flag':      hp.pregnancy_flag,
            'lactation_flag':      hp.lactation_flag,
            'pediatric_patient':   hp.pediatric_patient,
            'polypharmacy_flag':   hp.polypharmacy_flag,
            'known_allergies':     hp.known_allergies,
            'declared_allergies_text': hp.declared_allergies_text,
            'active_medications':  hp.active_medications,
            'active_ingredient_names': hp.active_ingredient_names,
            'is_chronic':          hp.is_chronic,
            'manually_overridden': hp.manually_overridden,
            'last_computed_at':    hp.last_computed_at.isoformat() if hp.last_computed_at else None,
        }
    except Exception:
        return {
            'exists': False,
            'note':   'الملف الصحي لم يُبنَ بعد — سيتم بناؤه في التشغيل القادم لـ segment_customers',
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
    """
    Chronic medications and refill status for this customer.

    Priority:
      1. CustomerHealthProfile.active_medications  — computed from purchase history + chronic module
      2. followups.FollowUpTask (pending/overdue)  — scheduled refill tasks
      3. Empty list if neither exists yet
    """
    result = []
    try:
        # ── Source 1: CustomerHealthProfile.active_medications ─────────────────
        hp = customer.health_profile
        for med in (hp.active_medications or []):
            # Get the linked FollowUpTask (if any) to show refill timing
            refill_due        = None
            days_until_refill = None
            open_task         = None
            try:
                from apps.followups.models import ChronicMedicationProfile as CMP
                profile = CMP.objects.filter(item_id=med['item_id']).first()
                if profile and med.get('last_purchase_date'):
                    from datetime import date, timedelta
                    raw = med['last_purchase_date']
                    # Handle both date objects and ISO strings
                    if hasattr(raw, 'year'):
                        last_date = raw if isinstance(raw, date) else raw.date()
                    else:
                        # Parse ISO date string (YYYY-MM-DD)
                        parts     = str(raw)[:10].split('-')
                        last_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                    refill_due        = last_date + timedelta(days=profile.expected_duration_days)
                    days_until_refill = (refill_due - date.today()).days
            except Exception:
                pass

            result.append({
                'item_id':               med.get('item_id'),
                'item_name':             med.get('item_name', ''),
                'item_softech_id':       '',
                'ingredient':            med.get('ingredient', ''),
                'purchase_count':        med.get('purchase_count', 0),
                'last_sale_date':        med.get('last_purchase_date'),
                'expected_duration_days': med.get('expected_duration_days'),
                'refill_due':            refill_due.isoformat() if refill_due else None,
                'days_until_refill':     days_until_refill,
                'needs_refill_soon':     (
                    days_until_refill is not None and days_until_refill <= 5
                ),
            })

    except Exception:
        pass

    # ── Source 2: Open FollowUpTasks (always include, merge with above) ────────
    try:
        from apps.followups.models import FollowUpTask
        tasks = (
            FollowUpTask.objects
            .filter(customer=customer, status__in=('pending', 'called', 'missed'))
            .select_related('item', 'chronic_profile')
            .order_by('due_date')[:10]
        )
        existing_item_ids = {r['item_id'] for r in result}
        for task in tasks:
            if task.item_id in existing_item_ids:
                # Enrich existing entry with task status
                for r in result:
                    if r['item_id'] == task.item_id:
                        r['task_status']  = task.status
                        r['task_due_date'] = str(task.due_date)
                        r['task_id']      = task.pk
            else:
                from datetime import date
                days_until = (task.due_date - date.today()).days if task.due_date else None
                result.append({
                    'item_id':               task.item_id,
                    'item_name':             task.item.name if task.item else '—',
                    'item_softech_id':       task.item.softech_id if task.item else '',
                    'ingredient':            '',
                    'purchase_count':        0,
                    'last_sale_date':        str(task.source_sale_date) if task.source_sale_date else None,
                    'expected_duration_days': (
                        task.chronic_profile.expected_duration_days
                        if task.chronic_profile else None
                    ),
                    'refill_due':            str(task.due_date),
                    'days_until_refill':     days_until,
                    'needs_refill_soon':     days_until is not None and days_until <= 5,
                    'task_status':           task.status,
                    'task_due_date':         str(task.due_date),
                    'task_id':               task.pk,
                })
    except Exception:
        pass

    return result


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
        from apps.demand.serializers import DemandListSerializer
        from apps.demand.models import DemandRecord
        demands = (
            DemandRecord.objects
            .filter(customer=customer)
            .select_related('branch', 'assigned_to__user')
            .order_by('-created_at')[:limit]
        )
        return DemandListSerializer(demands, many=True).data
    except Exception:
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
        from apps.demand.models import DemandRecord
        demands = (
            DemandRecord.objects
            .filter(customer=customer)
            .select_related('branch')
            .order_by('-created_at')[:10]
        )
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

    # ── Follow-up tasks (chronic refills) ────────────────────────────────────
    try:
        from apps.followups.models import FollowUpTask
        tasks = (
            FollowUpTask.objects
            .filter(customer=customer)
            .select_related('item')
            .order_by('-created_at')[:10]
        )
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
