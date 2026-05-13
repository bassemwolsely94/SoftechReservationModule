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
from apps.catalog.models import ItemStock, EXCLUDED_STORE_CODES
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
    stock_qs = (
        ItemStock.objects
        .filter(quantity_on_hand__gt=0, quantity_on_hand__lt=5)
        .exclude(softech_store_code__in=EXCLUDED_STORE_CODES)
        .select_related('item', 'branch')
        .order_by('quantity_on_hand')
    )
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
    transfers = {'pending': 0, 'in_erp': 0, 'this_week': 0}
    try:
        from django.apps import apps as _a
        TR = _a.get_model('transfers', 'TransferRequest')
        transfers['pending']   = TR.objects.filter(status='pending').count()
        transfers['in_erp']    = TR.objects.filter(status='sent_to_erp').count()
        transfers['this_week'] = TR.objects.filter(
            created_at__date__gte=week_start
        ).count()
        # Branch-scoped incoming transfers for branch staff
        if profile and profile.branch and profile.role not in ('admin', 'call_center', 'purchasing'):
            transfers['incoming_to_my_branch'] = TR.objects.filter(
                supplying_branch=profile.branch,
                status__in=['approved', 'sent_to_erp'],
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
            'item_name':     r.item_label,
            'softech_id':    r.item.softech_id if r.item_id else None,
            'customer_name': (
                r.customer.name if r.customer_id
                else r.contact_name or 'زبون مباشر'
            ),
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
    """
    Transfer-request analytics. Roles: admin, purchasing only.

    Uses apps.transfers.TransferRequest which has these statuses:
      draft | pending | approved | rejected | needs_revision |
      sent_to_erp | completed | cancelled
    """
    profile = _profile(request)
    if not profile or profile.role not in ('admin', 'purchasing'):
        return Response(
            {'detail': 'هذه الصفحة مخصصة لقسم المشتريات والمديرين فقط'},
            status=403,
        )

    try:
        from django.apps import apps as _a
        TR  = _a.get_model('transfers', 'TransferRequest')
        TRI = _a.get_model('transfers', 'TransferRequestItem')
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

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total       = tr_win.count()
    n_approved  = tr_win.filter(status__in=['approved', 'sent_to_erp', 'completed']).count()
    n_completed = tr_win.filter(status='completed').count()
    n_rejected  = tr_win.filter(status='rejected').count()
    n_pending   = TR.objects.filter(status='pending').count()
    n_in_erp    = TR.objects.filter(status='sent_to_erp').count()
    accept_rate = round(n_approved / total * 100, 1) if total else 0

    # Average time from creation to review
    reviewed = TR.objects.filter(
        created_at__gte=win, reviewed_at__isnull=False
    ).only('created_at', 'reviewed_at')
    avg_hrs = None
    if reviewed.exists():
        secs    = sum((t.reviewed_at - t.created_at).total_seconds() for t in reviewed)
        avg_hrs = round(secs / reviewed.count() / 3600, 1)

    weekly_breakdown = list(
        tr_week.values('status').annotate(count=Count('id')).order_by('status')
    )

    # Daily trend — last N days
    daily_trend = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).date()
        daily_trend.append({
            'date':  str(d),
            'count': TR.objects.filter(created_at__date=d).count(),
        })

    # ── Top items (via TransferRequestItem) ───────────────────────────────────
    top_items_raw = list(
        TRI.objects
        .filter(request__created_at__gte=win)
        .exclude(request__status='cancelled')
        .values('item__id', 'item__name', 'item__softech_id')
        .annotate(
            request_count  = Count('request', distinct=True),
            total_qty      = Sum('quantity'),
            approved_count = Count(
                'request',
                filter=Q(request__status__in=['approved', 'sent_to_erp', 'completed']),
                distinct=True,
            ),
            rejected_count = Count(
                'request',
                filter=Q(request__status='rejected'),
                distinct=True,
            ),
        )
        .order_by('-request_count')[:10]
    )
    top_items = []
    for row in top_items_raw:
        rc = row['request_count']
        top_items.append({
            'item_id':        row['item__id'],
            'item_name':      row['item__name'],
            'softech_id':     row['item__softech_id'],
            'request_count':  rc,
            'total_qty':      float(row['total_qty'] or 0),
            'accepted_count': row['approved_count'],
            'rejected_count': row['rejected_count'],
            'acceptance_rate': round(row['approved_count'] / rc * 100) if rc else 0,
        })

    recommended = [
        {
            'item_id':       r['item_id'],
            'item_name':     r['item_name'],
            'softech_id':    r['softech_id'],
            'request_count': r['request_count'],
            'total_qty':     r['total_qty'],
            'accept_rate':   r['acceptance_rate'],
            'reason':        f'طُلب تحويله {r["request_count"]} مرة خلال {days} يوماً',
        }
        for r in top_items if r['request_count'] >= 3
    ]

    # ── Top requesting branches ────────────────────────────────────────────────
    top_requestors = []
    for row in (
        tr_win.exclude(status='cancelled')
        .values('requesting_branch__id', 'requesting_branch__name_ar', 'requesting_branch__name')
        .annotate(
            count      = Count('id'),
            n_rejected = Count('id', filter=Q(status='rejected')),
        )
        .order_by('-count')[:8]
    ):
        top_requestors.append({
            'branch_id':      row['requesting_branch__id'],
            'branch_name':    row['requesting_branch__name_ar'] or row['requesting_branch__name'],
            'count':          row['count'],
            'rejection_rate': round(row['n_rejected'] / row['count'] * 100) if row['count'] else 0,
        })

    # ── Top supplying branches ─────────────────────────────────────────────────
    top_sources = []
    for row in (
        tr_win.exclude(status='cancelled')
        .filter(supplying_branch__isnull=False)
        .values('supplying_branch__id', 'supplying_branch__name_ar', 'supplying_branch__name')
        .annotate(
            count      = Count('id'),
            n_approved = Count('id', filter=Q(status__in=['approved', 'sent_to_erp', 'completed'])),
            n_rejected = Count('id', filter=Q(status='rejected')),
        )
        .order_by('-count')[:8]
    ):
        top_sources.append({
            'branch_id':       row['supplying_branch__id'],
            'branch_name':     row['supplying_branch__name_ar'] or row['supplying_branch__name'],
            'count':           row['count'],
            'acceptance_rate': round(row['n_approved'] / row['count'] * 100) if row['count'] else 0,
        })

    # ── Rejection reasons (free-text field on TransferRequest) ────────────────
    rejection_notes = list(
        TR.objects.filter(created_at__gte=win, status='rejected')
        .exclude(rejection_reason='')
        .values_list('rejection_reason', flat=True)[:50]
    )

    # ── Flow matrix (requesting → supplying) ──────────────────────────────────
    flow_matrix = [
        {
            'from':  r['requesting_branch__name_ar'] or r['requesting_branch__name'],
            'to':    r['supplying_branch__name_ar']  or r['supplying_branch__name'],
            'count': r['count'],
        }
        for r in (
            tr_win
            .exclude(status='cancelled')
            .filter(supplying_branch__isnull=False)
            .values(
                'requesting_branch__name_ar', 'requesting_branch__name',
                'supplying_branch__name_ar',  'supplying_branch__name',
            )
            .annotate(count=Count('id')).order_by('-count')[:15]
        )
    ]

    return Response({
        'window_days':  days,
        'generated_at': now.isoformat(),
        'kpis': {
            'total':            total,
            'approved':         n_approved,
            'completed':        n_completed,
            'rejected':         n_rejected,
            'pending':          n_pending,
            'in_erp':           n_in_erp,
            'accept_rate':      accept_rate,
            'avg_review_hrs':   avg_hrs,
        },
        'weekly_breakdown':  weekly_breakdown,
        'daily_trend':       daily_trend,
        'top_items':         top_items,
        'recommended':       recommended,
        'top_requestors':    top_requestors,
        'top_sources':       top_sources,
        'rejection_notes':   rejection_notes,
        'flow_matrix':       flow_matrix,
    })
