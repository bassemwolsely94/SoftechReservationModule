"""
migrate_call_center_to_crew  (crews piece 2b Part B, Task 5) — ONE-SHOT.

Moves the call center's history from the fake «CC» branch to the call-center crew and closes the
branch (apps/crews/cc_switch.py). Dry-run by default: prints per month × metric
«stored → new (source)», the targets that move with their attainment before/after (board figure,
October 2026 marked), the forecast rows count and the branch kind change.

  python manage.py migrate_call_center_to_crew                        # dry run
  python manage.py migrate_call_center_to_crew --out plan.json        # + the plan as JSON
  python manage.py migrate_call_center_to_crew --apply --confirm-months 28 --plan plan.json       --user <username>

--apply runs in one transaction and requires --confirm-months equal to the planned month count;
with --plan (the reviewed dry run's JSON) it also refuses when any month x metric figure differs.
--user puts that staff member on every audit row (default: none).
Run the dry run and --apply straight after `migrate`: between them the board's call-center block,
crew targets and the chain call_count read the crew while the history is still on CC (0 / short).
Run --apply while the scheduler's KPI refresh is quiet (not right after a sales sync): the
transaction re-reads ~28 months of SOFTECH returns and the CDR before it writes.
A second run reports 0 months and «nothing to move». No SOFTECH writes.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from apps.crews import cc_seed, cc_switch


class Command(BaseCommand):
    help = 'One-shot: move the call-center history from the CC branch to the crew; close CC.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='write (default: dry run)')
        parser.add_argument('--confirm-months', type=int,
                            help='required with --apply: the month count the dry run printed')
        parser.add_argument('--out', help='write the plan as JSON to this path')
        parser.add_argument('--plan', help='with --apply: the reviewed dry run JSON (--out); '
                                           'refuse when any figure differs')
        parser.add_argument('--user', help='our username of the person running it (audit)')

    def handle(self, *args, **o):
        if o['apply'] and o.get('confirm_months') is None:
            raise CommandError('--apply requires --confirm-months N (run the dry run first).')
        if o.get('plan') and not o['apply']:
            raise CommandError('--plan is for --apply (the dry run writes it with --out).')
        user = self._user(o.get('user'))
        reviewed = None
        if o.get('plan'):
            try:
                with open(o['plan'], encoding='utf-8') as fh:
                    reviewed = json.load(fh)
            except (OSError, ValueError) as exc:
                raise CommandError(f"cannot read --plan {o['plan']}: {exc}")
        try:
            if o['apply']:
                plan = cc_switch.apply_switch(user, confirm_months=o['confirm_months'],
                                              reviewed_plan=reviewed)
            else:
                plan = cc_switch.plan_switch(user)
        except (cc_switch.SwitchRefused, cc_seed.CcCrewNameTaken) as exc:
            raise CommandError(str(exc))
        self._print(plan, applied=o['apply'])
        if o.get('out'):
            with open(o['out'], 'w', encoding='utf-8') as fh:
                json.dump(plan, fh, ensure_ascii=False, indent=2)
            self.stdout.write(f"Plan written to {o['out']}")

    @staticmethod
    def _user(username):
        if not username:
            return None
        from apps.users.models import StaffProfile
        user = (StaffProfile.objects.select_related('user')
                .filter(user__username__iexact=username).first())
        if user is None:
            raise CommandError(f'no staff profile for username {username!r}')
        return user

    def _print(self, plan, *, applied):
        w = self.stdout.write
        tag = 'APPLIED' if applied else 'DRY RUN'
        if plan['nothing_to_move']:
            w(f'{tag}: 0 months — nothing to move.')
            return
        crew = 'seeded in the same transaction' if plan['seeds_crew'] else f"crew {plan['crew_id']}"
        w(f"{tag}: {plan['month_count']} month(s); {crew}")
        for mp in plan['months']:
            notes = f"  notes: {', '.join(mp['notes'])}" if mp['notes'] else ''
            w(f"{mp['year']}-{mp['month']:02d}{notes}")
            for r in mp['metrics']:
                w(f"  {r['metric']:<16} {r['stored'] or '—'} → {r['new']} ({r['source']}) "
                  f"[{r['action']}]")
        fy, fm = plan['focus_month']
        w(f"Targets moving to the crew: {len(plan['targets'])} "
          f"(* = covers {fy}-{fm:02d})")
        for t in plan['targets']:
            mark = '*' if t['id'] in plan['focus_targets'] else ' '
            w(f"  {mark} #{t['id']} {t['metric']} {t['period']} target {t['target']}: "
              f"board {t['achieved_before']} ({t['pct_before']}%) → "
              f"{t['achieved_after']} ({t['pct_after']}%)")
        w(f"Forecast rows moving to the crew: {plan['forecast_count']}")
        b = plan['branch']
        w(f"CC branch #{b['id']} kind: {b['kind_before']} → {b['kind_after']}")
        if not applied:
            w(f"To apply: --apply --confirm-months {plan['month_count']}")
