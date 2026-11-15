"""
apps/tax_invoicing/eta_recon.py — receipts reconciliation, SOFTECH ↔ ETA (spec §Phase 3).

Every SOFTECH sale (doccode 115) and return (30) of an open branch is matched to ETA's copy of the receipt by
(branch, kind, number, Cairo date): ETA's receiptNumber is SOFTECH's docnumber, and each POS serial belongs to one
branch (learned from a sample of its receipts; a manual entry is never overwritten). Each sale gets one outcome;
unmatched ETA receipts are listed too. A (system, branch, day) is recomputed as a whole, in one transaction.
SOFTECH is read only (HQ stktransm through config/sybase.py). Nothing is written to SOFTECH or sent to ETA.
"""
import datetime as dt
import logging
import uuid
from collections import Counter, defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count, Min, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core.errors import redact

from .models import EtaDeviceBranch, EtaHistoryState, EtaMirrorReceipt, EtaReconLine, TaxChannelRule

logger = logging.getLogger(__name__)
CAIRO = ZoneInfo('Africa/Cairo')
TOLERANCE = Decimal('0.05')
KIND_BY_DOCCODE = {'115': 's', '30': 'r'}
DOCCODE_BY_KIND = {v: k for k, v in KIND_BY_DOCCODE.items()}
OUTCOMES = ('matched', 'amount_differs', 'missing_at_eta', 'eta_only', 'not_valid', 'duplicate', 'by_invoice')
SAMPLE = 20
RECENT_DAYS = 30


# ── SOFTECH (read only) ────────────────────────────────────────────────────────────────────────

def _connect():
    from config.sybase import get_sybase_connection
    return get_sybase_connection()


def _softech_rows(branch, day):
    """One branch-day of SOFTECH sales and returns from HQ: [{doccode, docnumber, total, channel}]."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT doccode, docnumber, docvalue, ptclassifcode FROM stktransm "
                    "WHERE branchcode = ? AND docdate = ? AND doccode IN ('115', '30')", (branch, day.isoformat()))
        rows = cur.fetchall()
    finally:
        conn.close()
    return [{'doccode': str(r[0]).strip(), 'docnumber': str(int(float(str(r[1])))), 'total': Decimal(str(r[2] or 0)),
             'channel': str(r[3] or '').strip()} for r in rows]


def _softech_find(keys):
    """{(doccode, docnumber, day): branch} for the given keys, from HQ."""
    out = {}
    conn = _connect()
    try:
        cur = conn.cursor()
        for doccode, number, day in keys:
            cur.execute("SELECT branchcode FROM stktransm WHERE doccode = ? AND docnumber = CONVERT(DECIMAL(18,0), ?) "
                        "AND docdate = ?", (doccode, number, day.isoformat()))
            rows = cur.fetchall()
            if len(rows) == 1:
                out[(doccode, number, day)] = str(rows[0][0]).strip()
    finally:
        conn.close()
    return out


# ── which branch each device belongs to ────────────────────────────────────────────────────────

def _cairo_day(when):
    return when.astimezone(CAIRO).date()


def learn_devices(system, sample=SAMPLE):
    """For each POS serial at ETA: the SOFTECH branch most of a sample of its receipts belong to, and the day of its
    first receipt. A manual entry keeps its branch; its first day still follows ETA."""
    learned = {}
    serials = (EtaMirrorReceipt.objects.filter(system=system).exclude(pos_serial='').order_by()
               .values('pos_serial').annotate(first=Min('issued_at')))
    for row in serials:
        serial = row['pos_serial']
        receipts = list(EtaMirrorReceipt.objects.filter(system=system, pos_serial=serial, receipt_type='s')
                        .exclude(issued_at=None).order_by('-issued_at')[:sample])
        keys = {('115', r.receipt_number, _cairo_day(r.issued_at)) for r in receipts}
        found = Counter(_softech_find(keys).values())
        first_day = _cairo_day(row['first']) if row['first'] else None
        existing = EtaDeviceBranch.objects.filter(system=system, pos_serial=serial).first()
        if existing and existing.source == 'manual':
            existing.first_day = first_day or existing.first_day
            existing.save(update_fields=['first_day', 'updated_at'])
            learned[serial] = existing.softech_branchcode
            continue
        if not found:
            continue
        branch, hits = found.most_common(1)[0]
        EtaDeviceBranch.objects.update_or_create(system=system, pos_serial=serial, defaults={
            'softech_branchcode': branch, 'first_day': first_day, 'source': 'auto',
            'sample_matched': hits, 'sample_size': len(keys)})
        learned[serial] = branch
    return learned


def open_branches(system):
    """Device branches that are live in our branch list (HQ or retail). Branch.kind is the only liveness test: closed
    «لاغى» branches, pending ones, the call center and codes missing from the list are left out."""
    from apps.branches.models import Branch
    live = set(Branch.objects.live().values_list('softech_branch_id', flat=True))
    return sorted({b for b in EtaDeviceBranch.objects.filter(system=system).values_list('softech_branchcode', flat=True)
                   if b in live})


# ── one branch-day ─────────────────────────────────────────────────────────────────────────────

def _decide(sale, matches):
    if not matches:
        return 'missing_at_eta'
    if len(matches) > 1:
        return 'duplicate'
    eta = matches[0]
    if (eta.status or '').lower() != 'valid':
        return 'not_valid'
    if eta.total_amount is None or abs(Decimal(eta.total_amount) - sale['total']) > TOLERANCE:
        return 'amount_differs'
    return 'matched'


def reconcile_day(system, branch, day):
    """Recomputes one branch-day. Returns counts per outcome, or {'skipped': True} before the branch's devices began."""
    devices = list(EtaDeviceBranch.objects.filter(system=system, softech_branchcode=branch))
    starts = [d.first_day for d in devices if d.first_day]
    if not devices or (starts and day < min(starts)):
        return {'skipped': True}
    sales = _softech_rows(branch, day)
    by_invoice = set(TaxChannelRule.objects.filter(mode=TaxChannelRule.MODE_INVOICE).values_list('ptclassifcode', flat=True))
    since = dt.datetime.combine(day, dt.time.min, tzinfo=CAIRO)
    eta = defaultdict(list)
    for r in EtaMirrorReceipt.objects.filter(system=system, pos_serial__in=[d.pos_serial for d in devices],
                                             issued_at__gte=since, issued_at__lt=since + dt.timedelta(days=1)):
        eta[(DOCCODE_BY_KIND.get(r.receipt_type, '115'), r.receipt_number)].append(r)
    lines, used = [], set()
    for sale in sales:
        key = (sale['doccode'], sale['docnumber'])
        matches = eta.get(key, [])
        used.add(key)
        outcome = 'by_invoice' if sale['channel'] in by_invoice else _decide(sale, matches)
        first = matches[0] if matches else None
        lines.append(EtaReconLine(system=system, softech_branchcode=branch, day=day, doccode=sale['doccode'],
                                  docnumber=sale['docnumber'], softech_total=sale['total'], outcome=outcome,
                                  eta_uuid=first.uuid if first else '', eta_total=first.total_amount if first else None,
                                  eta_status=first.status if first else '', eta_count=len(matches)))
    for key, rows in eta.items():
        if key in used:
            continue
        lines.append(EtaReconLine(system=system, softech_branchcode=branch, day=day, doccode=key[0], docnumber=key[1],
                                  outcome='eta_only', eta_uuid=rows[0].uuid, eta_total=rows[0].total_amount,
                                  eta_status=rows[0].status, eta_count=len(rows)))
    with transaction.atomic():
        EtaReconLine.objects.filter(system=system, softech_branchcode=branch, day=day).delete()
        EtaReconLine.objects.bulk_create(lines, batch_size=1000)
    counts = Counter(l.outcome for l in lines)
    return {o: counts.get(o, 0) for o in OUTCOMES}


def reconcile_range(system, start, end, branches=None):
    """Recomputes every open branch from `start` to `end` (inclusive). Stops at the first SOFTECH failure; lines
    already computed stay as they were. The round is recorded per system (EtaHistoryState kind 'recon')."""
    out = {'days': 0, 'branch_days': 0, 'error': ''}
    branches = branches or open_branches(system)
    day = start
    try:
        while day <= end:
            for branch in branches:
                if not reconcile_day(system, branch, day).get('skipped'):
                    out['branch_days'] += 1
            out['days'] += 1
            day += dt.timedelta(days=1)
    except Exception as exc:        # noqa: BLE001 — SOFTECH (jConnect) raises Java and OS errors alike
        # driver text carries hostnames and SQL: the log keeps it (redacted), the screen gets a reference only
        ref = uuid.uuid4().hex[:8]
        logger.warning('[ref %s] ETA reconciliation %s stopped at %s: %s: %s', ref, system, day, type(exc).__name__,
                       redact(exc)[:500])
        out['error'] = f'تعذرت قراءة SOFTECH عند يوم {day} (مرجع: {ref})'
    state, _ = EtaHistoryState.objects.get_or_create(system=system, kind='recon')
    state.last_run_at, state.last_error = timezone.now(), out['error']
    if not out['error']:
        state.last_ok_at = state.last_run_at
    state.save()
    return out


def recent(system, days=RECENT_DAYS):
    today = timezone.localdate()
    return reconcile_range(system, today - dt.timedelta(days=days), today - dt.timedelta(days=1))


# ── summary ────────────────────────────────────────────────────────────────────────────────────

def summary(system, branch=None):
    qs = EtaReconLine.objects.filter(system=system)
    if branch:
        qs = qs.filter(softech_branchcode=branch)
    rows = {}
    for r in (qs.annotate(month=TruncMonth('day')).values('softech_branchcode', 'month', 'outcome')
              .annotate(n=Count('id'), softech=Sum('softech_total'), eta=Sum('eta_total'))
              .order_by('softech_branchcode', 'month')):
        key = (r['softech_branchcode'], r['month'].strftime('%Y-%m'))
        row = rows.setdefault(key, {'branch': key[0], 'month': key[1], **{o: 0 for o in OUTCOMES},
                                    'softech_total': Decimal('0'), 'eta_total': Decimal('0')})
        row[r['outcome']] = r['n']
        row['softech_total'] += r['softech'] or 0
        row['eta_total'] += r['eta'] or 0
    out = list(rows.values())
    for row in out:
        row['softech_total'] = str(Decimal(row['softech_total']).quantize(Decimal('0.01')))
        row['eta_total'] = str(Decimal(row['eta_total']).quantize(Decimal('0.01')))
    return out
