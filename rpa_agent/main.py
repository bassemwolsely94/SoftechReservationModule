"""ElRezeiky SOFTECH screen robot agent. Config: %APPDATA%\\ElRezeiky\\rpa_agent.json"""
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


def run_one(client, claim, mode="dry_run"):
    from .driver import Win32Driver
    from .overlay import Overlay

    kp, run_id = claim["keyplan"], claim["run_id"]
    doc_id = kp["document"]
    stop = threading.Event()
    overlay = Overlay(stop)
    if not overlay.confirm_checklist(kp["reference"], kp.get("checklist", [])):
        client.report(doc_id, {"run_id": run_id, "mode": mode,
                               "outcome": "stopped_by_operator", "steps": []})
        return
    alive = threading.Event()

    def beat():
        while not alive.wait(HEARTBEAT_SECONDS):
            try:
                client.heartbeat(doc_id)
            except Exception:
                pass
    threading.Thread(target=beat, daemon=True).start()
    overlay.show_running(kp["reference"])

    def on_shot(i, png):
        try:
            client.screenshot(run_id, i, png)
        except Exception:
            pass
    try:
        result = run_keyplan(kp, Win32Driver(), stop=stop, on_shot=on_shot, mode=mode)
    finally:
        alive.set()
        overlay.close()
    client.report(doc_id, {"run_id": run_id, "mode": mode, **result})


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
            run_one(client, claim)
        else:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
