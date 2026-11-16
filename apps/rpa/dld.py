"""Parser for DataLoad ``.dld`` templates, and import of one as a draft RpaRecipe.

A template is a text file of ``begin<x>`` / ``end<x>`` sections. We read ``delays``, ``header`` (first line
= column kinds), ``other`` (``Window=``) and the first ``data`` block; everything else is ignored.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max

KIND_BY_HEADER = {'Key Strokes': 'keys', 'Data': 'data'}


@dataclass
class DldTemplate:
    window_title: str
    cell_delay: Decimal
    form_delay: Decimal
    column_kinds: list = field(default_factory=list)
    rows: list = field(default_factory=list)


def decode_dld(raw: bytes) -> str:
    """Bytes of a .dld file to text. DataLoad itself saves the Window= line in the Windows Arabic ANSI page
    (cp1256) while the owner's copies are UTF-8 with a BOM, so try UTF-8 first."""
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1256')


def _sections(text: str) -> dict:
    """First occurrence of each section name -> its lines (the trailing grids repeat ``begindata``)."""
    found, name, lines = {}, None, []
    for line in text.lstrip('﻿').splitlines():
        stripped = line.strip()
        if name is None:
            if stripped.startswith('begin'):
                name, lines = stripped[5:], []
        elif stripped == 'end' + name:
            found.setdefault(name, lines)
            name = None
        else:
            lines.append(line)
    return found


def _decimal(value, default):
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return Decimal(default)


def _cut_trailing_empty(cells: list) -> list:
    while cells and cells[-1] == '':
        cells = cells[:-1]
    return cells


def parse_dld(text: str) -> DldTemplate:
    sections = _sections(text)
    pairs = {}
    for line in sections.get('delays', []):
        key, sep, value = line.partition('=')
        if sep:
            pairs[key.strip()] = value.strip()
    window = next((l.partition('=')[2].strip() for l in sections.get('other', []) if l.startswith('Window=')), '')
    if not window:
        raise ValueError('template has no Window= line')

    header = sections.get('header') or ['']
    kinds = []
    for cell in _cut_trailing_empty(header[0].split('\t')):
        if cell not in KIND_BY_HEADER:
            raise ValueError(f'unknown column kind in header: {cell!r}')
        kinds.append(KIND_BY_HEADER[cell])
    if not kinds:
        raise ValueError('template header has no columns')

    rows = []
    for line in sections.get('data', []):
        cells = (_cut_trailing_empty(line.split('\t')) + [''] * len(kinds))[:len(kinds)]
        # A blank row has an empty first data column (the owner's template pre-fills the expiry column and
        # repeats the keystrokes on its spare rows, so "all data columns empty" would keep them).
        first_data = kinds.index('data') if 'data' in kinds else None
        if first_data is not None and cells[first_data].strip():
            rows.append(cells)
    return DldTemplate(window_title=window, cell_delay=_decimal(pairs.get('CellDelay'), '0.2'),
                       form_delay=_decimal(pairs.get('FormDelay'), '0.25'), column_kinds=kinds, rows=rows)


def recipe_from_dld(template: DldTemplate, *, screen, field_map: list, created_by, source_filename: str = ''):
    """Draft RpaRecipe from a template. ``field_map`` names the data columns in order; each keys column takes its
    keystrokes from the template's first non-blank row."""
    from apps.audit.models import AuditLog
    from apps.rpa.models import RpaRecipe

    data_columns = template.column_kinds.count('data')
    if len(field_map) != data_columns:
        raise ValueError(f'field_map has {len(field_map)} names but the template has {data_columns} data columns')
    if not template.rows:
        raise ValueError('template has no non-blank data row to read the keystrokes from')

    names, cells = iter(field_map), []
    for kind, cell in zip(template.column_kinds, template.rows[0]):
        cells.append({'kind': 'field', 'value': next(names)} if kind == 'data' else {'kind': 'keys', 'value': cell})

    with transaction.atomic():
        top = RpaRecipe.objects.filter(screen=screen).aggregate(m=Max('version'))['m'] or 0
        recipe = RpaRecipe.objects.create(
            screen=screen, version=top + 1, status='draft', window_title=template.window_title,
            cell_delay=template.cell_delay, form_delay=template.form_delay, line_cells=cells,
            source_filename=source_filename, created_by=created_by)
        AuditLog.log('rpa_recipe_imported', user=created_by, obj=recipe,
                     new_data={'screen': screen.key, 'version': recipe.version, 'source_filename': source_filename,
                               'line_cells': cells})
    return recipe
