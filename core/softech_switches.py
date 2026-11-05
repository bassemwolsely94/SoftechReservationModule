"""
core/softech_switches.py

One switch for SOFTECH rehearsals and diagnostics: anything that runs real DML on SOFTECH
only to rehearse or investigate — rolled back or "restored" afterwards — still fires
production triggers and holds locks (and a restore that never runs leaves the change).
They run only where SOFTECH_PROBES_ENABLED is deliberately turned on (default off).

    require_probes('pos_orders.writer.probe_order')       # functions → ValueError
    command_require_probes('test_replication_cycle --mode plant')   # commands → CommandError
"""
from django.conf import settings


class SoftechProbesDisabled(ValueError):
    """A SOFTECH rehearsal / diagnostic write was refused (SOFTECH_PROBES_ENABLED off)."""


def probes_enabled() -> bool:
    return bool(getattr(settings, 'SOFTECH_PROBES_ENABLED', False))


def _copy_may_probe() -> bool:
    """The writer copy may probe; a reader only while SOFTECH_READ_ONLY keeps the connection
    read-only (round-2 R1, owner decision D1 2026-11-05 — probes used to ignore WRITER_INSTANCE)."""
    return bool(getattr(settings, 'WRITER_INSTANCE', False)) or bool(getattr(settings, 'SOFTECH_READ_ONLY', True))


def _refusal(what: str):
    if not probes_enabled():
        return (f'{what}: writes to SOFTECH (rehearsal / diagnostic) — refused while '
                f'SOFTECH_PROBES_ENABLED=False. Turn it on deliberately, run, turn it off.')
    if not _copy_may_probe():
        return (f'{what}: writes to SOFTECH (rehearsal / diagnostic) — refused on a non-writer copy '
                f'with SOFTECH_READ_ONLY=False (WRITER_INSTANCE=False). Run it on the writer.')
    return None


def require_probes(what: str) -> None:
    msg = _refusal(what)
    if msg:
        raise SoftechProbesDisabled(msg)


def command_require_probes(what: str) -> None:
    msg = _refusal(what)
    if msg:
        from django.core.management.base import CommandError
        raise CommandError(msg)
