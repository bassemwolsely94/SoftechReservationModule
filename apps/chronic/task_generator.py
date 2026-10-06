"""
apps.chronic.task_generator
============================
Generates FollowUpTask records (in apps.followups) based on
customer purchase history and active FollowUpProtocol rules.

Main entry point
----------------
generate_tasks_for_period(period_start, period_end, ...)
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
# Customer type detection  (shared with classifier.py)
# ─────────────────────────────────────────────────────────────────────────────

WALKIN_CLASSIF_CODES = {'1', '01', 'CASH', 'WALK', 'W'}
B2B_CLASSIF_CODES    = {'INS', 'B2B', 'CORP', 'GOV', '5', '6', '7', '8', '9'}


def _customer_type(customer) -> str:
    if customer is None:
        return 'walkin'
    code = (customer.softech_ptclassifcode or '').upper().strip()
    if code in WALKIN_CLASSIF_CODES:
        return 'walkin'
    if code in B2B_CLASSIF_CODES:
        return 'b2b'
    return 'home_delivery'


def _matches_type_filter(customer, type_filter: str) -> bool:
    if type_filter == 'all':
        return True
    return _customer_type(customer) == type_filter


# ─────────────────────────────────────────────────────────────────────────────
# Due date calculation
# ─────────────────────────────────────────────────────────────────────────────

def _calc_due_date(protocol, sale_date: date, ingredient) -> date | None:
    """
    Returns the follow-up due date for this protocol given the sale date.
    Returns None if the date cannot be determined.
    """
    ft = protocol.frequency_type

    if ft == 'days_after_purchase':
        if protocol.days is None:
            return None
        return sale_date + timedelta(days=protocol.days)

    elif ft == 'before_runout':
        # Need ChronicMedicationProfile or a default pack duration
        profile = _get_profile_for_ingredient(ingredient)
        duration = profile.expected_duration_days if profile else 30
        before   = protocol.days or 5
        return sale_date + timedelta(days=max(1, duration - before))

    elif ft == 'on_runout':
        profile  = _get_profile_for_ingredient(ingredient)
        duration = profile.expected_duration_days if profile else 30
        return sale_date + timedelta(days=duration)

    elif ft == 'days_after_last_task':
        # Computed at task-creation time from last task date — fall back to sale date
        if protocol.days is None:
            return None
        return sale_date + timedelta(days=protocol.days)

    elif ft == 'fixed_monthly':
        # Same day-of-month as sale, next month
        try:
            next_month = sale_date.replace(month=sale_date.month + 1)
        except ValueError:
            # month overflow (December → January next year)
            next_month = sale_date.replace(year=sale_date.year + 1, month=1)
        return next_month

    return None


def _get_profile_for_ingredient(ingredient):
    """
    Try to find a ChronicMedicationProfile for any item linked to this ingredient.
    Returns the first one found, or None.
    """
    try:
        from apps.followups.models import ChronicMedicationProfile
        map_item = ingredient.item_maps.first()
        if map_item:
            return ChronicMedicationProfile.objects.filter(item=map_item.item).first()
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Trigger condition check
# ─────────────────────────────────────────────────────────────────────────────

def _matches_trigger(protocol, customer, ingredient, sale_date: date) -> bool:
    cond = protocol.trigger_condition

    if cond == 'any_purchase':
        return True

    if cond == 'first_purchase':
        # True if customer has no prior purchase of any item with this ingredient
        # before this sale date
        from apps.customers.models import PurchaseHistoryLine
        prior = PurchaseHistoryLine.objects.filter(
            purchase__customer=customer,
            purchase__doc_code='115',
            item__ingredient_maps__active_ingredient=ingredient,
            purchase__invoice_date__date__lt=sale_date,
        ).exists()
        return not prior

    if cond == 'repeat_only':
        from apps.customers.models import PurchaseHistoryLine
        prior = PurchaseHistoryLine.objects.filter(
            purchase__customer=customer,
            purchase__doc_code='115',
            item__ingredient_maps__active_ingredient=ingredient,
            purchase__invoice_date__date__lt=sale_date,
        ).exists()
        return prior

    if cond == 'no_refill_missed':
        # True if customer was expected to refill (had a prior purchase) but didn't
        # within the expected duration window
        from apps.customers.models import PurchaseHistoryLine
        profile  = _get_profile_for_ingredient(ingredient)
        duration = profile.expected_duration_days if profile else 30
        window_start = sale_date - timedelta(days=duration + 10)
        window_end   = sale_date - timedelta(days=1)
        prior = PurchaseHistoryLine.objects.filter(
            purchase__customer=customer,
            purchase__doc_code='115',
            item__ingredient_maps__active_ingredient=ingredient,
            purchase__invoice_date__date__range=(window_start, window_end),
        ).exists()
        return prior  # there was a prior purchase that should have triggered refill

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication check
# ─────────────────────────────────────────────────────────────────────────────

def _already_has_open_task(customer, ingredient, due_date: date) -> bool:
    """
    Returns True if an open follow-up task already exists for this customer
    and ingredient within ±3 days of the due date.
    """
    try:
        from apps.followups.models import FollowUpTask
        return FollowUpTask.objects.filter(
            customer=customer,
            item__ingredient_maps__active_ingredient=ingredient,
            status__in=['pending', 'called'],
            due_date__range=(
                due_date - timedelta(days=3),
                due_date + timedelta(days=3),
            ),
        ).exists()
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Message template rendering
# ─────────────────────────────────────────────────────────────────────────────

def _render_template(template: str, customer, item, ingredient, sale_date: date) -> str:
    if not template:
        return ''
    days_since = (date.today() - sale_date).days
    try:
        return template.format(
            customer_name=getattr(customer, 'name', '') if customer else 'العميل',
            item_name=item.name if item else '',
            ingredient_name=ingredient.name_ar or ingredient.name,
            days_since_purchase=days_since,
            branch_name='',   # filled in at task level if needed
            phone=getattr(customer, 'phone', '') if customer else '',
        )
    except (KeyError, IndexError):
        return template


# ─────────────────────────────────────────────────────────────────────────────
# Main generator
# ─────────────────────────────────────────────────────────────────────────────

def generate_tasks_for_period(
    period_start: date,
    period_end: date,
    branch_ids=None,
    customer_types=None,
    ingredient_ids=None,
    dry_run: bool = False,
    requested_by=None,
) -> dict:
    """
    For every qualifying sale line in the period:
      1. Find the item's chronic active ingredient(s)
      2. For each active FollowUpProtocol on that ingredient:
         a. Check customer type filter
         b. Check trigger condition
         c. Calculate due date
         d. Deduplication check
         e. Create FollowUpTask (or count for dry_run)

    Returns a summary dict:
      {
        'created': int,
        'skipped_dedup': int,
        'skipped_no_customer': int,
        'skipped_type_filter': int,
        'skipped_trigger': int,
        'breakdown': [ { ingredient, protocol, count }, ... ]
      }
    """
    from apps.customers.models import PurchaseHistoryLine
    from apps.chronic.models import FollowUpProtocol

    # Build sale-line queryset
    lines_qs = PurchaseHistoryLine.objects.filter(
        purchase__doc_code='115',
        purchase__invoice_date__date__range=(period_start, period_end),
        item__ingredient_maps__active_ingredient__is_chronic=True,
        item__ingredient_maps__active_ingredient__followup_protocols__is_active=True,
    ).select_related(
        'purchase', 'purchase__customer', 'purchase__branch', 'item'
    ).prefetch_related(
        'item__ingredient_maps__active_ingredient__followup_protocols__applies_to_branches',
    ).distinct()

    if branch_ids:
        lines_qs = lines_qs.filter(purchase__branch_id__in=branch_ids)

    if ingredient_ids:
        lines_qs = lines_qs.filter(
            item__ingredient_maps__active_ingredient_id__in=ingredient_ids
        )

    # Counters
    created               = 0
    skipped_dedup         = 0
    skipped_no_customer   = 0
    skipped_type_filter   = 0
    skipped_trigger       = 0
    breakdown             = {}  # (ingredient_id, protocol_id) → count

    for line in lines_qs:
        customer  = line.purchase.customer
        branch    = line.purchase.branch
        item      = line.item
        sale_date = (
            line.purchase.invoice_date.date()
            if hasattr(line.purchase.invoice_date, 'date')
            else line.purchase.invoice_date
        )
        if sale_date is None:
            continue

        for ing_map in item.ingredient_maps.all():
            ingredient = ing_map.active_ingredient
            if not ingredient.is_chronic:
                continue

            for protocol in ingredient.followup_protocols.filter(is_active=True):

                # Branch filter
                branch_whitelist = list(protocol.applies_to_branches.values_list('id', flat=True))
                if branch_whitelist and (branch_ids is None or branch.id not in branch_whitelist):
                    if branch.id not in branch_whitelist:
                        continue

                # Customer type filter
                if customer_types and 'all' not in customer_types:
                    if not _matches_type_filter(customer, protocol.customer_type_filter):
                        skipped_type_filter += 1
                        continue
                elif not _matches_type_filter(customer, protocol.customer_type_filter):
                    skipped_type_filter += 1
                    continue

                # Must have a customer record for actual task creation
                if customer is None:
                    skipped_no_customer += 1
                    continue

                # Trigger condition
                if not _matches_trigger(protocol, customer, ingredient, sale_date):
                    skipped_trigger += 1
                    continue

                # Due date
                due = _calc_due_date(protocol, sale_date, ingredient)
                if due is None:
                    continue

                # Deduplication
                if _already_has_open_task(customer, ingredient, due):
                    skipped_dedup += 1
                    continue

                # Create task
                key = (ingredient.id, protocol.id)
                breakdown[key] = breakdown.get(key, 0) + 1
                created += 1

                if not dry_run:
                    _create_task(
                        customer=customer,
                        item=item,
                        ingredient=ingredient,
                        protocol=protocol,
                        branch=branch,
                        sale_date=sale_date,
                        due_date=due,
                        requested_by=requested_by,
                    )

    # Format breakdown for response
    breakdown_list = []
    for (ing_id, proto_id), cnt in breakdown.items():
        try:
            ing   = ActiveIngredient.objects.get(pk=ing_id)
            proto = FollowUpProtocol.objects.get(pk=proto_id)
            breakdown_list.append({
                'ingredient_id':   ing_id,
                'ingredient_name': ing.name_ar or ing.name,
                'protocol_id':     proto_id,
                'protocol_name':   proto.name,
                'task_type':       proto.task_type,
                'count':           cnt,
            })
        except Exception:
            pass

    return {
        'dry_run':              dry_run,
        'period_start':         period_start.isoformat(),
        'period_end':           period_end.isoformat(),
        'created':              created,
        'skipped_dedup':        skipped_dedup,
        'skipped_no_customer':  skipped_no_customer,
        'skipped_type_filter':  skipped_type_filter,
        'skipped_trigger':      skipped_trigger,
        'breakdown':            breakdown_list,
    }


def _create_task(customer, item, ingredient, protocol, branch,
                 sale_date: date, due_date: date, requested_by=None):
    """Create a FollowUpTask in apps.followups."""
    try:
        from apps.followups.models import FollowUpTask, ChronicMedicationProfile

        chronic_profile = ChronicMedicationProfile.objects.filter(item=item).first()
        notes = _render_template(
            protocol.message_template, customer, item, ingredient, sale_date
        )

        # Map protocol priority to task priority
        priority_map = {
            'low': 'refill', 'normal': 'refill',
            'high': 'chronic', 'urgent': 'chronic', 'chronic': 'chronic',
        }
        task_type = priority_map.get(protocol.priority, 'chronic')

        FollowUpTask.objects.create(
            customer         = customer,
            item             = item,
            branch           = branch,
            chronic_profile  = chronic_profile,
            task_type        = task_type,
            due_date         = due_date,
            priority         = protocol.priority if hasattr(FollowUpTask, 'priority') else None,
            source_sale_date = sale_date,
            notes            = notes,
            created_by       = requested_by,
        )
    except Exception as e:
        # Log but don't abort the entire generation run
        import logging
        logging.getLogger(__name__).warning(
            f'Failed to create FollowUpTask for customer={customer} item={item}: {e}'
        )
