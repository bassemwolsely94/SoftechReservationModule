"""Deploy checks for the channel-credentials key (go-live 2026-11-12). Run by `check --deploy` in release.sh."""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

from apps.omni.crypto import env_key, env_key_problem


@register(Tags.security, deploy=True)
def omni_credentials_key_check(app_configs, **kwargs):
    problem = env_key_problem()
    if problem:
        # A placeholder such as the template's old `CHANGE` makes saving any channel account fail and
        # silently empties every stored credential on read.
        return [Error(
            f'OMNI_CREDENTIALS_KEY is set but {problem}.',
            hint='Use the same key as the office: put the value from the password manager in .env, '
                 'or generate one with: python -c "from cryptography.fernet import Fernet; '
                 'print(Fernet.generate_key().decode())"',
            id='omni.E001')]
    if not env_key() and not settings.DEBUG:
        return [Warning(
            'OMNI_CREDENTIALS_KEY is empty: channel credentials are encrypted with a key derived from '
            'SECRET_KEY, so they cannot be read on a server with a different SECRET_KEY.',
            hint='Set one key on the office and the VPS, then run `manage.py omni_credentials --rekey --apply` '
                 'on the office (docs/deploy/2026-11-12-go-live-status.md).',
            id='omni.W001')]
    return []
