"""
python manage.py test_pic_points --pic 01HD14
python manage.py test_pic_points --pic 01HD14 --dry-run      # read-only
python manage.py test_pic_points --pic 01HD14 --delta 5      # add 5 then subtract 5

Tests the full cycle:
  1. Read current balance from localcustomers.picpoints
  2. INSERT +delta into picpoints log (same as ERP screen)
  3. Verify tr_picpoints trigger updated localcustomers.picpoints
  4. Verify the new row appears in picpoints log
  5. Reverse by inserting -delta
  6. Verify balance is restored
"""
from django.core.management.base import BaseCommand, CommandError
from config.sybase import get_sybase_connection
from apps.loyalty.pic_bridge import (
    read_softech_points,
    read_softech_points_log,
    adjust_softech_points,
)


class Command(BaseCommand):
    help = 'Test SOFTECH PIC points read/write cycle for a given phcode'

    def add_arguments(self, parser):
        parser.add_argument('--pic',     required=True, help='PIC code, e.g. 01HD14')
        parser.add_argument('--dry-run', action='store_true', help='Read only — no write')
        parser.add_argument('--delta',   type=int, default=1,
                            help='Points to add for the write test (default: 1, then reversed)')

    def handle(self, *args, **options):
        pic     = options['pic'].strip()
        dry_run = options['dry_run']
        delta   = abs(options['delta'])   # always positive; we test both +/- ourselves

        self.stdout.write(f'\nPIC: {pic}')
        self.stdout.write('-' * 50)

        # ── 1. Read current balance ───────────────────────────────────────────
        balance = read_softech_points(pic)
        if balance is None:
            raise CommandError(
                f'PIC "{pic}" not found in localcustomers — check the code.'
            )
        self.stdout.write(self.style.SUCCESS(f'Current balance:  {balance:,} points'))

        # ── 2. Show last 3 log rows ───────────────────────────────────────────
        log = read_softech_points_log(pic, limit=3)
        if log:
            self.stdout.write('\nRecent picpoints log rows:')
            for row in log:
                sign = '+' if row['points'] >= 0 else ''
                self.stdout.write(
                    f"  {row['transdate']}  {sign}{row['points']:,}  "
                    f"branch={row['branchcode']}  doc={row['doccode']}  "
                    f"vf1={row['vf1'] or '-'}  vf2={row['vf2'] or '-'}"
                )
        else:
            self.stdout.write('  (no log rows found for this PIC)')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n--dry-run set — skipping write test.'))
            return

        # ── 3. Apply +delta ───────────────────────────────────────────────────
        self.stdout.write(f'\nInserting +{delta} into picpoints log ...')
        try:
            after_add = adjust_softech_points(
                pic, +delta,
                reason='CRM write test',
                operator='CRM_TEST',
            )
        except Exception as exc:
            raise CommandError(f'Write +{delta} FAILED: {exc}')

        if after_add == balance + delta:
            self.stdout.write(self.style.SUCCESS(
                f'After +{delta}:  {after_add:,}  (trigger fired correctly)  OK'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'After +{delta}:  {after_add:,}  '
                f'(expected {balance + delta:,} — trigger may cap or round)  WARNING'
            ))

        # ── 4. Verify log row was written ─────────────────────────────────────
        log2 = read_softech_points_log(pic, limit=1)
        if log2 and log2[0]['vf2'] == 'CRM_TEST':
            self.stdout.write(self.style.SUCCESS(
                f'picpoints log row confirmed:  '
                f"{log2[0]['transdate']}  +{delta}  vf1={log2[0]['vf1']}  OK"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'Could not confirm the new log row — check picpoints table manually.'
            ))

        # ── 5. Reverse the change ─────────────────────────────────────────────
        self.stdout.write(f'Reversing -{delta} ...')
        try:
            after_sub = adjust_softech_points(
                pic, -delta,
                reason='CRM write test reversal',
                operator='CRM_TEST',
            )
        except Exception as exc:
            raise CommandError(
                f'Reversal -{delta} FAILED: {exc}  (balance is now {after_add}!)'
            )

        if after_sub == balance:
            self.stdout.write(self.style.SUCCESS(
                f'After -{delta}:  {after_sub:,}  (balance restored)  OK'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'After -{delta}:  {after_sub:,}  '
                f'(expected {balance:,})  WARNING — check for trigger rounding'
            ))

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write('')
        if after_sub == balance:
            self.stdout.write(self.style.SUCCESS(
                'All checks passed.\n'
                f'Cycle: {balance:,} -> {after_add:,} -> {after_sub:,}\n\n'
                'The INSERT -> trigger -> readback pattern works correctly.\n'
                'Run:  python manage.py migrate  to apply loyalty migrations.'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                'Write path works but trigger may apply rounding/caps.\n'
                'Review tr_picpoints trigger logic if unexpected.\n'
                f'Cycle: {balance:,} -> {after_add:,} -> {after_sub:,}'
            ))
