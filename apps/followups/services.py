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
from decimal import ROUND_DOWN, Decimal
from django.utils import timezone
from django.db.models import Q, Subquery, OuterRef, Value
from django.db.models.functions import Coalesce

from .models import ChronicMedicationProfile, FollowUpTask

logger = logging.getLogger('elrezeiky.followups')


# ── Core: ERP-first bulk generation ──────────────────────────────────────────

def generate_followup_tasks_bulk(branch=None, days_limit=90, dry_run=False, grace_days=14):
    """
    Main entry point — called by scheduler and management command.

    Strategy (O(N) not O(N×M)):
      1. Load all chronic profiles into a dict keyed by item_id
      2. Load the synced SOFTECH sales (PurchaseHistory) of chronic items in one query —
         the ERPTransaction mirror stopped 2026-04-30, so no task was generated after it
      3. Group by PIC (phcode) → find last sale per (phcode, item)
      4. For each group: calculate refill date, check window, create task

    grace_days: how many days PAST refill date we still create tasks.
                Use 9999 to generate retroactively for all past sales.

    Returns total tasks created (or would-create in dry_run).
    """
    from apps.erp.models import LocalCustomer
    from apps.customers.models import Customer, PurchaseHistoryLine

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

    # ── Step 2: Load synced sales of chronic items (ONE query) ───────────────
    # Only sales recent enough to still fall inside some item's window.
    longest = max(p.expected_duration_days for p in profiles.values())
    since   = today - timedelta(days=min(longest + grace_days + 1, 3650))
    lines = (
        PurchaseHistoryLine.objects
        .filter(
            purchase__doc_code='115',
            purchase__invoice_date__date__gte=since,
            item_id__in=chronic_item_ids,
        )
        .exclude(purchase__softech_phcode='')
        .values(
            'item_id',
            'quantity',
            'unit_price',
            'purchase__softech_phcode',
            'purchase__invoice_date',
            'purchase__branch__softech_branch_id',
            'purchase__docnumber',              # ← docnumber for SOFTECH lookup
            'purchase__total_amount',           # ← full invoice total
        )
        .order_by('purchase__softech_phcode', 'item_id', '-purchase__invoice_date')
    )

    # ── Step 3: Group by (phcode, item_id) → keep last sale per pair ─────────
    last_sale = {}
    for row in lines:
        phcode     = row['purchase__softech_phcode']
        item_id    = row['item_id']
        when       = row['purchase__invoice_date']

        if not phcode or not item_id or when is None:
            continue

        key = (phcode, item_id)
        if key not in last_sale:
            last_sale[key] = {
                'sale_date':    timezone.localtime(when).date(),   # Cairo date, not UTC
                'branch_code':  row['purchase__branch__softech_branch_id'],
                'docnumber':    row['purchase__docnumber'] or '',
                'total_amount': row['purchase__total_amount'],
                'item_qty':     row['quantity'],
                'item_price':   row['unit_price'],
            }
        # Already have the latest (ordered DESC) — skip duplicates

    logger.info(f'Found {len(last_sale)} (phcode, item) sale pairs')
    if not last_sale:
        return 0

    # ── Step 4: Pre-cache LocalCustomer + Customer + channel lookups ─────────
    all_phcodes = list({k[0] for k in last_sale.keys()})

    lc_map = {
        lc.phcode: lc
        for lc in LocalCustomer.objects.filter(
            phcode__in=all_phcodes
        ).select_related('linked_customer', 'branch')
    }
    # PIC → Customer (softech_pic IS the phcode; account placeholders are not people)
    pic_customer = {
        c.softech_pic: c
        for c in Customer.objects.filter(softech_pic__in=all_phcodes, is_account_placeholder=False)
    }

    # Pre-load phcode → sales_channel from PurchaseHistory (AUTHORITATIVE source).
    # Customer.softech_ptclassifcode is intentionally NOT used — it is blank for
    # all customers in this dataset. PurchaseHistory.sales_channel = stktransm.ptclassifcode.
    phcode_channel_map = _build_phcode_channel_map(all_phcodes)
    logger.info('Channel map loaded: %d phcodes with known channel', len(phcode_channel_map))

    # Pre-cache branch map
    from apps.branches.models import Branch
    branch_map = {b.softech_branch_id: b for b in Branch.objects.all()}

    # Build a fast lookup set of (phcode, item_id) for all open tasks.
    # Use the phcode field directly — reliable, no notes-string parsing.
    open_task_keys = set(
        FollowUpTask.objects.filter(
            status__in=('pending', 'called'),
            item_id__in=chronic_item_ids,
        ).exclude(phcode='').values_list('phcode', 'item_id')
    )
    # A sale that already produced a task (any status — done, missed, auto-closed) never
    # produces a second one.
    done_sale_keys = set(
        FollowUpTask.objects.filter(item_id__in=chronic_item_ids)
        .exclude(phcode='').exclude(source_erp_transaction='')
        .values_list('phcode', 'item_id', 'source_erp_transaction')
    )

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
        if (phcode, item_id, str(sale_info['docnumber'])) in done_sale_keys:
            continue

        # Resolve LocalCustomer and Customer
        lc       = lc_map.get(phcode)
        customer = pic_customer.get(phcode) or (lc.linked_customer if lc else None)

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
            # Resolve channel from pre-loaded PurchaseHistory map (authoritative).
            # Customer.softech_ptclassifcode is NOT used — blank for all customers.
            channel = phcode_channel_map.get(phcode, '')

            task = FollowUpTask.objects.create(
                customer=customer,           # None when not yet linked to personsdata
                local_customer=lc,          # Always set when available — provides name + phone
                phcode=phcode,              # Stored directly for fast display / filtering
                item=profile.item,
                branch=task_branch or (lc.branch if lc else None),
                chronic_profile=profile,
                task_type='refill',
                sales_channel=channel,
                due_date=refill_date,
                # ── Full transaction anchor ────────────────────────────
                source_sale_date=sale_date,
                source_erp_transaction=sale_info.get('docnumber', ''),
                source_softech_branch_code=sale_info.get('branch_code', ''),
                source_total_amount=sale_info.get('total_amount'),
                source_item_qty=sale_info.get('item_qty'),
                source_item_price=sale_info.get('item_price'),
                notes=(
                    f'آخر صرف: {sale_date} — '
                    f'المتوقع نفاد الدواء: {refill_date}'
                ),
            )
            open_task_keys.add((phcode, item_id))   # prevent double-create in same run
            total += 1

            if total % 100 == 0:
                logger.info(f'  Created {total} tasks so far...')
            # NO notification on auto-create — tasks start un-pinned.
            # Notifications only fire when a user manually pins or assigns a task.

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
    Searches the synced sales (PurchaseHistory) by the customer's PIC (softech_pic), linked
    LocalCustomer and same-phone PICs — the old ERPTransaction mirror stopped 2026-04-30, and
    softech_id is only the per-branch serial, never a phcode.
    """
    from apps.customers.models import PurchaseHistory
    from apps.erp.models import LocalCustomer

    created = []
    today   = date.today()

    try:
        profiles = ChronicMedicationProfile.objects.filter(
            is_chronic=True
        ).select_related('item')

        # Find all phcodes for this customer
        phcodes = []
        if customer.softech_pic and not customer.is_account_placeholder:
            phcodes.append(customer.softech_pic)

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
            last_sale = PurchaseHistory.objects.filter(
                doc_code='115',
                softech_phcode__in=phcodes,
                lines__item=profile.item,
                invoice_date__isnull=False,
            ).order_by('-invoice_date').first()

            if not last_sale:
                continue

            sale_date    = timezone.localtime(last_sale.invoice_date).date()
            refill_date  = sale_date + timedelta(days=profile.expected_duration_days)
            trigger_date = sale_date + timedelta(days=profile.followup_trigger_day)

            if trigger_date > today:
                continue
            if today > refill_date + timedelta(days=14):
                continue

            existing = FollowUpTask.objects.filter(
                Q(customer=customer) |
                Q(notes__startswith=f'phcode:{last_sale.softech_phcode}'),
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
                sales_channel=customer.softech_ptclassifcode or '',
                due_date=refill_date,
                source_sale_date=sale_date,
                notes=(
                    f'phcode:{last_sale.softech_phcode} '
                    f'آخر صرف: {sale_date} — '
                    f'المتوقع نفاد: {refill_date}'
                ),
            )
            created.append(task)

    except Exception as e:
        logger.warning(f'generate_followup_tasks_for_customer({customer.id}): {e}')

    return created


# ── Auto-close: match new ERP sales to open follow-up tasks ──────────────────

def _task_pic(task):
    """The PIC a refill task is about: its phcode field, else the 'phcode:<pic>' notes prefix."""
    if task.phcode:
        return task.phcode
    if (task.notes or '').startswith('phcode:'):
        return task.notes[len('phcode:'):].split(' ', 1)[0]
    return ''


def _is_source_invoice(task, invoice_id):
    """True when `invoice_id` ('<branch>-115-<docnumber>-<YYYYMMDD>') is the sale that created the
    task. Tasks made from the old ERPTransaction mirror carry source_sale_date ONE DAY EARLY (UTC
    date), so the date rule alone would let a task close on its own sale."""
    parts = (invoice_id or '').split('-')
    return (len(parts) == 4 and bool(task.source_erp_transaction)
            and parts[2] == str(task.source_erp_transaction).strip()
            and (not task.source_softech_branch_code or parts[0] == str(task.source_softech_branch_code).strip()))


def _later_purchases(pics, item_ids, since_date):
    """{(pic, item_id): [(sale_date, invoice_id), …]} — synced SOFTECH sales (PurchaseHistory,
    kept current by the sales sync; the ERPTransaction mirror stopped 2026-04-30)."""
    from collections import defaultdict
    from apps.customers.models import PurchaseHistoryLine
    out = defaultdict(list)
    rows = (PurchaseHistoryLine.objects
            .filter(purchase__doc_code='115', purchase__softech_phcode__in=pics, item_id__in=item_ids,
                    purchase__invoice_date__date__gte=since_date)
            .values_list('purchase__softech_phcode', 'item_id', 'purchase__invoice_date',
                         'purchase__softech_invoice_id'))
    for pic, item_id, when, inv in rows:
        out[(pic, item_id)].append((timezone.localtime(when).date(), inv))
    return out


def auto_close_followup_tasks_from_erp(since_minutes=12, dry_run=False):
    """
    Called after every sync. Auto-closes an open refill task when the same PIC bought the same
    item AFTER the sale that created the task. Sales come from the synced PurchaseHistory and
    are matched by sale DATE (a branch's sale can reach HQ hours late), looking back
    `since_minutes` (whole days, +1 day margin). dry_run counts without saving.
    """
    closed = 0
    try:
        since_date = (timezone.now() - timedelta(minutes=since_minutes)).date() - timedelta(days=1)
        tasks = [t for t in FollowUpTask.objects.filter(status__in=('pending', 'called'),
                                                        item__isnull=False).select_related('item')
                 if _task_pic(t)]
        if not tasks:
            return 0
        bought = _later_purchases({_task_pic(t) for t in tasks}, {t.item_id for t in tasks}, since_date)

        for task in tasks:
            after = [s for s in bought.get((_task_pic(task), task.item_id), ())
                     if not _is_source_invoice(task, s[1])
                     and (task.source_sale_date is None or s[0] > task.source_sale_date)]
            if not after:
                continue
            sale_date, invoice = min(after)
            closed += 1
            if dry_run:
                continue
            task.status                  = 'auto_closed'
            task.completed_at            = timezone.now()
            task.closing_erp_transaction = invoice
            task.result_note = (
                f'أُغلق تلقائياً — SOFTECH أكّد بيع '
                f'{task.item.name if task.item else ""} '
                f'بتاريخ {sale_date}'
            )
            task.save(update_fields=[
                'status', 'completed_at',
                'closing_erp_transaction', 'result_note', 'updated_at',
            ])

    except Exception as e:
        logger.warning(f'auto_close_followup_tasks_from_erp (non-fatal): {e}')

    return closed


# ── Infer chronic profiles from repeat purchases ─────────────────────────────

def _episodes(dates, merge_days=7):
    """Sorted purchase dates → one date per buying episode (buys within `merge_days` merge)."""
    out = []
    for d in sorted(set(dates)):
        if not out or (d - out[-1]).days > merge_days:
            out.append(d)
    return out


def infer_chronic_profiles_from_sales(months=24, min_episodes=3, min_patients=5,
                                      min_interval=20, max_interval=100, max_spread=0.5,
                                      min_share=0.05, dry_run=False):
    """
    A medicine is chronic when enough patients REBUY it on a steady cycle.

    From the synced SOFTECH sales (PurchaseHistory) of the last `months`, medicines only
    (Item.medicine_type '10'): for each (PIC, item) take the buying episodes; a patient counts
    when they have >= `min_episodes` episodes, their median gap is `min_interval`..`max_interval`
    days and the gaps are steady (median |gap - median| / median <= `max_spread`). An item with
    >= `min_patients` such patients, who are >= `min_share` of all its buyers, is chronic; its
    cycle = the median of their median gaps. The share is what separates chronic medicines
    (CONCOR 15%, PLAVIX 20%, DIAMICRON 14%) from short courses that a clinic or household PIC
    happens to rebuy (AUGMENTIN 2.3%, PANADOL 2.8%, FLAGYL 1.2%) — measured 2026-11-01.

    Replaces the old ERPTransaction inference, which read a mirror frozen on 2026-04-30 and
    called «span ÷ number of buyers» a refill cycle (every profile came out 30 days, coupons
    and syringes included). Never touches source='manual' profiles; inferred profiles that no
    longer qualify are switched off (is_chronic=False), not deleted — tasks link to them.

    Returns a report dict; dry_run computes it without saving.
    """
    from collections import defaultdict
    from statistics import median
    from apps.catalog.models import Item
    from apps.customers.models import PurchaseHistoryLine

    since = date.today() - timedelta(days=30 * months)
    dates = defaultdict(list)                      # (item_id, pic) → purchase dates
    rows = (PurchaseHistoryLine.objects
            .filter(purchase__doc_code='115', purchase__invoice_date__date__gte=since,
                    item__medicine_type='10')
            .exclude(purchase__softech_phcode='')
            .values_list('item_id', 'purchase__softech_phcode', 'purchase__invoice_date'))
    for item_id, pic, when in rows.iterator(chunk_size=20000):
        dates[(item_id, pic)].append(timezone.localtime(when).date())

    cycles = defaultdict(list)                     # item_id → each steady patient's median gap
    buyers = defaultdict(int)                      # item_id → patients who bought it at all
    for (item_id, _pic), ds in dates.items():
        buyers[item_id] += 1
        ep = _episodes(ds)
        if len(ep) < min_episodes:
            continue
        gaps = [(b - a).days for a, b in zip(ep, ep[1:])]
        m = median(gaps)
        if not (min_interval <= m <= max_interval):
            continue
        if median(abs(g - m) for g in gaps) / m > max_spread:
            continue
        cycles[item_id].append(m)

    chronic = {iid: (int(round(median(ms))), len(ms)) for iid, ms in cycles.items()
               if len(ms) >= min_patients and len(ms) / buyers[iid] >= min_share}
    existing = {p.item_id: p for p in ChronicMedicationProfile.objects.all()}
    names = dict(Item.objects.filter(id__in=set(chronic) | set(existing)).values_list('id', 'name'))
    effects = dict(Item.objects.filter(id__in=chronic).values_list('id', 'effect_name'))

    report = {'chronic': len(chronic), 'created': 0, 'updated': 0, 'protected_manual': 0, 'switched_off': 0,
              'items': sorted(((names.get(i, i), d, n, effects.get(i, ''), round(100 * n / buyers[i], 1))
                               for i, (d, n) in chronic.items()), key=lambda x: -x[2]),
              'switched_off_items': []}
    for iid, (cycle, patients) in chronic.items():
        p = existing.get(iid)
        if p is not None and p.source == 'manual':
            report['protected_manual'] += 1
            continue
        report['updated' if p else 'created'] += 1
        if dry_run:
            continue
        # save() re-derives the duration as pack_size ÷ avg_daily_usage (defaults 30 ÷ 1 = 30 —
        # why every old profile read 30 days), so express the cycle as the usage; rounding the
        # usage DOWN keeps int(pack ÷ usage) == cycle.
        pack = (p.pack_size if p is not None else None) or Decimal('30')
        usage = (Decimal(pack) / Decimal(cycle)).quantize(Decimal('0.001'), rounding=ROUND_DOWN)
        while usage > Decimal('0.001') and int(float(pack) / float(usage)) < cycle:   # 30 ÷ 1.2 = 24.999…
            usage -= Decimal('0.001')
        ChronicMedicationProfile.objects.update_or_create(item_id=iid, defaults={
            'is_chronic': True,
            'pack_size': pack,
            'avg_daily_usage': usage,
            'expected_duration_days': cycle,
            'followup_before_days': max(3, min(7, round(cycle * 0.15))),
            'source': 'sales_infer',
            'notes': f'مستنتج من {patients} مريض يكرّرون الشراء بانتظام — متوسط الدورة {cycle} يوم',
        })
    for iid, p in existing.items():
        if iid in chronic or p.source == 'manual' or not p.is_chronic:
            continue
        report['switched_off'] += 1
        report['switched_off_items'].append(names.get(iid, iid))
        if not dry_run:
            p.is_chronic = False
            p.notes = (p.notes + ' | ' if p.notes else '') + 'أُوقف — لا يوجد تكرار شراء منتظم في المبيعات'
            p.save(update_fields=['is_chronic', 'notes', 'updated_at'])
    logger.info('Chronic inference (dry_run=%s): %d chronic, %d created, %d updated, %d switched off',
                dry_run, report['chronic'], report['created'], report['updated'], report['switched_off'])
    return report


def infer_chronic_profiles_from_erp(min_purchase_count=3, min_months=2):
    """Kept for the API / command: runs the sales-based inference. `min_purchase_count` = the
    minimum buying episodes per patient; `min_months` is no longer used. Returns profiles saved."""
    r = infer_chronic_profiles_from_sales(min_episodes=min_purchase_count)
    return r['created'] + r['updated']


# ── Manual task actions (pin / assign) ────────────────────────────────────────

def pin_task(task, staff):
    """
    Staff manually pins a task to track it personally.
    Sets is_pinned=True, records who pinned it, sends a confirmation notification.
    """
    from django.utils import timezone as tz
    task.is_pinned = True
    task.pinned_by = staff
    task.pinned_at = tz.now()
    task.save(update_fields=['is_pinned', 'pinned_by', 'pinned_at', 'updated_at'])
    notify_pin(task, staff)
    logger.info('Task %d pinned by %s', task.id, staff.full_name)
    return task


def unpin_task(task, staff):
    """Remove the pin — task goes back to untracked state."""
    task.is_pinned = False
    task.pinned_by = None
    task.pinned_at = None
    task.save(update_fields=['is_pinned', 'pinned_by', 'pinned_at', 'updated_at'])
    logger.info('Task %d unpinned by %s', task.id, staff.full_name)
    return task


def assign_task(
    task,
    actor=None,
    assignee_ids=None,
    role=None,
    branch_id=None,
    use_task_branch=False,
    replace=True,
):
    """
    Assign a follow-up task to one or more staff members.

    Resolution order (union of all specified criteria):
      1. assignee_ids  — specific StaffProfile PKs
      2. role          — all active staff with this role
      3. branch_id     — filter by branch (combined with role if also given)
      4. use_task_branch — use the task's own branch instead of branch_id

    Parameters
    ----------
    replace : bool
        If True (default), clear all existing FollowUpTaskAssignment rows for this
        task before creating new ones.  Set False to ADD assignees on top of existing.

    Returns the resolved list of StaffProfile objects.
    """
    from apps.users.models import StaffProfile
    from .models import FollowUpTaskAssignment
    from django.utils import timezone as tz

    # ── Resolve the target branch ─────────────────────────────────────────────
    effective_branch_id = branch_id
    if use_task_branch and task.branch_id:
        effective_branch_id = task.branch_id

    # ── Build staff queryset from all criteria (union) ────────────────────────
    candidate_qs = StaffProfile.objects.filter(is_active=True)

    if not assignee_ids and not role and not effective_branch_id:
        logger.warning('assign_task: no criteria provided — nothing to assign')
        return []

    from django.db.models import Q
    q = Q(pk__in=[])  # empty start

    if assignee_ids:
        q |= Q(pk__in=assignee_ids)

    if role and effective_branch_id:
        # Role + branch: staff of this role at this branch
        q |= Q(role=role, branch_id=effective_branch_id)
    elif role:
        # All active staff with this role (all branches)
        q |= Q(role=role)
    elif effective_branch_id:
        # All active staff at this branch (any role)
        q |= Q(branch_id=effective_branch_id)

    resolved = list(candidate_qs.filter(q).distinct())
    if not resolved:
        logger.warning('assign_task %d: criteria matched no active staff', task.id)
        return []

    # ── Wipe existing assignments if replacing ────────────────────────────────
    if replace:
        FollowUpTaskAssignment.objects.filter(task=task).delete()

    # ── Create assignment rows (ignore duplicates on re-add) ──────────────────
    reason = _assignment_reason(bool(assignee_ids), role, effective_branch_id)
    rows = []
    for staff in resolved:
        rows.append(FollowUpTaskAssignment(
            task=task, staff=staff, assigned_by=actor, assignment_reason=reason,
        ))
    FollowUpTaskAssignment.objects.bulk_create(rows, ignore_conflicts=True)

    # ── Update task: pin + set lead assigned_to ───────────────────────────────
    lead = resolved[0]
    now  = tz.now()
    task.assigned_to = lead          # lead = first resolved user
    task.is_pinned   = True
    if not task.pinned_by_id:
        task.pinned_by = actor or lead
        task.pinned_at = now
    task.save(update_fields=[
        'assigned_to', 'is_pinned', 'pinned_by', 'pinned_at', 'updated_at',
    ])

    # ── Notify every assignee individually ───────────────────────────────────
    for staff in resolved:
        _notify_assigned_staff(task, staff, actor=actor, total=len(resolved))

    logger.info(
        'Task %d assigned to %d staff (%s) by %s',
        task.id, len(resolved), reason, actor.full_name if actor else 'system',
    )
    return resolved


def _assignment_reason(has_ids, role, branch_id):
    if has_ids and not role and not branch_id:
        return 'direct'
    if role and branch_id:
        return 'role_branch'
    if role:
        return 'role'
    if branch_id:
        return 'branch'
    return 'direct'


def _notify_assigned_staff(task, staff, actor=None, total=1):
    """Send a targeted assignment notification to one staff member."""
    try:
        from apps.notifications.models import Notification
        name      = task.customer_name or task.phcode or '—'
        item_name = task.item.name if task.item_id and task.item else '—'
        actor_name = actor.full_name if actor else 'النظام'
        suffix = f' (مع {total - 1} آخرين)' if total > 1 else ''
        Notification.objects.create(
            recipient_id      = staff.pk,
            title             = f'📋 مهمة متابعة مُعيَّنة لك{suffix} — {name}',
            body              = (
                f'الصنف: {item_name} | الاستحقاق: {task.due_date} '
                f'| عيّنها: {actor_name}'
            ),
            notification_type = 'followup',
        )
    except Exception:
        pass


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
    # Auto-flag phone after 3 consecutive missed/called-no-answer attempts
    if task.attempts >= 3 and not task.phone_invalid:
        flag_invalid_phone(task, actor=staff, auto=True)
    return task


# ── Feature 9: Outcome presets ────────────────────────────────────────────────

def apply_outcome_preset(task, preset_id: str, extra_note: str = '', actor=None):
    """
    Apply a one-tap outcome preset to a FollowUpTask.
    Handles status change, side actions (create_demand, flag_phone), and note.

    preset_id must be a key in OUTCOME_PRESET_MAP.
    Returns {'task': task, 'side_result': dict|None}
    """
    from .models import OUTCOME_PRESET_MAP
    preset = OUTCOME_PRESET_MAP.get(preset_id)
    if not preset:
        raise ValueError(f'Unknown preset: {preset_id}')

    _id, label, new_status, side_action = preset
    note = f'{label}{(" — " + extra_note) if extra_note else ""}'
    side_result = None

    if new_status == 'done':
        mark_task_done(task, note=note, staff=actor)
    elif new_status == 'missed':
        task.attempts += 1
        mark_task_missed(task, note=note, staff=actor)
    else:  # called
        mark_task_called(task, note=note, staff=actor)

    if side_action == 'flag_phone':
        flag_invalid_phone(task, actor=actor)
        side_result = {'action': 'phone_flagged'}

    elif side_action == 'create_demand':
        if task.item_id and task.branch_id:
            try:
                demand = create_demand_from_task(task, actor=actor)
                side_result = {
                    'action':         'demand_created',
                    'demand_number':  demand.demand_number,
                    'demand_id':      demand.id,
                }
            except Exception as exc:
                logger.warning('apply_outcome_preset create_demand failed: %s', exc)
                side_result = {'action': 'demand_failed', 'error': str(exc)}

    logger.info('Outcome preset %s applied to task %d by %s', preset_id, task.id,
                actor.full_name if actor else 'system')
    return {'task': task, 'side_result': side_result}


# ── Feature 12: Invalid phone flagging ────────────────────────────────────────

def flag_invalid_phone(task, actor=None, auto=False):
    """Mark a task's customer phone as invalid."""
    from django.utils import timezone as tz
    task.phone_invalid    = True
    task.phone_invalid_at = tz.now()
    task.save(update_fields=['phone_invalid', 'phone_invalid_at', 'updated_at'])
    note = f'{"[آلي] " if auto else ""}رقم الهاتف غير صالح — تم التحقق منه بعد {task.attempts} محاولات'
    task.result_note = note
    task.save(update_fields=['result_note'])
    logger.info('Task %d phone flagged invalid (auto=%s)', task.id, auto)
    return task


def unflag_invalid_phone(task, actor=None):
    """Remove the invalid-phone flag (after staff verified correct number)."""
    task.phone_invalid    = False
    task.phone_invalid_at = None
    task.save(update_fields=['phone_invalid', 'phone_invalid_at', 'updated_at'])
    return task


# ── Feature 1: Smart priority score ──────────────────────────────────────────

def _score_one(task, today) -> float:
    """
    Compute a priority score for one task.

    Components (each 0-1 normalised, weighted):
      LTV              0.25  — higher lifetime value → prioritise
      Churn risk       0.25  — higher churn risk → prioritise
      Days overdue     0.25  — more overdue → prioritise (capped at 30 days)
      Channel priority 0.25  — favoured channel → prioritise
    """
    from datetime import date as date_cls

    # LTV: normalise assuming 10,000 EGP = 1.0
    ltv_raw = 0.0
    if task.customer_id and task.customer:
        ltv_raw = float(task.customer.ltv or 0)
    ltv_score = min(ltv_raw / 10_000, 1.0)

    # Churn: already 0-1
    churn_score = 0.0
    if task.customer_id and task.customer:
        churn_score = float(task.customer.churn_score or 0)

    # Days overdue (or negative = days until due → not overdue)
    if task.due_date:
        days_delta = (today - task.due_date).days   # positive = overdue
        overdue_score = min(max(days_delta, 0) / 30, 1.0)
    else:
        overdue_score = 0.0

    # Channel: favoured → 1.0, others → 0.0
    from .models import FollowUpTask as FUT
    channel_score = 1.0 if task.sales_channel in FUT.FAVOURED_CHANNEL_CODES else 0.3

    score = (
        ltv_score      * 0.25 +
        churn_score    * 0.25 +
        overdue_score  * 0.25 +
        channel_score  * 0.25
    )
    return round(score, 4)


def update_priority_scores(branch=None, batch_size=500) -> int:
    """
    Recompute priority_score for all active (pending/called) tasks.
    Should run nightly via APScheduler.
    Returns number of tasks updated.
    """
    from datetime import date
    from django.utils import timezone as tz

    today = date.today()
    qs = (
        FollowUpTask.objects
        .filter(status__in=('pending', 'called'))
        .select_related('customer')
        .only(
            'id', 'due_date', 'sales_channel', 'priority_score',
            'customer__ltv', 'customer__churn_score',
        )
    )
    if branch:
        qs = qs.filter(branch=branch)

    updated = 0
    batch   = []
    now     = tz.now()

    for task in qs.iterator(chunk_size=batch_size):
        new_score = _score_one(task, today)
        if abs(new_score - task.priority_score) > 0.0001:
            task.priority_score         = new_score
            task.priority_score_updated = now
            batch.append(task)

        if len(batch) >= batch_size:
            FollowUpTask.objects.bulk_update(
                batch, ['priority_score', 'priority_score_updated']
            )
            updated += len(batch)
            batch = []

    if batch:
        FollowUpTask.objects.bulk_update(
            batch, ['priority_score', 'priority_score_updated']
        )
        updated += len(batch)

    logger.info('update_priority_scores: %d tasks updated', updated)
    return updated


# ── Feature 22: Dead account cleanup ─────────────────────────────────────────

def cleanup_dead_accounts(min_attempts: int = 5, min_stale_days: int = 30,
                          dry_run: bool = False) -> int:
    """
    Auto-cancel stale missed tasks where nobody has responded.

    Criteria:
      status='missed' AND attempts >= min_attempts
      AND last updated more than min_stale_days ago
      AND phone_invalid=True  (or attempts exhausted)

    Returns count cancelled.
    """
    from datetime import timedelta
    from django.utils import timezone as tz

    cutoff = tz.now() - timedelta(days=min_stale_days)
    qs = FollowUpTask.objects.filter(
        status='missed',
        attempts__gte=min_attempts,
        updated_at__lt=cutoff,
    )
    count = qs.count()
    if not dry_run:
        qs.update(
            status='cancelled',
            result_note='ألغي تلقائياً — تجاوز الحد الأقصى للمحاولات دون استجابة',
        )
    logger.info('cleanup_dead_accounts: %d tasks cancelled (dry_run=%s)', count, dry_run)
    return count


# ── Feature 21: Substitute / alternative detection ───────────────────────────

def auto_close_with_substitute_detection(since_minutes: int = 60 * 24) -> dict:
    """
    Extended auto-close that also recognises when a customer bought a SUBSTITUTE
    (item with the same effect_code / therapeutic indication) rather than the
    exact same item.

    Returns {'exact_closed': N, 'substitute_closed': M}
    """
    from datetime import timedelta

    exact_closed      = 0
    substitute_closed = 0

    since_date = (timezone.now() - timedelta(minutes=since_minutes)).date() - timedelta(days=1)

    # ── Pass 1: exact item match (existing logic) ──────────────────────────────
    exact_closed = auto_close_followup_tasks_from_erp(since_minutes=since_minutes)

    # ── Pass 2: same effect_code (substitute) ─────────────────────────────────
    # Find all open tasks whose item has an effect_code
    open_tasks = list(
        FollowUpTask.objects
        .filter(status__in=('pending', 'called'))
        .exclude(phcode='')
        .select_related('item')
        .only('id', 'phcode', 'item_id', 'item__effect_code',
              'source_sale_date', 'notes')
    )

    # Group open tasks by (phcode, effect_code)
    from collections import defaultdict
    effect_map = defaultdict(list)   # (phcode, effect_code) → [task]
    for task in open_tasks:
        if task.item and task.item.effect_code:
            effect_map[(task.phcode or '', task.item.effect_code)].append(task)

    if not effect_map:
        return {'exact_closed': exact_closed, 'substitute_closed': 0}

    all_phcodes    = list({k[0] for k in effect_map if k[0]})
    all_eff_codes  = list({k[1] for k in effect_map})

    # Recent ERP sales for these phcodes + any item with matching effect_code
    from apps.catalog.models import Item
    effect_item_ids = set(
        Item.objects.filter(effect_code__in=all_eff_codes)
        .values_list('id', flat=True)
    )

    # synced SOFTECH sales (PurchaseHistory) — the ERPTransaction mirror stopped 2026-04-30
    bought = _later_purchases(set(all_phcodes), effect_item_ids, since_date)
    eff_of = dict(Item.objects.filter(id__in=effect_item_ids).values_list('id', 'effect_code'))

    to_close = []
    for (phcode, eff_code), tasks in effect_map.items():
        for task in tasks:
            # a DIFFERENT item with the same effect_code, bought after the task's own sale
            bought_items = {iid for (pic, iid), sales in bought.items()
                            if pic == phcode and eff_of.get(iid) == eff_code and any(
                                not _is_source_invoice(task, inv)
                                and (task.source_sale_date is None or d > task.source_sale_date)
                                for d, inv in sales)}
            if task.item_id not in bought_items and bought_items:
                # Bought a DIFFERENT item with same effect_code → substitute
                task.status                  = 'auto_closed'
                task.closing_erp_transaction = 'substitute'
                task.result_note = (
                    f'أُغلق تلقائياً — العميل اشترى بديلاً '
                    f'(نفس التشخيص: {eff_code})'
                )
                to_close.append(task)
                substitute_closed += 1

    if to_close:
        FollowUpTask.objects.bulk_update(
            to_close,
            ['status', 'closing_erp_transaction', 'result_note', 'updated_at'],
        )

    logger.info(
        'auto_close_with_substitute_detection: exact=%d substitute=%d',
        exact_closed, substitute_closed,
    )
    return {'exact_closed': exact_closed, 'substitute_closed': substitute_closed}


# ── Feature 23: Bridge → Demand module ───────────────────────────────────────

def create_demand_from_task(task, actor=None, demand_type='out_of_stock',
                            source='call_center') -> 'DemandRecord':
    """
    Create a DemandRecord from a FollowUpTask.
    Used when outcome is 'item_unavailable' or 'requested_delivery'.
    Links the created record back to the task via task.demand_record FK.
    """
    from apps.demand.models import DemandRecord, DemandItem

    if not task.branch_id:
        raise ValueError('المهمة لا تحمل فرعاً — لا يمكن إنشاء طلب')

    customer_name = task.customer_name or task.phcode or '—'
    phone         = task.best_phone or task.customer_phone or ''
    item_name     = task.item.name if task.item_id and task.item else '—'

    demand = DemandRecord.objects.create(
        phone         = phone,
        customer_name = customer_name,
        customer      = task.customer,
        phcode        = task.phcode or '',
        branch        = task.branch,
        source        = source,
        priority      = 'chronic',
        notes         = (
            f'أُنشئ تلقائياً من مهمة المتابعة #{task.id} '
            f'للصنف {item_name}'
        ),
        created_by    = actor,
    )

    # Add the item
    if task.item_id:
        DemandItem.objects.create(
            demand      = demand,
            item        = task.item,
            quantity    = task.source_item_qty or 1,
            demand_type = demand_type,
        )

    # Link task → demand
    task.demand_record = demand
    task.save(update_fields=['demand_record', 'updated_at'])

    logger.info(
        'create_demand_from_task: demand %s created from task %d',
        demand.demand_number, task.id,
    )
    return demand


# ── Feature 24: Bridge → Vouchers module ─────────────────────────────────────

def assign_voucher_on_conversion(task, voucher_code: str, actor=None):
    """
    Assign a voucher to the task's customer phone when a follow-up converts.
    Creates a VoucherAssignment for the customer's phone.
    Returns the VoucherAssignment instance.
    """
    from apps.vouchers.models import Voucher, VoucherAssignment

    try:
        voucher = Voucher.objects.get(code=voucher_code, status='active')
    except Voucher.DoesNotExist:
        raise ValueError(f'القسيمة {voucher_code!r} غير موجودة أو غير نشطة')

    phone = task.best_phone or task.customer_phone
    if not phone:
        raise ValueError('لا يوجد رقم هاتف للعميل لتخصيص القسيمة')

    assignment, created = VoucherAssignment.objects.get_or_create(
        voucher        = voucher,
        customer_phone = phone,
        defaults={
            'customer':    task.customer,
            'assigned_by': actor,
        }
    )
    if not created:
        logger.info('Voucher %s already assigned to %s', voucher_code, phone)

    logger.info(
        'assign_voucher_on_conversion: voucher %s → task %d customer %s',
        voucher_code, task.id, phone,
    )
    return assignment


# ── Feature 3: Bridge → Campaigns module ─────────────────────────────────────

def create_campaign_from_tasks(
    task_ids: list,
    name: str,
    message_template: str,
    actor=None,
    featured_item_id: int = None,
) -> 'WhatsAppCampaign':
    """
    Create a WhatsAppCampaign from a batch of FollowUpTask IDs.
    Extracts unique customers with valid phones and creates one CampaignMessage per customer.
    Returns the created campaign (in 'draft' status — requires approval to send).
    """
    from apps.campaigns.models import WhatsAppCampaign, CampaignMessage

    tasks = (
        FollowUpTask.objects
        .filter(id__in=task_ids, phone_invalid=False)
        .select_related('customer', 'local_customer', 'item')
    )

    campaign = WhatsAppCampaign.objects.create(
        name             = name,
        message_template = message_template,
        status           = 'draft',
        featured_item_id = featured_item_id,
        created_by       = actor,
        target_filter    = {'source_followup_task_ids': task_ids[:100]},
    )

    # De-duplicate by phone
    seen_phones = set()
    messages    = []
    for task in tasks:
        phone = task.best_phone or task.customer_phone
        if not phone or phone in seen_phones:
            continue
        seen_phones.add(phone)

        customer     = task.customer
        cust_name    = task.customer_name or '—'
        item_obj     = task.item if task.item_id else None

        # Render message from template
        msg = message_template
        msg = msg.replace('{{customer_name}}', cust_name)
        msg = msg.replace('{{item_name}}',     item_obj.name if item_obj else '')
        msg = msg.replace('{{phone}}',         phone)

        wa_url = WhatsAppCampaign.build_whatsapp_url(phone, msg)

        messages.append(CampaignMessage(
            campaign      = campaign,
            customer      = customer,
            phone_number  = phone,
            customer_name = cust_name,
            message_text  = msg,
            whatsapp_url  = wa_url,
        ))

    if messages:
        CampaignMessage.objects.bulk_create(messages, batch_size=500)
        campaign.estimated_reach = len(messages)
        campaign.messages_queued = len(messages)
        campaign.save(update_fields=['estimated_reach', 'messages_queued'])

    # Link tasks to this campaign
    FollowUpTask.objects.filter(id__in=task_ids).update(source_campaign=campaign)

    logger.info(
        'create_campaign_from_tasks: campaign %d created with %d messages from %d tasks',
        campaign.id, len(messages), len(task_ids),
    )
    return campaign


# ── Feature 4: Upsell message helper ─────────────────────────────────────────

def build_multi_item_whatsapp_message(tasks: list, include_upsell: bool = False) -> str:
    """
    Build a single WhatsApp message covering multiple medications for one customer.
    tasks: list of FollowUpTask instances (all for the same customer).
    User selects which tasks to include — only those are passed here.
    """
    if not tasks:
        return ''

    anchor      = tasks[0]
    customer_name = anchor.customer_name or 'عزيزنا'
    customer_code = ''
    if anchor.customer_id and anchor.customer:
        customer_code = anchor.customer.softech_pic or anchor.customer.softech_id or anchor.phcode or ''
    elif anchor.local_customer_id and anchor.local_customer:
        customer_code = anchor.local_customer.phcode or anchor.phcode or ''
    else:
        customer_code = anchor.phcode or ''

    lines = [
        'أهلا بحضرتك يا فندم،',
        f'{customer_name} 🌿',
    ]
    if customer_code:
        lines.append(f'كود حضرتك {customer_code}')

    if len(tasks) == 1:
        # Single item — use the standard single-item message
        lines += [
            '',
            f'نتواصل معكم من صيدلية الرزيقي للتذكير بأن دواء/منتج '
            f'(*{tasks[0].item.name if tasks[0].item_id and tasks[0].item else "الدواء"}*) يقترب موعد نفاده.',
        ]
    else:
        lines += [
            '',
            f'نتواصل معكم من صيدلية الرزيقي للتذكير بأن الأدوية / المنتجات التالية يقترب موعد نفادها:',
            '',
        ]
        for task in tasks:
            item_name = task.item.name if task.item_id and task.item else '—'
            prof      = task.chronic_profile
            dur       = f' ({prof.expected_duration_days} يوم)' if prof else ''
            due       = f' — موعد الاستحقاق: {task.due_date}' if task.due_date else ''
            lines.append(f'💊 *{item_name}*{dur}{due}')

    lines += [
        '',
        'نحرص دائماً على متابعتكم لضمان استمرارية علاجكم. 💊',
        'يسعدنا خدمتكم في أقرب فرع أو عبر التوصيل لباب بيتكم 🏠',
    ]

    if include_upsell:
        # Gather FBT for the first task's item
        try:
            from apps.recommendations.engine import get_fbt_for_item
            if anchor.item_id:
                fbt = get_fbt_for_item(anchor.item_id, limit=2)
                if fbt:
                    upsell = ' · '.join(f['item_name'] for f in fbt if f.get('item_name'))
                    if upsell:
                        lines += [
                            '',
                            f'💡 *قد يهمكم أيضاً:* {upsell}',
                        ]
        except Exception:
            pass

    lines += ['', 'صيدليات الرزيقي — نهتم بصحتكم 💙']
    return '\n'.join(lines)


def build_upsell_whatsapp_message(task) -> str:
    """
    Build a combined WhatsApp message: refill reminder + top FBT upsell suggestion.
    Returns the combined message string.
    """
    from apps.recommendations.engine import get_fbt_for_item

    base_msg = task.render_whatsapp_message()

    if not task.item_id:
        return base_msg

    try:
        fbt = get_fbt_for_item(task.item_id, limit=2)
    except Exception:
        return base_msg

    if not fbt:
        return base_msg

    upsell_names = ' · '.join(f['item_name'] for f in fbt[:2] if f.get('item_name'))
    if not upsell_names:
        return base_msg

    upsell_block = (
        '\n\n💡 *عروض مكمّلة قد تهمك:*\n'
        f'{upsell_names}\n'
        'استفسر عنها في أقرب فرع أو أخبرنا برقم طلبك. 🌿'
    )
    return base_msg + upsell_block


# ── Feature 10: Bulk actions ──────────────────────────────────────────────────

def bulk_task_action(
    task_ids: list,
    action: str,
    actor=None,
    note: str = '',
    preset_id: str = '',
    assign_kwargs: dict = None,
) -> dict:
    """
    Apply an action to a list of task IDs atomically.

    Supported actions:
      mark_called   — mark all as called
      mark_done     — mark all as done
      mark_missed   — mark all as missed
      apply_preset  — apply a one-tap outcome preset (requires preset_id)
      assign        — assign all to staff (requires assign_kwargs)
      pin           — pin all
      unpin         — unpin all
      cancel        — cancel all (admin only)

    Returns {'processed': N, 'errors': [...]}.
    """
    tasks = list(
        FollowUpTask.objects
        .filter(id__in=task_ids, status__in=('pending', 'called'))
        .select_related('customer', 'item', 'branch')
    )

    processed = 0
    errors    = []

    for task in tasks:
        try:
            if action == 'mark_called':
                mark_task_called(task, note=note, staff=actor)
            elif action == 'mark_done':
                mark_task_done(task, note=note, staff=actor)
            elif action == 'mark_missed':
                mark_task_missed(task, note=note, staff=actor)
            elif action == 'apply_preset' and preset_id:
                apply_outcome_preset(task, preset_id, extra_note=note, actor=actor)
            elif action == 'assign' and assign_kwargs:
                assign_task(task, actor=actor, **assign_kwargs)
            elif action == 'pin':
                pin_task(task, actor)
            elif action == 'unpin':
                unpin_task(task, actor)
            elif action == 'cancel':
                task.status = 'cancelled'
                task.result_note = note or 'ألغي بشكل مجمّع'
                task.save(update_fields=['status', 'result_note', 'updated_at'])
            else:
                errors.append({'task_id': task.id, 'error': f'إجراء غير معروف: {action}'})
                continue
            processed += 1
        except Exception as exc:
            errors.append({'task_id': task.id, 'error': str(exc)})

    logger.info('bulk_task_action %s: %d processed, %d errors', action, processed, len(errors))
    return {'processed': processed, 'errors': errors}


def escalate_overdue_tasks(overdue_days: int = 3, dry_run: bool = False) -> dict:
    """
    Scans ALL pending FollowUpTasks whose due_date is more than `overdue_days`
    days in the past and marks them 'missed' — but only tasks that have EXISTED for
    `overdue_days` too: a task created already overdue (a catch-up batch — 2026-11-01 the
    generator restarted after 5 months with 2,876 of 4,788 tasks past due) gets the same
    chance to be called before it counts as a missed refill in the churn score.

    This is the critical link between the follow-up engine and the churn
    scoring engine: once a task is 'missed', segment_customers picks it up
    via missed_refills_map and adds it to the churn score.

    Called by: generate_followup_tasks management command (nightly)
    Also callable standalone: manage.py generate_followup_tasks --escalate-only

    Returns: {'escalated': N, 'already_missed': M}
    """
    from datetime import date, timedelta
    from django.db.models import Q

    cutoff = date.today() - timedelta(days=overdue_days)

    # Tasks that are still 'pending' or 'called' but passed due date + grace, and have
    # been open at least as long as the grace
    overdue_qs = FollowUpTask.objects.filter(
        status__in=('pending', 'called'),
        due_date__lt=cutoff,
        created_at__lt=timezone.now() - timedelta(days=overdue_days),
    )

    already_missed = FollowUpTask.objects.filter(status='missed').count()
    escalated = 0

    if not dry_run:
        # Bulk update is faster than iterating, but we lose per-task notes
        # Use update() for performance since these are automated transitions
        escalated = overdue_qs.update(
            status='missed',
            result_note='أُغلق تلقائياً — تجاوز موعد الاستحقاق دون استجابة',
        )
    else:
        escalated = overdue_qs.count()

    logger.info(
        'escalate_overdue_tasks: %d tasks → missed (dry_run=%s, overdue_days=%d)',
        escalated, dry_run, overdue_days,
    )
    return {'escalated': escalated, 'already_missed': already_missed}


def backfill_sales_channels() -> int:
    """
    Backfill FollowUpTask.sales_channel from PurchaseHistory.softech_phcode.

    DATA REALITY (discovered 2026-06-01):
      • Customer.softech_ptclassifcode — blank for ALL 193k customers (sync gap)
      • LocalCustomer.linked_customer  — NULL for all task-linked LocalCustomers
      • PurchaseHistory.softech_phcode — DIRECT phcode field on each invoice row
        → this is the authoritative join key: task phcode ↔ PH.softech_phcode
        → PH.sales_channel = stktransm.ptclassifcode (invoice-level, SOFTECH)

    Strategy:
      1. Extract phcode for every blank-channel task (from task.phcode field or notes)
      2. Bulk-load {phcode: latest_sales_channel} from PurchaseHistory
      3. bulk_update tasks
    """
    import re
    from apps.customers.models import PurchaseHistory

    # ── Step 1: Gather all blank-channel tasks + their phcodes ───────────────
    blank_tasks = list(
        FollowUpTask.objects
        .filter(sales_channel='')
        .only('id', 'phcode', 'notes', 'sales_channel')
    )
    logger.info('backfill_sales_channels: %d blank-channel tasks to process', len(blank_tasks))

    if not blank_tasks:
        return 0

    # Resolve phcode per task: prefer task.phcode field, fall back to notes
    _PHCODE_RE = re.compile(r'phcode:(\S+)')
    task_phcode_map = {}   # task.id → phcode
    all_phcodes = set()
    for task in blank_tasks:
        code = task.phcode or ''
        if not code and task.notes:
            m = _PHCODE_RE.match(task.notes)
            if m:
                code = m.group(1)
        if code:
            task_phcode_map[task.id] = code
            all_phcodes.add(code)

    logger.info('backfill_sales_channels: %d unique phcodes to look up', len(all_phcodes))

    if not all_phcodes:
        return 0

    # ── Step 2: Bulk-load latest channel per phcode from PurchaseHistory ─────
    phcode_channel = {}   # phcode → latest sales_channel
    for ph in (
        PurchaseHistory.objects
        .filter(softech_phcode__in=all_phcodes, sales_channel__gt='')
        .order_by('softech_phcode', '-invoice_date')
        .values('softech_phcode', 'sales_channel')
    ):
        code = ph['softech_phcode']
        if code not in phcode_channel:          # first row = latest (ordered DESC)
            phcode_channel[code] = ph['sales_channel']

    logger.info('backfill_sales_channels: %d phcodes matched in PurchaseHistory', len(phcode_channel))

    # ── Step 3: Apply and bulk-update ────────────────────────────────────────
    updated_tasks = []
    for task in blank_tasks:
        phcode = task_phcode_map.get(task.id)
        if not phcode:
            continue
        channel = phcode_channel.get(phcode, '')
        if channel:
            task.sales_channel = channel
            # Also backfill the phcode field if it was only in notes
            if not task.phcode:
                task.phcode = phcode
            updated_tasks.append(task)

    if updated_tasks:
        # Batch in chunks to avoid enormous single UPDATE
        chunk = 1000
        for i in range(0, len(updated_tasks), chunk):
            FollowUpTask.objects.bulk_update(updated_tasks[i:i+chunk], ['sales_channel', 'phcode'])

    logger.info('backfill_sales_channels: %d tasks updated with channel', len(updated_tasks))
    return len(updated_tasks)


def backfill_transaction_details() -> int:
    """
    Backfill full transaction detail on existing FollowUpTasks that were created
    before source_erp_transaction / source_total_amount / source_item_qty fields
    existed (migration 0011).

    Join path:
      task.phcode + task.source_sale_date + task.item_id
        → ERPTransactionLine.transaction.phcode + transaction_date + item_id
        → reference_number, softech_branch_code, total_amount, quantity, unit_price

    Also fills source_erp_transaction (docnumber) for tasks created by the old
    bulk service that never set it.
    """
    import re
    from datetime import timedelta
    from apps.erp.models import ERPTransaction, ERPTransactionLine

    _PHCODE_RE = re.compile(r'phcode:(\S+)')

    # ── Step 1: Gather tasks missing transaction detail ───────────────────────
    missing = list(
        FollowUpTask.objects
        .filter(source_erp_transaction='')
        .exclude(source_sale_date__isnull=True)
        .only('id', 'phcode', 'notes', 'item_id',
              'source_sale_date', 'source_erp_transaction',
              'source_softech_branch_code', 'source_total_amount',
              'source_item_qty', 'source_item_price')
    )
    logger.info('backfill_transaction_details: %d tasks need docnumber', len(missing))
    if not missing:
        return 0

    # Resolve phcode for each task (from field or legacy notes)
    task_info = {}   # task.id → {phcode, sale_date, item_id}
    all_phcodes = set()
    all_item_ids = set()
    all_dates = set()

    for task in missing:
        phcode = task.phcode or ''
        if not phcode and task.notes:
            m = _PHCODE_RE.match(task.notes)
            if m:
                phcode = m.group(1)
        if not phcode or not task.source_sale_date or not task.item_id:
            continue
        task_info[task.id] = {
            'phcode':    phcode,
            'sale_date': task.source_sale_date,
            'item_id':   task.item_id,
        }
        all_phcodes.add(phcode)
        all_item_ids.add(task.item_id)
        all_dates.add(task.source_sale_date)

    if not task_info:
        return 0

    logger.info('backfill_transaction_details: %d unique phcodes, %d items',
                len(all_phcodes), len(all_item_ids))

    # ── Step 2: Bulk fetch matching ERPTransactionLine rows ───────────────────
    # Window: ±1 day around sale_date to handle timezone edge cases
    date_min = min(all_dates) - timedelta(days=1)
    date_max = max(all_dates) + timedelta(days=1)

    line_rows = (
        ERPTransactionLine.objects
        .filter(
            transaction__doccode='115',
            transaction__phcode__in=all_phcodes,
            transaction__transaction_date__date__gte=date_min,
            transaction__transaction_date__date__lte=date_max,
            item_id__in=all_item_ids,
        )
        .values(
            'item_id',
            'quantity',
            'unit_price',
            'transaction__phcode',
            'transaction__transaction_date',
            'transaction__softech_branch_code',
            'transaction__reference_number',
            'transaction__total_amount',
        )
        .order_by('transaction__phcode', 'item_id', '-transaction__transaction_date')
    )

    # Build lookup: (phcode, item_id, date) → transaction detail
    # Keep only the most recent match per (phcode, item_id, date)
    tx_map = {}   # (phcode, item_id, date_str) → dict
    for row in line_rows:
        phcode   = row['transaction__phcode']
        item_id  = row['item_id']
        tx_date  = row['transaction__transaction_date']
        date_str = tx_date.date().isoformat() if hasattr(tx_date, 'date') else str(tx_date)[:10]
        key = (phcode, item_id, date_str)
        if key not in tx_map:   # first = most recent (ordered DESC)
            tx_map[key] = {
                'docnumber':    row['transaction__reference_number'] or '',
                'branch_code':  row['transaction__softech_branch_code'] or '',
                'total_amount': row['transaction__total_amount'],
                'item_qty':     row['quantity'],
                'item_price':   row['unit_price'],
            }

    logger.info('backfill_transaction_details: %d (phcode,item,date) matches found',
                len(tx_map))

    # ── Step 3: Apply to tasks ────────────────────────────────────────────────
    to_update = []
    fields = [
        'source_erp_transaction', 'source_softech_branch_code',
        'source_total_amount', 'source_item_qty', 'source_item_price',
    ]
    for task in missing:
        info = task_info.get(task.id)
        if not info:
            continue
        key = (info['phcode'], info['item_id'], info['sale_date'].isoformat())
        tx = tx_map.get(key)
        if not tx:
            continue
        task.source_erp_transaction      = tx['docnumber']
        task.source_softech_branch_code  = tx['branch_code']
        task.source_total_amount         = tx['total_amount']
        task.source_item_qty             = tx['item_qty']
        task.source_item_price           = tx['item_price']
        to_update.append(task)

    if to_update:
        chunk = 500
        for i in range(0, len(to_update), chunk):
            FollowUpTask.objects.bulk_update(to_update[i:i+chunk], fields)

    logger.info('backfill_transaction_details: %d tasks updated', len(to_update))
    return len(to_update)


def _build_phcode_channel_map(all_phcodes: list) -> dict:
    """
    Build a {phcode: sales_channel} mapping from PurchaseHistory.softech_phcode.

    Uses the most-recent invoice channel per phcode.
    PurchaseHistory.softech_phcode is the DIRECT phcode field on each invoice
    (= stktransm.phcode), matching localcustomers.phcode used in ERP transactions.

    Customer.softech_ptclassifcode is NOT used — it is blank for all customers.
    LocalCustomer.linked_customer is NOT used — it is NULL for all LC records here.
    """
    from apps.customers.models import PurchaseHistory

    if not all_phcodes:
        return {}

    phcode_channel = {}
    for ph in (
        PurchaseHistory.objects
        .filter(softech_phcode__in=all_phcodes, sales_channel__gt='')
        .order_by('softech_phcode', '-invoice_date')
        .values('softech_phcode', 'sales_channel')
    ):
        code = ph['softech_phcode']
        if code not in phcode_channel:      # first = latest (ordered DESC)
            phcode_channel[code] = ph['sales_channel']

    return phcode_channel


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
# Rule: notifications fire ONLY for tasks that are pinned OR have assigned_to set.
# Auto-generated tasks start un-pinned → zero noise until a human acts.

def notify_assignment(task, actor=None):
    """Legacy single-assignee notify — delegates to _notify_assigned_staff."""
    if task.assigned_to_id and task.assigned_to:
        _notify_assigned_staff(task, task.assigned_to, actor=actor, total=1)


def notify_pin(task, pinner):
    """
    Notify the pinner + their branch manager when they pin a task.
    Low-noise: only the pinner themselves is notified (confirmation).
    """
    try:
        from apps.notifications.models import Notification
        name      = task.customer_name or task.phcode or '—'
        item_name = task.item.name if task.item_id and task.item else '—'
        Notification.objects.create(
            recipient_id      = pinner.pk,
            title             = f'📌 مهمة مثبتة — {name}',
            body              = f'الصنف: {item_name} | الاستحقاق: {task.due_date}',
            notification_type = 'followup',
        )
    except Exception:
        pass


def notify_reminder(task):
    """
    Fire the scheduled reminder for a task.
    Sends to ALL current FollowUpTaskAssignment members + pinned_by.
    If nobody is watching (no assignments, not pinned) → silent.
    """
    from .models import FollowUpTaskAssignment
    recipients = set(
        FollowUpTaskAssignment.objects
        .filter(task=task)
        .values_list('staff_id', flat=True)
    )
    if task.pinned_by_id:
        recipients.add(task.pinned_by_id)
    if not recipients:
        return  # nobody watching — stay silent
    try:
        from apps.notifications.models import Notification
        name      = task.customer_name or task.phcode or '—'
        item_name = task.item.name if task.item_id and task.item else '—'
        prefix    = '⚠️ متأخر' if task.is_overdue else '💊 تذكير'
        for staff_id in recipients:
            Notification.objects.create(
                recipient_id      = staff_id,
                title             = f'{prefix} صرف — {name}',
                body              = f'الصنف: {item_name} | الاستحقاق: {task.due_date}',
                notification_type = 'followup',
            )
    except Exception:
        pass


# ── Deduplication: remove same (phcode, item_id) duplicates ──────────────────

def deduplicate_open_tasks(dry_run=False):
    """
    Remove duplicate open tasks that share the same (phcode, item_id).

    Root cause: the old duplicate-check used notes-string parsing which
    missed tasks created without the 'phcode:' prefix. This left multiple
    pending tasks for the same customer+item.

    Strategy:
      For each (phcode, item_id) group with >1 open task:
        - Keep the task with the highest priority_score (or earliest due_date)
        - Cancel the rest (set status='cancelled')

    Returns: { 'groups_affected': int, 'tasks_cancelled': int }
    """
    from django.db import transaction as db_transaction
    from django.db.models import Count

    # Find (phcode, item_id) pairs with duplicate open tasks
    dupes = (
        FollowUpTask.objects
        .filter(status__in=('pending', 'called'))
        .exclude(phcode='')
        .values('phcode', 'item_id')
        .annotate(cnt=Count('id'))
        .filter(cnt__gt=1)
    )

    groups_affected = 0
    tasks_cancelled = 0

    for group in dupes:
        phcode  = group['phcode']
        item_id = group['item_id']

        tasks = list(
            FollowUpTask.objects
            .filter(
                phcode=phcode,
                item_id=item_id,
                status__in=('pending', 'called'),
            )
            .order_by('-priority_score', 'due_date')   # best task first
        )
        if len(tasks) <= 1:
            continue

        keep   = tasks[0]
        remove = tasks[1:]

        groups_affected += 1
        tasks_cancelled += len(remove)

        if not dry_run:
            with db_transaction.atomic():
                for t in remove:
                    t.status      = 'cancelled'
                    t.result_note = 'أُلغي تلقائياً — مهمة مكررة (dedup)'
                    t.save(update_fields=['status', 'result_note', 'updated_at'])
                logger.info(
                    'Dedup: kept task %s, cancelled %s for phcode=%s item_id=%s',
                    keep.id, [t.id for t in remove], phcode, item_id,
                )

    logger.info('Dedup complete: %d groups, %d tasks cancelled', groups_affected, tasks_cancelled)
    return {'groups_affected': groups_affected, 'tasks_cancelled': tasks_cancelled}
