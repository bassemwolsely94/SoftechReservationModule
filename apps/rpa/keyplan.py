"""Server-built keyplans for the Windows RPA agent (Stage 1: dry-run only).

Turns an approved recipe plus a document's lines into the keystroke plan the agent replays. The
backend owns every decision here; the agent only types what it is handed, and the final step is
marked `final` so a dry run can cancel instead of saving.
"""
import re
from decimal import Decimal

from config.writers import writer_allowed

_DATALOAD = re.compile(r'\\{([^{}]*)\}')
_SPECIALS = set('+^%~(){}[]')
# The agent sends with with_spaces/with_tabs/with_newlines off, so whitespace must be explicit keys.
_WHITESPACE = {' ': '{SPACE}', '\t': '{TAB}', '\n': '{ENTER}'}


def _escape(text: str) -> str:
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return ''.join(_WHITESPACE.get(ch) or ('{%s}' % ch if ch in _SPECIALS else ch) for ch in text)


def to_send_keys(cell: str) -> str:
    r"""DataLoad `\{NAME}` becomes pywinauto `{NAME}`; any other text is literal (specials braced)."""
    out, pos = [], 0
    for m in _DATALOAD.finditer(cell):
        out.append(_escape(cell[pos:m.start()]))
        out.append('{%s}' % m.group(1))
        pos = m.end()
    out.append(_escape(cell[pos:]))
    return ''.join(out)


def format_field(line, field: str) -> str:
    if field == 'itemcode':
        return line.itemcode or ''
    if field == 'qty':
        text = format(Decimal(line.qty).normalize(), 'f')
        return text
    if field == 'expiry':
        d = line.expiry
        return '' if d is None else f'{d.day}/{d.month}/{d:%y}'
    raise ValueError(f'unknown recipe field: {field}')


_TOKEN = re.compile(r'\{\{\}|\{\}\}|\{[^{}]+\}|.', re.S)


def _norm_token(tok: str) -> str:
    if tok == '{{}':
        return '{'
    if tok == '{}}':
        return '}'
    if len(tok) > 1 and tok.startswith('{'):
        name = (tok[1:-1].split() or [''])[0].upper()
        if name.startswith('VK_'):
            name = name[3:]
        return name.lower() if len(name) == 1 else '{%s}' % name
    return tok.lower()


def _tokens(send: str) -> list:
    """Canonical send_keys tokens, so equivalent spellings compare equal.

    Brace names are upper-cased with any repeat count and VK_ prefix dropped; single-character
    braces and letters collapse to the bare lower-case character; `^(ab)` flattens to `^a ^b`.
    """
    raw = _TOKEN.findall(send)
    out, i = [], 0
    while i < len(raw):
        if raw[i] in ('+', '^', '%'):
            j = i
            while j < len(raw) and raw[j] in ('+', '^', '%'):
                j += 1
            mods = raw[i:j]
            if j < len(raw) and raw[j] == '(' and ')' in raw[j:]:
                end = raw.index(')', j)
                for ch in raw[j + 1:end]:
                    out.extend(mods + [_norm_token(ch)])
                i = end + 1
                continue
            out.extend(mods)
            i = j
            continue
        out.append(_norm_token(raw[i]))
        i += 1
    return out


def _contains(seq: list, sub: list) -> bool:
    return any(seq[i:i + len(sub)] == sub for i in range(len(seq) - len(sub) + 1))


def _cells_to_keys(cells, line=None, reference=None) -> str:
    parts = []
    for cell in cells or []:
        if isinstance(cell, str):
            parts.append(to_send_keys(cell))
        elif cell.get('kind') == 'field':
            name = cell['value']
            if name == 'reference':
                if reference is None:
                    raise ValueError('the reference field belongs in ref_cells, not line_cells')
                value = reference
            else:
                if line is None:
                    raise ValueError(f'line field {name!r} is only valid in line_cells')
                value = format_field(line, name)
            if any(ch in value for ch in '\r\n\t'):
                raise ValueError(f'field {name!r} value contains a newline or tab')
            parts.append(_escape(value))
        else:
            parts.append(to_send_keys(cell.get('value', '')))
    return ''.join(parts)


def _checklist(job, recipe) -> list:
    lines = list(recipe.header_checklist or [])
    if job.target_branch_id:
        lines.append(f'الفرع المستلم: {job.target_branch.name}')
    if job.store_code:
        lines.append(f'المخزن: {job.store_code}')
    return lines


def build_keyplan(document, *, mode: str) -> dict:
    job = document.job
    recipe = job.recipe
    if recipe is None:
        raise ValueError('job has no recipe')
    if mode == 'live':
        if not (job.screen.live and writer_allowed('RPA_SOFTECH_ENTRY_ENABLED') and recipe.save_keys):
            raise PermissionError('live entry is not enabled for this screen')
        final_label, final_keys = 'حفظ', recipe.save_keys
    elif mode == 'dry_run':
        if not recipe.cancel_keys:
            raise ValueError('recipe has no cancel keys; a dry run cannot end safely')
        final_label, final_keys = 'إلغاء بدون حفظ', recipe.cancel_keys
    else:
        raise ValueError(f'unknown mode: {mode}')

    lines = list(document.lines.order_by('row_no', 'pk'))
    if not lines:
        raise ValueError('document has no lines; a plan must not only save or cancel')

    steps = []
    for n, line in enumerate(lines, start=1):
        steps.append({'i': len(steps) + 1, 'label': f'سطر {n}',
                      'send': _cells_to_keys(recipe.line_cells, line)})
    if recipe.ref_cells:
        steps.append({'i': len(steps) + 1, 'label': 'المرجع',
                      'send': _cells_to_keys(recipe.ref_cells, reference=document.reference)})
    steps.append({'i': len(steps) + 1, 'label': final_label,
                  'send': _cells_to_keys(final_keys), 'final': True})

    popups = [{**p, 'answer_keys': to_send_keys(p['answer_keys'])} if p.get('answer_keys') else p
              for p in (recipe.popups or [])]

    if mode == 'dry_run' and recipe.save_keys:
        # A single-key save_keys (e.g. {ENTER}) refuses every dry run: deliberate, fails closed.
        save = _tokens(_cells_to_keys(recipe.save_keys))
        sequences = [[t for step in steps for t in _tokens(step['send'])]]
        sequences += [_tokens(p['answer_keys']) for p in popups if p.get('answer_keys')]
        if save and any(_contains(seq, save) for seq in sequences):
            raise ValueError('a dry-run plan must never contain the save keys')

    return {
        'document': document.pk,
        'reference': document.reference,
        'window_title': recipe.window_title,
        'cell_delay': float(recipe.cell_delay),
        'form_delay': float(recipe.form_delay),
        'checklist': _checklist(job, recipe),
        'popups': popups,
        'steps': steps,
    }
