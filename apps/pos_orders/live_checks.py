"""
apps/pos_orders/live_checks.py — D-11 (owner 2026-11-19, «Allow + flag»).

When a live branch read fails during a sale, the sale still goes through exactly as before: no
checkout block and no change to any discount, price or posted value. What changes is that the gap is
no longer silent:

  • record_gap()            — one PosLiveCheckGap per (order, kind): what was not checked, the discount
                              given, the cashier, branch and time. Never raises (a posted sale must
                              never fail on its review record).
  • mark_rechecked()        — a later /ready that DID read the discount authority (and found the
                              discount within it) closes the open discount record by itself.
  • credit_missing_points() — after the branch read works again, add the points the sale missed, ONCE:
        1. only for a points sale the cashier has finalized (status settled) and an enrolled PIC;
        2. dry-run unless commit=True; switched by POS_POINTS_RECOVERY_ENABLED (default OFF) on top of
           the registered loyalty writer flag LOYALTY_SOFTECH_WRITE_ENABLED;
        3. claim: one conditional UPDATE open → crediting (a stale claim > 10 min may be re-claimed);
           a second caller gets 0 rows and writes nothing;
        4. SOFTECH guard: picpoints is checked for our vf1 tag «POS<order>-D11» first — a strict read
           that aborts on error. Found → mark credited, write nothing (covers a lost reply / a crash
           between the INSERT and our save);
        5. write through the existing writer apps/loyalty/pic_bridge.adjust_softech_points, then mark
           credited + AuditLog `pos_points_recovered` (who, points, order).
     The amount (owner 2026-11-19: per batch slice) is exactly what the live writer would have put in
     vf4: the SETTLED invoice's own stktrans lines (doccode 115 — one line per FEFO batch / reservation
     slice) are re-read, and each slice earns floor(transqty × transprice × rate / 100) — the formula
     of writer._execute_write._slice_points — with rate = custdiscounts[channel rep, items.itemcode_alt3]
     and 0 on a discounted line (custdiscp > 0). Any read failure aborts; it is never taken as 0.
"""
import logging
import math
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import PosLiveCheckGap as Gap, SoftechSalesOrder

logger = logging.getLogger('elrezeiky.pos_orders')

STALE_CLAIM_MIN = 10


def credit_tag(order_ref) -> str:
    """The picpoints.vf1 marker of a D-11 re-credit (≤ 50 chars; unique per order)."""
    return f'POS{int(order_ref)}-D11'


def _discount_given(order) -> Decimal:
    gross = Decimal(order.doc_value_gross or 0)
    net = Decimal(order.doc_value or 0)
    return max(gross - net, Decimal('0')).quantize(Decimal('0.01'))


def record_gap(order, kind, *, cashier=None, detail=''):
    """Create the review record for `order` (idempotent per order+kind). Never raises.
    Returns the row, or None if it could not be saved (logged)."""
    try:
        defaults = {
            'order': order, 'branch_id': order.branch_id,
            'cashier': cashier or order.created_by,
            'seller_usercode': order.seller_usercode or '',
            'softech_pic': order.softech_pic or '',
            'discount_given': _discount_given(order),
            'doc_value': Decimal(order.doc_value or 0),
            'detail': str(detail or '')[:255],
        }
        try:
            with transaction.atomic():
                gap, created = Gap.objects.get_or_create(order_ref=order.pk, kind=kind, defaults=defaults)
        except IntegrityError:                     # two callers raced on the unique (order_ref, kind)
            gap, created = Gap.objects.get(order_ref=order.pk, kind=kind), False
        if not created and gap.status == Gap.STATUS_RECHECKED and kind == Gap.KIND_DISCOUNT:
            # checked fine once, then the read failed again on a later /ready → open it again
            Gap.objects.filter(pk=gap.pk, status=Gap.STATUS_RECHECKED).update(
                status=Gap.STATUS_OPEN, discount_given=defaults['discount_given'],
                doc_value=defaults['doc_value'], resolved_at=None, resolved_by=None,
                resolution_note='', updated_at=timezone.now())
            gap.refresh_from_db()
        if created:
            from apps.audit.models import AuditLog
            AuditLog.log('pos_live_check_skipped', user=defaults['cashier'], obj=order,
                         new_data={'kind': kind, 'discount_given': str(defaults['discount_given']),
                                   'doc_value': str(defaults['doc_value'])},
                         note=defaults['detail'])
            logger.warning('[pos_orders] order=%s %s not checked live — review record %s', order.pk,
                           kind, gap.pk)
        return gap
    except Exception:                              # the review record must never fail a sale
        logger.exception('[pos_orders] order=%s could not save the %s review record', order.pk, kind)
        return None


def mark_rechecked(order, kind=Gap.KIND_DISCOUNT):
    """A later live check succeeded and found nothing wrong → close the open record by itself."""
    try:
        Gap.objects.filter(order_ref=order.pk, kind=kind, status=Gap.STATUS_OPEN).update(
            status=Gap.STATUS_RECHECKED, resolved_at=timezone.now(),
            resolution_note='أُعيد الفحص المباشر — الخصم داخل الصلاحية', updated_at=timezone.now())
    except Exception:
        logger.exception('[pos_orders] order=%s could not close the %s review record', order.pk, kind)


def review_gap(gap, *, actor_staff, note):
    """Supervisor closes a record with a note (no SOFTECH contact). Only an open record closes."""
    n = Gap.objects.filter(pk=gap.pk, status=Gap.STATUS_OPEN).update(
        status=Gap.STATUS_REVIEWED, resolved_by=actor_staff, resolved_at=timezone.now(),
        resolution_note=str(note or '')[:255], updated_at=timezone.now())
    if n:
        from apps.audit.models import AuditLog
        AuditLog.log('pos_live_check_reviewed', user=actor_staff, obj=gap.order,
                     old_data={'status': Gap.STATUS_OPEN},
                     new_data={'status': Gap.STATUS_REVIEWED, 'gap': gap.pk, 'kind': gap.kind},
                     note=str(note or '')[:255])
    return bool(n)


# ── points re-credit ──────────────────────────────────────────────────────────

class CreditRefused(Exception):
    """The credit cannot run now (a person-readable Arabic reason). Nothing was written."""


def recovery_enabled() -> bool:
    return bool(getattr(settings, 'POS_POINTS_RECOVERY_ENABLED', False))


def _tag_in_softech(pic, tag) -> bool:
    """Strict read of SOFTECH picpoints for our tag. Raises on any read error (never 'not found')."""
    from config.sybase import get_sybase_connection
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.picpoints WHERE phcode = ? AND vf1 = ?',
                    [pic, tag])
        row = cur.fetchone()
        return bool(row and int(row[0] or 0) > 0)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def slice_points(qty, unit_net, rate) -> int:
    """One slice's points — the same float formula as writer._execute_write._slice_points (vf4)."""
    if not rate:
        return 0
    return int(math.floor(float(qty) * float(unit_net) * float(rate) / 100.0))


def points_from_slices(slices, rate_of) -> int:
    """Σ per batch slice of the settled invoice. `slices`: stktrans line dicts (itemcode, transqty,
    transprice, custdiscp); `rate_of(itemcode)` → points %. A discounted slice earns 0 (native rule:
    points ⊻ discount)."""
    total = 0
    for d in slices:
        if float(d.get('custdiscp') or 0) > 0:
            continue
        total += slice_points(d.get('transqty') or 0, d.get('transprice') or 0,
                              rate_of(str(d.get('itemcode') or '').strip()))
    return total


def missing_points(order) -> int:
    """The points the settled sale should have earned, per batch slice (owner 2026-11-19): re-reads the
    final invoice's lines and the points schedule from the branch. Raises on any read failure."""
    if not order.softech_final_docnumber:
        raise CreditRefused('رقم الفاتورة النهائية غير معروف بعد — انتظر مطابقة الكاشير.')
    from . import writer as _writer
    _, slices, _ = _writer.read_finalized_sale(order.branch, order.softech_branchcode,
                                               order.softech_final_docnumber)
    from .discount_authority import DiscountAuthorityReader
    rdr = DiscountAuthorityReader(order.branch.effective_db_host, order.branch.effective_db_port,
                                  order.branch.db_name or 'SOFTECHDB9')
    try:
        rep = rdr.customer_personcode(order.channel)
        rates = {}

        def rate_of(code):
            if code not in rates:
                rate = 0.0
                alt3 = rdr.item_alt3(code) if rep else None
                if alt3:
                    c = rdr.contracted(rep, alt3)
                    if c is not None:
                        rate = float(c[0])
                rates[code] = rate
            return rates[code]
        return points_from_slices(slices, rate_of)
    finally:
        rdr.close()


def _check_creditable(gap):
    if gap.kind != Gap.KIND_POINTS:
        raise CreditRefused('هذا السجل ليس سجل نقاط.')
    order = gap.order
    if order is None:
        raise CreditRefused('الأمر لم يعد موجوداً.')
    if order.doc_kind != 'sale':
        raise CreditRefused('المرتجع لا يُضاف له نقاط.')
    if order.status != SoftechSalesOrder.STATUS_SETTLED:
        raise CreditRefused('الكاشير لم يُنهِ البيع بعد — تُضاف النقاط بعد التحصيل فقط.')
    if not order.softech_pic:
        raise CreditRefused('لا يوجد PIC على الأمر.')
    return order


def preview_credit(gap) -> dict:
    """Dry run: what a credit would add. Reads SOFTECH (points schedule + tag); writes nothing."""
    order = _check_creditable(gap)
    if gap.status == Gap.STATUS_CREDITED:
        return {'dry_run': True, 'already_credited': True, 'points': gap.points_credited or 0}
    try:
        pts = missing_points(order)
    except CreditRefused:
        raise
    except Exception:
        raise CreditRefused('تعذّر قراءة الفاتورة أو جدول النقاط من الفرع — حاول لاحقاً.')
    return {'dry_run': True, 'points': pts, 'pic': order.softech_pic, 'tag': credit_tag(order.pk)}


def credit_missing_points(gap, *, actor=None, commit=False) -> dict:
    """Credit the missing points of one points_rate record exactly once. See the module docstring.
    Returns a result dict; raises CreditRefused when nothing may be written now."""
    if not commit:
        return preview_credit(gap)
    if not recovery_enabled():
        raise CreditRefused('إضافة النقاط المؤجلة غير مفعّلة (POS_POINTS_RECOVERY_ENABLED).')
    from config.writers import writer_allowed
    if not writer_allowed('LOYALTY_SOFTECH_WRITE_ENABLED'):
        raise CreditRefused('الكتابة في نقاط SOFTECH غير مفعّلة (LOYALTY_SOFTECH_WRITE_ENABLED).')
    order = _check_creditable(gap)
    actor_staff = getattr(actor, 'staff_profile', None) if actor is not None else None

    # 1) claim — exactly one caller moves the record to CREDITING; a stale claim may be re-taken
    now = timezone.now()
    stale = now - timedelta(minutes=STALE_CLAIM_MIN)
    claimed = (Gap.objects.filter(pk=gap.pk, kind=Gap.KIND_POINTS)
               .filter(models_q_open_or_stale(stale))
               .update(status=Gap.STATUS_CREDITING, updated_at=now))
    if not claimed:
        gap.refresh_from_db()
        if gap.status == Gap.STATUS_CREDITED:
            return {'already_credited': True, 'points': gap.points_credited or 0, 'wrote_to_softech': False}
        raise CreditRefused('السجل قيد المعالجة أو مغلق — لم يُكتب شيء.')

    tag = credit_tag(order.pk)
    pic = order.softech_pic.strip()
    try:
        # 2) SOFTECH guard — a previous run may have inserted before our save
        if _tag_in_softech(pic, tag):
            _finish(gap, order, actor_staff, points=None, tag=tag, wrote=False)
            return {'already_credited': True, 'found_in_softech': True, 'wrote_to_softech': False}
        from . import points as _points
        if not _points.is_enrolled(pic):
            raise CreditRefused('العميل غير مشترك في نظام النقاط في SOFTECH — لا تُضاف نقاط.')
        pts = missing_points(order)
        if pts <= 0:
            _finish(gap, order, actor_staff, points=0, tag='', wrote=False)
            return {'points': 0, 'wrote_to_softech': False}
        from apps.loyalty.pic_bridge import adjust_softech_points
        op = str(getattr(actor, 'username', '') or 'pos-d11')
        new_balance = adjust_softech_points(pic, pts, reason=tag, operator=op)
    except CreditRefused:
        _release(gap)
        raise
    except Exception as exc:
        # The INSERT may or may not have landed; the record goes back to open and the next run's
        # tag check decides. Nothing is retried here.
        _release(gap)
        logger.error('[pos_orders] order=%s points re-credit failed: %s', order.pk, type(exc).__name__)
        raise CreditRefused('تعذّر إضافة النقاط الآن — السجل ما زال مفتوحاً وسيُفحص قبل أي محاولة جديدة.')
    _finish(gap, order, actor_staff, points=pts, tag=tag, wrote=True, actor=actor,
            balance_after=new_balance)
    return {'points': pts, 'wrote_to_softech': True, 'balance_after': new_balance}


def models_q_open_or_stale(stale):
    from django.db.models import Q
    return Q(status=Gap.STATUS_OPEN) | Q(status=Gap.STATUS_CREDITING, updated_at__lt=stale)


def _release(gap):
    Gap.objects.filter(pk=gap.pk, status=Gap.STATUS_CREDITING).update(
        status=Gap.STATUS_OPEN, updated_at=timezone.now())


def _finish(gap, order, actor_staff, *, points, tag, wrote, actor=None, balance_after=None):
    now = timezone.now()
    note = ('أُضيفت النقاط المؤجلة' if wrote else
            'وُجدت الإضافة مسجلة في SOFTECH من قبل' if points is None else 'لا نقاط مستحقة (0)')
    upd = {'status': Gap.STATUS_CREDITED, 'credited_at': now, 'credit_tag': tag,
           'resolved_by': actor_staff, 'resolved_at': now, 'resolution_note': note, 'updated_at': now}
    if points is not None:
        upd['points_credited'] = points
    Gap.objects.filter(pk=gap.pk, status=Gap.STATUS_CREDITING).update(**upd)
    gap.refresh_from_db()
    if wrote:
        from core.softech_audit import audit_softech_write
        audit_softech_write('pos_points_recovered', actor=actor, obj=order,
                            before={'points_on_sale': 0},
                            after={'points_credited': points, 'tag': tag, 'gap': gap.pk,
                                   'balance_after': balance_after})
    else:
        from apps.audit.models import AuditLog
        AuditLog.log('pos_points_recovery_closed', user=actor_staff, obj=order,
                     new_data={'gap': gap.pk, 'points': points, 'tag': tag}, note=note)
