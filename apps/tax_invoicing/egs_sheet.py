"""The owner's bulk EGS sheet (ElRezeiky_Bulk_EGS_Items.xlsx) — the workbook the Invoicer reads to know which items
are coded. Doc 36, batch S3.

This module keeps its versions: `store` writes one version's file under TAX_EGS_SHEET_DIR and its row
(TaxEgsSheetVersion), keeping the newest 10 files; `latest` / `open_version` read them back; `read_counts` reads a
workbook's DataEntry sheet (coded row = CodeType (A) and ActiveFrom (G) filled; itemcode = EGSRelatedCode (J)).
The owner's original file is only ever read."""
import hashlib
import io
from pathlib import Path

import openpyxl
from django.conf import settings
from django.db import transaction

from apps.tax_invoicing.gpc import _text
from apps.tax_invoicing.models import TaxEgsSheetVersion

SHEET = 'DataEntry'
HEADER = ['CodeType', 'ItemCode', 'CodeName', 'CodeName2Ar', 'Description', 'DescriptionAr', 'ActiveFrom', 'ActiveTo',
          'GPCItemLinked', 'EGSRelatedCode', 'VAT %', 'VAT 0% "=1"\nVAT 14% "=0"', '', 'Blacklist', 'VAT % in Value',
          'VAT Code']
COL_A, COL_G, COL_J = 0, 6, 9
KEEP_FILES = 10


class SheetError(Exception):
    """The workbook or a stored version cannot be used; the message is Arabic, for the screen."""


def _header_text(v):
    return _text(v).replace('\r\n', '\n')


def read_counts(data):
    """{'total_rows', 'coded_rows', 'coded_itemcodes'} from a workbook's bytes. A data row = one with an itemcode in J;
    itemcodes are text as SOFTECH writes them (100 stored as a number reads '100'; text keeps leading zeros)."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
    except Exception as exc:    # openpyxl raises several types for a non-workbook
        raise SheetError('الملف ليس ملف Excel صالحاً') from exc
    try:
        if SHEET not in wb.sheetnames:
            raise SheetError(f'لا توجد ورقة باسم «{SHEET}» في الملف')
        rows = wb[SHEET].iter_rows(values_only=True)
        header = [_header_text(h) for h in (next(rows, None) or ())][:len(HEADER)]
        if header != HEADER:
            raise SheetError(f'عناوين ورقة «{SHEET}» ليست عناوين ملف الأكواد')
        total = coded = 0
        codes = set()
        for r in rows:
            code = _text(r[COL_J]) if len(r) > COL_J else ''
            if not code:
                continue
            total += 1
            if _text(r[COL_A]) and _text(r[COL_G]):
                coded += 1
                codes.add(code)
        return {'total_rows': total, 'coded_rows': coded, 'coded_itemcodes': sorted(codes)}
    finally:
        wb.close()


def _dir():
    return Path(settings.TAX_EGS_SHEET_DIR)


def latest():
    return TaxEgsSheetVersion.objects.order_by('-number').first()


def store(data, *, source, built_by=None, note='', coded_rows=0, total_rows=0, added=(), coded=(), skipped=(),
          coded_itemcodes=()):
    """Writes `data` as the next version: file first, then the row; a failed row removes the file. Then removes the
    files of all but the newest KEEP_FILES versions (their rows stay)."""
    folder = _dir()
    folder.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    with transaction.atomic():
        prev = TaxEgsSheetVersion.objects.select_for_update().order_by('-number').first()
        number = (prev.number if prev else 0) + 1
        name = f'egs_sheet_v{number:04d}_{sha[:12]}.xlsx'
        path = folder / name
        path.write_bytes(data)
        try:
            version = TaxEgsSheetVersion.objects.create(
                number=number, sha256=sha, file_name=name, size=len(data), coded_rows=coded_rows,
                total_rows=total_rows, added=list(added), coded=list(coded), skipped=list(skipped),
                coded_itemcodes=list(coded_itemcodes), source=source, built_by=built_by, note=note[:300])
        except Exception:
            path.unlink(missing_ok=True)
            raise
    _prune()
    return version


def _prune():
    keep = set(TaxEgsSheetVersion.objects.order_by('-number').values_list('file_name', flat=True)[:KEEP_FILES])
    for name in TaxEgsSheetVersion.objects.exclude(file_name__in=keep).values_list('file_name', flat=True):
        (_dir() / name).unlink(missing_ok=True)


def open_version(version):
    """The stored file's bytes; SheetError when its file was pruned or is missing."""
    path = _dir() / version.file_name
    if not path.is_file():
        raise SheetError(f'ملف النسخة {version.number} لم يعد محفوظاً (تُحفظ ملفات آخر {KEEP_FILES} نسخ فقط)')
    return path.read_bytes()
