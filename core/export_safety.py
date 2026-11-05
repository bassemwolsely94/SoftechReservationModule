"""
core/export_safety.py — keep typed text from running as a formula in exports (security Batch 6, W-4).

Text people type (a portal reorder's notes, a shortage line, an OCR'd invoice line) ends up in
Excel and CSV files that staff open. In an .xlsx a cell that starts with '=' is a live formula; in
a CSV Excel also runs cells that start with + - @ or a tab / CR. `=HYPERLINK(...)` sends the
sheet's data to an outside site and DDE can start programs on the staff PC.

  • `neutralise_formulas(wb)` — call right before `wb.save()`: every formula cell is written as
    plain text (the same characters, nothing added).
  • `neutralise_formulas(wb, keep_safe_formulas=True)` — for exports that build real formulas on
    purpose (the KPI board, the ISR fulfilment sheet; round 2, R5). A formula stays live only when
    it is plain arithmetic: cell / range references inside this workbook, numbers, quoted text and
    the functions in `SAFE_FUNCTIONS`. Anything else — HYPERLINK, WEBSERVICE, DDE (`cmd|...`),
    an outside-workbook reference (`[1]Sheet!A1`), a name, or text the tokenizer can't read — is
    written as plain text, so typed text can never become a live formula.
  • `csv_writer(f)` — drop-in for `csv.writer(f)`: a risky text cell gets a leading apostrophe;
    plain numbers such as "-5" or "+20%" stay as they are.
"""
from __future__ import annotations

import csv
import re

_CSV_TRIGGERS = ('=', '+', '-', '@', '\t', '\r')
_PLAIN_NUMBER = re.compile(r'^[+-]?\d[\d,]*(\.\d+)?%?$')


# Functions a code-built formula may use (round 2, R5). Only maths, logic, lookups inside the
# workbook and text joins — nothing that reaches a network, a file, another program or the clipboard.
SAFE_FUNCTIONS = frozenset({
    'ABS', 'AND', 'AVERAGE', 'AVERAGEIF', 'AVERAGEIFS', 'CEILING', 'CHOOSE', 'CONCAT',
    'CONCATENATE', 'COUNT', 'COUNTA', 'COUNTBLANK', 'COUNTIF', 'COUNTIFS', 'FLOOR', 'IF', 'IFERROR',
    'IFS', 'INDEX', 'INT', 'ISBLANK', 'ISNUMBER', 'LEN', 'MATCH', 'MAX', 'MAXIFS', 'MEDIAN', 'MIN',
    'MINIFS', 'MOD', 'NOT', 'OR', 'ROUND', 'ROUNDDOWN', 'ROUNDUP', 'SUM', 'SUMIF', 'SUMIFS',
    'SUMPRODUCT', 'TEXT', 'TRUE', 'FALSE', 'VLOOKUP', 'XLOOKUP',
})
_COL = r'\$?[A-Z]{1,3}'
_ROW = r'\$?\d{1,7}'
# a sheet name, quoted or bare; no '[' (another workbook), no '\\' or '/' (a path)
_SHEET = r"(?:'(?:[^'\[\]\\/?*:|]|'')+'|[A-Za-z_؀-ۿ][\w.؀-ۿ]*)!"
_SAFE_REF = re.compile(
    rf'^(?:{_SHEET})?(?:{_COL}{_ROW}(?::{_COL}{_ROW})?|{_COL}:{_COL}|{_ROW}:{_ROW})$')


def is_safe_formula(text) -> bool:
    """True when `text` (a string starting with '=') is a plain in-workbook calculation."""
    from openpyxl.formula import Tokenizer
    if not isinstance(text, str) or not text.startswith('=') or '|' in text:
        return False
    try:
        tokens = Tokenizer(text).items
    except Exception:                             # unreadable → treat as typed text
        return False
    if sum(t.subtype == 'OPEN' for t in tokens) != sum(t.subtype == 'CLOSE' for t in tokens):
        return False                              # unbalanced brackets: not a formula we built
    for tok in tokens:
        if tok.type == 'FUNC' and tok.subtype == 'OPEN':
            if tok.value[:-1].upper() not in SAFE_FUNCTIONS:
                return False
        elif tok.type == 'OPERAND' and tok.subtype == 'RANGE':
            if tok.value.upper() in ('TRUE', 'FALSE'):
                continue
            if not _SAFE_REF.match(tok.value):
                return False
        elif tok.type == 'OPERAND' and tok.subtype not in ('NUMBER', 'TEXT', 'LOGICAL', 'ERROR'):
            return False
    return True


def neutralise_formulas(wb, keep_safe_formulas=False):
    """Write every formula cell of `wb` as text. Returns `wb` so callers can chain `.save()`.

    With `keep_safe_formulas=True` a formula that `is_safe_formula` accepts stays live.
    A write-only workbook can't be walked after the fact: each of its sheets must have been
    wrapped with `safe_sheet()` when it was created, or this refuses."""
    if getattr(wb, 'write_only', False):
        if not all(getattr(ws, '_formula_safe', False) for ws in wb.worksheets):
            raise TypeError('write-only workbook: wrap each sheet with safe_sheet(wb.create_sheet(...))')
        return wb
    for ws in wb.worksheets:
        if not hasattr(ws, 'iter_rows'):          # chartsheet
            continue
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == 'f' and isinstance(cell.value, str):
                    if keep_safe_formulas and is_safe_formula(cell.value):
                        continue
                    cell.data_type = 's'
    return wb


class _SafeSheet:
    """A write-only sheet whose `append` writes '=' text as text."""

    def __init__(self, ws):
        object.__setattr__(self, '_ws', ws)

    def append(self, row):
        from openpyxl.cell import WriteOnlyCell
        cells = []
        for v in row:
            if isinstance(v, str) and v.startswith('='):
                v = WriteOnlyCell(self._ws, value=v)
            if getattr(v, 'data_type', None) == 'f' and isinstance(v.value, str):
                v.data_type = 's'
            cells.append(v)
        return self._ws.append(cells)

    def __getattr__(self, name):
        return getattr(self._ws, name)

    def __setattr__(self, name, value):
        setattr(self._ws, name, value)


def safe_sheet(ws):
    """Wrap a write-only sheet right after `wb.create_sheet()` (write-only books can't be
    cleaned at save time). Marks the sheet so `neutralise_formulas` accepts the workbook."""
    ws._formula_safe = True
    return _SafeSheet(ws)


def safe_csv_cell(value):
    """A text cell Excel would run as a formula gets a leading apostrophe; anything else as-is."""
    if isinstance(value, str) and value.startswith(_CSV_TRIGGERS) and not _PLAIN_NUMBER.match(value):
        return "'" + value
    return value


class _SafeWriter:
    def __init__(self, writer):
        self._writer = writer

    def writerow(self, row):
        return self._writer.writerow([safe_csv_cell(v) for v in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

    def __getattr__(self, name):
        return getattr(self._writer, name)


def csv_writer(f, *args, **kwargs):
    """`csv.writer(f, ...)` whose rows go through `safe_csv_cell`."""
    return _SafeWriter(csv.writer(f, *args, **kwargs))


class _SafeDictWriter(_SafeWriter):
    def writerow(self, rowdict):
        return self._writer.writerow({k: safe_csv_cell(v) for k, v in rowdict.items()})


def csv_dict_writer(f, fieldnames, *args, **kwargs):
    """`csv.DictWriter(f, fieldnames, ...)` whose values go through `safe_csv_cell`."""
    return _SafeDictWriter(csv.DictWriter(f, fieldnames, *args, **kwargs))
