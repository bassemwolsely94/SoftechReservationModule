"""
compute_forecast_references  (doc 16, Phase 8)
==============================================
Recompute the grounded forecast reference values (seasonality + benchmark from history,
growth plan from inflation + real growth) and store them. Run monthly after the rollups
refresh. Inflation is EXTERNAL — pass --inflation when CAPMAS publishes a new figure;
otherwise the last-entered value is kept.

  python manage.py compute_forecast_references
  python manage.py compute_forecast_references --real-growth 0.15 --inflation 0.145 \
        --inflation-source "CAPMAS Aug-2026 urban 14.5%"
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Compute & store grounded forecast reference values (seasonality/benchmark/growth/inflation).'

    def add_arguments(self, parser):
        parser.add_argument('--real-growth', type=float, default=None,
                            help='Target REAL growth above inflation (e.g. 0.15). Keeps last if omitted.')
        parser.add_argument('--inflation', type=float, default=None,
                            help='Egypt annual CPI as a fraction (e.g. 0.145). Keeps last if omitted.')
        parser.add_argument('--inflation-source', default='', help='Citation for the inflation figure.')

    def handle(self, *args, **o):
        from apps.forecasting import references as R
        prev = R.get() or {}
        rg = o['real_growth'] if o['real_growth'] is not None else float(prev.get('real_growth', 0.15))
        refs = R.compute(real_growth=rg, inflation_annual=o.get('inflation'),
                         inflation_source=o.get('inflation_source', ''))
        self.stdout.write(self.style.SUCCESS(
            f"Stored references (as_of {refs['as_of']}). "
            f"inflation {refs['inflation_annual']*100:.1f}%/yr (~{refs['inflation_monthly']*100:.2f}%/mo), "
            f"real growth {refs['real_growth']*100:.0f}%."))
        self.stdout.write(f"{'metric':<16}{'hist YoY':>10}{'benchmark':>11}{'growth goal':>13}")
        for m in refs['growth_goal']:
            self.stdout.write(
                f"{m:<16}{refs['historical_yoy'].get(m,0)*100:>9.1f}%"
                f"{refs['benchmark'].get(m,0)*100:>10.1f}%{refs['growth_goal'][m]*100:>12.1f}%")
