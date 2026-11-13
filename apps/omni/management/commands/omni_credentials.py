"""
Channel-credentials key status and re-key (go-live 2026-11-12). Never prints a credential or a key.

    manage.py omni_credentials                  # counts per key state; exit 1 if any row is not under the env key
    manage.py omni_credentials --rekey          # dry run: what a re-key would change
    manage.py omni_credentials --rekey --apply  # re-encrypt every readable row under OMNI_CREDENTIALS_KEY

States: env = readable with OMNI_CREDENTIALS_KEY (portable to the VPS); derived = readable only with the
SECRET_KEY-derived key (needs --rekey); plain = legacy unencrypted (also re-keyed); unreadable = no key in
this .env opens it (a re-key cannot fix it: re-enter that account's credentials on /omni).
"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.omni.crypto import env_key, env_key_problem, key_state, rekey_credentials
from apps.omni.models import ChannelAccount


class Command(BaseCommand):
    help = 'Show which key opens each channel account\'s stored credentials; --rekey moves them to OMNI_CREDENTIALS_KEY.'

    def add_arguments(self, parser):
        parser.add_argument('--rekey', action='store_true', help='Re-encrypt under OMNI_CREDENTIALS_KEY (dry run).')
        parser.add_argument('--apply', action='store_true', help='With --rekey: write the change.')

    def handle(self, *args, rekey=False, apply=False, **opts):
        if apply and not rekey:
            raise CommandError('--apply only goes with --rekey.')
        problem = env_key_problem()
        if problem:
            raise CommandError(f'OMNI_CREDENTIALS_KEY is set but {problem}. Fix .env first.')
        has_key = bool(env_key())

        states = {a.pk: key_state(a.credentials) for a in ChannelAccount.objects.only('pk', 'credentials')}
        counts = Counter(states.values())
        self.stdout.write(f'OMNI_CREDENTIALS_KEY: {"set" if has_key else "NOT SET (SECRET_KEY-derived key in use)"}')
        for state in ('env', 'derived', 'plain', 'unreadable', 'empty'):
            self.stdout.write(f'  {state:<11} {counts.get(state, 0)}')
        unreadable = sorted(pk for pk, s in states.items() if s == 'unreadable')
        if unreadable:
            self.stdout.write(f'  unreadable account ids (re-enter their credentials on /omni): {unreadable}')

        todo = sorted(pk for pk, s in states.items() if s in ('derived', 'plain'))
        if not rekey:
            if not has_key or todo or unreadable:
                raise CommandError('Not every stored credential is under OMNI_CREDENTIALS_KEY.')
            self.stdout.write(self.style.SUCCESS('OK: every stored credential opens with OMNI_CREDENTIALS_KEY.'))
            return

        if not has_key:
            raise CommandError('Set OMNI_CREDENTIALS_KEY in .env and restart before --rekey.')
        self.stdout.write(f'To re-key: {len(todo)} account(s) {todo}')
        if not apply:
            self.stdout.write('Dry run: nothing written. Add --apply to write.')
            return
        with transaction.atomic():
            for acc in ChannelAccount.objects.select_for_update().filter(pk__in=todo):
                if key_state(acc.credentials) not in ('derived', 'plain'):
                    continue
                acc.credentials = rekey_credentials(acc.credentials)
                acc.save(update_fields=['credentials'])
            _audit(todo)
        self.stdout.write(self.style.SUCCESS(f'Re-keyed {len(todo)} account(s).'))


def _audit(ids):
    from apps.audit.models import AuditLog
    AuditLog.objects.create(
        action='omni_credentials_rekeyed', model_name='omni.ChannelAccount', object_id=','.join(map(str, ids))[:50],
        object_repr=f'{len(ids)} channel account(s)', user_name='manage.py omni_credentials',
        new_data={'account_ids': ids, 'key': 'OMNI_CREDENTIALS_KEY'},
        note='Channel credentials re-encrypted under OMNI_CREDENTIALS_KEY (values unchanged)')
