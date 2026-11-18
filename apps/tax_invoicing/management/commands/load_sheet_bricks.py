"""Copy each item's GPC brick from the owner's sheet «ElRezeiky GPC Applied» (column «أكواد الضرائب») into
TaxItemProfile.gpc_code. Fills only profiles whose brick is empty or '0', and only with an 8-digit brick the GPC list
knows. Never overwrites a brick, never writes the sheet. Audited as one event listing every item it set."""
import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.tax_invoicing import gpc
from apps.tax_invoicing.models import TaxItemProfile
from apps.tax_invoicing.services import audit

SHEET = 'ElRezeiky GPC Applied'
CODE_COL = 'itemcode'
BRICK_COL = 'أكواد الضرائب'


def read_sheet(path):
    """[(itemcode, brick text)] from the sheet; header row 1, columns matched by name."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET not in wb.sheetnames:
            raise ValueError(f'no sheet named «{SHEET}»')
        rows = wb[SHEET].iter_rows(values_only=True)
        header = [gpc._text(h) for h in (next(rows, None) or ())]
        if CODE_COL not in header or BRICK_COL not in header:
            raise ValueError(f'sheet «{SHEET}» needs columns «{CODE_COL}» and «{BRICK_COL}» in row 1')
        ci, bi = header.index(CODE_COL), header.index(BRICK_COL)
        out = []
        for r in rows:
            code = gpc._text(r[ci]) if ci < len(r) else ''
            if code:
                out.append((code, gpc._text(r[bi]) if bi < len(r) else ''))
        return out
    finally:
        wb.close()


def apply(rows):
    counts = {'read': len(rows), 'set': 0, 'already_set': 0, 'blank': 0, 'bad_brick': 0, 'unknown_brick': 0,
              'no_profile': 0}
    profiles = {p.softech_itemcode: p for p in TaxItemProfile.objects.filter(softech_itemcode__in=[c for c, _ in rows])}
    known = {}
    now = timezone.now()
    changed = {}
    for code, brick in rows:
        p = profiles.get(code)
        if p is None:
            counts['no_profile'] += 1
        elif not brick or brick == '0':
            counts['blank'] += 1
        elif not gpc.BRICK.match(brick):
            counts['bad_brick'] += 1
        elif p.gpc_code not in ('', '0'):
            counts['already_set'] += 1
        else:
            if brick not in known:    # one lookup per distinct brick
                known[brick] = gpc.known(brick)
            if not known[brick]:
                counts['unknown_brick'] += 1
                continue
            p.gpc_code, p.updated_at = brick, now
            changed[code] = p
    with transaction.atomic():
        TaxItemProfile.objects.bulk_update(list(changed.values()), ['gpc_code', 'updated_at'], batch_size=1000)
    counts['set'] = len(changed)
    return counts, {c: p.gpc_code for c, p in changed.items()}


class Command(BaseCommand):
    help = f'Fill empty item GPC bricks from the owner\'s sheet «{SHEET}» (column «{BRICK_COL}»).'

    def add_arguments(self, parser):
        parser.add_argument('path')

    def handle(self, *args, **opts):
        try:
            rows = read_sheet(opts['path'])
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        counts, done = apply(rows)
        audit('gpc_sheet_bricks_loaded', actor=None, entity='gpc', reason=SHEET,
              after={'counts': counts, 'set': done})
        self.stdout.write(', '.join(f'{k} {v}' for k, v in counts.items()))
