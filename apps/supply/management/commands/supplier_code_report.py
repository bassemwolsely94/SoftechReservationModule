"""
How many supplier lines match by the supplier's own code (after the itemssuppliers mirror):

    python manage.py supplier_code_report                 # last 90 days, summary
    python manage.py supplier_code_report --days 30 --xlsx supplier_codes.xlsx
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Supplier-code match coverage across availability lists and supplier invoices.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--xlsx', default='', help='Also write the full report to this Excel file.')

    def handle(self, *args, **opts):
        from apps.supply import code_report
        rep = code_report.build(opts['days'])
        m, t = rep['mirror'], rep['totals']
        w = self.stdout.write
        w('itemssuppliers copy: ' + ('EMPTY — run sync_item_suppliers once SOFTECH is reachable' if m['empty']
          else f"{m['links']:,} links · {m['with_code']:,} with a supplier code · {m['suppliers']} suppliers "
               f"· synced {str(m['synced_at'])[:16]}"))
        w(f"last {rep['days']} days: {t['lines']} supplier lines · {t['with_code']} with a code ({t['code_rate'] or 0}%)")
        w(f"  matched by code now: {t['matched']} ({t['match_rate'] or 0}%) — confirmed mapping {t['by_mapping']}, "
          f"SOFTECH copy {t['by_mirror']}; ambiguous {t['ambiguous']}; unknown {t['unknown']}")
        w(f"  unmatched lines the code now resolves: {t['newly_matchable']}")
        w(f"  confirmed lines: code agrees {t['agrees']} · CONFLICTS {t['conflicts']}; barcode matches {t['by_barcode']}")
        for s in rep['suppliers'][:15]:
            w(f"  {s['supplier'][:28]:28} lines {s['lines']:4}  code {s['with_code']:4}  matched {s['matched']:4}"
              f"  conflicts {s['conflicts']:3}  copy codes {s['mirror_codes']}")
        if opts['xlsx']:
            with open(opts['xlsx'], 'wb') as f:
                f.write(code_report.to_excel(rep))
            self.stdout.write(self.style.SUCCESS(f"written {opts['xlsx']}"))
