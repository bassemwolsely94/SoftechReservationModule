"""Playwright driver for the Pharma Overseas website, in a persistent browser profile.

Hard rules, enforced here whatever the plan says (the server's plan cannot override them):
  * every click goes through _click: a control whose name or text matches recipe.DENY (Submit
    Order, Submit Return, Recurring order, Sign Out) raises DeniedControl, and so does any control
    not on recipe.ALLOW (or an Order History order number). A person presses Submit, never this code;
  * every typed value goes through _fill, which refuses a password field: the operator logs in by
    hand in this same browser, and the robot never types, stores or logs a password, cookie or token;
  * the robot never presses Enter in a field (a form could submit on Enter);
  * elements are found by role / label / text only, never by screen coordinates.

Playwright is imported lazily, so the rest of the agent works on a PC without it.
"""
from __future__ import annotations

import datetime
import re
import time

from . import recipe_pharma_overseas as default_recipe

MAX_SHOT_BYTES = 2 * 1024 * 1024


class DeniedControl(RuntimeError):
    """The robot was asked to press a control it never presses, or to type into a password field."""


class LoginRequired(RuntimeError):
    """The site shows its login page: a person must log in."""


class PortalError(RuntimeError):
    """The page is not what the recipe expects (a missing table, a row that did not go)."""


class AmbiguousOrder(RuntimeError):
    """More than one new order number showed: which one is this basket's, a person decides."""

    def __init__(self, numbers):
        super().__init__('more than one new order number')
        self.numbers = list(numbers)


def _norm(s):
    return ' '.join(str(s or '').split())


def canonical_sku(raw):
    """Digits only, leading zeros stripped (apps/rpa/portal/skus.canonical_sku); '' otherwise."""
    s = str(raw or '').strip().replace(' ', '')
    if s.upper().startswith('ID'):
        s = s[2:].strip()
    return s.lstrip('0') if s.isdigit() else ''


def parse_number(text):
    """'1,250.50' -> '1250.50' (kept as text, the server parses it); '' when there is none."""
    m = re.search(r'-?\d[\d,]*(?:\.\d+)?', str(text or ''))
    return m.group(0).replace(',', '') if m else ''


def parse_qty(text):
    """A whole quantity as int ('4', '4.000' -> 4); otherwise the text as shown (the server
    sends an unreadable quantity to a person, never reads it as "not ordered")."""
    n = parse_number(text)
    try:
        f = float(n)
    except ValueError:
        return _norm(text)
    return int(f) if f.is_integer() and f >= 0 else _norm(text)


_DMY = re.compile(r'^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$')


def parse_date(text, formats, strict=False):
    """The date in the recipe's formats (first match wins), or None.

    strict=True (the Order History filter only): A/B/YYYY with both parts 12 or less (and not
    equal) is None: 05/11 may be 5 November or May 11, and a wrong guess could drop the very
    order a history read looks for. Cart expiries are read with the recipe's pinned format
    (not strict), so 01/03/2027 stays 1 March 2027 and short_expiry still flags it."""
    s = _norm(text)
    m = _DMY.match(s)
    if strict and m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1).lstrip('0') != m.group(2).lstrip('0'):
        return None
    for fmt in formats:
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


_JS_NAME = """el => [el.getAttribute('aria-label') || '', el.innerText || el.textContent || '',
                     el.value || '', el.title || '',
                     (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)
                       .map(id => (document.getElementById(id) || {}).textContent || '').join(' ')]"""
_JS_FIELD = """el => ({tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
                      auto: (el.getAttribute('autocomplete') || '').toLowerCase()})"""
_JS_TABLE = """t => {
  const head = Array.from(t.querySelectorAll('thead th, thead td')).map(c => c.innerText.trim());
  const rows = Array.from(t.querySelectorAll('tbody tr')).map(r => Array.from(r.cells).map(c => {
    const i = c.querySelector('input, select');
    return i ? String(i.value) : c.innerText.trim();
  }));
  return {head, rows};
}"""


class PortalWebDriver:

    def __init__(self, profile_dir, *, recipe=None, headless=False, timeout_ms=15000, channel=None,
                 executable_path=None):
        self.profile_dir = str(profile_dir)
        # channel "msedge" / "chrome" drives that installed browser instead of Playwright's Chromium
        self.launch = {k: v for k, v in (('channel', channel), ('executable_path', executable_path)) if v}
        self.recipe = recipe or default_recipe
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self.context = None
        self._page = None
        self._deny = [re.compile(re.escape(d), re.I) for d in self.recipe.DENY]
        self._allow = {_norm(a).casefold() for a in self.recipe.ALLOW}
        self._order_link = re.compile(self.recipe.ORDER_LINK)

    # ── browser ───────────────────────────────────────────────────────────────────────────

    def start(self):
        if self.context is not None:
            return self
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            self.profile_dir, headless=self.headless, accept_downloads=False, **self.launch)
        self.context.set_default_timeout(self.timeout_ms)
        return self

    def close(self):
        try:
            if self.context is not None:
                self.context.close()
        finally:
            self.context = None
            self._page = None
            if self._pw is not None:
                self._pw.stop()
                self._pw = None

    @property
    def page(self):
        """The robot's own tab (the first one). A tab the person opens is never driven."""
        self.start()
        if self._page is None or self._page.is_closed():
            pages = [p for p in self.context.pages if not p.is_closed()]
            self._page = pages[0] if pages else self.context.new_page()
        return self._page

    def url(self, key):
        return self.recipe.BASE_URL + self.recipe.PATHS[key]

    def goto(self, key):
        self.page.goto(self.url(key))
        self._check_login()

    def _on_quick_order(self):
        if self.recipe.PATHS['quick_order'] not in self.page.url:
            self.goto('quick_order')
        self._check_login()

    def is_login_page(self):
        page = self.page
        if self.recipe.LOGIN_PATH_HINT in page.url:
            return True
        try:
            return page.locator('input[type=password]').count() > 0
        except Exception:      # noqa: BLE001 - a page mid-navigation is read again later
            return False

    def _check_login(self):
        if self.is_login_page():
            raise LoginRequired()

    # ── the guarded primitives ────────────────────────────────────────────────────────────

    def _click(self, locator):
        """Press one control, after the deny-list and allow-list checks. The element checked is
        the element clicked (one handle, not a second lookup). Nothing is pressed on the review
        page at all: Submit Order lives there, and any submit button of its form could send it."""
        if self.recipe.PATHS['place_order'] in self.page.url:
            raise DeniedControl('nothing is pressed on the review page')
        handle = locator.element_handle()
        names = [n for n in (_norm(x) for x in handle.evaluate(_JS_NAME)) if n]
        for n in names:
            if any(d.search(n) for d in self._deny):
                raise DeniedControl('denied control: %s' % n[:60])
        if not any(n.casefold() in self._allow or self._order_link.match(n) for n in names):
            raise DeniedControl('control not on the allow list: %s' % (names[0][:60] if names else '?'))
        handle.click()

    def _fill(self, locator, value):
        """Type a value; never into a password field and never on the login page."""
        handle = locator.element_handle()
        f = handle.evaluate(_JS_FIELD)
        if f['type'] == 'password' or 'password' in f['auto']:
            raise DeniedControl('never types into a password field')
        if self.is_login_page():
            raise DeniedControl('never types on the login page')
        handle.fill(str(value))

    def _label(self, name):
        return self.page.get_by_label(name, exact=True)

    def _text_of(self, name):
        loc = self._label(name)
        return _norm(loc.first.inner_text()) if loc.count() else ''

    # ── reads ─────────────────────────────────────────────────────────────────────────────

    def ensure_logged_in(self, timeout_s, wake=None):
        """True once the quick order page shows without a login form; waits up to timeout_s
        for the operator to log in by hand. Never touches the login form."""
        deadline = time.monotonic() + timeout_s
        try:
            self.goto('quick_order')
            return True
        except LoginRequired:
            pass
        while time.monotonic() < deadline:
            if wake is not None and wake.wait(2):
                wake.clear()
            else:
                time.sleep(min(2, max(0.0, deadline - time.monotonic())))
            if not self.is_login_page():
                try:
                    self.goto('quick_order')
                    return True
                except LoginRequired:
                    continue
        return False

    def account_identity(self):
        return self._text_of(self.recipe.ACCOUNT_LABEL)

    def credit(self):
        return {k: self._text_of(label) for k, label in self.recipe.CREDIT_LABELS.items()}

    def _table(self, name):
        loc = self.page.get_by_role('table', name=name, exact=True)
        if not loc.count():
            raise PortalError('table not found: %s' % name)
        return loc.first

    def _read_table(self, name, columns):
        data = self._table(name).evaluate(_JS_TABLE)
        index = {i: columns[h] for i, h in enumerate(data['head']) if h in columns}
        return [{key: (row[i] if i < len(row) else '') for i, key in index.items()} for row in data['rows']]

    def read_rows(self):
        """Every cart row: sku (canonical), name, qty (int or None), price, discount_pct,
        bonus_text, expiry (YYYY-MM-DD or the text as shown)."""
        self._on_quick_order()
        out = []
        for row in self._read_table(self.recipe.CART_TABLE, self.recipe.CART_COLUMNS):
            qty = parse_qty(row.get('qty'))
            exp = parse_date(row.get('expiry'), self.recipe.DATE_FORMATS)
            out.append({'sku': canonical_sku(row.get('sku')), 'name': _norm(row.get('name')),
                        'qty': qty if isinstance(qty, int) else None,
                        'price': parse_number(row.get('price')),
                        'discount_pct': parse_number(row.get('discount_pct')),
                        'bonus_text': _norm(row.get('bonus_text')),
                        'expiry': exp.isoformat() if exp else _norm(row.get('expiry'))})
        return out

    def cart_lines(self):
        return [{'sku': r['sku'], 'qty': r['qty']} for r in self.read_rows()]

    def banners(self):
        return [_norm(t) for t in self.page.get_by_role('alert').all_inner_texts() if _norm(t)]

    # ── cart actions ──────────────────────────────────────────────────────────────────────

    def _act_and_read_banner(self, action, wait_s=None):
        """Run `action`, then return the banner it produced ('' when none showed)."""
        page = self.page
        alerts = page.get_by_role('alert')
        before = alerts.element_handles()
        before_texts = [_norm(h.inner_text()) for h in before]
        action()
        deadline = time.monotonic() + (wait_s if wait_s is not None else self.timeout_ms / 1000)
        while time.monotonic() < deadline:
            self._check_login()
            now = alerts.element_handles()
            fresh = [h for h in now if not h.evaluate('(el, olds) => olds.includes(el)', before)]
            texts = [_norm(h.inner_text()) for h in (fresh or now)]
            if fresh and any(texts):
                return ' | '.join(t for t in texts if t)
            if not fresh and [_norm(h.inner_text()) for h in now] != before_texts and any(texts):
                return ' | '.join(t for t in texts if t)
            page.wait_for_timeout(100)
        return ''

    def add_line(self, sku_padded, qty):
        """Quick order: type the code and quantity, press Add to cart. Returns the banner text."""
        self._on_quick_order()
        r = self.recipe
        self._fill(self._label(r.SKU_FIELD), sku_padded)
        self._fill(self._label(r.QTY_FIELD), int(qty))
        return self._act_and_read_banner(
            lambda: self._click(self.page.get_by_role('button', name=r.ADD_BUTTON, exact=True)))

    def _row(self, sku):
        """The cart row locator for a code (padded or not)."""
        want = canonical_sku(sku)
        table = self._table(self.recipe.CART_TABLE)
        rows = table.locator('tbody').get_by_role('row')
        for i, r in enumerate(self.read_rows()):
            if r['sku'] == want:
                return rows.nth(i)
        return None

    def set_qty(self, sku, qty):
        self._on_quick_order()
        row = self._row(sku)
        if row is None:
            raise PortalError('row not in cart: %s' % canonical_sku(sku))
        self._fill(row.get_by_label(self.recipe.ROW_QTY_FIELD, exact=True), int(qty))
        return self._act_and_read_banner(
            lambda: self._click(row.get_by_role('button', name=self.recipe.UPDATE_BUTTON, exact=True)))

    def remove_line(self, sku):
        self._on_quick_order()
        row = self._row(sku)
        if row is None:
            return
        self._click(row.get_by_role('button', name=self.recipe.REMOVE_BUTTON, exact=True))
        want = canonical_sku(sku)
        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline:
            if all(r['sku'] != want for r in self.read_rows()):
                return
            self.page.wait_for_timeout(100)
        raise PortalError('row did not go: %s' % want)

    def go_review(self):
        """Proceed To Next Step, then read the review page totals."""
        self._on_quick_order()
        r = self.recipe
        self._click(self.page.get_by_role('link', name=r.PROCEED, exact=True).or_(
            self.page.get_by_role('button', name=r.PROCEED, exact=True)).first)
        self.page.wait_for_url('**/*%s*' % r.PATHS['place_order'])
        self._check_login()
        return {k: parse_number(self._text_of(label)) for k, label in r.TOTAL_LABELS.items()}

    # ── discovery ─────────────────────────────────────────────────────────────────────────

    def search(self, term):
        """Search by name; the top candidates as {name, sku (18 digits), price, stock_mark}."""
        self._on_quick_order()
        r = self.recipe
        self._fill(self._label(r.SEARCH_FIELD), term)
        results = self.page.get_by_role('list', name=r.SEARCH_RESULTS, exact=True)
        before = results.inner_text() if results.count() else None
        self._click(self.page.get_by_role('button', name=r.SEARCH_BUTTON, exact=True))
        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline and results.count() and results.inner_text() == before and before:
            self.page.wait_for_timeout(100)
        out = []
        for text in results.get_by_role('listitem').all_inner_texts()[:r.SEARCH_TOP]:
            m = re.search(r'\bID\s*(\d{6,})', text)
            if not m:
                continue
            name = _norm(text[:m.start()])
            price = re.search(r'PH\.?\s*Price\s*([\d,]+(?:\.\d+)?)', text, re.I)
            out.append({'name': name, 'sku': m.group(1),
                        'price': parse_number(price.group(1)) if price else '',
                        'stock_mark': bool(re.search(r'Out Of Stock', text, re.I))})
        return out

    # ── after the handover ────────────────────────────────────────────────────────────────

    def visible_order_numbers(self):
        """Order numbers shown on the robot's own tab (where Submit is pressed), in page order.
        Tabs the person opens are never read: an old order's page there is not this order."""
        pattern = next((re.compile(k, re.I) for k, v in self.recipe.MESSAGES.items() if v == 'order_ref'))
        try:
            text = self.page.locator('body').inner_text(timeout=1000)
        except Exception:              # noqa: BLE001 - a page mid-navigation is read next round
            return []
        return list(dict.fromkeys(pattern.findall(text)))

    def wait_order_number(self, timeout_s, stop=None, ignore=()):
        """The order number from the "Thank You … order number # N" answer, on any open tab,
        within timeout_s (None when it never shows or `stop` is set). Numbers in `ignore` (already
        on screen before the handover) are not this order. More than one new number raises
        AmbiguousOrder: the robot never picks one. Read only."""
        deadline = time.monotonic() + timeout_s
        while True:
            fresh = [n for n in self.visible_order_numbers() if n not in set(ignore)]
            if len(fresh) > 1:
                raise AmbiguousOrder(fresh)
            if fresh:
                return fresh[0]
            if (stop is not None and stop.is_set()) or time.monotonic() >= deadline:
                return None
            time.sleep(0.5)

    def order_history(self, since, keep_ref=None):
        """Orders placed on or after `since` (a date), newest first as listed, each
        {order_ref, date, lines: [{sku, qty}]} read from its details. A row whose date cannot be
        read for sure is kept (it may be the one we look for), and so is the row `keep_ref`
        whatever its date."""
        r = self.recipe
        self.goto('order_history')
        rows = self._read_table(r.HISTORY_TABLE, r.HISTORY_COLUMNS)
        wanted = []
        for row in rows:
            ref = _norm(row.get('order_ref'))
            day = parse_date(row.get('date'), r.DATE_FORMATS, strict=True)
            if ref and (ref == keep_ref or day is None or day >= since):
                wanted.append((ref, day))
        out = []
        for ref, day in wanted:
            self.goto('order_history')
            self._click(self._table(r.HISTORY_TABLE).get_by_role('link', name=ref, exact=True))
            details = self.page.get_by_role('table', name=r.DETAILS_TABLE, exact=True)
            details.wait_for(state='visible')
            lines = [{'sku': canonical_sku(x.get('sku')) or _norm(x.get('sku')),
                      'qty': parse_qty(x.get('qty'))}
                     for x in self._read_table(r.DETAILS_TABLE, r.DETAILS_COLUMNS)]
            out.append({'order_ref': ref, 'date': day.isoformat() if day else '', 'lines': lines})
        return out

    # ── screenshots ───────────────────────────────────────────────────────────────────────

    def screenshot(self):
        data = self.page.screenshot(type='png')
        if len(data) > MAX_SHOT_BYTES:
            data = self.page.screenshot(type='jpeg', quality=50)
        return data
