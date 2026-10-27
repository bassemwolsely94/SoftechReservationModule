"""
python manage.py topup_coverage                     # DRY-RUN: what the top-up would do now
python manage.py topup_coverage --branch 130        # one branch
python manage.py topup_coverage --commit            # LIVE (needs COVERAGE_WRITER_ENABLED)
python manage.py topup_coverage --status            # recent top-ups + whether one is due

Brings each branch in line with the latest engine run: items with NO coverage get the
default (COVERAGE_AUTO_TOPUP_MONTHS), stale maxes are refreshed; a coverage set on
purpose is never changed; branch 100's own rows are never written. The scheduler runs
the same thing automatically when COVERAGE_AUTO_TOPUP_ENABLED is on.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.purchasing import coverage_writer as cw


class Command(BaseCommand):
    help = 'Coverage top-up after an engine run (gated dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument('--branch', action='append', default=None)
        parser.add_argument('--months', type=float, default=None,
                            help='default coverage for items that have none (default: setting)')
        parser.add_argument('--target', default=None, choices=['node', 'hq', 'both'],
                            help='default: COVERAGE_AUTO_TOPUP_TARGET (node)')
        parser.add_argument('--commit', action='store_true')
        parser.add_argument('--status', action='store_true')

    def handle(self, *a, **o):
        if o['status']:
            return self._status()
        if o['commit'] and not cw.coverage_writer_enabled():
            raise CommandError('COVERAGE_WRITER_ENABLED is off — refusing --commit.')

        res = cw.topup_coverage(months=o['months'], target=o['target'],
                                branch_filter=o['branch'], dry_run=not o['commit'])
        if res['mode'] == 'commit':
            p = cw.persist_topup(res, trigger='manual')
            saved = f' — saved CoverageTopUp #{p.pk}'
        else:
            saved = ''
        t = res['totals']
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ coverage top-up — {res["mode"].upper()} — engine run {res["run_id"]} — '
            f'default {res["months"]} months — target={res["target"]} ═══'))
        self.stdout.write(f'  fill (no coverage yet): {t["fill"]}   refresh (stale max): {t["refresh"]}   '
                          f'no row on server: {t["missing"]}   unreachable: {t["unreachable"]}')
        if res['mode'] == 'commit':
            self.stdout.write(f'  verified: {t["verified"]}   not confirmed: {t["not_confirmed"]}   '
                              f'status: {res["status"]}{saved}')
        for r in res['branches']:
            head = f'  · branch {r["branchcode"]} [{r["surface"]}] items {r["items"]}'
            if not r['reachable']:
                self.stdout.write(self.style.WARNING(f'{head}: UNREACHABLE ({r.get("error")})'))
                continue
            line = f'{head}: fill {r["fill"]}  refresh {r["refresh"]}  missing {r["missing"]}'
            if res['mode'] == 'commit':
                line += f'  → verified {r["verified"]}  not confirmed {r["not_confirmed"]}'
            self.stdout.write(line)
            if r.get('error'):
                self.stdout.write(self.style.WARNING(f'      connection dropped, resumed: {r["error"][:250]}'))
        s = cw.topup_settings()
        self.stdout.write(f'\n  automatic top-up: {"ON" if s["enabled"] else "OFF"} '
                          f'(COVERAGE_AUTO_TOPUP_ENABLED)')

    def _status(self):
        from apps.purchasing.models import CoverageTopUp
        run = cw._latest_run()
        s = cw.topup_settings()
        self.stdout.write(f'automatic top-up: {"ON" if s["enabled"] else "OFF"} | default '
                          f'{s["months"]} months | target {s["target"]}')
        if run is not None:
            self.stdout.write(f'latest engine run: {run.id} (finished {run.finished_at}) — '
                              f'top-up due: {cw.topup_due(run)}')
        for p in CoverageTopUp.objects.all()[:10]:
            self.stdout.write(f'  #{p.pk} run {p.run_id} {p.status:<8} {p.trigger:<8} '
                              f'{p.created_at:%Y-%m-%d %H:%M}  fill {p.filled_count} '
                              f'refresh {p.refreshed_count} verified {p.verified_count} '
                              f'not confirmed {p.not_confirmed_count} unreachable {p.unreachable_count}')
