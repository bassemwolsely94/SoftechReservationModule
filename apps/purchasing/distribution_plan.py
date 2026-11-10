"""
apps/purchasing/distribution_plan.py — «التوزيعة» as ONE plan (doc 30 phases B–C, owner 2026-11-10).

build()    — read-only against SOFTECH; writes only our ledger (DistributionPlan + PlannedMove):
  1. live inputs: every branch's and HQ's real stock from server 100 (rate = the engine run's);
  2. the suggestions (distribution.analyze) → one move per (item, from, to);
  3. waves, HQ first: 1 HQ supplies (anything HQ holds) · 2 over-piled branch excess →
     branches that sell it with room · 3 never-stocked, only from a branch itself over its max ·
     4 new-item trial seeds from a branch (HQ holds none). A seed HQ can cover moves to HQ.
  4. wave 0 — what is already on its way to the destination: our live / recent drafts, SOFTECH's
     own ISRs of the last 3 days not yet dispensed, in-transit transfers, live transfer requests.
     A seed already covered → «متعارض»; an over-piled move is cut by the covered qty.
  5. thresholds: a branch-sourced line under 100 EGP is dropped; a branch → HQ document or an
     «after receipt» part under 1,000 EGP is folded into the next run; HQ moves always stay
     (SystemSetting distribution_min_line_value / _min_doc_value).
  6. documents: ONE branch → HQ ISR per source branch, ONE HQ → branch «جاهز الآن» per
     destination, and per (destination, source) one «بعد الاستلام من S» part that waits until
     S's leg is RECEIVED at HQ (isr_guards). A route held by an approved draft or another planner
     → its moves are «المسار مشغول».
generate() — turns the latest built plan into PROPOSED IsrPush drafts (PG only). SOFTECH is
written later, by the usual approve → push, with every push guard.
"""
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')

HQ = '100'
WAVE_LABELS = {1: 'من الرئيسي أولاً', 2: 'متكدس بفرع ← فروع تبيعه', 3: 'غير مُدرج — من فرع فوق حده',
               4: 'تجربة صنف جديد — من فرع'}
SEED_CATS = ('never_stocked', 'new_no_rate', 'hq_dormant')
SOFTECH_ISR_DAYS = 3          # SOFTECH's own daily HQ ISRs still waiting to be dispensed
TRANSFER_MAX_DAYS = 14        # in-transit window (the shared in_transit rule)
PLAN_MAX_AGE_HOURS = 12       # generate only from a fresh plan
KEEP_PLANS = 30
DEFAULT_MIN_LINE = 100.0
DEFAULT_MIN_DOC = 1000.0


def thresholds() -> dict:
    from apps.config.models import SystemSetting

    def num(key, default):
        try:
            return max(0.0, float(SystemSetting.get(key, default) or default))
        except (TypeError, ValueError):
            return default
    return {'min_line': num('distribution_min_line_value', DEFAULT_MIN_LINE),
            'min_doc': num('distribution_min_doc_value', DEFAULT_MIN_DOC)}


# ── 1. live inputs ───────────────────────────────────────────────────────────────
def live_stock(branch_codes):
    """({branch: {itemcode: qty}}, as_of) — real-balance stores (storerealbal = 1) from server 100,
    the same read as the SOFTECH ISR rule (isr_softech). READ-ONLY."""
    from config.sybase import get_sybase_connection
    codes = sorted({str(c).strip() for c in branch_codes if str(c).strip()} | {HQ})
    out = defaultdict(dict)
    conn = get_sybase_connection()
    cur = conn.cursor()
    try:
        ph = ','.join('?' for _ in codes)
        cur.execute('SELECT s.branchcode, s.itemcode, sum(s.nowqty) FROM stkbal s, stores st '
                    'WHERE s.storecode = st.storecode AND st.storerealbal = 1 '
                    f'AND s.branchcode IN ({ph}) GROUP BY s.branchcode, s.itemcode', codes)
        for bc, code, q in cur.fetchall():
            q = float(q or 0)
            if q:
                out[str(bc).strip()][str(code).strip()] = q
        cur.execute('SELECT getdate()')
        row = cur.fetchone()
    finally:
        cur.close()
        conn.close()
    as_of = row[0] if row else None
    return {c: dict(out.get(c, {})) for c in codes}, (as_of.strftime('%Y-%m-%d %H:%M')
                                                      if hasattr(as_of, 'strftime') else '')


# ── 2. wave 0: what is already on its way ────────────────────────────────────────
def _add(flows, code, dest, source, label, ref, qty):
    if qty and qty > 0:
        flows[(code, dest)].append({'source': source, 'label': label, 'ref': ref, 'qty': round(float(qty), 2)})


def committed_flows(codes, dests):
    """({(itemcode, dest): [{source, label, ref, qty}]}, notes). Proposed «التوزيعة» drafts are left
    out — a new generation replaces them."""
    from apps.purchasing import isr_guards
    from apps.purchasing.models import IsrPush as P
    codes, dests = {str(c) for c in codes}, {str(d) for d in dests}
    flows, notes = defaultdict(list), []
    if not codes or not dests:
        return flows, notes

    # our drafts to the destination: live (not this planner's proposed ones) + pushed, not dispensed
    since = timezone.now() - timedelta(days=isr_guards.DUP_PUSH_DAYS)
    qs = (P.objects.filter(kind__in=[P.KIND_HQ_TO_BRANCH, P.KIND_SELF])
          .filter(status__in=[P.STATUS_PROPOSED, P.STATUS_APPROVED, P.STATUS_PUSHED])
          .only('id', 'kind', 'status', 'branchcode', 'dest_branchcode', 'lines_snapshot', 'pushed_at',
                'isrdocnumber', 'params'))
    pushed_rows, ours = [], set()
    for p in qs.iterator():
        dest = str(p.dest_branchcode or p.branchcode)
        if dest not in dests:
            continue
        if p.status == P.STATUS_PUSHED:
            if not p.pushed_at or p.pushed_at < since:
                continue
            if p.isrdocnumber:
                ours.add(int(p.isrdocnumber))
        elif p.status == P.STATUS_PROPOSED and (p.params or {}).get('planner') == 'distribution':
            continue
        for l in p.lines_snapshot or []:
            code = str(l.get('itemcode') or '').strip()
            if code not in codes:
                continue
            row = {'code': code, 'dest': dest, 'qty': float(l.get('itemqty') or 0), 'push': p}
            if p.status == P.STATUS_PUSHED:
                pushed_rows.append(row)
            else:
                _add(flows, code, dest, 'draft', f'طلب توريد #{p.pk} ({p.get_status_display()})', p.pk, row['qty'])
    done = isr_guards._dispensed([{'push_id': r['push'].pk, 'itemcode': r['code'], 'pushed_at': r['push'].pushed_at,
                                   'source': str(r['push'].branchcode if r['push'].kind == P.KIND_HQ_TO_BRANCH else HQ),
                                   'dest': r['dest']} for r in pushed_rows], timezone.now())
    for r in pushed_rows:
        if (r['push'].pk, r['code']) not in done:
            _add(flows, r['code'], r['dest'], 'draft',
                 f'طلب توريد #{r["push"].pk} مُرحّل (ISR {r["push"].isrdocnumber}) لم يُصرف بعد', r['push'].pk, r['qty'])

    # SOFTECH's own ISRs to the destination (server 100), last few days, not yet dispensed
    try:
        rows = _softech_isrs(dests, ours)
        done = isr_guards._dispensed(rows, timezone.now())
        for r in rows:
            if (r['push_id'], r['itemcode']) not in done and r['itemcode'] in codes:
                _add(flows, r['itemcode'], r['dest'], 'softech_isr', f'ISR سوفتك {r["push_id"]}', r['push_id'], r['qty'])
    except Exception:
        logger.exception('[distribution_plan] SOFTECH ISR read failed')
        notes.append('تعذّرت قراءة طلبات التوريد في سوفتك (سيرفر 100) — لم تُخصم من الخطة.')

    # in transit to the destination (shared definition)
    from apps.purchasing.in_transit import by_branch_code
    transit, _days = by_branch_code(codes, max_age=TRANSFER_MAX_DAYS)
    for dest, items in transit.items():
        if dest in dests:
            for code, q in items.items():
                _add(flows, code, dest, 'transit', 'بضاعة بالطريق (إذن صرف لم يُستلم)', None, q)

    # open transfer requests (WhatsApp / shortage lists / manual) to the destination — the SAME rule
    # as the supply engine (apps/supply/engine/commitments.py): not yet dispatched, because a
    # dispatched one is already counted above as in transit
    from apps.supply.engine.commitments import OPEN_TRANSFER_STATUSES
    from apps.transfers.models import TransferRequestItem
    for code, dest, q, aq, req in (TransferRequestItem.objects.filter(
            request__status__in=OPEN_TRANSFER_STATUSES, request__dispatched_at__isnull=True,
            request__requesting_branch__softech_branch_id__in=dests, item__softech_id__in=codes)
            .values_list('item__softech_id', 'request__requesting_branch__softech_branch_id',
                         'quantity', 'approved_quantity', 'request_id')):
        _add(flows, str(code), str(dest), 'transfer', f'طلب تحويل #{req}', req, float(aq if aq is not None else q or 0))
    return flows, notes


def _softech_isrs(dests, ours):
    """[{push_id, itemcode, qty, pushed_at, source, dest}] — ISRs on server 100 for these
    destinations from the last SOFTECH_ISR_DAYS days, ours excluded (counted as drafts)."""
    from config.sybase import get_sybase_connection
    dl = sorted(dests)
    conn = get_sybase_connection()
    cur = conn.cursor()
    try:
        ph = ','.join('?' for _ in dl)
        cur.execute('SELECT m.isrdocnumber, m.forbranchcode, m.docdate, l.itemcode, l.itemqty '
                    'FROM stockisrm m, stockisr l WHERE l.isrdocnumber = m.isrdocnumber '
                    f'AND m.docdate >= dateadd(day, -{int(SOFTECH_ISR_DAYS)}, getdate()) '
                    f'AND m.forbranchcode IN ({ph})', dl)
        raw = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    out = []
    for num, dest, d, code, q in raw:
        if int(num) in ours:
            continue
        day = d.date() if hasattr(d, 'date') else d
        out.append({'push_id': int(num), 'itemcode': str(code).strip(), 'qty': float(q or 0),
                    'pushed_at': timezone.make_aware(datetime.combine(day, time.min)),
                    'source': HQ, 'dest': str(dest).strip()})       # HQ fills every branch ISR
    return out


# ── 3. moves, waves, thresholds, documents ───────────────────────────────────────
def _moves_from(sugs, costs, hq_stock, ceilings):
    """One move per (item, target). Waves and the source rules (doc 30 §2.3)."""
    moves = []
    for s in sugs:
        code, cat, src = s['itemcode'], s['category'], str(s['from_branch'])
        total = sum(int(t.get('qty') or s['qty_each']) for t in s['to_branches'])
        reasons = [cat, *s.get('signals', [])]
        if s.get('reason'):
            reasons.append(s['reason'])
        status, note = 'planned', ''
        if src != HQ and cat in ('never_stocked', 'new_no_rate') and hq_stock.get(code, 0) >= total:
            src = HQ                                    # HQ holds enough → one leg from HQ, never a branch
            reasons.append('hq_covers')
        if src == HQ:
            wave = 1
        elif cat == 'over_piled':
            wave = 2
        elif cat == 'never_stocked':
            wave = 3
            c = ceilings.get(src, {}).get(code)
            if not (c and c[0] - c[1] > 0.05):
                status, note = 'not_allowed', 'الفرع المصدر ليس فوق حده الأقصى — لا يُسحب رصيده العامل'
        else:                                           # new_no_rate (or anything else) from a branch
            wave = 4
        for t in s['to_branches']:
            qty = int(t.get('qty') or s['qty_each'])
            cost = float(costs.get(code, 0) or 0)
            moves.append({'itemcode': code, 'item_name': s.get('item_name', ''), 'from_code': src,
                          'to_code': str(t['code']), 'qty': qty, 'unit_cost': cost, 'value': round(qty * cost, 2),
                          'wave': wave, 'category': cat, 'reasons': reasons, 'status': status,
                          'status_note': note, 'conflicts': [],
                          'position': {'from': s.get('from_position') or {},
                                       'to': {k: t.get(k) for k in ('stock', 'rate', 'max', 'live')}}})
    return moves


def _apply_committed(moves, flows):
    for m in moves:
        if m['status'] != 'planned':
            continue
        got = flows.get((m['itemcode'], m['to_code'])) or []
        if not got:
            continue
        m['conflicts'] = got
        covered = sum(g['qty'] for g in got)
        if m['category'] in SEED_CATS:
            m['status'], m['status_note'] = 'conflict', f'مغطى بالفعل: {got[0]["label"]}'
            continue
        left = int(m['qty'] - covered)                  # over-piled: cut by what is already coming
        if left < 1:
            m['status'], m['status_note'] = 'conflict', f'مغطى بالفعل: {got[0]["label"]}'
        else:
            m['status_note'] = f'خُفّضت الكمية من {m["qty"]} إلى {left} — {got[0]["label"]}'
            m['qty'] = left
            m['value'] = round(left * m['unit_cost'], 2)


def _apply_line_threshold(moves, min_line):
    for m in moves:
        if m['status'] == 'planned' and m['from_code'] != HQ and m['value'] < min_line:
            m['status'], m['status_note'] = 'below_line', f'قيمة السطر {m["value"]:,.0f} أقل من {min_line:,.0f} ج'


def _doc_key(m):
    """The HQ → branch document a planned move lands in."""
    return ('ready', m['to_code'], '') if m['from_code'] == HQ else ('after', m['to_code'], m['from_code'])


def _route(key):
    """(kind, source, dest, route_tag) of a document key."""
    part, a, b = key
    if part == 'feed':
        return 'branch_to_hq', a, HQ, ''
    if part == 'ready':
        return 'hq_to_branch', HQ, a, 'dist'
    return 'hq_to_branch', HQ, a, f'dist:{b}'


def _route_holder(key):
    """An approved draft, or another planner's proposed draft, on the document's route → (id, why)."""
    from apps.purchasing import isr_guards
    kind, src, dest, tag = _route(key)
    for p in isr_guards.live_on_route(kind, src, dest, tag=tag).only('id', 'status', 'params'):
        if p.status == 'approved':
            return p.pk, f'طلب معتمد #{p.pk} على نفس المسار لم يُرحَّل بعد'
        planner = (p.params or {}).get('planner')
        if planner not in (None, '', 'distribution'):
            who = isr_guards.PLANNER_AR.get(planner, planner)
            return p.pk, f'طلب مقترح #{p.pk} من «{who}» على نفس المسار'
    return None, ''


def _documents(moves, min_doc, holder=_route_holder):
    """Mark blocked / folded moves and return the documents of the planned ones."""
    def planned():
        return [m for m in moves if m['status'] == 'planned']

    # routes held by someone else
    for key in {_doc_key(m) for m in planned()} | {('feed', m['from_code'], '') for m in planned()
                                                    if m['from_code'] != HQ}:
        pk, why = holder(key)
        if pk is None:
            continue
        for m in planned():
            hit = (_doc_key(m) == key) or (key[0] == 'feed' and m['from_code'] == key[1])
            if hit:
                m['status'], m['status_note'] = 'blocked', why
                m['conflicts'] = m['conflicts'] + [{'source': 'route', 'label': why, 'ref': pk, 'qty': 0}]

    # documents under the minimum value → next run (an «after» part and its feeder fold together)
    while True:
        changed = False
        docs = defaultdict(float)
        feeds = defaultdict(float)
        for m in planned():
            docs[_doc_key(m)] += m['value']
            if m['from_code'] != HQ:
                feeds[m['from_code']] += m['value']
        for key, v in docs.items():
            if key[0] == 'after' and v < min_doc:
                changed |= _fold(moves, lambda m, k=key: _doc_key(m) == k,
                                 f'جزء «بعد الاستلام» قيمته {v:,.0f} أقل من {min_doc:,.0f} ج')
        for src, v in feeds.items():
            if v < min_doc and not changed:
                changed |= _fold(moves, lambda m, s=src: m['from_code'] == s,
                                 f'طلب الفرع {src} للرئيسي قيمته {v:,.0f} أقل من {min_doc:,.0f} ج')
        if not changed:
            break
    # HQ «جاهز الآن» documents always stay (owner 2026-11-10: HQ ships to every branch anyway)

    out = {}
    for m in planned():
        for key in ([('feed', m['from_code'], ''), _doc_key(m)] if m['from_code'] != HQ else [_doc_key(m)]):
            d = out.setdefault(key, {'items': set(), 'qty': 0, 'value': 0.0})
            d['items'].add(m['itemcode'])
            d['qty'] += m['qty']
            d['value'] += m['value']
    docs = []
    for key, d in sorted(out.items(), key=lambda kv: ({'feed': 0, 'ready': 1, 'after': 2}[kv[0][0]], kv[0][1], kv[0][2])):
        kind, src, dest, tag = _route(key)
        docs.append({'key': ':'.join(x for x in key if x), 'part': key[0], 'kind': kind, 'source': src,
                     'dest': dest, 'route_tag': tag, 'waits_for': (key[2] if key[0] == 'after' else None),
                     'lines': len(d['items']), 'qty': d['qty'], 'value': round(d['value'], 2), 'push_id': None})
    return docs


def _fold(moves, match, note):
    hit = False
    for m in moves:
        if m['status'] == 'planned' and match(m):
            m['status'], m['status_note'] = 'folded', note
            hit = True
    return hit


def _rank(moves):
    by_wave = defaultdict(list)
    for m in moves:
        by_wave[m['wave']].append(m)
    for w, ms in by_wave.items():
        for i, m in enumerate(sorted(ms, key=lambda m: (-m['value'], m['itemcode'], m['to_code'])), 1):
            m['rank'] = i


def _totals(moves):
    waves = {w: {'label': WAVE_LABELS[w], 'moves': 0, 'qty': 0, 'value': 0.0} for w in WAVE_LABELS}
    by_status = defaultdict(lambda: {'moves': 0, 'value': 0.0})
    for m in moves:
        by_status[m['status']]['moves'] += 1
        by_status[m['status']]['value'] = round(by_status[m['status']]['value'] + m['value'], 2)
        if m['status'] == 'planned' and m['wave'] in waves:
            w = waves[m['wave']]
            w['moves'] += 1
            w['qty'] += m['qty']
            w['value'] = round(w['value'] + m['value'], 2)
    return {'waves': {str(k): v for k, v in waves.items()}, 'by_status': dict(by_status), 'moves': len(moves)}


def plan_moves(sugs, *, costs, hq_stock, ceilings, flows, th, holder=_route_holder):
    """The pure part of build(): suggestions → (moves, documents). Testable without SOFTECH."""
    moves = _moves_from(sugs, costs, hq_stock, ceilings)
    _apply_committed(moves, flows)
    _apply_line_threshold(moves, th['min_line'])
    docs = _documents(moves, th['min_doc'], holder=holder)
    _rank(moves)
    return moves, docs


# ── 4. build + store ─────────────────────────────────────────────────────────────
def build(*, user=None, categories=None, live=True, run=None):
    """Compute and store a plan. READ-ONLY against SOFTECH."""
    from apps.catalog.models import Item
    from apps.purchasing import distribution
    from apps.purchasing.models import DistributionPlan, PlannedMove
    from apps.purchasing.rate_writer import _latest_run
    run = run or _latest_run()
    if run is None:
        raise ValueError('لا يوجد تشغيل ناجح لمحرك الطلب.')
    th = thresholds()
    notes, stock, as_of = [], None, ''
    ops = distribution._operational_branches()
    if live:
        try:
            stock, as_of = live_stock(ops)
        except Exception:
            logger.exception('[distribution_plan] live stock read failed')
            notes.append('تعذّرت قراءة الأرصدة اللحظية من سيرفر 100 — استُخدمت أرصدة آخر تشغيل للمحرك.')
    ceilings = distribution._branch_ceilings(set(ops)) if live else {}
    sugs = distribution.analyze(run=run, categories=categories, ceilings=ceilings, live_stock=stock,
                                use_age=live)
    codes = {s['itemcode'] for s in sugs}
    dests = {str(t['code']) for s in sugs for t in s['to_branches']}
    flows, fnotes = committed_flows(codes, dests)
    notes += fnotes
    costs = dict(Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'cost_price'))
    hq_stock = (stock or {}).get(HQ) or {}
    moves, docs = plan_moves(sugs, costs=costs, hq_stock=hq_stock, ceilings=ceilings, flows=flows, th=th)
    with transaction.atomic():
        DistributionPlan.objects.filter(status=DistributionPlan.STATUS_BUILT).update(
            status=DistributionPlan.STATUS_SUPERSEDED)
        plan = DistributionPlan.objects.create(
            run=run, created_by=user, totals=_totals(moves), documents=docs,
            inputs={'thresholds': th, 'categories': categories or 'all', 'live_stock': bool(stock),
                    'stock_as_of': as_of, 'run_id': run.pk, 'ceilings_read': sorted(ceilings),
                    'softech_isr_days': SOFTECH_ISR_DAYS, 'transfer_days': TRANSFER_MAX_DAYS,
                    'notes': notes, 'suggestions': len(sugs)})
        PlannedMove.objects.bulk_create([PlannedMove(
            plan=plan, itemcode=m['itemcode'], item_name=(m['item_name'] or '')[:255], from_code=m['from_code'],
            to_code=m['to_code'], qty=m['qty'], unit_cost=Decimal(str(round(m['unit_cost'], 3))),
            value=Decimal(str(m['value'])), wave=m['wave'], rank=m.get('rank', 0), category=m['category'],
            reasons=m['reasons'], status=m['status'], status_note=(m['status_note'] or '')[:255],
            conflicts=m['conflicts'], position=m['position']) for m in moves], batch_size=1000)
    _prune()
    logger.info('[distribution_plan] plan %s: %d moves, %d documents', plan.pk, len(moves), len(docs))
    return plan


def _prune():
    from apps.purchasing.models import DistributionPlan
    old = list(DistributionPlan.objects.order_by('-created_at').values_list('pk', flat=True)[KEEP_PLANS:])
    if old:
        DistributionPlan.objects.filter(pk__in=old).delete()


# ── 5. generate drafts from the plan ─────────────────────────────────────────────
def generate(plan, *, user=None):
    """PROPOSED IsrPush drafts from the latest built plan. PG only (no SOFTECH write). The drafts
    replace this planner's older proposed drafts. Returns {'created': [...], 'skipped': [...]}."""
    from apps.purchasing import isr_guards, isr_writer
    from apps.purchasing.models import DistributionPlan, IsrPush as P
    with transaction.atomic():
        plan = DistributionPlan.objects.select_for_update().get(pk=plan.pk)
        latest = DistributionPlan.objects.order_by('-created_at').values_list('pk', flat=True).first()
        if plan.status != DistributionPlan.STATUS_BUILT or plan.pk != latest:
            raise ValueError('هذه ليست أحدث خطة محسوبة — ابنِ الخطة من جديد ثم ولّد.')
        if timezone.now() - plan.created_at > timedelta(hours=PLAN_MAX_AGE_HOURS):
            raise ValueError(f'الخطة أقدم من {PLAN_MAX_AGE_HOURS} ساعة — الأرصدة تغيّرت. ابنِ الخطة من جديد.')
        plan.status = DistributionPlan.STATUS_GENERATED       # claims the plan: a second click stops here
        plan.generated_at, plan.generated_by = timezone.now(), user
        plan.save(update_fields=['status', 'generated_at', 'generated_by'])

    moves = list(plan.moves.filter(status='planned'))
    by_doc = defaultdict(list)
    for m in moves:
        by_doc[_doc_key({'from_code': m.from_code, 'to_code': m.to_code})].append(m)
    sources = sorted({m.from_code for m in moves if m.from_code != HQ})
    created, skipped, keep = [], [], set()
    base = {'plan_id': plan.pk}

    def lines_for(node, ms):
        qty = defaultdict(int)
        wave = {}
        for m in ms:
            qty[m.itemcode] += m.qty
            wave[m.itemcode] = min(wave.get(m.itemcode, 9), m.wave)
        lines = isr_writer.build_items_plan(node, list(qty.items()))
        for l in lines:
            l['wave'] = wave.get(l['itemcode'])
        return lines

    def record(p, part, ms):
        keep.add(p.pk)
        plan.moves.filter(pk__in=[m.pk for m in ms]).update(**({'feeder_push': p} if part == 'feed'
                                                               else {'isr_push': p}))
        created.append({'id': p.pk, 'part': part, 'source': p.branchcode, 'dest': p.dest_branchcode,
                        'route_tag': p.route_tag, 'lines': p.line_count, 'value': float(p.docvalue),
                        'waits_for': (p.linked_push_id if part == 'after' else None)})

    for src in sources:                                  # the feeder and its «after» parts: all or nothing
        src_moves = [m for m in moves if m.from_code == src]
        afters = sorted({m.to_code for m in src_moves})
        try:
            with transaction.atomic():
                feeder = isr_writer._persist_proposal(
                    source=src, dest=HQ, kind=P.KIND_BRANCH_TO_HQ, lines=lines_for(src, src_moves),
                    run_id=plan.run_id, created_by=user, planner='distribution',
                    params={**base, 'part': 'feed'}, notes=f'التوزيعة — خطة #{plan.pk}: من فرع {src} إلى الرئيسي')
                if feeder is None:
                    raise isr_guards.GuardError(f'لا توجد أسطر صالحة لفرع {src}.', code='empty')
                parts = []
                for dest in afters:
                    ms = by_doc[('after', dest, src)]
                    p = isr_writer._persist_proposal(
                        source=HQ, dest=dest, kind=P.KIND_HQ_TO_BRANCH, lines=lines_for(HQ, ms),
                        run_id=plan.run_id, created_by=user, linked=feeder, planner='distribution',
                        route_tag=f'dist:{src}', params={**base, 'part': 'after', 'waits_for': src},
                        notes=f'التوزيعة — خطة #{plan.pk}: بعد الاستلام من {src}')
                    if p is not None:
                        parts.append((dest, p, ms))
                feeder.params = {**feeder.params, 'feeds': [p.pk for _, p, _ in parts]}
                feeder.save(update_fields=['params'])
            record(feeder, 'feed', src_moves)
            for dest, p, ms in parts:
                record(p, 'after', ms)
        except ValueError as exc:
            skipped.append({'route': f'{src} ← {HQ}', 'path': [src, HQ], 'reason': str(exc)})
            plan.moves.filter(pk__in=[m.pk for m in src_moves]).update(status='blocked', status_note=str(exc)[:255])

    for key, ms in sorted(by_doc.items()):
        if key[0] != 'ready':
            continue
        dest = key[1]
        try:
            p = isr_writer._persist_proposal(
                source=HQ, dest=dest, kind=P.KIND_HQ_TO_BRANCH, lines=lines_for(HQ, ms), run_id=plan.run_id,
                created_by=user, planner='distribution', route_tag='dist', params={**base, 'part': 'ready'},
                notes=f'التوزيعة — خطة #{plan.pk}: جاهز الآن من الرئيسي')
        except ValueError as exc:
            skipped.append({'route': f'{HQ} ← {dest}', 'path': [HQ, dest], 'reason': str(exc)})
            plan.moves.filter(pk__in=[m.pk for m in ms]).update(status='blocked', status_note=str(exc)[:255])
            continue
        if p is not None:
            record(p, 'ready', ms)

    # this planner's older PROPOSED drafts on routes the new plan no longer uses
    for p in isr_guards._general(P.objects.filter(status=P.STATUS_PROPOSED, params__planner='distribution')
                                 ).exclude(pk__in=keep):
        isr_guards._cancel(p, user=user, reason=f'استُبدل بخطة التوزيعة #{plan.pk}')

    docs = list(plan.documents or [])
    by_route = {(c['source'], c['dest'], c['route_tag']): c['id'] for c in created}
    for d in docs:
        d['push_id'] = by_route.get((d['source'], d['dest'], d['route_tag']))
    plan.documents = docs
    plan.totals = _totals([{'status': m.status, 'value': float(m.value), 'wave': m.wave, 'qty': m.qty}
                           for m in plan.moves.all().only('status', 'value', 'wave', 'qty')])
    plan.save(update_fields=['documents', 'totals'])
    from apps.audit.models import AuditLog
    try:
        staff = getattr(user, 'staff_profile', None) if user is not None else None
        AuditLog.log('distribution_plan_generated', user=staff, obj=plan,
                     note=f'{len(created)} طلب توريد مقترح', extra={'created': [c['id'] for c in created],
                                                                    'skipped': len(skipped)})
    except Exception:
        logger.warning('distribution plan audit failed for %s', plan.pk)
    return {'created': created, 'skipped': skipped}
