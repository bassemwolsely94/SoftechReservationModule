"""Runs one server plan (kind discovery / fill / history) through a PortalWebDriver and returns
the report payload for /api/rpa/agent/portal/runs/<id>/report/ (apps/rpa/portal/queue.report).

Payload keys are only those queue.report reads: outcome, steps, lines, credit, discovery,
order_ref, history_lines, orders, account. Outcome names mirror queue.py. No HTTP and no UI here: the
caller passes `on_report` (the live handover report), `say` (the overlay message) and `on_shot`.

The fill flow (spec §6.2 step 5; plan "Driver contract"):
  1. account check, then empty-cart check. A stop here reports ONLY the steps check_account /
     check_cart_empty and no lines, so the server keeps it "nothing touched" (ruling R11);
  2. add each line; on "No Enough material Stock" step down (binary search between the largest
     accepted and the smallest refused, never above the wanted qty, at most max_stepdown_tries);
  3. read back every row, then check the cart holds exactly what we added (cart_mismatch);
  4. dry_run: remove only our own codes and check the cart is empty again -> dry_run_ok;
     live: Proceed To Next Step, re-check the account (wrong_account_late), report `handover`,
     and only when the server answers status awaiting_submit tell the person to press Submit
     Order themselves, wait for the order number, read it in
     Order History and return submit_seen.
"""
from __future__ import annotations

import datetime
import re

from .driver import AmbiguousOrder, DeniedControl, LoginRequired, PortalError, canonical_sku

LOGIN_MSG = 'سجّل الدخول ثم اضغط متابعة'
LEFT_IN_CART = 'بقي %d صنف في السلة من الروبوت'
LEFT_UP_TO = 'قد يكون بقي حتى %d صنف في السلة من الروبوت'
# a dry run that stops for these leaves the cart alone: it is not (only) the robot's any more
NO_CLEANUP = ('cart_mismatch', 'cart_not_empty', 'wrong_account', 'wrong_account_late')
_URL = re.compile(r'\b[a-z][a-z0-9+.-]*://\S+', re.I)


def safe_note(exc):
    """An exception for a step note: its type and the first line of its text with any URL removed
    (a page address can carry a session id). Never the full text or a call log."""
    first = (str(exc).strip().splitlines() or [''])[0]
    return ('%s: %s' % (type(exc).__name__, _URL.sub('<url>', first)[:150])).rstrip(': ')
HANDOVER_MSG = 'راجع ثم اضغط Submit Order بنفسك'
LOGIN_WAIT_S = 5 * 60
ORDER_WAIT_S = 60 * 60          # the heartbeat keeps the lease while the person decides
MAX_RELOGINS = 3
MAX_ORDERS = 50                 # orders one history report carries (the server reads as many)


class _Halt(Exception):
    def __init__(self, outcome):
        super().__init__(outcome)
        self.outcome = outcome


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def handed_over(answer):
    """The server's answer to the handover report says the basket waits for Submit."""
    return isinstance(answer, dict) and answer.get('status') == 'awaiting_submit'


def _same(a, b):
    return ' '.join(str(a or '').split()).casefold() == ' '.join(str(b or '').split()).casefold()


def classify(recipe, text):
    """The meaning of a banner per recipe.MESSAGES ('' when none matches or there is no text)."""
    for pattern, meaning in recipe.MESSAGES.items():
        if text and re.search(pattern, text, re.I):
            return meaning
    return ''


class _Run:

    def __init__(self, plan, driver, stop, on_step, on_shot, say, login_wait_s):
        self.plan, self.d, self.stop = plan, driver, stop
        self.on_step, self.on_shot, self.say = on_step, on_shot, say
        self.login_wait_s = login_wait_s
        self.recipe = driver.recipe
        self.steps, self.sent_steps = [], 0
        self.lines = None          # the answers, in plan order (the report's "lines")
        self.done = []             # (canonical sku, answer) for the lines finished so far
        self.added = set()         # every code the robot may have put in the cart (incl. in flight)
        self.credit = None
        self.seen = None
        self.started = datetime.datetime.now()

    # ── bookkeeping ───────────────────────────────────────────────────────────────────────

    def rec(self, label, ok, note=''):
        s = {'i': len(self.steps), 'label': label, 'at': _now(), 'ok': bool(ok), 'note': str(note)[:300]}
        self.steps.append(s)
        if self.on_step:
            self.on_step(s)
        return s

    def shot(self):
        if not self.on_shot:
            return
        try:
            self.on_shot(max(len(self.steps) - 1, 0), self.d.screenshot())
        except Exception:      # noqa: BLE001 - a missing picture never stops the run
            pass

    def payload(self, outcome, **extra):
        """The report; steps are only those not yet sent (the server appends each report's steps)."""
        out = {'outcome': outcome, 'steps': self.steps[self.sent_steps:]}
        if self.seen is not None:
            out['account'] = {'identity_text': self.seen}
        if self.credit:
            out['credit'] = self.credit
        if self.lines:
            out['lines'] = self.lines
        out.update(extra)
        return out

    def halt_if_stopped(self):
        if self.stop.is_set():
            self.rec('stop', False, 'stopped_by_operator')
            raise _Halt('stopped_by_operator')

    def tell(self, text):
        if self.say:
            try:
                self.say(text)
            except Exception:  # noqa: BLE001 - the overlay is a courtesy, not a control
                pass

    # ── login ─────────────────────────────────────────────────────────────────────────────

    def wait_login(self):
        """The person logs in by hand; up to login_wait_s. Not a step (pre-cart reports carry
        only check_account / check_cart_empty)."""
        self.tell(LOGIN_MSG)
        if not self.d.ensure_logged_in(self.login_wait_s):
            self.rec('login', False, 'login page still shown')
            raise _Halt('login_required_timeout')

    def start(self):
        try:
            if self.d.ensure_logged_in(0):
                return
        except LoginRequired:
            pass
        self.wait_login()

    def check_account(self, label='check_account', outcome='wrong_account'):
        self.seen = self.d.account_identity()
        want = (self.plan.get('account') or {}).get('identity_text')
        if not want or not _same(self.seen, want):
            self.rec(label, False, 'account on screen differs from the job account')
            self.shot()
            raise _Halt(outcome)
        self.rec(label, True)

    def read_credit(self):
        try:
            credit = self.d.credit()
        except Exception:      # noqa: BLE001 - credit is information only
            return
        if any(credit.values()):
            self.credit = credit

    # ── fill ──────────────────────────────────────────────────────────────────────────────

    def pre_cart(self):
        for _ in range(MAX_RELOGINS):
            try:
                self.steps = []
                self.check_account()
                self.read_credit()
                cart = self.d.cart_lines()
                if cart:
                    self.rec('check_cart_empty', False, 'cart has %d row(s)' % len(cart))
                    self.shot()
                    raise _Halt('cart_not_empty')
                self.rec('check_cart_empty', True)
                return
            except LoginRequired:
                self.wait_login()
        self.rec('login', False, 'login page keeps returning')
        raise _Halt('login_required_timeout')

    def relogin(self):
        """The login page showed mid-run. After the person logs in, the account must be the same
        and (in a fill) the cart must hold exactly the lines finished so far, or a person takes over."""
        self.rec('login_mid_run', False, 'login page shown')
        self.wait_login()
        if self.lines is None:            # discovery / history: no cart to check
            if (self.plan.get('account') or {}).get('identity_text'):
                self.check_account('check_account_again', 'wrong_account')
            else:
                self.read_account()
            return
        self.check_account('check_account_again', 'wrong_account_late')
        self.check_cart(self.done, 'check_cart_after_login')

    @staticmethod
    def expected(done):
        return {sku: ans['accepted_qty'] for sku, ans in done if ans['accepted_qty'] > 0}

    def check_cart(self, done, label='check_cart'):
        want = self.expected(done)
        have = {}
        for row in self.d.cart_lines():
            have[row['sku']] = have.get(row['sku'], 0) + (row['qty'] if isinstance(row['qty'], int) else -1)
        if have != want:
            extra = sorted(set(have) - set(want))
            missing = sorted(set(want) - set(have))
            changed = sorted(k for k in set(have) & set(want) if have[k] != want[k])
            self.rec(label, False, 'extra %s missing %s qty %s' % (extra, missing, changed))
            self.shot()
            raise _Halt('cart_mismatch')
        self.rec(label, True)

    def in_cart(self, sku):
        return any(r['sku'] == sku for r in self.d.cart_lines())

    def unknown(self, label, text):
        self.rec(label, False, 'unknown message: %s' % (text or 'no message'))
        self.shot()
        raise _Halt('unknown_message')

    def add_one(self, line):
        """Add one plan line, stepping down on "No Enough material Stock". Returns its answer."""
        sku_p = str(line.get('sku_padded') or line.get('sku') or '')
        sku = canonical_sku(line.get('sku') or sku_p)
        want = int(line.get('qty') or 0)
        tries_max = int(self.plan.get('max_stepdown_tries') or 0)
        ans = {'line_id': line.get('line_id'), 'accepted_qty': 0, 'status': 'out', 'message': ''}
        if not sku or want <= 0:
            self.rec('add_line', False, 'line %s: no code or qty' % line.get('line_id'))
            ans['status'] = 'not_found'
            return ans
        self.added.add(sku)            # in flight from here: a halt cleans it up (dry run)
        text = self.d.add_line(sku_p, want)
        meaning = classify(self.recipe, text)
        ans['message'] = text[:255]
        if meaning == 'added':
            self.rec('add_line', True, 'line %s: %d' % (ans['line_id'], want))
            return dict(ans, accepted_qty=want, status='ok')
        if meaning == 'merged':        # the cart was empty: someone else is using it
            self.rec('add_line', False, 'line %s: %s' % (ans['line_id'], text))
            self.shot()
            raise _Halt('cart_mismatch')
        if meaning not in ('short', 'out'):
            self.unknown('add_line', text)
        if self.in_cart(sku):
            self.rec('add_line', False, 'line %s refused but in cart' % ans['line_id'])
            self.shot()
            raise _Halt('cart_mismatch')
        if meaning == 'out':
            self.rec('add_line', True, 'line %s: out' % ans['line_id'])
            return ans
        self.rec('add_line', True, 'line %s: %d short' % (ans['line_id'], want))
        lo, hi, tries, in_cart = 0, want, 0, False
        while hi - lo > 1 and tries < tries_max:
            self.halt_if_stopped()
            q = (lo + hi) // 2
            if in_cart:
                self.d.remove_line(sku)
                in_cart = False
            tries += 1
            text = self.d.add_line(sku_p, q)
            meaning = classify(self.recipe, text)
            if meaning == 'added':
                lo, in_cart = q, True
            elif meaning in ('short', 'out'):
                if self.in_cart(sku):
                    self.rec('stepdown', False, 'line %s: refused %d but in cart' % (ans['line_id'], q))
                    self.shot()
                    raise _Halt('cart_mismatch')
                hi = q
                if meaning == 'out':
                    lo = 0
                    break
            else:
                self.unknown('stepdown', text)
            self.rec('stepdown', True, 'line %s: %d %s' % (ans['line_id'], q, meaning))
        if lo > 0 and not in_cart:     # the last probe was refused: put the best one back
            text = self.d.add_line(sku_p, lo)
            meaning = classify(self.recipe, text)
            if meaning != 'added':
                if meaning not in ('short', 'out'):
                    self.unknown('stepdown', text)
                lo = 0
            self.rec('stepdown', True, 'line %s: %d again %s' % (ans['line_id'], lo, meaning or 'added'))
        if lo > 0:
            return dict(ans, accepted_qty=lo, status='short', message=ans['message'])
        return ans

    def read_back(self):
        rows = {r['sku']: r for r in self.d.read_rows()}
        for ans, line in zip(self.lines, self.plan_lines):
            row = rows.get(canonical_sku(line.get('sku') or line.get('sku_padded')))
            if row is None:
                continue
            ans.update({'price': row['price'], 'discount_pct': row['discount_pct'],
                        'bonus_text': row['bonus_text'], 'supplier_expiry': row['expiry'],
                        'supplier_name_seen': row['name']})
        self.rec('read_back', True, '%d row(s)' % len(rows))

    def fill(self, on_report, order_wait_s):
        self.start()
        self.pre_cart()
        self.plan_lines = [ln for ln in (self.plan.get('lines') or []) if isinstance(ln, dict)]
        self.lines = []
        logins = 0
        for line in self.plan_lines:
            while True:
                self.halt_if_stopped()
                try:
                    ans = self.add_one(line)
                    self.done.append((canonical_sku(line.get('sku') or line.get('sku_padded')), ans))
                    self.lines.append(ans)
                    break
                except LoginRequired:
                    logins += 1
                    if logins > MAX_RELOGINS:
                        raise _Halt('login_required_timeout')
                    self.relogin()
                    if self.in_cart(canonical_sku(line.get('sku') or line.get('sku_padded'))):
                        self.rec('check_cart_after_login', False, 'line %s state unknown' % line.get('line_id'))
                        raise _Halt('cart_mismatch')
        self.halt_if_stopped()
        self.with_login(self.read_back)
        self.with_login(lambda: self.check_cart(self.done))
        if self.plan.get('mode') == 'live':
            return self.live(on_report, order_wait_s)
        self.review()                  # ruling R13: read-only, as in a live run (spec §6.2 5.6)
        for sku in self.expected(self.done):
            self.with_login(lambda s=sku: self.d.remove_line(s))   # goes back to quick order first
            self.rec('remove_line', True, sku)
        self.with_login(lambda: self.check_cart([], 'check_cart_empty_after'))
        return self.payload('dry_run_ok')

    def review(self):
        """Proceed To Next Step and read the totals, the account and the credit. Nothing is pressed
        there (driver._click refuses every control on the review page)."""
        self.halt_if_stopped()
        totals = self.with_login(self.d.go_review)
        self.rec('go_review', True, ' '.join('%s=%s' % kv for kv in totals.items()))
        self.check_account('check_account_review', 'wrong_account_late')
        self.read_credit()

    def cleanup(self):
        """A dry run halted after adding: remove the robot's own codes (done and in flight), only
        when the cart holds nothing else and the finished lines still have the quantities the
        robot left. Otherwise touch nothing and say how many robot lines remain."""
        seen = None                    # robot lines last seen in the cart (None: never read)
        try:
            have = {}
            for row in self.d.cart_lines():
                have[row['sku']] = row['qty']
            mine = sorted(s for s in have if s in self.added)
            seen = len(mine)
            if not mine:
                self.rec('cleanup', True, 'cart already clear of robot lines')
                return
            done = self.expected(self.done)
            finished = {sku for sku, _ in self.done}
            foreign = [s for s in have if s not in self.added
                       or (s in finished and have[s] != done.get(s))]
            if foreign:
                self.rec('cleanup', False, (LEFT_IN_CART % len(mine)) + ' - cart changed, not touched')
                return
            for sku in mine:
                self.d.remove_line(sku)
                seen -= 1
            left = [r['sku'] for r in self.d.cart_lines() if r['sku'] in self.added]
            if left:
                self.rec('cleanup', False, LEFT_IN_CART % len(left))
            else:
                self.rec('cleanup', True, 'removed %d robot line(s)' % len(mine))
        except Exception as e:  # noqa: BLE001 - a failed clean-up is reported, never raised
            # the cart was never read: the robot touched at most len(added) codes ("up to")
            left = LEFT_IN_CART % seen if seen is not None else LEFT_UP_TO % len(self.added)
            self.rec('cleanup', False, '%s (%s)' % (left, safe_note(e)))

    def with_login(self, fn):
        for _ in range(MAX_RELOGINS):
            try:
                return fn()
            except LoginRequired:
                self.relogin()
        raise _Halt('login_required_timeout')

    def live(self, on_report, order_wait_s):
        self.review()
        self.shot()
        old_refs = self.d.visible_order_numbers()          # an old Thank You tab is not this order
        handover = self.payload('handover')
        try:
            answer = on_report(handover) if on_report else None
        except Exception:      # noqa: BLE001 - not handed over: nobody is told to press Submit
            answer = None
        # only the server's own "awaiting_submit" is a handover: a retried report whose first try
        # did arrive is refused there (handover_twice), and then nobody is told to press Submit
        if not handed_over(answer):
            self.rec('handover', False, 'handover not confirmed by the server (%s)'
                     % ((answer or {}).get('status') if isinstance(answer, dict) else 'no answer'))
            try:
                self.d.goto('quick_order')         # leave the review page
            except Exception:  # noqa: BLE001 - best effort; the error report still goes
                pass
            return self.payload('error')
        self.sent_steps = len(self.steps)
        self.tell(HANDOVER_MSG)
        self.rec('handover', True)
        try:
            ref = self.d.wait_order_number(order_wait_s, stop=self.stop, ignore=old_refs)
        except AmbiguousOrder as e:
            # an order WAS placed but we cannot tell which number is this basket's: submit_seen
            # with no ref -> queue needs_person 'submit_seen_no_ref', submitted_seen_at set, so it
            # can only be linked to its order or cancelled by a person (never retried)
            self.rec('order_seen', False, 'more than one new order number: %s' % ', '.join(e.numbers[:5]))
            self.shot()
            return self.final('submit_seen', order_ref='')
        if not ref:
            if self.stop.is_set():
                self.rec('wait_submit', False, 'stopped_by_operator')
                return self.final('stopped_by_operator')
            self.rec('wait_submit', False, 'no order number seen')
            return self.final('timeout')
        self.rec('order_seen', True, ref)
        history = []
        try:
            for order in self.d.order_history(self.started.date(), keep_ref=ref):
                if order['order_ref'] == ref:
                    history = order['lines']
                    break
            self.rec('read_order_history', bool(history), '%d line(s)' % len(history))
        except Exception as e:  # noqa: BLE001 - the order WAS placed: report it anyway
            self.rec('read_order_history', False, type(e).__name__)
        return self.final('submit_seen', order_ref=ref, history_lines=history)

    def final(self, outcome, **extra):
        out = {'outcome': outcome, 'steps': self.steps[self.sent_steps:]}
        if self.seen is not None:
            out['account'] = {'identity_text': self.seen}
        out.update(extra)
        return out

    # ── discovery / history ───────────────────────────────────────────────────────────────

    def discovery(self):
        self.start()
        self.with_login(self.check_account)
        found = []
        for s in self.plan.get('searches') or []:
            self.halt_if_stopped()
            cands = self.with_login(lambda t=s.get('term'): self.d.search(str(t or '')))
            self.rec('search', True, '%s: %d' % (s.get('buyline_id'), len(cands)))
            found.append({'buyline_id': s.get('buyline_id'), 'candidates': cands})
        return self.payload('discovery_ok', discovery=found)

    def read_account(self):
        """A history plan carries no account (apps/rpa/portal/plans.history_plan): the identity on
        screen goes in the report and the server compares it (wrong_account)."""
        self.seen = self.d.account_identity()
        self.rec('read_account', bool(self.seen))

    def history(self):
        self.start()
        self.with_login(self.read_account)
        since = datetime.datetime.fromisoformat(str(self.plan['since'])).date()
        want = str(self.plan.get('order_ref') or '')
        orders = self.with_login(lambda: self.d.order_history(since, keep_ref=want or None))[:MAX_ORDERS]
        self.rec('read_order_history', True, 'since %s: %s' % (since, [o['order_ref'] for o in orders][:20]))
        if not orders:
            return self.payload('history_none')
        # every order in the window: the server decides which one (if any) is this basket's - the
        # newest one is often another basket's order on the same account
        extra = {'orders': [{'order_ref': o['order_ref'], 'date': o.get('date', ''), 'lines': o['lines']}
                            for o in orders]}
        match = next((o for o in orders if want and o['order_ref'] == want), None)
        if match is not None:
            extra.update(order_ref=match['order_ref'], history_lines=match['lines'])
        return self.payload('history_found', **extra)


def run_plan(plan, driver, *, stop, on_step=None, on_shot=None, say=None, on_report=None,
             login_wait_s=LOGIN_WAIT_S, order_wait_s=ORDER_WAIT_S):
    """Run one plan; returns the report payload. Never raises."""
    run = _Run(plan if isinstance(plan, dict) else {}, driver, stop, on_step, on_shot, say, login_wait_s)
    kind = run.plan.get('kind')
    try:
        if kind == 'fill':
            if run.plan.get('mode') not in ('dry_run', 'live'):
                run.rec('mode', False, 'unknown mode')
                return run.payload('error')
            return run.fill(on_report, order_wait_s)
        if kind == 'discovery':
            return run.discovery()
        if kind == 'history':
            return run.history()
        run.rec('plan', False, 'unknown plan kind')
        return run.payload('error')
    except _Halt as h:
        outcome = h.outcome
    except DeniedControl as e:
        run.rec('denied', False, safe_note(e))
        run.shot()
        outcome = 'error'
    except (PortalError, LoginRequired, Exception) as e:  # noqa: BLE001 - reported, never raised
        run.rec('agent', False, safe_note(e))
        run.shot()
        outcome = 'error'
    if kind == 'fill' and run.plan.get('mode') == 'dry_run' and run.added and outcome not in NO_CLEANUP:
        run.cleanup()
    return run.payload(outcome) if run.sent_steps == 0 else run.final(outcome)
