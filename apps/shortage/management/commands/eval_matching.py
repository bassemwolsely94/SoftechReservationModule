"""
python manage.py eval_matching                  # accuracy + speed of the catalog matcher
python manage.py eval_matching --misses 30      # also list the first 30 misses
python manage.py eval_matching --lang ar        # Arabic lines only
python manage.py eval_matching --memory         # WITH the learned memory (default: off)

READ-ONLY benchmark of apps/shortage/matching.find_best_matches against every line a
person has CONFIRMED anywhere in the system (ground truth): learned spellings, supplier
availability lines, WhatsApp branch requests, shortage lists, supplier invoices, POS /
vision OCR. By default the learned memory is OFF, so the score measures the engine itself
(with memory on, anything ever confirmed trivially scores 100%).

Reports top-1 / top-3 / top-5 accuracy and latency (avg, p95), split Arabic / Latin.
The set grows by itself as people confirm more matches.
"""
import re
import statistics
import time

from django.core.management.base import BaseCommand

AR = re.compile(r'[؀-ۿ]')


def ground_truth() -> list:
    """[(text, item_id, source)] — unique (normalized text, item) pairs, active items only."""
    from apps.catalog.models import Item, ItemAlias
    from apps.shortage.matching import _normalize
    pairs = []
    pairs += [(a.sample_raw or a.normalized, a.item_id, 'alias') for a in ItemAlias.objects.all()]
    try:
        from apps.supply.models import AvailabilityLine, BranchRequestLine
        pairs += [((l.match_reason or {}).get('name_part') or l.raw_text, l.item_id, 'availability')
                  for l in AvailabilityLine.objects.filter(is_confirmed=True, item__isnull=False)]
        pairs += [(l.match_text or l.raw_text, l.item_id, 'whatsapp')
                  for l in BranchRequestLine.objects.filter(confirmed=True, item__isnull=False,
                                                           extra_items__isnull=True, all_variants=False)]
    except Exception:
        pass
    try:
        from apps.shortage.models import ShortageItem
        pairs += [(s.raw_name, s.item_id, 'shortage')
                  for s in ShortageItem.objects.filter(is_confirmed=True, item__isnull=False)]
    except Exception:
        pass
    try:
        from apps.invoices.models import InvoiceLine
        pairs += [(l.manual_name or l.raw_text, l.item_id, 'invoice')
                  for l in InvoiceLine.objects.filter(is_confirmed=True, item__isnull=False)]
    except Exception:
        pass
    try:
        from apps.vision.models import OcrSample
        for s in OcrSample.objects.exclude(confirmations=[]):
            for c in s.confirmations or []:
                if c.get('reading') and c.get('item_id'):
                    pairs.append((c['reading'], c['item_id'], 'ocr'))
    except Exception:
        pass
    active = set(Item.objects.filter(is_active=True).values_list('id', flat=True))
    seen, out = set(), []
    for text, iid, src in pairs:
        k = (_normalize(text or ''), iid)
        if text and iid in active and k[0] and k not in seen:
            seen.add(k)
            out.append((text.strip(), iid, src))
    return out


def evaluate(pairs, *, memory=False, top_n=5) -> dict:
    """One row per distinct TEXT. A supplier line confirmed as several items («بيبيلاك
    1...2...3» → BEBELAC 1, 2, 3) is a hit when the answer is ANY of them — only one can
    come first. rank = the best position of any confirmed item."""
    from apps.shortage.matching import _normalize, find_best_matches
    groups = {}
    for text, iid, src in pairs:
        g = groups.setdefault(_normalize(text), {'text': text, 'ids': set(), 'source': src})
        g['ids'].add(iid)
    rows = []
    for g in groups.values():
        t = time.perf_counter()
        res = find_best_matches(g['text'], top_n=top_n, min_score=0.15, use_memory=memory)
        ms = (time.perf_counter() - t) * 1000
        ids = [r['item_id'] for r in res]
        ranks = [ids.index(i) + 1 for i in g['ids'] if i in ids]
        rows.append({'text': g['text'], 'item_id': min(g['ids']), 'item_ids': g['ids'], 'source': g['source'],
                     'rank': min(ranks) if ranks else None, 'ms': ms,
                     'arabic': bool(AR.search(g['text'])), 'top': res[0]['item_name'] if res else ''})
    return summarize(rows)


def summarize(rows) -> dict:
    def block(rs):
        if not rs:
            return None
        ms = sorted(r['ms'] for r in rs)
        return {'n': len(rs),
                'top1': round(100 * sum(1 for r in rs if r['rank'] == 1) / len(rs), 1),
                'top3': round(100 * sum(1 for r in rs if r['rank'] and r['rank'] <= 3) / len(rs), 1),
                'top5': round(100 * sum(1 for r in rs if r['rank'] and r['rank'] <= 5) / len(rs), 1),
                'avg_ms': round(statistics.mean(ms)), 'p95_ms': round(ms[int(len(ms) * 0.95) - 1])}
    return {'all': block(rows), 'arabic': block([r for r in rows if r['arabic']]),
            'latin': block([r for r in rows if not r['arabic']]), 'rows': rows}


class Command(BaseCommand):
    help = 'READ-ONLY accuracy + speed benchmark of the catalog matcher on confirmed matches'

    def add_arguments(self, p):
        p.add_argument('--memory', action='store_true', help='include the learned memory')
        p.add_argument('--lang', choices=['ar', 'latin', 'all'], default='all')
        p.add_argument('--misses', type=int, default=0, help='list this many misses')
        p.add_argument('--baseline', action='store_true', help='without Arabic→Latin sound matching')

    def handle(self, *a, **o):
        from apps.catalog.models import Item
        from apps.shortage import matching
        matching.SOUND_MATCHING = not o['baseline']
        pairs = ground_truth()
        if o['lang'] != 'all':
            pairs = [p for p in pairs if bool(AR.search(p[0])) == (o['lang'] == 'ar')]
        res = evaluate(pairs, memory=o['memory'])
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'═══ Matcher benchmark — {res["all"]["n"] if res["all"] else 0} distinct confirmed lines '
            f'({len(pairs)} line→item pairs), memory {"ON" if o["memory"] else "OFF"} ═══'))
        for k in ('all', 'arabic', 'latin'):
            b = res[k]
            if b:
                self.stdout.write(f'  {k:7} n={b["n"]:4}  top1 {b["top1"]:5}%  top3 {b["top3"]:5}%  '
                                  f'top5 {b["top5"]:5}%  avg {b["avg_ms"]:4} ms  p95 {b["p95_ms"]:4} ms')
        if o['misses']:
            names = dict(Item.objects.filter(id__in={r['item_id'] for r in res['rows']}).values_list('id', 'name'))
            self.stdout.write(self.style.MIGRATE_HEADING('  misses (not top-1):'))
            for r in [r for r in res['rows'] if r['rank'] != 1][:o['misses']]:
                self.stdout.write(f'   [{r["source"][:5]}] rank {str(r["rank"] or "-"):>2} | {r["text"][:32]:32} | '
                                  f'want {names.get(r["item_id"], "")[:30]:30} | got {r["top"][:30]}')
