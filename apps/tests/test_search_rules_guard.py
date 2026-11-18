"""S4 guard: every user-typed search box follows the system's search rules (``*``/``%`` wildcards,
word order, ranking). Plain DRF ``SearchFilter`` and a bare ``__icontains=<typed text>`` bypass them,
so a new search box cannot quietly ship without the rules.

Use ``apps.catalog.wildcard.wq`` (ORM) or ``WildcardSearchFilter`` (DRF). A genuine non-search use
(internal probe, saved criterion, privacy gate) goes in ALLOW below, keyed by
``'<path>::<matched expression>'`` with a written reason; a stale entry fails so the list cannot rot.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
SKIP_DIRS = {'tests', 'migrations', 'management'}

# any `<field>__icontains=<non-literal>` (a variable, attribute or subscript; quoted literals are fine)
ICONTAINS = re.compile(r"""[\w.]*__icontains=\s*[A-Za-z_][\w.\[\]'"]*""")
SEARCH_FILTER = re.compile(r"filters\.SearchFilter|(?<![\w.])SearchFilter\b")

ALLOW_SEARCH_FILTER = {
    'apps/catalog/wildcard.py::SearchFilter': 'WildcardSearchFilter subclasses DRF SearchFilter here',
}

ALLOW = {
    'apps/audit/detector.py::description__icontains=str':
        'detector looks for a record id in audit descriptions, internal',
    "apps/campaigns/dispatcher.py::health_profile__chronic_conditions__icontains=f['chronic_category']":
        'saved audience criterion at dispatch time, drives a WhatsApp send; stays literal',
    'apps/campaigns/views.py::chronic_conditions__icontains=chronic_category':
        'saved audience criterion that drives a WhatsApp send, not a search box',
    'apps/catalog/universal.py::search_name__icontains=nq':
        'normalized search_name haystack probe after item_search; code stays exact',
    'apps/customers/access.py::phone__icontains=d':
        'phone-findability privacy gate on exact digits; must not be wildcarded',
    'apps/customers/access.py::phone_alt__icontains=d':
        'phone-findability privacy gate on exact digits; must not be wildcarded',
    'apps/customers/access.py::whatsapp_phone__icontains=d':
        'phone-findability privacy gate on exact digits; must not be wildcarded',
    'apps/customers/recognition.py::phone__icontains=d':
        'incoming-call number recognition on digits, internal',
    'apps/customers/recognition.py::phone_alt__icontains=d':
        'incoming-call number recognition on digits, internal',
    'apps/customers/recognition.py::whatsapp_phone__icontains=d':
        'incoming-call number recognition on digits, internal',
    'apps/demand/models.py::softech_id__icontains=self.phcode':
        'internal lookup of customers by stored phcode',
    'apps/insights/rules.py::name__icontains=k':
        'rule keywords come from config, not typed in a search box',
    'apps/insurance/models.py::dept_name__icontains=self.filter_dept_name':
        'saved billing-group dept filter followed by a bulk update; wildcard-only text must not match everything',
    'apps/insurance/views.py::patient_name__icontains=probe':
        'internal patient-name probing while matching imports, not a user search',
    'apps/insurance/views.py::patient_name__icontains=toks[':
        'internal patient-name probing while matching imports, not a user search',
    'apps/shortage/matching.py::name_scientific__icontains=p3':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name_scientific__icontains=p4':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name_scientific__icontains=tok':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name_scientific__icontains=tok[1':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name_scientific__icontains=tok[':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name_scientific__icontains=broad_tok':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/tax_invoicing/gpc_ai.py::name_en__icontains=w':
        'AI helper word probe over GPC bricks, internal',
    'apps/tax_invoicing/gpc_ai.py::definition__icontains=w':
        'AI helper word probe over GPC bricks, internal',
    'apps/shortage/matching.py::name__icontains=p3':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name__icontains=p4':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name__icontains=t':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name__icontains=tok':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name__icontains=tok[1':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name__icontains=tok[':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
    'apps/shortage/matching.py::name__icontains=broad_tok':
        'internal fuzzy matcher builds its own tokens from the query, not a search box',
}


def _files():
    for p in sorted((REPO / 'apps').rglob('*.py')):
        rel = p.relative_to(REPO)
        if SKIP_DIRS & set(rel.parts):
            continue
        yield rel.as_posix(), p.read_text(encoding='utf-8', errors='replace').splitlines()


def _scan(pattern):
    """{key: [file:line, ...]} for every match of `pattern`, key = path::matched text."""
    hits = {}
    for rel, lines in _files():
        for n, line in enumerate(lines, 1):
            for m in pattern.finditer(line):
                hits.setdefault(f'{rel}::{m.group(0)}', []).append(f'{rel}:{n}')
    return hits


class SearchRulesGuardTests(SimpleTestCase):
    def _check(self, pattern, allow, label):
        hits = _scan(pattern)
        offenders = {k: v for k, v in hits.items() if k not in allow}
        self.assertFalse(offenders, (
            f'{label}: use apps.catalog.wildcard.wq / WildcardSearchFilter so the box follows the search rules '
            f'(* and % wildcards, word order). If it is not a user-typed search, add it to ALLOW with a reason.\n'
            + '\n'.join(f'  {", ".join(v)}  [{k}]' for k, v in sorted(offenders.items()))))
        stale = sorted(set(allow) - set(hits))
        self.assertFalse(stale, f'stale ALLOW entries (no longer found, remove them): {stale}')
        short = [k for k, why in allow.items() if len((why or '').strip()) < 10]
        self.assertFalse(short, f'ALLOW entries need a written reason of 10+ characters: {short}')

    def test_no_plain_search_filter(self):
        self._check(SEARCH_FILTER, ALLOW_SEARCH_FILTER, 'plain DRF SearchFilter')

    def test_no_icontains_on_search_text(self):
        self._check(ICONTAINS, ALLOW, '__icontains on typed text')

    def test_the_patterns_catch_the_shapes_they_guard(self):
        for src in ('filter_backends = [filters.SearchFilter]', 'filter_backends = [SearchFilter, X]'):
            self.assertTrue(SEARCH_FILTER.search(src), src)
        self.assertFalse(SEARCH_FILTER.search('filter_backends = [WildcardSearchFilter]'))
        for src in ('qs.filter(name__icontains=q)', 'qs.filter(name__icontains=params["q"])',
                    'qs.filter(a__b__icontains=self.text)'):
            self.assertTrue(ICONTAINS.search(src), src)
        self.assertFalse(ICONTAINS.search("qs.filter(name__icontains='literal')"))
