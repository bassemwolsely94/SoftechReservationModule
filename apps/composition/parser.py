"""
Deterministic active-ingredient name parser.
============================================

Turns a raw SOFTECH ``activeingredients.ainame`` string (dirty free text that
conflates molecule + strength + salt form + combinations on a single line) into
a structured proposal:

    "AMLODIPINE (AS BESYLATE) 10 MG + VALSARTAN 160 MG"
      → combination of:
          molecule=AMLODIPINE  salt=besylate  10 mg
          molecule=VALSARTAN                  160 mg

IMPORTANT (project rules 5 / 10): this is a PROPOSAL engine only. It is
deterministic — no fuzzy/AI decisions — and every result is meant to be reviewed
and approved by a human before it is trusted or written anywhere. It never
decides substitutions or mutates data.

Kept dependency-free and Django-free so it can be unit-tested in isolation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PARSER_VERSION = '1.1'

# ── Approved unit set ────────────────────────────────────────────────────────
# Derived from the real ``ainame`` corpus (7,857 names) via
# ``derive_ingredient_units`` and approved by the owner (2026-08-25). Alias
# spellings (ug, gm, i.u, m.i.u, units) are INCLUDED so the regex matches them,
# then collapsed by ``_norm_unit`` to a canonical form. Ratio literals are listed
# explicitly; the regex ratio-tail also catches unseen "<num><unit>" ratios.
#
# Deliberately EXCLUDED as non-strength noise (they are molecule/packaging/age
# fragments): m, i, b, a, c, e, b2, b6, b12, b2b6, months, month, year(s), age,
# to, fish, collagen, biotin, box, blades, cream, complex, dis, off20%, and — per
# owner — the ambiguous ``gr`` and ``mil`` (rows using them get flagged for review).
PROVISIONAL_UNITS = [
    # concentration ratios (matched before their base units)
    'mg/ml', 'mg/5ml', 'mg/2ml', 'mg/1ml', 'mg/10ml', 'mg/100ml',
    'mcg/ml', 'iu/ml', 'u/ml', 'g/100ml', 'g/100g', 'gm/100gm', 'gm/10ml',
    'mg/1gm', 'mg/gm', 'mg/g', 'mcg/inhalation', 'mcg/dose', 'mcg/puff',
    # mass / volume
    'mg', 'mcg', 'ug', 'g', 'gm', 'ng', 'ml', 'l',
    # activity / percent / microbial
    '%', 'iu', 'i.u', 'ui', 'u', 'unit', 'units', 'miu', 'm.i.u',
    'meq', 'mmol', 'cfu', 'billion', 'million',
    # ratio denominators (so the regex tail can consume "/inhalation" etc.)
    'inhalation', 'dose', 'puff',
]

# ── Salt / ester forms to peel off the molecule name ─────────────────────────
# Keeps AMLODIPINE and "AMLODIPINE BESYLATE" collapsing to one molecule while
# preserving the salt as a separate attribute.
SALT_FORMS = [
    'besylate', 'maleate', 'mesylate', 'fumarate', 'succinate', 'tartrate',
    'hydrochloride', 'hydrobromide', 'hcl', 'hbr',
    'sulphate', 'sulfate', 'phosphate', 'nitrate', 'acetate', 'citrate',
    'sodium', 'potassium', 'calcium', 'magnesium', 'zinc',
    'dihydrate', 'monohydrate', 'trihydrate', 'hemihydrate', 'anhydrous',
    'valerate', 'propionate', 'dipropionate', 'furoate', 'xinafoate',
    'bromide', 'chloride', 'gluconate', 'lactate', 'oxide',
    'pamoate', 'embonate', 'arginine', 'aspartate', 'arginin',
]

# ── Placeholder / junk names — never propose a molecule from these ───────────
PLACEHOLDERS = {
    '', 'undefined item', 'undefined', 'n/a', 'na', 'n/a unidentified',
    'unidentified', 'not defined', 'none', '-', '--', 'xxx', 'test',
}

# Combination separators that DON'T also appear inside strength ratios.
_COMBO_TOKENS = re.compile(r'\s*(?:\+|,|&|\bAND\b|\bWITH\b)\s*', re.IGNORECASE)

# A numeric quantity, optionally decimal (comma or dot decimal separator).
_NUM = r'\d+(?:[.,]\d+)?'


def _unit_pattern(units) -> str:
    """Build a regex alternation of units, longest first so 'mg/ml' beats 'mg'."""
    esc = sorted((re.escape(u) for u in units), key=len, reverse=True)
    return '(?:' + '|'.join(esc) + ')'


def _strength_regex(units):
    unit = _unit_pattern(units)
    # number + unit, plus an optional "/<num?> <unit>" ratio tail (e.g. 5mg/5ml)
    ratio = r'(?:\s*/\s*' + _NUM + r'?\s*' + unit + r')?'
    return re.compile(r'(' + _NUM + r')\s*(' + unit + ratio + r')', re.IGNORECASE)


@dataclass
class ParsedComponent:
    molecule: str = ''            # uppercase molecule, salt stripped
    salt: str = ''                # e.g. "besylate"
    strength_value: float | None = None
    strength_unit: str = ''       # normalized unit, e.g. "mg", "mg/ml"
    raw_fragment: str = ''

    def to_json(self) -> dict:
        return {
            'molecule': self.molecule,
            'salt': self.salt,
            'strength_value': self.strength_value,
            'strength_unit': self.strength_unit,
            'raw_fragment': self.raw_fragment,
        }


@dataclass
class ParseResult:
    raw_name: str
    components: list[ParsedComponent] = field(default_factory=list)
    is_combination: bool = False
    is_placeholder: bool = False
    confidence: float = 0.0
    parser_version: str = PARSER_VERSION

    def to_json(self) -> dict:
        return {
            'raw_name': self.raw_name,
            'components': [c.to_json() for c in self.components],
            'is_combination': self.is_combination,
            'is_placeholder': self.is_placeholder,
            'confidence': round(self.confidence, 3),
            'parser_version': self.parser_version,
        }

    @property
    def molecules(self) -> list[str]:
        return [c.molecule for c in self.components if c.molecule]


def _norm_unit(unit: str) -> str:
    u = unit.lower().replace(' ', '')
    return {
        'ug': 'mcg', 'gm': 'g', 'ui': 'iu', 'units': 'unit',
        'i.u': 'iu', 'm.i.u': 'miu',
    }.get(u, u)


def _split_molecule_combinations(text: str) -> list[str]:
    """
    Split a strength-masked string into molecule fragments.

    Strengths are already masked to sentinels (``\x00N\x00``) before this runs,
    so the only remaining '/' characters separate two molecules
    (e.g. "AMLODIPINE / ATORVASTATIN") rather than a strength ratio.
    """
    # First split on the unambiguous combo tokens.
    parts = _COMBO_TOKENS.split(text)
    out: list[str] = []
    for p in parts:
        # A remaining slash now means molecule/molecule.
        out.extend(seg for seg in p.split('/'))
    return [seg.strip() for seg in out if seg and seg.strip()]


def _extract_salt(fragment: str) -> tuple[str, str]:
    """Return (fragment_without_salt, salt_form)."""
    salt = ''
    working = fragment
    # "(as besylate)" or "as besylate"
    for sf in SALT_FORMS:
        pat = re.compile(r'\b' + re.escape(sf) + r'\b', re.IGNORECASE)
        if pat.search(working):
            salt = salt or sf.lower()
            working = pat.sub(' ', working)
    # strip a lone "(as ...)" scaffolding and stray parentheses / the word "as"
    working = re.sub(r'\(\s*as\b', ' ', working, flags=re.IGNORECASE)
    working = re.sub(r'\bas\b', ' ', working, flags=re.IGNORECASE)
    working = working.replace('(', ' ').replace(')', ' ')
    return working, salt


def _clean_molecule(text: str) -> tuple[str, str]:
    """
    Reduce a salt-stripped, strength-masked fragment to a molecule name.
    Returns (molecule_upper, residue) where residue is any leftover junk
    (used to lower confidence).
    """
    # Drop sentinels and any stray digits/symbols left behind.
    no_sentinel = re.sub(r'\x00\d+\x00', ' ', text)
    # Molecule characters: letters, spaces, and internal hyphens.
    letters = re.sub(r'[^A-Za-z\-\s]', ' ', no_sentinel)
    molecule = re.sub(r'\s+', ' ', letters).strip(' -').upper()
    # Residue = non-letter, non-sentinel leftovers (stray digits, symbols).
    residue = re.sub(r'\x00\d+\x00', '', text)
    residue = re.sub(r'[A-Za-z\s]', '', residue).strip()
    return molecule, residue


def parse(name: str, units=None) -> ParseResult:
    """
    Parse one raw active-ingredient name into a structured, reviewable proposal.

    ``units`` overrides the provisional unit list (pass the owner-approved set
    once it exists).
    """
    units = units or PROVISIONAL_UNITS
    raw = (name or '').strip()
    result = ParseResult(raw_name=raw)

    if raw.lower() in PLACEHOLDERS or not re.search(r'[A-Za-z]', raw):
        result.is_placeholder = True
        result.confidence = 0.0
        return result

    strength_re = _strength_regex(units)

    # 1) Mask every strength occurrence with an ordered sentinel so combo
    #    splitting can't trip over '/' inside a ratio like "5mg/5ml".
    strengths: list[tuple[float | None, str]] = []

    def _mask(m: re.Match) -> str:
        num_raw = m.group(1).replace(',', '.')
        try:
            val = float(num_raw)
        except ValueError:
            val = None
        strengths.append((val, _norm_unit(m.group(2))))
        return f'\x00{len(strengths) - 1}\x00'

    masked = strength_re.sub(_mask, raw)

    # 2) Split into molecule fragments.
    fragments = _split_molecule_combinations(masked)
    if not fragments:
        fragments = [masked]

    residue_seen = False
    for frag in fragments:
        # Which strength sentinels landed in this fragment?
        idxs = [int(i) for i in re.findall(r'\x00(\d+)\x00', frag)]
        no_salt, salt = _extract_salt(frag)
        molecule, residue = _clean_molecule(no_salt)
        if residue:
            residue_seen = True
        if not molecule and not idxs:
            continue
        sval, sunit = (strengths[idxs[0]] if idxs else (None, ''))
        result.components.append(ParsedComponent(
            molecule=molecule, salt=salt,
            strength_value=sval, strength_unit=sunit,
            raw_fragment=frag.replace('\x00', '').strip(),
        ))

    result.is_combination = len(result.components) > 1

    # 3) Confidence — deterministic heuristic, intentionally conservative.
    if not result.components or any(not c.molecule for c in result.components):
        result.confidence = 0.2
    else:
        conf = 0.9
        if len(result.components) == 1:
            conf += 0.05
        if residue_seen:
            conf -= 0.2
        if len(result.components) >= 3:
            conf -= 0.1
        result.confidence = max(0.0, min(1.0, conf))

    return result
