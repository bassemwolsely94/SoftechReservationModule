"""
config/writers.py

P-54 (docs/product-review/06_SPEC_P-54): ONE instance writes to SOFTECH.

    writer_allowed('ISR_WRITER_ENABLED')  →  settings.WRITER_INSTANCE and settings.ISR_WRITER_ENABLED

Every SOFTECH writer gate reads its feature flag through writer_allowed() — never
directly — so the office development copy (WRITER_INSTANCE=False) can carry the
same .env flags as production and still never write (Rule 3: no double posting).
The driver-level kill-switch SOFTECH_READ_ONLY (config/sybase.py) stays the second,
independent lock.

run_startup_checks() runs in the web process (asgi / wsgi / runserver) and in
run_scheduler; it refuses to start on a duplicated .env key (python-decouple
silently keeps the last value) or on WRITER_INSTANCE + SOFTECH_READ_ONLY together,
and logs the instance role and the writer flags that are ON.
"""
import logging
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger('elrezeiky.writers')

# flag → what it protects (shown on /sync and in the signed-off switch table)
WRITER_FLAGS = {
    'ISR_WRITER_ENABLED':                  {'protects': 'طلبات التوريد ISR (stockisrm / stockisr)'},
    'SALES_RATE_WRITER_ENABLED':           {'protects': 'معدل البيع stkbal.monthlyqty'},
    'COVERAGE_WRITER_ENABLED':             {'protects': 'التغطية stkbal.maxnowqtymonths'},
    'COVERAGE_WRITE_MAXQTY':               {'protects': 'الحد الأقصى stkbal.maxnowqty'},
    'COVERAGE_AUTO_TOPUP_ENABLED':         {'protects': 'تحديث التغطية التلقائي بعد كل تشغيل للمحرك'},
    'DEMAND_ENGINE_SCHEDULE_ENABLED':      {'protects': 'تشغيل محرك الطلب المجدول'},
    'INVOICE_WRITER_ENABLED':              {'protects': 'ترحيل فواتير الشراء والكوبونات (stktransm / stktrans)'},
    'INVOICE_SUPPLIER_ITEM_WRITE_ENABLED': {'protects': 'أكواد الموردين itemssuppliers'},
    'SHORTAGE_SOFTECH_WRITE_ENABLED':      {'protects': 'علامات النواقص في items'},
    'AP_RECONCILE_WRITER_ENABLED':         {'protects': 'سداد الموردين (chequestrans / docvaluepay)'},
    'POS_OFFERS_EXECUTION_ENABLED':        {'protects': 'تنفيذ العروض على الطلبات'},
    'POS_OFFERS_POSDISCP_WRITE_ENABLED':   {'protects': 'خصم العروض posdiscp'},
    'POS_OFFERS_PROMO_WRITE_ENABLED':      {'protects': 'عروض الترويج في SOFTECH'},
    'CUSTOMER_BRANCH_COPY_WRITE_ENABLED':  {'protects': 'نسخ حالة العميل من الرئيسي للفروع'},
    'POINTS_REMOVAL_WRITE_ENABLED':        {'protects': 'استبعاد عميل من النقاط وتصفير رصيده'},
    'POS_WRITER_ENABLED':                  {'protects': 'نقطة البيع غير المباشرة (طلبات البيع)'},
    'POS_CANCEL_WRITE_ENABLED':            {'protects': 'سجل المبيعات غير المخزنة pos_cancel'},
    'PRICING_SOFTECH_WRITE_ENABLED':       {'protects': 'أسعار وخصومات وتصنيف الأصناف'},
    'REPLICATION_REPAIR_ENABLED':          {'protects': 'إعادة دفع الأصناف للفروع'},
    'LOYALTY_SOFTECH_WRITE_ENABLED':       {'protects': 'نقاط الشراء اليدوية picpoints'},
    'PERSONAL_COMMENT_WRITE_ENABLED':      {'protects': 'ملاحظات المستندات والشيكات'},
    'REPLACEMENT_POSTING_ENABLED':         {'protects': 'مستندات بدل الروشتة'},
    'INSURANCE_SOFTECH_WRITE_ENABLED':     {'protects': 'إعادة تسعير مطالبات التأمين'},
    'CUSTOMER_MERGE_WRITE_ENABLED':        {'protects': 'دمج أكواد العملاء المكررة'},
}

# Scheduled jobs that call a writer service: not registered on a non-writer instance.
WRITER_JOBS = ('pos_orders_flush', 'pos_cancel_write', 'coverage_topup', 'demand_engine_scheduled')


def writer_instance() -> bool:
    return bool(getattr(settings, 'WRITER_INSTANCE', False))


def writer_allowed(flag: str) -> bool:
    """True only on the writer instance AND with the feature flag on."""
    if flag not in WRITER_FLAGS:
        raise KeyError(f'{flag} is not a registered SOFTECH writer flag (config/writers.py)')
    return writer_instance() and bool(getattr(settings, flag, False))


def flags_on():
    return [f for f in WRITER_FLAGS if getattr(settings, f, False)]


_ENV_LINE = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=')


def duplicate_env_keys(path):
    """[(key, first_line, repeat_line), …] for every key set more than once."""
    seen, dups = {}, []
    try:
        lines = Path(path).read_text(encoding='utf-8-sig').splitlines()
    except OSError:
        return []
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith('#'):
            continue
        m = _ENV_LINE.match(line)
        if not m:
            continue
        key = m.group(1)
        if key in seen:
            dups.append((key, seen[key], n))
        else:
            seen[key] = n
    return dups


def default_env_path():
    return Path(settings.BASE_DIR) / '.env'


def run_startup_checks(env_path=None):
    import sys
    if env_path is None and len(sys.argv) > 1 and sys.argv[1] == 'test':
        return   # the test runner imports config.asgi; the developer's .env is not under test
    path = env_path or default_env_path()
    dups = duplicate_env_keys(path)
    if dups:
        listed = '; '.join(f'{k} (lines {a} and {b})' for k, a, b in dups)
        raise ImproperlyConfigured(
            f'{path}: duplicated key(s) — {listed}. Only the last value would be used, silently. '
            f'Remove the duplicates, then start again.')
    if writer_instance() and getattr(settings, 'SOFTECH_READ_ONLY', False):
        raise ImproperlyConfigured(
            'WRITER_INSTANCE=True together with SOFTECH_READ_ONLY=True is contradictory: the writer '
            'instance could not write. Set one of them to False.')
    on = flags_on()
    logger.info('[writers] WRITER_INSTANCE=%s SOFTECH_READ_ONLY=%s — %s',
                writer_instance(), bool(getattr(settings, 'SOFTECH_READ_ONLY', False)),
                (f'writer flags ON: {", ".join(on)}' if on else 'no writer flags ON')
                + ('' if writer_instance() else ' (not the writer instance — none of them can write)'))
