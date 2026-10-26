"""
python manage.py eval_supply_matching                    # both screens, memory OFF
python manage.py eval_supply_matching --misses 20        # list lines that look clean but are wrong
python manage.py eval_supply_matching --max-clean-wrong 6   # exit 1 when more slip through (a check)

READ-ONLY benchmark of the shared matching core (apps/supply/line_matching.match_text) on
every supplier-list and WhatsApp line a person CONFIRMED. The learned memory is OFF, so it
measures the engines themselves (with memory on, anything confirmed scores 100 %).

Reports per screen: first match right, flagged for review, and CLEAN-BUT-WRONG — a line with
no warning whose first match is wrong: the dangerous number (doc 31 §2 / §4).
Baseline 2026-10-25 (strict flags, before the strength-count and word fixes): 6 of 431.
"""
import re
from unittest import mock

from django.core.management.base import BaseCommand, CommandError

AR = re.compile(r'[؀-ۿ]')


def ground_truth():
    """[(text, item_id, source, branch)] — unique confirmed (text, item) pairs."""
    from apps.shortage.matching import _normalize
    from apps.supply.models import AvailabilityLine, BranchRequestLine
    pairs = [((l.match_reason or {}).get('name_part') or l.raw_text, l.item_id, 'supplier', None)
             for l in AvailabilityLine.objects.filter(is_confirmed=True, item__isnull=False, split_from__isnull=True)]
    pairs += [(l.raw_text, l.item_id, 'branch', l.request.branch if l.request_id else None)
              for l in BranchRequestLine.objects.filter(confirmed=True, item__isnull=False, extra_items__isnull=True,
                                                       all_variants=False).select_related('request__branch')]
    seen, out = set(), []
    for t, iid, src, br in pairs:
        k = (_normalize(t), iid, src)
        if t and k not in seen:
            seen.add(k)
            out.append((t, iid, src, br))
    return out


def evaluate(rows):
    from apps.shortage import matching as M
    from apps.supply import line_matching as LM
    from apps.supply import branch_requests as BR
    real = M.find_best_matches

    def nomem(*a, **k):
        k['use_memory'] = False
        return real(*a, **k)

    res, misses = {}, []
    with mock.patch.object(M, 'find_best_matches', nomem), \
            mock.patch('apps.shortage.learning.lookup_alias_group', return_value=None):
        for t, iid, src, br in rows:
            frag = None
            if src == LM.BRANCH:
                frags = [f for f in BR.extract(t) if f.get('kind', 'item') == 'item']
                frag = frags[0] if frags else None
            r = LM.match_text(t, source=src, branch=br, frag=frag)
            got = getattr(r['item'], 'id', None)
            flagged = LM.needs_review(r['flags']) or got is None
            c = res.setdefault(src, {'n': 0, 'top1': 0, 'flagged': 0, 'clean_wrong': 0, 'arabic': 0})
            c['n'] += 1
            c['arabic'] += bool(AR.search(t))
            c['top1'] += got == iid
            c['flagged'] += flagged
            if not flagged and got != iid:
                c['clean_wrong'] += 1
                misses.append((src, t, getattr(r['item'], 'name', None), iid))
    return res, misses


class Command(BaseCommand):
    help = 'Benchmark the shared supply matching core (read-only, memory off)'

    def add_arguments(self, p):
        p.add_argument('--misses', type=int, default=0)
        p.add_argument('--max-clean-wrong', type=int, default=None)

    def handle(self, *a, **o):
        from apps.catalog.models import Item
        rows = ground_truth()
        res, misses = evaluate(rows)
        total_cw = 0
        for src, c in sorted(res.items()):
            n = c['n']
            total_cw += c['clean_wrong']
            self.stdout.write(f"{src:8} n={n:4d}  first match right {100 * c['top1'] / n:5.1f}%  "
                              f"flagged {100 * c['flagged'] / n:5.1f}%  clean-but-wrong {c['clean_wrong']}")
        self.stdout.write(f'TOTAL clean-but-wrong: {total_cw} of {len(rows)}')
        if o['misses']:
            names = dict(Item.objects.filter(id__in=[m[3] for m in misses]).values_list('id', 'name'))
            for src, t, got, iid in misses[:o['misses']]:
                self.stdout.write(f'  [{src}] «{t}» → {got}  ✗ really {names.get(iid)}')
        if o['max_clean_wrong'] is not None and total_cw > o['max_clean_wrong']:
            raise CommandError(f'{total_cw} clean-but-wrong lines > allowed {o["max_clean_wrong"]}')
