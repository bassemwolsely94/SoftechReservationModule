"""
build_call_center_rollups  (doc 16, Phase 5)
============================================
Materialise the Call Center KPI overlay into KpiActualRollup under a dedicated
"Call Center" branch (is_operational=False → excluded from the branch grid/totals):
  sales / profit / beauty / orders  ← invoices by CC sales agents (SOFTECH usercodes)
  call_count                        ← Issabel CDR (live DB, or a --cdr-csv export)

Usage:
  python manage.py build_call_center_rollups --year 2026 --month 6
  python manage.py build_call_center_rollups --year 2026 --month 5 --cdr-csv "path/to/cdr_may.csv"
  python manage.py build_call_center_rollups --months 12          # sales side; call_count only if CDR live

The "Call Center" branch is auto-created (softech_branch_id='CC').
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


CC_BRANCH_KEY = 'CC'


def get_cc_branch():
    from apps.branches.models import Branch
    b, _ = Branch.objects.get_or_create(
        softech_branch_id=CC_BRANCH_KEY,
        defaults={'code': CC_BRANCH_KEY, 'name': 'Call Center',
                  'name_ar': 'الكول سنتر', 'is_operational': False, 'is_active': True})
    return b


class Command(BaseCommand):
    help = 'Build Call Center KPI rollups (sales/profit/beauty/orders + CDR call_count)'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)
        parser.add_argument('--month', type=int)
        parser.add_argument('--months', type=int, help='Last N completed months (sales side)')
        parser.add_argument('--cdr-csv', help='Issabel CDR CSV export for the call_count of a single month')

    def handle(self, *args, **opts):
        from apps.forecasting.kpi import KpiResolver
        from apps.forecasting.models import KpiActualRollup as K, CallCenterConfig

        cfg = CallCenterConfig.get_solo()
        if not cfg.sales_agent_usercodes:
            raise CommandError('No CC sales agent usercodes configured (CallCenterConfig).')
        periods = self._periods(opts)
        cc = get_cc_branch()
        resolver = KpiResolver()

        for (year, month) in periods:
            # Gross sales/profit/beauty/orders from the mirror (CC sales agents).
            kpis = resolver.compute_call_center_month(year, month, cfg.sales_agent_usercodes)
            # Penny-exact net: subtract CC returns (returns linked to a CC sale via
            # stktrans.r_docnumber — SOFTECH doesn't stamp the CC agent on returns).
            ret = self._cc_returns(cfg, year, month)
            if ret is not None:
                kpis[K.M_CASH_DELIVERY] = kpis.get(K.M_CASH_DELIVERY, 0) - ret['amount']
                kpis[K.M_GROSS_PROFIT] = kpis.get(K.M_GROSS_PROFIT, 0) - ret['profit']
            call_count = self._call_count(cfg, year, month, opts.get('cdr_csv'), single=len(periods) == 1)
            if call_count is not None:
                kpis[K.M_CALL_COUNT] = call_count
            with transaction.atomic():
                for metric, val in kpis.items():
                    K.objects.update_or_create(
                        branch=cc, year=year, month=month, metric=metric,
                        defaults={'value': val})
            self.stdout.write(
                f"  CC {year}-{month:02d}: net_sales={float(kpis.get('cash_delivery',0)):,.0f} "
                f"profit={float(kpis.get('gross_profit',0)):,.0f} "
                f"beauty={float(kpis.get('beauty',0)):,.0f} "
                f"orders={int(kpis.get('customer_count',0))} "
                f"returns={float(ret['amount']) if ret else 0:,.0f} "
                f"calls={int(call_count) if call_count is not None else '—'}")

        self.stdout.write(self.style.SUCCESS(f'Done: {len(periods)} month(s).'))

    def _cc_returns(self, cfg, year, month):
        """CC returns (amount+profit) from SOFTECH via r_docnumber; None if unreachable."""
        try:
            from apps.forecasting.cc_softech import cc_returns_from_softech
            return cc_returns_from_softech(year, month, cfg.sales_agent_usercodes)
        except Exception as e:
            self.stderr.write(f'CC returns (SOFTECH) skipped for {year}-{month:02d}: {e}')
            return None

    def _call_count(self, cfg, year, month, csv_path, single):
        from apps.forecasting.callcount import count_calls_from_csv, count_calls
        if csv_path and single:
            try:
                return count_calls_from_csv(csv_path, cfg.call_agent_extensions)
            except Exception as e:
                self.stderr.write(f'CDR CSV read failed: {e}')
                return None
        # live CDR DB
        try:
            from config.issabel import cdr_configured, fetch_cdr_rows
            if not cdr_configured():
                return None
            from calendar import monthrange
            start = date(year, month, 1)
            ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
            rows = fetch_cdr_rows(start, date(ny, nm, 1))
            return count_calls(rows, cfg.call_agent_extensions)
        except Exception as e:
            self.stderr.write(f'Live CDR pull skipped: {e}')
            return None

    def _periods(self, opts):
        if opts.get('months'):
            today = date.today(); y, m = today.year, today.month; out = []
            for _ in range(opts['months']):
                m -= 1
                if m == 0:
                    m = 12; y -= 1
                out.append((y, m))
            return list(reversed(out))
        if opts.get('year') and opts.get('month'):
            return [(opts['year'], opts['month'])]
        raise CommandError('Provide --year & --month, or --months N')
