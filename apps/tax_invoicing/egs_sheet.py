"""The owner's bulk EGS sheet (ElRezeiky_Bulk_EGS_Items.xlsx) — the workbook the Invoicer reads to know which items
are coded. Doc 36, batch S3.

This module keeps its versions: `store` writes one version's file under TAX_EGS_SHEET_DIR and its row
(TaxEgsSheetVersion), keeping the newest 10 files; `latest` / `open_version` read them back; `read_counts` reads a
workbook's DataEntry sheet (coded row = CodeType (A) and ActiveFrom (G) filled; itemcode = EGSRelatedCode (J)).
`build` makes the next version from the latest: it codes the uncoded row of each newly coded item or appends a row
for an item not in the sheet, never rewriting a coded row; `checks` must pass before a version is accepted.
The owner's original file is only ever read."""
import datetime as dt
import hashlib
import io
import re
from copy import copy
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter, range_boundaries

from apps.tax_invoicing.gpc import _text
from apps.tax_invoicing.models import (EtaCodeUsage, TaxCodingDecision, TaxEgsSheetVersion, TaxIssuerProfile,
                                       TaxItemProfile)
from apps.tax_invoicing.services import audit

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
        # data_only: cached values, so a formula text never reads as an itemcode or a filled A/G.
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
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
    """Writes `data` as the next version: file first, then the row; a failed row removes the file. Old files (all but
    the newest KEEP_FILES versions; their rows stay) are removed only after the transaction commits
    (transaction.on_commit), so a rollback never loses a kept version's file. A caller that wraps store() in its own
    transaction must call discard_file(version) when that transaction rolls back (Django has no on-rollback hook), as
    egs_sheet_seed does."""
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
        transaction.on_commit(_prune)
    return version


def discard_file(version):
    """Removes the file of a version whose row was rolled back (see store)."""
    if not TaxEgsSheetVersion.objects.filter(pk=version.pk, file_name=version.file_name).exists():
        (_dir() / version.file_name).unlink(missing_ok=True)


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


# ── Build (S3 Task 2) ──────────────────────────────────────────────────────────────────────────

COLS = 16
COL_B, COL_I, COL_K = 1, 8, 10
FORMULA_COLS = (11, 13, 14, 15)          # L, N, O, P: the sheet's own formulas, row number translated
CODE_TYPES = ('EGS', 'GS1')
VAT_RATES = (Decimal('0'), Decimal('0.14'))

NO_TREATMENT = 'المعاملة الضريبية غير مؤكدة (خاضع 14% أو معفى) — أكدها من شاشة الأصناف'
NO_BRICK = 'لا توجد فئة GPC للصنف'
NO_TAX_ID = 'رقم التسجيل الضريبي للممول غير مسجل — لا يُكتب كود EGS'
NO_BARCODE = 'كود GS1 بلا باركود'
CODE_MISMATCH = 'كود الصنف المعتمد لا يطابق EG-<رقم التسجيل>-<كود الصنف>'
NO_PROFILE = 'لا يوجد ملف ضريبي للصنف'


def _code_key(code):
    return (0, int(code), code) if code.isdigit() else (1, 0, code)


def _decision(profile):
    try:
        return profile.coding_decision
    except TaxCodingDecision.DoesNotExist:
        return None


def _production_usages():
    """{itemcode: its approved/active production usage}; several → the newest (EGS first on a tie)."""
    from apps.tax_invoicing.eta_codes import ACTIVE_STATUSES    # eta_codes -> eta_recon -> egs_sheet: no cycle
    best = {}
    for u in EtaCodeUsage.objects.filter(system='production').exclude(itemcode=''):
        if u.status.lower() not in ACTIVE_STATUSES:
            continue
        old = best.get(u.itemcode)
        if old is None or ((u.active_from or dt.date.min, u.code_type == 'EGS')
                           > (old.active_from or dt.date.min, old.code_type == 'EGS')):
            best[u.itemcode] = u
    return best


def _vat(profile):
    """0.14 / 0 from a confirmed treatment (taxable 14% or exempt), else None."""
    if not profile.treatment_confirmed_at:
        return None
    if profile.tax_treatment == TaxItemProfile.TREATMENT_TAXABLE and Decimal(profile.vat_rate) == 14:
        return Decimal('0.14')
    if profile.tax_treatment == TaxItemProfile.TREATMENT_EXEMPT:
        return Decimal('0')
    return None


def _candidate(code, profile, usage, tax_id, year):
    out = {'itemcode': code, 'why': ''}
    if profile is None:
        return {**out, 'why': NO_PROFILE}
    decision = _decision(profile)
    vat = _vat(profile)
    if vat is None:
        return {**out, 'why': NO_TREATMENT}
    if usage is not None:
        code_type, item_code = usage.code_type.upper(), usage.item_code.strip()
    else:
        item_code = profile.eta_code.strip()
        code_type = (profile.code_type or ('EGS' if item_code.upper().startswith('EG-') else 'GS1')).upper()
    if code_type == 'EGS':
        if not tax_id:
            return {**out, 'why': NO_TAX_ID}
        expected = f'EG-{tax_id}-{code}'
        if item_code and item_code != expected:
            return {**out, 'why': CODE_MISMATCH}
        item_code = expected
    elif code_type != 'GS1' or not item_code:
        return {**out, 'why': NO_BARCODE}
    brick = ((decision.brick if decision else '') or (usage.gpc if usage else '') or profile.gpc_code or '').strip()
    if not brick.strip('0'):
        return {**out, 'why': NO_BRICK}
    eta_name = usage.code_name.strip() if usage else ''
    name = (decision.code_name if decision else '') or eta_name or profile.item_name or profile.item_name_ar
    name_ar = (decision.code_name_ar if decision else '') or eta_name or profile.item_name_ar or name
    active = (usage.active_from if usage else None) or profile.active_from or dt.date(year, 1, 1)
    return {**out, 'code_type': code_type, 'item_code': item_code, 'code_name': name, 'code_name_ar': name_ar,
            'description': (decision.description if decision else '') or name,
            'description_ar': (decision.description_ar if decision else '') or name_ar,
            'active_from': active, 'gpc': brick, 'vat': vat}


def candidates(coded=None):
    """Newly coded items not yet coded in the sheet, sorted by itemcode: [{itemcode, why, ...row values}]. `why` is
    why an item is not written (unconfirmed VAT, no brick, ...); empty = ready. A newly coded item = no keep-out
    decision AND a code ETA production holds (profile approved with coding_env 'production', or an approved/active
    production EtaCodeUsage matched to it). `coded` = the sheet's coded itemcodes (default: the latest version's)."""
    if coded is None:
        version = latest()
        coded = version.coded_itemcodes if version else ()
    coded = {_text(c) for c in coded}
    issuer = TaxIssuerProfile.objects.first()
    tax_id = re.sub(r'\D', '', issuer.tax_id) if issuer else ''
    usages = _production_usages()
    profiles = {p.softech_itemcode: p for p in TaxItemProfile.objects.filter(
        Q(coding_status=TaxItemProfile.CODE_APPROVED, coding_env='production')
        | Q(softech_itemcode__in=list(usages))).select_related('coding_decision')}
    year = dt.date.today().year
    out = []
    for code in sorted(set(profiles) | set(usages), key=_code_key):
        if code in coded:
            continue
        profile = profiles.get(code)
        decision = _decision(profile) if profile is not None else None
        if decision is not None and decision.decision == TaxCodingDecision.DECISION_KEEP_OUT:
            continue
        out.append(_candidate(code, profile, usages.get(code), tax_id, year))
    return out


def _number(text):
    """Digit-only text as a number when that keeps it exact (the sheet stores numbers; '0200' stays text)."""
    return int(text) if text.isdigit() and str(int(text)) == text else text


def _padded(r):
    return tuple(r) + (None,) * (COLS - len(r))


def _scan(ws):
    """({itemcode: [(row number, coded)]}, last row with a value in A..K, the first row carrying the L/N/O/P
    formulas)."""
    rows, last, template = {}, 1, None
    for n, r in enumerate(ws.iter_rows(min_row=2, max_col=COLS, values_only=True), start=2):
        r = _padded(r)
        if any(v not in (None, '') for v in r[:COL_K + 1]):
            last = n
        code = _text(r[COL_J])
        if code:
            rows.setdefault(code, []).append((n, bool(_text(r[COL_A]) and _text(r[COL_G]))))
        if template is None and all(isinstance(r[c], str) and r[c].startswith('=') for c in FORMULA_COLS):
            template = n
    return rows, last, template


def _write_row(ws, n, c, template):
    values = {COL_A: c['code_type'], COL_B: c['item_code'], 2: c['code_name'], 3: c['code_name_ar'],
              4: c['description'], 5: c['description_ar'], COL_G: dt.datetime.combine(c['active_from'], dt.time()),
              COL_I: _number(c['gpc']), COL_J: _number(c['itemcode']), COL_K: float(c['vat'])}
    for col, value in values.items():
        ws.cell(n, col + 1).value = value
    for col in FORMULA_COLS:
        origin = ws.cell(template, col + 1)
        ws.cell(n, col + 1).value = Translator(origin.value, origin=origin.coordinate).translate_formula(
            f'{get_column_letter(col + 1)}{n}')


def _copy_style(ws, src, dst):
    for col in range(1, COLS + 1):
        cell = ws.cell(src, col)
        if cell.has_style:
            ws.cell(dst, col)._style = copy(cell._style)
    if ws.row_dimensions[src].height is not None:
        ws.row_dimensions[dst].height = ws.row_dimensions[src].height


def _extend(ref, last):
    """`ref` (A1:P5) grown down to row `last`; never shrunk."""
    min_col, min_row, max_col, max_row = range_boundaries(ref)
    return f'{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max(max_row, last)}'


def _is_rate(k):
    if isinstance(k, bool) or not isinstance(k, (int, float)):
        return False
    return any(abs(Decimal(str(k)) - v) < Decimal('0.000001') for v in VAT_RATES)


def _sheet_counts(ws):
    """read_counts' rule on an open (formula) workbook, plus duplicates and the coded rows' problems."""
    total = coded = 0
    codes, by_code, by_b, bad = set(), {}, {}, []
    for r in ws.iter_rows(min_row=2, max_col=COLS, values_only=True):
        r = _padded(r)
        code = _text(r[COL_J])
        if not code:
            continue
        total += 1
        by_code[code] = by_code.get(code, 0) + 1
        if not (_text(r[COL_A]) and _text(r[COL_G])):
            continue
        coded += 1
        codes.add(code)
        b = _text(r[COL_B])
        if b:
            by_b[b] = by_b.get(b, 0) + 1
        problems = [label for label, ok in (
            ('نوع الكود A', _text(r[COL_A]) in CODE_TYPES), ('الكود B', bool(b)),
            ('فئة GPC في I', _text(r[COL_I]) not in ('', '0')), ('نسبة الضريبة K', _is_rate(r[COL_K]))) if not ok]
        if problems:
            bad.append((code, problems))
    return {'total_rows': total, 'coded_rows': coded, 'coded_itemcodes': sorted(codes),
            'dup_codes': sorted((c for c, n in by_code.items() if n > 1), key=_code_key),
            'dup_b': sorted(b for b, n in by_b.items() if n > 1), 'bad': bad}


def _sample(items, n=5):
    items = list(items)
    more = f' و{len(items) - n} غيرها' if len(items) > n else ''
    return '، '.join(str(i) for i in items[:n]) + more


def checks(wb, held_counts):
    """Arabic reasons this workbook must not become a version; [] = accepted. `held_counts` = read_counts of the
    held version plus its `sheetnames`. The saved file's re-read is checked by build."""
    problems = []
    if list(wb.sheetnames) != list(held_counts['sheetnames']):
        problems.append('أسماء أوراق الملف تغيرت عن النسخة السابقة')
    if SHEET not in wb.sheetnames:
        return problems + [f'لا توجد ورقة باسم «{SHEET}» في الملف']
    ws = wb[SHEET]
    if [_header_text(ws.cell(1, c).value) for c in range(1, COLS + 1)] != HEADER:
        problems.append(f'عناوين ورقة «{SHEET}» ليست عناوين ملف الأكواد')
    counts = _sheet_counts(ws)
    if counts['dup_codes']:
        problems.append(f'كود صنف مكرر في العمود J: {_sample(counts["dup_codes"])}')
    if counts['dup_b']:
        problems.append(f'كود مكرر في العمود B لصفوف مكوّدة: {_sample(counts["dup_b"])}')
    if counts['bad']:
        problems.append('صفوف مكوّدة ناقصة أو خاطئة: '
                        + _sample(f'{code} ({"، ".join(p)})' for code, p in counts['bad']))
    new = set(counts['coded_itemcodes']) - {_text(c) for c in held_counts['coded_itemcodes']}
    keep_out = TaxCodingDecision.objects.filter(decision=TaxCodingDecision.DECISION_KEEP_OUT,
                                                profile__softech_itemcode__in=list(new))
    keep_out = sorted(keep_out.values_list('profile__softech_itemcode', flat=True), key=_code_key)
    if keep_out:
        problems.append(f'أصناف قرارها «يبقى خارج الترميز» مكوّدة في الملف: {_sample(keep_out)}')
    if counts['coded_rows'] < held_counts['coded_rows']:
        problems.append(f'عدد الصفوف المكوّدة ({counts["coded_rows"]}) أقل من النسخة السابقة '
                        f'({held_counts["coded_rows"]})')
    return problems


def build(actor, note=''):
    """The next version from the latest one: each ready candidate codes its uncoded row, or gets a new row after the
    last item row (style of the row above, inside the DataEntry table and autofilter). Coded rows are never touched.
    Returns the new version; the latest one unchanged when nothing is to be written; {'refused': [...]} when a check
    fails (nothing stored). One load, one save."""
    held = latest()
    if held is None:
        return {'refused': ['لا توجد نسخة محفوظة من ملف الأكواد — خزّن ملف المالك أولاً (egs_sheet_seed)']}
    try:
        data = open_version(held)
        held_counts = read_counts(data)
    except SheetError as exc:
        return {'refused': [str(exc)]}
    ready, skipped = [], []
    for c in candidates(held_counts['coded_itemcodes']):
        if c['why']:
            skipped.append({'itemcode': c['itemcode'], 'why': c['why']})
        else:
            ready.append(c)
    if not ready:
        return held
    wb = openpyxl.load_workbook(io.BytesIO(data))     # not read_only / data_only: the formulas must survive
    held_counts['sheetnames'] = list(wb.sheetnames)
    ws = wb[SHEET]
    rows, last, template = _scan(ws)
    if template is None:
        return {'refused': [f'لا يوجد في ورقة «{SHEET}» صف بمعادلات الأعمدة L وN وO وP لنسخها'], 'skipped': skipped}
    coded, added = [], []
    for c in ready:
        at = rows.get(c['itemcode'])
        if at and any(is_coded for _, is_coded in at):     # a coded row is never rewritten
            continue
        if at:
            _write_row(ws, at[0][0], c, template)
            coded.append(c['itemcode'])
        else:
            last += 1
            _copy_style(ws, last - 1, last)
            _write_row(ws, last, c, template)
            added.append(c['itemcode'])
    if not (coded or added):
        return held
    if added:
        for table in ws.tables.values():
            table.ref = _extend(table.ref, last)
            if table.autoFilter is not None and table.autoFilter.ref:
                table.autoFilter.ref = _extend(table.autoFilter.ref, last)
        if ws.auto_filter.ref:
            ws.auto_filter.ref = _extend(ws.auto_filter.ref, last)
    problems = checks(wb, held_counts)
    if problems:
        return {'refused': problems, 'skipped': skipped}
    expected = _sheet_counts(ws)
    buf = io.BytesIO()
    wb.save(buf)
    new = buf.getvalue()
    counts = read_counts(new)
    if any(counts[k] != expected[k] for k in ('total_rows', 'coded_rows', 'coded_itemcodes')):
        return {'refused': ['الملف المحفوظ لا يُقرأ بنفس الأعداد — لم تُحفظ نسخة'], 'skipped': skipped}
    version = None
    try:
        with transaction.atomic():      # no version without its audit event
            current = TaxEgsSheetVersion.objects.select_for_update().order_by('-number').first()
            if current is None or current.pk != held.pk:
                return {'refused': ['بُنيت نسخة أحدث أثناء البناء — أعد المحاولة'], 'skipped': skipped}
            version = store(new, source=TaxEgsSheetVersion.SOURCE_BUILD, built_by=actor, note=note, added=added,
                            coded=coded, skipped=skipped, **counts)
            audit('egs_sheet_built', actor=actor, entity='egs_sheet', entity_id=version.number, reason=note,
                  after={'number': version.number, 'from': held.number, 'sha256': version.sha256,
                         'coded_rows': version.coded_rows, 'total_rows': version.total_rows,
                         'added': added, 'coded': coded, 'skipped': len(skipped)})
    except Exception:
        if version is not None:     # rolled back: its file must not stay behind
            discard_file(version)
        raise
    return version
