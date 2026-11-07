"""python manage.py lifecycle list
python manage.py lifecycle preview <key>
python manage.py lifecycle set <key> --mode M [--keep-days N] --user USERNAME --reason R
python manage.py lifecycle restore <held_id> --user USERNAME

`set` goes only through policy.set_policy and `restore` only through holding.restore. They audit the change
and hold the refusals; the admin-only check is here because the services leave it to their caller (design §7)."""
from django.core.management.base import BaseCommand, CommandError

from apps.data_lifecycle.holding import HoldError, restore
from apps.data_lifecycle.policy import PolicyRefused, get_mode, keep_days, set_policy
from apps.data_lifecycle.register import RULES
from apps.data_lifecycle.runner import preview_rule
from apps.users.models import StaffProfile


class Command(BaseCommand):
    help = 'List, preview and change the data lifecycle rules.'

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest='action', required=True)
        actions.add_parser('list', help='Every rule with its mode and period')
        preview = actions.add_parser('preview', help='Count what a rule would remove; changes nothing')
        preview.add_argument('key')
        change = actions.add_parser('set', help="Change a rule's mode and period")
        change.add_argument('key')
        change.add_argument('--mode', required=True)
        change.add_argument('--keep-days', type=int)
        change.add_argument('--user', required=True, help='username of an active admin')
        change.add_argument('--reason', required=True)
        back = actions.add_parser('restore', help='Put a held file back where it was')
        back.add_argument('held_id', type=int)
        back.add_argument('--user', required=True, help='username of an active admin')

    def handle(self, *args, **opts):
        {'list': self._list, 'preview': self._preview, 'set': self._set, 'restore': self._restore}[opts['action']](opts)

    def _list(self, opts):
        for key, rule in RULES.items():
            self.stdout.write(f'{key}\t{rule.kind}\t{get_mode(key)}\t{keep_days(key) or "-"}\t{rule.label_en}')

    def _preview(self, opts):
        try:
            line = preview_rule(opts['key'])
        except ValueError as exc:
            raise CommandError(str(exc))
        if line.error:
            raise CommandError(line.error)
        self.stdout.write(f'{opts["key"]}: {line.count} candidates, {line.bytes} bytes')

    def _admin(self, opts):
        staff = StaffProfile.objects.filter(user__username=opts['user']).select_related('user').first()
        if staff is None or staff.role != 'admin' or not (staff.is_active and staff.user.is_active):
            raise CommandError('--user must be an active admin')
        return staff

    def _set(self, opts):
        staff = self._admin(opts)
        try:
            policy = set_policy(opts['key'], mode=opts['mode'], keep_days=opts['keep_days'], user=staff,
                                reason=opts['reason'])
        except PolicyRefused as exc:
            raise CommandError(str(exc))
        self.stdout.write(f'{policy.rule_key}: mode {policy.mode}, period {keep_days(policy.rule_key) or "-"}')

    def _restore(self, opts):
        staff = self._admin(opts)
        try:
            held = restore(opts['held_id'], staff)
        except HoldError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f'held {held.pk}: restored')
