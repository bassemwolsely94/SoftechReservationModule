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


def _message(what: str) -> str:
    return (f'{what}: writes to SOFTECH (rehearsal / diagnostic) — refused while '
            f'SOFTECH_PROBES_ENABLED=False. Turn it on deliberately, run, turn it off.')


def require_probes(what: str) -> None:
    if not probes_enabled():
        raise SoftechProbesDisabled(_message(what))


def command_require_probes(what: str) -> None:
    if not probes_enabled():
        from django.core.management.base import CommandError
        raise CommandError(_message(what))
