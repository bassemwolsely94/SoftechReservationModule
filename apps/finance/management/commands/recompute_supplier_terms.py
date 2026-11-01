"""
P-42: rebuild the category slices and due dates of every open supplier invoice (or one supplier's) from the
finance-entered terms. PostgreSQL only — reads the A/P mirror and procurement.PurchaseLine, never SOFTECH.

    python manage.py recompute_supplier_terms
    python manage.py recompute_supplier_terms --personcode 565
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'P-42: rebuild open supplier invoice slices (local / imported) and due dates from supplier terms.'

    def add_arguments(self, parser):
        parser.add_argument('--personcode', default=None)

    def handle(self, *args, **opts):
        from apps.finance import supplier_terms as ST
        n = ST.recompute(opts['personcode'])
        c = ST.terms_coverage()
        self.stdout.write(f'slices: {n} · open real payables: {c["open_real"]:,.2f} · '
                          f'with terms: {c["with_terms"]:,.2f} ({c["coverage_pct"] if c["coverage_pct"] is not None else "—"}%)')
