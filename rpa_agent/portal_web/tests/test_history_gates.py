"""Order History read, pre-live gates R20 / R21 - robot side, no browser needed.

The robot says "history_none" only with a positive proof that the whole window was read: the
recipe's paging locators were confirmed on the real site (HISTORY_PAGING_CONFIRMED) and the read
was not cut at MAX_ORDERS. Otherwise an empty read is "history_unclear" (a person decides), and
every report carries `complete` and `truncated` for the server to check again.
"""
import datetime
import threading
import types
import unittest

from rpa_agent.portal_web import recipe_pharma_overseas as base_recipe
from rpa_agent.portal_web import runner
from rpa_agent.portal_web.driver import PortalError, PortalWebDriver

PLAN = {"kind": "history", "basket_id": 9, "since": "2026-11-17T00:00:00+02:00", "order_ref": ""}


def recipe(**over):
    r = types.SimpleNamespace(**{k: getattr(base_recipe, k) for k in dir(base_recipe) if k.isupper()})
    for k, v in over.items():
        setattr(r, k, v)
    return r


class FakeDriver:
    """Just what run_plan's history read touches."""

    def __init__(self, orders, proof):
        self.recipe = recipe()
        self.orders, self.proof = orders, proof

    def ensure_logged_in(self, wait_s):
        return True

    def account_identity(self):
        return "ELREZEIKY PHARMACY 1"

    def screenshot(self):
        return b""

    def order_history(self, since, keep_ref=None):
        if self.proof is not None:
            self.history_proof = dict(self.proof)
        return list(self.orders)


def go(driver):
    return runner.run_plan(dict(PLAN), driver, stop=threading.Event())


def orders(n):
    return [{"order_ref": "21043%05d" % i, "date": "2026-11-18", "lines": [{"sku": "1", "qty": 1}]}
            for i in range(n)]


class RunnerHistoryGateTests(unittest.TestCase):

    def test_recipe_paging_is_not_confirmed_yet(self):
        self.assertIs(base_recipe.HISTORY_PAGING_CONFIRMED, False)

    def test_empty_read_without_proof_is_unclear(self):
        for proof in ({"complete": False}, None, {}):
            result = go(FakeDriver([], proof))
            self.assertEqual(result["outcome"], "history_unclear", proof)
            self.assertIs(result["complete"], False)
            self.assertIs(result["truncated"], False)

    def test_empty_read_with_proof_is_none(self):
        result = go(FakeDriver([], {"complete": True}))
        self.assertEqual(result["outcome"], "history_none")
        self.assertIs(result["complete"], True)

    def test_orders_carry_the_proof(self):
        result = go(FakeDriver(orders(2), {"complete": True}))
        self.assertEqual(result["outcome"], "history_found")
        self.assertEqual((result["complete"], result["truncated"]), (True, False))

    def test_more_than_the_cap_is_truncated_and_never_complete(self):
        result = go(FakeDriver(orders(runner.MAX_ORDERS + 1), {"complete": True}))
        self.assertEqual(result["outcome"], "history_found")
        self.assertEqual(len(result["orders"]), runner.MAX_ORDERS)
        self.assertEqual((result["complete"], result["truncated"]), (False, True))


class DriverHistoryProofTests(unittest.TestCase):
    """order_history's proof, with the page reads stubbed (no browser)."""

    def driver(self, rows, paged=False, **over):
        d = PortalWebDriver("unused-profile", recipe=recipe(**over))
        d.goto = lambda key: None
        d._read_table = lambda name, cols: [dict(r) for r in rows]
        d._paged = lambda name: paged
        return d

    def test_not_confirmed_is_never_complete(self):
        d = self.driver([])
        self.assertEqual(d.order_history(datetime.date(2026, 11, 17)), [])
        self.assertEqual(d.history_proof, {"complete": False})

    def test_confirmed_and_no_pager_is_complete(self):
        d = self.driver([], HISTORY_PAGING_CONFIRMED=True)
        d.order_history(datetime.date(2026, 11, 17))
        self.assertEqual(d.history_proof, {"complete": True})
        # rows all older than the window, pager shown: the next page is older still
        d = self.driver([{"order_ref": "2104300001", "date": "20/10/2026"}], paged=True,
                        HISTORY_PAGING_CONFIRMED=True)
        self.assertEqual(d.order_history(datetime.date(2026, 11, 17)), [])
        self.assertEqual(d.history_proof, {"complete": True})

    def test_a_failed_read_leaves_no_proof(self):
        d = self.driver([{"order_ref": "2104300001", "date": "18/11/2026"}], paged=True,
                        HISTORY_PAGING_CONFIRMED=True)
        d.history_proof = {"complete": True}                      # from an earlier read
        with self.assertRaises(PortalError):
            d.order_history(datetime.date(2026, 11, 17))
        self.assertEqual(d.history_proof, {"complete": False})


if __name__ == "__main__":
    unittest.main()
