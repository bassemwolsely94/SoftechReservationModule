"""The owner's bulk EGS sheet (ElRezeiky_Bulk_EGS_Items.xlsx) — the workbook the Invoicer reads to know which items
are coded. Doc 36, batch S3.

This module keeps its versions: `store` writes one version's file under TAX_EGS_SHEET_DIR and its row
(TaxEgsSheetVersion), keeping the newest 10 files; `latest` / `open_version` read them back; `read_counts` reads a
workbook's DataEntry sheet (coded row = CodeType (A) and ActiveFrom (G) filled; itemcode = EGSRelatedCode (J)).
`build` makes the next version from the latest: it codes the uncoded row of each newly coded item or appends a row
for an item not in the sheet, never rewriting a coded row; `checks` must pass before a version is accepted.
A build edits the DataEntry cells inside the file (egs_xlsx), so every other part of the owner's workbook keeps its
bytes. The owner's original file is only ever read."""
import datetime as dt
import hashlib
import html
import io
import json
import logging
import re
import zipfile
from decimal import Decimal
from pathlib import Path

import openpyxl
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

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
          coded_itemcodes=(), whole_workbook=None):
    """Writes `data` as the next version: file first, then the row; a failed row removes the file. Old files (all but
    the newest KEEP_FILES versions; their rows stay) are removed only after the transaction commits
    (transaction.on_commit), so a rollback never loses a kept version's file. A caller that wraps store() in its own
    transaction must call discard_file(version) when that transaction rolls back (Django has no on-rollback hook), as
    egs_sheet_seed does. `whole_workbook` (default: a seed or a fetched copy is; a build says so itself)."""
    if whole_workbook is None:
        whole_workbook = source != TaxEgsSheetVersion.SOURCE_BUILD
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
                coded_itemcodes=list(coded_itemcodes), source=source, built_by=built_by, note=note[:300],
                whole_workbook=whole_workbook)
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
FORMULA_COLS = (11, 13, 14, 15)          # L, N, O, P: the owner's formulas, written as their values (_fill_values)
CODE_TYPES = ('EGS', 'GS1')
VAT_RATES = (Decimal('0'), Decimal('0.14'))

NO_TREATMENT = 'المعاملة الضريبية غير مؤكدة (خاضع 14% أو معفى) — أكدها من شاشة الأصناف'
OTHER_RATE = 'نسبة الضريبة المعتمدة ليست 14٪ ولا معفاة — راجع المعاملة الضريبية للصنف'
NO_BRICK = 'لا توجد فئة GPC للصنف'
NO_TAX_ID = 'رقم التسجيل الضريبي للممول غير مسجل — لا يُكتب كود EGS'
NO_BARCODE = 'كود GS1 بلا باركود'
CODE_MISMATCH = 'كود الصنف المعتمد لا يطابق EG-<رقم التسجيل>-<كود الصنف>'
NO_PROFILE = 'لا يوجد ملف ضريبي للصنف'
NO_HELD = 'لا توجد نسخة محفوظة من ملف الأكواد — خزّن ملف المالك أولاً (egs_sheet_seed)'


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
    if vat is None:     # confirmed at another rate (e.g. taxable 5 %, zero-rated) is not "unconfirmed"
        return {**out, 'why': OTHER_RATE if profile.treatment_confirmed_at else NO_TREATMENT}
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
    production EtaCodeUsage matched to it). `coded` = the sheet's coded itemcodes (default: those of the latest whole
    version, the next build's base)."""
    if coded is None:
        version = latest_whole()       # the base of the next build
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


def _set(cell, value):
    """Writes `value`; a text starting with '=' (an item name from SOFTECH / ETA) stays that exact text, never a
    formula (openpyxl would save it as one)."""
    cell.value = value
    if isinstance(value, str) and value.startswith('='):
        cell.data_type = 's'


def _blank(v):
    return v is None or v == ''


def _formula_values(r):
    """(L, N, O, P) exactly as the owner's formulas compute them from A, G, I, K (Excel rules: a blank cell is 0 and
    ""; text compares case-insensitively and never equals a number):
    L =IF(AND(K=0%,A="EGS",I<>0,G<>""),1,0)   N =IF(AND(A="",G=""),"1","0")   O =K*100   P =IF(O=0,"v003","v009").
    A text K Excel cannot multiply gives (L, N, None, None)."""
    a, g, i, k = r[COL_A], r[COL_G], r[COL_I], r[COL_K]
    numeric_k = 0 if _blank(k) else (int(k) if isinstance(k, bool) else k)
    if not isinstance(numeric_k, (int, float)):
        try:
            numeric_k = float(str(numeric_k).strip())    # K*100 coerces numeric text; K=0% never matches text
            k_zero = False
        except ValueError:
            numeric_k, k_zero = None, False
    else:
        k_zero = numeric_k == 0
    a_egs = isinstance(a, str) and a.upper() == 'EGS'
    i_nonzero = not _blank(i) and not (isinstance(i, (int, float)) and not isinstance(i, bool) and i == 0)
    l_value = 1 if (k_zero and a_egs and i_nonzero and not _blank(g)) else 0
    n_value = '1' if (_blank(a) and _blank(g)) else '0'
    if numeric_k is None:
        return l_value, n_value, None, None
    o_value = round(numeric_k * 100, 9)
    if float(o_value).is_integer():
        o_value = int(o_value)
    return l_value, n_value, o_value, 'v003' if o_value == 0 else 'v009'


def _has_row(r):
    return any(not _blank(v) for v in r[:COL_K + 1]) or any(not _blank(r[c]) for c in FORMULA_COLS)


def _same(want, got):
    """A cell value equal to a formula's value: numbers within 1e-9, else the same text (a typed 0 = "0"); a formula
    or an empty cell never equals a value."""
    if want is None or got is None:
        return want is got
    if isinstance(got, str) and got.startswith('='):
        return False
    if isinstance(want, (int, float)) and isinstance(got, (int, float)) and not isinstance(got, bool):
        return abs(want - got) < 1e-9
    return _text(want) == _text(got)


def _formula_mismatches(ws, rows=None):
    """Itemcodes (or row numbers) of `rows` (default: every row) whose L/N/O/P are not the values of their
    formulas. A build checks only the rows it wrote: every other row is the owner's, untouched."""
    bad = []
    for n, r in enumerate(ws.iter_rows(min_row=2, max_col=COLS, values_only=True), start=2):
        if rows is not None and n not in rows:
            continue
        r = _padded(r)
        if not _has_row(r):
            continue
        if not all(_same(w, r[c]) for w, c in zip(_formula_values(r), FORMULA_COLS)):
            bad.append(_text(r[COL_J]) or f'صف {n}')
    return bad


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
    """Arabic reasons this workbook must not become a version; [] = accepted. `wb` is read with its values
    (data_only). `held_counts` = read_counts of the held version plus its `sheetnames` (and `written`: the rows the
    build wrote — only their L/N/O/P are checked). The saved file's re-read is checked by build."""
    problems = []
    if list(wb.sheetnames) != list(held_counts['sheetnames']):
        problems.append('أسماء أوراق الملف تغيرت عن النسخة السابقة')
    if SHEET not in wb.sheetnames:
        return problems + [f'لا توجد ورقة باسم «{SHEET}» في الملف']
    ws = wb[SHEET]
    header = next(ws.iter_rows(max_row=1, max_col=COLS, values_only=True), ())
    if [_header_text(v) for v in _padded(header)] != HEADER:
        problems.append(f'عناوين ورقة «{SHEET}» ليست عناوين ملف الأكواد')
    counts = _sheet_counts(ws)
    if counts['dup_codes']:
        problems.append(f'كود صنف مكرر في العمود J: {_sample(counts["dup_codes"])}')
    if counts['dup_b']:
        problems.append(f'كود مكرر في العمود B لصفوف مكوّدة: {_sample(counts["dup_b"])}')
    if counts['bad']:
        problems.append('صفوف مكوّدة ناقصة أو خاطئة: '
                        + _sample(f'{code} ({"، ".join(p)})' for code, p in counts['bad']))
    mismatched = _formula_mismatches(ws, held_counts.get('written'))
    if mismatched:
        problems.append(f'قيم الأعمدة L وN وO وP لا تطابق معادلاتها: {_sample(mismatched)}')
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


NOT_WHOLE = ('هذه النسخة بُنيت قبل 18 نوفمبر 2026 بطريقة أسقطت أجزاءً من ملف المالك (الاستعلامات والمعادلات) — '
             'لا تُنزَّل كاملة ولا تُكتب على جهاز الختم؛ ابنِ نسخة جديدة')
NO_DATE_STYLE = 'لا يوجد صف مكوّد في الملف يُؤخذ منه تنسيق التاريخ — لا يمكن كتابة ActiveFrom'
OTHER_PARTS = 'تغيّر جزء آخر من ملف المالك غير ورقة الأكواد — لم تُحفظ نسخة'
NOT_OPENED = 'الملف بعد التعديل لا يُفتح — لم تُحفظ نسخة'
ALWAYS = (COL_A, COL_G, COL_K)          # what makes the row coded, and the VAT rate a person confirmed
FORMULA_KINDS = {12: 'n', 14: 'str', 15: 'n', 16: 'str'}     # L, N, O, P (1-based): number or text results


def latest_whole():
    """The newest version that holds the owner's whole workbook: the base of the next build."""
    return TaxEgsSheetVersion.objects.filter(whole_workbook=True).order_by('-number').first()


def _scan_values(data):
    """({itemcode: [(row, coded)]}, {row: A..P values} of item rows, last row with a value in A..K, last coded
    row), from the workbook's cached values."""
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    rows, values, last, last_coded = {}, {}, 1, None
    try:
        for n, r in enumerate(wb[SHEET].iter_rows(min_row=2, max_col=COLS, values_only=True), start=2):
            r = _padded(r)
            if any(v not in (None, '') for v in r[:COL_K + 1]):
                last = n
            code = _text(r[COL_J])
            if code:
                coded = bool(_text(r[COL_A]) and _text(r[COL_G]))
                rows.setdefault(code, []).append((n, coded))
                values[n] = r
                if coded:
                    last_coded = n
    finally:
        wb.close()
    return rows, values, last, last_coded


def _new_values(c):
    """A..K of a candidate (0-based columns)."""
    return {COL_A: c['code_type'], COL_B: c['item_code'], 2: c['code_name'], 3: c['code_name_ar'],
            4: c['description'], 5: c['description_ar'], COL_G: dt.datetime.combine(c['active_from'], dt.time()),
            COL_I: _number(c['gpc']), COL_J: _number(c['itemcode']), COL_K: float(c['vat'])}


def _empty(col, v):
    """A cell the build may fill: empty, or a GPC brick of 0."""
    return _blank(v) or (col == COL_I and _text(v) in ('0', '0.0'))


def _one_based(cells):
    return {col + 1: v for col, v in cells.items()}


def _sheetnames(data):
    """The sheet names of a workbook, in order, from its workbook part."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read('xl/workbook.xml').decode('utf-8')
    return [html.unescape(m) for m in re.findall(r'<sheet\b[^>]*?\bname="([^"]*)"', text)]


def build(actor, note=''):
    """The next version from the latest whole version (whole_workbook): each ready candidate codes its uncoded row,
    or gets a new row after the last item row (a copy of that row: styles, formulas). Only DataEntry cells change,
    inside the file (egs_xlsx.patch); every other part of the owner's workbook keeps its bytes. On a row it codes,
    the build sets A (code type), G (ActiveFrom) and K (the confirmed VAT rate), fills B..F and I only where they are
    empty (a typed name or brick is never replaced), and gives L/N/O/P the results of their formulas (the formulas
    stay). Coded rows are never touched.
    Returns the new version; the base unchanged when nothing is to be written; {'refused': [...]} when a check
    fails (nothing stored)."""
    from apps.tax_invoicing import egs_xlsx
    started_on = latest()
    held = latest_whole()
    if held is None:
        return {'refused': [NO_HELD]}
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
    rows, values, last, last_coded = _scan_values(data)
    template = last
    edits, appends, coded, added, written = {}, [], [], [], []
    for c in ready:
        at = rows.get(c['itemcode'])
        if at and any(is_coded for _, is_coded in at):     # a coded row is never rewritten
            continue
        new = _new_values(c)
        if at:
            n = at[0][0]
            row = list(values[n])
            change = {}
            for col, v in new.items():
                if col in ALWAYS or _empty(col, row[col]):
                    row[col] = v
                    change[col] = v
            change.update(zip(FORMULA_COLS, _formula_values(row)))
            edits[n] = _one_based(change)
            written.append(n)
            coded.append(c['itemcode'])
        else:
            last += 1
            row = [None] * COLS
            for col, v in new.items():
                row[col] = v
            cells = dict(new)
            cells.update(zip(FORMULA_COLS, _formula_values(row)))
            appends.append((last, _one_based(cells)))
            written.append(last)
            added.append(c['itemcode'])
    if not (coded or added):
        return held
    if last_coded is None:
        return {'refused': [NO_DATE_STYLE], 'skipped': skipped}
    try:
        new_data, _ = egs_xlsx.patch(data, SHEET, edits=edits, appends=appends, template_row=template,
                                     formula_kinds=FORMULA_KINDS, date_style_row=last_coded,
                                     date_cols={COL_G + 1})
        allowed = egs_xlsx.editable_parts(data, SHEET)
    except egs_xlsx.PatchError as exc:
        return {'refused': [str(exc)], 'skipped': skipped}
    if egs_xlsx.changed_parts(data, new_data) - allowed:
        return {'refused': [OTHER_PARTS], 'skipped': skipped}
    held_counts['written'] = set(written)
    held_counts['sheetnames'] = _sheetnames(data)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(new_data), read_only=True, data_only=True)
    except Exception:       # openpyxl raises several types for a broken workbook
        return {'refused': [NOT_OPENED], 'skipped': skipped}
    try:
        problems = checks(wb, held_counts)
        expected = None if problems else _sheet_counts(wb[SHEET])
    finally:
        wb.close()
    if problems:
        return {'refused': problems, 'skipped': skipped}
    counts = read_counts(new_data)
    if any(counts[k] != expected[k] for k in ('total_rows', 'coded_rows', 'coded_itemcodes')):
        return {'refused': ['الملف المحفوظ لا يُقرأ بنفس الأعداد — لم تُحفظ نسخة'], 'skipped': skipped}
    version = None
    try:
        with transaction.atomic():      # no version without its audit event
            current = TaxEgsSheetVersion.objects.select_for_update().order_by('-number').first()
            if current is None or started_on is None or current.pk != started_on.pk:
                return {'refused': ['بُنيت نسخة أحدث أثناء البناء — أعد المحاولة'], 'skipped': skipped}
            version = store(new_data, source=TaxEgsSheetVersion.SOURCE_BUILD, built_by=actor, note=note,
                            added=added, coded=coded, skipped=skipped, whole_workbook=True, **counts)
            audit('egs_sheet_built', actor=actor, entity='egs_sheet', entity_id=version.number, reason=note,
                  after={'number': version.number, 'from': held.number, 'sha256': version.sha256,
                         'coded_rows': version.coded_rows, 'total_rows': version.total_rows,
                         'added': added, 'coded': coded, 'skipped': len(skipped)})
    except Exception:
        if version is not None:     # rolled back: its file must not stay behind
            discard_file(version)
        raise
    return version


# ── Downloads and the background build (S3 Task 3) ─────────────────────────────────────────────

DOWNLOAD_NAME = 'ElRezeiky_Bulk_EGS_Items.xlsx'      # the name the Invoicer reads in D:\invoicer_mini


def new_rows_xlsx(version):
    """A small workbook: the DataEntry header and only the rows this version added or coded, as values (a seed
    version has none: the header alone). SheetError when the version's file is gone."""
    wanted = {_text(c) for c in [*version.added, *version.coded]}
    src = openpyxl.load_workbook(io.BytesIO(open_version(version)), read_only=True, data_only=True)
    out = openpyxl.Workbook()
    ws = out.active
    ws.title = SHEET
    ws.append(HEADER)
    try:
        for r in src[SHEET].iter_rows(min_row=2, max_col=COLS, values_only=True):
            r = _padded(r)
            if _text(r[COL_J]) in wanted:
                n = ws.max_row + 1
                for col, value in enumerate(r, start=1):
                    _set(ws.cell(n, col), value)
    finally:
        src.close()
    for row in ws.iter_rows(min_row=2, min_col=COL_G + 1, max_col=COL_G + 1):
        row[0].number_format = 'yyyy-mm-dd'
    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()


# The build takes ~100 s on the real 15 MB sheet, so it runs on a thread; one at a time. Its state lives in one
# SystemSetting row (JSON): durable across restarts and shared by every server process, where the cache is per
# process (LocMemCache). A "running" state older than BUILD_STALE (a restart killed the thread) no longer blocks.
BUILD_KEY = 'tax_egs_sheet_build'
BUILD_STALE = dt.timedelta(minutes=30)
BUILD_BUSY = 'جارٍ بناء الملف — انتظر'
BUILD_RACE = 'بُنيت نسخة أخرى في نفس الوقت — أعد المحاولة'
BUILD_NOT_STARTED = 'تعذّر بدء البناء — أعد المحاولة'


def build_state():
    """{'state': idle|running|built|unchanged|refused|error, ...}: the last build's outcome, or the running one."""
    from apps.config.models import SystemSetting
    value = SystemSetting.get(BUILD_KEY)
    return value if isinstance(value, dict) and value.get('state') else {'state': 'idle'}


def _running(state):
    if state.get('state') != 'running':
        return False
    try:
        started = dt.datetime.fromisoformat(state.get('started_at') or '')
    except ValueError:
        return False
    return timezone.now() - started < BUILD_STALE


def _save_state(row, state):
    row.value = json.dumps(state, ensure_ascii=False, default=str)
    row.value_type = 'json'
    row.save(update_fields=['value', 'value_type', 'updated_at'])


def claim_build(actor):
    """Marks a build as running and returns True; False when one is already running (the row is locked, so two
    requests never both claim)."""
    from apps.config.models import SystemSetting
    with transaction.atomic():
        row, _ = SystemSetting.objects.select_for_update().get_or_create(key=BUILD_KEY, defaults={
            'label': 'ملف أكواد الإيصالات — آخر بناء', 'value': '{}', 'value_type': 'json',
            'description': 'حالة بناء ملف ElRezeiky_Bulk_EGS_Items.xlsx (يكتبها النظام)'})
        if _running(build_state()):
            return False
        _save_state(row, {'state': 'running', 'started_at': timezone.now().isoformat(),
                          'by': getattr(actor, 'username', '') or ''})
    return True


def fail_start():
    """The build thread could not start: the claimed "running" state becomes an error at once."""
    _finish({'state': 'error', 'error': BUILD_NOT_STARTED})


def _finish(state):
    from apps.config.models import SystemSetting
    with transaction.atomic():
        row, _ = SystemSetting.objects.select_for_update().get_or_create(key=BUILD_KEY, defaults={
            'label': 'ملف أكواد الإيصالات — آخر بناء', 'value': '{}', 'value_type': 'json'})
        started = build_state()
        _save_state(row, {**state, 'started_at': started.get('started_at'), 'by': started.get('by', ''),
                          'finished_at': timezone.now().isoformat()})


def run_build(actor, note=''):
    """build() with its outcome recorded in build_state(), never raised. A clash on the version number (another
    build stored first) and any other failure become the state's Arabic `error`."""
    from django.db import IntegrityError
    from core.errors import public_error
    held = None
    try:
        held = latest()
        out = build(actor, note)
    except IntegrityError:
        state = {'state': 'error', 'error': BUILD_RACE}
    except Exception as exc:    # recorded for the screen, logged with a reference by public_error
        state = {'state': 'error', 'error': public_error(None, exc)}
    else:
        if isinstance(out, dict):
            state = {'state': 'refused', 'refused': out.get('refused', []), 'skipped': out.get('skipped', [])}
        elif held is not None and out.pk == held.pk:
            state = {'state': 'unchanged', 'version': out.number}
        else:
            state = {'state': 'built', 'version': out.number}
    _finish(state)


def build_thread(actor, note=''):
    """The background thread's target: run_build, then the thread's own DB connection is closed."""
    from django.db import connection
    try:
        run_build(actor, note)
    except Exception:       # the state could not be saved: it stays "running" until BUILD_STALE passes
        logging.getLogger('elrezeiky.tax_invoicing').exception('egs sheet build: state not saved')
    finally:
        connection.close()
