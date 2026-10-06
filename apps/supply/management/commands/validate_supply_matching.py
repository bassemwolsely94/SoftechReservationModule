"""
Measure supplier-list parsing + catalog matching on the messy ground-truth corpus against
the LIVE catalog. Read-only.

    python manage.py validate_supply_matching
    python manage.py validate_supply_matching --corpus path/to/cases.json --strict
      --strict  → exit non-zero if any wrong match scores at/above the trust bar
"""
import sys

from django.core.management.base import BaseCommand

from apps.supply import validation


class Command(BaseCommand):
    help = 'Validate supplier-list parsing and catalog matching on messy real-world lines.'

    def add_arguments(self, parser):
        parser.add_argument('--corpus', default=None)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **opts):
        res = validation.run(opts['corpus'])
        for r in res['rows']:
            mark = {'correct_confident': '✓', 'correct_review': '~', 'absent_ok': '✓',
                    'wrong_flagged': '!', 'no_match': '?', 'wrong_confident': '✗✗'}[r['outcome']]
            self.stdout.write(f"{mark:2} {r['outcome']:17} {str(r['score']):6} "
                              f"{r['line'][:42]:42} → {r['top'] or '-':>7} {r['top_name'][:44]}"
                              f"   (want {r['expect']}, qty {r['qty']})")
        s = res['summary']
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"cases {s['cases']} · top-1 accuracy {s['top1_accuracy']} · top-3 recall "
            f"{s['top3_recall']} · confident&correct {s['confident_and_correct']} · "
            f"DANGEROUS wrong-confident {s['dangerous_wrong_confident']} · "
            f"qty accuracy {s['qty_accuracy']} · trust bar {s['trust_bar']}"))
        self.stdout.write(f"outcomes: {res['counts']}")
        if opts['strict'] and s['dangerous_wrong_confident']:
            sys.exit(1)
