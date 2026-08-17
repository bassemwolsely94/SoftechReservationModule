"""
apps/demand/service.py

Service layer for the Demand Engine.
ALL business logic lives here — views just call service functions.
This ensures clean separation and testability.
"""
from django.utils import timezone
from django.db import transaction, models
from django.db.models import Exists, OuterRef
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
        from config.sybase import get_sybase_connection
        conn = get_sybase_connection()
        cursor = conn.cursor()

        # Real SOFTECH schema (see apps/sync/sybase_queries.py):
        #   localcustomers: phcode (PIC), branchcustname, branchcode, mobileno, branchcustphone
        #   personphones:   personcode (= lc.phcode), phoneno, phoneblock
        # Sybase/jConnect quirks: NO `TOP n` and NO `IN (list)` in prepared
        # statements; CHAR columns carry trailing spaces → RTRIM on equality.
        conditions = []
        params = []

        if phcode:
            conditions.append("RTRIM(lc.phcode) = ?")
            params.append(phcode.strip())

        if phone and not phcode:
            cleaned = phone.replace(" ", "").replace("-", "")
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM SOFTECHDB9.dbo.personphones ph
                    WHERE ph.personcode = lc.phcode
                      AND ph.phoneblock = 0
                      AND ph.phoneno LIKE ?
                )
            """)
            params.append(f'%{cleaned}%')

        if not conditions:
            return None

        where = " OR ".join(conditions)
        # No TOP — fetchone() takes the first match (single-customer lookup).
        sql = f"""
            SELECT lc.phcode,
                   lc.branchcustname,
                   lc.branchcode,
                   ISNULL(lc.mobileno, lc.branchcustphone)
            FROM SOFTECHDB9.dbo.localcustomers lc
            WHERE {where}
        """
        cursor.execute(sql, params)
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            'phcode':          str(row[0] or '').strip(),
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
        di_kwargs = dict(
            demand=demand,
            item_id=item_data.get('item'),
            item_name_free=item_data.get('item_name_free', ''),
            quantity=item_data.get('quantity', 1),
            demand_type=item_data.get('demand_type', 'out_of_stock'),
            notes=item_data.get('notes', ''),
            substitute_for_item_id=item_data.get('substitute_for_item'),
        )
        # Uncoded item with a hand-entered pack value → store it, flagged manual
        # (so the UI never presents it as an ERP-sourced figure).
        manual_price = item_data.get('manual_price')
        if not item_data.get('item') and manual_price not in (None, ''):
            di_kwargs.update(
                unit_price_snapshot=manual_price,
                price_is_manual=True,
                price_snapshot_at=timezone.now(),
            )
        DemandItem.objects.create(**di_kwargs)

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
    from .models import DemandFollowUp, DemandLog

    due = timezone.now() + timedelta(hours=hours_from_now)

    task = DemandFollowUp.objects.create(
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

    # Value-weighted buy signal threshold (config-driven, EGP). A real customer
    # asking is the highest-confidence buy signal — flag on count OR on lost value.
    try:
        from apps.config.services import get_setting
        value_threshold = float(get_setting('demand_suggest_order_value_threshold', default='1000'))
    except (ValueError, TypeError):
        value_threshold = 1000.0

    items = demand.items.filter(item__isnull=False).select_related('item')
    for demand_item in items:
        item = demand_item.item
        qs = DemandItem.objects.filter(item=item, demand__branch=branch, demand__created_at__gte=cutoff)

        agg = qs.aggregate(
            total=Count('id'),
            lost=Count('id', filter=Q(item_status='lost')),
            fulfilled=Count('id', filter=Q(item_status='fulfilled')),
            lost_qty=Sum('quantity', filter=Q(item_status='lost')),
            lost_value=Sum(
                models.F('quantity') * models.F('unit_price_snapshot'),
                filter=Q(item_status='lost', unit_price_snapshot__isnull=False),
            ),
            open_qty=Sum('quantity', filter=Q(
                item_status__in=['pending', 'sourcing', 'available_again'])),
        )

        stat, _ = ItemDemandStat.objects.get_or_create(item=item, branch=branch)
        stat.demand_count_30d    = agg['total'] or 0
        stat.lost_count_30d      = agg['lost'] or 0
        stat.fulfilled_count_30d = agg['fulfilled'] or 0
        stat.lost_qty_30d        = agg['lost_qty'] or 0
        stat.lost_value_30d      = agg['lost_value'] or 0
        # Suggested purchase qty = unmet demand still open + already lost units.
        stat.suggested_order_qty = (agg['open_qty'] or 0) + (agg['lost_qty'] or 0)
        # Suggest purchasing if lost ≥3 times OR lost value crosses the threshold.
        stat.suggest_order = (
            stat.lost_count_30d >= 3
            or float(stat.lost_value_30d or 0) >= value_threshold
        )
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
                notification_type='demand_created',
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
                        notification_type='demand_follow_up',
                    )
                except Exception:
                    pass
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — Back-in-stock recovery loop
# ══════════════════════════════════════════════════════════════════════════════

@transaction.atomic
def detect_restocked_demand():
    """
    Post-sync sweep (§5.3). For every recovery-eligible demand line whose item is
    now back in stock at the demand's branch, flag it `available_again`, stamp
    `back_in_stock_at`, open a `stock_check` follow-up, log it, and notify staff.

    Idempotent: lines already `available_again` are excluded by the status filter,
    so re-running on the next sync does not re-flag or re-notify them.
    Returns the number of lines newly flagged.
    """
    from apps.catalog.models import ItemStock
    from .models import DemandItem, DemandLog

    stock_now = ItemStock.objects.filter(
        item_id=OuterRef('item_id'),
        branch_id=OuterRef('demand__branch_id'),
        quantity_on_hand__gt=0,
    )
    candidates = (
        DemandItem.objects.recovery_eligible()
        .filter(item_status__in=['pending', 'sourcing', 'lost'])   # not yet flagged
        .filter(Exists(stock_now))
        .select_related('demand', 'demand__branch', 'item', 'demand__assigned_to')
    )

    now = timezone.now()
    flagged = 0
    for di in candidates:
        di.item_status     = 'available_again'
        di.back_in_stock_at = now
        di.save(update_fields=['item_status', 'back_in_stock_at'])
        DemandLog.system(
            di.demand,
            f'🔔 عاد للمخزون: {di.item_display_name} — جاهز لاسترداد العميل',
        )
        # Immediate stock-check follow-up so the line lands on a worklist today.
        schedule_followup(
            di.demand, hours_from_now=0, task_type='stock_check',
            note=f'صنف {di.item_display_name} عاد للمخزون — تواصل مع العميل',
            created_by=None,
        )
        _notify_back_in_stock(di)
        _auto_whatsapp_restock(di)   # opt-in, gated; respects contact_opt_out
        flagged += 1

    return flagged


def _auto_whatsapp_restock(demand_item):
    """Auto-send a back-in-stock WhatsApp to the customer — opt-in & gated.

    Only fires when `demand_auto_whatsapp_enabled` config is on. The caller only
    passes recovery-eligible lines, so opted-out/disqualified customers are never
    contacted. Uses a configured Meta template if set, else a plain-text message
    (best-effort within the 24h session window). Never raises.
    """
    try:
        from apps.config.services import get_setting
        if get_setting('demand_auto_whatsapp_enabled', default='false').strip().lower() not in ('true', '1', 'yes'):
            return False
        if demand_item.contact_opt_out:
            return False
        demand = demand_item.demand
        phone = (demand.phone or '').strip()
        if not phone:
            return False

        from apps.whatsapp.sender import WhatsAppSender
        from .models import DemandLog
        branch = demand.branch
        branch_name = (branch.name_ar or branch.name) if branch else ''
        template = get_setting('demand_restock_whatsapp_template', default='').strip()

        sender = WhatsAppSender()
        if template:
            sender.send_template(
                wa_id=phone, template_name=template,
                variables=[
                    {'type': 'text', 'text': demand_item.item_display_name},
                    {'type': 'text', 'text': branch_name or '—'},
                ],
            )
        else:
            msg = (
                f'السلام عليكم {demand.customer_name or ""}،\n'
                f'صنف "{demand_item.item_display_name}" الذي طلبته أصبح متوفراً الآن'
                f'{" في فرع " + branch_name if branch_name else ""}.\n'
                'يسعدنا خدمتك — صيدليات الرزيقي.'
            )
            sender.send_text(wa_id=phone, body=msg)

        demand_item.notified_customer_at = timezone.now()
        demand_item.save(update_fields=['notified_customer_at'])
        DemandLog.objects.create(
            demand=demand, log_type='whatsapp', created_by=None,
            message=f'🤖 إشعار تلقائي عبر واتساب: توفر {demand_item.item_display_name}',
        )
        return True
    except Exception as exc:
        import logging
        logging.getLogger('elrezeiky.demand').warning('auto-whatsapp restock failed: %s', exc)
        return False


def _notify_back_in_stock(demand_item):
    """Notify the assignee + branch staff that a wanted item is back in stock."""
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile

        demand = demand_item.demand
        branch = demand.branch
        value  = demand_item.line_value
        title  = f'🔔 عاد للمخزون — {demand_item.item_display_name}'
        body   = (
            f'العميل {demand.customer_name or demand.phone} طلب هذا الصنف '
            f'({demand.demand_number}). '
            + (f'قيمة محتملة: {value:.0f} ج.م. ' if value else '')
            + 'تواصل معه لاسترداد البيعة.'
        )
        dedup = f'demand_back_in_stock:{demand_item.id}'

        recipients = StaffProfile.objects.filter(is_active=True).filter(
            models.Q(id=demand.assigned_to_id) |
            models.Q(role__in=('admin', 'call_center')) |
            models.Q(branch=branch, role__in=('pharmacist', 'salesperson'))
        ).distinct()

        for staff in recipients:
            try:
                Notification.objects.create(
                    recipient=staff, title=title, body=body,
                    notification_type='demand_back_in_stock',
                    dedup_key=dedup, demand_id_ref=demand.id,
                )
            except Exception:
                pass
    except Exception:
        pass


@transaction.atomic
def mark_recovered(demand_item, revenue=None, by=None):
    """Close the loop: customer came back and bought. Captures recovered EGP (ROI)."""
    from .models import DemandLog

    if revenue is None:
        revenue = demand_item.line_value   # may be None for free-text items
    demand_item.item_status      = 'recovered'
    demand_item.recovered_at      = timezone.now()
    demand_item.recovered_revenue = revenue
    demand_item.save(update_fields=['item_status', 'recovered_at', 'recovered_revenue'])

    val = f'{float(revenue):.0f} ج.م' if revenue else '—'
    DemandLog.objects.create(
        demand=demand_item.demand, log_type='system',
        message=f'💰 تم استرداد البيعة: {demand_item.item_display_name} — {val}',
        created_by=by,
    )
    return demand_item


def mark_notified(demand_item, channel='whatsapp', by=None):
    """Stamp the last outreach time (drives the monthly-reminder cadence) and log it."""
    from .models import DemandLog
    demand_item.notified_customer_at = timezone.now()
    demand_item.save(update_fields=['notified_customer_at'])
    log_type = {'whatsapp': 'whatsapp', 'call': 'call', 'sms': 'sms'}.get(channel, 'note')
    DemandLog.objects.create(
        demand=demand_item.demand, log_type=log_type,
        message=f'📤 تم التواصل مع العميل بخصوص توفر {demand_item.item_display_name}',
        created_by=by,
    )
    return demand_item


@transaction.atomic
def disqualify_item(demand_item, reason, by=None):
    """Approval-gated removal from the recovery loop (§5.8)."""
    from .models import DemandLog
    demand_item.disqualified        = True
    demand_item.disqualified_reason = reason
    demand_item.disqualified_by      = by
    demand_item.disqualified_at      = timezone.now()
    demand_item.save(update_fields=[
        'disqualified', 'disqualified_reason', 'disqualified_by', 'disqualified_at',
    ])
    label = dict(demand_item.DISQUALIFY_REASONS).get(reason, reason)
    DemandLog.objects.create(
        demand=demand_item.demand, log_type='system',
        message=f'🚫 استُبعِد من الاسترداد: {demand_item.item_display_name} — {label}',
        created_by=by,
    )
    return demand_item


@transaction.atomic
def requalify_item(demand_item, by=None):
    """Reverse a disqualification (same approval permission)."""
    from .models import DemandLog
    demand_item.disqualified        = False
    demand_item.disqualified_reason = ''
    demand_item.disqualified_by      = None
    demand_item.disqualified_at      = None
    demand_item.save(update_fields=[
        'disqualified', 'disqualified_reason', 'disqualified_by', 'disqualified_at',
    ])
    DemandLog.objects.create(
        demand=demand_item.demand, log_type='system',
        message=f'↩️ أُعيد للاسترداد: {demand_item.item_display_name}',
        created_by=by,
    )
    return demand_item


@transaction.atomic
def opt_out_item(demand_item, reason='', by=None):
    """Record an item-level contact opt-out after first follow-up (§5.10)."""
    from .models import DemandLog
    demand_item.contact_opt_out        = True
    demand_item.contact_opt_out_reason = reason
    demand_item.contact_opt_out_at      = timezone.now()
    demand_item.save(update_fields=[
        'contact_opt_out', 'contact_opt_out_reason', 'contact_opt_out_at',
    ])
    label = dict(demand_item.OPT_OUT_REASONS).get(reason, reason or '—')
    DemandLog.objects.create(
        demand=demand_item.demand, log_type='system',
        message=f'🔕 رفض العميل التواصل بخصوص: {demand_item.item_display_name} — {label}',
        created_by=by,
    )
    return demand_item


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Therapeutic substitution at capture (§7.2)
# ══════════════════════════════════════════════════════════════════════════════

# SAFETY: catalog scientific names are dirty. Placeholder values group hundreds
# of unrelated products under one "molecule" — suggesting them as substitutes
# would be dangerous in a pharmacy. Reject placeholders, and reject any molecule
# whose group is implausibly large for a real INN.
_PLACEHOLDER_SCIENTIFIC = {
    '', '-', '--', '0', '.', 'undefined', 'undefined item', 'غير محدد',
    'na', 'n/a', 'none', 'null', 'unknown', 'غير معروف',
}
_MAX_MOLECULE_GROUP = 40   # > this sharing a name = junk placeholder, not a molecule


def find_substitutes(item, branch=None, network=False, limit=8):
    """In-stock catalog items sharing the same scientific molecule as `item`.

    Used at capture to convert a stockout into a sale NOW. By default returns
    items in stock at `branch`; pass network=True to consider all branches.
    Returns a list of dicts sorted by stock (desc). Empty if the item has no
    (real) scientific name. 2–3 queries total regardless of candidate count.
    """
    from apps.catalog.models import Item, ItemStock

    scientific = (getattr(item, 'name_scientific', '') or '').strip()
    if not scientific or scientific.lower() in _PLACEHOLDER_SCIENTIFIC:
        return []

    # Fetch one more than the cap so we can detect (and reject) junk groupings.
    cand_ids = list(
        Item.objects.filter(name_scientific__iexact=scientific, is_active=True)
        .exclude(pk=item.pk)
        .values_list('id', flat=True)[:_MAX_MOLECULE_GROUP + 1]
    )
    if not cand_ids or len(cand_ids) > _MAX_MOLECULE_GROUP:
        return []

    branch_stock = {}
    if branch is not None:
        for s in ItemStock.objects.filter(item_id__in=cand_ids, branch=branch).values('item_id', 'quantity_on_hand'):
            branch_stock[s['item_id']] = float(s['quantity_on_hand'])

    net_stock = {}
    for s in (ItemStock.objects.filter(item_id__in=cand_ids)
              .values('item_id').annotate(t=models.Sum('quantity_on_hand'))):
        net_stock[s['item_id']] = float(s['t'] or 0)

    cands = {
        c['id']: c for c in
        Item.objects.filter(id__in=cand_ids).values('id', 'name', 'softech_id', 'pack_price')
    }

    results = []
    for cid in cand_ids:
        sb  = branch_stock.get(cid, 0.0)
        net = net_stock.get(cid, 0.0)
        in_stock = (net > 0) if (network or branch is None) else (sb > 0)
        if not in_stock:
            continue
        c = cands.get(cid, {})
        results.append({
            'id':              cid,
            'name':            c.get('name', ''),
            'softech_id':      c.get('softech_id', ''),
            'pack_price':      float(c.get('pack_price') or 0),
            'stock_at_branch': sb,
            'stock_network':   net,
        })

    results.sort(key=lambda r: (r['stock_at_branch'], r['stock_network']), reverse=True)
    return results[:limit]


def escalate_stale_recoveries():
    """Escalate back-in-stock opportunities that have sat uncontacted too long.

    Any `available_again` line flagged > N hours ago (config
    `demand_recovery_escalation_hours`, default 24) with no recent customer
    contact is escalated to supervisors/admins. De-duplicated so it escalates at
    most once per window (checks for a prior escalation notification). Returns the
    number escalated. Designed to run hourly from the scheduler.
    """
    from datetime import timedelta
    from apps.config.services import get_setting
    from apps.notifications.models import Notification
    from apps.users.models import StaffProfile
    from .models import DemandItem, DemandLog

    try:
        hours = float(get_setting('demand_recovery_escalation_hours', default='24'))
    except (ValueError, TypeError):
        hours = 24.0
    cutoff = timezone.now() - timedelta(hours=hours)

    items = (
        DemandItem.objects.awaiting_winback()
        .filter(back_in_stock_at__lt=cutoff)
        .filter(models.Q(notified_customer_at__isnull=True) |
                models.Q(notified_customer_at__lt=cutoff))
        .select_related('demand', 'demand__branch', 'item')
    )

    escalated = 0
    for di in items:
        dedup = f'recovery_escalation:{di.id}'
        # Already escalated within this window? skip (no hourly spam).
        if Notification.objects.filter(dedup_key=dedup, created_at__gte=cutoff).exists():
            continue
        demand = di.demand
        value  = di.line_value
        title  = f'⏫ تصعيد استرداد متأخر — {di.item_display_name}'
        body   = (
            f'فرصة استرداد لم تُعالَج منذ أكثر من {int(hours)} ساعة. '
            f'العميل {demand.customer_name or demand.phone} ({demand.demand_number}). '
            + (f'قيمة محتملة {value:.0f} ج.م.' if value else '')
        )
        recipients = StaffProfile.objects.filter(is_active=True).filter(
            models.Q(role__in=('admin', 'supervisor')) |
            models.Q(branch=demand.branch, role='supervisor')
        ).distinct()
        for staff in recipients:
            try:
                Notification.objects.create(
                    recipient=staff, title=title, body=body,
                    notification_type='demand_back_in_stock',
                    dedup_key=dedup, demand_id_ref=demand.id,
                )
            except Exception:
                pass
        DemandLog.system(demand, f'⏫ تصعيد فرصة استرداد متأخرة: {di.item_display_name}')
        escalated += 1

    return escalated


def escalate_breached_demand_sla():
    """Push SLA-breach escalations for demand records stuck in intake (TD-C003).

    Two tiers, from DemandRecord.SLA_MINUTES:
      • 'new'      — created but not assigned within N minutes (default 10)
      • 'assigned' — assigned but not progressed within N minutes (default 20)

    Recipients are tiered:
      • new      → call-center + supervisors/admins + branch supervisor (whoever
                   should assign it)
      • assigned → the assignee + supervisors/admins + branch supervisor
                   (escalate above the person sitting on it)

    Re-escalates at most once per `demand_sla_repeat_minutes` (config, default 60)
    per record+tier, deduped via Notification.dedup_key — so an hourly run alerts
    once on first breach and once per hour thereafter until the record moves on.
    Writes a DemandLog.system audit line on each fire. Returns the count escalated.

    Designed to run hourly from the scheduler.
    """
    from datetime import timedelta
    from apps.config.services import get_setting
    from apps.notifications.models import Notification
    from apps.users.models import StaffProfile
    from .models import DemandRecord, DemandLog

    now = timezone.now()
    try:
        repeat_minutes = int(get_setting('demand_sla_repeat_minutes', default='60'))
    except (ValueError, TypeError):
        repeat_minutes = 60
    repeat_cutoff = now - timedelta(minutes=repeat_minutes)

    new_cutoff      = now - timedelta(minutes=DemandRecord.SLA_MINUTES['new'])
    assigned_cutoff = now - timedelta(minutes=DemandRecord.SLA_MINUTES['assigned'])

    breached = DemandRecord.objects.filter(
        models.Q(status='new', created_at__lt=new_cutoff) |
        models.Q(status='assigned', assigned_at__lt=assigned_cutoff)
    ).select_related('branch', 'assigned_to', 'assigned_to__user')

    escalated = 0
    for demand in breached:
        tier  = demand.status                       # 'new' | 'assigned'
        dedup = f'demand_sla:{demand.id}:{tier}'
        # Already escalated within the repeat window? skip (no hourly spam).
        if Notification.objects.filter(dedup_key=dedup, created_at__gte=repeat_cutoff).exists():
            continue

        deadline    = demand.sla_deadline
        overdue_min = int((now - deadline).total_seconds() / 60) if deadline else 0
        branch_name = (demand.branch.name_ar or demand.branch.name) if demand.branch_id else '—'
        who         = demand.customer_name or demand.phone

        if tier == 'new':
            title = f'⏰ تجاوز SLA — لم يُعيَّن: {demand.demand_number}'
            body  = (
                f'طلب لم يُعيَّن منذ {overdue_min} دقيقة '
                f'(الحد {DemandRecord.SLA_MINUTES["new"]} د). '
                f'{who} — فرع {branch_name}.'
            )
            recipients = StaffProfile.objects.filter(is_active=True).filter(
                models.Q(role__in=('admin', 'supervisor', 'call_center')) |
                models.Q(branch=demand.branch, role='supervisor')
            ).distinct()
        else:  # 'assigned'
            assignee_name = (
                demand.assigned_to.full_name
                if demand.assigned_to_id and demand.assigned_to else '—'
            )
            title = f'⏰ تجاوز SLA — متوقف: {demand.demand_number}'
            body  = (
                f'طلب مُعيَّن لـ {assignee_name} ولم يتقدّم منذ {overdue_min} دقيقة '
                f'(الحد {DemandRecord.SLA_MINUTES["assigned"]} د). {who}.'
            )
            recipients = StaffProfile.objects.filter(is_active=True).filter(
                models.Q(id=demand.assigned_to_id) |
                models.Q(role__in=('admin', 'supervisor')) |
                models.Q(branch=demand.branch, role='supervisor')
            ).distinct()

        for staff in recipients:
            try:
                Notification.send_to_user(
                    staff, 'demand_sla_breach',
                    title=title, body=body,
                    demand_id=demand.id,
                    dedup_key=dedup,
                )
            except Exception:
                pass
        DemandLog.system(
            demand,
            f'⏰ تصعيد SLA ({demand.get_status_display()}) — متأخر {overdue_min} دقيقة',
        )
        escalated += 1

    return escalated


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1b — Demand ↔ Reservation bridge (§5.9)
# ══════════════════════════════════════════════════════════════════════════════

# demand priority → reservation priority
_DEMAND_TO_RES_PRIORITY = {
    'low': 'normal', 'normal': 'normal', 'high': 'high',
    'urgent': 'urgent', 'chronic': 'chronic',
}


@transaction.atomic
def convert_item_to_reservation(demand_item, by=None, status='available'):
    """Forward bridge: turn a recovered demand line into a Reservation (hold for
    pickup now that the item is in stock). Links DemandItem.reservation and marks
    the line recovered. Idempotent — returns the existing reservation if already
    linked. We *link*, never fork intake (respects DUP-001)."""
    from apps.reservations.models import Reservation, ReservationActivity
    from .models import DemandLog

    if demand_item.reservation_id:
        return demand_item.reservation

    demand = demand_item.demand
    res = Reservation.objects.create(
        branch=demand.branch,
        item=demand_item.item,
        manual_item_name=demand_item.item_name_free or '',
        quantity_requested=demand_item.quantity,
        contact_phone=demand.phone,
        contact_name=demand.customer_name or '',
        customer=demand.customer,
        status=status,
        priority=_DEMAND_TO_RES_PRIORITY.get(demand.priority, 'normal'),
        notes=f'محوّل من طلب ضائع {demand.demand_number} بعد عودة الصنف للمخزون',
        created_by=by,
    )
    ReservationActivity.objects.create(
        reservation=res,
        activity_type='status_changed',
        message=f'🔄 أُنشئ من طلب ضائع {demand.demand_number} (استرداد بعد عودة الصنف للمخزون)',
    )

    demand_item.reservation     = res
    demand_item.item_status      = 'recovered'
    demand_item.recovered_at      = timezone.now()
    if demand_item.recovered_revenue is None:
        demand_item.recovered_revenue = demand_item.line_value
    demand_item.save(update_fields=[
        'reservation', 'item_status', 'recovered_at', 'recovered_revenue',
    ])

    DemandLog.objects.create(
        demand=demand, log_type='system',
        message=f'🔄 تم تحويل {demand_item.item_display_name} إلى حجز #{res.id}',
        created_by=by,
    )
    return res


@transaction.atomic
def create_lost_demand_from_reservation(reservation, by=None,
                                        lost_reason='no_stock', disqualified_reason=''):
    """Reverse bridge: turn an expired/cancelled Reservation into a lost
    DemandRecord so the unmet intent re-enters the demand dataset (and can be
    recovered later). Manager-gated at the view. Optionally disqualifies the line
    immediately (for items that aren't a real recoverable lost sale). Idempotent —
    returns the existing demand if this reservation was already converted."""
    from .models import DemandRecord, DemandItem, DemandLog
    from apps.reservations.models import ReservationActivity

    existing = (
        DemandItem.objects.filter(reservation=reservation, item_status='lost')
        .select_related('demand').first()
    )
    if existing:
        return existing.demand

    demand = DemandRecord.objects.create(
        phone=reservation.contact_phone,
        customer_name=reservation.contact_name or '',
        branch=reservation.branch,
        customer=reservation.customer,
        status='lost',
        lost_reason=lost_reason,
        source='other',
        created_by=by,
        notes=f'محوّل من حجز منتهٍ #{reservation.id}',
    )
    di = DemandItem.objects.create(
        demand=demand,
        item=reservation.item,
        item_name_free=reservation.manual_item_name or '',
        quantity=reservation.quantity_requested,
        item_status='lost',
        reservation=reservation,
    )
    if disqualified_reason:
        disqualify_item(di, reason=disqualified_reason, by=by)

    DemandLog.system(demand, f'📥 أُنشئ من حجز منتهٍ #{reservation.id}')
    ReservationActivity.objects.create(
        reservation=reservation,
        activity_type='status_changed',
        message=f'📥 حُوّل إلى طلب ضائع {demand.demand_number} للتتبع والاسترداد',
    )
    return demand
