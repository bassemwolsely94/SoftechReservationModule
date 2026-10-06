"""
apps/supply/validation.py — measure parsing + catalog-match quality on messy real lists
(doc 24 Phase 7, §37/§38).

Runs a ground-truth corpus through the EXACT production path used by the availability
inbox (parse_availability_line → find_best_matches, learned aliases included) against the
live catalog, READ-ONLY, and classifies every case. The class that matters most is
``wrong_confident`` — a wrong item scored at/above the auto-trust bar (§5: fuzzy matching
must never silently create dangerous false matches).

Outcome classes:
  correct_confident  top-1 is an expected code and score ≥ bar   (would be pre-trusted)
  correct_review     top-1 correct but score < bar                (operator confirms)
  wrong_flagged      top-1 wrong but score < bar                  (safe: held for review)
  wrong_confident    top-1 wrong and score ≥ bar                  (DANGEROUS)
  no_match           nothing above the floor
  (expect_none cases) → absent_ok if no confident match, else wrong_confident
"""
from __future__ import annotations

import json
from pathlib import Path

from .availability import parse_availability_line
from .ingest import AUTO_MATCH_SINGLE, review_flags

CORPUS_PATH = Path(__file__).resolve().parent / 'fixtures' / 'messy_availability_corpus.json'


def classify(expect, expect_none, top, score, bar=AUTO_MATCH_SINGLE, guarded=False) -> str:
    """Pure classification of one case (unit-tested). ``guarded`` = the match-safety guard
    raised a reason, so production holds it for review regardless of score."""
    confident = top is not None and score is not None and score >= bar and not guarded
    if expect_none:
        return 'wrong_confident' if confident else 'absent_ok'
    if top is None:
        return 'no_match'
    correct = str(top) in {str(e) for e in (expect or [])}
    if correct:
        return 'correct_confident' if confident else 'correct_review'
    return 'wrong_confident' if confident else 'wrong_flagged'


def run(corpus_path=None, *, vendor_code='') -> dict:
    from apps.shortage.matching import find_best_matches

    data = json.loads(Path(corpus_path or CORPUS_PATH).read_text(encoding='utf-8'))
    rows, counts = [], {}
    qty_ok = qty_total = in_top3 = expected_total = 0
    for case in data['cases']:
        p = parse_availability_line(case['line'])
        hits = find_best_matches(p.name_part, top_n=3, min_score=0.15, vendor_code=vendor_code) \
            if p.name_part else []
        top = hits[0] if hits else None
        # Mirror production: a guarded match is NOT trusted, whatever its score.
        guard = []
        if top and not top.get('learned'):
            runner = hits[1] if len(hits) > 1 else None
            guard = review_flags(p.name_part, top['item_name'],
                                 runner_up_name=runner['item_name'] if runner else '',
                                 score=top['score'], runner_up_score=runner['score'] if runner else None)
        outcome = classify(case.get('expect'), case.get('expect_none'),
                           top['item_softech_id'] if top else None,
                           top['score'] if top else None, guarded=bool(guard))
        counts[outcome] = counts.get(outcome, 0) + 1
        if not case.get('expect_none'):
            expected_total += 1
            if any(str(h['item_softech_id']) in {str(e) for e in case['expect']} for h in hits):
                in_top3 += 1
        if 'qty' in case:
            qty_total += 1
            want = case['qty']
            got = p.supplier_qty
            qty_ok += int((want is None and got is None) or (want is not None and got == float(want)))
        rows.append({
            'line': case['line'], 'name_part': p.name_part, 'qty': p.supplier_qty,
            'expect': case.get('expect') or ('∅' if case.get('expect_none') else None),
            'top': top['item_softech_id'] if top else None,
            'top_name': top['item_name'] if top else '',
            'score': round(top['score'], 3) if top else None,
            'guard': guard,
            'outcome': outcome,
        })
    judged = expected_total
    correct_top1 = counts.get('correct_confident', 0) + counts.get('correct_review', 0)
    return {
        'rows': rows,
        'counts': counts,
        'summary': {
            'cases': len(rows),
            'top1_accuracy': round(correct_top1 / judged, 3) if judged else None,
            'top3_recall': round(in_top3 / judged, 3) if judged else None,
            'confident_and_correct': counts.get('correct_confident', 0),
            'dangerous_wrong_confident': counts.get('wrong_confident', 0),
            'qty_accuracy': round(qty_ok / qty_total, 3) if qty_total else None,
            'trust_bar': AUTO_MATCH_SINGLE,
        },
    }
