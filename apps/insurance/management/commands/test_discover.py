"""Test discover endpoint across ALL personcodes in a date range."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Discover motalbas for all personcodes in Softech within a date range'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', default='2026-01-01')
        parser.add_argument('--to',   dest='date_to',   default='2026-06-30')

    def handle(self, *args, **opts):
        from apps.insurance.sybase_queries import QUERY_DISCOVER_MOTALBAS_BY_DATERANGE
        from apps.insurance.models import InsuranceSubClient
        from config.sybase import get_sybase_connection

        date_from = opts['date_from']
        date_to   = opts['date_to']

        conn = get_sybase_connection()
        cursor = conn.cursor()
        cursor.execute(QUERY_DISCOVER_MOTALBAS_BY_DATERANGE, [date_from, date_to])
        rows = cursor.fetchall()

        # Build personcode → subclient map
        pc_map = {}
        for sc in InsuranceSubClient.objects.select_related('client').all():
            for pc in sc.get_all_personcodes():
                pc_map[pc] = sc

        self.stdout.write(f'Motalbas in Softech from {date_from} to {date_to}:')
        self.stdout.write(f'Total: {len(rows)}')
        self.stdout.write('')

        by_pc: dict[str, list] = {}
        for r in rows:
            pc = str(r[0]).strip() if r[0] else 'UNKNOWN'
            by_pc.setdefault(pc, []).append(r)

        for pc, pc_rows in sorted(by_pc.items()):
            sc = pc_map.get(pc)
            label = f'{sc.client.name} — {sc.name}' if sc else f'[NOT CONFIGURED] personcode={pc}'
            total_rx = sum(int(r[4] or 0) for r in pc_rows)
            self.stdout.write(f'  {label}  ({len(pc_rows)} motalbas  {total_rx} Rx total)')
            for r in pc_rows[:5]:
                mot = int(str(r[1]).split('.')[0])
                self.stdout.write(f'    mot={mot}  {str(r[2])[:10]} → {str(r[3])[:10]}  rx={r[4]}  total={float(r[5] or 0):,.2f}')
            if len(pc_rows) > 5:
                self.stdout.write(f'    ... and {len(pc_rows)-5} more')
            self.stdout.write('')
