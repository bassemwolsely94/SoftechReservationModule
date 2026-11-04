"""
python manage.py writer_status [--expect reader|writer]

P-54 cutover check: prints this instance's SOFTECH role from the .env it would start with —
WRITER_INSTANCE, SOFTECH_READ_ONLY and every writer flag (value + effective) — without starting
anything. Read-only; never connects to SOFTECH.

--expect reader   exit 1 unless no writer gate can open here (WRITER_INSTANCE=False or
                  SOFTECH_READ_ONLY=True). Run it on the office copy before the VPS writes.
--expect writer   exit 1 unless WRITER_INSTANCE=True and SOFTECH_READ_ONLY=False.

Runbook §11 (deploy/LINKDATACENTER_VPS_RUNBOOK.md) and docs/GO_LIVE_CHECKLIST.md use it.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.writers import WRITER_FLAGS, duplicate_env_keys, default_env_path, writer_allowed, writer_instance


def can_write():
    """True when at least one SOFTECH write could get through on this instance."""
    return writer_instance() and not bool(getattr(settings, 'SOFTECH_READ_ONLY', False))


class Command(BaseCommand):
    help = 'Show this instance’s SOFTECH writer role (P-54); --expect reader|writer exits 1 on a mismatch.'

    def add_arguments(self, parser):
        parser.add_argument('--expect', choices=('reader', 'writer'))

    def handle(self, *args, **opts):
        read_only = bool(getattr(settings, 'SOFTECH_READ_ONLY', False))
        out = self.stdout.write
        out(f'WRITER_INSTANCE   = {writer_instance()}')
        out(f'SOFTECH_READ_ONLY = {read_only}')
        for flag in WRITER_FLAGS:
            value = bool(getattr(settings, flag, False))
            out(f'  {flag:<38} value={str(value):<5} effective={writer_allowed(flag)}')
        dups = duplicate_env_keys(default_env_path())
        if dups:
            out(self.style.WARNING('duplicated .env keys: ' + ', '.join(k for k, _, _ in dups)))
        role = 'writer' if can_write() else 'reader'
        out(f'ROLE = {role}')

        expect = opts.get('expect')
        if expect and expect != role:
            raise CommandError(f'expected {expect}, but this instance is a {role}')
        if dups:
            raise CommandError('duplicated .env keys — the web process and the scheduler refuse to start')
