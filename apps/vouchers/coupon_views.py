"""
apps/vouchers/coupon_views.py

API for the gift-coupon screen (VouchersPage → «كوبونات الهدايا»), under /api/vouchers/coupons/.

Permissions are enforced HERE (CLAUDE.md §9):
  * view   — COUPON_VIEW_ROLES (default admin, supervisor, purchasing, quality_manager):
             serial history, flagged customers, lines without a serial, batches.
  * manage — the same roles that may push supplier invoices into SOFTECH
             (SupplierInvoiceViewSet._PUSH_ROLES): generate a batch, download its print
             sheet, rehearse (rollback probe), stock it in SOFTECH, run the sync now.
Stocking goes through the existing audited path only (coupon_push → invoices.writer), still
gated by INVOICE_WRITER_ENABLED, serialised by a PostgreSQL advisory lock per batch, and
every generate / stock action is written to the AuditLog.
"""
import datetime as dt
import logging

from django.conf import settings
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from . import coupon_dashboard as dash
from . import coupons
from core.errors import public_error

logger = logging.getLogger('elrezeiky.vouchers')


def _profile(request):
    p = getattr(request.user, 'staff_profile', None)
    return p if (p and p.is_active) else None


def view_roles():
    return set(getattr(settings, 'COUPON_VIEW_ROLES',
                       ('admin', 'supervisor', 'purchasing', 'quality_manager')))


def manage_roles():
    from apps.invoices.views import SupplierInvoiceViewSet
    return set(SupplierInvoiceViewSet._PUSH_ROLES)


def can_view(p):
    return bool(p and (p.role in view_roles() or p.role in manage_roles()))


def can_manage(p):
    return bool(p and p.role in manage_roles())


class CanViewCoupons(BasePermission):
    message = 'غير مصرح بعرض رقابة كوبونات الهدايا'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and can_view(_profile(request)))


class CanManageCoupons(BasePermission):
    message = 'غير مصرح بتوليد أو إدخال كوبونات الهدايا'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and can_manage(_profile(request)))


def _audit(request, action, batch, note='', extra=None):
    try:
        from apps.audit.models import AuditLog
        AuditLog.log(action, user=_profile(request), obj=batch, note=note[:255],
                     extra=extra, request=request)
    except Exception:
        logger.exception('[coupons] audit log failed')


def _batch(pk):
    from .models import CouponBatch
    return (CouponBatch.objects.select_related('points_invoice', 'served_invoice', 'created_by')
            .filter(pk=pk).first())


def _json_safe(v):
    """Probe / push results may hold driver values (Java/Sybase types) — stringify them."""
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return str(v)


# ── read ───────────────────────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([CanViewCoupons])
def overview(request):
    data = dash.overview()
    data['can_manage'] = can_manage(_profile(request))
    return Response(data)


@api_view(['GET'])
@permission_classes([CanViewCoupons])
def serial_lookup(request):
    q = (request.query_params.get('q') or '').strip()
    if not q:
        return Response({'detail': 'أدخل السريال أو الرقم'}, status=status.HTTP_400_BAD_REQUEST)
    return Response(dash.serial_lookup(q))


@api_view(['GET'])
@permission_classes([CanViewCoupons])
def customers(request):
    pic = (request.query_params.get('pic') or '').strip()
    if pic:
        return Response(dash.customer_history(pic))
    active = request.query_params.get('all') not in ('1', 'true')
    return Response(dash.customers_over(active_only=active))


@api_view(['GET'])
@permission_classes([CanViewCoupons])
def no_serial(request):
    try:
        days = max(1, min(int(request.query_params.get('days') or 30), 3650))
    except ValueError:
        days = 30
    return Response(dash.no_serial_lines(branch=(request.query_params.get('branch') or '').strip(),
                                         days=days))


@api_view(['GET', 'POST'])
@permission_classes([CanViewCoupons])
def batches(request):
    from .models import CouponBatch
    if request.method == 'GET':
        qs = (CouponBatch.objects.select_related('points_invoice', 'served_invoice', 'created_by')
              .order_by('-created_at')[:50])
        return Response({'rows': [dash.batch_dict(b) for b in qs]})
    # POST = generate a new batch (manage only). Nothing is written to SOFTECH.
    if not can_manage(_profile(request)):
        return Response({'detail': CanManageCoupons.message}, status=status.HTTP_403_FORBIDDEN)
    try:
        size = int(request.data.get('size') or coupons.batch_size())
    except (TypeError, ValueError):
        size = 0
    if not 1 <= size <= coupons.batch_size():
        return Response({'detail': f'عدد الكوبونات يجب أن يكون بين 1 و {coupons.batch_size()}'},
                        status=status.HTTP_400_BAD_REQUEST)
    from config.sybase import get_sybase_connection
    try:      # fail-closed: never pick expiry dates without checking SOFTECH's live rows
        conn = get_sybase_connection()
        try:
            blocked = coupons.read_blocked_expiries(conn)
        finally:
            conn.close()
    except Exception as e:
        return Response({'detail': f'تعذّر قراءة تواريخ الصلاحية من SOFTECH: {public_error(request, e)}'},
                        status=status.HTTP_502_BAD_GATEWAY)
    try:
        batch = coupons.generate_batch(size=size, created_by=_profile(request), blocked_dates=blocked,
                                       notes=(request.data.get('notes') or '')[:500])
    except ValueError as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    _audit(request, 'coupon_batch_generated', batch,
           note=f'{batch.size} serials {batch.serial_from}–{batch.serial_to}',
           extra={'expiry_from': str(batch.expiry_from), 'expiry_to': str(batch.expiry_to)})
    return Response(dash.batch_dict(_batch(batch.pk)), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([CanManageCoupons])
def batch_export(request, pk):
    """kind=print → the 4-up print sheet (xlsx); kind=dataload → the RPA DataLoad TSV."""
    import io
    batch = _batch(pk)
    if not batch:
        return Response({'detail': 'الدفعة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
    kind = request.query_params.get('kind') or 'print'
    if kind == 'dataload':
        body = ''.join('\t'.join(r) + '\r\n' for r in coupons.dataload_rows(batch))
        resp = HttpResponse(body.encode('utf-8'), content_type='text/tab-separated-values; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="coupon_batch_{batch.pk}_dataload.tsv"'
    else:
        buf = io.BytesIO()
        coupons.print_workbook(batch).save(buf)
        resp = HttpResponse(buf.getvalue(), content_type=(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'))
        resp['Content-Disposition'] = f'attachment; filename="coupon_batch_{batch.pk}_print.xlsx"'
    _audit(request, 'coupon_batch_exported', batch, note=kind)
    return resp


@api_view(['POST'])
@permission_classes([CanManageCoupons])
def batch_probe(request, pk):
    """Rollback rehearsal on HQ (INSERT → read back → ROLLBACK) diffed against the reference
    documents. Nothing is kept in SOFTECH."""
    from .coupon_push import probe_batch
    batch = _batch(pk)
    if not batch:
        return Response({'detail': 'الدفعة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
    if batch.status != 'generated':
        return Response({'detail': 'الدفعة ليست بانتظار الإدخال'}, status=status.HTTP_400_BAD_REQUEST)
    with dash.pg_lock(dash.LOCK_PUSH * 1000 + batch.pk) as got:
        if not got:
            return Response({'detail': 'هذه الدفعة قيد التنفيذ الآن — انتظر حتى تنتهي.'},
                            status=status.HTTP_409_CONFLICT)
        try:
            report = probe_batch(batch)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception('[coupons] probe batch %s failed', batch.pk)
            return Response({'detail': f'فشل الاختبار: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)
    clean = all(r.get('ok') and r.get('rolled_back') and not r.get('header_diff')
                and not r.get('line_diff') and r.get('serials_ok') for r in report.values())
    return Response({'clean': clean, 'legs': _json_safe(report)})


@api_view(['POST'])
@permission_classes([CanManageCoupons])
def batch_push(request, pk):
    """Stock the batch in SOFTECH (two purchase documents, points leg first) via
    coupon_push.push_batch → invoices.writer. Idempotent: a finalized leg is skipped and the
    writer's own duplicate guard refuses a second document with the same supplier number."""
    from apps.invoices import writer
    from .coupon_push import push_batch
    batch = _batch(pk)
    if not batch:
        return Response({'detail': 'الدفعة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
    if batch.status != 'generated':
        return Response({'detail': 'الدفعة ليست بانتظار الإدخال'}, status=status.HTTP_400_BAD_REQUEST)
    if str(request.data.get('confirm', '')).lower() not in ('1', 'true', 'yes'):
        return Response({'detail': 'أكّد الإدخال في SOFTECH أولاً'}, status=status.HTTP_400_BAD_REQUEST)
    if not writer.writer_enabled():
        return Response({'detail': 'الإدخال في SOFTECH مغلق (INVOICE_WRITER_ENABLED=False) — لم يُكتب شيء.'},
                        status=status.HTTP_409_CONFLICT)
    force = str(request.data.get('force', '')).lower() in ('1', 'true', 'yes')
    with dash.pg_lock(dash.LOCK_PUSH * 1000 + batch.pk) as got:
        if not got:
            return Response({'detail': 'هذه الدفعة قيد الإدخال الآن — انتظر حتى تنتهي.'},
                            status=status.HTTP_409_CONFLICT)
        before = {'status': batch.status}
        try:
            results = push_batch(batch, commit=True, force=force)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception('[coupons] push batch %s failed', batch.pk)
            _audit(request, 'coupon_batch_stocked', batch, note=f'FAILED: {e}'[:255])
            return Response({'detail': f'فشل الإدخال: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)
    batch = _batch(pk)
    legs = {leg: {k: r.get(k) for k in ('mode', 'wrote_to_softech', 'docnumber', 'already_finalized',
                                        'ok', 'blocked', 'error')}
            for leg, r in results.items()}
    _audit(request, 'coupon_batch_stocked', batch,
           note=f'{batch.serial_from}–{batch.serial_to} → {batch.status}',
           extra={'before': before, 'after': {'status': batch.status}, 'force': force,
                  'legs': _json_safe(legs)})
    return Response({'batch': dash.batch_dict(batch), 'legs': _json_safe(results)})


@api_view(['GET'])
@permission_classes([CanManageCoupons])
def batch_verify(request, pk):
    from .coupon_push import verify_batch
    batch = _batch(pk)
    if not batch:
        return Response({'detail': 'الدفعة غير موجودة'}, status=status.HTTP_404_NOT_FOUND)
    try:
        return Response(_json_safe(verify_batch(batch)))
    except Exception as e:
        return Response({'detail': f'تعذّر التحقق من SOFTECH: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(['POST'])
@permission_classes([CanManageCoupons])
def sync_now(request):
    """Incremental read-only mirror of coupon movements (same as the daily job)."""
    try:
        res = dash.locked_sync()
    except Exception as e:
        return Response({'detail': f'فشل التحديث من SOFTECH: {public_error(request, e)}'}, status=status.HTTP_502_BAD_GATEWAY)
    if res is None:
        return Response({'detail': 'التحديث يعمل الآن — حاول بعد قليل.'}, status=status.HTTP_409_CONFLICT)
    return Response(res)
