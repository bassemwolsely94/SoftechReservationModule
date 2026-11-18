"""ElRezeiky SOFTECH screen robot agent. Config: %APPDATA%\\ElRezeiky\\rpa_agent.json

Also runs the supplier-portal robot (portal_web) when the config says "portal_enabled": true.
`python -m rpa_agent.main --open-portal-browser` (menu item «فتح متصفح الموردين») opens the
persistent supplier browser at start so the operator can log in by hand.
"""
import datetime
import json
import os
import sys
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


def report_with_retry(client, doc_id, payload, attempts=4, sleep=time.sleep, send=None):
    """The server's answer (a dict when it sent one, else True) once a report is taken; False
    when every attempt failed. A portal handover reads the answer: only status awaiting_submit
    means the server holds the basket for Submit (a retried handover is refused there)."""
    send = send or client.report
    for n in range(attempts):
        try:
            answer = send(doc_id, payload)
            return answer if answer is not None else True
        except Exception as e:  # noqa: BLE001
            print("report failed (%d/%d): %s" % (n + 1, attempts, e))
            if n < attempts - 1:
                sleep(2 ** (n + 1))
    return False


# The server answers a heartbeat with 409 when the document is no longer ours (lease ran out, a
# person took it over), 404 when it was never ours and 401 when the device was revoked: stop typing.
LEASE_LOST_CODES = (401, 404, 409)


def heartbeat_loop(client, doc_id, alive, stop, lost, interval=HEARTBEAT_SECONDS, beat=None):
    """Renew the lease until `alive` is set. If the server says the lease is gone, set `lost` and
    `stop` (the same stop the operator's Esc sets), so the runner halts before the next keystroke."""
    beat = beat or client.heartbeat
    while not alive.wait(interval):
        try:
            beat(doc_id)
        except Exception as e:  # noqa: BLE001 - a network blip is retried on the next beat
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in LEASE_LOST_CODES:
                lost.set()
                stop.set()
                return


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def refused_mode(claim, allow_live=False):
    """Why this agent will not run the claim's mode ('' = it will). Only a dry run is typed,
    unless the server says live AND this machine's own setting allows live (default off)."""
    mode = claim.get("mode")
    if mode == "dry_run":
        return ""
    if mode == "live" and allow_live is True:
        return ""
    if mode == "live":
        return "live mode refused: allow_live is off on this agent"
    return "unknown mode refused: %r" % (mode,)


def run_one(client, claim, allow_live=False):
    kp, run_id = claim["keyplan"], claim["run_id"]
    doc_id = kp["document"]
    refusal = refused_mode(claim, allow_live)
    if refusal:                       # nothing is typed: the server sends the document to a person
        report_with_retry(client, doc_id, {"run_id": run_id, "mode": claim.get("mode"), "outcome": "error",
                                           "steps": [{"i": -1, "label": "mode", "at": _now(), "ok": False,
                                                      "note": refusal}]})
        return
    mode = claim["mode"]

    from .driver import Win32Driver
    from .overlay import Overlay

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
            {"i": -1, "label": "agent", "at": _now(), "ok": False, "note": str(e)}]}
    finally:
        alive.set()
        try:
            overlay.close()
        except Exception:
            pass
    report_with_retry(client, doc_id, {"run_id": run_id, "mode": mode, **result})


# ── supplier-portal robot ─────────────────────────────────────────────────────────────────────

PORTAL_KINDS = ("discovery", "fill", "history")
OPEN_PORTAL_BROWSER = "فتح متصفح الموردين"
PORTAL_PROFILE = os.path.join(os.environ.get("LOCALAPPDATA", "."), "ElRezeiky", "portal_browser")
_portal_driver = None


def is_portal_claim(claim):
    plan = claim.get("plan") if isinstance(claim, dict) else None
    return isinstance(plan, dict) and plan.get("kind") in PORTAL_KINDS


def portal_driver(cfg):
    """One visible browser per agent, on a persistent profile (the operator's login lives there;
    the agent never reads or stores its cookies). Created on first use."""
    global _portal_driver
    if _portal_driver is None:
        from .portal_web.driver import PortalWebDriver
        _portal_driver = PortalWebDriver(cfg.get("portal_profile_dir") or PORTAL_PROFILE,
                                         channel=cfg.get("portal_browser_channel") or None)
    return _portal_driver.start()


def open_portal_browser(cfg):
    """«فتح متصفح الموردين»: show the supplier site so the operator logs in by hand."""
    driver = portal_driver(cfg)
    driver.page.goto(driver.url("quick_order"))
    print("%s: log in by hand in the browser window, then leave it open." % OPEN_PORTAL_BROWSER)
    return driver


def run_portal(client, claim, driver, allow_live=False):
    """Run one portal plan through portal_web.runner.run_plan and report on the portal run."""
    plan, run_id = claim["plan"], claim["run_id"]

    def send(payload):
        return report_with_retry(client, run_id, payload, send=client.portal_report)

    if plan.get("kind") == "fill" and plan.get("mode") == "live" and allow_live is not True:
        send({"outcome": "error", "steps": [{"i": 0, "label": "mode", "at": _now(), "ok": False,
                                             "note": "live mode refused: allow_live is off on this agent"}]})
        return
    from .overlay import Overlay
    from .portal_web.runner import run_plan

    stop, alive, lost = threading.Event(), threading.Event(), threading.Event()
    overlay = Overlay(stop)
    threading.Thread(target=heartbeat_loop,
                     args=(client, run_id, alive, stop, lost, HEARTBEAT_SECONDS, client.portal_heartbeat),
                     daemon=True).start()

    def on_shot(i, png):
        try:
            client.portal_screenshot(run_id, i, png)
        except Exception:  # noqa: BLE001 - a missing picture never stops the run
            pass
    try:
        overlay.show_running("%s %s" % (plan.get("kind"), plan.get("basket_id") or ""))
        result = run_plan(plan, driver, stop=stop, on_shot=on_shot, say=overlay.say, on_report=send)
    except Exception as e:  # noqa: BLE001 - run_plan never raises; the overlay might
        result = {"outcome": "error", "steps": [{"i": 0, "label": "agent", "at": _now(), "ok": False,
                                                 "note": type(e).__name__}]}
    finally:
        alive.set()
        try:
            overlay.close()
        except Exception:  # noqa: BLE001 - closing the strip never fails the report
            pass
    send(result)


def main(argv=None):
    argv = list(argv or [])
    cfg = load_config()
    client = AgentClient(cfg["base_url"], cfg["token"])
    allow_live = cfg.get("allow_live") is True     # local setting, default off: Stage 1 types dry runs only
    portal = cfg.get("portal_enabled") is True     # local setting, default off: supplier-portal robot
    print("ElRezeiky RPA agent started. Ctrl+C to quit.")
    if portal:
        print("%s: python -m rpa_agent.main --open-portal-browser" % OPEN_PORTAL_BROWSER)
        if "--open-portal-browser" in argv:
            open_portal_browser(cfg)
    while True:
        try:
            claim = client.claim()
        except Exception as e:  # noqa: BLE001
            print("claim failed:", e)
            claim = None
        if not claim and portal:
            try:
                claim = client.portal_claim()
            except Exception as e:  # noqa: BLE001 - a network blip is retried on the next poll
                print("portal claim failed:", e)
                claim = None
        if claim:
            try:
                if is_portal_claim(claim):
                    run_portal(client, claim, portal_driver(cfg), allow_live=allow_live)
                else:
                    run_one(client, claim, allow_live=allow_live)
            except Exception as e:  # noqa: BLE001 - the poll loop must survive
                print("run failed:", e)
                time.sleep(POLL_SECONDS)
        else:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main(sys.argv[1:])
