"""Edits cells of one worksheet inside an .xlsx without re-saving the workbook. Doc 36, the bulk EGS sheet.

openpyxl re-saves a workbook from what it understands and drops the rest (Power Query connections, the data model,
custom XML, the calculation chain), and it cannot keep a formula together with its computed value. The Invoicer's
sheet must stay the owner's workbook, so the build changes only the cells it codes, here, as text inside the sheet's
XML part:

- a value cell gets its new value and keeps its style (`s`);
- a formula cell keeps its formula (`<f>`) and gets the value Excel would compute (`<v>`), so a reader that does not
  recalculate reads the right result and Excel still recalculates it later;
- an appended row is a copy of a template row (styles, row attributes) with the new values; its formulas are written
  out in full (a shared formula's group never covers a new row), translated to the new row;
- the sheet's <dimension>, its autofilter and its tables grow to cover appended rows when they covered the last row.

Every other part of the file is copied with the same bytes. Text is written as an inline string, so the shared
strings part is untouched too."""
import datetime as dt
import html
import io
import posixpath
import re
import zipfile

from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

_ROW_START = re.compile(r'<row\b[^>]*?\br="(\d+)"[^>]*?(/>|>)')
_CELL = re.compile(r'<c\b([^>]*?)(/>|>(.*?)</c>)', re.S)
_ATTR = re.compile(r'\s([\w:]+)="([^"]*)"')
_F = re.compile(r'<f\b([^>]*?)(?:/>|>(.*?)</f>)', re.S)
_XML_CHARS = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f]')


class PatchError(Exception):
    """The workbook cannot be edited this way; the message is Arabic, for the screen."""


def _attrs(text):
    return dict(_ATTR.findall(' ' + text))


def _attr_text(attrs):
    return ''.join(f' {k}="{v}"' for k, v in attrs.items())


def _resolve(base, target):
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


def _rels(parts, part):
    """{rId: (type, target part)} of `part`."""
    path = posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
    if path not in parts:
        return {}
    out = {}
    for m in re.finditer(r'<Relationship\b([^>]*)/?>', parts[path].decode('utf-8')):
        a = _attrs(m.group(1))
        if a.get('TargetMode') == 'External':
            continue
        out[a.get('Id')] = (a.get('Type', ''), _resolve(part, a.get('Target', '')))
    return out


def sheet_part(parts, sheet_name):
    """The zip path of worksheet `sheet_name`, and whether the workbook uses the 1904 date system."""
    wb = parts.get('xl/workbook.xml')
    if wb is None:
        raise PatchError('الملف ليس ملف Excel صالحاً')
    text = wb.decode('utf-8')
    rels = _rels(parts, 'xl/workbook.xml')
    for m in re.finditer(r'<sheet\b([^>]*)/?>', text):
        a = _attrs(m.group(1))
        if html.unescape(a.get('name', '')) == sheet_name:
            rid = next((v for k, v in a.items() if k.endswith(':id')), None)
            if rid in rels:
                pr = re.search(r'<workbookPr\b([^>]*)/?>', text)
                date1904 = bool(pr) and _attrs(pr.group(1)).get('date1904') in ('1', 'true')
                return rels[rid][1], date1904
    raise PatchError(f'لا توجد ورقة باسم «{sheet_name}» في الملف')


def _serial(value, date1904):
    epoch = dt.datetime(1904, 1, 1) if date1904 else dt.datetime(1899, 12, 30)
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        value = dt.datetime.combine(value, dt.time())
    days = (value - epoch).total_seconds() / 86400
    return int(days) if float(days).is_integer() else days


def _num(value):
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return repr(value)[:-2] if repr(value).endswith('.0') else repr(value)
    return repr(value) if isinstance(value, float) else str(value)


def escape(text):
    """XML text content: &, < and > escaped (quotes may stay in element text)."""
    return html.escape(text, quote=False)


def unescape(text):
    return html.unescape(text)


def _text(value):
    return escape(_XML_CHARS.sub('', str(value)))


def _value_cell(ref, attrs, value, date_style, date1904):
    """A value cell (no formula). None/'' leaves an empty cell with its style."""
    a = {k: v for k, v in attrs.items() if k not in ('r', 't', 'cm', 'vm')}
    head = f'<c r="{ref}"'
    if value is None or value == '':
        return head + _attr_text(a) + '/>'
    if isinstance(value, (dt.date, dt.datetime)):
        if date_style is not None:
            a['s'] = date_style
        return head + _attr_text(a) + f'><v>{_num(_serial(value, date1904))}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return head + _attr_text(a) + f'><v>{_num(value)}</v></c>'
    return head + _attr_text(a) + f' t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>'


def _formula_cell(ref, attrs, formula_xml, value, kind):
    """A formula cell: its <f> as given, its cached value `value` (kind 'str' or 'n')."""
    a = {k: v for k, v in attrs.items() if k not in ('r', 't', 'cm', 'vm')}
    if value is None:
        return f'<c r="{ref}"' + _attr_text(a) + f'>{formula_xml}</c>'
    if kind == 'str':
        return f'<c r="{ref}"' + _attr_text(a) + f' t="str">{formula_xml}<v>{_text(value)}</v></c>'
    return f'<c r="{ref}"' + _attr_text(a) + f'>{formula_xml}<v>{_num(value)}</v></c>'


def _cells(row_xml):
    """[(column index, attrs, inner xml or None, whole cell text)] of a <row> element."""
    out = []
    for m in _CELL.finditer(row_xml):
        a = _attrs(m.group(1))
        col = column_index_from_string(re.match(r'[A-Z]+', a['r']).group(0))
        out.append((col, a, m.group(3) if m.group(2) != '/>' else None, m.group(0)))
    return out


def _row_spans(xml):
    """{row number: (start, end)} of every <row> element in the sheet XML."""
    spans = {}
    for m in _ROW_START.finditer(xml):
        start = m.start()
        if m.group(2) == '/>':
            end = m.end()
        else:
            end = xml.index('</row>', m.end()) + len('</row>')
        spans[int(m.group(1))] = (start, end)
    return spans


class _SharedFormulas:
    """The master text of each shared formula group: si → (master cell ref, formula text)."""

    def __init__(self, xml):
        self.masters = {}
        for m in re.finditer(r'<c\b[^>]*?\br="([A-Z]+\d+)"[^>]*>\s*<f\b([^>]*?\bt="shared"[^>]*)>(.*?)</f>', xml, re.S):
            a = _attrs(m.group(2))
            if 'ref' in a and m.group(3):
                self.masters[a.get('si')] = (m.group(1), unescape(m.group(3)))

    def text(self, f_attrs, f_text, ref):
        """The formula of a cell at `ref`: (origin ref, text)."""
        if f_attrs.get('t') == 'shared' and not f_text:
            master = self.masters.get(f_attrs.get('si'))
            if master is None:
                raise PatchError('معادلة مشتركة في الملف بلا أصل — لا يمكن تعديل الملف')
            return master
        return ref, unescape(f_text or '')


def _translate(formula, origin, dest):
    return Translator('=' + formula, origin=origin).translate_formula(dest)[1:]


def _grow(ref, old_last, new_last):
    """`ref` grown down to `new_last` when it reached `old_last` (the last item row); else unchanged."""
    min_col, min_row, max_col, max_row = range_boundaries(ref)
    if max_row < old_last or new_last <= max_row:
        return ref
    return f'{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_last}'


def patch(data, sheet_name, *, edits, appends=(), template_row=None, formula_kinds=None, date_style_row=None,
          date_cols=()):
    """The workbook `data` with worksheet `sheet_name` edited; every other zip part keeps its bytes.

    edits: {row: {column index (1-based): value}}. On a formula cell the value is its cached result (the formula
    stays); on any other cell it is the new value (a missing cell is created in column order).
    appends: [(row, {column: value})] new rows, copied from `template_row` (an existing row): its styles and row
    attributes, its formulas translated to the new row with the given value as their result.
    formula_kinds: {column: 'n' | 'str'}: the result type of each formula column.
    date_style_row: a row whose cells in `date_cols` carry a date format; a date written into a cell whose style is
    not that row's takes that row's style. Returns (bytes, the zip parts changed)."""
    formula_kinds = formula_kinds or {}
    with zipfile.ZipFile(io.BytesIO(data)) as zin:
        infos = zin.infolist()
        parts = {i.filename: zin.read(i.filename) for i in infos}
    path, date1904 = sheet_part(parts, sheet_name)
    xml = parts[path].decode('utf-8')
    spans = _row_spans(xml)
    shared = _SharedFormulas(xml)

    date_styles = {}
    if date_style_row is not None and date_style_row in spans:
        s, e = spans[date_style_row]
        for col, a, _, _ in _cells(xml[s:e]):
            if col in date_cols and 's' in a:
                date_styles[col] = a['s']

    replacements = {}       # row → new row xml

    for n, values in edits.items():
        if n not in spans:
            raise PatchError(f'الصف {n} غير موجود في ورقة «{sheet_name}»')
        s, e = spans[n]
        row_xml = xml[s:e]
        head = re.match(r'<row\b[^>]*?(/>|>)', row_xml).group(0)
        cells = {col: (a, inner, whole) for col, a, inner, whole in _cells(row_xml)}
        out = {}
        for col, (a, inner, whole) in cells.items():
            if col not in values:
                out[col] = whole
                continue
            ref = a['r']
            fm = _F.search(inner or '')
            if fm:
                out[col] = _formula_cell(ref, a, fm.group(0), values[col], formula_kinds.get(col, 'n'))
            else:
                out[col] = _value_cell(ref, a, values[col], date_styles.get(col), date1904)
        for col, value in values.items():
            if col not in cells and value not in (None, ''):
                out[col] = _value_cell(f'{get_column_letter(col)}{n}', {}, value, date_styles.get(col), date1904)
        if head.endswith('/>'):
            head = head[:-2] + '>'
        replacements[n] = head + ''.join(out[c] for c in sorted(out)) + '</row>'

    old_last = new_last = None
    if appends:
        if template_row not in spans:
            raise PatchError('لا يوجد صف نموذج لإضافة صفوف جديدة')
        s, e = spans[template_row]
        t_xml = xml[s:e]
        t_head = re.match(r'<row\b[^>]*?(/>|>)', t_xml).group(0)
        t_attrs = {k: v for k, v in _attrs(t_head[4:].rstrip('/>')).items() if k != 'r'}
        t_cells = {col: (a, inner) for col, a, inner, _ in _cells(t_xml)}
        old_last = template_row
        for n, values in appends:
            out = {}
            for col in sorted(set(t_cells) | {c for c, v in values.items() if v not in (None, '')}):
                a, inner = t_cells.get(col, ({}, None))
                ref = f'{get_column_letter(col)}{n}'
                fm = _F.search(inner or '')
                if fm:
                    origin, text = shared.text(_attrs(fm.group(1)), fm.group(2), a['r'])
                    f_xml = f'<f>{escape(_translate(text, origin, ref))}</f>'
                    out[col] = _formula_cell(ref, a, f_xml, values.get(col), formula_kinds.get(col, 'n'))
                else:
                    style = date_styles.get(col) if isinstance(values.get(col), (dt.date, dt.datetime)) else None
                    out[col] = _value_cell(ref, a, values.get(col), style, date1904)
            replacements[n] = f'<row r="{n}"{_attr_text(t_attrs)}>' + ''.join(out[c] for c in sorted(out)) + '</row>'
            new_last = max(new_last or 0, n)

    # Splice: replace existing rows; insert new rows after the nearest row above them.
    pieces, pos = [], 0
    order = sorted(spans.items(), key=lambda kv: kv[1][0])
    inserts = sorted(n for n in replacements if n not in spans)
    sheet_data_end = xml.find('</sheetData>')
    if sheet_data_end < 0:
        empty = re.search(r'<sheetData\s*/>', xml)
        if empty is None:
            raise PatchError(f'ورقة «{sheet_name}» بلا بيانات')
        xml = xml[:empty.start()] + '<sheetData></sheetData>' + xml[empty.end():]
        sheet_data_end = xml.find('</sheetData>')
    pending = list(inserts)
    for n, (s, e) in order:
        while pending and pending[0] < n:
            pieces.append(xml[pos:s])
            pieces.append(replacements[pending.pop(0)])
            pos = s
        pieces.append(xml[pos:s])
        pieces.append(replacements.get(n, xml[s:e]))
        pos = e
    pieces.append(xml[pos:sheet_data_end])
    for n in pending:
        pieces.append(replacements[n])
    pieces.append(xml[sheet_data_end:])
    xml = ''.join(pieces)

    changed = {path}
    if new_last:
        def grow_attr(m):
            return m.group(1) + _grow(m.group(2), old_last, new_last) + m.group(3)
        dim = re.search(r'(<dimension\b[^>]*?\bref=")([^"]+)(")', xml)
        if dim and ':' in dim.group(2):
            min_col, min_row, max_col, max_row = range_boundaries(dim.group(2))
            if new_last > max_row:
                new_ref = f'{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{new_last}'
                xml = xml[:dim.start(2)] + new_ref + xml[dim.end(2):]
        xml = re.sub(r'(<autoFilter\b[^>]*?\bref=")([^"]+)(")', grow_attr, xml, count=1)
        for rid, (kind, target) in _rels(parts, path).items():
            if kind.endswith('/table') and target in parts:
                t = parts[target].decode('utf-8')
                t2 = re.sub(r'(<table\b[^>]*?\bref=")([^"]+)(")', grow_attr, t, count=1)
                t2 = re.sub(r'(<autoFilter\b[^>]*?\bref=")([^"]+)(")', grow_attr, t2, count=1)
                if t2 != t:
                    parts[target] = t2.encode('utf-8')
                    changed.add(target)
    parts[path] = xml.encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zout:
        for info in infos:
            zout.writestr(info, parts[info.filename], compress_type=info.compress_type)
    return buf.getvalue(), changed


def changed_parts(old, new):
    """Zip parts whose bytes differ between two workbooks, plus parts only one of them has."""
    with zipfile.ZipFile(io.BytesIO(old)) as a, zipfile.ZipFile(io.BytesIO(new)) as b:
        names_a, names_b = set(a.namelist()), set(b.namelist())
        out = names_a ^ names_b
        for name in names_a & names_b:
            if a.read(name) != b.read(name):
                out.add(name)
    return out


def editable_parts(data, sheet_name):
    """The zip parts `patch` may change: the worksheet `sheet_name` and its tables (they grow with appended rows)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = {n: z.read(n) for n in z.namelist() if n.endswith('.rels') or n == 'xl/workbook.xml'}
    path, _ = sheet_part(parts, sheet_name)
    return {path} | {t for k, t in _rels(parts, path).values() if k.endswith('/table')}
