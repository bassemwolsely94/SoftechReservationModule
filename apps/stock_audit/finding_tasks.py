"""
apps/stock_audit/finding_tasks.py — C13: a stock-audit finding becomes an assigned task plus a
targeted count of just its items, and the count result closes it.

  create_tasks(findings, by, request)   one task per finding (never a second open one) + ONE
                                        filtered count session per branch holding only those
                                        findings' items at that branch. AuditLog per finding.
  on_count_closed(session, by, request) called when a count session is closed (finalized):
                                        every open link on it closes — the finding is marked
                                        reviewed when all its items matched, or stays as it is
                                        with the variance written on it. AuditLog per finding.

Permissions and branch scope are checked by the caller (views.py, stock_audit Access). The count
session reads SOFTECH only when the counter takes its snapshot; nothing here writes to SOFTECH.
"""
import datetime as _dt
from collections import OrderedDict

from django.db import transaction
from django.utils import timezone

from .assignment import default_assignee
from .models import StockAuditFinding, StockAuditFindingTask
from .rules import RULES

DUE_DAYS = 2                       # task due date = created + 2 days (owner question in the PR)
MAX_ITEMS_PER_FINDING = 50
REVIEWABLE = (StockAuditFinding.ST_OPEN, StockAuditFinding.ST_ESCALATED)
PRIORITY_BY_SEVERITY = {'critical': 'high', 'warning': 'normal', 'info': 'low'}
TASK_DONE = ('completed', 'cancelled')


def finding_item_codes(f):
    """The finding's own item, then any other item on its evidence lines (order kept, no repeats)."""
    codes = OrderedDict()
    if f.itemcode:
        codes[f.itemcode] = True
    ev = f.evidence or {}
    lines = ev.get('lines') or ([ev['line']] if isinstance(ev.get('line'), dict) else [])
    for line in lines:
        code = str((line or {}).get('itemcode') or '').strip()
        if code:
            codes[code] = True
    return list(codes)[:MAX_ITEMS_PER_FINDING]


def _audit(action, finding, by, request, changes=None, extra=None, note=''):
    from apps.audit.models import AuditLog
    AuditLog.log(action, user=by, obj=finding, changes=changes, note=note[:255], request=request,
                 extra={'rule': finding.rule_code, 'branch': finding.branchcode, **(extra or {})})


def _close_stale(link, by, request):
    """An open link whose task was cancelled/deleted or whose count was deleted no longer holds the
    finding: close it (outcome cancelled) so a new task can be made. Returns True when closed."""
    task, session = link.task, link.count_session
    if task is not None and task.status != 'cancelled' and session is not None:
        return False
    link.status, link.outcome, link.closed_at = link.ST_CLOSED, link.OUT_CANCELLED, timezone.now()
    link.save(update_fields=['status', 'outcome', 'closed_at'])
    _audit('stock_audit_finding_task_closed', link.finding, by, request,
           extra={'link': link.pk, 'task': link.task_id, 'count_session': link.count_session_id,
                  'outcome': link.outcome})
    return True


def open_link(finding, by=None, request=None):
    link = (finding.tasks.filter(status=StockAuditFindingTask.ST_OPEN)
            .select_related('task', 'count_session', 'finding').first())
    if link is None or _close_stale(link, by, request):
        return None
    return link


def _branches(codes):
    from apps.branches.models import Branch
    return {b.softech_branch_id: b for b in Branch.objects.filter(softech_branch_id__in=codes)}


def _make_session(code, branch, findings, items, by):
    from apps.stockcount.models import StockCountSession
    bname = (branch.name_ar or branch.name) if branch else code
    ids = ', '.join(f'#{f.pk}' for f in findings)
    return StockCountSession.objects.create(
        name=f'جرد ملاحظات تدقيق — {bname} — {len(findings)} ملاحظة'[:200],
        mode='filtered', branch_code=code, item_codes_filter=items, created_by=by,
        notes=f'جرد مستهدف لأصناف ملاحظات تدقيق المخزون {ids}. إغلاق الجلسة يقفل الملاحظات بنتيجة الجرد.')


def _make_task(f, branch, session, items, assignee, by):
    from apps.tasks.models import OperationalTask
    from apps.tasks.views import _add_system_message, _log_audit, _notify_assignee
    rule = RULES.get(f.rule_code, {}).get('name_ar', f.rule_code)
    item = (f.item.name if f.item_id else '') or f.itemcode
    task = OperationalTask.objects.create(
        title=f'ملاحظة تدقيق: {rule} — {item}'[:255],
        description=(f'{f.message_ar}\n\nالقيمة: {f.value_egp} ج.م — المستند {f.doccode} {f.docnumber or ""}\n'
                     f'جلسة الجرد المستهدف #{session.pk} ({len(items)} صنف): {", ".join(items)}\n'
                     f'إغلاق جلسة الجرد يقفل الملاحظة بالنتيجة.'),
        task_type='stock_count', category='operations',
        priority=PRIORITY_BY_SEVERITY.get(f.severity, 'normal'),
        branch=branch, created_by=by, assigned_to=assignee,
        related_model='stock_audit_finding', related_id=f.pk,
        due_date=timezone.now() + _dt.timedelta(days=DUE_DAYS),
        tags='stock_audit',
    )
    _log_audit(task, 'created', by, extra={'stock_audit_finding': f.pk, 'count_session': session.pk})
    _add_system_message(task, f'أُنشئت من ملاحظة تدقيق المخزون #{f.pk} بواسطة {by.full_name if by else "النظام"}')
    if assignee:
        _notify_assignee(task, assignee, by)
    return task


def create_tasks(findings, by=None, request=None):
    """findings: already permission- and branch-checked by the caller.
    Returns {'created': [link], 'existing': [link], 'skipped': [{id, reason}]}."""
    out = {'created': [], 'existing': [], 'skipped': []}
    todo = OrderedDict()                       # branchcode → [(finding, items)]
    with transaction.atomic():
        locked = (StockAuditFinding.objects.select_for_update()
                  .filter(pk__in=[f.pk for f in findings]).order_by('pk'))
        for f in locked:
            link = open_link(f, by, request)
            if link is not None:
                out['existing'].append(link)
                continue
            if f.status not in REVIEWABLE:
                out['skipped'].append({'id': f.pk, 'reason': 'الملاحظة ليست مفتوحة — finding is not open'})
                continue
            items = finding_item_codes(f)
            if not items:
                out['skipped'].append({'id': f.pk, 'reason': 'لا يوجد صنف للجرد — no item to count'})
                continue
            todo.setdefault(f.branchcode, []).append((f, items))
        branches = _branches(list(todo))
        for code, rows in todo.items():
            branch = branches.get(code)
            union = list(OrderedDict.fromkeys(c for _, items in rows for c in items))
            session = _make_session(code, branch, [f for f, _ in rows], union, by)
            for f, items in rows:
                assignee = default_assignee(f)
                task = _make_task(f, branch, session, items, assignee, by)
                link = StockAuditFindingTask.objects.create(
                    finding=f, task=task, count_session=session, item_codes=items,
                    assigned_to=assignee, created_by=by)
                _audit('stock_audit_finding_task_created', f, by, request,
                       extra={'link': link.pk, 'task': task.pk, 'task_number': task.task_number,
                              'count_session': session.pk, 'assigned_to': assignee.pk if assignee else None,
                              'items': items})
                out['created'].append(link)
    return out


def _num(v):
    return None if v is None else str(v)


def on_count_closed(session, by=None, request=None):
    """Close every open finding link on this (just closed) count session. Returns links closed."""
    from apps.tasks.views import _add_system_message, _log_audit
    links = list(session.audit_finding_tasks.filter(status=StockAuditFindingTask.ST_OPEN)
                 .select_related('finding', 'task'))
    if not links:
        return 0
    snaps = {s.item_code: s for s in session.snapshots.all()}
    now = timezone.now()
    who = by.full_name if by else 'النظام'
    for link in links:
        result, matched = {}, True
        for code in link.item_codes:
            s = snaps.get(code)
            if s is None or s.counted_qty is None:
                result[code] = {'expected': _num(s.expected_qty) if s else None, 'counted': None,
                                'difference': None, 'variance_type': 'not_counted'}
                matched = False
                continue
            result[code] = {'expected': _num(s.expected_qty), 'counted': _num(s.counted_qty),
                            'difference': _num(s.difference), 'variance_type': s.variance_type}
            matched = matched and s.variance_type == 'ok'
        link.result = result
        link.outcome = link.OUT_MATCH if matched else link.OUT_VARIANCE
        link.status, link.closed_at = link.ST_CLOSED, now
        link.save(update_fields=['result', 'outcome', 'status', 'closed_at'])

        f = StockAuditFinding.objects.select_for_update().get(pk=link.finding_id)
        old = f.status
        stamp = f'[{timezone.localtime(now):%Y-%m-%d %H:%M} {who}]'
        if matched:
            line = f'{stamp} الجرد المستهدف #{session.pk} مطابق — تُقفل الملاحظة'
            if f.status in REVIEWABLE:
                f.status, f.reviewed_by, f.reviewed_at = StockAuditFinding.ST_REVIEWED, by, now
        else:
            diffs = '، '.join(f'{c}: {r["difference"] if r["counted"] is not None else "لم يُجرد"}'
                              for c, r in result.items() if r['variance_type'] != 'ok')
            line = f'{stamp} الجرد المستهدف #{session.pk} به فروق — تبقى الملاحظة مفتوحة ({diffs})'
        f.review_note = f'{f.review_note}\n{line}'.strip()
        f.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_note'])

        task = link.task
        if task is not None and task.status not in TASK_DONE:
            old_task = task.status
            task.status, task.completed_at, task.completed_by = 'completed', now, by
            task.completion_notes = ('الجرد مطابق' if matched else 'الجرد به فروق — الملاحظة مفتوحة للمتابعة')
            task.save(update_fields=['status', 'completed_at', 'completed_by', 'completion_notes', 'updated_at'])
            _log_audit(task, 'completed', by, field_name='status', old_value=old_task, new_value='completed',
                       extra={'count_session': session.pk, 'outcome': link.outcome})
            _add_system_message(task, f'أُغلقت جلسة الجرد #{session.pk}: {task.completion_notes}')
        _audit('stock_audit_finding_task_closed', f, by, request,
               changes={'status': [old, f.status]} if old != f.status else None,
               extra={'link': link.pk, 'task': link.task_id, 'count_session': session.pk,
                      'outcome': link.outcome, 'result': result})
    return len(links)


def link_json(link):
    if link is None:
        return None
    t = link.task
    return {'id': link.pk, 'status': link.status, 'outcome': link.outcome,
            'task_id': link.task_id, 'task_number': t.task_number if t else '',
            'task_status': t.status if t else '',
            'assigned_to': link.assigned_to.full_name if link.assigned_to_id else '',
            'count_session_id': link.count_session_id,
            'count_status': link.count_session.status if link.count_session_id else '',
            'item_codes': link.item_codes, 'created_at': link.created_at, 'closed_at': link.closed_at}


def latest_links(finding_ids):
    """{finding_id: newest link} for the grid (one query)."""
    out = {}
    for link in (StockAuditFindingTask.objects.filter(finding_id__in=list(finding_ids))
                 .select_related('task', 'count_session', 'assigned_to').order_by('finding_id', '-created_at')):
        out.setdefault(link.finding_id, link)
    return out
