"""The agent routes supplier-portal claims to portal_web.runner.run_plan (no browser needed here)."""
import sys
import types
import unittest
from unittest import mock

from rpa_agent import main


class FakeOverlay:
    def __init__(self, stop):
        self.stop = stop
        self.said = []

    def show_running(self, reference):
        pass

    def say(self, text):
        self.said.append(text)

    def close(self):
        pass


class FakeClient:
    def __init__(self, portal_claims=()):
        self.portal_claims = list(portal_claims)
        self.reports, self.portal_reports, self.beats = [], [], []

    def claim(self):
        return None

    def portal_claim(self):
        return self.portal_claims.pop(0) if self.portal_claims else None

    def portal_heartbeat(self, run_id):
        self.beats.append(run_id)

    def portal_report(self, run_id, payload):
        self.portal_reports.append((run_id, payload))

    def portal_screenshot(self, run_id, step, png):
        pass

    def report(self, doc_id, payload):
        self.reports.append(payload)


def portal_claim(kind="fill", mode="dry_run"):
    plan = {"kind": kind, "basket_id": 4, "mode": mode, "account": {"identity_text": "A"}, "lines": []}
    return {"run_id": 11, "plan": plan}


class RunPortalTests(unittest.TestCase):

    def run_claim(self, claim, result=None, **kw):
        calls = []

        def run_plan(plan, driver, *, stop, on_step=None, on_shot=None, say=None, on_report=None):
            calls.append({"plan": plan, "driver": driver, "on_report": on_report})
            if on_report and plan.get("mode") == "live":
                on_report({"outcome": "handover", "steps": []})
            return result or {"outcome": "dry_run_ok", "steps": []}

        fakes = {"rpa_agent.portal_web.runner": types.SimpleNamespace(run_plan=run_plan),
                 "rpa_agent.overlay": types.SimpleNamespace(Overlay=FakeOverlay)}
        client = FakeClient()
        with mock.patch.dict(sys.modules, fakes):
            main.run_portal(client, claim, driver=object(), **kw)
        return calls, client

    def test_fill_claim_goes_to_run_plan_and_reports_on_the_portal_run(self):
        calls, client = self.run_claim(portal_claim())
        self.assertEqual(calls[0]["plan"]["kind"], "fill")
        self.assertEqual(client.portal_reports, [(11, {"outcome": "dry_run_ok", "steps": []})])
        self.assertEqual(client.reports, [])                   # never the SOFTECH document report

    def test_discovery_and_history_claims_go_to_run_plan(self):
        for kind in ("discovery", "history"):
            calls, client = self.run_claim(portal_claim(kind))
            self.assertEqual(calls[0]["plan"]["kind"], kind)
            self.assertEqual(client.portal_reports[0][0], 11)

    def test_live_fill_refused_unless_this_agent_allows_live(self):
        calls, client = self.run_claim(portal_claim(mode="live"))
        self.assertEqual(calls, [])
        self.assertEqual(client.portal_reports[0][1]["outcome"], "error")
        self.assertEqual(client.portal_reports[0][1]["steps"][0]["label"], "mode")

    def test_live_handover_is_reported_before_the_final_report(self):
        calls, client = self.run_claim(portal_claim(mode="live"), allow_live=True,
                                       result={"outcome": "submit_seen", "steps": [], "order_ref": "9"})
        self.assertEqual([p["outcome"] for _, p in client.portal_reports], ["handover", "submit_seen"])

    def test_report_answer_reaches_the_runner(self):
        # the handover's answer is what the runner checks (status awaiting_submit) - never just "sent"
        answer = {"run_id": 11, "outcome": "handover", "basket": 4, "status": "awaiting_submit"}
        self.assertEqual(main.report_with_retry(None, 11, {}, send=lambda rid, p: answer), answer)
        self.assertIs(main.report_with_retry(None, 11, {}, send=lambda rid, p: None), True)

        def down(rid, p):
            raise OSError("down")
        self.assertIs(main.report_with_retry(None, 11, {}, send=down, sleep=lambda s: None), False)

    def test_is_portal_claim(self):
        self.assertTrue(main.is_portal_claim(portal_claim("history")))
        self.assertFalse(main.is_portal_claim({"run_id": 1, "mode": "dry_run", "keyplan": {}}))
        self.assertFalse(main.is_portal_claim({"run_id": 1, "plan": {"kind": "submit"}}))

    def test_main_polls_the_portal_only_when_enabled(self):
        client = mock.Mock()
        client.claim.return_value = None
        client.portal_claim.side_effect = [portal_claim(), KeyboardInterrupt()]
        seen = []
        cfg = {"base_url": "x", "token": "t", "portal_enabled": True}
        with mock.patch.object(main, "load_config", return_value=cfg), \
                mock.patch.object(main, "AgentClient", return_value=client), \
                mock.patch.object(main, "run_portal", side_effect=lambda cl, c, drv, **kw: seen.append(c)), \
                mock.patch.object(main, "portal_driver", return_value=object()), \
                mock.patch.object(main.time, "sleep"), mock.patch("builtins.print"):
            with self.assertRaises(KeyboardInterrupt):
                main.main([])
        self.assertEqual(seen[0]["run_id"], 11)
        client = mock.Mock()
        client.claim.side_effect = [None, KeyboardInterrupt()]
        with mock.patch.object(main, "load_config", return_value={"base_url": "x", "token": "t"}), \
                mock.patch.object(main, "AgentClient", return_value=client), \
                mock.patch.object(main.time, "sleep"), mock.patch("builtins.print"):
            with self.assertRaises(KeyboardInterrupt):
                main.main([])
        client.portal_claim.assert_not_called()


if __name__ == "__main__":
    unittest.main()
