"""
apps/demand/service.py

Service layer for the Demand Engine.
ALL business logic lives here — views just call service functions.
This ensures clean separation and testability.
"""
from django.utils import timezone
from django.db import transaction
from datetime import timedelta


# ── ERP Customer Lookup ───────────────────────────────────────────────────────

def lookup_customer_in_erp(phone=None, phcode=None):
    """
    Look up a customer in the Sybase ERP localcustomers table.
    Returns dict with {phcode, customer_name, phone, erp_branch_code} or None.

    phcode format: "140HD515"
      - "140" = branch code
      - "HD"  = customer type
      - "515" = customer ID
    """
    try:
        from apps.sync.connection import get_sybase_connection
        conn = get_sybase_connection()
        cursor = conn.cursor()

        conditions = []
        params = []

        if phcode:
            conditions.append("lc.ptcode = ?")
            params.append(phcode)

        if phone and not phcode:
            # Search in personphones table
            conditions.append("""
                lc.personid IN (
                    SELECT personid FROM personphones
                    WHERE phonenumber LIKE ? AND phonetype IN ('40','10','20')
                )
            """)
            params.append(f'%{phone.replace(" ", "").replace("-", "")}%')

        if not conditions:
            return None

        where = " OR ".join(conditions)
        sql = f"""
            SELECT TOP 1
                lc.ptcode,
                lc.personname,
                lc.branchcode,
                ISNULL(pp.phonenumber, '')
            FROM localcustomers lc
            LEFT JOIN personphones pp ON pp.personid = lc.personid
                AND pp.phonetype = '40'
            WHERE {where}
        """
        cursor.execute(sql, params)
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        phcode_val = str(row[0] or '').strip()
        return {
            'phcode':          phcode_val,
            'customer_name':   str(row[1] or '').strip(),
            'erp_branch_code': str(row[2] or '').strip(),
            'phone':           str(row[3] or '').strip(),
        }
    except Exception as e:
        import logging
        logging.getLogger('elrezeiky.demand').warning(f'ERP lookup failed: {e}')
        return None


def enrich_demand_from_erp(demand):
    """
    Try to populate phcode and customer link from ERP.
    Called on create and by background task.
    """
    result = lookup_customer_in_erp(
        phone=demand.phone,
        phcode=demand.phcode or None,
    )
    if result:
        update_fields = []
        if not demand.phcode and result['phcode']:
            demand.phcode = result['phcode']
            update_fields.append('phcode')
        if not demand.erp_branch_code and result['erp_branch_code']:
            demand.erp_branch_code = result['erp_branch_code']
            update_fields.append('erp_branch_code')
        if result['customer_name'] and demand.customer_name in ('', 'عميل'):
            demand.customer_name = result['customer_name']
            update_fields.append('customer_name')
        if update_fields:
            demand.save(update_fields=update_fields)

    # Try linking to local Customer model
    demand.try_link_customer()
    return result


# ── Demand creation ───────────────────────────────────────────────────────────

@transaction.atomic
def create_demand(*, phone, customer_name, branch, created_by,
                  source='walk_in', priority='normal', notes='',
                  phcode='', items_data=None, follow_up_date=None):
    """
    Main entry point for creating a demand record.
    items_data: list of dicts {item_id, quantity, demand_type, notes}
    """
    from .models import DemandRecord, DemandItem, DemandLog

    demand = DemandRecord.objects.create(
        phone=phone,
        customer_name=customer_name,
        phcode=phcode,
        branch=branch,
        created_by=created_by,
        source=source,
        priority=priority,
        notes=notes,
        status='new',
        follow_up_date=follow_up_date,
    )

    # Add items
    for item_data in (items_data or []):
        DemandItem.objects.create(
            demand=demand,
            item_id=item_data.get('item'),
            item_name_free=item_data.get('item_name_free', ''),
            quantity=item_data.get('quantity', 1),
            demand_type=item_data.get('demand_type', 'out_of_stock'),
            notes=item_data.get('notes', ''),
        )

    # System log
    DemandLog.system(demand, f'تم إنشاء الطلب بواسطة {created_by.full_name if created_by else "النظام"}')

    # Try ERP enrichment (non-blocking)
    try:
        enrich_demand_from_erp(demand)
    except Exception:
        pass

    # Auto-schedule follow-up
    schedule_followup(demand, hours_from_now=2, created_by=created_by)

    # Fire notification
    _notify_new_demand(demand)

    return demand


# ── State machine transitions ─────────────────────────────────────────────────

VALID_TRANSITIONS = {
    'new':                 ['assigned', 'cancelled'],
    'assigned':            ['follow_up', 'stock_eta', 'transfer_suggested', 'purchasing_flagged', 'fulfilled', 'lost', 'cancelled'],
    'follow_up':           ['follow_up', 'stock_eta', 'transfer_suggested', 'purchasing_flagged', 'fulfilled', 'lost', 'cancelled'],
    'stock_eta':           ['follow_up', 'fulfilled', 'lost', 'cancelled'],
    'transfer_suggested':  ['follow_up', 'fulfilled', 'lost', 'cancelled'],
    'purchasing_flagged':  ['follow_up', 'stock_eta', 'fulfilled', 'lost', 'cancelled'],
    'fulfilled':           [],
    'lost':                [],
    'cancelled':           [],
}


@transaction.atomic
def transition_status(demand, new_status, by=None, note='', **kwargs):
    """
    Execute a status transition with full validation and side effects.
    kwargs: lost_reason, erp_invoice_ref, etc.
    """
    from .models import DemandLog

    old_status = demand.status

    if new_status not in VALID_TRANSITIONS.get(old_status, []):
        raise ValueError(
            f'لا يمكن الانتقال من "{demand.get_status_display()}" إلى "{new_status}"'
        )

    # Apply state-specific side effects
    now = timezone.now()

    if new_status == 'assigned' and not demand.assigned_at:
        demand.assigned_at = now
        if kwargs.get('assigned_to'):
            demand.assigned_to = kwargs['assigned_to']

    if new_status == 'fulfilled':
        demand.fulfilled_at = now
        demand.erp_invoice_ref = kwargs.get('erp_invoice_ref', '')
        # Mark all pending items as fulfilled
        demand.items.filter(item_status='pending').update(item_status='fulfilled')

    if new_status == 'lost':
        demand.lost_reason = kwargs.get('lost_reason', '')
        demand.items.filter(item_status='pending').update(item_status='lost')

    demand.status = new_status
    demand.save()

    # Log the transition
    DemandLog.status_change(demand, old_status, new_status, by=by, note=note)

    # Update demand stats
    try:
        _update_item_stats(demand)
    except Exception:
        pass

    # Notifications
    _notify_status_change(demand, old_status, new_status)

    return demand


# ── Follow-up scheduling ──────────────────────────────────────────────────────

def schedule_followup(demand, hours_from_now=24, task_type='call',
                      assigned_to=None, note='', created_by=None):
    """Create a follow-up task for a demand record."""
    from .models import FollowUpTask, DemandLog

    due = timezone.now() + timedelta(hours=hours_from_now)

    task = FollowUpTask.objects.create(
        demand=demand,
        task_type=task_type,
        due_date=due,
        assigned_to=assigned_to or demand.assigned_to,
        note=note,
    )

    DemandLog.system(
        demand,
        f'تم جدولة متابعة ({task.get_task_type_display()}) في {due.strftime("%d/%m %H:%M")}'
    )

    # Update the demand's follow_up_date
    if not demand.follow_up_date or demand.follow_up_date < due.date():
        demand.follow_up_date = due.date()
        demand.save(update_fields=['follow_up_date'])

    return task


@transaction.atomic
def complete_followup(task, outcome, note='', completed_by=None):
    """Mark a follow-up task as done and log the outcome."""
    from .models import DemandLog

    task.status = 'done'
    task.completed_at = timezone.now()
    task.completed_by = completed_by
    task.note = note
    task.save()

    DemandLog.objects.create(
        demand=task.demand,
        log_type='call',
        message=f'متابعة ({task.get_task_type_display()}): {outcome or note}',
        created_by=completed_by,
    )

    return task


# ── Demand intelligence ───────────────────────────────────────────────────────

def _update_item_stats(demand):
    """Update ItemDemandStat for all items in this demand record."""
    from .models import ItemDemandStat, DemandItem
    from django.db.models import Count, Sum, Q
    from datetime import date, timedelta

    cutoff = timezone.now() - timedelta(days=30)
    branch = demand.branch

    items = demand.items.filter(item__isnull=False).select_related('item')
    for demand_item in items:
        item = demand_item.item
        qs = DemandItem.objects.filter(item=item, demand__branch=branch, demand__created_at__gte=cutoff)

        agg = qs.aggregate(
            total=Count('id'),
            lost=Count('id', filter=Q(item_status='lost')),
            fulfilled=Count('id', filter=Q(item_status='fulfilled')),
            lost_qty=Sum('quantity', filter=Q(item_status='lost')),
        )

        stat, _ = ItemDemandStat.objects.get_or_create(item=item, branch=branch)
        stat.demand_count_30d    = agg['total'] or 0
        stat.lost_count_30d      = agg['lost'] or 0
        stat.fulfilled_count_30d = agg['fulfilled'] or 0
        stat.lost_qty_30d        = agg['lost_qty'] or 0
        # Suggest purchasing if lost > 3 times in 30 days
        stat.suggest_order = stat.lost_count_30d >= 3
        stat.save()


# ── Notifications ─────────────────────────────────────────────────────────────

def _notify_new_demand(demand):
    """Notify call center and branch manager of new demand."""
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile

        title = f'طلب جديد — {demand.customer_name}'
        body = (
            f'📞 {demand.phone} | '
            f'فرع {demand.branch.name_ar or demand.branch.name} | '
            f'{demand.items.count()} صنف'
        )

        recipients = StaffProfile.objects.filter(
            is_active=True,
        ).filter(
            models.Q(role__in=('admin', 'call_center')) |
            models.Q(branch=demand.branch, role__in=('pharmacist', 'salesperson'))
        ).distinct()

        for staff in recipients:
            Notification.objects.create(
                recipient=staff,
                title=title,
                body=body or '',
                notification_type='reservation_created',
            )
    except Exception:
        pass


def _notify_status_change(demand, old_status, new_status):
    """Notify relevant staff when demand status changes."""
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile

        if new_status in ('fulfilled', 'lost', 'cancelled'):
            return  # No notification for terminal states

        if new_status == 'stock_eta' or new_status == 'follow_up':
            title = f'متابعة مطلوبة — {demand.customer_name} ({demand.demand_number})'
            body = f'الحالة: {demand.get_status_display()}'
            recipients = StaffProfile.objects.filter(
                is_active=True,
            ).filter(
                models.Q(id=demand.assigned_to_id) |
                models.Q(branch=demand.branch, role='call_center')
            ).distinct()
            for staff in recipients:
                try:
                    Notification.objects.create(
                        recipient=staff,
                        title=title,
                        body=body or '',
                        notification_type='follow_up_due',
                    )
                except Exception:
                    pass
    except Exception:
        pass
