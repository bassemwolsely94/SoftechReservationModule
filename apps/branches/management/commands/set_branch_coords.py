"""
Bulk-set branch GPS coordinates (for the attendance geofence + delivery pickup).

Usage:
    python manage.py set_branch_coords --report
        Print current coverage (how many branches have lat/lng).

    python manage.py set_branch_coords path/to/coords.csv [--dry-run]
        Import coordinates from a CSV with a header row:
            branch_code,latitude,longitude
        `branch_code` matches Branch.softech_branch_id (falls back to pk).
        Rows with blank lat/lng are skipped.

Coordinates can also be edited per-branch via the branch settings API/admin
(latitude/longitude are exposed on the Branch serializer).
"""
import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from apps.branches.models import Branch


class Command(BaseCommand):
    help = 'Set branch GPS coordinates from a CSV, or report current coverage.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', nargs='?', default=None,
                            help='CSV with columns: branch_code, latitude, longitude')
        parser.add_argument('--report', action='store_true', help='Print coverage and exit')
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving')

    def _report(self):
        total = Branch.objects.count()
        withc = Branch.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True).count()
        self.stdout.write(f'Branches with coordinates: {withc}/{total}')
        missing = Branch.objects.filter(latitude__isnull=True) | Branch.objects.filter(longitude__isnull=True)
        for b in missing.distinct().order_by('softech_branch_id'):
            self.stdout.write(f'  MISSING  {b.softech_branch_id or b.pk}  {b.name_ar or b.name}')

    def handle(self, *args, **opts):
        if opts['report'] or not opts['csv_path']:
            self._report()
            if not opts['csv_path']:
                return

        path = opts['csv_path']
        dry = opts['dry_run']
        updated, skipped, missing = 0, 0, []

        try:
            f = open(path, encoding='utf-8-sig')
        except OSError as e:
            raise CommandError(f'Cannot open {path}: {e}')

        with f:
            reader = csv.DictReader(f)
            cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
            need = ('branch_code', 'latitude', 'longitude')
            if not all(n in cols for n in need):
                raise CommandError(f'CSV must have columns: {", ".join(need)} (got {reader.fieldnames})')

            for row in reader:
                code = str(row[cols['branch_code']]).strip()
                lat_s = str(row[cols['latitude']]).strip()
                lng_s = str(row[cols['longitude']]).strip()
                if not code or not lat_s or not lng_s:
                    skipped += 1
                    continue
                try:
                    lat, lng = Decimal(lat_s), Decimal(lng_s)
                except InvalidOperation:
                    self.stderr.write(f'  bad number for {code}: {lat_s},{lng_s}')
                    skipped += 1
                    continue

                branch = Branch.objects.filter(softech_branch_id=code).first()
                if not branch and code.isdigit():
                    branch = Branch.objects.filter(pk=int(code)).first()
                if not branch:
                    missing.append(code)
                    continue

                if dry:
                    self.stdout.write(f'  would set {code} → {lat},{lng}  ({branch.name_ar or branch.name})')
                else:
                    branch.latitude, branch.longitude = lat, lng
                    branch.save(update_fields=['latitude', 'longitude'])
                updated += 1

        verb = 'would update' if dry else 'updated'
        self.stdout.write(self.style.SUCCESS(
            f'Done — {verb} {updated} | skipped {skipped} | unmatched codes: {missing or "none"}'
        ))
