"""
apps/data_lifecycle/runner.py

Previews and really runs the rules of register.py. Called once a day from
apps.sync.maintenance.run_daily_retention, inside its lock; the only other way in is
`manage.py lifecycle preview`, which changes nothing.

What a daily run does depends on policy.get_mode: `off` nothing, `preview` writes a preview line (so
previews stay fresh), `on` removes. p56 rules are listed in the register only and never run here.

Circuit breaker, per rule: a real run stops when its candidates exceed
    min(ceiling, 1.5 × unconsumed preview count + margin)
Every real line consumes the preview before it, stopped or failed ones included. So a large first
cleanup needs its own preview, every later day is held to the margin (the rule's normal volume), and
after a stop a person has to preview again before the rule can pass.

File rules: one reference index per run, split by references.partition, so a preview counts exactly what a real
run would move and a file used by anything else never moves. If too many referenced files are missing from disk
the folder is probably wrong, so every file rule stops for the run and admins get one alert. hold_file refuses to
run inside a transaction, so nothing here may wrap a rule in one.

Company-level by nature, no branch scoping; see models.py. No SOFTECH reads or writes.
"""
import logging
import traceback

from django.db import connection
from django.db.models import Max
from django.utils import timezone

from apps.sync.maintenance import _alert_admins, _batched_delete
from core.errors import redact

from . import holding
from .models import MODE_OFF, MODE_ON, MODE_PREVIEW, LifecycleRun, LifecycleRunLine, TableSizeSnapshot
from .policy import get_mode
from .references import build_reference_index, partition
from .register import KIND_FILE, KIND_P56, RULES
from .rules_files import missing_references, too_many_missing

logger = logging.getLogger('elrezeiky.sync')

ERROR_MAX = 1000
TABLE_SIZE_MIN_BYTES = 20 * 1024 * 1024


class FileRulesStopped(Exception):
    """Too many referenced files are missing from disk. The message holds counts only and is safe to show."""


class _FileRun:
    """What the file rules of one run share: one reference index and one check of the media folder."""

    def __init__(self):
        self._index = None
        self._stopped = None

    def index(self):
        if self._stopped:
            raise FileRulesStopped(self._stopped)
        if self._index is None:
            index = build_reference_index()
            missing, total = missing_references(index)
            if too_many_missing(missing, total):
                self._stopped = f'توقفت قواعد الملفات: {missing:,} من {total:,} ملف مستخدم غير موجود على القرص.'
                _alert_wrong_folder(missing, total)
                raise FileRulesStopped(self._stopped)
            self._index = index
        return self._index


def _alert_wrong_folder(missing, total):
    logger.error('[lifecycle] file rules stopped: %s of %s referenced files are missing from disk', missing, total)
    _alert_admins('🔴 توقفت قواعد الملفات',
                  f'{missing:,} من {total:,} ملف تشير إليه السجلات غير موجود في مجلد الملفات، وقد يكون المجلد خطأ أو '
                  f'الاسترجاع غير مكتمل. لم يُنقل أي ملف في هذا التشغيل. راجع MEDIA_ROOT.',
                  f'lifecycle_wrong_folder_{timezone.localdate().isoformat()}')


def file_candidate_size(candidate):
    """Bytes of one file candidate."""
    return candidate.size


def _candidate_id(candidate):
    """Which candidate, for a log or an error: a record id. Never the path, which is a file name."""
    if not candidate.rows:
        return 'a file with no record'
    first = candidate.rows[0]
    return f'{first.model}#{first.pk}.{first.field}'


def move_file_candidates(rule, candidates, line):
    """Move a `file` rule's movable candidates to the holding folder and return how many moved. A file that fails
    is logged and put on the line's error by id, and the rule carries on with the next. A FileStranded has already
    written its critical log line. Adds the bytes moved to the line; the caller saves it."""
    moved, failures = 0, []
    for candidate in candidates:
        try:
            holding.hold_file(candidate.path, [row._asdict() for row in candidate.rows], rule.key)
        except holding.HoldError as exc:
            failure = f'{_candidate_id(candidate)}: {type(exc).__name__}'
            logger.error('[lifecycle] %s: %s', rule.key, failure)
            failures.append(failure)
        else:
            moved += 1
            line.bytes += file_candidate_size(candidate)
    if failures:
        line.error = redact(f'{len(failures)} لم تُنقل: ' + '; '.join(failures))[:ERROR_MAX]
    return moved


def snapshot_table_sizes(min_bytes=TABLE_SIZE_MIN_BYTES):
    """The retention:table_sizes step. One TableSizeSnapshot row per table of the current schema that is at least
    min_bytes (20 MB), so growth history exists before the data health screen. Returns the rows written.
    Reads PostgreSQL's catalog only; it never raises, because a missing size row must not fail the daily run."""
    try:
        with connection.cursor() as cur:
            cur.execute(
                """SELECT c.relname, pg_total_relation_size(c.oid), pg_relation_size(c.oid),
                          pg_indexes_size(c.oid), GREATEST(c.reltuples, 0)::bigint
                   FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE c.relkind = 'r' AND n.nspname = current_schema()
                     AND pg_total_relation_size(c.oid) >= %s
                   ORDER BY 1""", [min_bytes])
            rows = cur.fetchall()
        now = timezone.now()
        TableSizeSnapshot.objects.bulk_create([
            TableSizeSnapshot(taken_at=now, table=name, total_bytes=total, heap_bytes=heap,
                              index_bytes=index, row_estimate=estimate)
            for name, total, heap, index, estimate in rows])
        return len(rows)
    except Exception:
        logger.exception('[lifecycle] table size snapshot failed')
        return 0


def purge_held_files():
    """The retention:purge_held step."""
    return holding.purge_expired()


def _measure(rule, candidates):
    """(count, bytes) of a rule's candidates, without changing anything."""
    if rule.kind == KIND_FILE:
        return len(candidates), sum(file_candidate_size(c) for c in candidates)
    return sum(qs.count() for qs in candidates), 0


def _unconsumed_preview_count(key):
    """The count of the latest good preview, if no real line of this rule came after it. Otherwise 0."""
    lines = LifecycleRunLine.objects.filter(rule_key=key)
    last_real = lines.filter(is_preview=False).aggregate(last=Max('pk'))['last'] or 0
    return (lines.filter(is_preview=True, error='', run__finished_at__isnull=False, pk__gt=last_real)
            .order_by('-pk').values_list('count', flat=True).first()) or 0


def breaker_limit(rule):
    """The most a real run of this rule may remove right now."""
    return min(rule.ceiling, _unconsumed_preview_count(rule.key) * 3 // 2 + rule.margin)


def _error_text(key, exc):
    logger.error('[lifecycle] %s failed: %s', key, redact(traceback.format_exc()))
    return redact(f'{type(exc).__name__}: {exc}')[:ERROR_MAX]


def _alert_breaker(rule, count, limit):
    logger.warning('[lifecycle] %s stopped by the circuit breaker: %s candidates, limit %s', rule.key, count, limit)
    _alert_admins(f'🟠 توقفت قاعدة «{rule.label_ar}»',
                  f'كانت قاعدة «{rule.label_ar}» ستحذف {count:,} والحد المسموح {limit:,}، فتوقفت ولم تحذف شيئًا. '
                  f'القواعد الأخرى استمرت. راجع السبب ثم شغّل معاينة جديدة حتى تعمل القاعدة مرة أخرى.',
                  f'lifecycle_breaker_{rule.key}_{timezone.localdate().isoformat()}')


def _removed_count(value):
    """What `apply` or the file hook reported. The removal has already happened by now, so a wrong type must
    become an error on the rule's line, not a failed save that leaves no record of the run."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f'expected the count removed as an integer, got {type(value).__name__}; '
                        f'the removal may already have happened')
    return value


def _select_files(rule, files, refresh):
    """(movable, skipped because something else uses them)."""
    index = files.index()
    if refresh and rule.refresh is not None:
        rule.refresh(index)
    return partition(rule.candidates(), index)


def _preview_line(run, rule, files, refresh=False):
    line = LifecycleRunLine(run=run, rule_key=rule.key, is_preview=True)
    try:
        if rule.kind == KIND_FILE:
            movable, skipped = _select_files(rule, files, refresh)
            line.skipped_shared = len(skipped)
            line.count, line.bytes = _measure(rule, movable)
        else:
            line.count, line.bytes = _measure(rule, rule.candidates())
    except FileRulesStopped as exc:
        line.error = str(exc)
    except Exception as exc:
        line.error = _error_text(rule.key, exc)
    line.save()
    return line


def _real_line(run, rule, files):
    """`count` is what was actually removed. Rows are deleted in committed batches, so when a delete fails
    part way the batches already done in that queryset are gone but not counted; the error is on the line."""
    line = LifecycleRunLine(run=run, rule_key=rule.key)
    try:
        if rule.kind == KIND_FILE:
            candidates, skipped = _select_files(rule, files, refresh=True)
            line.skipped_shared = len(skipped)
        else:
            candidates = rule.candidates()
        count, _ = _measure(rule, candidates)
        limit = breaker_limit(rule)
        if count > limit:
            line.stopped_by_breaker = True
            _alert_breaker(rule, count, limit)
        elif rule.apply is not None:
            line.count = _removed_count(rule.apply())
        elif rule.kind == KIND_FILE:
            line.count = _removed_count(move_file_candidates(rule, candidates, line))
        else:
            for qs in candidates:
                line.count += _batched_delete(qs)
    except FileRulesStopped as exc:
        line.error = str(exc)
    except Exception as exc:
        line.error = _error_text(rule.key, exc)
    line.save()
    return line


def _finish(run):
    run.finished_at = timezone.now()
    run.save(update_fields=['finished_at'])


def preview_rule(key):
    """Preview one rule, whatever its mode. Changes nothing but its own run and line. A failure of the rule
    is on the returned line; an unknown or p56 rule raises ValueError. The "first seen" clocks are not
    touched: they only move in a daily run."""
    rule = RULES.get(key)
    if rule is None or rule.kind == KIND_P56:
        raise ValueError(f'لا يمكن معاينة القاعدة «{key}».')
    run = LifecycleRun.objects.create(is_preview=True)
    line = _preview_line(run, rule, _FileRun())
    _finish(run)
    return line


def run_lifecycle_rules():
    """One daily pass over every rule. A rule's failure goes on its line and the others still run. If even
    the line cannot be written or the mode read, that rule is only logged. Returns the total removed."""
    run = LifecycleRun.objects.create(is_preview=False)
    files = _FileRun()
    total = 0
    for key, rule in RULES.items():
        if rule.kind == KIND_P56:
            continue
        try:
            mode = get_mode(key)
            if mode == MODE_OFF:
                continue
            if mode == MODE_PREVIEW:
                _preview_line(run, rule, files, refresh=True)
            elif mode == MODE_ON:       # any other stored value does nothing
                total += _real_line(run, rule, files).count
        except Exception as exc:
            _error_text(key, exc)
    _finish(run)
    return total
