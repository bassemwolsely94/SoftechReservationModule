"""
apps/insurance/roster.py

Patient ROSTERS — catch receipts entered under the wrong insurer / division.

A salesperson sometimes picks the wrong insurance entry at the till, so a patient
who belongs to insurer B lands on insurer A's motalba.  The insurer deducts it
and we have to re-bill it on a separate motalba later — collection is delayed.

Rosters are DERIVED, never typed: every patient name on an earlier, non-excluded
receipt is a member of the unit it was billed under.  They grow by themselves
each month.  A roster UNIT is

    جهة (InsuranceClient) → فئة (InsuranceSubClient) → فئة فوترة (billing group)

The billing-group level is matched across months by `group_key` (an
order-insensitive, Arabic-folded token key) because groups are re-created per
claim with slightly different spellings («تشغيل» / «التشغيل»).

On top of history:
  • a separation list with a `target_client` adds its names to that insurer;
  • InsuranceRosterDecision rows (reviewer verdicts) say «member» / «not member»
    so a decided name is not re-flagged every month.

Each receipt of the claim under review is classified (deterministic, read-only):

  wrong   — not known in this unit, but known under ANOTHER company, or under
            another فئة / فئة فوترة of the same جهة  (highest priority — these
            are the deductions that delay collection)
  shared  — known here AND under another company (possible earlier mistake)
  sister  — not known here, only under a sister record of the same company
            (e.g. العاملين ↔ المعاشات) — low priority
  new     — not in any roster (joins this unit's roster once the claim stays)
  known   — in this unit's roster
"""
import re
from collections import defaultdict

from .separation import match_name, normalize_name

# Claims whose receipts do NOT count as roster evidence.
INACTIVE_STATUSES = ('cancelled', 'rejected')

_PUNCT = re.compile(r'[^\w\s]', re.UNICODE)
_GROUP_STOP = {'شركه', 'شركتي', 'قطاع', 'و', 'للتوزيع'}
_GROUP_PREFIXES = ('وال', 'بال', 'لل', 'ال')


def name_tokens(value) -> list:
    """Arabic-folded patient-name tokens, punctuation dropped («على / ك» → على ك),
    and «عبد الموجود» joined to «عبدالموجود» so both spellings compare equal."""
    raw = [t for t in _PUNCT.sub(' ', normalize_name(value)).split() if t]
    out, i = [], 0
    while i < len(raw):
        if raw[i] == 'عبد' and i + 1 < len(raw):
            out.append('عبد' + raw[i + 1]); i += 2
        else:
            out.append(raw[i]); i += 1
    return out


def name_key(value) -> str:
    return ' '.join(name_tokens(value))


def _strip_article(tok: str) -> str:
    for p in _GROUP_PREFIXES:
        if tok.startswith(p) and len(tok) - len(p) >= 2:
            return tok[len(p):]
    return tok


def group_key(label) -> str:
    """Order-insensitive key for a billing-group label («منطقة القاهرة - الجهد الفائق»
    ≡ «منطقة القاهرة - جهد فائق»).  '' when there is no group."""
    toks = {_strip_article(t) for t in name_tokens(label)}
    toks = {t for t in toks if t not in _GROUP_STOP and len(t) > 1}
    return ' '.join(sorted(toks))


def same_group(a: str, b: str) -> bool:
    if a == b:
        return True
    if not a or not b:
        return False
    sa, sb = set(a.split()), set(b.split())
    return len(sa & sb) / len(sa | sb) >= 0.6


def company_key(client) -> str:
    """Records of the same company (العاملين / المعاشات split into two جهات) share
    this key: the parent client when one is set, else the folded client name."""
    if getattr(client, 'parent_id', None):
        return f'p{client.parent_id}'
    return ' '.join(name_tokens(client.name))


# ── Roster index ─────────────────────────────────────────────────────────────

class _Roster:
    """All roster evidence, indexed by name key + tokens for fast candidate lookup."""

    def __init__(self):
        # name_key → {(client_id, subclient_id|None, group_key): occurrence dict}
        self.units = defaultdict(dict)
        self.tokens = {}
        self.by_first = defaultdict(set)
        self.by_any = defaultdict(set)

    def add(self, key, *, client_id, subclient_id, gkey, glabel, display, count, last, source):
        if not key:
            return
        u = (client_id, subclient_id, gkey)
        occ = self.units[key].get(u)
        if occ is None:
            occ = self.units[key][u] = {
                'client_id': client_id, 'subclient_id': subclient_id,
                'group_key': gkey, 'group_label': glabel,
                'count': 0, 'last': None, 'spellings': defaultdict(int), 'sources': set(),
            }
            if key not in self.tokens:
                toks = key.split()
                self.tokens[key] = toks
                self.by_first[toks[0]].add(key)
                for t in toks:
                    self.by_any[t].add(key)
        occ['count'] += count
        occ['spellings'][display] += max(count, 1)
        occ['sources'].add(source)
        if last and (occ['last'] is None or last > occ['last']):
            occ['last'] = last

    def candidates(self, rx_tokens):
        """Names that could pass match_name: their first token is in rx, or rx's
        first token is in them (covers full, ordered-subsequence and prefix)."""
        out = set(self.by_any.get(rx_tokens[0], ()))
        for t in set(rx_tokens):
            out |= self.by_first.get(t, set())
        return out


def build_roster(exclude_claim_id=None) -> _Roster:
    from django.db.models import Count, Max
    from .models import (InsuranceClaimPrescription, InsuranceClaimManualRx,
                         InsuranceSeparationName)
    r = _Roster()
    fields = ('claim__subclient__client_id', 'claim__subclient_id',
              'billing_group__name', 'patient_name')
    rx_qs = InsuranceClaimPrescription.objects.filter(exclusion__isnull=True)
    mrx_qs = InsuranceClaimManualRx.objects.filter(is_excluded=False)
    for qs in (rx_qs, mrx_qs):
        qs = (qs.exclude(claim__status__in=INACTIVE_STATUSES)
                .exclude(patient_name='').exclude(claim__subclient__isnull=True))
        if exclude_claim_id:
            qs = qs.exclude(claim_id=exclude_claim_id)
        for row in qs.values(*fields).annotate(n=Count('id'), last=Max('softech_docdate')):
            glabel = row['billing_group__name'] or ''
            r.add(name_key(row['patient_name']),
                  client_id=row['claim__subclient__client_id'],
                  subclient_id=row['claim__subclient_id'],
                  gkey=group_key(glabel), glabel=glabel,
                  display=row['patient_name'], count=row['n'], last=row['last'],
                  source='history')
    # Separation lists that name the insurer their names belong to
    for n in (InsuranceSeparationName.objects
              .filter(is_active=True, sep_list__is_active=True, sep_list__target_client__isnull=False)
              .values('name', 'sep_list__target_client_id', 'sep_list__target_group_label')):
        glabel = n['sep_list__target_group_label'] or ''
        r.add(name_key(n['name']), client_id=n['sep_list__target_client_id'], subclient_id=None,
              gkey=group_key(glabel), glabel=glabel, display=n['name'], count=0, last=None,
              source='list')
    # Reviewer-confirmed members
    from .models import InsuranceRosterDecision
    for d in InsuranceRosterDecision.objects.filter(verdict='member'):
        r.add(name_key(d.name), client_id=d.client_id, subclient_id=d.subclient_id,
              gkey=d.group_key, glabel=d.group_label, display=d.name, count=0, last=None,
              source='decision')
    return r


def _decisions():
    """{(client_id, subclient_id|None, group_key, name_key): verdict}

    Reviewer decisions, plus the insurer's own word: a deduction recorded as
    «المريض لا يتبع الجهة» on a receipt says that patient is not this unit's member.
    An explicit reviewer decision on the same unit + name wins."""
    from .models import InsuranceDeduction, InsuranceRosterDecision
    out = {}
    for cid, sid, glabel, nm in (InsuranceDeduction.objects
            .filter(reason_code=InsuranceDeduction.REASON_NOT_MEMBER, prescription__isnull=False)
            .values_list('claim__subclient__client_id', 'claim__subclient_id',
                         'prescription__billing_group__name', 'prescription__patient_name')):
        if cid and nm:
            out[(cid, sid, group_key(glabel or ''), name_key(nm))] = 'not_member'
    out.update({(d.client_id, d.subclient_id, d.group_key, name_key(d.name)): d.verdict
                for d in InsuranceRosterDecision.objects.all()})
    return out


def _deducted_rx_ids(claim):
    from .models import InsuranceDeduction
    return set(InsuranceDeduction.objects.filter(
        claim=claim, reason_code=InsuranceDeduction.REASON_NOT_MEMBER,
        prescription__isnull=False).values_list('prescription_id', flat=True))


def unit_decision(decisions, client_id, subclient_id, gkey, key):
    """Most specific verdict for a unit: exact unit → فئة level → جهة level."""
    for k in ((client_id, subclient_id, gkey, key),
              (client_id, subclient_id, '', key),
              (client_id, None, '', key)):
        if k in decisions:
            return decisions[k]
    return None


# ── Classification ───────────────────────────────────────────────────────────

_RANK = {'wrong': 0, 'shared': 1, 'sister': 2, 'new': 3, 'known': 4}


def check_claim_roster(claim) -> dict:
    """READ-ONLY roster check of every non-excluded prescription of `claim`."""
    from .models import InsuranceClient, InsuranceSubClient

    roster = build_roster(exclude_claim_id=claim.pk)
    decisions = _decisions()
    clients = {c.id: c for c in InsuranceClient.objects.all()}
    subs = dict(InsuranceSubClient.objects.values_list('id', 'name'))
    co_key = {cid: company_key(c) for cid, c in clients.items()}

    here_client = claim.subclient.client_id
    here_sub = claim.subclient_id
    here_co = co_key.get(here_client)

    def unit_label(occ):
        parts = [clients[occ['client_id']].name if occ['client_id'] in clients else '?']
        if occ['subclient_id']:
            parts.append(subs.get(occ['subclient_id'], ''))
        if occ['group_label']:
            parts.append(occ['group_label'])
        return ' — '.join(p for p in parts if p)

    rows, counts = [], defaultdict(int)
    deducted = _deducted_rx_ids(claim)
    qs = list(claim.prescriptions.filter(exclusion__isnull=True)
              .select_related('billing_group').order_by('softech_docdate', 'sequence'))
    manual = list(claim.manual_rx.filter(is_excluded=False).select_related('billing_group')
                  .order_by('softech_docdate', 'sequence'))
    for rx in qs + manual:
        is_manual = rx in manual
        toks = name_tokens(rx.patient_name)
        if not toks:
            continue
        key = ' '.join(toks)
        glabel = rx.billing_group.name if rx.billing_group_id else ''
        gkey = group_key(glabel)

        here_n, elsewhere = 0, []
        for cand in roster.candidates(toks):
            ok, mtype, _ = match_name(toks, roster.tokens[cand])
            if not ok:
                continue
            # A 3-word name inside a longer one («محمد سيد احمد») is too common to
            # be a confident hit — only identical names or ≥4 shared words are «full».
            if mtype == 'full' and cand != key and len(roster.tokens[cand]) < 4:
                mtype = 'partial'
            for occ in roster.units[cand].values():
                if unit_decision(decisions, occ['client_id'], occ['subclient_id'],
                                 occ['group_key'], cand) == 'not_member':
                    continue   # a reviewer ruled this billing was a mistake
                same_client = occ['client_id'] == here_client
                sub_ok = occ['subclient_id'] is None or occ['subclient_id'] == here_sub
                if same_client and sub_ok:
                    # Same فئة. With a فئة فوترة on both sides, the groups must agree;
                    # history without a group says nothing about the division.
                    if gkey and occ['group_key'] and not same_group(gkey, occ['group_key']):
                        scope = 'division'
                    else:
                        here_n += occ['count'] or 1
                        continue
                elif same_client:
                    scope = 'division'
                elif co_key.get(occ['client_id']) == here_co:
                    scope = 'sister'
                else:
                    scope = 'company'
                elsewhere.append((scope, mtype, cand, occ))

        verdict = unit_decision(decisions, here_client, here_sub, gkey, key)
        strong = [e for e in elsewhere if e[0] in ('company', 'division')]
        if verdict == 'not_member':
            cat = 'wrong'
        elif verdict == 'member':
            cat = 'known'
        elif here_n:
            # Only a specific (≥4-word) name billed to another company is worth a look;
            # 3-word names like «محمد على احمد» are simply different people.
            cat = ('shared' if len(toks) >= 4 and any(
                e[0] == 'company' and e[1] == 'full' for e in elsewhere) else 'known')
        elif strong:
            cat = 'wrong'
        elif elsewhere:
            cat = 'sister'
        else:
            cat = 'new'
        counts[cat] += 1
        if cat == 'known':
            continue

        # Where else this patient is billed — one entry per unit, strongest first
        seen, where = set(), []
        order = {'company': 0, 'division': 1, 'sister': 2}
        for scope, mtype, cand, occ in sorted(
                elsewhere, key=lambda e: (order[e[0]], e[1] != 'full', -(e[3]['count'] or 0))):
            u = (occ['client_id'], occ['subclient_id'], occ['group_key'])
            if u in seen:
                continue
            seen.add(u)
            sp = occ['spellings']
            where.append({
                'scope':        scope,
                'match_type':   mtype,
                'client_id':    occ['client_id'],
                'subclient_id': occ['subclient_id'],
                'group_label':  occ['group_label'],
                'label':        unit_label(occ),
                'matched_name': max(sp, key=sp.get) if sp else cand,
                'count':        occ['count'],
                'last':         occ['last'].isoformat() if occ['last'] else None,
                'from_list':    'list' in occ['sources'],
            })
        rows.append({
            'prescription_id': None if is_manual else rx.id,
            'manual_rx_id':    rx.id if is_manual else None,
            'kind':            'manual' if is_manual else 'receipt',
            'deducted':        (not is_manual) and rx.id in deducted,
            'patient_name':    rx.patient_name,
            'category':        cat,
            'decided':         verdict,
            'confidence':      ('full' if any(e[1] == 'full' for e in (strong if cat == 'wrong' else elsewhere))
                                else ('partial' if elsewhere else None)),
            'here_count':      here_n,
            'where':           where[:5],
            'group_label':     glabel,
            'sequence':        rx.sequence,
            'docnumber':       rx.softech_docnumber,
            'docdate':         rx.softech_docdate.isoformat() if rx.softech_docdate else None,
            'branch':          rx.softech_branchcode,
            'gross_before':    float(rx.gross_before or 0),
            'net_after':       float(rx.net_after or 0),
        })

    rows.sort(key=lambda r: (_RANK[r['category']], r['confidence'] != 'full', -r['net_after']))
    return {
        'unit': {
            'client_id': here_client, 'client': clients[here_client].name if here_client in clients else '',
            'subclient_id': here_sub, 'subclient': subs.get(here_sub, ''),
        },
        'counts':   {k: counts.get(k, 0) for k in _RANK},
        'wrong_net': round(sum(r['net_after'] for r in rows if r['category'] == 'wrong'), 2),
        'rows':     rows,
        'roster_names': len(roster.tokens),
    }


def record_decision(claim, rx, verdict, *, target=None, note='', actor=None):
    """Upsert a reviewer verdict for this receipt's patient in the claim's unit.
    `target` = {client_id, subclient_id?, group_label?} also records the name as a
    member of the unit it really belongs to.  verdict 'clear' removes the verdict."""
    from .models import InsuranceRosterDecision
    glabel = rx.billing_group.name if rx.billing_group_id else ''
    unit = dict(client_id=claim.subclient.client_id, subclient_id=claim.subclient_id,
                group_key=group_key(glabel))
    key = name_key(rx.patient_name)
    existing = [d for d in InsuranceRosterDecision.objects.filter(**unit)
                if name_key(d.name) == key]
    if verdict == 'clear':
        for d in existing:
            d.delete()
        return None
    d = existing[0] if existing else InsuranceRosterDecision(**unit)
    d.name, d.verdict, d.note, d.claim, d.decided_by, d.group_label = (
        rx.patient_name, verdict, note[:300], claim, actor, glabel)
    d.save()
    if verdict == 'not_member' and target and target.get('client_id'):
        tg = target.get('group_label') or ''
        tunit = dict(client_id=target['client_id'], subclient_id=target.get('subclient_id') or None,
                     group_key=group_key(tg))
        t = next((x for x in InsuranceRosterDecision.objects.filter(**tunit)
                  if name_key(x.name) == key), None) or InsuranceRosterDecision(**tunit)
        t.name, t.verdict, t.note, t.claim, t.decided_by, t.group_label = (
            rx.patient_name, 'member', f'نُقل من {claim.claim_number}', claim, actor, tg)
        t.save()
    return d


# ── Per-insurer roster (read-only page) ──────────────────────────────────────

ROSTER_ORDERS = ('name', 'subclient', 'group_label', 'count', 'last', 'elsewhere')


def roster_for_unit(client_id, subclient_id=None, q='', ordering=''):
    """The cumulative roster of one جهة (optionally one فئة): every name billed there
    (non-excluded receipts of live claims), listed, or confirmed by a reviewer — with
    where else it is billed — plus the names ruled out (decisions + deductions)."""
    from .models import InsuranceClient, InsuranceSubClient
    roster = build_roster()
    decisions = _decisions()
    clients = {c.id: c for c in InsuranceClient.objects.all()}
    subs = dict(InsuranceSubClient.objects.values_list('id', 'name'))
    here = clients.get(client_id)
    if here is None:
        return {'client': None, 'members': [], 'ruled_out': [], 'counts': {}}
    here_co = company_key(here)
    q_toks = name_tokens(q) if q else []

    members = []
    for key, units in roster.units.items():
        if q_toks and not all(any(t.startswith(x) for t in roster.tokens[key]) for x in q_toks):
            continue
        mine = [o for o in units.values() if o['client_id'] == client_id
                and (subclient_id is None or o['subclient_id'] in (subclient_id, None))]
        if not mine:
            continue
        other_co = sorted({clients[o['client_id']].name for o in units.values()
                           if o['client_id'] in clients and o['client_id'] != client_id
                           and company_key(clients[o['client_id']]) != here_co})
        for o in mine:
            if unit_decision(decisions, o['client_id'], o['subclient_id'], o['group_key'], key) == 'not_member':
                continue
            sp = o['spellings']
            members.append({
                'name':         max(sp, key=sp.get) if sp else key,
                'subclient':    subs.get(o['subclient_id'], '') if o['subclient_id'] else '',
                'group_label':  o['group_label'],
                'count':        o['count'],
                'last':         o['last'].isoformat() if o['last'] else None,
                'sources':      sorted(o['sources']),
                'other_companies': other_co[:3],
            })
    members.sort(key=lambda m: (m['last'] or '', m['count']), reverse=True)
    # optional column sort of ALL members (before the 3000 cut); ties keep the last-billed order (stable)
    from apps.pic_analytics.queries.ordering import parse_ordering, sort_items
    okey, odesc = parse_ordering(ordering, ROSTER_ORDERS)          # ValueError on an unknown field
    if okey:
        val = (lambda m: len(m['other_companies'])) if okey == 'elsewhere' else (lambda m: m[okey])
        members = sort_items(members, val, odesc)

    ruled_out = [{'name': k[3], 'subclient': subs.get(k[1], '') if k[1] else '', 'group_key': k[2]}
                 for k, v in decisions.items()
                 if v == 'not_member' and k[0] == client_id
                 and (subclient_id is None or k[1] in (subclient_id, None))]
    return {
        'client': {'id': here.id, 'name': here.name, 'parent_id': here.parent_id},
        'subclient': subs.get(subclient_id, '') if subclient_id else '',
        'counts': {'members': len(members),
                   'also_elsewhere': sum(1 for m in members if m['other_companies']),
                   'ruled_out': len(ruled_out)},
        'members': members[:3000],
        'ruled_out': ruled_out,
    }


# ── فئة فوترة suggestions (read-only) ───────────────────────────────────────

def suggest_billing_groups(claim) -> dict:
    """For every active receipt of `claim`, the billing group its patient belongs to,
    learned from earlier claims of the same جهة (their receipts' فئة فوترة) and from
    separation lists linked to a جهة + فئة فوترة. Read-only — assigning stays a user action.

    rows: {prescription_id, sequence, patient_name, docnumber, docdate, branch, net_after,
           current_group_id, suggested_group_id, confidence full|partial,
           options [{group_id, label, count, from_list}], evidence [..], conflict}"""
    groups = list(claim.billing_groups.all())
    if not groups:
        return {'groups': [], 'rows': [], 'counts': {}}
    gkeys = [(g, group_key(g.name)) for g in groups]
    here_client, here_sub = claim.subclient.client_id, claim.subclient_id
    roster = build_roster(exclude_claim_id=claim.pk)
    decisions = _decisions()

    def to_group(occ_gkey):
        hits = [g for g, gk in gkeys if gk and occ_gkey and same_group(gk, occ_gkey)]
        return hits[0] if len(hits) == 1 else None

    rows, counts = [], defaultdict(int)
    qs = (claim.prescriptions.filter(exclusion__isnull=True)
          .select_related('billing_group').order_by('sequence'))
    for rx in qs:
        toks = name_tokens(rx.patient_name)
        if not toks:
            continue
        key = ' '.join(toks)
        per_group = {}          # group id → evidence
        best_type = {}
        for cand in roster.candidates(toks):
            ok, mtype, _ = match_name(toks, roster.tokens[cand])
            if not ok:
                continue
            # (no 3-word downgrade here: inside one جهة a 3-word match is the same
            # employee far more often than across companies)
            for occ in roster.units[cand].values():
                if occ['client_id'] != here_client or not occ['group_key']:
                    continue
                if occ['subclient_id'] not in (None, here_sub):
                    continue
                if unit_decision(decisions, occ['client_id'], occ['subclient_id'],
                                 occ['group_key'], cand) == 'not_member':
                    continue
                g = to_group(occ['group_key'])
                if g is None:
                    continue
                e = per_group.setdefault(g.id, {'group_id': g.id, 'label': g.name, 'count': 0,
                                                'last': None, 'from_list': False, 'seen_as': set()})
                e['count'] += occ['count'] or 0
                e['from_list'] = e['from_list'] or 'list' in occ['sources']
                e['seen_as'].add(occ['group_label'])
                if occ['last'] and (e['last'] is None or occ['last'] > e['last']):
                    e['last'] = occ['last']
                if best_type.get(g.id) != 'full':
                    best_type[g.id] = mtype
        options = sorted(per_group.values(), key=lambda e: (best_type[e['group_id']] != 'full',
                                                            not e['from_list'], -e['count']))
        for o in options:
            o['seen_as'] = sorted(x for x in o['seen_as'] if x)
            o['last'] = o['last'].isoformat() if o['last'] else None
            o['match'] = best_type[o['group_id']]
        full = [o for o in options if o['match'] == 'full']
        conflict = len(full) > 1 or (not full and len(options) > 1)
        pick = full[0] if len(full) == 1 else (options[0] if len(options) == 1 else None)
        status = ('assigned' if rx.billing_group_id else
                  'none' if not options else 'conflict' if conflict else
                  'full' if pick and pick['match'] == 'full' else 'partial')
        counts[status] += 1
        rows.append({
            'prescription_id': rx.id, 'sequence': rx.sequence, 'patient_name': rx.patient_name,
            'docnumber': rx.softech_docnumber, 'branch': rx.softech_branchcode,
            'docdate': rx.softech_docdate.isoformat() if rx.softech_docdate else None,
            'net_after': float(rx.net_after or 0),
            'current_group_id': rx.billing_group_id,
            'current_group': rx.billing_group.name if rx.billing_group_id else '',
            'suggested_group_id': pick['group_id'] if pick and not conflict else None,
            'status': status, 'options': options,
        })
    return {'groups': [{'id': g.id, 'code': g.code, 'name': g.name} for g in groups],
            'rows': rows, 'counts': dict(counts)}
