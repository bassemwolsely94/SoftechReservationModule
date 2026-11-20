"""
apps/pos_orders/missed_sales.py — Project 3 (a): missed sales → reservation SUGGESTIONS.

Source: OUR POS item selections (PosSelectionEvent). Only our POS knows the customer for
certain — SOFTECH pos_cancel.custcode is the sales account (1510 Walk-In, 1500 Home Delivery,
contracts), never the person (read-only probe 2026-11-03). Owner decision: our POS only.

An 'add' becomes a MissedSaleSuggestion when ALL hold:
  * the cart is finished: older than MISSED_SALES_MIN_AGE_MINUTES and its order (if any) either
    reached SOFTECH (pushing/pushed/settled) or was cancelled — a cart still being worked waits;
  * the customer is known and a real person (not an account placeholder, not merged away, not
    excluded from PIC analytics, file not closed / deceased);
  * the item was not sold: not a line of the cart's order, and the customer has not bought it
    in SOFTECH (PurchaseHistory) on or after the selection day;
  * there is no open suggestion and no open reservation for that customer + item.

Pure Postgres; never touches SOFTECH. Idempotent: (cart_token, item_code) is unique and every
re-run skips what already exists. Nothing here creates a Reservation — a person confirms.

C28 — second source, the call centre (own switch MISSED_SALES_CALLCENTER_ENABLED, default OFF;
the owner's earlier decision was "our POS only", so this waits for their yes). A catalog item an
agent recorded on a call (CallItem) becomes a suggestion when ALL hold:
  * the call is at least MISSED_SALES_CALL_WAIT_DAYS old (time to buy) and inside the window;
  * the item was not converted on the call (no reservation / transfer made from it);
  * the caller is a known, real customer (same rule as the POS source);
  * the customer has not bought the item in SOFTECH on or after the call day;
  * no open suggestion (either source) and no open reservation for that customer + item.
Idempotent: CallItem is UNIQUE on the suggestion (call_item). Branch = the call's branch, else the
customer's branch; a call with neither is skipped (suggestions are branch-scoped).
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('elrezeiky.pos_orders')

OPEN_RESERVATION_STATUSES = ('pending', 'available', 'contacted', 'confirmed')


def enabled():
    return bool(getattr(settings, 'MISSED_SALES_ENABLED', False))


def call_center_enabled():
    """C28: the call-centre source runs only when the inbox is on AND its own switch is on."""
    return enabled() and bool(getattr(settings, 'MISSED_SALES_CALLCENTER_ENABLED', False))


def _real_customer_ids(ids):
    """The subset of customer ids that are real people we may follow up."""
    from apps.customers import account_state
    from apps.customers.models import Customer
    from apps.pic_analytics.exclusions import excluded_pics
    excluded = excluded_pics()
    out = set()
    for c in Customer.objects.filter(pk__in=ids):
        if c.is_account_placeholder or (c.merged_into_pic or '').strip():
            continue
        if c.softech_pic and c.softech_pic in excluded:
            continue
        if account_state.state(c)['blocked']:
            continue
        out.add(c.pk)
    return out


def _bought_since(cust_ids, codes, since):
    """{(customer_id, item_code): [invoice datetimes]} — SOFTECH sales (doc 115) since `since`."""
    from apps.customers.models import PurchaseHistoryLine
    bought = {}
    for cid, code, at in (PurchaseHistoryLine.objects
                          .filter(purchase__customer_id__in=cust_ids, item__softech_id__in=codes,
                                  purchase__doc_code='115', purchase__invoice_date__gte=since)
                          .values_list('purchase__customer_id', 'item__softech_id', 'purchase__invoice_date')):
        bought.setdefault((cid, str(code).strip()), []).append(at)
    return bought


def _open_pairs(cust_ids, codes):
    """(customer_id, item_code) pairs that already have an open suggestion (any source) or an
    open reservation — never suggest those again."""
    from apps.reservations.models import Reservation
    from .models import MissedSaleSuggestion
    pairs = set(MissedSaleSuggestion.objects
                .filter(status=MissedSaleSuggestion.STATUS_NEW, customer_id__in=cust_ids)
                .values_list('customer_id', 'item_code'))
    pairs |= {(cid, str(code).strip()) for cid, code in Reservation.objects
              .filter(customer_id__in=cust_ids, status__in=OPEN_RESERVATION_STATUSES,
                      item__softech_id__in=codes)
              .values_list('customer_id', 'item__softech_id')}
    return pairs


def detect_call_center_missed_sales(now=None):
    """C28: call items asked for by a known customer and not bought → suggestions.
    Returns a summary dict. Caller checks call_center_enabled()."""
    from apps.callcenter.models import CallItem
    from .models import MissedSaleSuggestion

    now = now or timezone.now()
    wait = timedelta(days=int(getattr(settings, 'MISSED_SALES_CALL_WAIT_DAYS', 2)))
    keep = timedelta(days=int(getattr(settings, 'MISSED_SALES_EXPIRE_DAYS', 14)))
    summary = {'created': 0, 'skipped_sold': 0, 'skipped_open': 0, 'skipped_customer': 0,
               'skipped_branch': 0}

    items = list(CallItem.objects
                 .filter(item__isnull=False, converted_to='none', missed_sale__isnull=True,
                         call_log__customer__isnull=False,
                         call_log__called_at__gte=now - keep, call_log__called_at__lte=now - wait)
                 .select_related('item', 'call_log__customer')
                 .order_by('call_log__called_at', 'id'))
    if not items:
        return summary

    real = _real_customer_ids({ci.call_log.customer_id for ci in items})
    cust_ids = {ci.call_log.customer_id for ci in items} & real
    codes = {str(ci.item.softech_id).strip() for ci in items}
    since = (now - keep).replace(hour=0, minute=0, second=0, microsecond=0)
    bought = _bought_since(cust_ids, codes, since)
    open_pairs = _open_pairs(cust_ids, codes)

    created = []
    for ci in items:
        log, cid = ci.call_log, ci.call_log.customer_id
        code = str(ci.item.softech_id).strip()
        if cid not in real:
            summary['skipped_customer'] += 1
            continue
        branch_id = log.branch_id or log.customer.preferred_branch_id
        if not branch_id:
            summary['skipped_branch'] += 1
            continue
        call_day = timezone.localtime(log.called_at).date()
        if any(at and timezone.localtime(at).date() >= call_day for at in bought.get((cid, code), ())):
            summary['skipped_sold'] += 1
            continue
        if (cid, code) in open_pairs:
            summary['skipped_open'] += 1
            continue
        open_pairs.add((cid, code))
        qty = ci.quantity or Decimal('1')
        price = ci.item.pack_price or Decimal('0')
        created.append(MissedSaleSuggestion(
            branch_id=branch_id, customer_id=cid, item_id=ci.item_id, item_code=code,
            item_name=ci.item.name or code, qty=qty,
            value=(Decimal(str(price)) * qty).quantize(Decimal('0.01')),
            cart_token=None, selected_by_id=log.handled_by_id, seen_at=log.called_at,
            source=MissedSaleSuggestion.SOURCE_CALL_CENTER, call_item=ci,
        ))
    if created:
        MissedSaleSuggestion.objects.bulk_create(created, ignore_conflicts=True)
    summary['created'] = len(created)
    logger.info('[missed_sales:call_center] %s', summary)
    return summary


def detect_missed_sales(now=None):
    """Scan finished POS carts → create new MissedSaleSuggestion rows; expire stale ones.
    With the call-centre switch on, also scans call items (C28). Returns a summary dict."""
    summary = _detect_pos_missed_sales(now)
    if call_center_enabled():
        summary['call_center'] = detect_call_center_missed_sales(now)
    return summary


def _detect_pos_missed_sales(now=None):
    """The POS source (Project 3)."""
    from .models import MissedSaleSuggestion, PosSelectionEvent, SoftechSalesOrder

    now = now or timezone.now()
    min_age = timedelta(minutes=int(getattr(settings, 'MISSED_SALES_MIN_AGE_MINUTES', 60)))
    keep = timedelta(days=int(getattr(settings, 'MISSED_SALES_EXPIRE_DAYS', 14)))
    summary = {'created': 0, 'skipped_sold': 0, 'skipped_open': 0, 'skipped_customer': 0,
               'waiting': 0, 'expired': 0}

    summary['expired'] = (MissedSaleSuggestion.objects
                          .filter(status=MissedSaleSuggestion.STATUS_NEW, seen_at__lt=now - keep)
                          .update(status=MissedSaleSuggestion.STATUS_EXPIRED, decided_at=now))

    events = list(PosSelectionEvent.objects
                  .filter(event_type=PosSelectionEvent.EVENT_ADD, doc_kind='sale',
                          cart_token__isnull=False,
                          occurred_at__gte=now - keep, occurred_at__lte=now - min_age)
                  .order_by('occurred_at', 'id'))
    if not events:
        return summary

    tokens = {e.cart_token for e in events}
    orders = {o.client_token: o for o in SoftechSalesOrder.objects
              .filter(client_token__in=tokens).prefetch_related('lines')}
    reached = {SoftechSalesOrder.STATUS_PUSHING, SoftechSalesOrder.STATUS_PUSHED,
               SoftechSalesOrder.STATUS_SETTLED}

    # one candidate per (cart, item): the LAST add wins (qty / value as last put on the screen)
    carts = {}
    for e in events:
        carts.setdefault(e.cart_token, {})[e.item_code.strip()] = e

    existing = set(MissedSaleSuggestion.objects.filter(cart_token__in=tokens)
                   .values_list('cart_token', 'item_code'))

    candidates = []          # (event, customer_id)
    for token, items in carts.items():
        order = orders.get(token)
        sold = set()
        if order is not None:
            if order.status in reached:
                sold = {str(l.softech_itemcode).strip() for l in order.lines.all() if l.softech_itemcode}
            elif order.status != SoftechSalesOrder.STATUS_CANCELLED:
                summary['waiting'] += len(items)          # cart still being worked
                continue
        cust_id = next((e.customer_id for e in items.values() if e.customer_id), None) \
            or (order.customer_id if order is not None else None)
        for code, e in items.items():
            if (token, code) in existing:
                continue
            if code in sold:
                summary['skipped_sold'] += 1
                continue
            if not cust_id:
                summary['skipped_customer'] += 1
                continue
            candidates.append((e, cust_id))

    if not candidates:
        return summary

    real = _real_customer_ids({c for _, c in candidates})
    cust_ids = {c for _, c in candidates if c in real}
    codes = {e.item_code.strip() for e, _ in candidates}

    # bought later in SOFTECH (any branch): {(customer, item_code): [invoice datetimes]}
    bought = _bought_since(cust_ids, codes,
                           (now - keep).replace(hour=0, minute=0, second=0, microsecond=0))
    open_pairs = _open_pairs(cust_ids, codes)

    created = []
    for e, cid in candidates:
        code = e.item_code.strip()
        if cid not in real:
            summary['skipped_customer'] += 1
            continue
        seen_day = timezone.localtime(e.occurred_at).date()
        if any(at and timezone.localtime(at).date() >= seen_day for at in bought.get((cid, code), ())):
            summary['skipped_sold'] += 1
            continue
        if (cid, code) in open_pairs:
            summary['skipped_open'] += 1
            continue
        open_pairs.add((cid, code))                       # one open suggestion per customer + item
        created.append(MissedSaleSuggestion(
            branch_id=e.branch_id, customer_id=cid, item_id=e.item_id, item_code=code,
            item_name=e.item_name or code, qty=e.transqty or Decimal('1'),
            value=Decimal(str(e.transprice_total or 0)).quantize(Decimal('0.01')),
            cart_token=e.cart_token, seller_usercode=e.seller_usercode,
            selected_by_id=e.created_by_id, seen_at=e.occurred_at,
        ))
    if created:
        MissedSaleSuggestion.objects.bulk_create(created, ignore_conflicts=True)
    summary['created'] = len(created)
    logger.info('[missed_sales] %s', summary)
    return summary
