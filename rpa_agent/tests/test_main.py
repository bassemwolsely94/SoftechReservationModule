import sys
import threading
import time
import types
import unittest
from unittest import mock

from rpa_agent import main


class HttpError(Exception):
    def __init__(self, code):
        super().__init__("HTTP %d" % code)
        self.response = types.SimpleNamespace(status_code=code)


class FakeClient:
    def __init__(self, beat_error=None):
        self.beat_error = beat_error
        self.beats = 0
        self.reports = []

    def heartbeat(self, doc_id):
        self.beats += 1
        if self.beat_error:
            raise self.beat_error

    def screenshot(self, run_id, i, png):
        pass

    def report(self, doc_id, payload):
        self.reports.append(payload)


class SlowDriver:
    """Each keystroke chunk takes a while, so the heartbeat fires mid-plan."""

    def __init__(self):
        self.sent = []

    def focus(self, title):
        return True

    def send(self, keys, pause):
        self.sent.append(keys)
        time.sleep(0.02)

    def popups(self):
        return []

    def screenshot(self):
        return b"png"


class FakeOverlay:
    def __init__(self, stop):
        self.stop = stop

    def confirm_checklist(self, reference, checklist):
        return True

    def show_running(self, reference):
        pass

    def close(self):
        pass


def claim(n=200):
    steps = [{"i": i, "label": "s%d" % i, "send": "k%d{TAB}" % i} for i in range(1, n + 1)]
    steps[-1]["final"] = True
    return {"run_id": 7, "keyplan": {"document": 3, "reference": "RPA-3", "window_title": "SOFTECH",
                                     "cell_delay": 0, "form_delay": 0, "checklist": [], "popups": [],
                                     "steps": steps}}


class HeartbeatLoopTests(unittest.TestCase):

    def run_loop(self, client):
        alive, stop, lost = threading.Event(), threading.Event(), threading.Event()
        t = threading.Thread(target=main.heartbeat_loop, args=(client, 3, alive, stop, lost, 0.01))
        t.start()
        time.sleep(0.1)
        alive.set()
        t.join(2)
        return stop, lost

    def test_409_sets_stop_and_lost(self):
        client = FakeClient(HttpError(409))
        stop, lost = self.run_loop(client)
        self.assertTrue(stop.is_set() and lost.is_set())
        self.assertEqual(client.beats, 1)           # no more beats after the lease is gone

    def test_revoked_device_stops_too(self):
        stop, lost = self.run_loop(FakeClient(HttpError(401)))
        self.assertTrue(stop.is_set() and lost.is_set())

    def test_network_blip_keeps_beating(self):
        client = FakeClient(ConnectionError("offline"))
        stop, lost = self.run_loop(client)
        self.assertFalse(stop.is_set() or lost.is_set())
        self.assertGreater(client.beats, 1)


class RunOneLeaseLostTests(unittest.TestCase):

    def test_lease_lost_mid_plan_stops_typing_and_reports(self):
        driver = SlowDriver()
        fakes = {"rpa_agent.driver": types.SimpleNamespace(Win32Driver=lambda: driver),
                 "rpa_agent.overlay": types.SimpleNamespace(Overlay=FakeOverlay)}
        client = FakeClient(HttpError(409))
        with mock.patch.dict(sys.modules, fakes), mock.patch.object(main, "HEARTBEAT_SECONDS", 0.05):
            main.run_one(client, claim())
        self.assertLess(len(driver.sent), 200)      # the plan did not run to the end
        self.assertEqual(len(client.reports), 1)
        self.assertEqual(client.reports[0]["outcome"], "lease_lost")
        self.assertEqual(client.reports[0]["run_id"], 7)


if __name__ == "__main__":
    unittest.main()
