"""Finance party codes <-> SOFTECH persons (Plan 2 / Task 2).

Finance's sub-ledger codes (suppliers / creditors / customers) are imported as GLParty rows,
proposed against ReconParty by normalised name, and only ever *confirmed* by a human. An
unconfirmed party never resolves, so its documents become exceptions (spec section 7).
"""
import math
from dataclasses import dataclass

import openpyxl
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.finance.models import GLParty, ReconParty
from .names import normalize_ar

STOP_WORDS = {'شركه', 'شركة', 'ش', 'للادويه', 'لتجاره', 'الادويه', 'ادويه', 'فرع', 'و', 'ال'}
_SKIP = {'total', 'grand total', normalize_ar('الرصيد الافتتاحى')}
_HEADERS = {'suppliar code': 'supplier', 'customer code': 'customer'}
# Ruling P26: finance's 2020 master sheets - (code header, name header) pairs, normalised
_MASTER_HEADERS = {(normalize_ar('الكود'), normalize_ar('اسم المورد')): 'supplier',
                   (normalize_ar('كود الموظف'), 'name in arabic'): 'employee',
                   (normalize_ar('كود العميل'), normalize_ar('اسم العميل')): 'customer'}


def _hdr(v) -> str:
    return normalize_ar(v).lower()


@dataclass(frozen=True)
class PartyRow:
    party_type: str
    code: str
    name: str
    master: bool = False   # from a 2020 master sheet (Ruling P26): imported only in create_only mode
    sheet: str = ''


def _audit(action, *, user, obj, old_data=None, new_data=None, extra=None):
    row = AuditLog(action=action)
    if user:
        row.user, row.user_name, row.user_role = user, user.full_name, user.role
    if obj is not None:
        row.model_name, row.object_id = type(obj).__name__, str(obj.pk)
        row.object_repr = str(obj)[:200]
    row.old_data, row.new_data, row.extra = old_data or None, new_data or None, extra or None
    row.save()


def _snap(p):
    return {'party_type': p.party_type, 'code': p.code, 'name': p.name,
            'softech_personcode': p.softech_personcode, 'status': p.status,
            'proposal_basis': p.proposal_basis}


def _code(v):
    """Integer-like cell -> str(int); anything else (None, text, totals, fractions) -> None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        f = v
    else:
        try:
            f = float(str(v).strip())
        except ValueError:
            return None
    if not math.isfinite(f):   # 'nan' / 'inf' cells: skip the row, never raise
        return None
    return str(int(f)) if f == int(f) else None


def _name(v):
    """Non-empty, non-numeric text, else None."""
    if v is None or isinstance(v, (int, float)):
        return None
    s = str(v).strip()
    if not s or s.lower() in _SKIP or normalize_ar(s) in _SKIP:
        return None
    try:
        float(s)
        return None
    except ValueError:
        return s


def parse_party_sheets(path) -> list[PartyRow]:
    """Read sub-ledger pivots by header ('suppliar code' / 'customer code') and the 2020 master
    sheets by their (code, name) header pair (Ruling P26), never by position. The name is the cell
    right of the code. Duplicate (type, code) keep the first name (master rows are deduplicated
    separately, so a skipped master sheet never hides a sub-ledger row)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    seen, out = set(), []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        hdr = None
        for i, r in enumerate(rows):
            for j, c in enumerate(r):
                t, master = _HEADERS.get(_hdr(c)), False
                if not t and j + 1 < len(r):
                    t = _MASTER_HEADERS.get((_hdr(c), _hdr(r[j + 1])))
                    master = bool(t)
                if t:
                    hdr = (i, j, t, master)
                    break
            if hdr:
                break
        if not hdr:
            continue
        i0, j, ptype, master = hdr
        for r in rows[i0 + 1:]:
            if j >= len(r):
                continue
            code = _code(r[j])
            if not code:
                continue
            name = _name(r[j + 1]) if j + 1 < len(r) else None
            if not name:
                continue
            if (master, ptype, code) in seen:
                continue
            seen.add((master, ptype, code))
            out.append(PartyRow(ptype, code, name, master, ws.title))
    wb.close()
    return out


def import_parties(rows, *, user, create_only=False) -> dict:
    """Create missing parties; rename existing ones unless `create_only` (Ruling P26: the 2020
    master sheets only add codes - the 2026 sub-ledger names stay authoritative). Master-sheet rows
    are imported only in `create_only` mode; otherwise they are skipped and reported."""
    created = updated = 0
    skipped = [r for r in rows if r.master and not create_only]
    master_sheets = sorted({r.sheet for r in skipped})
    with transaction.atomic():
        for r in rows:
            if r.master and not create_only:
                continue
            obj, was_new = GLParty.objects.get_or_create(
                party_type=r.party_type, code=r.code, defaults={'name': r.name[:200]})
            if was_new:
                created += 1
            elif not create_only and r.name and obj.name != r.name[:200]:
                obj.name = r.name[:200]
                obj.save(update_fields=['name'])
                updated += 1
        _audit('gl_parties_imported', user=user, obj=None,
               extra={'created': created, 'updated': updated, 'rows': len(rows),
                      'create_only': bool(create_only), 'master_skipped': len(skipped),
                      'master_sheets': master_sheets})
    return {'created': created, 'updated': updated, 'master_skipped': len(skipped),
            'master_sheets': master_sheets}


def _tokens(name) -> frozenset:
    return frozenset(t for t in normalize_ar(name).split() if t not in STOP_WORDS)


def propose_matches(*, user) -> dict:
    """Propose (never confirm) a ReconParty for every unmapped party; exactly one candidate."""
    recon = {}
    for rp in ReconParty.objects.all():
        recon.setdefault(rp.party_type, []).append(rp)
    res = {'exact': 0, 'tokens': 0, 'none': 0}
    with transaction.atomic():
        for g in GLParty.objects.filter(status='unmapped', is_active=True):
            cands = recon.get(g.party_type, [])
            norm = normalize_ar(g.name)
            hit, basis = [], 'exact'
            if norm:
                hit = [c for c in cands if normalize_ar(c.name) == norm]
                if not hit:
                    tk = _tokens(g.name)
                    if tk:
                        hit, basis = [c for c in cands if _tokens(c.name) == tk], 'tokens'
            if len(hit) != 1:
                res['none'] += 1
                continue
            old = _snap(g)
            g.recon_party, g.softech_personcode = hit[0], hit[0].softech_personcode
            g.status, g.proposal_basis = 'proposed', basis
            g.save(update_fields=['recon_party', 'softech_personcode', 'status', 'proposal_basis'])
            _audit('gl_party_proposed', user=user, obj=g, old_data=old, new_data=_snap(g))
            res[basis] += 1
    return res


def _confirm(g, user, personcode, basis, name=''):
    if g.status == 'confirmed' and g.softech_personcode:
        if g.softech_personcode == str(personcode).strip():
            return g
        raise ValueError('هذا الطرف مؤكد بالفعل على كود SOFTECH مختلف')
    old = _snap(g)
    if name:
        g.name = name[:200]
    g.softech_personcode = str(personcode).strip()
    g.recon_party = ReconParty.objects.filter(softech_personcode=g.softech_personcode,
                                         party_type=g.party_type).first()
    g.status, g.proposal_basis = 'confirmed', basis or g.proposal_basis or 'manual'
    g.confirmed_by, g.confirmed_at = user, timezone.now()
    try:
        with transaction.atomic():
            g.save()
    except IntegrityError:
        raise ValueError('كود SOFTECH هذا مربوط بطرف آخر مؤكد بالفعل') from None
    _audit('gl_party_confirmed', user=user, obj=g, old_data=old, new_data=_snap(g))
    return g


def confirm_party(party_id, *, user, personcode: str) -> GLParty:
    if not str(personcode or '').strip():
        raise ValueError('كود SOFTECH مطلوب')
    with transaction.atomic():
        g = GLParty.objects.select_for_update().get(pk=party_id)
        basis = g.proposal_basis if (g.softech_personcode == str(personcode).strip()
                                     and g.proposal_basis) else 'manual'
        return _confirm(g, user, personcode, basis)


def reject_party(party_id, *, user) -> GLParty:
    with transaction.atomic():
        g = GLParty.objects.select_for_update().get(pk=party_id)
        old = _snap(g)
        g.status, g.softech_personcode, g.recon_party = 'rejected', '', None
        g.save(update_fields=['status', 'softech_personcode', 'recon_party'])
        _audit('gl_party_rejected', user=user, obj=g, old_data=old, new_data=_snap(g))
    return g


def create_party_from_personcode(*, user, party_type, code, personcode, name='') -> GLParty:
    """Confirmed party for a code finance never listed (from the exceptions inbox)."""
    personcode = str(personcode).strip()
    rp = ReconParty.objects.filter(softech_personcode=personcode, party_type=party_type).first()
    with transaction.atomic():
        g, _ = GLParty.objects.select_for_update().get_or_create(
            party_type=party_type, code=str(code),
            defaults={'name': (name or (rp.name if rp and rp.name else str(code)))[:200]})
        return _confirm(g, user, personcode, 'manual', name=name)


def resolve_party(party_type: str, personcode: str):
    """Confirmed + active only; proposals never resolve."""
    return GLParty.objects.filter(party_type=party_type, softech_personcode=str(personcode),
                                  status='confirmed', is_active=True).first()


# ── bulk confirm from the reviewed suggestions sheet ─────────────────────────
# Header labels of the «مقترحات الربط» sheet; matched after Arabic normalisation, by "starts with".
_CONFIRM_COLS = {'type': 'النوع', 'code': 'كود المالية', 'personcode': 'الكود المعتمد'}
_TYPE_WORDS = {'عميل': 'customer', 'customer': 'customer', 'مورد': 'supplier', 'دائن': 'supplier',
               'supplier': 'supplier'}


@dataclass(frozen=True)
class ConfirmRow:
    row: int            # Excel row number, for messages
    party_type: str
    code: str
    personcode: str
    name: str = ''      # «اسم المالية», optional


def _names_conflict(a, b) -> bool:
    """True when two names for one finance code share no word: likely two different parties."""
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb and not (ta & tb))


def _party_type(v):
    s = normalize_ar(str(v or '')).strip().lower()
    for word, ptype in _TYPE_WORDS.items():
        if s.startswith(normalize_ar(word)):
            return ptype
    return None


def parse_confirm_sheet(path) -> tuple[list[ConfirmRow], list[dict]]:
    """Rows of the first sheet that has the three headers; rows with an empty approved code are
    left out (not reviewed yet). Returns (rows, problems) — a problem is {row, detail}."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            for hdr_no, hdr in enumerate(it, start=1):
                if hdr_no > 5:
                    break
                labels = [normalize_ar(str(c or '')).strip() for c in hdr]
                cols = {}
                for key, label in _CONFIRM_COLS.items():
                    want = normalize_ar(label)
                    cols[key] = next((i for i, t in enumerate(labels) if t.startswith(want)), None)
                if None in cols.values():
                    continue
                want_name = normalize_ar('اسم المالية')
                name_col = next((i for i, t in enumerate(labels) if t.startswith(want_name)), None)
                rows, problems = [], []
                for n, r in enumerate(it, start=hdr_no + 1):
                    cell = lambda k: r[cols[k]] if cols[k] < len(r) else None   # noqa: E731
                    raw_pc = cell('personcode')
                    if raw_pc is None or not str(raw_pc).strip():
                        continue
                    pc = _code(raw_pc)
                    ptype, code = _party_type(cell('type')), _code(cell('code'))
                    if not ptype or not code:
                        problems.append({'row': n, 'detail': 'النوع أو كود المالية غير مفهوم'})
                    elif not pc:
                        problems.append({'row': n, 'detail': f'الكود المعتمد «{raw_pc}» ليس رقماً'})
                    else:
                        raw_name = r[name_col] if name_col is not None and name_col < len(r) else None
                        rows.append(ConfirmRow(n, ptype, code, pc, str(raw_name or '').strip()))
                return rows, problems
        raise ValueError('لم أجد أعمدة «النوع» و«كود المالية» و«الكود المعتمد» في الملف')
    finally:
        wb.close()


def bulk_confirm(rows, problems, *, user, apply: bool) -> dict:
    """Preview (apply=False, nothing saved) or confirm every valid row through ``confirm_party``
    (audited per party). Each row stands alone: a refused row never blocks the others.
    A code not imported yet is added under the sheet's name (``create_party_from_personcode``).
    A sheet name sharing no word with the party's name is held back as ``name_conflict``: the code
    may be two parties, so a person decides on the grid; it is never renamed or confirmed here.
    Result: {results: [{row, party_type, code, name, personcode, outcome, detail}], counts}."""
    results = [{'row': p['row'], 'outcome': 'error', 'detail': p['detail']} for p in problems]
    seen = {}
    for r in rows:
        key = (r.party_type, r.personcode)
        if key in seen:
            results.append({'row': r.row, 'party_type': r.party_type, 'code': r.code, 'personcode': r.personcode,
                            'outcome': 'error',
                            'detail': f'كود SOFTECH {r.personcode} مكرر في الملف (السطر {seen[key]})'})
            continue
        seen[key] = r.row
        out = {'row': r.row, 'party_type': r.party_type, 'code': r.code, 'personcode': r.personcode}
        g = GLParty.objects.filter(party_type=r.party_type, code=r.code).first()
        if g is None:
            if not r.name:
                results.append({**out, 'outcome': 'error', 'detail': 'الطرف غير موجود — استورد أطراف الحسابات أولاً'})
                continue
            out['name'] = r.name
            try:
                with transaction.atomic():
                    create_party_from_personcode(user=user, party_type=r.party_type, code=r.code,
                                                 personcode=r.personcode, name=r.name)
                    if not apply:
                        transaction.set_rollback(True)
            except ValueError as e:
                results.append({**out, 'outcome': 'error', 'detail': str(e)})
                continue
            results.append({**out, 'outcome': 'created' if apply else 'will_create'})
            continue
        out['name'] = g.name
        if g.status == 'confirmed' and g.softech_personcode == r.personcode:
            results.append({**out, 'outcome': 'unchanged', 'detail': 'مؤكد بالفعل'})
            continue
        if r.name and _names_conflict(r.name, g.name):
            results.append({**out, 'outcome': 'name_conflict',
                            'detail': f'الاسم في الملف «{r.name}» غير الاسم المسجل — راجعه وأكّده من الجدول'})
            continue
        try:
            with transaction.atomic():
                confirm_party(g.pk, user=user, personcode=r.personcode)
                if not apply:
                    transaction.set_rollback(True)
        except ValueError as e:
            results.append({**out, 'outcome': 'error', 'detail': str(e)})
            continue
        results.append({**out, 'outcome': 'confirmed' if apply else 'will_confirm'})
    results.sort(key=lambda x: x['row'])
    counts = {}
    for x in results:
        counts[x['outcome']] = counts.get(x['outcome'], 0) + 1
    if apply:
        _audit('gl_parties_bulk_confirmed', user=user, obj=None, extra={'counts': counts, 'rows': len(results)})
    return {'results': results, 'counts': counts, 'applied': apply}
