"""ElRezeiky SOFTECH screen robot agent. Config: %APPDATA%\\ElRezeiky\\rpa_agent.json"""
import datetime
import json
import os
import threading
import time

from .client import AgentClient
from .runner import run_keyplan

CONFIG = os.path.join(os.environ.get("APPDATA", "."), "ElRezeiky", "rpa_agent.json")
POLL_SECONDS = 10
HEARTBEAT_SECONDS = 90  # lease is 10 min; backend asks for at least every 2 min


def load_config(path=CONFIG):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def report_with_retry(client, doc_id, payload, attempts=4, sleep=time.sleep):
    for n in range(attempts):
        try:
            client.report(doc_id, payload)
            return True
        except Exception as e:  # noqa: BLE001
            print("report failed (%d/%d): %s" % (n + 1, attempts, e))
            if n < attempts - 1:
                sleep(2 ** (n + 1))
    return False


# The server answers a heartbeat with 409 when the document is no longer ours (lease ran out, a
# person took it over), 404 when it was never ours and 401 when the device was revoked: stop typing.
LEASE_LOST_CODES = (401, 404, 409)


def heartbeat_loop(client, doc_id, alive, stop, lost, interval=HEARTBEAT_SECONDS):
    """Renew the lease until `alive` is set. If the server says the lease is gone, set `lost` and
    `stop` (the same stop the operator's Esc sets), so the runner halts before the next keystroke."""
    while not alive.wait(interval):
        try:
            client.heartbeat(doc_id)
        except Exception as e:  # noqa: BLE001 - a network blip is retried on the next beat
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in LEASE_LOST_CODES:
                lost.set()
                stop.set()
                return


def run_one(client, claim, mode="dry_run"):
    from .driver import Win32Driver
    from .overlay import Overlay

    kp, run_id = claim["keyplan"], claim["run_id"]
    doc_id = kp["document"]
    stop = threading.Event()
    overlay = Overlay(stop)
    alive = threading.Event()

    lost = threading.Event()
    # heartbeat covers the checklist wait as well as the run
    threading.Thread(target=heartbeat_loop, args=(client, doc_id, alive, stop, lost, HEARTBEAT_SECONDS),
                     daemon=True).start()

    def on_shot(i, png):
        try:
            client.screenshot(run_id, i, png)
        except Exception:
            pass
    try:
        if not overlay.confirm_checklist(kp["reference"], kp.get("checklist", [])):
            result = {"outcome": "stopped_by_operator", "steps": []}
        elif lost.is_set():
            result = {"outcome": "lease_lost", "steps": []}
        else:
            overlay.show_running(kp["reference"])
            result = run_keyplan(kp, Win32Driver(), stop=stop, on_shot=on_shot, mode=mode)
        # our own stop, not the operator's: say so (a run that already saved keeps "saved" so
        # the server checks SOFTECH for it)
        if lost.is_set() and result.get("outcome") == "stopped_by_operator":
            result = {**result, "outcome": "lease_lost"}
    except Exception as e:  # noqa: BLE001 - keyplan/tk/driver failure
        result = {"outcome": "error", "steps": [
            {"i": -1, "label": "agent", "at": datetime.datetime.now(
                datetime.timezone.utc).isoformat(), "ok": False, "note": str(e)}]}
    finally:
        alive.set()
        try:
            overlay.close()
        except Exception:
            pass
    report_with_retry(client, doc_id, {"run_id": run_id, "mode": mode, **result})


def main():
    cfg = load_config()
    client = AgentClient(cfg["base_url"], cfg["token"])
    print("ElRezeiky RPA agent started. Ctrl+C to quit.")
    while True:
        try:
            claim = client.claim()
        except Exception as e:  # noqa: BLE001
            print("claim failed:", e)
            claim = None
        if claim:
            try:
                run_one(client, claim)
            except Exception as e:  # noqa: BLE001 - the poll loop must survive
                print("run failed:", e)
                time.sleep(POLL_SECONDS)
        else:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
