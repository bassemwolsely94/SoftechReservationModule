"""
manage.py csp_report_summary — group the CSP violation reports in the log (D-04).

/api/csp-report/ stores nothing; each report is one `elrezeiky.csp` log line (core/csp.py). This
reads those lines and prints one row per (directive, blocked source, page, mode) with a count and
the first / last time seen, so the policy in deploy/nginx-csp.conf can be reviewed.

    python manage.py csp_report_summary                     # logs/platform.log* (7 days kept)
    python manage.py csp_report_summary --markdown          # a table to paste into a PR
    journalctl -u elrezeiky-web --since -30d | python manage.py csp_report_summary -

Read only. Pages are paths with ids folded and no query string (portal links carry tokens).
"""
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.csp import summarize


class Command(BaseCommand):
    help = 'Group the CSP violation reports from the log (directive × blocked source × page).'

    def add_arguments(self, parser):
        parser.add_argument('files', nargs='*',
                            help='log files to read; "-" = stdin; default logs/platform.log*')
        parser.add_argument('--markdown', action='store_true', help='print a Markdown table')

    def _lines(self, files):
        if files == ['-']:
            yield from sys.stdin
            return
        paths = [Path(f) for f in files] or sorted((Path(settings.BASE_DIR) / 'logs').glob('platform.log*'))
        for path in paths:
            with open(path, encoding='utf-8', errors='replace') as fh:
                yield from fh

    def handle(self, *args, files=(), markdown=False, **options):
        rows = summarize(self._lines(list(files)))
        if not rows:
            self.stdout.write('No CSP reports found.')
            return
        cols = ('count', 'directive', 'blocked', 'page', 'mode', 'first', 'last', 'verdict')
        if markdown:
            self.stdout.write('| ' + ' | '.join(cols) + ' |')
            self.stdout.write('|' + '---|' * len(cols))
            for r in rows:
                self.stdout.write('| ' + ' | '.join(str(r[c]).replace('|', '\\|') for c in cols) + ' |')
        else:
            for r in rows:
                self.stdout.write('  '.join(f'{c}={r[c]}' for c in cols))
        self.stdout.write(f'{sum(r["count"] for r in rows)} reports in {len(rows)} groups.')
