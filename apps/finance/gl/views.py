"""General-ledger REST API (finance-gl Task 8) — /api/finance/gl/.

Every view: authenticated, RBAC module `ledger`, and all-branch users only (security batch 5,
decision B-1: ledger data is company-level).  State changes go through gl/ledger.py; this module
only parses input and shapes output.  LedgerError → 400 {code, detail} (409 for not_draft /
already_reversed).  Decimals are serialised as strings.  `?format=xlsx` on a report needs
ledger.export and returns finance's Excel layout (gl/exports.py).
"""
import datetime
import os
import tempfile
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.catalog.wildcard import filter_and_rank
from apps.finance.models import GLAccount, GLAccountGroup, LedgerEntry, LedgerLine
from core.branch_scope import sees_everything
from core.permissions import deny_unless, matrix_permission

from . import balances, exports, ledger, statements
from .coa_import import import_coa, parse_trial_balance_sheet

CONFLICT_CODES = {'not_draft', 'already_reversed'}
MANUAL_BOOKS = ('general', 'cash', 'credit')
ACCOUNT_EDITABLE = ('name', 'statement_line', 'is_active', 'requires_branch', 'party_type')


class AllBranchOnly(BasePermission):
    message = 'دفتر الأستاذ متاح لمستخدمي كل الفروع فقط'

    def has_permission(self, request, view):
        return sees_everything(request.user)


def _perms(**kw):
    return [IsAuthenticated, AllBranchOnly, matrix_permission('ledger', **kw)]


VIEW = _perms()                                              # GET view
ENTRY = _perms(post=('create',), edit=('create',), delete=('create',))
APPROVE = _perms(post=('approve',))
EDIT = _perms(post=('edit',), edit=('edit',))


# ── helpers ──────────────────────────────────────────────────────────────────

def _j(v):
    """Decimals → strings, dates → ISO, recursively (JSON-safe, exact)."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _j(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_j(x) for x in v]
    return v


def _bad(code, detail, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': code, 'detail': detail}, status=http)


def _ledger_error(e: ledger.LedgerError):
    detail = e.message
    extra = e.detail or {}
    if extra.get('line_no'):
        detail = f'{detail} (السطر {extra["line_no"]})'
    http = status.HTTP_409_CONFLICT if e.code in CONFLICT_CODES else status.HTTP_400_BAD_REQUEST
    return Response({'code': e.code, 'detail': detail, 'extra': _j(extra)}, status=http)


def _date(value, name, required=True):
    if not value:
        if required:
            raise ValueError(f'{name}: التاريخ مطلوب')
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f'{name}: تاريخ غير صحيح')


def _int(value):
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _profile(request):
    return getattr(request.user, 'staff_profile', None)


def _branch_label(b):
    if b is None:
        return ''
    sid = (b.softech_branch_id or '').strip()
    return f'{sid} · {b.name}' if sid else b.name


def _wants_xlsx(request):
    return request.query_params.get('format') == 'xlsx'


# ── chart of accounts ────────────────────────────────────────────────────────

def _group(g):
    return {'id': g.id, 'name': g.name, 'section': g.section, 'order': g.order}


def _account(a):
    return {'code': a.code, 'name': a.name, 'group': _group(a.group), 'nature': a.nature,
            'account_type': a.account_type, 'statement_line': a.statement_line,
            'is_posting': a.is_posting, 'is_active': a.is_active, 'is_system': a.is_system,
            'requires_branch': a.requires_branch, 'requires_party': a.requires_party,
            'party_type': a.party_type}


@api_view(['GET'])
@permission_classes(VIEW)
def groups(request):
    return Response([_group(g) for g in GLAccountGroup.objects.all()])


@api_view(['GET'])
@permission_classes(VIEW)
def accounts(request):
    qs = GLAccount.objects.select_related('group').order_by('code')
    group = _int(request.query_params.get('group'))
    if group:
        qs = qs.filter(group_id=group)
    active = request.query_params.get('active')
    if active in ('true', 'false'):
        qs = qs.filter(is_active=(active == 'true'))
    q = (request.query_params.get('q') or '').strip()
    if q:
        qs = filter_and_rank(qs, q, ['code', 'name'])
    return Response([_account(a) for a in qs])


@api_view(['PATCH'])
@permission_classes(EDIT)
def account_update(request, code):
    try:
        acc = GLAccount.objects.select_related('group').get(code=code)
    except GLAccount.DoesNotExist:
        return _bad('not_found', 'الحساب غير موجود', status.HTTP_404_NOT_FOUND)
    data = request.data
    before = _account(acc)
    if 'name' in data:
        name = str(data['name'] or '').strip()
        if not name:
            return _bad('bad_name', 'اسم الحساب مطلوب')
        acc.name = name[:200]
    if 'statement_line' in data:
        acc.statement_line = str(data['statement_line'] or '').strip()[:40]
    for flag in ('is_active', 'requires_branch'):
        if flag in data:
            setattr(acc, flag, bool(data[flag]) and data[flag] not in ('false', '0'))
    if 'party_type' in data:
        if data['party_type'] not in dict(GLAccount.PARTY_CHOICES):
            return _bad('bad_party_type', 'نوع الطرف غير صحيح')
        acc.party_type = data['party_type']
    acc.save()
    AuditLog.log('gl_account_updated', user=_profile(request), obj=acc,
                 old_data=before, new_data=_account(acc))
    return Response(_account(acc))


@api_view(['POST'])
@permission_classes(EDIT)
@parser_classes([MultiPartParser, FormParser])
def accounts_import(request):
    f = request.FILES.get('file')
    if f is None:
        return _bad('no_file', 'اختر ملف Excel')
    if not f.name.lower().endswith('.xlsx'):
        return _bad('bad_file', 'الملف لازم يكون Excel (.xlsx)')
    dry_run = str(request.data.get('dry_run', 'true')).lower() in ('1', 'true', 'yes')
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    try:
        with os.fdopen(fd, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        try:
            rows = parse_trial_balance_sheet(path, request.data.get('sheet') or None)
        except Exception:      # unreadable workbook / no header row
            return _bad('bad_file', 'تعذّر قراءة الملف: لم يُعثر على ميزان المراجعة')
        res = import_coa(rows, user=_profile(request), dry_run=dry_run)
    finally:
        os.remove(path)
    return Response({'dry_run': dry_run, 'rows': len(rows), 'created': res.created,
                     'updated': res.updated, 'unknown_groups': res.unknown_groups})


# ── entries ──────────────────────────────────────────────────────────────────

def _entry_row(e):
    return {
        'id': e.id, 'number': e.number, 'entry_date': e.entry_date.isoformat(), 'book': e.book,
        'branch_id': e.branch_id, 'branch_name': _branch_label(e.branch),
        'description': e.description, 'status': e.status, 'source_type': e.source_type,
        'source_key': e.source_key, 'reverses': e.reverses_id,
        'total_debit': str(getattr(e, 'total_debit', None) or Decimal('0.00')),
        'total_credit': str(getattr(e, 'total_credit', None) or Decimal('0.00')),
        'created_by_name': e.created_by.full_name if e.created_by_id else '',
        'approved_by_name': e.approved_by.full_name if e.approved_by_id else '',
    }


def _entry_detail(e):
    lines = list(e.lines.select_related('account', 'branch').order_by('line_no'))
    row = _entry_row(e)
    row['total_debit'] = str(sum((ln.debit for ln in lines), Decimal('0.00')))
    row['total_credit'] = str(sum((ln.credit for ln in lines), Decimal('0.00')))
    row.update({
        'notes': e.notes, 'period': str(e.period) if e.period_id else '',
        'created_at': e.created_at.isoformat() if e.created_at else None,
        'approved_at': e.approved_at.isoformat() if e.approved_at else None,
        'reverses_number': e.reverses.number if e.reverses_id else None,
        'reversals': [{'id': r.id, 'number': r.number} for r in e.reversals.all()],
        'lines': [{
            'line_no': ln.line_no, 'account_code': ln.account.code, 'account_name': ln.account.name,
            'branch_id': ln.branch_id, 'branch_name': _branch_label(ln.branch),
            'party_code': ln.party_code, 'debit': str(ln.debit), 'credit': str(ln.credit),
            'description': ln.description, 'cheque_no': ln.cheque_no,
            'due_date': ln.due_date.isoformat() if ln.due_date else None,
        } for ln in lines],
    })
    return row


def _entries_qs():
    return (LedgerEntry.objects
            .select_related('branch', 'created_by__user', 'approved_by__user', 'period', 'reverses')
            .annotate(total_debit=Sum('lines__debit'), total_credit=Sum('lines__credit')))


class EntryCursor(CursorPagination):
    page_size = 100
    ordering = ('-entry_date', '-id')


def _parse_entry(data):
    """Request body → save_draft kwargs (raises ValueError with an Arabic message)."""
    entry_date = _date(data.get('entry_date'), 'تاريخ القيد')
    book = data.get('book') or 'general'
    if book not in MANUAL_BOOKS:
        raise ValueError('الدفتر غير صحيح للقيد اليدوي')
    branch = None
    branch_id = _int(data.get('branch') if data.get('branch') is not None else data.get('branch_id'))
    if branch_id:
        branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            raise ValueError('الفرع غير موجود')
    lines = data.get('lines') or []
    if not isinstance(lines, list):
        raise ValueError('الأسطر غير صحيحة')
    out = []
    for i, ln in enumerate(lines, start=1):
        if not isinstance(ln, dict):
            raise ValueError(f'السطر {i} غير صحيح')
        out.append({
            'account_code': str(ln.get('account_code') or '').strip(),
            'debit': ln.get('debit'), 'credit': ln.get('credit'),
            'branch_id': ln.get('branch_id') or None,
            'party_code': str(ln.get('party_code') or ''),
            'description': str(ln.get('description') or '')[:500],
            'cheque_no': str(ln.get('cheque_no') or '')[:40],
            'due_date': _date(ln.get('due_date'), f'استحقاق السطر {i}', required=False),
        })
    return {'entry_date': entry_date, 'book': book, 'branch': branch,
            'description': str(data.get('description') or '')[:500], 'lines': out}


def _save(request, entry=None):
    try:
        kw = _parse_entry(request.data)
    except ValueError as e:
        return _bad('bad_input', str(e))
    try:
        with transaction.atomic():
            saved = ledger.save_draft(user=_profile(request), entry=entry,
                                      source_type=entry.source_type if entry else 'manual',
                                      source_key=entry.source_key if entry else '', **kw)
            notes = str(request.data.get('notes') or '')
            if notes != saved.notes:
                saved.notes = notes
                saved.save(update_fields=['notes'])
    except ledger.LedgerError as e:
        return _ledger_error(e)
    return Response(_entry_detail(_entries_qs().get(pk=saved.pk)),
                    status=status.HTTP_200_OK if entry else status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@permission_classes(ENTRY)
def entries(request):
    if request.method == 'POST':
        return _save(request)
    p = request.query_params
    qs = _entries_qs()
    if p.get('status'):
        qs = qs.filter(status=p['status'])
    if p.get('book'):
        qs = qs.filter(book=p['book'])
    try:
        if p.get('date_from'):
            qs = qs.filter(entry_date__gte=_date(p['date_from'], 'من'))
        if p.get('date_to'):
            qs = qs.filter(entry_date__lte=_date(p['date_to'], 'إلى'))
    except ValueError as e:
        return _bad('bad_input', str(e))
    # line filters go through a subquery: a join on lines here would inflate the annotated totals
    branch = _int(p.get('branch'))
    if branch:
        qs = qs.filter(Q(branch_id=branch) |
                       Q(pk__in=LedgerLine.objects.filter(branch_id=branch).values('entry_id')))
    if p.get('account'):
        qs = qs.filter(pk__in=LedgerLine.objects.filter(
            account__code=p['account'].strip()).values('entry_id'))
    q = (p.get('q') or '').strip()
    if q:
        qs = filter_and_rank(qs, q, ['number', 'description'])
    pager = EntryCursor()
    page = pager.paginate_queryset(qs, request)
    return pager.get_paginated_response([_entry_row(e) for e in page])


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes(ENTRY)
def entry(request, pk):
    try:
        e = _entries_qs().get(pk=pk)
    except LedgerEntry.DoesNotExist:
        return _bad('not_found', 'القيد غير موجود', status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(_entry_detail(e))
    if e.status != 'draft':
        return _ledger_error(ledger.LedgerError('not_draft'))
    if request.method == 'PUT':
        return _save(request, entry=e)
    with transaction.atomic():
        locked = LedgerEntry.objects.select_for_update().get(pk=pk)
        if locked.status != 'draft':
            return _ledger_error(ledger.LedgerError('not_draft'))
        snapshot = ledger._snapshot(locked)
        ledger._audit('gl_entry_draft_deleted', user=_profile(request), obj=locked, old_data=snapshot)
        locked.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes(APPROVE)
def entry_approve(request, pk):
    try:
        e = ledger.approve(pk, user=_profile(request))
    except LedgerEntry.DoesNotExist:
        return _bad('not_found', 'القيد غير موجود', status.HTTP_404_NOT_FOUND)
    except ledger.LedgerError as err:
        return _ledger_error(err)
    return Response(_entry_detail(_entries_qs().get(pk=e.pk)))


@api_view(['POST'])
@permission_classes(APPROVE)
def entries_approve(request):
    ids = request.data.get('ids') or []
    if not isinstance(ids, list) or not ids:
        return _bad('bad_input', 'اختر قيداً واحداً على الأقل')
    if len(ids) > 500:
        return _bad('bad_input', 'الحد الأقصى 500 قيد في المرة')
    results = []
    for raw in ids:
        pk = _int(raw)
        try:
            e = ledger.approve(pk, user=_profile(request))
            results.append({'id': pk, 'ok': True, 'number': e.number})
        except LedgerEntry.DoesNotExist:
            results.append({'id': raw, 'ok': False, 'code': 'not_found', 'detail': 'القيد غير موجود'})
        except ledger.LedgerError as err:
            body = _ledger_error(err).data
            results.append({'id': pk, 'ok': False, 'code': body['code'], 'detail': body['detail']})
    return Response({'results': results,
                     'approved': sum(1 for r in results if r['ok']),
                     'refused': sum(1 for r in results if not r['ok'])})


@api_view(['POST'])
@permission_classes(APPROVE)
def entry_reverse(request, pk):
    reason = str(request.data.get('reason') or '').strip()
    if not reason:
        return _bad('reason_required', 'سبب العكس مطلوب')
    try:
        day = _date(request.data.get('entry_date'), 'تاريخ العكس', required=False)
    except ValueError as e:
        return _bad('bad_input', str(e))
    try:
        mirror = ledger.reverse(pk, user=_profile(request), reason=reason[:500], entry_date=day)
    except LedgerEntry.DoesNotExist:
        return _bad('not_found', 'القيد غير موجود', status.HTTP_404_NOT_FOUND)
    except ledger.LedgerError as err:
        return _ledger_error(err)
    return Response(_entry_detail(_entries_qs().get(pk=mirror.pk)))


# ── reports ──────────────────────────────────────────────────────────────────

def _range(request):
    return _date(request.query_params.get('from'), 'من'), _date(request.query_params.get('to'), 'إلى')


def _report(request, build, export=None):
    """Run `build()`; JSON, or the Excel layout when ?format=xlsx (needs ledger.export)."""
    if _wants_xlsx(request):
        denied = deny_unless(request, 'ledger', 'export')
        if denied:
            return denied
    try:
        data = build()
    except ValueError as e:
        return _bad('bad_input', str(e))
    if _wants_xlsx(request):
        return export(data)
    return Response(_j(data))


@api_view(['GET'])
@permission_classes(VIEW)
def report_trial_balance(request):
    by = request.query_params.get('by') or 'account'
    if by not in ('account', 'group'):
        return _bad('bad_input', 'by = account أو group')
    branch = _int(request.query_params.get('branch'))

    def build():
        f, t = _range(request)
        return {'from': f, 'to': t, 'by': by, 'branch': branch,
                'rows': balances.trial_balance(f, t, branch_id=branch, by=by)}
    resp = _report(request, build, exports.trial_balance)
    if isinstance(resp, Response) and resp.status_code == 200:
        resp.data = resp.data['rows']      # list + its is_total row
    return resp


@api_view(['GET'])
@permission_classes(VIEW)
def report_account_statement(request):
    code = (request.query_params.get('code') or '').strip()
    if not code:
        return _bad('bad_input', 'اختر الحساب')
    if not GLAccount.objects.filter(code=code).exists():
        return _bad('not_found', 'الحساب غير موجود', status.HTTP_404_NOT_FOUND)
    party = (request.query_params.get('party') or '').strip() or None
    branch = _int(request.query_params.get('branch'))

    def build():
        f, t = _range(request)
        acc = GLAccount.objects.get(code=code)
        return {'code': code, 'name': acc.name, 'from': f, 'to': t, 'party': party,
                **balances.account_statement(code, f, t, branch_id=branch, party_code=party)}
    return _report(request, build, exports.account_statement)


@api_view(['GET'])
@permission_classes(VIEW)
def report_statements(request):
    def build():
        f, t = _range(request)
        return {'from': f, 'to': t, **statements.trading_and_pl(f, t)}
    return _report(request, build, exports.trading)


@api_view(['GET'])
@permission_classes(VIEW)
def report_position(request):
    def build():
        as_of = _date(request.query_params.get('as_of'), 'التاريخ')
        return {'as_of': as_of, **statements.financial_position(as_of)}
    return _report(request, build, exports.position)


@api_view(['GET'])
@permission_classes(VIEW)
def report_branch_pl(request):
    def build():
        f, t = _range(request)
        cols = statements.branch_pl(f, t)
        ids = {c['branch_id'] for c in cols if c.get('branch_id')}
        labels = {b.pk: _branch_label(b) for b in Branch.objects.filter(pk__in=ids)}
        for c in cols:
            c['label'] = labels.get(c.get('branch_id')) or c['name']
        return {'from': f, 'to': t, 'columns': cols}
    return _report(request, build, exports.branch_pl)


@api_view(['GET'])
@permission_classes(VIEW)
def report_comparison(request):
    def build():
        raw = (request.query_params.get('years') or '').replace(' ', '')
        years = sorted({int(y) for y in raw.split(',') if y.isdigit()})
        if not years:
            this = datetime.date.today().year
            years = [this - 1, this]
        if len(years) > 10 or any(y < 2000 or y > 2100 for y in years):
            raise ValueError('السنوات غير صحيحة (حتى 10 سنوات)')
        return {'years': statements.comparison(years)}
    resp = _report(request, build, exports.comparison)
    if isinstance(resp, Response) and resp.status_code == 200:
        resp.data = resp.data['years']
    return resp
