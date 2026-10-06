"""
python manage.py shadow_validate_ap [--party-type supplier] [--sample N] [--seed 0]

Phase-D SHADOW-MODE validation — measure the real precision of the matching
engine's HIGH-confidence proposals against SOFTECH's own already-correct
allocations (the 36k `chequestrans` links = ground truth).

Method (read-only, no writes): for every known allocation (payment P → true
invoice I), HIDE the answer and ask the engine, blind, which invoice it would pick
for P among the party's invoices (same blocking + scoring + conflict rules it uses
live). Then:
  • the engine makes a HIGH-confidence pick == I        → TRUE POSITIVE
  • the engine makes a HIGH-confidence pick != I        → FALSE POSITIVE
  • the engine makes NO high-confidence pick (or a tie) → no-high (recall miss)

  precision(high) = TP / (TP + FP)         ← "how trustworthy is a high match"
  recall(high)    = TP / (known pairs)      ← "share of true links it auto-finds"

This calibrates a safe auto-approve threshold from evidence, not assumption (§19).
"""
from collections import defaultdict
from decimal import Decimal
import random

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Shadow-mode precision/recall of the engine vs SOFTECH ground-truth allocations'

    def add_arguments(self, parser):
        parser.add_argument('--party-type', default='supplier')
        parser.add_argument('--sample', type=int, default=0, help='0 = all known allocations')
        parser.add_argument('--seed', type=int, default=0)

    def handle(self, *args, **o):
        from apps.finance.models import ReconParty, Allocation
        from apps.finance import recon_engine as E
        cfg = E.SCORING_V1
        HIGH = cfg['high_threshold']
        MED = cfg['medium_threshold']
        DELTA = cfg['conflict_delta']
        TOL = cfg['amount_exact_tol']
        random.seed(o['seed'])

        # ground truth: existing SOFTECH allocations, grouped by party
        gt = (Allocation.objects.filter(origin=Allocation.ORIGIN_SOFTECH,
                                        payment__party__party_type=o['party_type'])
              .select_related('payment', 'invoice', 'payment__party'))
        by_party = defaultdict(list)
        for a in gt.iterator():
            by_party[a.payment.party_id].append(a)
        total_known = sum(len(v) for v in by_party.values())
        self.stdout.write(f'ground-truth allocations: {total_known} across {len(by_party)} parties')

        if o['sample']:
            # sample allocation ids proportionally by drawing from the flat list
            flat = [(pid, a) for pid, lst in by_party.items() for a in lst]
            random.shuffle(flat)
            flat = flat[:o['sample']]
            by_party = defaultdict(list)
            for pid, a in flat:
                by_party[pid].append(a)
            self.stdout.write(f'sampled {sum(len(v) for v in by_party.values())} allocations')

        TP = FP = no_high = no_cand = 0
        fp_examples = []
        # precision of the top (non-conflict) pick by EVIDENCE PATTERN, any score ≥ medium
        pattern = defaultdict(lambda: [0, 0])     # key → [correct, wrong]
        parties = ReconParty.objects.in_bulk(list(by_party.keys()))

        for pid, allocs in by_party.items():
            party = parties[pid]
            invoices = list(party.invoices.all())
            if not invoices:
                continue
            # indexes: by exact amount, and by the invoice's OWN reference numbers
            by_amount = defaultdict(list)
            by_token = defaultdict(list)
            amounts = set()
            for inv in invoices:
                by_amount[inv.doc_value].append(inv)
                amounts.add(inv.doc_value)
                for key in (str(inv.docnumber).split('.')[0].lstrip('0'),
                            str(inv.docnumber2).lstrip('0') if inv.docnumber2 else ''):
                    if key:
                        by_token[key].append(inv)

            for a in allocs:
                P = a.payment
                I_true = a.invoice
                # SHADOW candidate set for P (ignore existing allocations):
                cand = {}
                for t in E.payment_ref_tokens(P, cfg['min_ref_token_len']):
                    for inv in by_token.get(t, []):
                        cand[inv.id] = inv
                for amt in amounts:
                    if abs(amt - (P.amount or Decimal('0'))) <= TOL:
                        for inv in by_amount[amt]:
                            cand[inv.id] = inv
                if not cand:
                    no_cand += 1
                    continue
                # score each candidate invoice for P (treat as unpaid/unallocated)
                scored = []
                for inv in cand.values():
                    score, ev = E.score_candidate(inv, P, inv.doc_value, P.amount or Decimal('0'), cfg)
                    amount_exact = any(e['signal'] == 'amount' and e['outcome'] == 'exact' for e in ev)
                    amt_ev = next((e for e in ev if e['signal'] == 'amount'), None)
                    ref_ev = next((e for e in ev if e['signal'] == 'reference'), None)
                    amt_kind = ('exact' if amt_ev['outcome'] == 'exact' else
                                'partial' if (P.amount or 0) < inv.doc_value else 'over')
                    ref_kind = ('none' if ref_ev['outcome'] != 'exact' else
                                'cheqno' if 'cheqno' in ref_ev['detail'] else 'note')
                    xb = ('' if P.branchcode == inv.branchcode else
                          ' HQ-voucher' if P.branchcode == '100' else ' CROSS-branch')
                    scored.append((score, amount_exact, inv, f'amount={amt_kind} ref={ref_kind}{xb}'))
                scored.sort(key=lambda x: x[0], reverse=True)
                top_score, top_exact, top_inv, top_pat = scored[0]
                # conflict: ≥2 amount-exact rivals within DELTA and ≥ medium ⇒ no confident pick
                exact_rivals = [s for s in scored if s[1] and s[0] >= MED]
                is_conflict = (len(exact_rivals) >= 2 and
                               (exact_rivals[0][0] - exact_rivals[1][0]) <= DELTA)

                if top_score >= MED and not is_conflict:
                    pattern[top_pat][0 if top_inv.id == I_true.id else 1] += 1
                if top_score >= HIGH and not is_conflict:
                    if top_inv.id == I_true.id:
                        TP += 1
                    else:
                        FP += 1
                        if len(fp_examples) < 8:
                            fp_examples.append(
                                f"pay {P.branchcode}/{P.cheqsno} '{P.note}' {P.amount}: "
                                f"picked inv {top_inv.docnumber} ({top_score}), true {I_true.docnumber}")
                else:
                    no_high += 1

        graded = TP + FP
        precision = (TP / graded * 100) if graded else 0.0
        recall = (TP / total_known * 100) if total_known else 0.0
        self.stdout.write('')
        self.stdout.write('═══════════════ SHADOW-MODE RESULT ═══════════════')
        self.stdout.write(f'  known pairs graded      : {total_known}')
        self.stdout.write(f'  no candidate generated  : {no_cand}')
        self.stdout.write(f'  no HIGH pick (or tie)    : {no_high}')
        self.stdout.write(f'  HIGH predictions made    : {graded}')
        self.stdout.write(f'    ✓ correct (TP)         : {TP}')
        self.stdout.write(f'    ✗ wrong   (FP)         : {FP}')
        self.stdout.write(f'  ──────────────────────────────')
        self.stdout.write(self.style.SUCCESS(f'  PRECISION (high) : {precision:.2f}%'))
        self.stdout.write(f'  RECALL (high)    : {recall:.2f}%   (auto-found / all true links)')
        self.stdout.write('\n  precision of the top pick by evidence pattern (score ≥ medium, no conflict):')
        for k, (ok, bad) in sorted(pattern.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
            n = ok + bad
            self.stdout.write(f'    {k:28} n={n:6}  precision {ok / n * 100:6.2f}%')
        if fp_examples:
            self.stdout.write('\n  sample false positives:')
            for e in fp_examples:
                self.stdout.write('    - ' + e)
