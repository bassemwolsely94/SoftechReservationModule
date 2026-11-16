"""Fixed synonym table (unified item search, design Appendix A / D3).

ONE direction: a typed token expands to its canonical form(s); typing SYRUP does not search
`syp`. Only a whole typed token expands. The canonical form must match as a whole word in the
name or as a unit glued to a number (`500MG`, `1G`) — see `apps.catalog.wildcard._synonym_ids`.
Keys are stored folded (`fold_query`), so Arabic spellings compare the way names do."""
from apps.catalog.wildcard import fold_query

_TABLE = [
    (('syp', 'syr', 'شراب'), ('SYRUP',)),
    (('susp', 'معلق'), ('SUSP', 'SUSPENSION')),
    (('tab', 'tabs', 'قرص', 'اقراص'), ('TAB',)),
    (('cap', 'caps', 'كبسول', 'كبسولات'), ('CAP',)),
    (('amp', 'حقن', 'حقنة', 'امبول'), ('AMP',)),
    (('vial', 'فيال'), ('VIAL',)),
    (('supp', 'لبوس', 'تحاميل'), ('SUPP',)),
    (('drops', 'drop', 'نقط', 'نقاط'), ('DROPS',)),
    (('cr', 'crm', 'كريم'), ('CREAM',)),
    (('oint', 'مرهم'), ('OINT',)),
    (('gel', 'جل'), ('GEL',)),
    (('sach', 'sachet', 'فوار', 'اكياس'), ('SACH',)),
    (('eff', 'effervescent', 'فوار'), ('EFF',)),
    (('inh', 'بخاخ'), ('INHALER', 'SPRAY')),
    (('vit', 'فيتامين'), ('VITAMIN',)),
    (('mg', 'مجم', 'مللجم'), ('MG',)),
    (('g', 'gm', 'gram', 'جم', 'جرام'), ('G', 'GM')),
    (('ml', 'مل'), ('ML',)),
    (('mcg', 'ميكروجرام'), ('MCG',)),
    (('iu', 'وحدة'), ('IU',)),
]


def _build() -> dict:
    out: dict = {}
    for keys, canon in _TABLE:
        for k in keys:
            k = fold_query(k)
            out[k] = tuple(dict.fromkeys(out.get(k, ()) + canon))   # 'فوار' → SACH + EFF
    return out


SYNONYMS: dict = _build()


def expand_terms(terms: list):
    """Per (folded) term: the typed term plus its canonical forms. None when no term has one."""
    out, any_hit = [], False
    for t in terms:
        canon = SYNONYMS.get(t)
        if canon:
            any_hit = True
        out.append(tuple(dict.fromkeys((t,) + (canon or ()))))
    return out if any_hit else None
