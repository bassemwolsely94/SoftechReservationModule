"""
migrate_call_center_to_crew  (crews piece 2b Part B, Task 5) — ONE-SHOT.

Moves the call center's history from the fake «CC» branch to the call-center crew and closes the
branch (apps/crews/cc_switch.py). Dry-run by default: prints per month × metric
«stored → new (source)», the targets that move with their attainment before/after (board figure,
October 2026 marked), the forecast rows count and the branch kind change.

  python manage.py migrate_call_center_to_crew                        # dry run
  python manage.py migrate_call_center_to_crew --out plan.json        # + the plan as JSON
  python manage.py migrate_call_center_to_crew --apply --confirm-months 28

--apply runs in one transaction and requires --confirm-months equal to the planned month count.
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

    def handle(self, *args, **o):
        if o['apply'] and o.get('confirm_months') is None:
            raise CommandError('--apply requires --confirm-months N (run the dry run first).')
        try:
            if o['apply']:
                plan = cc_switch.apply_switch(None, confirm_months=o['confirm_months'])
            else:
                plan = cc_switch.plan_switch()
        except (cc_switch.SwitchRefused, cc_seed.CcCrewNameTaken) as exc:
            raise CommandError(str(exc))
        self._print(plan, applied=o['apply'])
        if o.get('out'):
            with open(o['out'], 'w', encoding='utf-8') as fh:
                json.dump(plan, fh, ensure_ascii=False, indent=2)
            self.stdout.write(f"Plan written to {o['out']}")

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
