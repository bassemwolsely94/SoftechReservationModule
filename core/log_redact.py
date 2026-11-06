"""
core/log_redact.py — no credentials in any log line (round 2, R4 step 5).

Exception text reaches the logs from everywhere (`logger.error('… %s', exc, exc_info=True)`,
django.request's 500 lines). A driver or library error can carry a password, an API key or a bearer
token. install() wraps the logging record factory once per process: every record's message is
rendered and passed through core.errors.redact(), and its traceback text is pre-rendered redacted
(logging.Formatter reuses record.exc_text), before any handler or filter sees it.

Hosts, paths and error codes stay — IT needs them. Phones are not touched here (masking is a
display rule; the logs are IT-only).
"""
import logging

_installed = False


def _redact(text):
    try:
        from core.errors import redact
        return redact(text)
    except Exception:          # noqa: BLE001 — settings not ready (very early import): leave as is
        return text


def install():
    global _installed
    if _installed:
        return
    base = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = base(*args, **kwargs)
        try:
            msg = record.getMessage()
        except Exception:      # noqa: BLE001 — a bad format string: the handler will report it
            return record
        clean = _redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        if record.exc_info and record.exc_info[1] is not None:
            text = logging.Formatter().formatException(record.exc_info)
            red = _redact(text)
            if red != text:
                record.exc_text = red
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
