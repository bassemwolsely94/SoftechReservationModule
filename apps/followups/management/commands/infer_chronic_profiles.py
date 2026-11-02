"""
infer_chronic_profiles
======================
Rebuild the chronic medicine list (ChronicMedicationProfile) from patients' repeat purchases
in the synced SOFTECH sales. Dry run unless --apply. Manual profiles are never touched.

Usage:
  python manage.py infer_chronic_profiles                    # report only
  python manage.py infer_chronic_profiles --apply
  python manage.py infer_chronic_profiles --min-patients 8 --months 18
"""
from collections import Counter

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Infer chronic medicines from steady repeat purchases (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--months', type=int, default=24)
        parser.add_argument('--min-patients', type=int, default=5)
        parser.add_argument('--min-episodes', type=int, default=3)
        parser.add_argument('--min-share', type=float, default=0.05,
                            help='Steady rebuyers ÷ all buyers of the item (0.05 = 5%%)')
        parser.add_argument('--top', type=int, default=40, help='How many items to list')

    def handle(self, *args, **o):
        from apps.followups.services import infer_chronic_profiles_from_sales
        r = infer_chronic_profiles_from_sales(months=o['months'], min_patients=o['min_patients'],
                                              min_episodes=o['min_episodes'], min_share=o['min_share'],
                                              dry_run=not o['apply'])
        mode = 'APPLIED' if o['apply'] else 'DRY RUN'
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: {r['chronic']} chronic medicines | create {r['created']} | update {r['updated']} | "
            f"manual kept {r['protected_manual']} | switch off {r['switched_off']}"))
        cyc = Counter(min(d // 15 * 15, 90) for _, d, *_ in r['items'])
        self.stdout.write('Cycle (days, from): ' + ', '.join(f'{k}+: {v}' for k, v in sorted(cyc.items())))
        self.stdout.write('By therapeutic class: ' + ', '.join(
            f'{k or "—"}: {v}' for k, v in Counter(e for _, _, _, e, _ in r['items']).most_common(15)))
        self.stdout.write(f"Top {o['top']} by steady patients (item · cycle days · patients · share of buyers · class):")
        for name, d, n, eff, share in r['items'][:o['top']]:
            self.stdout.write(f'  {name[:44]:44} {d:>4}d {n:>5} {share:>5}%  {eff}')
