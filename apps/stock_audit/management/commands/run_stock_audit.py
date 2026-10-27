"""
run_stock_audit
===============
Doc 32 Phase 2 — run the stock-audit checks over the StockLedgerLine mirror and upsert findings.
Reads our Postgres mirror only (never SOFTECH). Idempotent.

Usage:
  python manage.py run_stock_audit                         # last 30 days, all enabled checks
  python manage.py run_stock_audit --days 7 --rule sale_below_cost --branch 160
  python manage.py run_stock_audit --seed                  # create/refresh the rule rows only
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Run the stock-transactions audit checks over the ledger mirror.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--rule', action='append', default=[], help='Rule code (repeatable).')
        parser.add_argument('--branch', action='append', default=[], help='Branch code (repeatable).')
        parser.add_argument('--seed', action='store_true', help='Only create/refresh the rule rows.')
        parser.add_argument('--triggered-by', default='run_stock_audit')

    def handle(self, *args, **opts):
        from apps.stock_audit.engine import run_stock_audit
        from apps.stock_audit.params import ensure_rules
        from apps.stock_audit.rules import RULES

        unknown = [r for r in opts['rule'] if r not in RULES]
        if unknown:
            raise CommandError(f'unknown rule(s): {", ".join(unknown)} — known: {", ".join(RULES)}')
        if opts['seed']:
            rules = ensure_rules()
            self.stdout.write(self.style.SUCCESS(f'rules ready: {", ".join(sorted(rules))}'))
            return

        run = run_stock_audit(days=opts['days'], rules=opts['rule'] or None,
                              branches=opts['branch'] or None, triggered_by=opts['triggered_by'])
        style = self.style.SUCCESS if run.status == 'success' else self.style.WARNING
        self.stdout.write(style(f'run #{run.pk} {run.status}: {run.date_from} → {run.date_to}'))
        for code, c in run.counts.items():
            if 'error' in c:
                self.stdout.write(self.style.ERROR(f'  {code}: FAILED — {c["error"]}'))
            else:
                self.stdout.write(f'  {code}: seen={c["seen"]} new={c["new"]} updated={c["updated"]} '
                                  f'reopened={c["reopened"]}')
