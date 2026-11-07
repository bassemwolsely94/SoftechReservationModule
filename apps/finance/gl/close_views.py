"""Close and reconcile REST API (finance-gl Plan 3, Task 10) — /api/finance/gl/.

Same gate as views.py: authenticated, RBAC module `ledger`, all-branch users only; writes need a staff profile. The
services own the rules, this module parses input and shapes output. A CloseError or LedgerError leaves as
{code, detail}: 409 for a state conflict, else 400. Two jobs read SOFTECH for minutes and run in a thread: the close
(step (a) runs on the request, so its refusals come back on the POST and the month is `closing` from the 202 on) and
the comparison refresh. Screens poll `periods/{id}/` and `compare/`, neither of which reads SOFTECH.
"""
import datetime
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from django.db import connections, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.finance.models import (FinancialPeriod, GLAccount, GLAccountGroup, GLComparisonLine, GLSoftechCheck,
                                 LedgerEntry, SourceException)
from apps.finance.recon_labels import branch_label
from core.errors import public_error
from core.permissions import deny_unless
from core.threads import start_thread
from core.upload_safety import max_import_rows, max_upload_bytes

from . import close, compare, corrections, exports, ledger, manual_import, plan2_adapter, softech_stock, subledgers, validation
from . import close_serializers as ser
from .periods import OPENING_DATE, month_period
from .views import (APPROVE, MAX_NOTES, MAX_SHORT, MAX_TEXT, VIEW, _bad, _date, _entries_qs, _entry_detail, _int, _j,
                    _ledger_error, _no_profile, _perms, _profile, _report, _text)

logger = logging.getLogger('elrezeiky.finance')

CREATE = _perms()                      # POST create
FINALIZE = _perms(post=('finalize',))
REFRESH = _perms(post=('view',))       # only reads SOFTECH and recomputes the comparison
EXPORT = _perms(post=('export',))

CONFLICT_CLOSE_CODES = {'not_open', 'close_running', 'superseded', 'next_not_open'}
STORES_SETTING = 'gl_closing_stock_stores'
MAX_STORE_CODE = 10   # ClosingStockStore.store_code
XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
NOT_FOUND = {'period': 'الشهر غير موجود', 'line': 'سطر المقارنة غير موجود', 'entry': 'القيد غير موجود',
             'exception': 'الاستثناء غير موجود', 'check': 'الفحص غير موجود', 'kind': 'الأستاذ المساعد غير معروف'}


# ── helpers ──────────────────────────────────────────────────────────────────

def _missing(what):
    return _bad('not_found', NOT_FOUND[what], status.HTTP_404_NOT_FOUND)


def _strict_id(value):
    """An id from a request body: an int or its digits, else ValueError."""
    pk = value if isinstance(value, int) and not isinstance(value, bool) else _int(value) if isinstance(value, str) else None
    if pk is None:
        raise ValueError('رقم غير صحيح')
    return pk


def _body(request) -> dict:
    """The request body, or {} when it is not a JSON object."""
    return request.data if hasattr(request.data, 'get') else {}


def _close_error(e: close.CloseError):
    http = status.HTTP_409_CONFLICT if e.code in CONFLICT_CLOSE_CODES else status.HTTP_400_BAD_REQUEST
    return Response(_j({'code': e.code, 'detail': e.message, 'items': e.items, 'extra': e.detail}), status=http)


def _softech_down(request, exc):
    return _bad('softech_unavailable', public_error(request, exc), status.HTTP_503_SERVICE_UNAVAILABLE)


def _period(pk):
    return (FinancialPeriod.objects.select_related('closed_by__user', 'closing_stock')
            .filter(pk=pk, period_type='month').first())


def _background(fn, *args, **kwargs):
    """A thread's body: its own database connection goes with it."""
    try:
        fn(*args, **kwargs)
    finally:
        connections.close_all()


# ── periods and close ────────────────────────────────────────────────────────

def _months(year: int):
    """The year's month rows from the opening month on. Months up to today get their row (a screen acts on its id);
    a future month is listed only if something already created it."""
    today = timezone.localdate()
    if OPENING_DATE.year <= year <= today.year:
        have = set(FinancialPeriod.objects.filter(year=year, period_type='month').values_list('month', flat=True))
        for month in range(1, (today.month if year == today.year else 12) + 1):
            if month not in have:
                month_period(datetime.date(year, month, 1))
    return (FinancialPeriod.objects.select_related('closed_by__user', 'closing_stock')
            .filter(year=year, period_type='month', period_start__gte=OPENING_DATE).order_by('month'))


@api_view(['GET'])
@permission_classes(VIEW)
def periods(request):
    raw = request.query_params.get('year')
    year = _int(raw) if raw else timezone.localdate().year
    if year is None or not 2000 <= year <= 2100:
        return _bad('bad_input', 'السنة غير صحيحة')
    info = ser.reopen_info()
    return Response([ser.period_json(p, info) for p in _months(year)])


@api_view(['GET'])
@permission_classes(VIEW)
def period_detail(request, pk):
    period = _period(pk)
    if period is None:
        return _missing('period')
    return Response(ser.period_detail_json(period))


@api_view(['GET'])
@permission_classes(VIEW)
def period_checklist(request, pk):
    period = _period(pk)
    if period is None:
        return _missing('period')
    items = close.checklist(period)
    return Response({'period': ser.period_json(period), 'items': _j(items),
                     'can_close': period.status == 'open' and not close._blocked(items)})


def _run_close(period, token, profile):
    """run_close has already put a failure on the record (audit row, month back to open)."""
    try:
        close.run_close(period, token, user=profile)
    except (close.CloseError, ledger.LedgerError) as exc:
        logger.warning('[GLClose] close of %s refused: %s', period, exc.code)
    except Exception:
        logger.exception('[GLClose] close of %s failed', period)


@api_view(['POST'])
@permission_classes(FINALIZE)
def period_close(request, pk):
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    if _period(pk) is None:
        return _missing('period')
    try:
        period, token = close.begin_close(pk, user=profile)
    except close.CloseError as e:
        return _close_error(e)
    try:
        start_thread(_background, args=(_run_close, period, token, profile), name=f'gl-close-{pk}')
    except Exception as exc:   # no thread will ever finish this run: the month must not wait for the takeover
        close._close_failed(pk, exc, profile, token)
        raise
    return Response(ser.period_detail_json(_period(pk)), status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes(FINALIZE)
def period_reopen(request, pk):
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    if _period(pk) is None:
        return _missing('period')
    try:
        reason = _text(_body(request).get('reason'), MAX_TEXT, 'سبب إعادة الفتح')
    except ValueError as e:
        return _bad('bad_input', str(e))
    try:
        months = close.reopen_month(pk, user=profile, reason=reason)
    except close.CloseError as e:
        return _close_error(e)
    except ledger.LedgerError as e:
        return _ledger_error(e)
    info = ser.reopen_info()
    return Response({'months': [ser.period_json(_period(m.pk), info) for m in months]})


@api_view(['GET'])
@permission_classes(VIEW)
def period_closing_stock(request, pk):
    period = _period(pk)
    if period is None:
        return _missing('period')
    if request.query_params.get('preview') == '1':
        try:
            return Response(ser.valuation_json(softech_stock.valuation(period.period_end)))
        except softech_stock.BadStockRow as e:
            return _bad(e.code, str(e), status.HTTP_409_CONFLICT)
        except Exception as exc:
            return _softech_down(request, exc)
    snapshot = period.closing_stock
    if snapshot is None:
        return Response({'snapshot': None, 'stores': []})
    return Response({'snapshot': ser.snapshot_json(snapshot),
                     'stores': [ser.store_json(s) for s in snapshot.stores.select_related('branch')]})


# ── comparison ───────────────────────────────────────────────────────────────

def _compare_lines(period, check_key):
    # a check with nothing on either side leaves a zero line on the no-branch key, only so "computed" shows
    placeholder = Q(branch__isnull=True, party_code='', ledger_amount=0, softech_amount=0, explanation='')
    qs = (GLComparisonLine.objects.filter(period=period, softech_check__is_active=True).exclude(placeholder)
          .select_related('softech_check', 'branch', 'explained_by__user'))
    return qs.filter(softech_check__key=check_key) if check_key else qs


def _party_names(lines) -> dict:
    # per_party today means the supplier balance check; codes are only unique per party type
    return plan2_adapter.party_names({ln.party_code for ln in lines if ln.party_code}, 'supplier')


@api_view(['GET'])
@permission_classes(VIEW)
def compare_list(request):
    pk = _int(request.query_params.get('period'))
    if pk is None:
        return _bad('bad_input', 'اختر الشهر')
    period = _period(pk)
    if period is None:
        return _missing('period')
    lines = list(_compare_lines(period, (request.query_params.get('check') or '').strip()))
    names = _party_names(lines)
    return Response({'period': ser.period_json(period), 'stale': compare.is_stale(period),
                     'refresh': ser.refresh_state_json(period, compare.refresh_running()),
                     'lines': [ser.line_json(ln, names) for ln in lines]})


def _run_refresh(period, check_keys, profile):
    code = ''
    try:
        compare.refresh(period, check_keys=check_keys, user=profile)
    except compare.RefreshBusy:   # lost the race after the view's check: the screen hears it from the last run
        code = 'compare_running'
    except Exception:
        logger.exception('[GLCompare] refresh of %s failed', period)
        code = 'softech_unavailable'
    if code:
        ledger._audit(ser.REFRESH_FAILED, user=profile, obj=period, extra={'code': code, 'checks': check_keys})


@api_view(['POST'])
@permission_classes(REFRESH)
def compare_refresh(request):
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    data = _body(request)
    try:
        pk = _strict_id(data.get('period'))
    except ValueError:
        return _bad('bad_input', 'اختر الشهر')
    period = _period(pk)
    if period is None:
        return _missing('period')
    checks = data.get('checks')
    if checks is not None:
        if not isinstance(checks, list) or not all(isinstance(c, str) for c in checks):
            return _bad('bad_input', 'قائمة الفحوصات غير صحيحة')
        known = set(GLSoftechCheck.objects.filter(is_active=True, key__in=checks).values_list('key', flat=True))
        if set(checks) - known:
            return _bad('bad_input', 'فحص غير معروف أو موقوف')
    if period.status == 'closing':   # its checklist is reading these very lines
        return _ledger_error(ledger.LedgerError('period_closing'))
    if compare.refresh_running():
        return _bad('compare_running', 'فيه تحديث للمقارنة شغال، استنى لما يخلص.', status.HTTP_409_CONFLICT)
    start_thread(_background, args=(_run_refresh, period, checks or None, profile), name=f'gl-compare-{pk}')
    return Response(status=status.HTTP_202_ACCEPTED)


def _line(pk):
    return (GLComparisonLine.objects.select_related('softech_check', 'branch', 'explained_by__user')
            .filter(pk=pk).first())


@api_view(['GET'])
@permission_classes(VIEW)
def compare_line(request, pk):
    line = _line(pk)
    if line is None:
        return _missing('line')
    return Response(_j({**compare.detail(pk), 'line': ser.line_json(line, _party_names([line]))}))


@api_view(['POST'])
@permission_classes(APPROVE)
def compare_explain(request, pk):
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    try:
        text = _text(_body(request).get('text'), MAX_NOTES, 'التفسير')
    except ValueError as e:
        return _bad('bad_input', str(e))
    try:
        compare.explain(pk, user=profile, text=text)
    except GLComparisonLine.DoesNotExist:
        return _missing('line')
    except ledger.LedgerError as e:
        return _ledger_error(e)
    line = _line(pk)
    return Response(ser.line_json(line, _party_names([line])))


def _tolerance(value) -> Decimal:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('التسامح غير صحيح')
    if not d.is_finite() or d < 0 or d >= Decimal('1e16') or d != d.quantize(Decimal('0.01')):
        raise ValueError('التسامح غير صحيح: رقم موجب بحد أقصى رقمين عشريين')
    return d.quantize(Decimal('0.01'))


def _string_list(value, name) -> list:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValueError(f'{name}: قائمة غير صحيحة')
    return list(dict.fromkeys(v.strip() for v in value))


def _apply_check_patch(check, data):
    """Set the editable fields, or ValueError with an Arabic message. Two lists, both checked against what exists: a
    code or group that matches nothing would silently compare SOFTECH against zero."""
    if 'tolerance' in data:
        check.tolerance = _tolerance(data['tolerance'])
    if 'account_codes' in data:
        check.account_codes = _string_list(data['account_codes'], 'الحسابات')
        known = set(GLAccount.objects.filter(code__in=check.account_codes).values_list('code', flat=True))
        if set(check.account_codes) - known:
            raise ValueError('حساب غير موجود في الدليل')
    if 'group_names' in data:
        check.group_names = _string_list(data['group_names'], 'المجموعات')
        known = set(GLAccountGroup.objects.filter(name__in=check.group_names).values_list('name', flat=True))
        if set(check.group_names) - known:
            raise ValueError('مجموعة غير موجودة')
    if not check.account_codes and not check.group_names:
        raise ValueError('الفحص لازم يكون عليه حساب أو مجموعة')
    for flag in ('blocks_close', 'is_active'):
        if flag in data:
            if not isinstance(data[flag], bool):
                raise ValueError('القيمة لازم تكون نعم أو لا')
            setattr(check, flag, data[flag])


@api_view(['GET', 'PATCH'])
@permission_classes(VIEW)
def compare_checks(request):
    if request.method == 'GET':
        return Response([ser.check_json(c) for c in GLSoftechCheck.objects.all()])
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    data = _body(request)
    with transaction.atomic():
        check = GLSoftechCheck.objects.select_for_update().filter(key=str(data.get('key') or '')).first()
        if check is None:
            return _missing('check')
        before = ser.check_json(check)
        try:
            _apply_check_patch(check, data)
        except ValueError as e:
            return _bad('bad_input', str(e))
        after = ser.check_json(check)
        if after != before:
            check.save()
            # these move the figures; a tolerance is read live and moves none
            moved = any(after[f] != before[f] for f in ('account_codes', 'group_names', 'is_active'))
            ledger._audit(compare.CHECK_UPDATED, user=profile, obj=check, old_data=before, new_data=after,
                          extra={'figures_changed': moved})
    return Response(after)


# ── sub-ledgers ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(VIEW)
def subledger(request, kind):
    if kind not in subledgers.SUBLEDGERS:
        return _missing('kind')

    def build():
        f = _date(request.query_params.get('from'), 'من')
        t = _date(request.query_params.get('to'), 'إلى')
        if f > t:
            raise ValueError('تاريخ البداية بعد تاريخ النهاية')
        return {'from': f, 'to': t, **subledgers.subledger(kind, f, t)}
    return _report(request, build, exports.subledger)


@api_view(['GET'])
@permission_classes(VIEW)
def suppliers_vs_ap(request):
    def build():
        as_of = _date(request.query_params.get('as_of'), 'التاريخ')
        return {'as_of': as_of, 'rows': subledgers.supplier_vs_ap(as_of)}
    return _report(request, build, exports.supplier_vs_ap)


# ── corrections ──────────────────────────────────────────────────────────────

def _reason(data) -> str:
    reason = _text(data.get('reason'), MAX_TEXT, 'السبب').strip()
    if not reason:
        raise ValueError('السبب مطلوب')
    return reason


def _correction_lines(raw) -> list:
    if not isinstance(raw, list) or not raw:
        raise ValueError('الأسطر غير صحيحة')
    out = []
    for i, ln in enumerate(raw, start=1):
        if not isinstance(ln, dict):
            raise ValueError(f'السطر {i} غير صحيح')
        out.append({'account_code': str(ln.get('account_code') or '').strip(),
                    'debit': ln.get('debit'), 'credit': ln.get('credit'), 'branch_id': ln.get('branch_id') or None,
                    'party_code': _text(ln.get('party_code'), MAX_SHORT, f'كود طرف السطر {i}')})
    return out


def _posted(entry):
    return Response(_entry_detail(_entries_qs().get(pk=entry.pk)), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes(CREATE)
def corrections_create(request):
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    data = _body(request)
    try:
        original_id = _strict_id(data.get('original_id'))
        exception_id = None if data.get('exception_id') in (None, '') else _strict_id(data.get('exception_id'))
        reason = _reason(data)
        lines = _correction_lines(data.get('lines'))
    except ValueError as e:
        return _bad('bad_input', str(e))
    try:
        entry = corrections.post_late_correction(original_id, lines, user=profile, reason=reason,
                                                 exception_id=exception_id)
    except LedgerEntry.DoesNotExist:
        return _missing('entry')
    except SourceException.DoesNotExist:
        return _missing('exception')
    except ledger.LedgerError as e:
        return _ledger_error(e)
    return _posted(entry)


@api_view(['POST'])
@permission_classes(CREATE)
def corrections_from_exception(request):
    """One call per exception = per group (ruling P19). The services check the exception's state under its lock."""
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    data = _body(request)
    try:
        exception_id = _strict_id(data.get('exception_id'))
        reason = _reason(data)
    except ValueError as e:
        return _bad('bad_input', str(e))
    try:
        entry = corrections.post_from_exception(exception_id, user=profile, reason=reason)
    except SourceException.DoesNotExist:
        return _missing('exception')
    except ledger.LedgerError as e:
        return _ledger_error(e)
    return _posted(entry)


# ── cutover: manual import and validation ────────────────────────────────────

def _upload_refusal(request):
    """The upload's refusal Response, or None. `.xlsx` only, within the size limit."""
    f = request.FILES.get('file')
    if f is None:
        return _bad('no_file', 'اختر ملف Excel')
    if os.path.splitext(f.name or '')[1].lower() != '.xlsx':
        return _bad('bad_file', 'الملف لازم يكون Excel (.xlsx)')
    if f.size and f.size > max_upload_bytes():
        return _bad('bad_file', 'الملف أكبر من المسموح')
    return None


@contextmanager
def _saved_upload(f):
    """The upload on disk under its own name (Django keeps only the base name): the journal's book may be in the file
    name, and the import's audit row records it. Gone on exit."""
    with tempfile.TemporaryDirectory(prefix='gl_upload_') as folder:
        path = os.path.join(folder, os.path.basename(f.name))
        with open(path, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        yield path


def _parse_refusal(e: manual_import.ParseError):
    if e.code == 'too_many_rows':
        return _bad(e.code, f'الملف أكبر من حد الشاشة ({max_import_rows()} صف) — استوردْه من السيرفر '
                            'بأمر import_gl_manual_entries.')
    return _bad(e.code, e.message)


def _include_mixed(request) -> list:
    """Multipart: repeated fields, or one field holding a JSON list."""
    raw = request.data.getlist('include_mixed') if hasattr(request.data, 'getlist') else []
    if not all(isinstance(k, str) for k in raw):   # sent as a file
        raise ValueError('قائمة المجموعات غير صحيحة')
    if len(raw) == 1 and raw[0].lstrip()[:1] in ('[', '{'):
        try:
            raw = json.loads(raw[0])
        except ValueError:
            raise ValueError('قائمة المجموعات غير صحيحة')
    if not isinstance(raw, list) or not all(isinstance(k, str) for k in raw):
        raise ValueError('قائمة المجموعات غير صحيحة')
    return raw


def _journal(request, run):
    """Run `run(path, sheet_name=, book=, max_rows=)` on the uploaded journal, JSON-safe."""
    refused = _upload_refusal(request)
    if refused:
        return refused
    try:
        with _saved_upload(request.FILES['file']) as path:
            return Response(_j(run(path, sheet_name=request.data.get('sheet') or None,
                                   book=request.data.get('book') or None, max_rows=max_import_rows())))
    except manual_import.ParseError as e:
        return _parse_refusal(e)


@api_view(['POST'])
@permission_classes(CREATE)
@parser_classes([MultiPartParser, FormParser])
def manual_import_preview(request):
    return _journal(request, manual_import.preview)


@api_view(['POST'])
@permission_classes(CREATE)
@parser_classes([MultiPartParser, FormParser])
def manual_import_run(request):
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    try:
        include = _include_mixed(request)
    except ValueError as e:
        return _bad('bad_input', str(e))

    def run(path, **kw):
        return manual_import.import_entries(path, user=profile, include_mixed=include, **kw)
    return _journal(request, run)


@api_view(['POST'])
@permission_classes(EXPORT)
@parser_classes([MultiPartParser, FormParser])
def validation_report(request):
    denied = deny_unless(request, 'ledger', 'view')   # reads the ledger and hands it back as a file: view + export
    if denied:
        return denied
    refused = _upload_refusal(request)
    if refused:
        return refused
    try:
        through = _date(request.data.get('through'), 'حتى تاريخ', required=False) or validation.DEFAULT_THROUGH
    except ValueError as e:
        return _bad('bad_input', str(e))
    if through < validation.START:
        return _bad('bad_input', f'التاريخ قبل {validation.START.isoformat()}')
    try:
        with _saved_upload(request.FILES['file']) as path:
            result = validation.validate(path, through=through, max_rows=max_import_rows())
    except validation.WorkbookError as e:
        return _bad(e.code, e.message)
    resp = HttpResponse(validation.export_validation(result), content_type=XLSX_CONTENT_TYPE)
    resp['Content-Disposition'] = f'attachment; filename="gl_validation_{through.isoformat()}.xlsx"'
    resp['X-GL-Validation-Differences'] = str(result['totals']['differences'])
    resp['X-GL-Validation-Difference-Total'] = str(result['totals']['difference_total'])
    resp['Access-Control-Expose-Headers'] = 'X-GL-Validation-Differences, X-GL-Validation-Difference-Total'
    return resp


# ── closing-stock store map ──────────────────────────────────────────────────

def _store_rows() -> list:
    overrides = softech_stock._setting_overrides()
    return [{'store_code': code, 'branch_code': rule.branch_code, 'branch_label': branch_label(rule.branch_code),
             'included': rule.included, 'overridden': code in overrides, 'override': overrides.get(code)}
            for code, rule in softech_stock.store_map().items()]


def _clean_store_patch(stores) -> dict:
    """{store: entry | None}, stricter than the reader only where it would fail later: a null value inside an entry,
    a branch we don't have (the close would stop on `unknown_branch`), a code too long for the snapshot."""
    if not isinstance(stores, dict) or not stores:
        raise ValueError('حدد مخزن واحد على الأقل')
    branches = set(Branch.objects.values_list('softech_branch_id', flat=True))
    out = {}
    for store, entry in stores.items():
        code = store.strip() if isinstance(store, str) else ''
        if not code or len(code) > MAX_STORE_CODE:
            raise ValueError('كود المخزن غير صحيح')
        if entry is None:
            out[code] = None
            continue
        if not softech_stock.valid_store_entry(code, entry) or any(v is None for v in entry.values()):
            raise ValueError(f'إعداد المخزن {code} غير صحيح')
        entry = {k: (v.strip() if isinstance(v, str) else v) for k, v in entry.items()}
        if 'branch' in entry and entry['branch'] not in branches:
            raise ValueError(f'فرع المخزن {code} غير موجود')
        out[code] = entry
    return out


@api_view(['GET', 'PATCH'])
@permission_classes(VIEW)
def closing_stock_stores(request):
    """PATCH {stores: {code: {branch?, included?} | null}}: per store, null back to the default; others untouched."""
    if request.method == 'GET':
        return Response(_store_rows())
    profile = _profile(request)
    if profile is None:
        return _no_profile()
    try:
        patch = _clean_store_patch(_body(request).get('stores'))
    except ValueError as e:
        return _bad('bad_input', str(e))
    with transaction.atomic():
        row, _ = SystemSetting.objects.select_for_update().get_or_create(key=STORES_SETTING, defaults={
            'label': 'مخازن بضاعة آخر المدة', 'value': '{}', 'value_type': 'json',
            'description': 'لكل مخزن: الفرع وهل يدخل في بضاعة آخر المدة (الإقفال الشهري)'})
        before = softech_stock._setting_overrides()
        after = {**before, **patch}
        after = {code: entry for code, entry in sorted(after.items()) if entry is not None}
        row.value = json.dumps(after, ensure_ascii=False)
        row.value_type = 'json'
        row.save(update_fields=['value', 'value_type', 'updated_at'])
        ledger._audit('gl_closing_stock_stores_updated', user=profile, obj=row, old_data={'stores': before},
                      new_data={'stores': after})
    return Response(_store_rows())
