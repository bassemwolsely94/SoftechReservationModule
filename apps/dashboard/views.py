"""
apps/dashboard/views.py

Three endpoints:
  GET /api/dashboard/summary/      — main dashboard (all roles, branch-scoped)
  GET /api/dashboard/followups/    — follow-ups due today with full detail
  GET /api/dashboard/purchasing/   — purchasing analytics (admin/purchasing only)
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Count, Sum, Q, Avg
from django.utils import timezone
from datetime import date, timedelta

from apps.reservations.models import Reservation
from apps.customers.models import Customer, PurchaseHistory
from apps.catalog.models import ItemStock
from apps.sync.models import SyncRun


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _scope_reservations(qs, profile, branch_id=None):
    """Apply branch scoping based on role."""
    if profile and profile.role not in ('admin', 'call_center', 'purchasing'):
        if profile.branch:
            return qs.filter(branch=profile.branch)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    return qs


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/dashboard/summary/
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    today      = date.today()
    week_start = today - timedelta(days=today.weekday())
    profile    = _profile(request)
    branch_id  = request.query_params.get('branch')

    res_qs = _scope_reservations(Reservation.objects.all(), profile, branch_id)

    # ── Reservation KPIs ──────────────────────────────────────────────────────
    active_statuses = ['pending', 'available', 'contacted', 'confirmed']
    reservations = {
        'pending':             res_qs.filter(status='pending').count(),
        'available':           res_qs.filter(status='available').count(),
        'contacted':           res_qs.filter(status='contacted').count(),
        'confirmed':           res_qs.filter(status='confirmed').count(),
        'active_total':        res_qs.filter(status__in=active_statuses).count(),
        'follow_ups_today':    res_qs.filter(
            follow_up_date=today,
            status__in=active_statuses
        ).count(),
        'fulfilled_this_week': res_qs.filter(
            status='fulfilled',
            updated_at__date__gte=week_start
        ).count(),
        'urgent_active':       res_qs.filter(
            priority='urgent',
            status__in=active_statuses
        ).count(),
        'chronic_active':      res_qs.filter(
            priority='chronic',
            status__in=active_statuses
        ).count(),
        'stale_7d':            res_qs.filter(
            status='pending',
            updated_at__lt=timezone.now() - timedelta(days=7)
        ).count(),
    }

    # ── Status funnel (for mini-funnel widget) ────────────────────────────────
    status_funnel = [
        {'status': s, 'count': res_qs.filter(status=s).count()}
        for s in ['pending', 'available', 'contacted', 'confirmed', 'fulfilled']
    ]

    # ── By-branch active breakdown (admin/CC only) ────────────────────────────
    by_branch = []
    if profile and profile.role in ('admin', 'call_center', 'purchasing'):
        by_branch = list(
            Reservation.objects.filter(status__in=active_statuses)
            .values('branch__name_ar', 'branch__name', 'branch__id')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        for b in by_branch:
            b['branch_name'] = b['branch__name_ar'] or b['branch__name']

    # ── Sales KPIs (last 7 days) ──────────────────────────────────────────────
    sales_qs = PurchaseHistory.objects.filter(
        invoice_date__date__gte=today - timedelta(days=7),
        doc_code='115'
    )
    if branch_id:
        sales_qs = sales_qs.filter(branch_id=branch_id)
    elif profile and profile.branch and profile.role not in ('admin', 'call_center', 'purchasing'):
        sales_qs = sales_qs.filter(branch=profile.branch)

    sales = {
        'invoices_7d': sales_qs.count(),
        'revenue_7d':  float(sales_qs.aggregate(t=Sum('total_amount'))['t'] or 0),
    }

    # ── Customer stats ────────────────────────────────────────────────────────
    customers = {
        'total': Customer.objects.count(),
        'new_this_month': Customer.objects.filter(
            created_at__year=today.year,
            created_at__month=today.month
        ).count(),
    }

    # ── Low stock alerts ──────────────────────────────────────────────────────
    stock_qs = ItemStock.objects.filter(
        quantity_on_hand__gt=0,
        quantity_on_hand__lt=5
    ).select_related('item', 'branch').order_by('quantity_on_hand')
    if profile and profile.branch and profile.role not in ('admin', 'call_center', 'purchasing'):
        stock_qs = stock_qs.filter(branch=profile.branch)
    stock_alerts = [
        {
            'item_name':   s.item.name,
            'softech_id':  s.item.softech_id,
            'branch_name': s.branch.name_ar or s.branch.name,
            'quantity':    float(s.quantity_on_hand),
        }
        for s in stock_qs[:12]
    ]

    # ── Transfer KPIs ─────────────────────────────────────────────────────────
    transfers = {'pending': 0, 'flagged': 0, 'this_week': 0}
    try:
        from django.apps import apps as _a
        TR = _a.get_model('transfers', 'TransferRequest')
        transfers['pending']   = TR.objects.filter(status='sent').count()
        transfers['flagged']   = TR.objects.filter(flagged_no_sale=True).count()
        transfers['this_week'] = TR.objects.filter(
            created_at__date__gte=week_start
        ).count()
        # Branch-scoped incoming transfers for branch staff
        if profile and profile.branch and profile.role not in ('admin', 'call_center', 'purchasing'):
            transfers['incoming_to_my_branch'] = TR.objects.filter(
                source_branch=profile.branch,
                status='sent',
            ).count()
    except Exception:
        pass

    # ── Sync info ─────────────────────────────────────────────────────────────
    last_sync = SyncRun.objects.first()
    sync = {
        'status':  last_sync.status if last_sync else 'never',
        'last_at': last_sync.completed_at.isoformat()
                   if last_sync and last_sync.completed_at else None,
        'records': last_sync.records_synced if last_sync else 0,
        'duration': last_sync.duration_seconds if last_sync else None,
    }

    return Response({
        'reservations':  reservations,
        'status_funnel': status_funnel,
        'by_branch':     by_branch,
        'sales':         sales,
        'customers':     customers,
        'stock_alerts':  stock_alerts,
        'transfers':     transfers,
        'sync':          sync,
        'generated_at':  timezone.now().isoformat(),
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/dashboard/followups/
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def followups_today(request):
    """
    Full list of reservations with follow_up_date = today,
    scoped to the caller's branch. Used by the follow-up panel on the dashboard.
    """
    today   = date.today()
    profile = _profile(request)

    qs = Reservation.objects.filter(
        follow_up_date=today,
        status__in=['pending', 'available', 'contacted', 'confirmed'],
    ).select_related('customer', 'item', 'branch', 'assigned_to__user')

    qs = _scope_reservations(qs, profile)

    results = [
        {
            'id':            r.id,
            'item_name':     r.item.name,
            'softech_id':    r.item.softech_id,
            'customer_name': r.customer.name,
            'contact_phone': r.contact_phone,
            'branch_name':   r.branch.name_ar or r.branch.name,
            'status':        r.status,
            'status_label':  r.status_label_ar,
            'priority':      r.priority,
            'assigned_to':   r.assigned_to.full_name if r.assigned_to else None,
        }
        for r in qs.order_by('priority', '-updated_at')[:50]
    ]
    return Response({'count': len(results), 'results': results})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GET /api/dashboard/purchasing/
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def purchasing_dashboard(request):
    """Full purchasing analytics. Roles: admin, purchasing only."""
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing'):
        return Response(
            {'detail': 'هذه الصفحة مخصصة لقسم المشتريات والمديرين فقط'},
            status=403,
        )

    try:
        from django.apps import apps as _a
        TR = _a.get_model('transfers', 'TransferRequest')
    except Exception:
        return Response(
            {'detail': 'تطبيق التحويلات غير مُثبَّت بعد. تأكد من تشغيل migrate.'},
            status=503,
        )

    now      = timezone.now()
    days     = min(int(request.query_params.get('days', 30)), 180)
    win      = now - timedelta(days=days)
    week_ago = now - timedelta(days=7)

    tr_win  = TR.objects.filter(created_at__gte=win)
    tr_week = TR.objects.filter(created_at__gte=week_ago)

    total       = tr_win.count()
    n_accepted  = tr_win.filter(status__in=['accepted', 'fulfilled']).count()
    n_partial   = tr_win.filter(status='partial').count()
    n_rejected  = tr_win.filter(status='rejected').count()
    n_fulfilled = tr_win.filter(status='fulfilled').count()
    n_pending   = TR.objects.filter(status='sent').count()
    n_flagged   = TR.objects.filter(flagged_no_sale=True).count()
    accept_rate = round((n_accepted + n_partial) / total * 100, 1) if total else 0

    responded = TR.objects.filter(
        created_at__gte=win, responded_at__isnull=False
    ).only('created_at', 'responded_at')
    avg_hrs = None
    if responded.exists():
        secs = sum((t.responded_at - t.created_at).total_seconds() for t in responded)
        avg_hrs = round(secs / responded.count() / 3600, 1)

    weekly_breakdown = list(
        tr_week.values('status').annotate(count=Count('id')).order_by('status')
    )

    # Daily trend — last N days
    daily_trend = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).date()
        daily_trend.append({
            'date': str(d),
            'count': TR.objects.filter(created_at__date=d).count(),
        })

    top_items = list(
        tr_win.exclude(status='cancelled')
        .values('item__id', 'item__name', 'item__softech_id')
        .annotate(
            request_count  = Count('id'),
            total_qty      = Sum('quantity_needed'),
            accepted_count = Count('id', filter=Q(status__in=['accepted', 'partial', 'fulfilled'])),
            rejected_count = Count('id', filter=Q(status='rejected')),
        )
        .order_by('-request_count')[:10]
    )
    for row in top_items:
        rc = row['request_count']
        row['acceptance_rate'] = round(row['accepted_count'] / rc * 100) if rc else 0
        row['total_qty'] = float(row['total_qty'] or 0)

    recommended = [
        {
            'item_id':       r['item__id'],
            'item_name':     r['item__name'],
            'softech_id':    r['item__softech_id'],
            'request_count': r['request_count'],
            'total_qty':     r['total_qty'],
            'accept_rate':   r['acceptance_rate'],
            'reason':        f'طُلب تحويله {r["request_count"]} مرة خلال {days} يوماً',
        }
        for r in top_items if r['request_count'] >= 3
    ]

    top_requestors = []
    for row in (
        tr_win.exclude(status='cancelled')
        .values('requesting_branch__id', 'requesting_branch__name_ar', 'requesting_branch__name')
        .annotate(count=Count('id'), qty_total=Sum('quantity_needed'),
                  n_rejected=Count('id', filter=Q(status='rejected')))
        .order_by('-count')[:8]
    ):
        top_requestors.append({
            'branch_id':      row['requesting_branch__id'],
            'branch_name':    row['requesting_branch__name_ar'] or row['requesting_branch__name'],
            'count':          row['count'],
            'qty_total':      float(row['qty_total'] or 0),
            'rejection_rate': round(row['n_rejected'] / row['count'] * 100) if row['count'] else 0,
        })

    top_sources = []
    for row in (
        tr_win.exclude(status='cancelled')
        .values('source_branch__id', 'source_branch__name_ar', 'source_branch__name')
        .annotate(count=Count('id'),
                  n_accepted=Count('id', filter=Q(status__in=['accepted', 'partial', 'fulfilled'])),
                  n_rejected=Count('id', filter=Q(status='rejected')))
        .order_by('-count')[:8]
    ):
        top_sources.append({
            'branch_id':       row['source_branch__id'],
            'branch_name':     row['source_branch__name_ar'] or row['source_branch__name'],
            'count':           row['count'],
            'acceptance_rate': round(row['n_accepted'] / row['count'] * 100) if row['count'] else 0,
        })

    REASON_LABELS = {
        'insufficient_stock': 'مخزون غير كافٍ',
        'reserved_customers': 'محجوز لعملاء الفرع',
        'item_on_order':      'الصنف قيد الأوردر',
        'other':              'أخرى',
        '':                   'غير محدد',
    }
    rejection_reasons = [
        {
            'reason': r['rejection_reason'],
            'label':  REASON_LABELS.get(r['rejection_reason'], r['rejection_reason']),
            'count':  r['count'],
        }
        for r in (
            TR.objects.filter(created_at__gte=win, status='rejected')
            .values('rejection_reason').annotate(count=Count('id')).order_by('-count')
        )
    ]

    flagged_list = []
    for t in (
        TR.objects.filter(flagged_no_sale=True)
        .select_related('item', 'requesting_branch', 'source_branch')
        .order_by('-responded_at')[:20]
    ):
        flagged_list.append({
            'id':          t.id,
            'item_name':   t.item.name,
            'softech_id':  t.item.softech_id,
            'branch_name': t.requesting_branch.name_ar or t.requesting_branch.name,
            'source_name': t.source_branch.name_ar or t.source_branch.name,
            'qty':         float(t.quantity_approved or t.quantity_needed or 0),
            'days_since':  (now - t.responded_at).days if t.responded_at else None,
            'responded_at': t.responded_at.isoformat() if t.responded_at else None,
        })

    flow_matrix = [
        {
            'from':  r['requesting_branch__name_ar'] or r['requesting_branch__name'],
            'to':    r['source_branch__name_ar']     or r['source_branch__name'],
            'count': r['count'],
        }
        for r in (
            tr_win.exclude(status='cancelled')
            .values('requesting_branch__name_ar', 'requesting_branch__name',
                    'source_branch__name_ar',     'source_branch__name')
            .annotate(count=Count('id')).order_by('-count')[:15]
        )
    ]

    return Response({
        'window_days': days,
        'generated_at': now.isoformat(),
        'kpis': {
            'total': total, 'accepted': n_accepted, 'partial': n_partial,
            'rejected': n_rejected, 'fulfilled': n_fulfilled,
            'pending': n_pending, 'flagged': n_flagged,
            'accept_rate': accept_rate, 'avg_response_hrs': avg_hrs,
        },
        'weekly_breakdown': weekly_breakdown,
        'daily_trend':      daily_trend,
        'top_items':        top_items,
        'recommended':      recommended,
        'top_requestors':   top_requestors,
        'top_sources':      top_sources,
        'rejection_reasons': rejection_reasons,
        'flagged_list':     flagged_list,
        'flow_matrix':      flow_matrix,
    })
