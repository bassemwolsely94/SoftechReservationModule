"""
apps/catalog/gs1.py

GS1 DataMatrix / GS1-128 element-string parser for serialised medicine packs (P-58,
EDA track-and-trace foundation). Pure and deterministic — no database, no network.

    parse_gs1(raw) -> {'gtin', 'serial', 'batch', 'expiry', 'raw'}

Accepts what scanners send:
  • symbology prefix ]d2 (DataMatrix), ]C1 (GS1-128), ]Q3 (QR) — stripped
  • FNC1 as the GS character (0x1D) between variable-length fields
  • the bracketed human-readable form "(01)…(17)…(10)…(21)…" (manual entry)

Application Identifiers (GS1 General Specifications):
  01 GTIN, 14 digits, check digit validated     17 expiry YYMMDD (day 00 = month end)
  10 batch/lot, up to 20                         21 serial, up to 20
  11 production date / 15 best-before (6, read and ignored)
Any other AI is rejected rather than guessed. Confirm the AI set against EDA guideline
804/2025 before activation.
"""
import calendar
import datetime
import re

GS = '\x1d'

FIXED = {'01': 14, '17': 6, '11': 6, '15': 6}
VARIABLE = {'10': 20, '21': 20}
_PREFIXES = (']d2', ']C1', ']Q3', ']e0')


class GS1Error(ValueError):
    """The scan is not a valid GS1 element string for a medicine pack."""


def gtin_check_ok(gtin):
    if not (len(gtin) == 14 and gtin.isdigit()):
        return False
    body, check = gtin[:13], int(gtin[13])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def _expiry(yymmdd):
    if not (len(yymmdd) == 6 and yymmdd.isdigit()):
        raise GS1Error(f'bad date {yymmdd!r}')
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    # GS1 century rule simplified for packs on hand: 00-49 → 20xx, 50-99 → 19xx
    year = 2000 + yy if yy < 50 else 1900 + yy
    if not 1 <= mm <= 12:
        raise GS1Error(f'bad month in {yymmdd!r}')
    if dd == 0:
        dd = calendar.monthrange(year, mm)[1]
    try:
        return datetime.date(year, mm, dd)
    except ValueError as exc:
        raise GS1Error(f'bad date {yymmdd!r}') from exc


def _bracketed(s):
    parts = re.findall(r'\((\d{2,4})\)([^(]*)', s)
    if not parts or ''.join(f'({a}){v}' for a, v in parts) != s:
        raise GS1Error('malformed bracketed element string')
    return [(ai, v) for ai, v in parts]


def _element_string(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == GS:
            i += 1
            continue
        ai = s[i:i + 2]
        i += 2
        if ai in FIXED:
            n = FIXED[ai]
            val = s[i:i + n]
            if len(val) != n:
                raise GS1Error(f'AI {ai} needs {n} characters')
            i += n
        elif ai in VARIABLE:
            end = s.find(GS, i)
            end = len(s) if end == -1 else end
            val = s[i:end]
            i = end
        else:
            raise GS1Error(f'unsupported or invalid AI {ai!r}')
        out.append((ai, val))
    return out


def parse_gs1(raw):
    s = str(raw or '').strip()
    for p in _PREFIXES:
        if s.startswith(p):
            s = s[len(p):]
            break
    if s.startswith(GS):
        s = s[1:]
    if not s:
        raise GS1Error('empty scan')
    pairs = _bracketed(s) if s.startswith('(') else _element_string(s)

    out = {'gtin': None, 'serial': '', 'batch': '', 'expiry': None, 'raw': str(raw)}
    for ai, val in pairs:
        if ai in VARIABLE and not 1 <= len(val) <= VARIABLE[ai]:
            raise GS1Error(f'AI {ai} must be 1–{VARIABLE[ai]} characters')
        if ai == '01':
            if not gtin_check_ok(val):
                raise GS1Error(f'GTIN {val} fails its check digit')
            out['gtin'] = val
        elif ai == '17':
            out['expiry'] = _expiry(val)
        elif ai == '10':
            out['batch'] = val
        elif ai == '21':
            out['serial'] = val
        elif ai in ('11', '15'):
            _expiry(val)          # validate, not stored
        else:
            raise GS1Error(f'unsupported AI {ai!r}')
    if not out['gtin']:
        raise GS1Error('no GTIN (AI 01) in the scan')
    return out


def gtin_barcode_candidates(gtin):
    """Barcodes an ItemBarcode / Item.barcode may hold for this GTIN-14:
    the GTIN itself, its EAN-13 (leading 0 dropped) and its UPC-A (two zeros)."""
    out = [gtin]
    if gtin.startswith('0'):
        out.append(gtin[1:])
    if gtin.startswith('00'):
        out.append(gtin[2:])
    return out
