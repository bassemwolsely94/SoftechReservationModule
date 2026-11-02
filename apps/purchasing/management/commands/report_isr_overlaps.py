"""
P-32 §2.4 — how often did a pushed ISR repeat items already pushed to the same destination (same kind) in the
DUP_PUSH_DAYS days before it and not yet dispensed by then (owner 2026-11-01)? Read-only (PostgreSQL IsrPush history only). Run it before switching
SystemSetting `isr_overlap_guard` on: a high count on the daily HQ → branch route means the rule as written would
stop normal replenishment and needs the owner's refinement first.

    python manage.py report_isr_overlaps --days 90
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'P-32: count pushed ISRs that repeated items of an earlier push to the same destination (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--examples', type=int, default=10)

    def handle(self, *args, **o):
        from apps.purchasing import isr_guards as G
        from apps.purchasing.models import IsrPush as P
        since = timezone.now() - timedelta(days=o['days'])
        window = timedelta(days=G.DUP_PUSH_DAYS)
        pushes = list(P.objects.filter(status=P.STATUS_PUSHED, pushed_at__gte=since - window)
                      .only('id', 'kind', 'branchcode', 'dest_branchcode', 'lines_snapshot', 'isrdocnumber',
                            'pushed_at', 'origin_isr', 'origin_request_id', 'origin_shortage_list_id')
                      .order_by('pushed_at'))
        by_dest = defaultdict(list)
        counted = with_overlap = lines = 0
        per_route = Counter()
        examples = []
        for p in pushes:
            key = (p.kind, p.dest_branchcode)
            earlier = [x for x in by_dest[key] if x.pushed_at >= p.pushed_at - window]
            by_dest[key].append(p)
            if p.pushed_at < since:
                continue
            counted += 1
            rows = G.overlapping_pushed(p, pushed=earlier, before=p.pushed_at)   # dispensed before this push
            if rows:
                with_overlap += 1
                lines += len(rows)
                per_route[f'{p.branchcode}→{p.dest_branchcode or p.branchcode} ({p.kind})'] += 1
                if len(examples) < o['examples']:
                    origin = ('request' if p.origin_request_id else 'shortage list' if p.origin_shortage_list_id
                              else 'branch ISR' if p.origin_isr else 'general')
                    examples.append(f'  #{p.pk} ISR {p.isrdocnumber} {p.pushed_at:%Y-%m-%d} [{origin}] '
                                    f'{len(rows)}/{len(p.lines_snapshot or [])} lines repeat '
                                    f'#{sorted({r["push_id"] for r in rows})}')
        self.stdout.write(f'last {o["days"]} days, window {G.DUP_PUSH_DAYS} days: pushes {counted} · '
                          f'with overlap {with_overlap} · overlapping lines {lines}')
        for route, n in per_route.most_common():
            self.stdout.write(f'  {route}: {n}')
        for e in examples:
            self.stdout.write(e)
        self.stdout.write(f'guard is {"ON" if G.overlap_guard_on() else "OFF"} (SystemSetting isr_overlap_guard)')
