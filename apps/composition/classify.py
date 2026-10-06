"""
Deterministic molecule → pharmacological-class classifier.

Given a (already-parsed) molecule name, propose a class using, in priority order:
  1. exact OVERRIDES   (confidence 1.0 / 0.95 word-level)
  2. CONTAINS substrings (0.9)
  3. INN STEM_RULES     (0.85)
Returns (class_key|None, rule, confidence). No match → (None, '', 0.0).

Deterministic and Django-free — every result is a PROPOSAL a pharmacist reviews
before it is trusted (rules 5/10). Never used to auto-decide anything clinical.
"""
from __future__ import annotations

import re

from .taxonomy import OVERRIDES, CONTAINS, STEM_RULES

CLASSIFIER_VERSION = '1.0'

_WORD = re.compile(r'[A-Z]+')


def _norm(molecule: str) -> str:
    return re.sub(r'\s+', ' ', (molecule or '').upper()).strip()


def classify(molecule: str):
    """Return (class_key|None, rule, confidence) for one molecule name."""
    m = _norm(molecule)
    if not m:
        return (None, '', 0.0)

    # 1) exact override on the whole string
    if m in OVERRIDES:
        return (OVERRIDES[m], f'override:{m}', 1.0)

    words = _WORD.findall(m)
    # word-level exact override (e.g. "AMLODIPINE VALSARTAN" → VALSARTAN handled by stem,
    # but "ASCORBIC ACID" → ASCORBIC override)
    for w in words:
        if w in OVERRIDES:
            return (OVERRIDES[w], f'override_word:{w}', 0.95)

    # 2) substring overrides
    for sub, key in CONTAINS:
        if sub in m:
            return (key, f'contains:{sub}', 0.9)

    # 3) INN stems — test against each word
    for mode, stem, key in STEM_RULES:
        s = stem.upper()
        for w in words:
            if mode == 'suffix' and w.endswith(s) and len(w) > len(s):
                return (key, f'suffix:{stem}', 0.85)
            if mode == 'prefix' and w.startswith(s) and len(w) > len(s):
                return (key, f'prefix:{stem}', 0.85)
            if mode == 'contains' and s in w:
                return (key, f'contains_stem:{stem}', 0.85)

    return (None, '', 0.0)
