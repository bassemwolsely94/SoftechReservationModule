"""Draft-now endpoints (Plan 2 / Task 7) - mounted under /api/finance/gl/drafting/.

POST run/ starts a background run (202 {run_id}; 409 when another run is active); GET runs/ and
runs/{id}/ feed the ProgressBar. All-branch users only, RBAC module ``ledger``.
"""
import datetime
import logging
import os
import re
import tempfile

from django.db import transaction
from django.db.models import Count, Max, Min
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.pagination import CursorPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.branches.models import Branch
from apps.catalog.wildcard import filter_and_rank
from apps.finance.models import (
    GLDraftRun, GLParty, GLSourceDoc, GLSourceMap, LedgerEntry, PostingRule, ReconParty,
    SourceException,
)
from core.errors import public_error
from core.threads import start_thread
from core.upload_safety import capped_rows, max_upload_bytes

from . import drafting, parties, plan2_adapter, rules
from .ledger import OPENING_DATE
from .drafting_serializers import (
    exception_json, map_json, party_json, rule_json, source_doc_json,
)
from .views import APPROVE, EDIT, VIEW, _date, _int, _j, _no_profile, _perms, _profile

logger = logging.getLogger(__name__)

CREATE = _perms(post=('create',))
PARTIES = _perms(post=('approve',))          # GET view, POST approve
PARTY_EDIT = _perms(post=('edit',))          # import / propose, rules (GET view, POST edit)
PREVIEW = _perms(post=('view',))             # computes only, saves nothing
MAX_PREVIEW_DAYS = 31
MAX_NOTE = 2000
MAX_SPAN_DAYS = 400
BEFORE_OPENING = f'لا يمكن الترحيل قبل تاريخ الافتتاح {OPENING_DATE.isoformat()}'
RULE_CODE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$')   # seed codes use dots: sales.cash
MAX_RULE_DESCRIPTION = 300   # PostingRule.description max_length


def _bad(detail):
    return Response({'code': 'bad_input', 'detail': detail}, status=status.HTTP_400_BAD_REQUEST)


def _run_json(r):
    return {'id': r.pk, 'status': r.status, 'date_from': r.date_from.isoformat(),
            'date_to': r.date_to.isoformat(), 'source_types': r.source_types,
            'triggered_by': r.triggered_by, 'counts': r.counts, 'detail': r.detail,
            'started_at': r.started_at.isoformat() if r.started_at else None,
            'finished_at': r.finished_at.isoformat() if r.finished_at else None}


def _background(run_id, date_from, date_to, source_types):
    run = GLDraftRun.objects.get(pk=run_id)
    try:
        drafting.draft_range(date_from, date_to, source_types=source_types, run=run)
    except Exception as exc:   # draft_range records its own failures; last line of defence
        logger.exception('gl draft-now run %s crashed', run_id)
        drafting.mark_failed(run_id, exc)


@api_view(['POST'])
@permission_classes(CREATE)
def drafting_run(request):
    try:
        d1 = datetime.date.fromisoformat(str(request.data.get('date_from') or '')[:10])
        d2 = datetime.date.fromisoformat(str(request.data.get('date_to') or '')[:10])
    except ValueError:
        return _bad('التاريخ غير صحيح (YYYY-MM-DD)')
    if d2 < d1:
        return _bad('تاريخ النهاية قبل البداية')
    if d1 < OPENING_DATE:
        return _bad(BEFORE_OPENING)
    if (d2 - d1).days > MAX_SPAN_DAYS:
        return _bad('المدة أطول من المسموح')
    types = request.data.get('source_types') or []
    if not isinstance(types, list) or any(t not in drafting.SOURCE_ORDER for t in types):
        return _bad('نوع مصدر غير معروف')
    try:
        run = drafting.start_run(triggered_by=f'user:{request.user.pk}', date_from=d1, date_to=d2,
                                 source_types=types)
    except drafting.DraftBusy:
        return Response({'code': 'busy', 'detail': 'هناك عملية ترحيل جارية الآن'},
                        status=status.HTTP_409_CONFLICT)
    try:
        start_thread(_background, args=(run.pk, d1, d2, types or None), name=f'gl-draft-{run.pk}')
    except Exception:
        GLDraftRun.objects.filter(pk=run.pk, status='running').update(status='failed')
        raise
    return Response({'run_id': run.pk}, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes(VIEW)
def drafting_runs(request):
    try:
        limit = max(1, min(int(request.query_params.get('limit') or 10), 100))
    except ValueError:
        limit = 10
    return Response({'results': [_run_json(r) for r in GLDraftRun.objects.all()[:limit]]})


@api_view(['GET'])
@permission_classes(VIEW)
def drafting_run_detail(request, pk):
    r = GLDraftRun.objects.filter(pk=pk).first()
    if r is None:
        return Response({'code': 'not_found', 'detail': 'التشغيل غير موجود'},
                        status=status.HTTP_404_NOT_FOUND)
    return Response(_run_json(r))


# ── shared helpers ───────────────────────────────────────────────────────────

def _err(errors, http=status.HTTP_400_BAD_REQUEST):
    return Response({'code': 'invalid', 'detail': errors[0] if errors else '', 'errors': list(errors)},
                    status=http)


def _need_profile(request):
    p = _profile(request)
    return p, (None if p else _no_profile())


class _Cursor(CursorPagination):
    page_size = 100
    ordering = ('id',)


class ExceptionCursor(_Cursor):
    ordering = ('-created_at', '-id')


class PartyCursor(_Cursor):
    ordering = ('party_type', 'code', 'id')


# ── parties ──────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes(PARTIES)
def parties_root(request):
    if request.method == 'POST':
        profile, bad = _need_profile(request)
        if bad:
            return bad
        d = request.data
        ptype, code = str(d.get('type') or '').strip(), str(d.get('code') or '').strip()
        personcode = str(d.get('personcode') or '').strip()
        if ptype not in dict(GLParty.TYPE_CHOICES) or not code or not personcode:
            return _err(['النوع والكود وكود SOFTECH مطلوبة'])
        name = str(d.get('name') or '').strip()[:200]
        try:
            g = parties.create_party_from_personcode(user=profile, party_type=ptype, code=code,
                                                     personcode=personcode, name=name)
        except ValueError as e:
            return _err([str(e)])
        return Response(party_json(g), status=status.HTTP_201_CREATED)
    p = request.query_params
    qs = GLParty.objects.select_related('recon_party')
    if p.get('type'):
        qs = qs.filter(party_type=p['type'])
    if p.get('status'):
        qs = qs.filter(status=p['status'])
    q = (p.get('q') or '').strip()
    if q:
        qs = filter_and_rank(qs, q, ['code', 'name', 'softech_personcode', 'recon_party__name'])
    pager = PartyCursor()
    page = pager.paginate_queryset(qs, request)
    return pager.get_paginated_response([party_json(g) for g in page])


@api_view(['POST'])
@permission_classes(PARTY_EDIT)
@parser_classes([MultiPartParser, FormParser])
def parties_import(request):
    profile, bad = _need_profile(request)
    if bad:
        return bad
    f = request.FILES.get('file')
    if f is None:
        return _err(['اختر ملف Excel'])
    if os.path.splitext(f.name or '')[1].lower() != '.xlsx':
        return _err(['الملف لازم يكون Excel (.xlsx)'])
    if f.size and f.size > max_upload_bytes():
        return _err(['الملف أكبر من المسموح'])
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    try:
        with os.fdopen(fd, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        try:
            rows = list(capped_rows(parties.parse_party_sheets(path)))
        except Exception:
            return _err(['تعذّر قراءة الملف'])
        res = parties.import_parties(rows, user=profile)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return Response({**res, 'rows': len(rows)})


@api_view(['POST'])
@permission_classes(PARTIES)
@parser_classes([MultiPartParser, FormParser])
def parties_confirm_upload(request):
    """The reviewed suggestions sheet: «النوع» + «كود المالية» + «الكود المعتمد». dry_run=true (default)
    previews every row and saves nothing; dry_run=false confirms the valid rows (each audited)."""
    profile, bad = _need_profile(request)
    if bad:
        return bad
    f = request.FILES.get('file')
    if f is None:
        return _err(['اختر ملف Excel'])
    if os.path.splitext(f.name or '')[1].lower() != '.xlsx':
        return _err(['الملف لازم يكون Excel (.xlsx)'])
    if f.size and f.size > max_upload_bytes():
        return _err(['الملف أكبر من المسموح'])
    apply = str(request.data.get('dry_run', 'true')).lower() in ('false', '0', 'no')
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    try:
        with os.fdopen(fd, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        try:
            rows, problems = parties.parse_confirm_sheet(path)
            rows = list(capped_rows(rows))
        except ValueError as e:
            return _err([str(e)])
        except Exception:
            return _err(['تعذّر قراءة الملف'])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return Response(parties.bulk_confirm(rows, problems, user=profile, apply=apply))


@api_view(['POST'])
@permission_classes(PARTY_EDIT)
def parties_propose(request):
    profile, bad = _need_profile(request)
    if bad:
        return bad
    return Response(parties.propose_matches(user=profile))


def _party_action(request, pk, fn, **kw):
    profile, bad = _need_profile(request)
    if bad:
        return bad
    try:
        return Response(party_json(fn(pk, user=profile, **kw)))
    except GLParty.DoesNotExist:
        return Response({'code': 'not_found', 'detail': 'الطرف غير موجود'},
                        status=status.HTTP_404_NOT_FOUND)
    except ValueError as e:
        return _err([str(e)])


@api_view(['POST'])
@permission_classes(PARTIES)
def party_confirm(request, pk):
    return _party_action(request, pk, parties.confirm_party,
                         personcode=str(request.data.get('personcode') or ''))


@api_view(['POST'])
@permission_classes(PARTIES)
def party_reject(request, pk):
    return _party_action(request, pk, parties.reject_party)


# ── source maps (never deleted: PUT only) ────────────────────────────────────

@api_view(['GET'])
@permission_classes(VIEW)
def maps_list(request):
    qs = GLSourceMap.objects.select_related('account')
    if request.query_params.get('kind'):
        qs = qs.filter(kind=request.query_params['kind'])
    return Response({'results': [map_json(m) for m in qs]})


@api_view(['PUT'])
@permission_classes(EDIT)
def map_put(request, kind, source_value):
    profile, bad = _need_profile(request)
    if bad:
        return bad
    branch_id = _int(request.data.get('branch_id'))
    if kind == 'card_clearing' and not branch_id:
        return _err(['ربط تسوية البطاقات يحتاج فرعاً'])
    if kind == 'intercompany' and not branch_id:   # Ruling P24: the HQ branch
        return _err(['ربط الشركات الشقيقة يحتاج فرعاً (المركز الرئيسي)'])
    try:
        m = rules.save_map(user=profile, kind=kind, source_value=source_value,
                           account_code=str(request.data.get('account_code') or ''),
                           branch_id=branch_id, note=str(request.data.get('note') or '')[:200])
    except rules.RuleError as e:
        return _err(e.errors)
    return Response(map_json(m))


# ── posting rules (versioned, never deleted: no DELETE route) ────────────────

_RULE_KEYS = ('code', 'source_type', 'description', 'conditions', 'action', 'granularity', 'lines',
              'book', 'priority', 'effective_from', 'effective_to')


def _rule_args(data):
    """Whitelisted, typed rule fields from a request body; ValueError on a bad date/priority."""
    d = {k: data[k] for k in _RULE_KEYS if k in data}
    d['effective_from'] = _date(d.get('effective_from'), 'ساري من')
    if d.get('effective_to'):
        d['effective_to'] = _date(d['effective_to'], 'ساري حتى')
    else:
        d.pop('effective_to', None)
    if 'code' in d and (not isinstance(d['code'], str) or not RULE_CODE_RE.match(d['code'])):
        raise ValueError('الكود: حروف إنجليزية وأرقام و . _ - فقط، حتى 60 حرفاً')
    if 'description' in d:
        if d['description'] is None:
            d['description'] = ''
        if not isinstance(d['description'], str) or len(d['description']) > MAX_RULE_DESCRIPTION:
            raise ValueError(f'الوصف نص حتى {MAX_RULE_DESCRIPTION} حرف')
    if 'priority' in d:
        p = d['priority']
        if isinstance(p, bool) or isinstance(p, float) and not p.is_integer():
            raise ValueError('الأولوية يجب أن تكون رقماً صحيحاً')
        try:
            d['priority'] = int(p)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('الأولوية يجب أن تكون رقماً صحيحاً')
        if not -32768 <= d['priority'] <= 32767:
            raise ValueError('الأولوية خارج المدى المسموح (-32768 إلى 32767)')
    for k in ('source_type', 'action', 'granularity', 'book'):
        if k in d and not isinstance(d[k], str):
            raise ValueError(f'{k}: شكل غير صحيح')
    if 'conditions' in d and not isinstance(d['conditions'], dict):
        raise ValueError('الشروط: شكل غير صحيح')
    if 'lines' in d and not isinstance(d['lines'], list):
        raise ValueError('الأسطر: شكل غير صحيح')
    return d


@api_view(['GET', 'POST'])
@permission_classes(PARTY_EDIT)
def rules_root(request):
    if request.method == 'POST':
        profile, bad = _need_profile(request)
        if bad:
            return bad
        try:
            if request.data.get('effective_to'):
                return _err(['تاريخ الانتهاء يُحدد تلقائياً عند إصدار نسخة جديدة'])
            d = _rule_args(request.data)
            d.pop('effective_to', None)
            if not d.get('code') or not d.get('source_type'):
                return _err(['الكود ونوع المصدر مطلوبان'])
            rule = rules.save_rule(user=profile, **d)
        except ValueError as e:
            return _err([str(e)])
        except rules.RuleError as e:
            return _err(e.errors)
        return Response(rule_json(rule), status=status.HTTP_201_CREATED)
    p = request.query_params
    qs = PostingRule.objects.all()
    if p.get('source_type'):
        qs = qs.filter(source_type=p['source_type'])
    if p.get('active') in ('1', 'true'):
        qs = qs.filter(is_active=True)
    current = {}
    for r in qs.order_by('code', '-version'):
        current.setdefault(r.code, r)         # highest version per code
    return Response({'results': [rule_json(r) for r in current.values()]})


@api_view(['GET'])
@permission_classes(VIEW)
def rule_versions(request, code):
    return Response({'results': [rule_json(r) for r in
                                 PostingRule.objects.filter(code=code).order_by('-version')]})


@api_view(['POST'])
@permission_classes(PREVIEW)
def rule_preview(request):
    try:
        d1 = _date(request.data.get('date_from'), 'من')
        d2 = _date(request.data.get('date_to'), 'إلى')
        if d2 < d1:
            return _err(['تاريخ النهاية قبل البداية'])
        if (d2 - d1).days >= MAX_PREVIEW_DAYS:
            return _err([f'مدة التجربة لا تتجاوز {MAX_PREVIEW_DAYS} يوماً'])
        raw = request.data.get('rule')
        if not isinstance(raw, dict):
            return _err(['القاعدة مطلوبة'])
        d = _rule_args({**raw, 'effective_from': raw.get('effective_from') or d1.isoformat()})
        d.setdefault('code', 'preview')
        res = rules.preview_rule(d, d1, d2)
    except ValueError as e:
        return _err([str(e)])
    except rules.RuleError as e:
        return _err(e.errors)
    except Exception as exc:   # a failed SOFTECH read: a clear answer in the rule editor, not a 500
        return _err([public_error(request, exc)], http=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(_j(res))


# ── exceptions inbox ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(VIEW)
def exceptions_list(request):
    p = request.query_params
    qs = SourceException.objects.select_related('source_doc', 'original_entry')
    qs = qs.filter(status=p.get('status') or 'open')
    if p.get('kind'):
        qs = qs.filter(kind=p['kind'])
    if p.get('source_type'):
        qs = qs.filter(source_doc__source_type=p['source_type'])
    try:
        if p.get('date_from'):
            qs = qs.filter(source_date__gte=_date(p['date_from'], 'من'))
        if p.get('date_to'):
            qs = qs.filter(source_date__lte=_date(p['date_to'], 'إلى'))
    except ValueError as e:
        return _err([str(e)])
    if p.get('branch'):
        b = Branch.objects.filter(pk=_int(p['branch'])).first()
        qs = qs.filter(source_doc__branch_code=(b.softech_branch_id if b else p['branch']))
    pager = ExceptionCursor()
    page = pager.paginate_queryset(qs, request)
    return pager.get_paginated_response([exception_json(e) for e in page])


@api_view(['GET'])
@permission_classes(VIEW)
def exceptions_counts(request):
    """Open exceptions per kind (optionally one source_type) - the tab badge and kind chips."""
    qs = SourceException.objects.filter(status='open')
    if request.query_params.get('source_type'):
        qs = qs.filter(source_doc__source_type=request.query_params['source_type'])
    by_kind = {r['kind']: r['n'] for r in qs.values('kind').annotate(n=Count('id'))}
    return Response({'total': sum(by_kind.values()), 'by_kind': by_kind})


@api_view(['POST'])
@permission_classes(CREATE)
def exception_ignore(request, pk):
    profile, bad = _need_profile(request)
    if bad:
        return bad
    note = str(request.data.get('note') or '').strip()
    if not note or len(note) > MAX_NOTE:
        return _err(['اكتب سبب التجاهل'])
    with transaction.atomic():
        e = (SourceException.objects.select_for_update().select_related('source_doc')
             .filter(pk=pk).first())
        if e is None:
            return Response({'code': 'not_found', 'detail': 'الاستثناء غير موجود'},
                            status=status.HTTP_404_NOT_FOUND)
        if e.status != 'open':
            return Response({'code': 'not_open', 'detail': 'الاستثناء ليس مفتوحاً'},
                            status=status.HTTP_409_CONFLICT)
        e.status, e.resolved_by, e.resolved_at, e.resolution_note = 'ignored', profile, timezone.now(), note
        e.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note'])
        # the doc stays 'exception' on purpose: the engine only retries new/changed docs
        if e.kind == 'closed_period_change':   # except here: the old figure stands until the next change
            plan2_adapter.closed_change_ignored(e)
        parties._audit('gl_exception_ignored', user=profile, obj=e,
                       old_data={'status': 'open'},
                       new_data={'status': 'ignored', 'kind': e.kind, 'note': note,
                                 'source_key': e.source_doc.source_key})
    return Response(exception_json(e))


@api_view(['POST'])
@permission_classes(CREATE)
def exceptions_redraft(request):
    ids = request.data.get('ids')
    if (not isinstance(ids, list) or not ids or len(ids) > 500
            or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)):
        return _err(['اختر استثناءات لإعادة الترحيل'])
    if SourceException.objects.filter(pk__in=ids, status='open').count() != len(set(ids)):
        return _err(['بعض الاستثناءات غير موجودة أو ليست مفتوحة'])
    # finance's parked journal groups have no SOFTECH reader: they end by inclusion or «تجاهل»
    docs = (GLSourceDoc.objects.filter(exceptions__pk__in=ids)
            .exclude(source_type=plan2_adapter.MANUAL_IMPORT_SOURCE).distinct())
    agg = docs.aggregate(lo=Min('doc_date'), hi=Max('doc_date'))
    d1, d2 = agg['lo'], agg['hi']
    if d1 is None:
        return _err(['قيود يومية المالية مبتتعادش ترحيلها: تتضم بكل أسطرها أو تتجاهل بسبب'])
    if d1 < OPENING_DATE:
        return _err([BEFORE_OPENING])
    if (d2 - d1).days > MAX_SPAN_DAYS:
        return _err(['المدة أطول من المسموح'])
    types = sorted(set(docs.values_list('source_type', flat=True)))
    try:
        run = drafting.start_run(triggered_by=f'user:{request.user.pk}', date_from=d1, date_to=d2,
                                 source_types=types)
    except drafting.DraftBusy:
        return Response({'code': 'busy', 'detail': 'هناك عملية ترحيل جارية الآن'},
                        status=status.HTTP_409_CONFLICT)
    try:
        start_thread(_background, args=(run.pk, d1, d2, types), name=f'gl-redraft-{run.pk}')
    except Exception:
        GLDraftRun.objects.filter(pk=run.pk, status='running').update(status='failed')
        raise
    return Response({'run_id': run.pk}, status=status.HTTP_202_ACCEPTED)


# ── Ruling P23: accountant's decision on an edited entry SOFTECH changed ────

_DECISION_HTTP = {'not_found': status.HTTP_404_NOT_FOUND}
BUSY = 'هناك عملية ترحيل جارية الآن'


class _Refused(Exception):
    def __init__(self, response):
        super().__init__('refused')
        self.response = response


def _decision_refused(e: drafting.DecisionError):
    return Response({'code': e.code, 'detail': e.message},
                    status=_DECISION_HTTP.get(e.code, status.HTTP_409_CONFLICT))


def _decision_args(request):
    """-> (note, version, error response). ``version`` = proposal_version of the lines shown."""
    note = request.data.get('note')
    note = '' if note is None else str(note).strip()
    if len(note) > MAX_NOTE:
        return note, None, _err([f'الملاحظة أطول من {MAX_NOTE} حرف'])
    version = request.data.get('version')
    if not isinstance(version, str) or not version:
        return note, None, _err(['نسخة سوفتيك المعروضة مطلوبة (version) — أعد تحميل الصفحة'])
    return note, version, None


@api_view(['POST'])
@permission_classes(APPROVE)
def exception_accept_softech(request, pk):
    """«اعتماد نسخة سوفتيك»: release the edit and redraft the group's window now (202 {run_id}).
    The release and the run start commit together: a busy engine (409) changes nothing."""
    profile, bad = _need_profile(request)
    if bad:
        return bad
    note, version, bad = _decision_args(request)
    if bad:
        return bad
    try:
        with transaction.atomic():
            try:
                win = drafting.accept_softech(pk, user=profile, note=note, version=version)
            except drafting.DecisionError as e:
                raise _Refused(_decision_refused(e))
            d1, d2, types = win['date_from'], win['date_to'], win['source_types']
            if d1 < OPENING_DATE:
                raise _Refused(_err([BEFORE_OPENING]))
            if (d2 - d1).days > MAX_SPAN_DAYS:
                raise _Refused(_err(['المدة أطول من المسموح']))
            try:
                run = drafting.start_run(triggered_by=f'user:{request.user.pk}', date_from=d1, date_to=d2,
                                         source_types=types)
            except drafting.DraftBusy:
                raise _Refused(Response({'code': 'busy', 'detail': BUSY}, status=status.HTTP_409_CONFLICT))
    except _Refused as r:
        return r.response
    try:
        start_thread(_background, args=(run.pk, d1, d2, types), name=f'gl-accept-{run.pk}')
    except Exception:
        GLDraftRun.objects.filter(pk=run.pk, status='running').update(status='failed')
        raise
    return Response({'run_id': run.pk}, status=status.HTTP_202_ACCEPTED)


@api_view(['POST'])
@permission_classes(APPROVE)
def exception_keep_edit(request, pk):
    """«إبقاء تعديلي»: keep the accountant's entry; nothing changes until SOFTECH changes again."""
    profile, bad = _need_profile(request)
    if bad:
        return bad
    note, version, bad = _decision_args(request)
    if bad:
        return bad
    try:
        ex = drafting.keep_edit(pk, user=profile, note=note, version=version)
    except drafting.DecisionError as e:
        return _decision_refused(e)
    return Response(exception_json(SourceException.objects.select_related('source_doc').get(pk=ex.pk)))


# ── entry -> source documents ────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes(VIEW)
def entry_source(request, pk):
    if not LedgerEntry.objects.filter(pk=pk).exists():
        return Response({'code': 'not_found', 'detail': 'القيد غير موجود'},
                        status=status.HTTP_404_NOT_FOUND)
    docs = GLSourceDoc.objects.filter(entry_id=pk).select_related('rule').order_by('doc_date', 'id')
    return Response({'docs': [source_doc_json(d) for d in docs]})


# ── read-only metadata for the screens (Ruling P16) ──────────────────────────

@api_view(['GET'])
@permission_classes(VIEW)
def rules_meta(request):
    """Everything the rule editor offers, read from rules.py - the UI keeps no copy."""
    return Response({
        'source_fields': {k: list(v) for k, v in rules.SOURCE_FIELDS.items()},
        'condition_keys': {k: list(v) for k, v in rules.CONDITION_KEYS.items()},
        'map_kinds': list(rules.MAP_KINDS), 'map_keys': list(rules.MAP_KEYS),
        'map_key_for_kind': dict(rules.MAP_KEY_FOR_KIND),
        'branch_modes': list(rules.BRANCH_MODES), 'party_modes': list(rules.PARTY_MODES),
        'placeholders': list(rules.PLACEHOLDERS),
        'bank_branch_sources': list(rules.BANK_BRANCH_SOURCES),
        'cheque_sources': list(rules._CHEQUES),
        'actions': ['post', 'skip'],
        'granularities': [k for k, _ in PostingRule.GRANULARITY_CHOICES],
        'books': [k for k, _ in PostingRule.BOOK_CHOICES],
    })


@api_view(['GET'])
@permission_classes(VIEW)
def parties_persons(request):
    """SOFTECH persons (A/P mirror) for the party picker; wildcard search, at most 50."""
    p = request.query_params
    qs = ReconParty.objects.all()
    if p.get('type'):
        qs = qs.filter(party_type=p['type'])
    q = (p.get('q') or '').strip()
    if q:
        qs = filter_and_rank(qs, q, ['softech_personcode', 'name'])
    qs = qs.order_by('name', 'id')[:50]
    return Response({'results': [{'id': r.pk, 'party_type': r.party_type,
                                  'softech_personcode': r.softech_personcode, 'name': r.name}
                                 for r in qs]})


@api_view(['GET'])
@permission_classes(VIEW)
def exceptions_unmapped_values(request):
    """Distinct values behind open unmapped_account exceptions: [{kind, value, count}]."""
    kind = request.query_params.get('kind') or 'unmapped_account'
    counts = {}
    for d in (SourceException.objects.filter(status='open', kind=kind)
              .values_list('detail', flat=True).iterator()):
        d = d or {}
        if d.get('kind') and d.get('value') not in (None, ''):
            k = (str(d['kind']), str(d['value']))
            counts[k] = counts.get(k, 0) + 1
    return Response({'results': [{'kind': k, 'value': v, 'count': n}
                                 for (k, v), n in sorted(counts.items())]})
