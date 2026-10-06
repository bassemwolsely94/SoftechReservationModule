"""
apps/replacement/reconstruct.py — Phase 0 historical reconstruction (doc 25 §13 P0).

READ-ONLY with respect to SOFTECH: every input is an existing Postgres mirror —
  finance.APInvoice / Payment / Allocation / ReturnLink / MatchCandidate  (A/P sub-ledger)
  procurement.PurchaseLine                                                (purchase lines)
  customers.PurchaseHistory / PurchaseHistoryLine                        (sales + lines)
One ReplacementCase per virtual-supplier purchase. Idempotent: re-running refreshes
snapshots, appends only NEW ledger facts, and never overrides a person's decision.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.lineage.models import DocumentEdge as Edge, DocumentRef as Ref

from . import config as C
from . import ledger as L
from . import matching as M
from .models import CaseDocument as CD, CaseException as X, EntitlementLedgerEntry as E, \
    ReplacementCase as RC, ReplacementItem, ReconstructionRun

log = logging.getLogger(__name__)
D0 = Decimal('0')
CENT = Decimal('0.01')


def _q2(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT)


def _docno(v) -> str:
    return str(v or '').split('.')[0].strip()


# ─────────────────────────────────────────────────────────────────────────────
# DocumentRef upserts (display snapshot refreshed each run)
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_ref(kind, branchcode, doccode, docnumber, docdate, **display) -> Ref:
    ref, created = Ref.objects.get_or_create(
        system=Ref.SYSTEM_SOFTECH, branchcode=str(branchcode).strip(), doccode=str(doccode).strip(),
        docnumber=_docno(docnumber), docdate=docdate,
        defaults={'doc_kind': kind, **display})
    if not created:
        dirty = [k for k, v in display.items() if getattr(ref, k) != v]
        if dirty:
            for k in dirty:
                setattr(ref, k, display[k])
            ref.save(update_fields=dirty + ['updated_at'])
    return ref


def ref_for_apinvoice(inv) -> Ref:
    return _upsert_ref(Ref.KIND_SUPPLIER_RETURN if inv.doccode == '120' else Ref.KIND_PURCHASE,
                       inv.branchcode, inv.doccode, inv.docnumber, inv.docdate,
                       amount=inv.doc_value, party_code=inv.party.softech_personcode,
                       party_name=inv.party.name[:300], usercode=inv.usercode or '',
                       doc_time=inv.trans_time, source_model='finance.apinvoice', source_pk=inv.pk)


def ref_for_payment(p) -> Ref:
    return _upsert_ref(Ref.KIND_VOUCHER, p.branchcode, Ref.DOCCODE_VOUCHER, p.cheqsno, p.voucher_date,
                       amount=p.amount, party_code=p.party.softech_personcode,
                       party_name=p.party.name[:300], usercode=p.usercode or '',
                       doc_time=p.trans_time, note=(p.note or '')[:300],
                       source_model='finance.payment', source_pk=p.pk)


def _local_date(dt):
    return timezone.localtime(dt).date() if dt else None


def ref_for_sale(ph) -> Ref:
    kind = Ref.KIND_SALE_RETURN if ph.doc_code == '30' else Ref.KIND_SALE
    return _upsert_ref(kind, ph.branch.softech_branch_id, ph.doc_code or '115',
                       ph.docnumber or ph.softech_invoice_id.split('-')[2], _local_date(ph.invoice_date),
                       amount=ph.total_amount, phcode=(ph.softech_phcode or '').strip(),
                       channel=ph.sales_channel or '', party_code=ph.cust_branch_code or '',
                       usercode=ph.softech_user or '', doc_time=ph.trans_time,
                       source_model='customers.purchasehistory', source_pk=ph.pk)


def _edge(from_ref, to_ref, relation, *, origin, status, amount=None, confidence=0, evidence=None):
    """Create/refresh an edge; a person's decision (decided_by set) is never overwritten."""
    e, created = Edge.objects.get_or_create(
        from_ref=from_ref, to_ref=to_ref, relation=relation,
        defaults={'origin': origin, 'status': status, 'amount': amount,
                  'confidence': confidence, 'evidence': evidence or []})
    if not created and e.decided_by_id is None and (
            e.status != status or e.amount != amount or e.confidence != Decimal(str(confidence))):
        e.status, e.amount, e.confidence, e.evidence = status, amount, confidence, evidence or []
        e.save(update_fields=['status', 'amount', 'confidence', 'evidence', 'updated_at'])
    return e


def _casedoc(case, ref, role, *, status, origin='matched', confidence=0, evidence=None,
             parent=None, amount=None) -> CD:
    cd, created = CD.objects.get_or_create(
        case=case, document=ref, role=role,
        defaults={'status': status, 'origin': origin, 'confidence': confidence,
                  'evidence': evidence or [], 'parent': parent, 'amount': amount})
    if not created and cd.origin != 'manual':
        cd.status, cd.confidence, cd.evidence, cd.parent, cd.amount = \
            status, confidence, evidence or [], parent, amount
        cd.save(update_fields=['status', 'confidence', 'evidence', 'parent', 'amount', 'updated_at'])
    return cd


# ─────────────────────────────────────────────────────────────────────────────
# Loading mirror data as plain dicts for the pure matcher
# ─────────────────────────────────────────────────────────────────────────────

def _purchase_lines(inv):
    """Lines of the purchase from procurement.PurchaseLine. Rows synced before the 2026-06-25
    Sybase date fix carry doc_date ONE DAY EARLY, so match docdate or docdate−1 (supplier +
    per-branch serial keep it unambiguous) and prefer the exact date when both exist."""
    from apps.procurement.models import PurchaseLine
    base = PurchaseLine.objects.filter(branch_code=inv.branchcode, doc_number=_docno(inv.docnumber),
                                       supplier_code=inv.party.softech_personcode, doccode='10')
    rows = base.filter(doc_date=inv.docdate)
    if not rows.exists():
        rows = base.filter(doc_date=inv.docdate - timedelta(days=1))
    rows = rows.select_related('item')
    return [{'itemcode': r.item_code, 'item': r.item, 'qty': r.raw_qty, 'public': r.public_price,
             'value': r.raw_value, 'unit': r.unit_price} for r in rows]


def _sale_dict(ph) -> dict:
    lines = {}
    for ln in ph.lines.all():
        code = ln.item.softech_id if ln.item_id else None
        if not code:
            continue
        cur = lines.get(code)
        if cur:
            cur['qty'] += ln.quantity
        else:
            lines[code] = {'qty': ln.quantity, 'unit': ln.unit_price, 'list': ln.list_price,
                           'name': ln.item.name, 'item': ln.item}
    return {'key': ph.pk, 'obj': ph, 'phcode': (ph.softech_phcode or '').strip(),
            'date': _local_date(ph.invoice_date), 'total': ph.total_amount, 'lines': lines,
            'trans_time': ph.trans_time, 'channel': ph.sales_channel}


def _contract_candidates(inv, itemcodes):
    from apps.customers.models import PurchaseHistory
    lo = inv.docdate - timedelta(days=C.get('SALE_BEFORE_PURCHASE_DAYS'))
    hi = inv.docdate + timedelta(days=C.get('SALE_AFTER_PURCHASE_DAYS'))
    base = PurchaseHistory.objects.filter(
        branch__softech_branch_id=inv.branchcode, sales_channel__in=C.CONTRACT_CHANNELS,
        invoice_date__date__gte=lo).select_related('branch').prefetch_related('lines__item')
    sales = list(base.filter(doc_code='115', invoice_date__date__lte=hi,
                             lines__item__softech_id__in=itemcodes).distinct())
    phcodes = {(s.softech_phcode or '').strip() for s in sales} - {''}
    returns = []
    if phcodes:
        returns = list(base.filter(doc_code='30', softech_phcode__in=phcodes,
                                   invoice_date__date__lte=hi + timedelta(days=C.get('RETURN_PAIR_DAYS'))))
    # the chain can include same-patient contract sales WITHOUT the item (for return pairing)
    return [_sale_dict(s) for s in sales if (s.softech_phcode or '').strip()], [_sale_dict(r) for r in returns]


def _claimed_capacity(case, sale_keys, itemcodes):
    """Quantities of these sales' lines already bought back by EARLIER cases — ordered by
    (purchase_date, id) so the result never depends on the order a run happens to visit
    invoices. Returns ({(sale_pk, itemcode): qty}, {(sale_pk, itemcode): [case numbers]})."""
    claimed, claimers = {}, {}
    if not sale_keys:
        return claimed, claimers
    earlier = Q(purchase_date__lt=case.purchase_date) | Q(purchase_date=case.purchase_date, pk__lt=case.pk)
    links = (CD.objects.filter(role=CD.ROLE_CONTRACT_SALE, document__source_model='customers.purchasehistory',
                               document__source_pk__in=sale_keys)
             .exclude(case=case).filter(case__in=RC.objects.filter(earlier))
             .values_list('case_id', 'case__number', 'document__source_pk'))
    by_case = {}
    for cid, num, spk in links:
        by_case.setdefault(cid, (num, set()))[1].add(spk)
    if not by_case:
        return claimed, claimers
    for it in ReplacementItem.objects.filter(case_id__in=by_case, itemcode__in=itemcodes,
                                             disposition=ReplacementItem.DISP_REPLACED):
        num, spks = by_case[it.case_id]
        for spk in spks:
            claimed[(spk, it.itemcode)] = claimed.get((spk, it.itemcode), D0) + it.qty_replaced
            claimers.setdefault((spk, it.itemcode), []).append(num or str(it.case_id))
    return claimed, claimers


def _voucher_day_patients(inv, candidate_phcodes) -> frozenset:
    """Which candidate patients have non-contract receipts at the purchase branch on the day
    of one of the purchase's native vouchers (the redemption names the patient)."""
    from apps.customers.models import PurchaseHistory
    from apps.finance.recon_models import Allocation
    candidate_phcodes = {p for p in candidate_phcodes if p}
    if len(candidate_phcodes) < 2:
        return frozenset()
    days = set(Allocation.objects.filter(invoice=inv, origin__in=['softech', 'written'])
               .values_list('payment__voucher_date', flat=True))
    if not days:
        return frozenset()
    seen = (PurchaseHistory.objects.filter(branch__softech_branch_id=inv.branchcode, doc_code='115',
                                           invoice_date__date__in=days, softech_phcode__in=candidate_phcodes)
            .exclude(sales_channel__in=C.NON_REDEMPTION_CHANNELS)
            .values_list('softech_phcode', flat=True).distinct())
    return frozenset(p.strip() for p in seen)


def _same_day_receipts(branchcode, day, v_time, case):
    """Candidate redemption receipts for one voucher: same branch + day, non-contract, inside
    the widest funding window (receipts without a clock are kept — the matcher decides),
    minus receipts already claimed by ANOTHER case or rejected for this voucher."""
    from apps.customers.models import PurchaseHistory
    qs = (PurchaseHistory.objects.filter(branch__softech_branch_id=branchcode, doc_code='115',
                                         invoice_date__date=day)
          .exclude(sales_channel__in=C.NON_REDEMPTION_CHANNELS).select_related('branch'))
    if v_time is not None:
        lo = v_time - timedelta(minutes=max(C.get('FUND_PATIENT_BEFORE_MIN'), C.get('FUND_ANON_BEFORE_MIN')))
        hi = v_time + timedelta(minutes=max(C.get('FUND_PATIENT_AFTER_MIN'), C.get('FUND_ANON_AFTER_MIN')))
        qs = qs.filter(Q(trans_time__range=(lo, hi)) | Q(trans_time__isnull=True))
    rows = list(qs)
    ids = [r.pk for r in rows]
    claimed = set(CD.objects.filter(role=CD.ROLE_PRODUCT_SALE, document__source_model='customers.purchasehistory',
                                    document__source_pk__in=ids,
                                    status__in=[CD.STATUS_PROPOSED, CD.STATUS_CONFIRMED])
                  .exclude(case=case).values_list('document__source_pk', flat=True))
    return [{'key': r.pk, 'obj': r, 'amount': r.total_amount, 'phcode': (r.softech_phcode or '').strip(),
             'trans_time': r.trans_time} for r in rows if r.pk not in claimed]


def tabdeel_pics() -> frozenset:
    from apps.customers.models import Customer
    return frozenset(p.strip() for p in Customer.objects.filter(
        Q(name__contains='تبديل') | Q(name__contains='استبدال')).values_list('softech_pic', flat=True) if p)


# ─────────────────────────────────────────────────────────────────────────────
# Case reconstruction
# ─────────────────────────────────────────────────────────────────────────────

def _own_receipts(case) -> dict:
    """{PurchaseHistory pk: PostingOperation} for the settled product sales a LIVE case created
    (pos_orders reconciler fills softech_final_docnumber when the cashier settles)."""
    if case.origin != RC.ORIGIN_LIVE:
        return {}
    from apps.customers.models import PurchaseHistory
    from .models import PostingOperation as Op
    out = {}
    for op in case.operations.filter(kind=Op.KIND_PRODUCT_SALE, sales_order__softech_final_docnumber__isnull=False) \
            .select_related('sales_order'):
        so = op.sales_order
        ph = PurchaseHistory.objects.filter(branch__softech_branch_id=so.softech_branchcode, doc_code='115',
                                            docnumber=str(int(so.softech_final_docnumber))).order_by('-invoice_date').first()
        if ph is not None:
            out[ph.pk] = op
    return out


def _live_case_for(inv, p_ref):
    """A live case whose purchase leg posted this very invoice (by the writer's returned docnumber
    on the same branch). Re-points the case to the mirror's DocumentRef if the date differed."""
    from .models import PostingOperation as Op
    op = (Op.objects.filter(kind=Op.KIND_PURCHASE, status=Op.ST_VERIFIED, result_docnumber=_docno(inv.docnumber),
                            supplier_invoice__softech_branchcode=inv.branchcode,
                            supplier_invoice__vendor__softech_personcode=inv.party.softech_personcode)
          .select_related('case').first())
    if op is None:
        return None
    case = RC.objects.select_for_update().get(pk=op.case_id)
    if case.purchase_ref_id != p_ref.pk:
        old = case.purchase_ref
        if old is not None:
            for e in L.active_entries(case, old).filter(entry_type=E.TYPE_CREATED):
                L.reverse(e, note='إعادة ربط فاتورة الشراء بمستند SOFTECH الفعلي')
            CD.objects.filter(case=case, document=old, role=CD.ROLE_PURCHASE).delete()
        case.purchase_ref = p_ref
        case.save(update_fields=['purchase_ref', 'updated_at'])
    return case


def _source_type(code, sale_matched):
    cfg = C.supplier_cfg(code)
    if cfg.get('family') == 'general':
        return RC.SOURCE_CLIENT_BUYBACK
    if cfg.get('expects_sale') is False and not sale_matched:
        return RC.SOURCE_INSURANCE_EXTERNAL
    if code == '4470' and not sale_matched:
        return RC.SOURCE_INSURANCE_EXTERNAL
    return RC.SOURCE_INSURANCE_RX


def _expects_cash(code, sale_matched):
    cfg = C.supplier_cfg(code)
    return cfg.get('default_mode') == 'cash' or (code == '4470' and sale_matched)


@transaction.atomic
def reconstruct_invoice(inv, *, tabdeel=frozenset(), user=None) -> dict:
    """Build or refresh the case anchored on one virtual-supplier purchase invoice."""
    from apps.branches.models import Branch
    from apps.customers.models import Customer
    from apps.finance.recon_models import Allocation, MatchCandidate, ReturnLink

    code = inv.party.softech_personcode
    cfg = C.supplier_cfg(code)
    p_ref = ref_for_apinvoice(inv)
    case = RC.objects.select_for_update().filter(purchase_ref=p_ref).first()
    if case is None:
        case = _live_case_for(inv, p_ref)         # posted from a live case → attach, never duplicate
    created = case is None
    live = not created and case.origin == RC.ORIGIN_LIVE
    if created:
        case = RC(purchase_ref=p_ref, origin=RC.ORIGIN_RECONSTRUCTED, source_type=RC.SOURCE_INSURANCE_RX,
                  branchcode=inv.branchcode, supplier_personcode=code, purchase_date=inv.docdate,
                  status=RC.STATUS_ENTITLEMENT_ACTIVE)
    case.purchase_invoice = inv
    case.branch = Branch.objects.filter(softech_branch_id=inv.branchcode).first()
    case.supplier_name = inv.party.name[:300]
    case.entitlement = _q2(inv.doc_value)
    case.supplier_tier_pct = cfg.get('tier')
    case.rules_version = C.RULES_VERSION
    case.save()
    _casedoc(case, p_ref, CD.ROLE_PURCHASE, status=CD.STATUS_CONFIRMED, origin='native',
             confidence=100, amount=_q2(inv.doc_value))
    issues = {}      # (type, key) → dict(severity, amount, detail, evidence)

    def issue(t, sev, key='', amount=None, detail='', evidence=None):
        issues[(t, str(key))] = {'severity': sev, 'amount': amount, 'detail': detail,
                                 'evidence': evidence or {}}

    # ── 1. purchase lines (the replaced items) ─────────────────────────────────
    # A LIVE case already knows its items, patient, contract and source from the operator and its
    # approved calculation — reconstruction must not overwrite them; it only checks the native
    # purchase against what was approved, then books vouchers / returns (steps 3–6).
    if live:
        calc = case.current_calc
        if calc and abs(_q2(inv.doc_value) - calc.entitlement) > Decimal('0.05'):
            issue('purchase_value_mismatch', X.SEV_HIGH, amount=_q2(inv.doc_value) - calc.entitlement,
                  detail=f'فاتورة الشراء في SOFTECH = {_q2(inv.doc_value)} والرصيد المعتمد = {calc.entitlement}')
    plines = [] if live else _purchase_lines(inv)
    if not plines and not live:
        issue('purchase_lines_missing', X.SEV_WARNING, detail='procurement.PurchaseLine لا يحتوي أصناف هذه الفاتورة')
    applied = M.applied_deduction_pct(plines) if plines else None
    case.applied_deduction_pct = applied
    case.public_value = _q2(sum((Decimal(l['public']) * Decimal(l['qty']) for l in plines), D0))
    if applied is not None and cfg.get('tier') is not None and \
            abs(applied - cfg['tier']) > C.get('RATE_DEVIATION_PP'):
        issue('rate_deviation', X.SEV_WARNING, amount=None,
              detail=f'الخصم المطبق {applied}% مقابل فئة المورد {cfg["tier"]}%',
              evidence={'applied': str(applied), 'tier': str(cfg['tier'])})

    # ── 2. contract sale chain → patient ──────────────────────────────────────
    purchase = {'date': inv.docdate, 'trans_time': inv.trans_time,
                'lines': {l['itemcode']: {'qty': l['qty'], 'public': l['public']} for l in plines}}
    res = {'sale': None}
    if plines:
        sales, returns = _contract_candidates(inv, list(purchase['lines']))
        claimed, claimers = _claimed_capacity(case, [s['key'] for s in sales], list(purchase['lines']))
        res = M.resolve_contract_sale(purchase, sales, returns,
                                      patient_hint=_voucher_day_patients(inv, {s['phcode'] for s in sales}),
                                      claimed=claimed)
        if res['sale'] is not None and res['conf'] == 'low' and not res.get('over_claim'):
            issue('no_contract_sale', X.SEV_INFO, detail='أفضل مرشح منخفض الثقة — لم يُربط',
                  evidence={'best_sale': res['sale']['obj'].softech_invoice_id,
                            'score': float(res['score']), 'signals': res['evidence']})
            res = {'sale': None}
    sale = res['sale']
    if not live:
        CD.objects.filter(case=case, role__in=[CD.ROLE_CONTRACT_SALE, CD.ROLE_CONTRACT_RETURN,
                                               CD.ROLE_CONTRACT_VOID]).exclude(origin='manual').delete()
        case.items.all().delete()
    if live:
        pass
    elif sale:
        s_ref = ref_for_sale(sale['obj'])
        st = CD.STATUS_CONFIRMED if res['conf'] == 'high' else CD.STATUS_PROPOSED
        _casedoc(case, s_ref, CD.ROLE_CONTRACT_SALE, status=st, confidence=res['score'],
                 evidence=res['evidence'], amount=_q2(sale['total']))
        for r in res['partial_returns']:
            r_ref = ref_for_sale(r['obj'])
            _casedoc(case, r_ref, CD.ROLE_CONTRACT_RETURN, status=st, confidence=res['score'],
                     amount=_q2(r['total']))
            _edge(r_ref, s_ref, Edge.REL_RETURNS, origin=Edge.ORIGIN_MATCHED, status=Edge.STATUS_CONFIRMED,
                  amount=_q2(r['total']), confidence=90)
        for vs, vr in res['void_pairs']:
            vs_ref, vr_ref = ref_for_sale(vs['obj']), ref_for_sale(vr['obj'])
            _casedoc(case, vs_ref, CD.ROLE_CONTRACT_VOID, status=CD.STATUS_CONFIRMED, amount=_q2(vs['total']))
            _casedoc(case, vr_ref, CD.ROLE_CONTRACT_VOID, status=CD.STATUS_CONFIRMED, amount=_q2(vr['total']))
            _edge(vr_ref, vs_ref, Edge.REL_CANCELS, origin=Edge.ORIGIN_MATCHED, status=Edge.STATUS_CONFIRMED,
                  amount=_q2(vs['total']), confidence=95,
                  evidence=[{'signal': 'full_return', 'points': 95,
                             'detail': 'مرتجع كامل بنفس القيمة ونفس الأصناف خلال أيام من البيع'}])
        case.softech_pic = sale['phcode']
        case.contract_personcode = (sale['obj'].cust_branch_code or '').strip()
        cust = Customer.objects.filter(softech_pic__iexact=sale['phcode']).first()
        case.customer, case.patient_name = cust, (cust.name if cust else '')
        case.contract_value = _q2(sum((Decimal(res['eff_lines'][c]['unit']) * Decimal(purchase['lines'][c]['qty'])
                                       for c in purchase['lines'] if c in res['eff_lines']), D0))
        if res['ambiguous_patients']:
            issue('ambiguous_patient', X.SEV_WARNING, detail='مرضى آخرون لديهم بيع تعاقد مماثل',
                  evidence={'patients': res['ambiguous_patients']})
        # prescribed-but-dispensed items (traceability: what the patient actually took)
        for c, v in res['eff_lines'].items():
            if c not in purchase['lines']:
                ReplacementItem.objects.create(
                    case=case, item=v.get('item'), itemcode=c, item_name=(v.get('name') or '')[:255],
                    disposition=ReplacementItem.DISP_DISPENSED, qty_prescribed=v['qty'], qty_replaced=0,
                    public_unit_price=v.get('list') or 0, contract_unit_price=v.get('unit'))
        # duplicate = OVER-CLAIM: purchases of this sale line exceed the quantity actually sold
        if res.get('over_claim'):
            over_items = {l['itemcode'] for l in res['over_claim']}
            earlier = sorted({n for (sk, code), lst in claimers.items()
                              if sk == sale['key'] and code in over_items for n in lst})
            if earlier:
                # units of this sale were ALREADY bought back by earlier case(s) → true duplicate
                issue('duplicate_purchase', X.SEV_HIGH,
                      detail='الكمية المشتراة تتجاوز المباع بعد خصم ما اشتُري سابقاً في: ' + '، '.join(earlier),
                      evidence={'lines': res['over_claim'], 'earlier_cases': earlier})
            else:
                # one sale simply holds fewer units than were bought back — the patient may be
                # returning medicine accumulated over several prescriptions (multi-sale: Phase 1)
                issue('qty_exceeds_sale', X.SEV_WARNING,
                      detail='الكمية المشتراة أكبر من كمية فاتورة التعاقد المطابقة — قد تغطي أكثر من روشتة',
                      evidence={'lines': res['over_claim']})
    else:
        case.softech_pic = case.softech_pic if case.origin == RC.ORIGIN_LIVE else ''
        case.contract_personcode, case.contract_value = '', D0
        if plines and cfg.get('expects_sale') is not False:
            sev = X.SEV_WARNING if cfg.get('expects_sale') else X.SEV_INFO
            issues.setdefault(('no_contract_sale', ''), {
                'severity': sev, 'amount': None, 'evidence': {},
                'detail': 'لم يُعثر على فاتورة تعاقد بنفس الصنف في نافذة '
                          f'{C.get("SALE_BEFORE_PURCHASE_DAYS")}/{C.get("SALE_AFTER_PURCHASE_DAYS")} يوم'})
    for l in plines:
        ev = res.get('eff_lines', {}).get(l['itemcode']) if sale else None
        ReplacementItem.objects.create(
            case=case, item=l['item'], itemcode=l['itemcode'], item_name=(l['item'].name if l['item'] else '')[:255],
            disposition=ReplacementItem.DISP_REPLACED,
            qty_prescribed=ev['qty'] if ev else None, qty_replaced=l['qty'],
            public_unit_price=l['public'], contract_unit_price=ev['unit'] if ev else None,
            purchase_unit_price=l['unit'], applied_deduction_pct=M.applied_deduction_pct([l]))
    if live:
        sale_matched = case.documents.filter(role=CD.ROLE_CONTRACT_SALE, status=CD.STATUS_CONFIRMED).exists()
    else:
        sale_matched = sale is not None
        case.source_type = _source_type(code, sale_matched)

    # ── 3. entitlement credit ─────────────────────────────────────────────────
    L.ensure(case, E.TYPE_CREATED, _q2(inv.doc_value), document=p_ref,
             note=f'فاتورة شراء {inv.branchcode}/{_docno(inv.docnumber)} — {case.supplier_name}')

    # ── 4. vouchers (native allocations) → funding → ledger debits ─────────────
    native = list(Allocation.objects.filter(invoice=inv, origin__in=[Allocation.ORIGIN_SOFTECH,
                                                                     Allocation.ORIGIN_WRITTEN])
                  .select_related('payment__party', 'candidate').order_by('payment__voucher_date', 'payment__cheqsno'))
    live_voucher_refs = set()
    absorbed = topup = D0
    for a in native:
        pay = a.payment
        v_ref = ref_for_payment(pay)
        live_voucher_refs.add(v_ref.pk)
        amt = _q2(a.amount)
        v_cd = _casedoc(case, v_ref, CD.ROLE_VOUCHER, status=CD.STATUS_CONFIRMED, origin='native',
                        confidence=100, amount=amt)
        _edge(v_ref, p_ref, Edge.REL_PAYS, origin=Edge.ORIGIN_NATIVE, status=Edge.STATUS_CONFIRMED,
              amount=amt, confidence=100)
        if pay.branchcode != inv.branchcode:
            # Owner 2026-10-02: contract-patient payments never cross branches. A cross-branch link
            # our own A/P writer created (origin 'written') on a contract supplier is most likely a
            # wrong allocation we posted into SOFTECH → HIGH. Branch-to-branch buying is legitimate
            # on the general accounts (3068/4069) → info.
            ours = a.origin == Allocation.ORIGIN_WRITTEN
            if cfg.get('family') == 'general':
                sev = X.SEV_INFO
            else:
                sev = X.SEV_HIGH if ours else X.SEV_WARNING
            issue('cross_branch_voucher', sev, key=v_ref.pk, amount=amt,
                  detail=f'السند من فرع {pay.branchcode} والشراء من فرع {inv.branchcode}'
                         + (' — الربط كتبه معالج سداد الموردين في SOFTECH (غالباً خاطئ)' if ours else ' — ربط أصلي من SOFTECH'),
                  evidence={'allocation_id': a.pk, 'origin': a.origin,
                            'strategy': a.candidate.strategy if a.candidate_id else ''})
        if pay.chain_role == 'reversed':
            issue('voucher_reversed', X.SEV_INFO, key=v_ref.pk, amount=amt,
                  detail='السند مُلغى بسند مقبوضات لاحق (سلسلة تصحيح)')

        f = _fund_voucher(case, v_ref, v_cd, pay, amt, tabdeel, sale_matched, code, issue)
        if f['excess_kind'] == 'absorbed':
            absorbed += f['excess']
        elif f['excess_kind'] == 'customer_topup':
            topup += f['excess']
        L.reclassify_voucher(case, v_ref, f['product'], f['cash'], f['unclassified'],
                             note=f'سند {pay.branchcode}/{pay.cheqsno}', user=user)

    # native link removed since we booked it → reverse our debits (keeps I-1 true)
    for e in L.active_entries(case).filter(entry_type__in=[E.TYPE_PRODUCT, E.TYPE_CASH, E.TYPE_UNCLASSIFIED]) \
            .exclude(document_id__in=live_voucher_refs):
        L.reverse(e, note='السند لم يعد مربوطاً بالفاتورة في SOFTECH', user=user)

    # ── 5. supplier returns (120) ─────────────────────────────────────────────
    # A return reduces the entitlement. SOFTECH then CLOSES the return through a voucher
    # allocation — either a مقبوضات (patient hands the cash back) or netting inside a
    # payment voucher (docvaluepaynow on the return row). That settlement restores value
    # (+), so only the still-OPEN part of a return leaves the case negative: real money
    # the patient still owes back.
    open_returns = D0
    for rl in ReturnLink.objects.filter(purchase_invoice=inv).select_related('return_invoice__party'):
        ret = rl.return_invoice
        r_ref = ref_for_apinvoice(ret)
        amt = _q2(ret.doc_value or rl.amount)
        _casedoc(case, r_ref, CD.ROLE_SUPPLIER_RETURN, status=CD.STATUS_CONFIRMED, origin='native',
                 confidence=100, amount=amt)
        _edge(r_ref, p_ref, Edge.REL_RETURNS, origin=Edge.ORIGIN_NATIVE, status=Edge.STATUS_CONFIRMED,
              amount=amt, confidence=100)
        L.ensure(case, E.TYPE_SUPPLIER_RET, -amt, document=r_ref, note='مرتجع للمورد')
        settled = D0
        r_cd = case.documents.get(document=r_ref, role=CD.ROLE_SUPPLIER_RETURN)
        for ra in Allocation.objects.filter(invoice=ret, origin__in=[Allocation.ORIGIN_SOFTECH,
                                                                     Allocation.ORIGIN_WRITTEN]) \
                .select_related('payment__party'):
            rv_ref = ref_for_payment(ra.payment)
            settled += _q2(ra.amount)
            _casedoc(case, rv_ref, CD.ROLE_RETURN_SETTLEMENT, status=CD.STATUS_CONFIRMED, origin='native',
                     confidence=100, amount=_q2(ra.amount), parent=r_cd)
            _edge(rv_ref, r_ref, Edge.REL_PAYS, origin=Edge.ORIGIN_NATIVE, status=Edge.STATUS_CONFIRMED,
                  amount=_q2(ra.amount), confidence=100)
            L.ensure(case, E.TYPE_RETURN_SETTLED, _q2(ra.amount), document=rv_ref,
                     note=f'تسوية المرتجع {ret.docnumber} بسند {ra.payment.branchcode}/{ra.payment.cheqsno}')
        open_part = max(D0, amt - settled)
        open_returns += open_part
        issue('supplier_return', X.SEV_INFO, key=r_ref.pk, amount=amt,
              detail=f'مرتجع للمورد {amt} — مُسوّى {settled}' + (f' — مفتوح {open_part}' if open_part else ''))

    # ── 6. snapshots + invariants ────────────────────────────────────────────
    t = L.totals(case)
    case.redeemed_products = -t['product']
    case.redeemed_cash = -t['cash']
    case.redeemed_unclassified = -t['unclassified']
    case.reversed_by_return = -(t['supplier_return'] + t['return_settled'])   # still-open return effect
    case.absorbed, case.customer_topup = absorbed, topup
    case.outstanding = _q2(L.balance(case))
    case.native_outstanding = _q2(inv.doc_value - sum((a.amount for a in native), D0) - open_returns)
    if abs(case.outstanding - case.native_outstanding) > CENT:
        issue('ledger_native_mismatch', X.SEV_CRITICAL, amount=case.outstanding - case.native_outstanding,
              detail=f'رصيد الدفتر {case.outstanding} ≠ رصيد SOFTECH {case.native_outstanding}')
    if case.outstanding < -CENT:
        issue('negative_entitlement', X.SEV_HIGH, amount=case.outstanding,
              detail='الرصيد سالب — صُرف للمريض أكثر من رصيده بعد المرتجع (مبلغ مستحق الاسترداد)')
    if case.outstanding > CENT:
        age = (timezone.localdate() - inv.docdate).days
        if age > C.get('AGED_OUTSTANDING_DAYS'):
            issue('aged_outstanding', X.SEV_WARNING, amount=case.outstanding,
                  detail=f'رصيد قائم منذ {age} يوم')
        cands = list(MatchCandidate.objects.filter(invoice=inv, status__in=['proposed', 'approved'])
                     .select_related('payment').order_by('-confidence_score')[:5])
        if cands:
            issue('unlinked_voucher_likely', X.SEV_INFO, amount=case.outstanding,
                  detail='يوجد سند صرف غير مربوط يُحتمل أنه سدد هذا الرصيد (مطابقة الموردين)',
                  evidence={'candidates': [{'voucher': f'{c.payment.branchcode}/{c.payment.cheqsno}',
                                            'amount': str(c.proposed_amount),
                                            'confidence': str(c.confidence_score),
                                            'status': c.status} for c in cands]})

    prod, cash = case.redeemed_products, case.redeemed_cash
    case.settlement_mode = (RC.MODE_MIXED if prod > 0 and cash > 0 else RC.MODE_PRODUCTS if prod > 0
                            else RC.MODE_CASH if cash > 0 else RC.MODE_PENDING)
    _sync_exceptions(case, issues)
    confs = list(case.documents.exclude(role=CD.ROLE_PURCHASE).values_list('confidence', flat=True))
    case.link_confidence = C.conf_class(min(confs)) if confs else ''
    open_proposed = case.documents.filter(status=CD.STATUS_PROPOSED).exists()
    if case.outstanding > CENT:
        case.status = RC.STATUS_ENTITLEMENT_ACTIVE
    elif (case.redeemed_unclassified == 0 and not open_proposed and
          not case.exceptions.filter(status=X.STATUS_OPEN, severity__in=X.BLOCKING).exists()):
        case.status = RC.STATUS_RECONCILED
    else:
        case.status = RC.STATUS_SETTLED
    case.reconstructed_at = timezone.now()
    case.save()
    case.assign_number()
    if created:
        from apps.audit.models import AuditLog
        AuditLog.log('replacement_case_reconstructed', user=user, obj=case,
                     new_data={'purchase': str(p_ref), 'pic': case.softech_pic,
                               'entitlement': str(case.entitlement), 'outstanding': str(case.outstanding)},
                     extra={'correlation_id': str(case.correlation_id), 'rules_version': C.RULES_VERSION})
    return {'case': case, 'created': created}


def _fund_voucher(case, v_ref, v_cd, pay, amt, tabdeel, sale_matched, code, issue):
    """Decide which receipts the voucher's cash paid for. Human decisions win."""
    human = list(Edge.objects.filter(from_ref=v_ref, relation=Edge.REL_FUNDED_BY,
                                     decided_by__isnull=False).select_related('to_ref'))
    rejected = {e.to_ref_id for e in human if e.status == Edge.STATUS_REJECTED}
    confirmed = [e for e in human if e.status == Edge.STATUS_CONFIRMED]

    if confirmed:
        total = sum((e.to_ref.amount for e in confirmed), D0)
        fund = {'receipts': [], 'total': total, 'product': min(total, amt),
                'cash_remainder': max(D0, amt - total), 'excess': max(D0, total - amt),
                'status': 'confirmed', 'conf': 'high', 'score': Decimal('100'), 'evidence': [],
                'anonymous': False}
        absorb = max(C.get('ABSORB_ABS'), (amt * C.get('ABSORB_PCT')).quantize(CENT))
        fund['excess_kind'] = '' if not fund['excess'] else (
            'absorbed' if fund['excess'] <= absorb else 'customer_topup')
        keep = set()
        for e in confirmed:
            keep.add(e.to_ref_id)
            _casedoc(case, e.to_ref, CD.ROLE_PRODUCT_SALE, status=CD.STATUS_CONFIRMED, origin='manual',
                     confidence=100, evidence=[{'signal': 'human', 'points': 100,
                                                'detail': f'أكده {e.decided_by.full_name if e.decided_by_id else ""}'}],
                     parent=v_cd, amount=_q2(e.to_ref.amount))
        Edge.objects.filter(from_ref=v_ref, relation=Edge.REL_FUNDED_BY, decided_by__isnull=True) \
            .exclude(to_ref_id__in=keep).update(status=Edge.STATUS_SUPERSEDED)
        CD.objects.filter(case=case, role=CD.ROLE_PRODUCT_SALE, parent=v_cd) \
            .exclude(document_id__in=keep).exclude(status=CD.STATUS_REJECTED).delete()
    else:
        rejected_src = set(Ref.objects.filter(pk__in=rejected).values_list('source_pk', flat=True))
        pool = [r for r in _same_day_receipts(pay.branchcode, pay.voucher_date, pay.trans_time, case)
                if r['key'] not in rejected_src]
        own = _own_receipts(case)
        fund = M.select_funding({'amount': amt, 'trans_time': pay.trans_time}, pool, case.softech_pic,
                                tabdeel, known_keys=frozenset(own))
        for r in fund['receipts']:                       # live: mark the product op as voucher-funded
            op = own.get(r['key'])
            if op is not None and fund['status'] == 'confirmed' and 'voucher_linked' not in op.result:
                op.result = {**op.result, 'voucher_linked': f'{pay.branchcode}/{pay.cheqsno}'}
                op.status = op.ST_VERIFIED
                op.save(update_fields=['result', 'status', 'updated_at'])
        chosen_refs = set()
        for r in fund['receipts']:
            r_ref = ref_for_sale(r['obj'])
            chosen_refs.add(r_ref.pk)
            st = CD.STATUS_CONFIRMED if fund['status'] == 'confirmed' else CD.STATUS_PROPOSED
            _casedoc(case, r_ref, CD.ROLE_PRODUCT_SALE, status=st, confidence=fund['score'],
                     evidence=fund['evidence'], parent=v_cd, amount=_q2(r['amount']))
            _edge(v_ref, r_ref, Edge.REL_FUNDED_BY, origin=Edge.ORIGIN_MATCHED,
                  status=Edge.STATUS_CONFIRMED if st == CD.STATUS_CONFIRMED else Edge.STATUS_PROPOSED,
                  amount=_q2(r['amount']), confidence=fund['score'], evidence=fund['evidence'])
        # matcher-owned links that are no longer chosen → superseded (history kept on the edge)
        stale = Edge.objects.filter(from_ref=v_ref, relation=Edge.REL_FUNDED_BY, decided_by__isnull=True) \
            .exclude(to_ref_id__in=chosen_refs)
        stale.update(status=Edge.STATUS_SUPERSEDED)
        CD.objects.filter(case=case, role=CD.ROLE_PRODUCT_SALE, parent=v_cd).exclude(origin='manual') \
            .exclude(document_id__in=chosen_refs).delete()

    key = v_ref.pk
    if fund['status'] == 'confirmed':
        product, cash, uncl = fund['product'], fund['cash_remainder'], D0
        if cash > C.get('CASH_REMAINDER_ABS') and cash > amt * C.get('CASH_REMAINDER_PCT') \
                and not _expects_cash(code, sale_matched):
            issue('cash_remainder_high', X.SEV_WARNING, key=key, amount=cash,
                  detail=f'باقي نقدي {cash} من سند {amt} صُرف بسعر المنتجات (قاعدة C)')
        if fund['excess_kind'] == 'customer_topup':
            issue('receipts_exceed_voucher', X.SEV_INFO, key=key, amount=fund['excess'],
                  detail=f'فواتير المنتجات أكبر من السند بـ {fund["excess"]} (دفعها المريض)')
    elif fund['status'] == 'proposed':
        product, cash, uncl = D0, D0, amt
        if fund.get('anonymous'):
            issue('anonymous_receipt', X.SEV_INFO, key=key, amount=amt,
                  detail='فاتورة منتجات بدون كود مريض قريبة من السند — تحتاج تأكيد')
    elif _expects_cash(code, sale_matched):
        product, cash, uncl = D0, amt, D0
    else:
        product, cash, uncl = D0, D0, amt
        sev = X.SEV_WARNING if C.supplier_cfg(code).get('default_mode') == 'products' else X.SEV_INFO
        issue('voucher_without_receipt', sev, key=key, amount=amt,
              detail='لم يُعثر على فواتير منتجات لهذا السند في نفس اليوم — صرف نقدي أو فاتورة غير مربوطة')
    return {'product': product, 'cash': cash, 'unclassified': uncl,
            'excess': fund.get('excess', D0) if fund['status'] == 'confirmed' else D0,
            'excess_kind': fund.get('excess_kind', '') if fund['status'] == 'confirmed' else ''}


def _sync_exceptions(case, issues: dict):
    """Upsert detected exceptions; auto-clear previously-open ones that are no longer detected.
    Acknowledged/resolved exceptions are a person's decision and are never touched."""
    seen = set()
    for (t, key), d in issues.items():
        exc, created = X.objects.get_or_create(case=case, exception_type=t, key=key, defaults=d)
        seen.add(exc.pk)
        if not created and exc.status in (X.STATUS_OPEN, X.STATUS_CLEARED):
            exc.severity, exc.amount, exc.detail, exc.evidence = d['severity'], d['amount'], d['detail'], d['evidence']
            exc.status = X.STATUS_OPEN
            exc.save(update_fields=['severity', 'amount', 'detail', 'evidence', 'status', 'updated_at'])
    case.exceptions.filter(status=X.STATUS_OPEN).exclude(pk__in=seen).update(status=X.STATUS_CLEARED)
    recount_exceptions(case)


def recount_exceptions(case):
    """Refresh the case's exception counters (no detection, no status changes)."""
    open_ = list(case.exceptions.filter(status__in=[X.STATUS_OPEN, X.STATUS_ACK]).values_list('severity', flat=True))
    case.open_exceptions = len(open_)
    case.max_severity = max(open_, key=lambda s: X.SEVERITY_RANK[s]) if open_ else ''


# ─────────────────────────────────────────────────────────────────────────────
# Reset (Phase 0 only)
# ─────────────────────────────────────────────────────────────────────────────

def reset_blockers() -> list[str]:
    """Reasons a reset must be refused. Anything a PERSON did, or any live case, is history."""
    out = []
    if RC.objects.exclude(origin=RC.ORIGIN_RECONSTRUCTED).exists():
        out.append('توجد حالات تشغيلية (live)')
    if Edge.objects.filter(decided_by__isnull=False).exists():
        out.append('توجد قرارات ربط بشرية')
    if X.objects.filter(status__in=[X.STATUS_ACK, X.STATUS_RESOLVED]).exists():
        out.append('توجد استثناءات عالجها مستخدم')
    if CD.objects.filter(origin='manual').exists():
        out.append('توجد روابط يدوية')
    return out


def reset_reconstructed() -> dict:
    """Wipe DERIVED Phase-0 reconstruction output so a corrected rules version can rebuild it
    cleanly. Refused when any human decision or live case exists (see reset_blockers). The
    ledger is append-only for business history; a machine-derived rebuild with no human input
    is not history — this is the only path that removes it, and it is audited."""
    from django.db import connection
    blockers = reset_blockers()
    if blockers:
        raise RuntimeError('لا يمكن إعادة الضبط: ' + '، '.join(blockers))
    counts = {'cases': RC.objects.count(), 'ledger': E.objects.count(), 'documents': Ref.objects.count()}
    from .models import PostingOperation, ReplacementCalculation
    # explicit list (no CASCADE): only this module's derived tables. Live data (calculations,
    # operations) can't exist here — reset_blockers refuses whenever a live case exists.
    tables = [m._meta.db_table for m in (E, CD, X, ReplacementItem, ReplacementCalculation, PostingOperation,
                                         RC, Edge, Ref)]
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute('SET CONSTRAINTS ALL IMMEDIATE')     # flush deferred FK checks first
        # NO 'RESTART IDENTITY': ids must never be reused, or a new case would inherit the
        # AuditLog trail (model_name + object_id) of a wiped one.
        cur.execute('TRUNCATE ' + ', '.join(f'"{t}"' for t in tables))
    from apps.audit.models import AuditLog
    AuditLog.log('replacement_case_reconstructed', note='reset of reconstructed Phase-0 data',
                 extra={'reset': counts, 'rules_version': C.RULES_VERSION})
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# Batch driver
# ─────────────────────────────────────────────────────────────────────────────

def candidate_invoices(date_from=None, date_to=None, suppliers=None, branch=None):
    from apps.finance.recon_models import APInvoice
    qs = APInvoice.objects.filter(party__softech_personcode__in=suppliers or C.supplier_codes(),
                                  doccode='10').select_related('party')
    if date_from:
        qs = qs.filter(docdate__gte=date_from)
    if date_to:
        qs = qs.filter(docdate__lte=date_to)
    if branch:
        qs = qs.filter(branchcode=branch)
    return qs.order_by('docdate', 'id')


def run(date_from=None, date_to=None, suppliers=None, branch=None, limit=None, triggered_by='',
        progress=None) -> ReconstructionRun:
    params = {'date_from': str(date_from or ''), 'date_to': str(date_to or ''),
              'suppliers': suppliers or C.supplier_codes(), 'branch': branch or '', 'limit': limit}
    r = ReconstructionRun.objects.create(params=params, rules_version=C.RULES_VERSION,
                                         triggered_by=triggered_by[:100])
    counts = {'invoices': 0, 'created': 0, 'updated': 0, 'errors': 0}
    tabdeel = tabdeel_pics()
    qs = candidate_invoices(date_from, date_to, suppliers, branch)
    if limit:
        qs = qs[:limit]
    for inv in qs.iterator(chunk_size=200):
        counts['invoices'] += 1
        try:
            out = reconstruct_invoice(inv, tabdeel=tabdeel)
            counts['created' if out['created'] else 'updated'] += 1
        except Exception as exc:     # one bad invoice never aborts the run
            counts['errors'] += 1
            log.exception('replacement reconstruct failed for invoice %s', inv.pk)
            if counts['errors'] <= 20:
                r.notes += f'{inv.branchcode}/{inv.docnumber}: {exc}\n'
        if counts['invoices'] % 250 == 0:
            ReconstructionRun.objects.filter(pk=r.pk).update(counts=dict(counts))
            if progress:
                progress(counts)
    r.counts = counts
    r.status = 'success' if not counts['errors'] else 'partial'
    r.finished_at = timezone.now()
    r.save()
    return r
