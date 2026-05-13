"""
apps/followups/services.py  —  Follow-up Engine (Phase 5, v2)

ROOT CAUSE FIX:
  ERP sales (stktransm) use phcode = localcustomers.phcode  (e.g. '01HD1425')
  Customer.softech_id = personsdata.personcode             (e.g. '4827')
  These are DIFFERENT ID spaces with ZERO overlap.

CORRECT ARCHITECTURE:
  1. Query ERP transactions directly by phcode
  2. Match phcode → LocalCustomer
  3. Use LocalCustomer.linked_customer if it exists (for Customer FK)
     Otherwise store on LocalCustomer directly
  4. Create FollowUpTask with customer=linked_customer (or None)
     and local_customer stored in task notes/extra field

PERFORMANCE FIX:
  Old: loop 406 customers × 3302 profiles × DB query = ~1.3M hits
  New: ONE bulk ERP query → group by phcode → batch process
       Runs in seconds, not hours.

HARD RULES: ❌ No ERP writes  ✅ ERP READ ONLY
"""
import logging
from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Q

from .models import ChronicMedicationProfile, FollowUpTask

logger = logging.getLogger('elrezeiky.followups')


# ── Core: ERP-first bulk generation ──────────────────────────────────────────

def generate_followup_tasks_bulk(branch=None, days_limit=90, dry_run=False, grace_days=14):
    """
    Main entry point — called by scheduler and management command.

    Strategy (ERP-first, O(N) not O(N×M)):
      1. Load all chronic profiles into a dict keyed by item_id
      2. Load all ERP sales for chronic items in one query
      3. Group by phcode → find last sale per (phcode, item)
      4. For each group: calculate refill date, check window, create task

    grace_days: how many days PAST refill date we still create tasks.
                Use 9999 to generate retroactively for all past sales.

    Returns total tasks created (or would-create in dry_run).
    """
    from collections import defaultdict
    from apps.erp.models import ERPTransaction, ERPTransactionLine
    from apps.erp.models import LocalCustomer
    from apps.customers.models import Customer

    total = 0
    today = date.today()

    # ── Step 1: Load all chronic profiles → dict {item_id: profile} ──────────
    profiles = {
        p.item_id: p
        for p in ChronicMedicationProfile.objects.filter(
            is_chronic=True
        ).select_related('item')
    }
    if not profiles:
        logger.info('No chronic profiles found — skipping')
        return 0

    chronic_item_ids = list(profiles.keys())
    logger.info(f'Processing {len(chronic_item_ids)} chronic items')

    # ── Step 2: Load ERP sales for chronic items (ONE query) ─────────────────
    # We need: phcode, item_id, transaction_date, branch
    # Join through ERPTransactionLine → ERPTransaction
    lines = (
        ERPTransactionLine.objects
        .filter(
            transaction__doccode='115',
            item_id__in=chronic_item_ids,
        )
        .select_related('transaction')
        .values(
            'item_id',
            'transaction__phcode',
            'transaction__transaction_date',
            'transaction__softech_branch_code',
            'transaction__id',
        )
        .order_by('transaction__phcode', 'item_id', '-transaction__transaction_date')
    )

    # ── Step 3: Group by (phcode, item_id) → keep last sale per pair ─────────
    # {(phcode, item_id): {date, branch_code, tx_id}}
    last_sale = {}
    for row in lines:
        phcode     = row['transaction__phcode']
        item_id    = row['item_id']
        sale_date  = row['transaction__transaction_date']

        if not phcode or not item_id:
            continue

        key = (phcode, item_id)
        if key not in last_sale:
            last_sale[key] = {
                'sale_date':   sale_date.date() if hasattr(sale_date, 'date') else sale_date,
                'branch_code': row['transaction__softech_branch_code'],
                'tx_id':       row['transaction__id'],
            }
        # Already have the latest (ordered DESC) — skip duplicates

    logger.info(f'Found {len(last_sale)} (phcode, item) sale pairs')
    if not last_sale:
        return 0

    # ── Step 4: Pre-cache LocalCustomer + Customer lookups ────────────────────
    all_phcodes = list({k[0] for k in last_sale.keys()})

    lc_map = {
        lc.phcode: lc
        for lc in LocalCustomer.objects.filter(
            phcode__in=all_phcodes
        ).select_related('linked_customer', 'branch')
    }

    # Pre-cache branch map
    from apps.branches.models import Branch
    branch_map = {b.softech_branch_id: b for b in Branch.objects.all()}

    # Pre-fetch existing open tasks to avoid duplicates — {(customer_id or phcode, item_id)}
    existing_tasks = set()
    for t in FollowUpTask.objects.filter(
        status__in=('pending', 'called'),
        item_id__in=chronic_item_ids,
    ).values_list('notes', 'item_id'):
        # We'll check by phcode stored in notes
        existing_tasks.add(t)

    # Simpler duplicate check: (phcode, item_id) stored as task note prefix
    existing_by_phcode_item = set(
        FollowUpTask.objects.filter(
            status__in=('pending', 'called'),
            item_id__in=chronic_item_ids,
        ).values_list('notes', 'item_id')
    )
    # Build a fast lookup set of (phcode, item_id) for open tasks
    open_task_keys = set()
    for t in FollowUpTask.objects.filter(
        status__in=('pending', 'called'),
        item_id__in=chronic_item_ids,
    ).values_list('notes', 'item_id', 'due_date'):
        note, item_id, due = t
        # Extract phcode from note prefix "phcode:XXXXX ..."
        if note and note.startswith('phcode:'):
            phcode_part = note.split(' ')[0].replace('phcode:', '')
            open_task_keys.add((phcode_part, item_id))

    # ── Step 5: For each (phcode, item_id), check window and create task ──────
    tasks_to_create = []

    for (phcode, item_id), sale_info in last_sale.items():
        profile    = profiles.get(item_id)
        if not profile:
            continue

        sale_date    = sale_info['sale_date']
        if not isinstance(sale_date, date):
            try:
                sale_date = sale_date.date()
            except Exception:
                continue

        trigger_date = sale_date + timedelta(days=profile.followup_trigger_day)
        refill_date  = sale_date + timedelta(days=profile.expected_duration_days)

        # Window check
        if trigger_date > today:
            continue  # Too early
        if today > refill_date + timedelta(days=grace_days):
            continue  # Too late

        # Duplicate check
        if (phcode, item_id) in open_task_keys:
            continue

        # Resolve LocalCustomer and Customer
        lc       = lc_map.get(phcode)
        customer = lc.linked_customer if lc else None

        # Resolve branch
        branch_code = sale_info['branch_code']
        task_branch = branch_map.get(branch_code)
        if branch and task_branch and task_branch != branch:
            continue  # Branch filter

        if dry_run:
            tasks_to_create.append({
                'phcode':    phcode,
                'item':      profile.item.name,
                'due_date':  str(refill_date),
                'customer':  customer.name if customer else (lc.name if lc else phcode),
                'dry_run':   True,
            })
            total += 1
            continue

        # Create task
        try:
            task = FollowUpTask.objects.create(
                customer=customer,                       # May be None if not linked
                item=profile.item,
                branch=task_branch or (lc.branch if lc else None),
                chronic_profile=profile,
                task_type='refill',
                due_date=refill_date,
                source_sale_date=sale_date,
                notes=(
                    f'phcode:{phcode} '
                    f'آخر صرف: {sale_date} — '
                    f'المتوقع نفاد الدواء: {refill_date}'
                ),
            )
            open_task_keys.add((phcode, item_id))   # prevent double-create in same run
            total += 1

            if total % 100 == 0:
                logger.info(f'  Created {total} tasks so far...')

            _notify_new_task(task, phcode=phcode, lc=lc)

        except Exception as e:
            logger.warning(f'Task create failed phcode={phcode} item={item_id}: {e}')

    mode = 'dry_run' if dry_run else 'created'
    logger.info(f'Bulk followup generation: {total} tasks ({mode})')
    return total


# ── Legacy per-customer function (kept for API compatibility) ─────────────────

def generate_followup_tasks_for_customer(customer, branch=None, dry_run=False):
    """
    Generate tasks for one specific customer.
    Used by the quick-followup API endpoint.
    Searches by customer.softech_id OR linked LocalCustomer phcodes.
    """
    from apps.erp.models import ERPTransaction, LocalCustomer

    created = []
    today   = date.today()

    try:
        profiles = ChronicMedicationProfile.objects.filter(
            is_chronic=True
        ).select_related('item')

        # Find all phcodes for this customer
        phcodes = []
        if customer.softech_id:
            phcodes.append(customer.softech_id)

        # Also check LocalCustomer linkage
        try:
            lc = customer.local_customer_profile
            if lc:
                phcodes.append(lc.phcode)
        except Exception:
            pass

        # Also search by phone
        try:
            tail = customer.phone.strip().replace(' ', '')[-9:]
            linked_lcs = LocalCustomer.objects.filter(phone__endswith=tail)
            phcodes += [lc.phcode for lc in linked_lcs]
        except Exception:
            pass

        if not phcodes:
            return []

        for profile in profiles:
            last_sale = ERPTransaction.objects.filter(
                doccode='115',
                phcode__in=phcodes,
                lines__item=profile.item,
            ).order_by('-transaction_date').first()

            if not last_sale:
                continue

            sale_date    = last_sale.transaction_date.date()
            refill_date  = sale_date + timedelta(days=profile.expected_duration_days)
            trigger_date = sale_date + timedelta(days=profile.followup_trigger_day)

            if trigger_date > today:
                continue
            if today > refill_date + timedelta(days=14):
                continue

            existing = FollowUpTask.objects.filter(
                Q(customer=customer) |
                Q(notes__startswith=f'phcode:{last_sale.phcode}'),
                item=profile.item,
                status__in=('pending', 'called'),
            ).exists()
            if existing:
                continue

            if dry_run:
                created.append({'item': profile.item.name, 'due_date': str(refill_date)})
                continue

            task = FollowUpTask.objects.create(
                customer=customer,
                item=profile.item,
                branch=branch or customer.preferred_branch,
                chronic_profile=profile,
                task_type='refill',
                due_date=refill_date,
                source_sale_date=sale_date,
                notes=(
                    f'phcode:{last_sale.phcode} '
                    f'آخر صرف: {sale_date} — '
                    f'المتوقع نفاد: {refill_date}'
                ),
            )
            created.append(task)

    except Exception as e:
        logger.warning(f'generate_followup_tasks_for_customer({customer.id}): {e}')

    return created


# ── Auto-close: match new ERP sales to open follow-up tasks ──────────────────

def auto_close_followup_tasks_from_erp(since_minutes=12):
    """
    Called after every sync. Looks at recent ERP sales and auto-closes
    any matching open FollowUpTask where the same phcode bought the item.
    """
    closed = 0
    try:
        from apps.erp.models import ERPTransaction
        cutoff = timezone.now() - timedelta(minutes=since_minutes)

        recent_sales = ERPTransaction.objects.filter(
            doccode='115',
            transaction_date__gte=cutoff,
        ).prefetch_related('lines__item')

        for sale in recent_sales:
            phcode        = sale.phcode
            sold_item_ids = {l.item_id for l in sale.lines.all() if l.item_id}
            if not phcode or not sold_item_ids:
                continue

            # Find open tasks matching this phcode (stored in notes)
            tasks = FollowUpTask.objects.filter(
                status__in=('pending', 'called'),
                item_id__in=sold_item_ids,
                notes__startswith=f'phcode:{phcode}',
            )

            for task in tasks:
                task.status                   = 'auto_closed'
                task.completed_at             = timezone.now()
                task.closing_erp_transaction  = sale
                task.result_note = (
                    f'أُغلق تلقائياً — ERP أكّد بيع '
                    f'{task.item.name if task.item else ""} '
                    f'بتاريخ {sale.transaction_date.date()}'
                )
                task.save(update_fields=[
                    'status', 'completed_at',
                    'closing_erp_transaction', 'result_note', 'updated_at',
                ])
                closed += 1

    except Exception as e:
        logger.warning(f'auto_close_followup_tasks_from_erp (non-fatal): {e}')

    return closed


# ── Infer chronic profiles from ERP history ───────────────────────────────────

def infer_chronic_profiles_from_erp(min_purchase_count=3, min_months=2):
    """
    Analyse ERP sales to detect chronic medications.
    Creates/updates ChronicMedicationProfile for qualifying items.
    """
    count = 0
    try:
        from apps.erp.models import ERPTransactionLine
        from django.db.models import Count, Min, Max

        stats = (
            ERPTransactionLine.objects
            .filter(transaction__doccode='115')
            .values('item', 'item_code')
            .annotate(
                purchase_count=Count('transaction__phcode', distinct=True),
                first_sale=Min('transaction__transaction_date'),
                last_sale=Max('transaction__transaction_date'),
            )
            .filter(purchase_count__gte=min_purchase_count)
        )

        for stat in stats:
            if not stat['item']:
                continue
            if not stat['first_sale'] or not stat['last_sale']:
                continue

            months_span = (stat['last_sale'] - stat['first_sale']).days / 30
            if months_span < min_months:
                continue

            avg_days = max(1, int(
                (stat['last_sale'] - stat['first_sale']).days
                / max(stat['purchase_count'] - 1, 1)
            ))

            ChronicMedicationProfile.objects.update_or_create(
                item_id=stat['item'],
                defaults={
                    'is_chronic':             True,
                    'expected_duration_days': min(avg_days, 90),
                    'followup_before_days':   max(3, min(7, avg_days // 5)),
                    'source':                 'erp_infer',
                    'notes': (
                        f'مستنتج من {stat["purchase_count"]} عميل '
                        f'خلال {months_span:.1f} شهر — '
                        f'متوسط دورة {avg_days} يوم'
                    ),
                }
            )
            count += 1

    except Exception as e:
        logger.warning(f'infer_chronic_profiles_from_erp failed: {e}')

    logger.info(f'Chronic profile inference: {count} profiles created/updated')
    return count


# ── Task state helpers ────────────────────────────────────────────────────────

def mark_task_called(task, note='', staff=None):
    task.status   = 'called'
    task.attempts += 1
    if note:
        task.result_note = note
    task.save(update_fields=['status', 'attempts', 'result_note', 'updated_at'])
    return task


def mark_task_done(task, note='', staff=None):
    task.status       = 'done'
    task.result_note  = note or 'تم التواصل — العميل سيحضر للصرف'
    task.completed_at = timezone.now()
    task.completed_by = staff
    task.save(update_fields=[
        'status', 'result_note', 'completed_at', 'completed_by', 'updated_at'
    ])
    return task


def mark_task_missed(task, note='', staff=None):
    task.status      = 'missed'
    task.result_note = note or 'لا يوجد رد بعد محاولات متعددة'
    task.save(update_fields=['status', 'result_note', 'updated_at'])
    return task


def get_dashboard_stats(branch=None, days=30):
    from django.db.models import Count
    from datetime import date, timedelta

    today  = date.today()
    cutoff = today - timedelta(days=days)
    qs     = FollowUpTask.objects.filter(created_at__date__gte=cutoff)
    if branch:
        qs = qs.filter(branch=branch)

    return {
        'pending':        qs.filter(status='pending').count(),
        'called':         qs.filter(status='called').count(),
        'done':           qs.filter(status='done').count(),
        'missed':         qs.filter(status='missed').count(),
        'auto_closed':    qs.filter(status='auto_closed').count(),
        'overdue':        qs.filter(status='pending', due_date__lt=today).count(),
        'due_today':      qs.filter(status='pending', due_date=today).count(),
        'due_this_week':  qs.filter(
            status='pending',
            due_date__range=(today, today + timedelta(days=7))
        ).count(),
        'chronic_profiles': ChronicMedicationProfile.objects.filter(is_chronic=True).count(),
    }


# ── Notifications ─────────────────────────────────────────────────────────────

def _notify_new_task(task, phcode=None, lc=None):
    try:
        from apps.notifications.models import Notification
        from apps.users.models import StaffProfile

        recipients = StaffProfile.objects.filter(
            is_active=True, role__in=('admin', 'call_center')
        )
        if task.assigned_to:
            recipients = recipients | StaffProfile.objects.filter(pk=task.assigned_to_id)

        name = (
            task.customer.name if task.customer
            else (lc.name if lc else phcode or '—')
        )
        title = f'💊 تذكير صرف — {name}'
        body  = (
            f'الصنف: {task.item.name if task.item else "—"} | '
            f'الاستحقاق: {task.due_date}'
        )

        for staff in recipients.distinct():
            try:
                Notification.objects.create(
                    recipient=staff,
                    title=title,
                    body=body,
                    notification_type='followup',
                )
            except Exception:
                pass
    except Exception:
        pass
