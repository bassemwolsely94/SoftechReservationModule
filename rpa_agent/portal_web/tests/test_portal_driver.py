"""Pharma Overseas web driver + plan runner, against local fixture pages only (file://).

Never opens the real supplier site: the recipe's BASE_URL is overridden to the fixtures folder.
Needs Playwright with Chromium installed; skipped otherwise.
"""
import datetime
import importlib.util
import json
import os
import pathlib
import shutil
import tempfile
import threading
import types
import unittest

from rpa_agent.portal_web import recipe_pharma_overseas as base_recipe

HAVE_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
# which browser the tests drive: unset = Playwright's bundled Chromium; "msedge" / "chrome" = that
# installed channel; anything else = a browser executable path
BROWSER = os.environ.get("RPA_PORTAL_TEST_BROWSER", "")
FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
# keys apps/rpa/portal/queue.report reads; nothing else is sent
REPORT_KEYS = {"outcome", "steps", "lines", "credit", "discovery", "order_ref", "history_lines", "account"}
PRE_CART_STEPS = {"check_account", "check_cart_empty"}
ACCOUNT = "ELREZEIKY PHARMACY 1"
SKU = "52872"


def fixture_recipe(**paths):
    r = types.SimpleNamespace(**{k: getattr(base_recipe, k) for k in dir(base_recipe) if k.isupper()})
    r.BASE_URL = FIX.as_uri() + "/"
    r.PATHS = dict(base_recipe.PATHS, quick_order="quick_order.html", place_order="review.html",
                   order_history="order_history.html")
    r.PATHS.update(paths)
    return r


def touched_cart(payload):
    """Mirror of apps/rpa/portal/queue._touched_cart (ruling R11)."""
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return True
    for s in steps:
        if not isinstance(s, dict) or s.get("label") not in PRE_CART_STEPS:
            return True
    lines = payload.get("lines")
    return not (lines is None or (isinstance(lines, list) and not lines))


def fill_plan(lines, mode="dry_run", tries=6):
    return {"kind": "fill", "basket_id": 9, "portal": "pharma_overseas", "mode": mode,
            "account": {"identity_text": ACCOUNT},
            "lines": [{"line_id": 100 + n, "sku_padded": sku.zfill(18), "sku": sku, "qty": qty}
                      for n, (sku, qty) in enumerate(lines)],
            "expect_lines": len(lines), "max_stepdown_tries": tries}


@unittest.skipUnless(HAVE_PLAYWRIGHT, "playwright not installed")
class PortalDriverTests(unittest.TestCase):

    def setUp(self):
        from rpa_agent.portal_web.driver import PortalWebDriver
        self.profile = tempfile.mkdtemp(prefix="portal-profile-")
        self.addCleanup(shutil.rmtree, self.profile, True)
        self.Driver = PortalWebDriver

    def driver(self, fx=None, **paths):
        state = {"account": ACCOUNT, "credit": {"consumption": "1,000.00", "credit": "9,000.00",
                                                 "limit": "10,000.00"},
                 "names": {SKU: "PANADOL EXTRA 24 TAB", "60634": "CONGESTAL 20 TAB"},
                 "stock": {}, "cart": [], "log": []}
        state.update(fx or {})
        browser = ({"channel": BROWSER} if BROWSER in ("msedge", "chrome") else
                   {"executable_path": BROWSER} if BROWSER else {})
        d = self.Driver(self.profile, recipe=fixture_recipe(**paths), headless=True, timeout_ms=3000, **browser)
        self.addCleanup(d.close)
        d.start()
        d.context.add_init_script(
            "try { if (!localStorage.getItem('fx')) localStorage.setItem('fx', %s); } catch (e) {}"
            % json.dumps(json.dumps(state)))
        return d

    def cart_view(self, d):
        """What the cart shows: every cell's text and every field's value."""
        return d.page.get_by_role("table", name="Cart").evaluate(
            "t => Array.from(t.querySelectorAll('td, th')).map("
            "c => c.innerText + '|' + Array.from(c.querySelectorAll('input')).map(i => i.value).join(','))")

    def fx(self, d):
        return json.loads(d.page.evaluate("localStorage.getItem('fx')") or "{}")

    def go(self, d, plan, **kw):
        from rpa_agent.portal_web.runner import run_plan
        self.shots, self.said, self.reports = [], [], []
        kw.setdefault("on_shot", lambda i, png: self.shots.append((i, png)))
        kw.setdefault("say", self.said.append)
        kw.setdefault("stop", threading.Event())
        kw.setdefault("on_step", None)
        result = run_plan(plan, d, **kw)
        self.assertLessEqual(set(result), REPORT_KEYS)
        return result

    # ── the deny-list ─────────────────────────────────────────────────────────────────────

    def test_deny_list_blocks_submit(self):
        from rpa_agent.portal_web.driver import DeniedControl
        d = self.driver()
        d.goto("place_order")
        for role, name in (("button", "Submit Order"), ("button", "Submit Return"), ("link", "Sign Out")):
            with self.assertRaises(DeniedControl, msg=name):
                d._click(d.page.get_by_role(role, name=name))
        self.assertIn("review.html", d.page.url)             # still on the review page
        # off the review page the names themselves are refused (any case, any element kind)
        d.goto("quick_order")
        d.page.evaluate("document.body.insertAdjacentHTML('beforeend',"
                        " '<button>submit order</button><input type=submit value=\"Submit Order\">')")
        for loc in (d.page.get_by_role("button", name="submit order", exact=True),
                    d.page.locator("input[type=submit]"), d.page.get_by_role("link", name="Sign Out")):
            with self.assertRaisesRegex(DeniedControl, "denied control"):
                d._click(loc)
        d.goto("order_history")
        with self.assertRaises(DeniedControl):
            d._click(d.page.get_by_role("button", name="Recurring order"))
        self.assertNotIn("submit", [a["a"] for a in self.fx(d)["log"]])

    def test_click_outside_allow_list_refused(self):
        from rpa_agent.portal_web.driver import DeniedControl
        d = self.driver()
        d.page.goto((FIX / "login.html").as_uri())
        with self.assertRaises(DeniedControl):
            d._click(d.page.get_by_role("button", name="Login"))

    def test_never_types_password(self):
        from rpa_agent.portal_web.driver import DeniedControl
        d = self.driver()
        d.page.goto((FIX / "login.html").as_uri())
        with self.assertRaises(DeniedControl):
            d._fill(d.page.get_by_label("Password"), "secret")
        self.assertEqual(d.page.get_by_label("Password").input_value(), "")

    # ── fill: pre-cart checks ─────────────────────────────────────────────────────────────

    def test_cart_not_empty_touches_nothing(self):
        d = self.driver(quick_order="cart_not_empty.html")
        d.goto("quick_order")
        before = self.cart_view(d)
        result = self.go(d, fill_plan([(SKU, 5)]))
        self.assertEqual(result["outcome"], "cart_not_empty")
        self.assertEqual({s["label"] for s in result["steps"]}, PRE_CART_STEPS)
        self.assertFalse(result.get("lines"))
        self.assertFalse(touched_cart(result))                # the server keeps it pre-cart
        self.assertEqual(self.cart_view(d), before)
        self.assertEqual(self.fx(d)["log"], [])
        self.assertEqual(self.fx(d)["cart"], [{"sku": "11111", "qty": 2}])

    def test_wrong_account_is_pre_cart(self):
        d = self.driver({"account": "SOMEONE ELSE"})
        result = self.go(d, fill_plan([(SKU, 5)]))
        self.assertEqual(result["outcome"], "wrong_account")
        self.assertEqual([s["label"] for s in result["steps"]], ["check_account"])
        self.assertEqual(result["account"], {"identity_text": "SOMEONE ELSE"})
        self.assertFalse(touched_cart(result))
        self.assertEqual(self.fx(d)["log"], [])

    def test_login_page_waits_then_times_out(self):
        d = self.driver(quick_order="login.html")
        result = self.go(d, fill_plan([(SKU, 5)]), login_wait_s=1)
        self.assertEqual(result["outcome"], "login_required_timeout")
        self.assertTrue(any("سجّل الدخول" in s for s in self.said))

    # ── fill: lines ───────────────────────────────────────────────────────────────────────

    def test_stepdown_finds_largest_accepted(self):
        d = self.driver({"stock": {SKU: 7}})
        result = self.go(d, fill_plan([(SKU, 20)]))
        self.assertEqual(result["outcome"], "dry_run_ok", result["steps"])
        line = result["lines"][0]
        self.assertEqual((line["line_id"], line["accepted_qty"], line["status"]), (100, 7, "short"))
        adds = [a["qty"] for a in self.fx(d)["log"] if a["a"] == "add"]
        self.assertTrue(all(q <= 20 for q in adds))
        self.assertLessEqual(len(adds) - 1, 6)                 # the first add + at most 6 tries
        self.assertEqual(self.fx(d)["cart"], [])

    def test_stepdown_all_refused_is_out(self):
        d = self.driver({"stock": {SKU: -1}})                  # the fixture refuses every quantity
        result = self.go(d, fill_plan([(SKU, 20)], tries=3))
        self.assertEqual(result["outcome"], "dry_run_ok", result["steps"])
        line = result["lines"][0]
        self.assertEqual((line["accepted_qty"], line["status"]), (0, "out"))
        self.assertEqual(len([a for a in self.fx(d)["log"] if a["a"] == "add"]), 4)
        self.assertEqual(self.fx(d)["cart"], [])

    def test_no_material_stock_is_out(self):
        d = self.driver({"stock": {SKU: 0}})
        result = self.go(d, fill_plan([(SKU, 4), ("60634", 2)]))
        self.assertEqual(result["outcome"], "dry_run_ok", result["steps"])
        self.assertEqual([(ln["status"], ln["accepted_qty"]) for ln in result["lines"]], [("out", 0), ("ok", 2)])

    def test_unknown_banner_stops(self):
        d = self.driver({"unknown": {SKU: "Material blocked for this customer"}})
        result = self.go(d, fill_plan([(SKU, 5), ("60634", 2)]))
        self.assertEqual(result["outcome"], "unknown_message")
        self.assertTrue(any("Material blocked for this customer" in s["note"] for s in result["steps"]))
        self.assertTrue(self.shots)
        self.assertEqual([a["sku"] for a in self.fx(d)["log"]], [SKU])   # nothing after the banner

    # -- a halted dry run cleans up its own lines (fix round 1, Important 1) --

    def stop_after_first_add(self, stop, then=None):
        def on_step(s):
            if s["label"] == "add_line" and s["ok"] and not stop.is_set():
                if then:
                    then()
                stop.set()
        return on_step

    def test_stop_after_first_add_removes_robot_lines(self):
        d = self.driver()
        stop = threading.Event()
        result = self.go(d, fill_plan([(SKU, 3), ("60634", 2)]), stop=stop,
                         on_step=self.stop_after_first_add(stop))
        self.assertEqual(result["outcome"], "stopped_by_operator")
        self.assertEqual(self.fx(d)["cart"], [])
        cleanup = [s for s in result["steps"] if s["label"] == "cleanup"]
        self.assertEqual([c["ok"] for c in cleanup], [True])

    def test_stop_mid_stepdown_removes_the_line_in_flight(self):
        d = self.driver({"stock": {SKU: 7}})
        stop = threading.Event()

        def on_step(s):
            if s["label"] == "stepdown" and "added" in s["note"]:
                stop.set()                                  # the line is in the cart, not yet done
        result = self.go(d, fill_plan([(SKU, 20)]), stop=stop, on_step=on_step)
        self.assertEqual(result["outcome"], "stopped_by_operator")
        self.assertEqual(self.fx(d)["cart"], [])
        self.assertTrue([s for s in result["steps"] if s["label"] == "cleanup" and s["ok"]])

    def test_error_after_first_add_removes_robot_lines(self):
        d = self.driver()
        real_add, calls = d.add_line, []

        def add_line(sku, qty):
            calls.append(sku)
            if len(calls) == 2:
                raise RuntimeError("boom at https://shop.example/x?jsessionid=SECRET\ncall log line")
            return real_add(sku, qty)
        d.add_line = add_line
        result = self.go(d, fill_plan([(SKU, 3), ("60634", 2)]))
        self.assertEqual(result["outcome"], "error")
        self.assertEqual(self.fx(d)["cart"], [])
        notes = " ".join(s["note"] for s in result["steps"])
        self.assertIn("RuntimeError: boom at <url>", notes)       # ruling R14: no URL, no call log
        self.assertNotIn("SECRET", notes)
        self.assertNotIn("call log", notes)
        self.assertTrue([s for s in result["steps"] if s["label"] == "cleanup" and s["ok"]])

    def test_cleanup_leaves_a_changed_cart_alone_and_says_so(self):
        d = self.driver()
        stop = threading.Event()

        def someone_adds():                                 # a buyer adds an item by hand
            d.page.evaluate("(() => { const fx = JSON.parse(localStorage.getItem('fx'));"
                            " fx.cart.push({sku: '99999', qty: 1});"
                            " localStorage.setItem('fx', JSON.stringify(fx)); })()")
            d.page.reload()
        result = self.go(d, fill_plan([(SKU, 3), ("60634", 2)]), stop=stop,
                         on_step=self.stop_after_first_add(stop, someone_adds))
        self.assertEqual(result["outcome"], "stopped_by_operator")
        self.assertEqual(sorted(r["sku"] for r in self.fx(d)["cart"]), [SKU, "99999"])
        cleanup = [s for s in result["steps"] if s["label"] == "cleanup"]
        self.assertEqual(cleanup[0]["ok"], False)
        self.assertIn("بقي 1 صنف في السلة من الروبوت", cleanup[0]["note"])

    def test_cleanup_error_counts_only_lines_seen_in_the_cart(self):
        d = self.driver({"stock": {SKU: 0}})                # line 1 is out: never in the cart
        stop = threading.Event()

        def broken_remove(sku):
            raise RuntimeError("remove failed")

        def on_step(s):
            if s["label"] == "add_line" and s["note"] == "line 101: 2":     # 60634 is in the cart
                d.remove_line = broken_remove
                stop.set()
        result = self.go(d, fill_plan([(SKU, 4), ("60634", 2), ("11111", 1)]), stop=stop, on_step=on_step)
        self.assertEqual(result["outcome"], "stopped_by_operator")
        cleanup = [s for s in result["steps"] if s["label"] == "cleanup"]
        # two codes were tried, one reached the cart: the note counts the one seen, not two
        self.assertIn("\u0628\u0642\u064a 1 \u0635\u0646\u0641", cleanup[0]["note"])
        self.assertFalse(cleanup[0]["ok"])

    def test_cart_mismatch_is_not_cleaned_up(self):
        d = self.driver()
        # the same code twice: the second add answers "already in your cart" (merged), which on
        # a cart the robot found empty means someone else uses it: no clean-up
        result = self.go(d, fill_plan([(SKU, 3), (SKU, 2)]))
        self.assertEqual(result["outcome"], "cart_mismatch")
        self.assertFalse([s for s in result["steps"] if s["label"] == "cleanup"])

    def test_expiry_day_up_to_12_is_read_with_the_recipe_format(self):
        d = self.driver({"expiry": "01/03/2027"})           # 1 March 2027, a short-dated item
        result = self.go(d, fill_plan([(SKU, 3)]))
        self.assertEqual(result["outcome"], "dry_run_ok", result["steps"])
        self.assertEqual(result["lines"][0]["supplier_expiry"], "2027-03-01")

    def test_dry_run_leaves_cart_as_found(self):
        d = self.driver()
        result = self.go(d, fill_plan([(SKU, 3), ("60634", 2)]))
        self.assertEqual(result["outcome"], "dry_run_ok", result["steps"])
        self.assertEqual(self.fx(d)["cart"], [])
        self.assertEqual([a["a"] for a in self.fx(d)["log"]], ["add", "add", "remove", "remove"])
        labels = [s["label"] for s in result["steps"]]
        # ruling R13: the review page is visited read-only before the removal
        self.assertLess(labels.index("go_review"), labels.index("remove_line"))
        self.assertIn("check_account_review", labels)
        self.assertIn("quick_order.html", d.page.url)            # back on quick order
        first = result["lines"][0]
        self.assertEqual((first["accepted_qty"], first["status"]), (3, "ok"))
        self.assertEqual(first["supplier_expiry"], "2027-06-30")
        self.assertEqual(first["price"], "12.50")
        self.assertEqual(result["credit"], {"consumption": "1,000.00", "credit": "9,000.00",
                                            "limit": "10,000.00"})
        self.assertNotIn("submit", [a["a"] for a in self.fx(d)["log"]])

    # ── live handover and the order number ────────────────────────────────────────────────

    def test_reads_order_number_from_thank_you(self):
        d = self.driver()
        d.page.goto((FIX / "thank_you.html").as_uri())
        self.assertEqual(d.wait_order_number(5), "2104322530")
        # a Thank You page already on screen before the handover is not this order
        self.assertIsNone(d.wait_order_number(1, ignore=d.visible_order_numbers()))

    def test_live_hands_over_and_reports_submit_seen(self):
        d = self.driver({"today": datetime.date.today().strftime("%d/%m/%Y")})

        def on_report(payload):
            self.reports.append(payload)
            # the person presses Submit Order themselves (not through the driver's _click)
            d.page.get_by_role("button", name="Submit Order").click()
            return True

        result = self.go(d, fill_plan([(SKU, 3)], mode="live"), on_report=on_report, order_wait_s=10)
        self.assertEqual([p["outcome"] for p in self.reports], ["handover"])
        self.assertEqual(self.reports[0]["lines"][0]["accepted_qty"], 3)
        self.assertIn("راجع ثم اضغط Submit Order بنفسك", self.said)
        self.assertEqual(result["outcome"], "submit_seen", result["steps"])
        self.assertEqual(result["order_ref"], "2104322530")
        self.assertEqual(result["history_lines"], [{"sku": SKU, "qty": 3}])

    def test_order_number_on_another_tab_is_not_this_order(self):
        d = self.driver()
        d.goto("quick_order")
        other = d.context.new_page()                        # the person opens an old order page
        other.goto((FIX / "thank_you.html").as_uri())
        self.assertIsNone(d.wait_order_number(1))

    def test_two_new_order_numbers_go_to_a_person(self):
        from rpa_agent.portal_web.driver import AmbiguousOrder
        d = self.driver()
        d.page.goto((FIX / "thank_you.html").as_uri())
        d.page.evaluate("document.body.insertAdjacentHTML('beforeend', '<p>Your order number # 2104322599</p>')")
        with self.assertRaises(AmbiguousOrder):
            d.wait_order_number(1)
        d.page.goto((FIX / "quick_order.html").as_uri())

        def on_report(payload):
            d.page.get_by_role("button", name="Submit Order").click()
            d.page.wait_for_url("**/thank_you.html")
            d.page.evaluate("document.body.insertAdjacentHTML('beforeend',"
                            " '<p>Your order number # 2104322599</p>')")
            return True
        result = self.go(d, fill_plan([(SKU, 3)], mode="live"), on_report=on_report, order_wait_s=5)
        # queue.report: submit_seen with no ref -> needs_person 'submit_seen_no_ref', never retried
        self.assertEqual(result["outcome"], "submit_seen")
        self.assertEqual(result["order_ref"], "")
        self.assertNotIn("history_lines", result)
        self.assertIn("2104322599", result["steps"][-1]["note"])

    def test_live_handover_report_failure_does_not_hand_over(self):
        d = self.driver()
        result = self.go(d, fill_plan([(SKU, 3)], mode="live"), on_report=lambda p: False)
        self.assertEqual(result["outcome"], "error")
        self.assertNotIn("راجع ثم اضغط Submit Order بنفسك", self.said)

    # ── discovery and Order History reads ─────────────────────────────────────────────────

    def test_discovery_reports_candidates_and_adds_nothing(self):
        d = self.driver({"stock": {"60634": 0}})
        plan = {"kind": "discovery", "portal": "pharma_overseas", "account": {"identity_text": ACCOUNT},
                "searches": [{"buyline_id": 5, "term": "PANADOL"}, {"buyline_id": 6, "term": "CONGESTAL"}]}
        result = self.go(d, plan)
        self.assertEqual(result["outcome"], "discovery_ok", result["steps"])
        self.assertEqual(result["discovery"][0]["buyline_id"], 5)
        self.assertEqual(result["discovery"][0]["candidates"][0]["sku"], SKU.zfill(18))
        self.assertEqual(result["discovery"][1]["candidates"][0]["stock_mark"], True)
        self.assertEqual(self.fx(d)["log"], [])

    def test_history_found_and_none(self):
        orders = [{"ref": "2104300001", "date": "25/10/2026", "lines": [{"sku": "1", "qty": 1}]},
                  {"ref": "2104322530", "date": "18/11/2026", "lines": [{"sku": SKU, "qty": 4}]}]
        d = self.driver({"orders": orders})
        plan = {"kind": "history", "basket_id": 9, "since": "2026-11-17T00:00:00+02:00", "order_ref": ""}
        result = self.go(d, plan)
        self.assertEqual(result["outcome"], "history_found", result["steps"])
        self.assertEqual(result["order_ref"], "2104322530")
        self.assertEqual(result["history_lines"], [{"sku": SKU, "qty": 4}])
        result = self.go(d, dict(plan, since="2026-11-19T00:00:00+02:00"))
        self.assertEqual(result["outcome"], "history_none")


    def test_history_keeps_the_plan_order_and_ambiguous_dates(self):
        orders = [{"ref": "2104300001", "date": "20/10/2026", "lines": [{"sku": "1", "qty": 1}]},
                  {"ref": "2104300002", "date": "05/11/2026", "lines": [{"sku": "2", "qty": 2}]}]
        d = self.driver({"orders": orders})
        plan = {"kind": "history", "basket_id": 9, "since": "2026-11-17T00:00:00+02:00",
                "order_ref": "2104300001"}
        # the plan's own order is kept whatever its date
        result = self.go(d, plan)
        self.assertEqual((result["outcome"], result["order_ref"]), ("history_found", "2104300001"))
        # 05/11/2026 may be 11 May or 5 November: kept, never read as "before since"
        result = self.go(d, dict(plan, order_ref=""))
        self.assertEqual((result["outcome"], result["order_ref"]), ("history_found", "2104300002"))


class ParseDateTests(unittest.TestCase):

    def test_ambiguous_day_month_is_unreadable(self):
        from rpa_agent.portal_web.driver import parse_date
        fmts = base_recipe.DATE_FORMATS
        self.assertIsNone(parse_date("05/11/2026", fmts, strict=True))          # Order History only
        self.assertEqual(parse_date("05/11/2026", fmts), datetime.date(2026, 11, 5))  # pinned format
        self.assertEqual(parse_date("01/03/2027", fmts), datetime.date(2027, 3, 1))
        self.assertEqual(parse_date("18/11/2026", fmts, strict=True), datetime.date(2026, 11, 18))
        self.assertEqual(parse_date("18/11/2026", fmts), datetime.date(2026, 11, 18))
        self.assertEqual(parse_date("11/11/2026", fmts), datetime.date(2026, 11, 11))
        self.assertEqual(parse_date("2026-11-05", fmts), datetime.date(2026, 11, 5))


if __name__ == "__main__":
    unittest.main()
