"""
apps/pos_orders/checkout.py — D-18 server-side POS checkout (docs/architecture/39_POS_SERVER_CHECKOUT.md).

    POST /api/pos-orders/checkout/preview/   prices only; saves nothing
    POST /api/pos-orders/checkout/           Phase A (one PostgreSQL transaction) + Phase B (the writer)

Behind POS_SERVER_CHECKOUT (default OFF; optional POS_SERVER_CHECKOUT_BRANCHES). While it is OFF both
endpoints answer 404 {'detail': 'disabled'} and the screen runs today's create → offers → ready → push.

Nothing here is a second writer. Phase A reuses the create view's own perform_create, the offers
attach, and the /ready/ body (views._ready_checks → writer.prepare_order, unchanged). Phase B is the
/push/ body (views._push_checks → writer.push_order, unchanged: client_token, row lock, atomic
PUSHING claim, the 'POS<pk>' vf2 recovery, the outcome-unknown stop, POS_WRITER_ENABLED). The only
money worked out here is the نقدى/آجل split from the cashier's intent (pricing.resolve_tenders).

Why two phases (doc 39 §2.4): PostgreSQL and SOFTECH cannot share a transaction, and the writer needs
its PUSHING claim and outcome-unknown marker committed in PostgreSQL before the SOFTECH write. So
Phase A (create, offers, prices, tenders, checks, the total the cashier saw) is all-or-nothing, and
Phase B is the existing push, which leaves the order pushed / queued / push_failed exactly as today.
"""
import hashlib
import json
import logging
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from .models import SoftechSalesOrder, CLAIM_CHANNELS
from .permissions import CanOperatePosOrders, CanPushPosOrders
from .platform_accounts import is_platform_order
from . import pricing, writer

logger = logging.getLogger('pos_orders')

# pg advisory-lock namespace: one checkout per client_token at a time (double click / two tabs).
LOCK_NAMESPACE = 7_301_018

DISABLED = {'detail': 'disabled'}
MODES = ('dry_run', 'live')


# ── the switch ────────────────────────────────────────────────────────────────────────────────────
def enabled_for(branch) -> bool:
    """POS_SERVER_CHECKOUT on, and the branch is in POS_SERVER_CHECKOUT_BRANCHES (empty = all)."""
    if not getattr(settings, 'POS_SERVER_CHECKOUT', False):
        return False
    codes = [str(c).strip() for c in (getattr(settings, 'POS_SERVER_CHECKOUT_BRANCHES', None) or [])]
    if not codes:
        return True
    return branch is not None and str(branch.softech_branch_id or '').strip() in codes


def enabled_branch_ids():
    """For the POS reference data: None = every branch, [] = switch off, else the branch pks."""
    if not getattr(settings, 'POS_SERVER_CHECKOUT', False):
        return []
    codes = [str(c).strip() for c in (getattr(settings, 'POS_SERVER_CHECKOUT_BRANCHES', None) or [])]
    if not codes:
        return None
    from apps.branches.models import Branch
    return sorted(Branch.objects.filter(softech_branch_id__in=codes).values_list('pk', flat=True))


# ── small helpers ─────────────────────────────────────────────────────────────────────────────────
class _Abort(Exception):
    """Stop the checkout with this Response. Raised inside Phase A, it rolls back everything."""
    def __init__(self, response):
        super().__init__(response.data.get('detail') if isinstance(response.data, dict) else '')
        self.response = response


class _Rollback(Exception):
    """Preview only: throw the priced order away."""


def _bad(detail, field=None, code=status.HTTP_400_BAD_REQUEST, **flags):
    body = {'detail': detail, **flags}
    if field:
        body['errors'] = {field: [detail]}
    return Response(body, status=code)


def _num(v):
    """Normalised number text for the basket hash ('25', '25.0' and 25 hash the same)."""
    if v is None or str(v).strip() == '':
        return ''
    try:
        return format(Decimal(str(v).strip()).normalize(), 'f')
    except (InvalidOperation, ValueError):
        return str(v).strip()


def _money(v):
    return str(pricing._r2(v))


def _parse_money(v, label):
    try:
        return pricing._r2(Decimal(str(v).strip()))
    except (InvalidOperation, ValueError, AttributeError):
        raise _Abort(_bad(f'{label} غير صحيح.', 'checkout'))


def request_hash(data) -> str:
    """SHA-256 over the normalised basket (doc 39 §2.5): branch, channel, doc_kind, customer, PIC, lines
    [itemcode, qty, price, discount, batch, reservation], خصم فكة, tender intent, return lines."""
    ck = data.get('checkout') or {}
    intent = ck.get('tender_intent') or {}
    body = {
        'branch': _num(data.get('branch')),
        'channel': str(data.get('channel') or '').strip(),
        'doc_kind': str(data.get('doc_kind') or 'sale').strip(),
        'customer': _num(data.get('customer')),
        'softech_pic': str(data.get('softech_pic') or '').strip(),
        'return_of_invoice': _num(data.get('return_of_invoice')),
        'change_discount': _num(data.get('change_discount') or 0),
        'lines': [[str(l.get('softech_itemcode') or '').strip(), _num(l.get('qty')),
                   _num(l.get('item_sale_price')), _num(l.get('cust_discp')),
                   str(l.get('batchno') or '').strip(), bool(l.get('is_reservation'))]
                  for l in (data.get('lines') or []) if isinstance(l, dict)],
        'tender_intent': {'kind': str(intent.get('kind') or 'default'),
                          'credit': _num(intent.get('credit')), 'patient': _num(intent.get('patient'))},
        'return_lines': [[_num(r.get('dblitemflag')), _num(r.get('qty'))]
                         for r in (data.get('return_lines') or []) if isinstance(r, dict)],
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode('ascii')).hexdigest()


def _token_key(token) -> int:
    return int(hashlib.sha256(str(token).encode('ascii')).hexdigest()[:8], 16) - 2 ** 31   # signed int4


@contextmanager
def _token_lock(token):
    """Session advisory lock on the client_token for the whole checkout (Phase A + B). A second request
    with the same token (double click, second tab, retry while the first still runs) does not wait and
    does not post: it answers 202 busy. The writer's own PUSHING claim stays the real guard."""
    key = _token_key(token)
    with connection.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(%s, %s)', [LOCK_NAMESPACE, key])
        got = bool(cur.fetchone()[0])
    try:
        yield got
    finally:
        if got:
            with connection.cursor() as cur:
                cur.execute('SELECT pg_advisory_unlock(%s, %s)', [LOCK_NAMESPACE, key])


class _Req:
    """The create view reads request.data (seller, client_token, return_lines); this hands it the
    checkout body (or the token-less preview copy) and the real user."""
    def __init__(self, request, data):
        self._request, self.data, self.user = request, data, request.user

    def __getattr__(self, name):
        return getattr(self._request, name)


def _staff(user):
    try:
        return user.staff_profile
    except Exception:
        return None


# ── the response blocks ───────────────────────────────────────────────────────────────────────────
def totals_block(order):
    pays = list(order.payments.order_by('id').values_list('pay_type', 'amount'))
    credit = sum((Decimal(str(a)) for t, a in pays if t == 'credit'), Decimal('0'))
    now = sum((Decimal(str(a)) for t, a in pays if t != 'credit'), Decimal('0'))
    gross, net = Decimal(str(order.doc_value_gross or 0)), Decimal(str(order.doc_value or 0))
    cd = Decimal(str(order.change_discount or 0))
    due = net - cd
    claim = order.channel in CLAIM_CHANNELS
    return {
        'gross': _money(gross), 'discount': _money(gross - net), 'tax': _money(order.doc_value_tax or 0),
        'net': _money(net), 'change_discount': _money(cd), 'due': _money(due),
        'patient_pays': _money(now if claim else due), 'claim_amount': _money(credit if claim else 0),
    }


def tenders_block(order):
    return [{'pay_type': t, 'amount': _money(a)}
            for t, a in order.payments.order_by('id').values_list('pay_type', 'amount')]


# ── Phase A steps ─────────────────────────────────────────────────────────────────────────────────
def _create(request, data):
    """The create view's own serializer + perform_create (seller rule, branch check, return mirror)."""
    from . import views as v
    req = _Req(request, data)
    view = v.OrderListCreateView()
    view.request, view.args, view.kwargs, view.format_kwarg = req, (), {}, None
    ser = v.OrderSerializer(data=data, context={'request': req, 'view': view, 'format': None})
    try:
        ser.is_valid(raise_exception=True)
        view.perform_create(ser)
    except ValidationError as e:
        raise _Abort(Response({'detail': 'فشل التحقق من بيانات الأمر.', 'errors': e.detail},
                              status=status.HTTP_400_BAD_REQUEST))
    return ser.instance


def _apply_offers(order, actor):
    """Sales only. Flag OFF → the offers layer answers enabled=False (no-op). Flag ON → an error
    ABORTS the checkout (doc 39 S4) instead of being swallowed as the old browser path does."""
    off = {'enabled': False, 'attached': False, 'requires_approval': False}
    if order.doc_kind == 'return':
        return off
    from apps.offers.order_attach import apply_offers_to_order, execution_enabled
    try:
        r = apply_offers_to_order(order, actor=actor, commit=True)
    except Exception as exc:
        if not execution_enabled():
            return off
        logger.warning('[pos_checkout] offers failed for a new order (%s) - checkout aborted',
                       type(exc).__name__)
        raise _Abort(_bad('تعذّر تطبيق العروض — لم يُحفظ شيء. احذف صنف العرض أو أعد المحاولة.', 'offers'))
    return {'enabled': bool(r.get('enabled')), 'attached': bool(r.get('attached')),
            'requires_approval': bool(r.get('requires_approval')),
            'approval_request_id': r.get('approval_request_id')}


def _priced_doc_value(order, live):
    """Price the order once inside a savepoint that is always rolled back, to learn the net the split
    needs. Uses prepare_order itself (live price reads, contract discounts and blocked items included);
    خصم فكة is set aside so the default single tender balances. Leaves no trace."""
    sid = transaction.savepoint()
    try:
        order.change_discount = Decimal('0')
        writer.prepare_order(order, tenders=None, live=live)
        return Decimal(str(order.doc_value))
    except ValueError as e:
        raise _Abort(_bad(str(e)))
    finally:
        transaction.savepoint_rollback(sid)
        order.refresh_from_db()


def _tender_rows(order, intent, extras, live):
    """None (prepare_order's own rules) or the explicit نقدى/آجل rows for the intent."""
    kind = str((intent or {}).get('kind') or 'default')
    platform = is_platform_order(order)
    cd = pricing._r2(order.change_discount or 0)
    needs_net = not (kind == 'default' and cd == 0 and not platform)
    try:
        if kind not in pricing.TENDER_INTENT_KINDS:
            raise ValueError('طريقة سداد غير معروفة.')
        net = _priced_doc_value(order, live) if needs_net else Decimal('0')
        rows = pricing.resolve_tenders(order.channel, net, cd, intent, is_platform=platform,
                                       claim_channels=CLAIM_CHANNELS)
    except ValueError as e:
        raise _Abort(_bad(str(e), 'tenders'))
    if rows is None:
        return None
    serial = str((extras or {}).get('internal_payserial') or '')
    return [{'pay_type': r['pay_type'], 'amount': str(r['amount']), 'currency': 'L.E', 'exchange_rate': 1,
             'internal_payserial': serial} for r in rows]


def _prepare(request, order, intent, extras, live):
    """Tenders from the intent, then the SAME /ready/ checks the old path runs (views._ready_checks)."""
    from . import views as v
    tenders = None
    if order.doc_kind != 'return':
        # The new path never reuses old payment rows: the split is the intent's, rebuilt every time.
        # A return keeps the rows build_return_from_sale mirrored from the sale (refund = sale's own).
        order.payments.all().delete()
        tenders = _tender_rows(order, intent, extras, live)
    err = v._ready_checks(request, order, tenders, live)
    if err is not None:
        raise _Abort(err)
    order.refresh_from_db()
    if order.doc_kind != 'return':
        paid = sum((Decimal(str(a)) for a in order.payments.values_list('amount', flat=True)), Decimal('0'))
        due = Decimal(str(order.doc_value)) - Decimal(str(order.change_discount or 0))
        if paid != due:            # zero tolerance on the new path (doc 39 §2.6) — never expected
            logger.error('[pos_checkout] order=%s tenders %s != due %s - refused', order.pk, paid, due)
            raise _Abort(_bad(f'مجموع طرق السداد ({paid}) لا يساوي المطلوب ({due}).', 'tenders'))


def _check_expected(order, expected):
    """S3: never post at a total the cashier did not see. Raised inside Phase A → nothing saved."""
    if expected is None:
        return
    due = pricing._r2(Decimal(str(order.doc_value)) - Decimal(str(order.change_discount or 0)))
    if due != expected:
        raise _Abort(Response({
            'detail': f'تغيّر المطلوب من {expected} إلى {due} — راجِع الإجمالي الجديد ثم اضغط «إرسال» مرة أخرى.',
            'totals_changed': True, 'totals': totals_block(order), 'tenders': tenders_block(order),
        }, status=status.HTTP_409_CONFLICT))


def _read_checkout_block(data):
    ck = data.get('checkout')
    if not isinstance(ck, dict):
        ck = {}
    mode = str(ck.get('mode') or 'dry_run')
    if mode not in MODES:
        raise _Abort(_bad('وضع الإرسال غير معروف.', 'checkout'))
    intent = ck.get('tender_intent') if isinstance(ck.get('tender_intent'), dict) else {'kind': 'default'}
    extras = ck.get('tender_extras') if isinstance(ck.get('tender_extras'), dict) else {}
    cur, rate = extras.get('currency'), extras.get('exchange_rate')
    try:
        foreign = (cur not in (None, '', 'L.E')) or (rate not in (None, '') and Decimal(str(rate)) != 1)
    except (InvalidOperation, ValueError):
        foreign = True
    if foreign:
        raise _Abort(_bad('السداد على هذه الشاشة بالجنيه فقط (نقدى / آجل).', 'tenders'))
    raw = ck.get('expected_due')
    expected = None if raw in (None, '') else _parse_money(raw, 'المطلوب المعروض')
    return mode, bool(ck.get('confirm')), intent, extras, expected


def _gate(request):
    """Switch + POS branch lock (D2). Returns (branch, None) or (None, Response)."""
    if not getattr(settings, 'POS_SERVER_CHECKOUT', False):
        return None, Response(DISABLED, status=status.HTTP_404_NOT_FOUND)
    from . import views as v
    branch, err = v._pos_branch(request, (request.data or {}).get('branch'))
    if err is not None:
        return None, err
    if not enabled_for(branch):
        return None, Response(DISABLED, status=status.HTTP_404_NOT_FOUND)
    refused = v._channel_refusal(request)
    if refused is not None:
        return None, refused
    return branch, None


# ── views ─────────────────────────────────────────────────────────────────────────────────────────
@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([CanOperatePosOrders])
def checkout_preview(request):
    """The server's totals + نقدى/آجل split for the basket on screen. Runs the real Phase A (create,
    offers, prices, checks) in a transaction that is always rolled back: nothing is saved, no
    approval is raised (offers run without an actor), no order id is returned."""
    _, err = _gate(request)
    if err is not None:
        return err
    data = {k: v for k, v in dict(request.data).items() if k != 'client_token'}
    try:
        _, _, intent, extras, _ = _read_checkout_block(data)
        body = {}
        with transaction.atomic():
            order = _create(request, data)
            offers = _apply_offers(order, actor=None)
            ready_errors = None
            try:
                _prepare(request, order, intent, extras, bool(settings.POS_LIVE_PRICING))
            except _Abort as a:
                ready_errors = a.response.data
                order.refresh_from_db()
            body = {'totals': totals_block(order), 'tenders': tenders_block(order), 'offers': offers,
                    'ready_errors': ready_errors}
            raise _Rollback()
    except _Rollback:
        return Response(body)
    except _Abort as a:
        return a.response


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([CanOperatePosOrders])
def checkout(request):
    """One call: build the order, apply offers, price it, split نقدى/آجل, check it, then hand it to the
    unchanged writer. Body = the create payload + {checkout: {mode, confirm, expected_due,
    tender_intent, tender_extras}}. client_token is required: it is the idempotency key."""
    from . import views as v
    _, err = _gate(request)
    if err is not None:
        return err
    data = dict(request.data)
    token = v._valid_uuid(data.get('client_token'))
    if not token:
        return _bad('client_token مطلوب لإتمام البيع.', 'client_token')
    data['client_token'] = token
    try:
        mode, confirm, intent, extras, expected = _read_checkout_block(data)
    except _Abort as a:
        return a.response
    live_push = mode == 'live'
    if live_push and expected is None:
        return _bad('المطلوب المعروض مطلوب للإرسال الفعلي.', 'checkout')
    if live_push and writer.writer_enabled() and not confirm:
        return Response({'detail': 'الإرسال الفعلي إلى الكاشير يتطلب تأكيداً.', 'requires_confirm': True},
                        status=status.HTTP_409_CONFLICT)
    basket = request_hash(data)

    with _token_lock(token) as got:
        if not got:
            return Response({'detail': 'هذا الطلب قيد الإرسال من نافذة أخرى — انتظر لحظة.', 'busy': True},
                            status=status.HTTP_202_ACCEPTED)
        try:
            return _run(request, data, token, basket, live_push, confirm, intent, extras, expected)
        except IntegrityError:
            # the old path created an order with this token at the same moment
            return Response({'detail': 'هذا الطلب قيد التجهيز من نافذة أخرى — انتظر لحظة ثم أعد المحاولة.',
                             'busy': True}, status=status.HTTP_202_ACCEPTED)


def _replay_response(order, **flags):
    return Response({'order_id': order.pk, 'status': order.status, 'replayed': True,
                     'totals': totals_block(order), 'tenders': tenders_block(order),
                     'softech': {'mode': 'idempotent', 'wrote_to_softech': False,
                                 'docnumber': int(order.softech_docnumber) if order.softech_docnumber else None},
                     **flags})


def _run(request, data, token, basket, live_push, confirm, intent, extras, expected):
    from core import branch_scope
    from . import views as v
    S = SoftechSalesOrder
    live_pricing = bool(settings.POS_LIVE_PRICING)
    offers = {'enabled': False, 'attached': False, 'requires_approval': False}
    replayed = False
    try:
        with transaction.atomic():
            existing = S.objects.select_for_update().filter(client_token=token).first()
            if existing is not None:
                # ── replay rules (doc 39 §2.5) ── decided under the row lock
                if not branch_scope.allows(request.user, existing.branch_id):
                    return Response({'detail': 'client_token مستخدم.'}, status=status.HTTP_409_CONFLICT)
                if existing.status in (S.STATUS_PUSHED, S.STATUS_SETTLED) and existing.softech_docnumber:
                    return _replay_response(existing)                       # no writer call
                if existing.status == S.STATUS_PUSHING:
                    return Response({'detail': 'الطلب قيد الإرسال من عملية أخرى — لم يُكتب مرة ثانية.',
                                     'busy': True, 'order_id': existing.pk}, status=status.HTTP_202_ACCEPTED)
                if existing.status == S.STATUS_PUSH_FAILED and writer.is_outcome_unknown(existing):
                    return Response({'detail': 'انقطع الاتصال بعد إرسال الطلب للكاشير ولا نعرف هل حُفظ في '
                                               'SOFTECH — راجع شاشة الكاشير/SOFTECH قبل إعادة الإرسال '
                                               '(من شاشة الاستثناءات).',
                                     'outcome_unknown': True, 'order_id': existing.pk},
                                    status=status.HTTP_409_CONFLICT)
                if existing.status not in (S.STATUS_DRAFT, S.STATUS_READY, S.STATUS_QUEUED,
                                           S.STATUS_PUSH_FAILED) or existing.checkout_request_hash != basket:
                    # cancelled, an old-path order (no hash), or another basket under this token
                    return Response({'detail': 'رمز السلة مستخدم لطلب آخر — ابدأ سلة جديدة.',
                                     'token_reused': True, 'order_id': existing.pk},
                                    status=status.HTTP_409_CONFLICT)
                order, replayed = existing, True
            else:
                order = _create(request, data)
                order.checkout_request_hash = basket
                order.save(update_fields=['checkout_request_hash', 'updated_at'])
                offers = _apply_offers(order, actor=_staff(request.user))
                if offers['requires_approval'] and live_push:
                    # kept as a draft (offer + approval request committed); never pushed until approved
                    return Response({'detail': f'⏸ العرض يتطلب اعتماد مشرف قبل الترحيل — أُرسل طلب الاعتماد '
                                               f'(أمر #{order.pk}). لن يُرسل حتى الموافقة.',
                                     'requires_offer_approval': True, 'order_id': order.pk,
                                     'status': 'awaiting_offer_approval', 'offers': offers},
                                    status=status.HTTP_409_CONFLICT)
            _prepare(request, order, intent, extras, live_pricing)
            _check_expected(order, expected)
    except _Abort as a:
        return a.response

    # ── Phase B: the /push/ body, unchanged ──
    if not CanPushPosOrders().has_permission(request, None):
        return Response({'detail': 'جُهّز الأمر ولكن ليست لديك صلاحية الإرسال إلى الكاشير.',
                         'order_id': order.pk, 'status': order.status, 'replayed': replayed,
                         'totals': totals_block(order), 'tenders': tenders_block(order)},
                        status=status.HTTP_403_FORBIDDEN)
    resp = v._push_checks(request, order, want_live=live_push, confirm=confirm, confirmed_not_landed=False)
    result = resp.data if isinstance(resp.data, dict) else {}
    order.refresh_from_db()
    code = resp.status_code
    if result.get('busy'):
        code = status.HTTP_202_ACCEPTED
    body = {k: val for k, val in result.items() if k not in ('plan', 'readback', 'mode', 'docnumber',
                                                              'wrote_to_softech', 'order_id')}
    body.update({
        'order_id': order.pk, 'status': order.status, 'replayed': replayed,
        'totals': totals_block(order), 'tenders': tenders_block(order), 'offers': offers,
        'softech': {'mode': result.get('mode'), 'wrote_to_softech': bool(result.get('wrote_to_softech')),
                    'docnumber': result.get('docnumber') or (int(order.softech_docnumber)
                                                             if order.softech_docnumber else None)},
    })
    if 'plan' in result:
        body['plan'] = result['plan']
    return Response(body, status=code)
