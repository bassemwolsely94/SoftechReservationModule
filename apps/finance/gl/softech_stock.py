"""Closing stock at cost from SOFTECH's own "stock at date" report tables (read-only).

``storebal_date`` holds one line per product per store for each date finance ran the report;
``storebal_datem`` says which stores the report was run for on which date. A store's closing value is
Σ nowqty × nowcostprice, summed in Decimal and rounded ONCE per store (ROUND_HALF_UP); nothing is
rounded again afterwards. Which stores count, and under which branch, comes from ``store_map``.

SOFTECH is reached only through ``apps.finance.queries.sybase_gl`` (SELECT-only), imported lazily:
nothing under ``gl/`` imports ``config.sybase`` at load.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from apps.batches.store_roles import CLOSED, resolver

logger = logging.getLogger('elrezeiky.finance')

CENT = Decimal('0.01')
HQ_BRANCH = '100'
HQ_STORES = ('100', '101', '102', '103', '104', '105', '110')   # 110 so the store role map ('100:110') closes it
STORE_BRANCH = {**{s: HQ_BRANCH for s in HQ_STORES}, '152': '150'}
DEFAULT_CARRY_FORWARD_UNTIL = date(2026, 10, 31)


class BadStockRow(Exception):
    """A line of SOFTECH's stock-at-date report has no quantity or cost: finance fixes it in SOFTECH."""
    code = 'bad_stock_row'

    def __init__(self, store_code: str):
        self.detail = {'store_code': store_code}
        super().__init__(f'تقرير رصيد المخازن في سوفتيك فيه صنف من غير كمية أو تكلفة في مخزن {store_label(store_code)}')


@dataclass(frozen=True)
class StoreRow:
    store_code: str
    rows: int
    value: Decimal


@dataclass(frozen=True)
class StoreRule:
    branch_code: str
    included: bool
    label: str


@dataclass
class Valuation:
    as_of: date
    stores: list = field(default_factory=list)
    total: Decimal = Decimal('0.00')
    excluded_total: Decimal = Decimal('0.00')
    missing_stores: list = field(default_factory=list)
    carried_stores: list = field(default_factory=list)


def _sybase_gl():
    from apps.finance.queries import sybase_gl   # lazy: gl/ never imports config.sybase at load
    return sybase_gl


def _code(v) -> str:
    return str(v if v is not None else '').strip()


def _day(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v).strip()[:10])


def _sum_stores(raw) -> list:
    """Raw storebal_date lines -> one StoreRow per store; the total is rounded once, products are not."""
    sums, counts = {}, {}
    for r in raw:
        code = _code(r['storecode'])
        if r['nowqty'] is None or r['nowcostprice'] is None:
            raise BadStockRow(code)
        sums[code] = sums.get(code, Decimal(0)) + Decimal(str(r['nowqty'])) * Decimal(str(r['nowcostprice']))
        counts[code] = counts.get(code, 0) + 1
    return [StoreRow(c, counts[c], sums[c].quantize(CENT, rounding=ROUND_HALF_UP)) for c in sorted(sums)]


def read_storebal(as_of: date) -> list:
    """Per-store row count and value of SOFTECH's stock-at-date report for ``as_of`` (one SELECT on HQ)."""
    return _sum_stores(_sybase_gl().storebal_rows(as_of))


def snapshot_stores(as_of: date) -> set:
    """The stores SOFTECH ran the stock-at-date report for on ``as_of``."""
    return {_code(r['storecode']) for r in _sybase_gl().storebal_snapshots(as_of, as_of)}


def valid_store_entry(store, entry) -> bool:
    """One `gl_closing_stock_stores` entry as the reader accepts it (the API writes only what passes this)."""
    branch = entry.get('branch') if isinstance(entry, dict) else None
    included = entry.get('included') if isinstance(entry, dict) else None
    return bool(isinstance(store, str) and store.strip() and isinstance(entry, dict)
                and set(entry) <= {'branch', 'included'} and entry
                and (branch is None or (isinstance(branch, str) and branch.strip()))
                and (included is None or isinstance(included, bool)))


def _setting_overrides() -> dict:
    """``gl_closing_stock_stores`` -> {store: {'branch'?: str, 'included'?: bool}}; invalid entries logged and dropped."""
    try:
        from apps.config.models import SystemSetting
        custom = SystemSetting.get('gl_closing_stock_stores')
    except Exception:
        custom = None
    if custom is None:
        return {}
    if not isinstance(custom, dict):
        logger.warning('[GLStock] gl_closing_stock_stores is not a JSON object — using the defaults')
        return {}
    out = {}
    for store, entry in custom.items():
        if not valid_store_entry(store, entry):
            logger.warning('[GLStock] ignored gl_closing_stock_stores entry %r → %r', store, entry)
            continue
        out[store.strip()] = {k: (v.strip() if isinstance(v, str) else v) for k, v in entry.items()}
    return out


def store_map(extra_stores=()) -> dict:
    """{store_code: StoreRule} for every store SOFTECH might hold stock in: the branches, the HQ stores,
    the setting's stores and ``extra_stores``. Quarantine stores are included (owner, 2026-11-04); only
    stores whose role is closed are not."""
    from apps.branches.models import Branch
    from apps.finance.recon_labels import branch_label

    overrides = _setting_overrides()
    codes = {_code(c) for c in Branch.objects.values_list('softech_branch_id', flat=True)}
    codes |= set(STORE_BRANCH) | set(overrides) | {_code(c) for c in extra_stores}
    codes.discard('')
    role = resolver()
    out = {}
    for store in sorted(codes):
        o = overrides.get(store, {})
        branch = o.get('branch') or STORE_BRANCH.get(store, store)
        included = o['included'] if 'included' in o else role(branch, store) != CLOSED
        out[store] = StoreRule(branch, included, branch_label(branch))
    return out


def store_label(code: str) -> str:
    """A store that is its branch: the branch label says it all; an HQ store: the label is the branch, so keep the code."""
    rule = store_map([code])[code]
    return rule.label if rule.branch_code == code else f'{code} ({rule.label})'


class _Snapshots:
    """One valuation's reads of SOFTECH, each made once: the snapshot index and the storebal_date dates."""

    def __init__(self):
        self._dates = None
        self._rows = {}

    def dates_by_store(self) -> dict:
        if self._dates is None:
            by = {}
            for r in _sybase_gl().storebal_snapshots():
                by.setdefault(_code(r['storecode']), set()).add(_day(r['storebaldate']))
            self._dates = by
        return self._dates

    def stores_on(self, day: date) -> set:
        return {s for s, ds in self.dates_by_store().items() if day in ds}

    def rows_on(self, day: date) -> dict:
        if day not in self._rows:
            self._rows[day] = {r.store_code: r for r in read_storebal(day)}
        return self._rows[day]

    def expected(self, included) -> set:
        """Included stores whose last non-empty snapshot (any date) had a non-zero value."""
        by = self.dates_by_store()
        pending = {s for s in included if s in by}
        out = set()
        for day in sorted({d for s in pending for d in by[s]}, reverse=True):
            if not pending:
                break
            here = self.rows_on(day)
            for s in sorted(pending):
                if day in by[s] and here.get(s) and here[s].rows:
                    pending.discard(s)
                    if here[s].value != 0:
                        out.add(s)
        return out


def _included_stores(smap) -> set:
    return {s for s, rule in smap.items() if rule.included}


def expected_stores() -> set:
    """Included stores that normally report: their last non-empty snapshot had a non-zero value."""
    snaps = _Snapshots()
    smap = store_map(snaps.dates_by_store())
    return snaps.expected(_included_stores(smap))


def _carry_until() -> date:
    try:
        from apps.config.models import SystemSetting
        raw = SystemSetting.get('gl_stock_carry_forward_until')
        return _day(raw) if raw else DEFAULT_CARRY_FORWARD_UNTIL
    except Exception:
        logger.warning('[GLStock] gl_stock_carry_forward_until is not a date — using the default')
        return DEFAULT_CARRY_FORWARD_UNTIL


def valuation(as_of: date) -> Valuation:
    snaps = _Snapshots()
    today = snaps.rows_on(as_of)
    ran = snaps.stores_on(as_of) | set(today)
    smap = store_map(set(snaps.dates_by_store()) | set(today))
    expected = snaps.expected(_included_stores(smap))
    names = {_code(r['storecode']): (r['storename'] or '').strip() for r in _sybase_gl().store_names()}
    carry_ok = as_of <= _carry_until()

    v = Valuation(as_of=as_of)
    entries = {}   # store -> (StoreRow | None, snapshot_date, carried)
    for store, row in today.items():
        entries[store] = (row, as_of, False)
    for store in sorted(ran - set(today)):   # report ran for the store and found nothing in it
        entries[store] = (StoreRow(store, 0, Decimal('0.00')), as_of, False)
    for store in sorted(expected - ran):
        earlier = [d for d in snaps.dates_by_store().get(store, ()) if d < as_of]
        # the latest date the store has lines on: an empty report in between would carry a false 0
        day = next((d for d in sorted(earlier, reverse=True) if store in snaps.rows_on(d)), None) if carry_ok else None
        if day is not None:
            entries[store] = (snaps.rows_on(day)[store], day, True)
            v.carried_stores.append(store)
        else:
            v.missing_stores.append(store)

    for store in sorted(entries):
        row, day, carried = entries[store]
        rule = smap[store]
        v.stores.append({
            'store_code': store, 'store_name': names.get(store, ''), 'branch_code': rule.branch_code,
            'included': rule.included, 'rows': row.rows, 'value': row.value,
            'snapshot_date': day, 'carried': carried})
        if rule.included:
            v.total += row.value
        else:
            v.excluded_total += row.value
    return v
