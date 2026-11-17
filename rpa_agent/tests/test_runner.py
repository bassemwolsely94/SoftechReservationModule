import threading
import unittest

from rpa_agent.runner import run_keyplan


class FakeDriver:
    def __init__(self, title="SOFTECH  Pharmacy", popups_after=None, focus_lost_after=None):
        self.title = title
        self.sent = []
        self.popups_after = popups_after or {}  # send count -> list of popups
        self.focus_lost_after = focus_lost_after
        self.shots = 0

    def focus(self, window_title):
        if self.focus_lost_after is not None and len(self.sent) >= self.focus_lost_after:
            return False
        return " ".join(self.title.split()) == " ".join(window_title.split())

    def send(self, keys, pause):
        self.sent.append((keys, pause))

    def popups(self):
        return list(self.popups_after.get(len(self.sent), []))

    def screenshot(self):
        self.shots += 1
        return b"png"


def plan(n=3, **kw):
    p = {
        "document": 1, "reference": "RPA-1", "window_title": "SOFTECH Pharmacy",
        "cell_delay": 0, "form_delay": 0, "checklist": [], "popups": [],
        "steps": [{"i": i, "label": "s%d" % i, "send": "k%d" % i} for i in range(n)],
    }
    p["steps"][-1]["final"] = True
    p.update(kw)
    return p


class RunnerTests(unittest.TestCase):
    def run_it(self, p, d, stop=None):
        shots = []
        r = run_keyplan(p, d, stop=stop or threading.Event(),
                        on_shot=lambda i, b: shots.append(i))
        return r, shots

    def test_wrong_window_types_nothing(self):
        d = FakeDriver(title="Notepad")
        r, _ = self.run_it(plan(), d)
        self.assertEqual(r["outcome"], "wrong_window")
        self.assertEqual(d.sent, [])

    def test_title_whitespace_tolerated(self):
        d = FakeDriver(title="SOFTECH    Pharmacy ")
        r, _ = self.run_it(plan(), d)
        self.assertEqual(r["outcome"], "dry_run_ok")

    def test_stop_flag_halts_before_next_step(self):
        stop = threading.Event()
        d = FakeDriver()
        orig = d.send

        def send(keys, pause):
            orig(keys, pause)
            stop.set()
        d.send = send
        r, _ = self.run_it(plan(), d, stop)
        self.assertEqual(r["outcome"], "stopped_by_operator")
        self.assertEqual(len(d.sent), 1)

    def test_unknown_popup_stops_and_screenshots(self):
        d = FakeDriver(popups_after={1: [{"title": "Error", "text": "boom"}]})
        r, shots = self.run_it(plan(), d)
        self.assertEqual(r["outcome"], "unknown_popup")
        self.assertEqual(len(d.sent), 1)
        self.assertTrue(shots)

    def test_empty_popup_rule_never_matches(self):
        p = plan(popups=[{"title_contains": " ", "text_contains": "", "answer_keys": "{ENTER}"}])
        d = FakeDriver(popups_after={1: [{"title": "Save changes?", "text": "anything"}]})
        r = run_keyplan(p, d, stop=threading.Event())
        self.assertEqual(r["outcome"], "unknown_popup")
        self.assertNotIn("{ENTER}", [k for k, _ in d.sent])

    def test_known_popup_answered_and_continues(self):
        p = plan(popups=[{"title_contains": "Confirm", "text_contains": "save", "answer_keys": "{ENTER}"}])
        d = FakeDriver(popups_after={1: [{"title": "Confirm", "text": "Do you save?"}]})
        r, _ = self.run_it(p, d)
        self.assertEqual(r["outcome"], "dry_run_ok")
        self.assertIn("{ENTER}", [k for k, _ in d.sent])
        self.assertEqual(len(d.sent), 4)

    def test_dry_run_final_step_outcome(self):
        d = FakeDriver()
        r, shots = self.run_it(plan(2), d)
        self.assertEqual(r["outcome"], "dry_run_ok")
        self.assertEqual(len(r["steps"]), 2)
        self.assertIn(0, shots)
        self.assertIn(1, shots)
        self.assertTrue(all(s["ok"] for s in r["steps"]))

    def test_focus_lost_midway_stops(self):
        d = FakeDriver(focus_lost_after=1)
        r, _ = self.run_it(plan(), d)
        self.assertEqual(r["outcome"], "wrong_window")
        self.assertEqual(len(d.sent), 1)

    def test_exception_gives_error(self):
        d = FakeDriver()

        def boom(keys, pause):
            raise RuntimeError("bad")
        d.send = boom
        r, _ = self.run_it(plan(), d)
        self.assertEqual(r["outcome"], "error")
        self.assertIn("bad", r["steps"][-1]["note"])


if __name__ == "__main__":
    unittest.main()


class FixRoundTests(unittest.TestCase):
    def test_stop_mid_step_sends_no_further_chunks(self):
        from rpa_agent.runner import split_chunks
        self.assertEqual(split_chunks("a{TAB}b{ENTER}c"), ["a{TAB}", "b{ENTER}", "c"])
        self.assertEqual(split_chunks("^{TAB}{}}x"), ["^{TAB}{}}x"])
        stop = threading.Event()
        d = FakeDriver()
        orig = d.send

        def send(keys, pause):
            orig(keys, pause)
            stop.set()
        d.send = send
        p = plan(1)
        p["steps"][0]["send"] = "a{TAB}b{TAB}c{ENTER}"
        r = run_keyplan(p, d, stop=stop)
        self.assertEqual(r["outcome"], "stopped_by_operator")
        self.assertEqual(d.sent, [("a{TAB}", 0)])

    def test_stop_during_final_step_is_not_dry_run_ok(self):
        stop = threading.Event()
        d = FakeDriver()
        orig = d.send

        def send(keys, pause):
            orig(keys, pause)
            stop.set()
        d.send = send
        r = run_keyplan(plan(1), d, stop=stop)
        self.assertEqual(r["outcome"], "stopped_by_operator")

    def test_injected_esc_ignored(self):
        from rpa_agent.overlay import handle_press
        stop = threading.Event()
        handle_press(stop, True, True)
        self.assertFalse(stop.is_set())
        handle_press(stop, False, False)
        self.assertFalse(stop.is_set())
        handle_press(stop, True, False)
        self.assertTrue(stop.is_set())

    def test_empty_steps_is_error(self):
        d = FakeDriver()
        r = run_keyplan(plan(1, steps=[]), d, stop=threading.Event())
        self.assertEqual(r["outcome"], "error")
        self.assertEqual(d.sent, [])
