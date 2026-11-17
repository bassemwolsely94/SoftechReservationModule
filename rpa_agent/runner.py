"""Pure keyplan runner. No pywinauto/HTTP here; everything goes through `driver`."""
import datetime


def _norm(s):
    return " ".join((s or "").split())


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


_MODS = "^%+"
_CELL_END = ("{TAB}", "{ENTER}")


def split_chunks(keys):
    """Split send_keys notation into chunks ending at each {TAB}/{ENTER} token, so the
    runner can check the stop flag between chunks. Never splits inside a token."""
    chunks, cur, i, n = [], "", 0, len(keys)
    while i < n:
        start = i
        while i < n and keys[i] in _MODS:
            i += 1
        if i >= n:
            cur += keys[start:]
            break
        c = keys[i]
        if c == "{":
            j = keys.find("}", i + 2)
            i = n if j == -1 else j + 1
        elif c == "(":
            j = keys.find(")", i + 1)
            i = n if j == -1 else j + 1
        else:
            i += 1
        tok = keys[start:i]
        cur += tok
        if tok.upper() in _CELL_END:
            chunks.append(cur)
            cur = ""
    if cur:
        chunks.append(cur)
    return chunks


def _match_rule(rules, popup):
    title = popup.get("title", "") or ""
    text = popup.get("text", "") or ""
    for r in rules:
        want_title = r.get("title_contains") or ""
        want_text = r.get("text_contains") or ""
        if not (want_title.strip() or want_text.strip()):   # an empty rule would answer every popup: never use it
            continue
        if want_title in title and want_text in text:
            return r
    return None


def run_keyplan(keyplan, driver, *, stop, on_step=None, on_shot=None, mode="dry_run"):
    steps_out = []
    title = _norm(keyplan["window_title"])
    cell_delay = float(keyplan.get("cell_delay", 0) or 0)
    form_delay = float(keyplan.get("form_delay", 0) or 0)
    rules = keyplan.get("popups", [])
    steps = keyplan["steps"]
    done_outcome = "dry_run_ok" if mode == "dry_run" else "saved"

    def rec(i, label, ok, note=""):
        s = {"i": i, "label": label, "at": _now(), "ok": ok, "note": note}
        steps_out.append(s)
        if on_step:
            on_step(s)

    def shot(i):
        if on_shot:
            try:
                on_shot(i, driver.screenshot())
            except Exception:
                pass

    def finish(outcome):
        return {"outcome": outcome, "steps": steps_out}

    if not steps:
        rec(-1, "plan", False, "empty keyplan")
        return finish("error")
    if stop.is_set():
        rec(-1, "start", False, "stopped_by_operator")
        return finish("stopped_by_operator")
    if not title or not driver.focus(title):
        rec(-1, "focus", False, "wrong_window")
        return finish("wrong_window")

    last = len(steps) - 1
    for pos, step in enumerate(steps):
        i, label = step["i"], step.get("label", "")
        try:
            if stop.is_set():
                rec(i, label, False, "stopped_by_operator")
                return finish("stopped_by_operator")
            if not driver.focus(title):
                rec(i, label, False, "wrong_window")
                return finish("wrong_window")
            for chunk in split_chunks(step["send"]):
                if stop.is_set():
                    rec(i, label, False, "stopped_by_operator")
                    return finish("stopped_by_operator")
                driver.send(chunk, cell_delay)
            if form_delay:
                stop.wait(form_delay)
            for _ in range(5):
                popups = driver.popups()
                if not popups:
                    break
                for p in popups:
                    rule = _match_rule(rules, p)
                    if rule is None:
                        shot(i)
                        rec(i, label, False, "unknown_popup: %s" % (p.get("title", ""),))
                        return finish("unknown_popup")
                    if stop.is_set():
                        rec(i, label, False, "stopped_by_operator")
                        return finish("stopped_by_operator")
                    driver.send(rule["answer_keys"], cell_delay)
                if form_delay:
                    stop.wait(form_delay)
            if stop.is_set():
                rec(i, label, False, "stopped_by_operator")
                return finish("stopped_by_operator")
            is_final = bool(step.get("final")) or pos == last
            if pos == 0 or (pos + 1) % 10 == 0 or is_final:
                shot(i)
            rec(i, label, True)
            if is_final:
                return finish(done_outcome)
        except Exception as e:  # noqa: BLE001 - reported to the server as outcome=error
            rec(i, label, False, str(e))
            return finish("error")
    return finish(done_outcome)
