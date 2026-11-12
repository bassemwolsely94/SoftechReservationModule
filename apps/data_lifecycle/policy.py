"""
apps/data_lifecycle/policy.py

Reads and changes a rule's mode and period. The refusals here hold for everyone, admins included:
a period below the minimum, `on` without a fresh preview, a file rule `on` off the VPS, any change to a
P-56 step. Who may call set_policy is the caller's check (server-side, admin only; design §7).

Company-level by nature, no branch scoping; see models.py. No SOFTECH reads or writes.
"""
import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog

from .models import MODE_CHOICES, MODE_ON, MODE_PREVIEW, LifecycleRulePolicy, LifecycleRunLine
from .register import KIND_FILE, KIND_P56, RULES

PREVIEW_MAX_AGE_DAYS = 7
AUDIT_ACTION = 'lifecycle_policy_changed'
AUDIT_NOTE_MAX = 255     # AuditLog.note; the full reason goes in `extra`


class PolicyRefused(Exception):
    """The change is not allowed. The message is Arabic and safe to show."""


def get_mode(key):
    """The mode a run must obey: `off`, `preview` or `on`. P-56 steps are always on. A stored `on` reads
    as `preview` while file rules are locked, so a database restored onto another machine moves nothing."""
    rule = RULES[key]
    if rule.kind == KIND_P56:
        return MODE_ON
    mode = LifecycleRulePolicy.objects.filter(rule_key=key).values_list('mode', flat=True).first() or MODE_PREVIEW
    if mode == MODE_ON and rule.kind == KIND_FILE and not settings.LIFECYCLE_FILE_RULES_ENABLED:
        return MODE_PREVIEW
    return mode


def minimum_days(rule):
    """The lowest period allowed: the floor, or the default when the rule has none (design §4: admins can
    only lengthen a period). None for a rule that does not keep by days."""
    return rule.floor_days if rule.floor_days is not None else rule.default_days


def _effective_days(rule, override):
    if override is None or rule.default_days is None:
        return rule.default_days
    return max(override, minimum_days(rule))    # a floor raised in code beats an older stored override


def keep_days(key):
    """The period in days. None only for a rule that does not keep by days (rate_runs, p56_engine)."""
    rule = RULES[key]
    override = LifecycleRulePolicy.objects.filter(rule_key=key).values_list('keep_days_override', flat=True).first()
    return _effective_days(rule, override)


def has_fresh_preview(key, now=None):
    """A finished preview of this rule, with no error, under PREVIEW_MAX_AGE_DAYS old."""
    cutoff = (now or timezone.now()) - datetime.timedelta(days=PREVIEW_MAX_AGE_DAYS)
    return LifecycleRunLine.objects.filter(rule_key=key, is_preview=True, error='',
                                           run__finished_at__gt=cutoff).exists()


def _check_mode(key, rule, mode):
    if mode not in dict(MODE_CHOICES):
        raise PolicyRefused('الوضع غير معروف.')
    if mode != MODE_ON:
        return
    if rule.kind == KIND_FILE and not settings.LIFECYCLE_FILE_RULES_ENABLED:
        raise PolicyRefused('قواعد الملفات تبقى في وضع المعاينة حتى الانتقال إلى السيرفر.')
    if not has_fresh_preview(key):
        raise PolicyRefused(f'التشغيل يحتاج معاينة ناجحة عمرها أقل من {PREVIEW_MAX_AGE_DAYS} أيام.')


def _check_days(rule, days):
    if rule.default_days is None:
        raise PolicyRefused('هذه القاعدة لا تحتفظ بالبيانات بعدد أيام، فلا يمكن تعديل مدتها.')
    if not isinstance(days, int) or isinstance(days, bool):
        raise PolicyRefused('مدة الاحتفاظ يجب أن تكون عددًا صحيحًا من الأيام.')
    minimum = minimum_days(rule)
    if days < minimum:
        raise PolicyRefused(f'لا يمكن أن تقل مدة الاحتفاظ لهذه القاعدة عن {minimum} يومًا.')


def set_policy(key, *, mode=None, keep_days=None, user, reason):
    """Change a rule's mode and/or period and write AuditLog with before, after and the reason.
    The policy row and its audit row are saved together or not at all. Raises PolicyRefused."""
    rule = RULES.get(key)
    if rule is None:
        raise PolicyRefused('القاعدة غير معروفة.')
    if rule.kind == KIND_P56:
        raise PolicyRefused('هذه خطوة قائمة في الصيانة اليومية وتعمل دائمًا، ولا يمكن تعديلها من هنا.')
    reason = (reason or '').strip()
    if not reason:
        raise PolicyRefused('يجب كتابة سبب التعديل.')
    if user is None:
        raise PolicyRefused('يجب تحديد المستخدم الذي يقوم بالتعديل.')
    if mode is None and keep_days is None:
        raise PolicyRefused('لا يوجد تعديل.')
    if mode is not None:
        _check_mode(key, rule, mode)
    if keep_days is not None:
        _check_days(rule, keep_days)

    with transaction.atomic():
        policy = (LifecycleRulePolicy.objects.select_for_update().filter(rule_key=key).first()
                  or LifecycleRulePolicy(rule_key=key))
        before = {'mode': policy.mode, 'keep_days': _effective_days(rule, policy.keep_days_override)}
        if mode is not None:
            policy.mode = mode
        if keep_days is not None:
            policy.keep_days_override = keep_days
        policy.changed_by = user
        policy.reason = reason
        policy.save()
        after = {'mode': policy.mode, 'keep_days': _effective_days(rule, policy.keep_days_override)}
        # AuditLog.log returns None instead of raising; rule 8 says no unaudited change may stick.
        if AuditLog.log(AUDIT_ACTION, user=user, obj=policy, old_data=before, new_data=after,
                        extra={'rule_key': key, 'reason': reason}, note=reason[:AUDIT_NOTE_MAX]) is None:
            raise PolicyRefused('تعذر تسجيل التعديل في سجل المراجعة، فلم يُحفظ.')
    return policy
