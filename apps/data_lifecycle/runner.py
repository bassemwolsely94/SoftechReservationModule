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

Company-level by nature, no branch scoping; see models.py. No SOFTECH reads or writes.
"""
import logging
import traceback

from django.db.models import Max
from django.utils import timezone

from apps.sync.maintenance import _alert_admins, _batched_delete
from core.errors import redact

from .models import MODE_OFF, MODE_PREVIEW, LifecycleRun, LifecycleRunLine
from .policy import get_mode
from .register import KIND_FILE, KIND_P56, RULES

logger = logging.getLogger('elrezeiky.sync')

ERROR_MAX = 1000


def file_candidate_size(candidate):
    """Bytes of one file candidate. Task 9 of the Stage 3 plan supplies the candidates."""
    return candidate.size


def move_file_candidates(rule, candidates):
    """HOOK for Task 9: move a `file` rule's candidates to the holding folder and return how many moved.
    Moves nothing until then, even for a rule that is `on` with LIFECYCLE_FILE_RULES_ENABLED."""
    return 0


def purge_held_files():
    """The retention:purge_held step. Task 7 replaces this with the real purge."""
    return 0


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


def _preview_line(run, rule):
    line = LifecycleRunLine(run=run, rule_key=rule.key, is_preview=True)
    try:
        line.count, line.bytes = _measure(rule, rule.candidates())
    except Exception as exc:
        line.error = _error_text(rule.key, exc)
    line.save()
    return line


def _real_line(run, rule):
    """`count` is what was actually removed. Rows are deleted in committed batches, so when a delete fails
    part way the batches already done in that queryset are gone but not counted; the error is on the line."""
    line = LifecycleRunLine(run=run, rule_key=rule.key)
    try:
        candidates = rule.candidates()
        count, _ = _measure(rule, candidates)
        limit = breaker_limit(rule)
        if count > limit:
            line.stopped_by_breaker = True
            _alert_breaker(rule, count, limit)
        elif rule.apply is not None:
            line.count = _removed_count(rule.apply())
        elif rule.kind == KIND_FILE:
            line.count = _removed_count(move_file_candidates(rule, candidates))
        else:
            for qs in candidates:
                line.count += _batched_delete(qs)
    except Exception as exc:
        line.error = _error_text(rule.key, exc)
    line.save()
    return line


def _finish(run):
    run.finished_at = timezone.now()
    run.save(update_fields=['finished_at'])


def preview_rule(key):
    """Preview one rule, whatever its mode. Changes nothing but its own run and line. A failure of the rule
    is on the returned line; an unknown or p56 rule raises ValueError."""
    rule = RULES.get(key)
    if rule is None or rule.kind == KIND_P56:
        raise ValueError(f'لا يمكن معاينة القاعدة «{key}».')
    run = LifecycleRun.objects.create(is_preview=True)
    line = _preview_line(run, rule)
    _finish(run)
    return line


def run_lifecycle_rules():
    """One daily pass over every rule. A rule's failure goes on its line and the others still run. If even
    the line cannot be written or the mode read, that rule is only logged. Returns the total removed."""
    run = LifecycleRun.objects.create(is_preview=False)
    total = 0
    for key, rule in RULES.items():
        if rule.kind == KIND_P56:
            continue
        try:
            mode = get_mode(key)
            if mode == MODE_OFF:
                continue
            if mode == MODE_PREVIEW:
                _preview_line(run, rule)
            else:
                total += _real_line(run, rule).count
        except Exception as exc:
            _error_text(key, exc)
    _finish(run)
    return total
