"""
python manage.py import_pivot_snapshot <file.xlsx> --exported-at YYYY-MM-DD

P-31: keep a saved demand pivot (e.g. purchasing-pivot-2026-10-19.xlsx) as a sent need sheet, so the
received-without-order check has history from day one. Reads `itemcode`, `Items_.كود-المورد` and
`Total.الفرق-مطلوب/راكد` from the header row (headers matched exactly); a missing column refuses the file.
Local file only — no SOFTECH, no change to the file. Importing the same file twice for the same day stores it once.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.purchasing import pivot_sheets as P


class Command(BaseCommand):
    help = 'Import a saved demand pivot (.xlsx) as a sent need sheet (P-31).'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--exported-at', required=True, help='The day the sheet was sent (YYYY-MM-DD).')

    def handle(self, path, exported_at, **opts):
        import openpyxl
        try:
            day = datetime.date.fromisoformat(exported_at)
        except ValueError:
            raise CommandError('--exported-at must be YYYY-MM-DD')
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise CommandError(f'Cannot open {path}: {exc}')
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header, cols = None, None
        for _ in range(5):                       # the header is row 2 in our export; allow a little slack
            row = next(rows, None)
            if row is None:
                break
            names = [str(v).strip() if v is not None else '' for v in row]
            if P.CODE_HEADER in names and P.GAP_HEADER in names:
                header = names
                break
        if header is None:
            raise CommandError(f'No header row with «{P.CODE_HEADER}» and «{P.GAP_HEADER}» in the first rows.')
        c_code, c_gap = header.index(P.CODE_HEADER), header.index(P.GAP_HEADER)
        c_sup = header.index(P.SUPPLIER_HEADER) if P.SUPPLIER_HEADER in header else None
        cov_cols = [header.index(h) if h in header else None for h in (P.COVER_HEADER, P.RATE_HEADER, P.STOCK_HEADER)]
        lines, covers = [], {}
        for row in rows:
            if row is None or len(row) <= max(c_code, c_gap) or row[c_code] is None:
                continue
            if None not in cov_cols:
                cv = P.cover_entry(*(row[c] if isinstance(row[c], (int, float)) else None for c in cov_cols))
                if cv is not None:
                    covers[str(row[c_code]).strip()] = cv
            gap = row[c_gap]
            if not isinstance(gap, (int, float)):
                continue
            lines.append({'item_code': row[c_code], 'total_gap': gap,
                          'supplier_code': row[c_sup] if c_sup is not None and row[c_sup] is not None else ''})
        when = timezone.make_aware(datetime.datetime.combine(day, datetime.time(12, 0)))
        s = P.record_snapshot(lines, staff=None, run=None, params={'imported_from': str(path)}, source='import',
                              exported_at=when, file_name=str(path).replace('\\', '/').rsplit('/', 1)[-1],
                              covers=covers)
        if s is None:
            self.stdout.write(f'Already imported for that day — kept; {len(covers)} well-covered items on file '
                              f'(filled in when the stored copy had none).')
        else:
            self.stdout.write(f'Stored sheet #{s.pk}: {s.line_count} items with a positive Total gap, '
                              f'{len(s.covers)} already well covered, dated {day}.')
