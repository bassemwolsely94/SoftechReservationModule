"""
manage.py access_preflight — is it safe to switch NETWORK_POLICY_ENFORCEMENT to enforce? (N3)

Read-only. Prints an Arabic + English checklist; exit code 1 when anything blocks the switch.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.access import preflight
from apps.access.policy_middleware import _mode

MARK = {preflight.OK: '✔', preflight.WARN: '!', preflight.BLOCK: '✘'}


class Command(BaseCommand):
    help = 'Pre-enforce checklist for the zone policy (read-only; exit 1 on blockers).'

    def handle(self, *args, **options):
        items = preflight.run()
        self.stdout.write(f'Zone policy preflight — current mode: {_mode()}')
        for item in items:
            line = f' {MARK[item.level]} [{item.code}] {item.ar}\n     {item.en}'
            style = {preflight.OK: self.style.SUCCESS, preflight.WARN: self.style.WARNING,
                     preflight.BLOCK: self.style.ERROR}[item.level]
            self.stdout.write(style(line))
            for name in item.names:
                self.stdout.write(f'       - {name}')
        blocking = preflight.blockers(items)
        warns = sum(1 for i in items if i.level == preflight.WARN)
        if blocking:
            raise CommandError(f'لا تفعّل enforce بعد — {len(blocking)} عائق / NOT ready for enforce: '
                               f'{len(blocking)} blocker(s), {warns} warning(s)', returncode=1)
        self.stdout.write(self.style.SUCCESS(
            f'جاهز للتفعيل / Ready for enforce ({warns} warning(s) to read first)'))
