"""
Pre-enforce checklist for the zone policy (N3): what would break the day
NETWORK_POLICY_ENFORCEMENT is switched to `enforce`. Read-only; never writes anything.

Each item is (level, code, Arabic, English). level is 'block' (enforce must wait), 'warn' (look at
it) or 'ok'. `run()` returns the list; the management command prints it and exits 1 on a block.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

BLOCK, WARN, OK = 'block', 'warn', 'ok'
ZONES = ('Z1', 'Z2', 'Z3', 'Z4')
RECENT_DAYS = 7          # "recent" traffic / pending devices
ADMIN_DEVICE_DAYS = 30   # an admin device counts when used within this window
MAX_NAMES = 15


@dataclass
class Item:
    level: str
    code: str
    ar: str
    en: str
    names: list = field(default_factory=list)


def _names(rows):
    rows = list(rows)
    shown = rows[:MAX_NAMES]
    if len(rows) > MAX_NAMES:
        shown.append(f'… +{len(rows) - MAX_NAMES}')
    return shown


def _who(profile):
    return profile.full_name or profile.user.username


def check_settings():
    out = []
    trusted = bool(getattr(settings, 'NETWORK_HEADER_TRUSTED', False))
    key = bool(getattr(settings, 'NETWORK_PROXY_KEY', ''))
    if trusted:
        out.append(Item(OK, 'header', 'لافتة الشبكة من nginx معتمدة (NETWORK_HEADER_TRUSTED)',
                        'The nginx network label is trusted (NETWORK_HEADER_TRUSTED)'))
    else:
        out.append(Item(BLOCK, 'header', 'NETWORK_HEADER_TRUSTED غير مفعّل — لا يمكن تمييز داخل الشبكة من خارجها',
                        'NETWORK_HEADER_TRUSTED is off — inside and outside cannot be told apart'))
    if key:
        out.append(Item(OK, 'proxy_key', 'مفتاح nginx مضبوط (NETWORK_PROXY_KEY)', 'The nginx key is set (NETWORK_PROXY_KEY)'))
    else:
        out.append(Item(BLOCK, 'proxy_key', 'NETWORK_PROXY_KEY فارغ — أي برنامج على السيرفر يقدر يدّعي إنه داخل الشبكة',
                        'NETWORK_PROXY_KEY is empty — anything on the server could claim to be inside'))
    return out


def check_internal_traffic(now):
    """Split DNS live: recent sign-ins labelled internal, overall and per selling branch."""
    from apps.branches.models import Branch
    from apps.users.models import UserActivityLog
    since = now - timedelta(days=RECENT_DAYS)
    logins = UserActivityLog.objects.filter(action__in=('login_success', 'mfa_verified'), created_at__gte=since)
    internal = logins.filter(network='internal')
    if not internal.exists():
        return [Item(BLOCK, 'internal_traffic',
                     f'لا يوجد أي دخول «داخل الشبكة» آخر {RECENT_DAYS} أيام — الـ split DNS / النفق غير شغال بعد',
                     f'No sign-in labelled "internal" in the last {RECENT_DAYS} days — split DNS / the tunnel is not live yet')]
    out = [Item(OK, 'internal_traffic', f'دخول داخل الشبكة آخر {RECENT_DAYS} أيام: {internal.count()}',
                f'Internal sign-ins in the last {RECENT_DAYS} days: {internal.count()}')]
    seen = set(internal.exclude(target_user__branch_id=None).values_list('target_user__branch_id', flat=True))
    staffed = set(_selling_staff().exclude(branch_id=None).values_list('branch_id', flat=True))
    quiet = Branch.objects.filter(pk__in=staffed - seen).exclude(kind=Branch.KIND_CLOSED).order_by('name')
    if quiet:
        out.append(Item(WARN, 'internal_by_branch',
                        'فروع بدون أي دخول «داخل الشبكة» — افتح شارة الشبكة من جهاز في الفرع وتأكد إنها «داخل الشبكة»',
                        'Branches with no "internal" sign-in — open the network badge on a branch PC and check it says inside',
                        _names(b.name_ar or b.name for b in quiet)))
    return out


def _selling_staff():
    from apps.users.models import StaffProfile
    return StaffProfile.objects.filter(is_active=True, user__is_active=True,
                                       role__in=('pharmacist', 'salesperson'))


def check_rows():
    """Every role has its four rows; the admin keeps full access inside on an approved device."""
    from apps.access.models import ZonePolicy
    from apps.users.models import ROLE_CHOICES
    have = {}
    for role, zone in ZonePolicy.objects.values_list('role', 'zone'):
        have.setdefault(role, set()).add(zone)
    missing = [f'{role}: {", ".join(z for z in ZONES if z not in have.get(role, set()))}'
               for role, _ in ROLE_CHOICES if have.get(role, set()) != set(ZONES)]
    out = []
    if missing:
        out.append(Item(WARN, 'rows', 'أدوار ناقصها صفوف في «سياسة الشبكات» — من خارج الشبكة هتتمنع، ومن الداخل مفتوحة',
                        'Roles missing rows on the zone policy — blocked outside, open inside', missing))
    admin_z1 = ZonePolicy.objects.filter(role='admin', zone='Z1').first()
    if admin_z1 is None or admin_z1.access != 'full' or admin_z1.view_only:
        out.append(Item(BLOCK, 'admin_z1', 'صف المدير «داخل الشبكة — جهاز معتمد» لازم يفضل «كامل»',
                        'The admin row "inside, approved device" must stay full'))
    return out


def check_mfa():
    """Everyone whose role must use 2FA from outside (require_mfa on a Z3 / Z4 row with access)
    has enrolled — first enrolment at sign-in is refused from outside once enforced."""
    from apps.access.models import ZonePolicy
    from apps.users.models import StaffProfile
    roles = set(ZonePolicy.objects.filter(zone__in=('Z3', 'Z4'), require_mfa=True)
                .exclude(access='none').values_list('role', flat=True))
    pending = (StaffProfile.objects.filter(is_active=True, user__is_active=True, role__in=roles, mfa_enabled=False)
               .select_related('user').order_by('role', 'user__username'))
    riders = [p for p in pending if p.role == 'delivery']
    others = [p for p in pending if p.role != 'delivery']
    out = []
    if riders:
        out.append(Item(BLOCK, 'mfa_riders',
                        'طيارين بدون مصادقة ثنائية — يفعّلوها من «أمان الحساب» في شاشة الطيار وهم داخل الفرع',
                        'Riders without two-factor — they enrol from «أمان الحساب» on the rider screen while at a branch',
                        _names(_who(p) for p in riders)))
    if others:
        out.append(Item(BLOCK, 'mfa_users',
                        'مستخدمين مسموح لهم من خارج الشبكة بدون مصادقة ثنائية — يفعّلوها من «أمان الحساب» وهم داخل الشبكة',
                        'Users allowed outside the network without two-factor — they enrol from «أمان الحساب» while inside',
                        _names(f'{_who(p)} ({p.role})' for p in others)))
    if not pending:
        out.append(Item(OK, 'mfa', 'كل من يدخل من خارج الشبكة مفعّل المصادقة الثنائية',
                        'Everyone who may sign in from outside has two-factor on'))
    return out


def check_devices(now):
    """Selling branches have an approved PC; admins have two approved devices; no fresh pending queue."""
    from apps.access.models import Device, DeviceUser
    from apps.branches.models import Branch
    out = []
    used_since = now - timedelta(days=ADMIN_DEVICE_DAYS)
    by_link = set(DeviceUser.objects.filter(device__status='approved', last_seen__gte=used_since,
                                            user__is_active=True).exclude(user__branch_id=None)
                  .values_list('user__branch_id', flat=True))
    by_branch = set(Device.objects.filter(status='approved').exclude(branch_id=None)
                    .values_list('branch_id', flat=True))
    staffed = set(_selling_staff().exclude(branch_id=None).values_list('branch_id', flat=True))
    bare = Branch.objects.filter(pk__in=staffed - by_link - by_branch).exclude(kind=Branch.KIND_CLOSED).order_by('name')
    if bare:
        out.append(Item(BLOCK, 'branch_devices',
                        'فروع بدون أي جهاز معتمد — بعد التفعيل الكاشير على جهاز غير معتمد يقدر يعرض بس ومايبيعش',
                        'Branches with no approved device — after the switch a cashier on an unapproved PC can only look, not sell',
                        _names(b.name_ar or b.name for b in bare)))
    else:
        out.append(Item(OK, 'branch_devices', 'كل فرع فيه جهاز معتمد واحد على الأقل',
                        'Every selling branch has at least one approved device'))
    admin_devices = (Device.objects.filter(status='approved', device_users__user__role='admin',
                                           device_users__user__is_active=True,
                                           device_users__last_seen__gte=used_since).distinct().count())
    if admin_devices == 0:
        out.append(Item(BLOCK, 'admin_devices', 'لا يوجد جهاز معتمد مستخدم من مدير — لن يستطيع أحد اعتماد الأجهزة',
                        'No approved device used by an admin — nobody could approve devices'))
    elif admin_devices < 2:
        out.append(Item(WARN, 'admin_devices', 'جهاز معتمد واحد فقط للمديرين — اعتمد جهازاً ثانياً احتياطياً',
                        'Only one approved admin device — approve a second one as a spare'))
    else:
        out.append(Item(OK, 'admin_devices', f'أجهزة المديرين المعتمدة: {admin_devices}',
                        f'Approved admin devices: {admin_devices}'))
    pending = Device.objects.filter(status='pending', last_seen__gte=now - timedelta(days=RECENT_DAYS)).count()
    if pending:
        out.append(Item(WARN, 'pending_devices',
                        f'{pending} جهاز في الانتظار ظهر آخر {RECENT_DAYS} أيام — اعتمد أجهزة الفروع قبل التفعيل',
                        f'{pending} pending devices seen in the last {RECENT_DAYS} days — approve branch PCs before the switch'))
    return out


def check_softech(now):
    """N4: what the SOFTECH gate logged in the last RECENT_DAYS (rows `softech_gate_denied`).
    A `no_context` row means a screen opens SOFTECH from a thread or path without a request
    context, which breaks the moment SOFTECH_GATE_ENFORCEMENT is `enforce`."""
    from collections import Counter

    from django.conf import settings as dj
    from django.db.models import Count

    from apps.audit.models import AuditLog
    from . import softech_gate
    # grouped in the database: cost is the number of distinct combinations, not of rows
    rows = (AuditLog.objects.filter(action=softech_gate.AUDIT_ACTION,
                                    created_at__gte=now - timedelta(days=RECENT_DAYS))
            .order_by()
            .values('user_role', 'extra__reason', 'extra__zone', 'extra__scope', 'extra__label',
                    'extra__sql_first', 'extra__write_word')
            .annotate(n=Count('id')))
    out = []
    no_ctx = Counter()
    would = Counter()
    for r in rows:
        reason = r['extra__reason']
        if reason == 'no_context':
            no_ctx[f"{r['extra__scope']} / {r['extra__label'] or '-'}"] += r['n']
        else:
            # M10: a write observation carries its first keyword and the write word it matched
            # (SELECT / LOAD is a read with an odd identifier, UPDATE / UPDATE a real write)
            sig = (f" [{r['extra__sql_first']} / {r['extra__write_word']}]"
                   if r.get('extra__sql_first') else '')
            would[f"{r['user_role'] or '?'} × {r['extra__zone'] or '-'} × {reason}{sig}"] += r['n']
    if no_ctx:
        out.append(Item(BLOCK, 'softech_no_context',
                        'شاشة تفتح SOFTECH من خيط أو مسار بلا سياق طلب — ستنكسر عند التطبيق الفعلي لبوابة SOFTECH',
                        'A screen opens SOFTECH from a thread or path with no request context — it would break once the SOFTECH gate enforces',
                        _names(f'{k}: {n}' for k, n in no_ctx.most_common())))
    if would:
        out.append(Item(WARN, 'softech_would_deny',
                        f'بوابة SOFTECH كانت سترفض (آخر {RECENT_DAYS} أيام) — راجع الدور × المنطقة × السبب',
                        f'The SOFTECH gate would have refused (last {RECENT_DAYS} days) — review role × zone × reason',
                        _names(f'{k}: {n}' for k, n in would.most_common())))
    current = softech_gate.mode()
    configured = str(getattr(dj, 'SOFTECH_GATE_ENFORCEMENT', 'log') or 'log').lower()
    if current == 'enforce':
        out.append(Item(OK, 'softech_mode', 'بوابة SOFTECH: التطبيق الفعلي (enforce)', 'SOFTECH gate: enforce'))
    elif configured == 'enforce':
        out.append(Item(WARN, 'softech_mode',
                        'بوابة SOFTECH مضبوطة enforce لكنها تعمل كتسجيل فقط — الإعداد غير آمن (راجع سجل الأخطاء)',
                        'SOFTECH gate is set to enforce but runs as log — unsafe setup (see the error log)'))
    else:
        out.append(Item(WARN, 'softech_mode', f'بوابة SOFTECH في وضع {current} — لا ترفض شيئاً بعد',
                        f'SOFTECH gate mode is {current} — nothing is refused yet'))
    return out


def check_bulk_read():
    out = []
    from . import bulk_read
    bulk = bulk_read.mode()
    if bulk == 'enforce':
        out.append(Item(OK, 'bulk_read_mode', 'حماية قراءة البيانات الكبيرة: التطبيق الفعلي (enforce)',
                        'Bulk-read guard: enforce'))
    else:
        out.append(Item(WARN, 'bulk_read_mode', f'حماية قراءة البيانات الكبيرة في وضع {bulk} — لا توقف أحداً بعد',
                        f'Bulk-read guard mode is {bulk} — nobody is blocked yet'))
    return out


def check_public_api():
    from .public_middleware import mode
    current = mode()
    if current == 'enforce':
        return [Item(OK, 'public_api_mode', 'بوابة المسارات العامة: التطبيق الفعلي (enforce)',
                     'Public-API gate: enforce')]
    return [Item(WARN, 'public_api_mode', f'بوابة المسارات العامة في وضع {current} — لا ترفض أحداً بعد',
                 f'Public-API gate mode is {current} — nobody is refused yet')]


def run(now=None):
    now = now or timezone.now()
    items = []
    items += check_settings()
    items += check_bulk_read()
    items += check_public_api()
    items += check_internal_traffic(now)
    items += check_rows()
    items += check_mfa()
    items += check_devices(now)
    items += check_softech(now)
    return items


def blockers(items):
    return [i for i in items if i.level == BLOCK]
