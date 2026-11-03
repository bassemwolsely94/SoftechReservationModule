"""
apps/pic_analytics/queries/numbers.py — the «أرقام جديدة» tab (doc 33 §8). Management only.

New numbers = customer calls (transfer legs excluded, agent filter ignored) in range whose number
matches NO PIC (pic_match='none'; 'no_number' and shared numbers are not leads) and that carry no
PhoneLabel. Unlinked numbers stay masked, same as the missed-calls tab.
kind: CdrCall.phone_key is the national number (apps/pbx/cdr.py), so a mobile is '01[0125]xxxxxxxx'
(older 10-digit '1…' keys are still read as mobile); everything else is a landline.
Conversion: a number «became a PIC» when its PIC (now on CdrCall.pic) was created
(Customer.softech_created_at, a date; null = skipped) inside the period AND the number had a call
dated (Cairo) before that date; «bought» = a PicDayFact visit for that PIC on/after it.
"""
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.customers import access as cust_access
from apps.customers.models import Customer
from apps.pbx.models import AgentExtension, CdrCall
from apps.pic_analytics.models import PhoneLabel, PicDayFact
from apps.pic_analytics.queries import groups
from apps.pic_analytics.queries.calls import _day, agent_labels, calls_qs
from apps.pic_analytics.queries.retention import MAX_PAGE_SIZE, _int_param

DENIED = 'تبويب الأرقام الجديدة للإدارة فقط'
CONVERSION_ROWS = 200


def _require(access):
    if not access.sees_calls_tabs:
        raise PermissionError(DENIED)


def _kind(key):
    mobile = key.startswith('01') or (len(key) == 10 and key.startswith('1'))
    return 'mobile' if mobile else 'landline'


def new_numbers(f, access, page, page_size=50) -> dict:
    _require(access)
    page = _int_param(page, 'الصفحة', 1)
    # page_size=None = everything (internal, Excel export only; the HTTP layer always passes a capped int)
    page_size = None if page_size is None else _int_param(page_size, 'حجم الصفحة', 1, MAX_PAGE_SIZE)
    labelled = PhoneLabel.objects.values('phone_key')
    rows = (calls_qs(f, use_agent=False).filter(pic_match='none').exclude(phone_key='')
            .exclude(phone_key__in=labelled).order_by('call_at')
            .values_list('phone_key', 'customer_number', 'call_at', 'direction', 'status',
                         'billable_seconds', 'agent_ext', 'agent_name'))
    agg = {}
    for key, number, at, direction, status, billable, ext, name in rows:       # ascending: last write wins
        a = agg.setdefault(key, {'calls_in': 0, 'calls_out': 0, 'answered': 0, 'missed': 0,
                                 'talk_seconds': 0, 'first_call': at, 'agent': None})
        a['number'], a['last_call'] = number, at
        a['calls_in' if direction == 'inbound' else 'calls_out'] += 1
        if status == 'answered':
            a['answered'] += 1
            a['talk_seconds'] += billable or 0
        elif direction == 'inbound':
            a['missed'] += 1
        if ext:
            a['agent'] = (ext, name)
    keys = sorted(agg, key=lambda k: agg[k]['last_call'], reverse=True)
    chunk = keys if page_size is None else keys[(page - 1) * page_size: page * page_size]
    exts = {e.extension: e for e in AgentExtension.objects.filter(
        extension__in={agg[k]['agent'][0] for k in chunk if agg[k]['agent']}).select_related('staff')}
    out = []
    for k in chunk:
        a = agg[k]
        agent = None
        if a['agent']:
            ext, name = a['agent']
            e = exts.get(ext)
            agent = {'agent_ext': ext,
                     'staff_name': (e.staff.full_name or None) if e and e.staff else None,
                     'pbx_name': e.pbx_name if e and e.pbx_name else name}
        row = {
            'phone_key': k, 'number': a['number'], 'calls_in': a['calls_in'], 'calls_out': a['calls_out'],
            'answered': a['answered'], 'missed': a['missed'],
            'first_call': timezone.localtime(a['first_call']).isoformat(),
            'last_call': timezone.localtime(a['last_call']).isoformat(),
            'last_agent': agent, 'talk_seconds': a['talk_seconds'], 'kind': _kind(k),
        }
        cust_access.mask_fields(row, ['number'], False)         # unlinked numbers stay masked
        out.append(row)
    return {'count': len(keys), 'rows': out}


def conversions(f, access) -> dict:
    _require(access)
    custs = {}
    for c in (Customer.objects.filter(softech_created_at__gte=f.start, softech_created_at__lte=f.end,
                                      is_account_placeholder=False, merged_into_pic='')
              .exclude(softech_pic__isnull=True).exclude(softech_pic='').exclude(softech_pic__startswith='ACCT-')
              .exclude(softech_pic__in=f.excluded())
              .order_by('-pk')):
        custs[c.softech_pic] = c                                  # lowest pk wins (iterated last)
    first = {}
    for pic, key, number, at in (CdrCall.objects.filter(pic__in=list(custs), is_transfer=False)
                                 .exclude(pic_match='none').order_by('call_at')
                                 .values_list('pic', 'phone_key', 'customer_number', 'call_at')):
        if pic not in first and _day(at) < custs[pic].softech_created_at:
            first[pic] = (key, number, at)
    bought = defaultdict(bool)
    for pic, day in (PicDayFact.objects.filter(pic__in=list(first), invoices__gt=0)
                     .values_list('pic', 'day').distinct()):
        if day >= custs[pic].softech_created_at:
            bought[pic] = True
    pics = sorted(first, key=lambda p: (custs[p].softech_created_at, p), reverse=True)
    user = getattr(access.profile, 'user', None)
    rows = []
    for p in pics[:CONVERSION_ROWS]:
        key, number, at = first[p]
        c = custs[p]
        row = {'phone_key': key, 'number': number, 'pic': p, 'customer_name': c.name,
               'created_at': c.softech_created_at, 'first_call': timezone.localtime(at).isoformat(),
               'bought': bought[p]}
        cust_access.mask_fields(row, ['number'], bool(user is not None and cust_access.phones_visible(user, c)))
        rows.append(row)
    return {'became_pic': len(first), 'became_pic_and_bought': sum(1 for p in first if bought[p]),
            'by_agent': _by_agent(first, custs, bought), 'by_branch': _by_branch(first, custs, bought),
            'rows': rows}


def _split(first, bought, key_of):
    """{key: [became_pic, became_pic_and_bought]} over the converted PICs."""
    out = defaultdict(lambda: [0, 0])
    for p in first:
        o = out[key_of(p)]
        o[0] += 1
        o[1] += 1 if bought[p] else 0
    return out


def _by_agent(first, custs, bought):
    """Per agent: the one on the number's LAST ANSWERED call before the PIC was created ('' = none)."""
    keys = {k for k, _n, _a in first.values()}
    calls = defaultdict(list)
    for key, ext, at in (CdrCall.objects.filter(phone_key__in=keys, status='answered', is_transfer=False)
                         .order_by('call_at').values_list('phone_key', 'agent_ext', 'call_at')):
        calls[key].append((_day(at), ext))
    agent = {}
    for p, (key, _n, _a) in first.items():
        agent[p] = ''
        for day, ext in calls.get(key, ()):             # ascending: the last one before creation wins
            if day < custs[p].softech_created_at:
                agent[p] = ext
    split = _split(first, bought, agent.get)
    labels = agent_labels(split)
    rows = [{'agent_ext': ext, 'label': labels.get(ext) or 'غير محدد', 'became_pic': n, 'became_pic_and_bought': b}
            for ext, (n, b) in split.items()]
    return sorted(rows, key=lambda r: (-r['became_pic'], r['agent_ext']))


def _by_branch(first, custs, bought):
    """Per branch of the PIC's first sale on/after it was created (None = not bought yet)."""
    where = {}
    for pic, day, branch_id in (PicDayFact.objects.filter(pic__in=list(first), invoices__gt=0)
                                .order_by('day', 'branch_id').values_list('pic', 'day', 'branch_id')):
        if pic not in where and day >= custs[pic].softech_created_at:
            where[pic] = branch_id
    split = _split(first, bought, lambda p: where.get(p) if bought[p] else None)
    names = groups.branch_labels()
    rows = [{'branch_id': b, 'label': names.get(b) or ('لم يشترِ بعد' if b is None else str(b)),
             'became_pic': n, 'became_pic_and_bought': bo} for b, (n, bo) in split.items()]
    return sorted(rows, key=lambda r: (-r['became_pic'], str(r['branch_id'])))


def label_number(phone_key, label, note, staff) -> PhoneLabel:
    """Upsert a PhoneLabel (a number that is not a customer) and audit the change."""
    if label not in dict(PhoneLabel.LABEL_CHOICES):
        raise ValueError('تصنيف غير صالح')
    phone_key = (phone_key or '').strip()
    if not phone_key or len(phone_key) > 15:
        raise ValueError('رقم غير صالح')
    note = (note or '')[:255]
    pl = PhoneLabel.objects.filter(phone_key=phone_key).first()
    before = {'label': pl.label, 'note': pl.note} if pl else None
    if pl:
        pl.label, pl.note, pl.created_by = label, note, staff
        pl.save()
    else:
        pl = PhoneLabel.objects.create(phone_key=phone_key, label=label, note=note, created_by=staff)
    AuditLog.log('pic_phone_labelled', user=staff, obj=pl, old_data=before,
                 new_data={'label': label, 'note': note}, note=phone_key)
    return pl


def labelled_numbers(access, page, page_size=50) -> dict:
    """The numbers someone labelled (newest first) so a wrong label can be reviewed and undone.
    Rows carry `phone_key` (the HTTP layer swaps it for an opaque number_id) and a masked number."""
    _require(access)
    page = _int_param(page, 'الصفحة', 1)
    page_size = _int_param(page_size, 'حجم الصفحة', 1, MAX_PAGE_SIZE)
    qs = PhoneLabel.objects.select_related('created_by__user').order_by('-created_at', '-pk')
    chunk = list(qs[(page - 1) * page_size: page * page_size])
    shown = {}
    for key, number in (CdrCall.objects.filter(phone_key__in=[p.phone_key for p in chunk], is_transfer=False)
                        .exclude(customer_number='').order_by('call_at', 'pk')
                        .values_list('phone_key', 'customer_number')):
        shown[key] = number                                    # last assignment = latest call
    labels = dict(PhoneLabel.LABEL_CHOICES)
    rows = []
    for pl in chunk:
        row = {'label_id': pl.pk, 'phone_key': pl.phone_key, 'number': shown.get(pl.phone_key, ''),
               'label': pl.label, 'label_display': labels.get(pl.label, pl.label), 'note': pl.note,
               'created_by': pl.created_by.full_name if pl.created_by_id else '',
               'created_at': timezone.localtime(pl.created_at).isoformat()}
        cust_access.mask_fields(row, ['number'], False)         # a labelled number is not a customer: masked
        rows.append(row)
    return {'count': qs.count(), 'rows': rows}


def unlabel_number(label_id, staff, request=None):
    """Delete a PhoneLabel (the number returns to «new numbers» / the missed-call action list) and audit it."""
    with transaction.atomic():
        pl = PhoneLabel.objects.select_for_update().filter(pk=label_id).first()
        if pl is None:
            return None
        before = {'label': pl.label, 'note': pl.note}
        AuditLog.log('pic_phone_unlabelled', user=staff, obj=pl, old_data=before, new_data=None,
                     note=pl.phone_key, request=request)
        pl.delete()
    return before
