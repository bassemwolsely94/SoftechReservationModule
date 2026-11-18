"""/api/rpa/portal/ — the staff side of the supplier-portal robot (the /rpa/portals screen).

Thin views: the portal services (buylist, jobs, skus, queue) own every rule — rounding, the open-list
guard, the four-eyes limit, the ready rule, retry / link / cancel and the placed-order guard. These
views authenticate, check the module grant, parse the request and shape the answer.

Access:
  • module `rpa` on every view (GET view · POST create; settling a basket and confirming a
    discovered code need `edit`, as the services do; the middleware asks the same, module_access);
  • portal data is COMPANY level (ordered for HQ, apps/rpa/portal/jobs.py): only people who see
    every branch (core.branch_scope.sees_everything) read or act on it — the rpa holders are all
    all-branch roles (seed_permissions.RPA_GRANTS), a branch-scoped person gets 403;
  • a buyer sees their own jobs and baskets; holders of rpa approve (and the admin) see all;
  • portal settings and accounts (the live switch) are the admin's only, audited. An account has
    no secret field: a password / cookie / token in the request is refused, never stored.
Nothing here writes SOFTECH.
"""
import io
import logging
import re

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.rpa.models import (BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob, SupplierPortal)
from config.writers import writer_allowed
from core import branch_scope
from core.errors import public_error
from core.permissions import IsAdminRole, matrix_permission
from core.upload_safety import max_upload_bytes, sha256_of

from . import buylist as bl_service
from . import jobs as job_service
from . import queue, serializers as ser, skus
from .recording import RecordError

logger = logging.getLogger(__name__)

RPA = matrix_permission('rpa')                       # GET view · POST create
RPA_EDIT = matrix_permission('rpa', post=('edit',))  # settle a basket, confirm a discovered code
SECRET_FIELDS = ('password', 'passwd', 'secret', 'cookie', 'cookies', 'token', 'session', 'otp')
ACCOUNT_FIELDS = ('label', 'identity_text', 'active', 'paper_branch')
PORTAL_FIELDS = ('enabled', 'live', 'basket_size')


class CompanyLevel(BasePermission):
    """Portal jobs are company level (HQ purchasing): only a person who sees every branch."""
    message = 'بيانات مواقع الموردين على مستوى الشركة — متاحة لمن يرى كل الفروع فقط.'

    def has_permission(self, request, view):
        return branch_scope.sees_everything(request.user)


STAFF = [IsAuthenticated, RPA, CompanyLevel]
STAFF_EDIT = [IsAuthenticated, RPA_EDIT, CompanyLevel]
ADMIN = [IsAuthenticated, IsAdminRole]


# ── helpers ───────────────────────────────────────────────────────────────────────────────────

def _profile(request):
    return request.user.staff_profile


def _body(request):
    data = request.data
    if not hasattr(data, 'get'):
        raise ValidationError({'detail': 'صيغة الطلب غير صحيحة.'})
    return data


def _int(data, key):
    try:
        return int(data.get(key))
    except (TypeError, ValueError):
        raise ValidationError({key: 'رقم غير صالح.'})


def _text(data, key, *, limit=255):
    value = data.get(key, '')
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise ValidationError({key: 'القيمة يجب أن تكون نصاً.'})
    return value.strip()[:limit]


def _refuse_secrets(data):
    bad = sorted(k for k in data if str(k).lower() in SECRET_FIELDS)
    if bad:
        raise ValidationError({'detail': 'لا يُحفظ أي كلمة سر أو كوكي أو رمز دخول للموقع — سجّل الدخول بنفسك على جهازك.'})


def _service_call(fn, *args, **kwargs):
    """Run a service; its own Arabic refusals become 400 (409 for a placed-order cancel), a
    permission refusal 403. Anything else is a real fault and surfaces as a 500."""
    try:
        return fn(*args, **kwargs)
    except queue.PlacedOrderCancel as exc:
        return Response({'detail': str(exc), 'needs': ['confirm_placed_order_cancel', 'reason']},
                        status=status.HTTP_409_CONFLICT)
    except (bl_service.BuyListError, job_service.JobError, skus.DiscoveryError, skus.PortalSetupError,
            queue.QueueError, RecordError) as exc:
        raise ValidationError({'detail': str(exc)})
    except DjangoPermissionDenied as exc:
        raise PermissionDenied(str(exc) or 'ليس لديك صلاحية لهذا الإجراء')


def _sees_all_jobs(profile):
    return profile.is_admin or profile.can_do('rpa', 'approve')


def _jobs_for(request):
    profile = _profile(request)
    qs = PortalJob.objects.select_related('portal', 'account', 'created_by__user', 'approved_by__user')
    return qs if _sees_all_jobs(profile) else qs.filter(created_by=profile)


def _job_or_404(request, pk):
    return get_object_or_404(_jobs_for(request), pk=pk)


def _baskets_for(request):
    return PortalBasket.objects.filter(job__in=_jobs_for(request)).select_related('job__portal', 'job__account')


def _basket_or_404(request, pk):
    return get_object_or_404(_baskets_for(request), pk=pk)


def _ranking(item_ids):
    """Suppliers best first per item (the comparison board). A board failure is not fatal: the
    buyer still sees and picks the lines, only without the ranking."""
    try:
        return bl_service.rank_suppliers(item_ids)
    except Exception as exc:                     # noqa: BLE001 - display aid only
        logger.warning('portal buy list: supplier ranking failed (%s)', type(exc).__name__)
        return {}


def _suppliers(codes):
    """{code: {'name', 'portal'}} for the codes on screen (portal = the robot's portal key)."""
    from apps.invoices.models import VendorProfile
    codes = {str(c) for c in codes if c}
    names = dict(VendorProfile.objects.filter(softech_personcode__in=codes)
                 .values_list('softech_personcode', 'name'))
    portals = dict(SupplierPortal.objects.filter(supplier_code__in=codes).values_list('supplier_code', 'key'))
    return {c: {'name': names.get(c, ''), 'portal': portals.get(c, '')} for c in sorted(codes)}


# ── portals + accounts ────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def portal_list(request):
    return Response({
        'switch_on': writer_allowed(queue.FLAG),
        'portals': ser.PortalSerializer(SupplierPortal.objects.order_by('key'), many=True).data,
    })


@api_view(['PATCH'])
@permission_classes(ADMIN)
def portal_edit(request, key):
    """Admin: enabled / live / basket_size. `live` is switched only here, audited."""
    portal = get_object_or_404(SupplierPortal, key=key)
    data = _body(request)
    _refuse_secrets(data)
    unknown = sorted(set(data) - set(PORTAL_FIELDS))
    if unknown:
        raise ValidationError({'detail': f'حقول غير مسموحة: {", ".join(unknown)}'})
    old = {f: getattr(portal, f) for f in PORTAL_FIELDS}
    for f in ('enabled', 'live'):
        if f in data:
            if not isinstance(data[f], bool):
                raise ValidationError({f: 'القيمة يجب أن تكون true أو false.'})
            setattr(portal, f, data[f])
    if 'basket_size' in data:
        size = _int(data, 'basket_size')
        if not 1 <= size <= 50:
            raise ValidationError({'basket_size': 'حجم السلة من 1 إلى 50.'})
        portal.basket_size = size
    new = {f: getattr(portal, f) for f in PORTAL_FIELDS}
    if new != old:
        portal.save(update_fields=list(PORTAL_FIELDS))
        AuditLog.log('rpa_portal_changed', user=_profile(request), obj=portal, old_data=old, new_data=new,
                     note=f'{portal.key}: ' + ', '.join(f'{k} {old[k]}→{new[k]}' for k in PORTAL_FIELDS
                                                       if old[k] != new[k]))
    return Response(ser.PortalSerializer(portal).data)


def _accounts():
    return PortalAccount.objects.select_related('portal', 'paper_branch').order_by('portal__key', 'label', 'pk')


def _account_values(data, account):
    from apps.branches.models import Branch
    _refuse_secrets(data)
    unknown = sorted(set(data) - set(ACCOUNT_FIELDS) - {'portal'})
    if unknown:
        raise ValidationError({'detail': f'حقول غير مسموحة: {", ".join(unknown)}'})
    if 'label' in data:
        account.label = _text(data, 'label', limit=120)
        if not account.label:
            raise ValidationError({'label': 'اكتب اسم الحساب.'})
    if 'identity_text' in data:
        account.identity_text = _text(data, 'identity_text')
    if 'active' in data:
        if not isinstance(data['active'], bool):
            raise ValidationError({'active': 'القيمة يجب أن تكون true أو false.'})
        account.active = data['active']
    if 'paper_branch' in data:
        value = data.get('paper_branch')
        if value in (None, ''):
            account.paper_branch = None
        else:
            account.paper_branch = Branch.objects.filter(pk=value).first() if str(value).isdigit() else None
            if account.paper_branch is None:
                raise ValidationError({'paper_branch': 'فرع غير صالح.'})


def _account_snapshot(a):
    return {'label': a.label, 'identity_text': a.identity_text, 'active': a.active,
            'paper_branch': a.paper_branch_id}


class AccountListView(APIView):
    """GET: rpa view (the buyer picks the account and sees its last credit). POST: admin."""

    def get_permissions(self):
        if self.request.method == 'POST':
            return [p() for p in ADMIN]
        return [p() for p in STAFF]

    def get(self, request):
        return Response(ser.AccountSerializer(_accounts(), many=True).data)

    def post(self, request):
        data = _body(request)
        _refuse_secrets(data)
        portal = get_object_or_404(SupplierPortal, key=_text(data, 'portal', limit=30))
        account = PortalAccount(portal=portal)
        _account_values(data, account)
        if not account.label:
            raise ValidationError({'label': 'اكتب اسم الحساب.'})
        account.save()
        AuditLog.log('rpa_portal_account_changed', user=_profile(request), obj=account, old_data={},
                     new_data=_account_snapshot(account), note=f'{portal.key}: حساب جديد {account.label}')
        return Response(ser.AccountSerializer(_accounts().get(pk=account.pk)).data, status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
@permission_classes(ADMIN)
def account_edit(request, pk):
    account = get_object_or_404(_accounts(), pk=pk)
    data = _body(request)
    old = _account_snapshot(account)
    _account_values(data, account)
    new = _account_snapshot(account)
    if new != old:
        account.save()
        AuditLog.log('rpa_portal_account_changed', user=_profile(request), obj=account, old_data=old,
                     new_data=new, note=f'{account.portal.key}: {account.label}')
    return Response(ser.AccountSerializer(_accounts().get(pk=account.pk)).data)


# ── buy lists ─────────────────────────────────────────────────────────────────────────────────

def _buylists():
    return (BuyList.objects.select_related('created_by__user')
            .annotate(line_count=Count('lines', distinct=True),
                      open_count=Count('lines', filter=Q(lines__remaining_qty__gt=0), distinct=True)))


def _created(request, lst):
    data = _buylist_detail(lst)
    data['errors'] = getattr(lst, 'errors', [])
    return Response(data, status=status.HTTP_201_CREATED)


def _buylist_detail(lst):
    lst = _buylists().get(pk=lst.pk)
    lines = list(lst.lines.select_related('item').order_by('seq', 'pk'))
    ranking = _ranking([ln.item_id for ln in lines])
    frozen = job_service.frozen_buyline_ids(lines)
    data = ser.BuyListSerializer(lst).data
    data['lines'] = [ser.buyline_row(ln, frozen=ln.pk in frozen, ranking=ranking.get(ln.item_id))
                     for ln in lines]
    codes = {ln.chosen_supplier for ln in lines} | {c for r in ranking.values() for c in r}
    data['suppliers'] = _suppliers(codes)
    data['jobs'] = ser.JobSerializer(lst.jobs.select_related('portal', 'account').order_by('-created_at'),
                                     many=True).data
    return data


@api_view(['GET'])
@permission_classes(STAFF)
def buylist_list(request):
    qs = _buylists()
    wanted = request.query_params.get('status')
    if wanted in ('open', 'closed'):
        qs = qs.filter(status=wanted)
    return Response(ser.BuyListSerializer(qs.order_by('-created_at', '-pk')[:200], many=True).data)


@api_view(['POST'])
@permission_classes(STAFF)
def buylist_from_pivot(request):
    from apps.purchasing.models import PivotSheetSnapshot
    data = _body(request)
    snap = get_object_or_404(PivotSheetSnapshot, pk=_int(data, 'snapshot_id'))
    codes = data.get('supplier_codes') or None
    if codes is not None and not isinstance(codes, list):
        raise ValidationError({'supplier_codes': 'قائمة أكواد موردين.'})
    lst = _service_call(bl_service.create_from_pivot, snap, staff=_profile(request), supplier_codes=codes)
    return _created(request, lst)


@api_view(['POST'])
@permission_classes(STAFF)
def buylist_from_isr(request):
    from apps.purchasing.models import IsrPush
    push = get_object_or_404(IsrPush, pk=_int(_body(request), 'push_id'))
    lst = _service_call(bl_service.create_from_isr, push, staff=_profile(request))
    return _created(request, lst)


@api_view(['POST'])
@permission_classes(STAFF)
@parser_classes([MultiPartParser, FormParser])
def buylist_upload(request):
    """An Excel / CSV with «كود الصنف» and «الكمية» columns (same reader as the /rpa upload)."""
    import csv
    import zipfile

    from openpyxl.utils.exceptions import InvalidFileException

    from apps.rpa.sheet import parse_issue_sheet
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'يجب إرفاق ملف.'})
    if upload.size > max_upload_bytes():
        raise ValidationError({'file': 'الملف أكبر من الحد المسموح.'})
    if not (upload.name or '').lower().endswith(('.xlsx', '.csv')):
        raise ValidationError({'file': 'نوع الملف غير مدعوم — Excel (.xlsx) أو CSV.'})
    digest = sha256_of(upload)
    try:
        parsed = parse_issue_sheet(upload.read(), upload.name or '')
    except (ValueError, InvalidFileException, zipfile.BadZipFile, csv.Error, KeyError, SyntaxError) as exc:
        if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) and any(
                '؀' <= ch <= 'ۿ' for ch in str(exc)):
            raise ValidationError({'detail': str(exc)})
        ref = re.search(r'مرجع:\s*(\w+)', public_error(request, exc))
        raise ValidationError({'detail': 'تعذّرت قراءة الملف؛ تأكد أنه Excel أو CSV بعمودي الكود والكمية.'
                                         + (f' (مرجع: {ref.group(1)})' if ref else '')})
    rows, errors = bl_service.rows_from_sheet(parsed)
    if not rows:
        raise ValidationError({'detail': 'لا توجد أسطر صالحة في الملف.', 'errors': errors})
    lst = _service_call(bl_service.create_from_rows, rows, staff=_profile(request), file_sha256=digest)
    lst.errors = errors + list(getattr(lst, 'errors', []))
    return _created(request, lst)


@api_view(['GET'])
@permission_classes(STAFF)
def buylist_detail(request, pk):
    return Response(_buylist_detail(get_object_or_404(BuyList, pk=pk)))


@api_view(['POST'])
@permission_classes(STAFF)
def buylist_pick(request, pk):
    data = _body(request)
    line = get_object_or_404(BuyListLine.objects.select_related('buylist', 'item'), pk=_int(data, 'line_id'),
                             buylist_id=pk)
    _service_call(bl_service.pick, line, _text(data, 'supplier', limit=120), staff=_profile(request))
    line.refresh_from_db()
    frozen = job_service.frozen_buyline_ids([line])
    return Response(ser.buyline_row(line, frozen=line.pk in frozen))


def _order_list_xlsx(order_ref, supplier_code):
    from openpyxl import Workbook

    from apps.supply.models import SupplyDecision
    from core.export_safety import neutralise_formulas
    wb = Workbook()
    ws = wb.active
    ws.title = 'طلبية'
    ws.sheet_view.rightToLeft = True
    ws.append(['طلبية مورد', supplier_code, order_ref])
    ws.append(['كود الصنف', 'اسم الصنف', 'الكمية'])
    for d in (SupplyDecision.objects.filter(order_ref=order_ref).select_related('item').order_by('pk')):
        ws.append([d.item.softech_id, d.item.name, float(d.decided_qty)])
    buf = io.BytesIO()
    neutralise_formulas(wb).save(buf)
    return buf.getvalue()


@api_view(['POST'])
@permission_classes(STAFF)
def buylist_send_other(request, pk):
    """A supplier without a portal: record the order list (supply decisions) and return the
    WhatsApp text, or the same list as Excel (?format=xlsx). A company-level HQ order list, not
    a per-branch report (so not in apps/tests/new_value_registry.py)."""
    lst = get_object_or_404(BuyList, pk=pk)
    data = _body(request)
    supplier = _text(data, 'supplier', limit=120)
    if not supplier:
        raise ValidationError({'supplier': 'اختر المورد.'})
    key = _text(data, 'idempotency_key', limit=120) or None
    res = _service_call(bl_service.send_other, lst, supplier, staff=_profile(request), idempotency_key=key)
    if isinstance(res, Response):
        return res
    if request.query_params.get('format') == 'xlsx':
        body = _order_list_xlsx(res['order_ref'], supplier)
        resp = HttpResponse(body, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        # the supplier code is typed by a person: only safe characters go into the header
        safe = re.sub(r'[^A-Za-z0-9_-]', '', supplier)[:40] or 'supplier'
        resp['Content-Disposition'] = f'attachment; filename="order-{safe}-{lst.pk}.xlsx"'
        return resp
    return Response(res)


# ── jobs ──────────────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes(STAFF)
def job_list(request):
    if request.method == 'GET':
        qs = _jobs_for(request).annotate(
            basket_count=Count('baskets', distinct=True),
            needs_person_count=Count('baskets', filter=queue.needs_person_q('baskets__'), distinct=True))
        wanted = request.query_params.get('status')
        if wanted:
            qs = qs.filter(status=wanted)
        buylist = request.query_params.get('buylist')
        if buylist and buylist.isdigit():
            qs = qs.filter(buylist_id=int(buylist))
        return Response(ser.JobSerializer(qs.order_by('-created_at', '-pk')[:200], many=True).data)
    data = _body(request)
    lst = get_object_or_404(BuyList, pk=_int(data, 'buylist_id'))
    portal = get_object_or_404(SupplierPortal, key=_text(data, 'portal', limit=30))
    account = get_object_or_404(PortalAccount, pk=_int(data, 'account_id'))
    job = _service_call(job_service.create_job, lst, portal=portal, account=account, staff=_profile(request))
    return Response(ser.job_detail(_job_or_404(request, job.pk)), status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes(STAFF)
def portal_job_detail(request, pk):
    return Response(ser.job_detail(_job_or_404(request, pk)))


@api_view(['POST'])
@permission_classes(STAFF)
def portal_job_approve(request, pk):
    """The service decides: the need check (an over-need line needs a reason) and four-eyes (above
    SystemSetting portal_four_eyes_above, a different person holding rpa approve)."""
    job = _job_or_404(request, pk)
    reasons = _body(request).get('reasons') or {}
    if not isinstance(reasons, dict):
        raise ValidationError({'reasons': 'الأسباب بصيغة {رقم السطر: السبب}.'})
    try:
        reasons = {int(k): str(v or '') for k, v in reasons.items()}
    except (TypeError, ValueError):
        raise ValidationError({'reasons': 'رقم سطر غير صالح.'})
    _service_call(job_service.approve_job, job, staff=_profile(request), reasons=reasons)
    return Response(ser.job_detail(_job_or_404(request, pk)))


@api_view(['POST'])
@permission_classes(STAFF)
def portal_job_cancel(request, pk):
    job = _job_or_404(request, pk)
    _service_call(job_service.cancel_job, job, staff=_profile(request), reason=_text(_body(request), 'reason'))
    return Response(ser.job_detail(_job_or_404(request, pk)))


# ── discovery ─────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def discovery_job(request, job_id):
    return Response(ser.discovery_detail(_job_or_404(request, job_id)))


@api_view(['POST'])
@permission_classes(STAFF_EDIT)
def discovery_confirm(request):
    from apps.supply.models import AvailabilityBatch, AvailabilityLine
    line = get_object_or_404(AvailabilityLine.objects.select_related('batch'),
                             pk=_int(_body(request), 'availability_line_id'),
                             batch__source=AvailabilityBatch.SOURCE_PORTAL)
    job = _job_or_404(request, (line.match_reason or {}).get('job_id') or 0)
    _service_call(skus.confirm_discovery, line, staff=_profile(request))
    return Response(ser.discovery_detail(job))


@api_view(['POST'])
@permission_classes(STAFF_EDIT)
def discovery_none(request):
    buyline = get_object_or_404(BuyListLine, pk=_int(_body(request), 'buyline_id'))
    job = (_jobs_for(request).filter(baskets__lines__buyline=buyline).order_by('-created_at').first())
    if job is None:
        from django.http import Http404
        raise Http404
    _service_call(skus.reject_discovery, buyline, staff=_profile(request))
    return Response(ser.discovery_detail(job))


# ── baskets ───────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def basket_list(request):
    qs = _baskets_for(request).annotate(line_count=Count('lines'))
    if request.query_params.get('needs_person') in ('1', 'true'):
        qs = qs.filter(queue.needs_person_q())
    job = request.query_params.get('job')
    if job and job.isdigit():
        qs = qs.filter(job_id=int(job))
    rows = []
    for b in qs.order_by('-job__created_at', 'job_id', 'seq')[:500]:
        row = ser.basket_row(b)
        row.update({'portal': b.job.portal.key, 'account_label': b.job.account.label, 'dry_run': b.job.dry_run})
        rows.append(row)
    return Response(rows)


@api_view(['GET'])
@permission_classes(STAFF)
def portal_basket_detail(request, pk):
    return Response(ser.basket_detail(_basket_or_404(request, pk)))


@api_view(['POST'])
@permission_classes(STAFF_EDIT)
def portal_basket_resolve(request, pk):
    """retry / link_order (order_ref + history lines, or the stored read) / cancel. The queue owns
    every rule; cancelling a basket whose order was placed answers 409 until it is confirmed."""
    basket = _basket_or_404(request, pk)
    data = _body(request)
    lines = data.get('history_lines')
    if lines is not None and not isinstance(lines, list):
        raise ValidationError({'history_lines': 'قائمة أسطر.'})
    res = _service_call(queue.resolve, basket, staff=_profile(request), action=_text(data, 'action', limit=20),
                        order_ref=_text(data, 'order_ref', limit=60), confirm_none=data.get('confirm_none') is True,
                        history_lines=lines,
                        confirm_placed_order_cancel=data.get('confirm_placed_order_cancel') is True,
                        reason=_text(data, 'reason'))
    if isinstance(res, Response):
        return res
    return Response(ser.basket_detail(_basket_or_404(request, pk)))


@api_view(['POST'])
@permission_classes(STAFF_EDIT)
def portal_basket_history_check(request, pk):
    """«افحص سجل الطلبات الآن»: queue an Order History read for a stuck basket (one at a time)."""
    basket = _basket_or_404(request, pk)
    run = _service_call(queue.request_history, basket)
    AuditLog.log('rpa_portal_needs_person', user=_profile(request), obj=basket,
                 new_data={'history_read_requested': run.pk},
                 note=f'basket {basket.pk}: Order History read requested at {timezone.now():%Y-%m-%d %H:%M}')
    return Response(ser.basket_detail(_basket_or_404(request, pk)))


# ── remainders ────────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(STAFF)
def remainder_list(request):
    lines = list(bl_service.remainders().order_by('buylist_id', 'seq'))
    ranking = _ranking([ln.item_id for ln in lines]) if lines else {}
    rows = ser.remainder_rows(lines, ranking)
    codes = {c for r in rows for c in r['ranking']} | {t.get('supplier') for r in rows for t in r['tried']}
    return Response({'rows': rows, 'suppliers': _suppliers(codes)})
