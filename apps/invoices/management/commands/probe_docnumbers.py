"""
Diagnose why specific invoice numbers come back NOT FOUND in the benchmark.

The benchmark matches a detected invoice number against stktransm.docnumber2 for
doccode=10 (purchases) within a date window. A NOT FOUND can mean three very
different things, and we can't fix what we can't name:
  1. the invoice simply isn't posted in the window (nothing to match),
  2. it's posted under a DIFFERENT doccode (a reservation 80/180/81, a return, …),
  3. our OCR'd number is wrong in a way truncation can't repair.

This probe does ONE wide scan of stktransm over a window across ALL doccodes, then
for each target number tries the same truncation variants the benchmark uses and
reports every hit (doccode, docnumber, docnumber2, docdate) — or says it's absent
everywhere. That tells us (2) vs (1)/(3) immediately, and the hit's doccode names
exactly which screen the invoice actually lives on.

Usage:
  python manage.py probe_docnumbers 13260608845574 182606330555 182850341 1825060879694 \
      --host 192.168.1.8 --since 2026-07-01
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError


def _digits(s) -> str:
    return re.sub(r'\D', '', str(s or ''))


def _variants(target: str) -> list[str]:
    """The same family of trimmings the benchmark's _resolve tries, widened: the
    raw value, each end trimmed to 9–12 digits, and one digit off either end."""
    t = _digits(target)
    out: set[str] = set()
    if t:
        out.add(t)
        for length in (12, 11, 10, 9):
            if len(t) > length:
                out.add(t[:length])    # drop trailing (barcode check digits)
                out.add(t[-length:])   # drop leading (barcode marker digits)
        if len(t) > 6:
            out.add(t[:-1])
            out.add(t[1:])
    return sorted((v for v in out if len(v) >= 6), key=lambda s: (-len(s), s))


class Command(BaseCommand):
    help = "Check whether invoice numbers exist anywhere in SofTech stktransm (any doccode)."

    def add_arguments(self, parser):
        parser.add_argument('numbers', nargs='+', help='Invoice numbers to look up.')
        parser.add_argument('--host', default='192.168.1.8')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--db', default='SOFTECHDB9')
        parser.add_argument('--since', default=None,
                            help="docdate lower bound 'YYYY-MM-DD' (default: 180 days back).")
        parser.add_argument('--timeout', type=int, default=600)

    def handle(self, *args, **o):
        import datetime

        since = o['since']
        if not since:
            since = (datetime.date.today() - datetime.timedelta(days=180)).strftime('%Y-%m-%d')

        try:
            from config.sybase import get_branch_connection
            conn = get_branch_connection(o['host'], o['port'], o['db'], charset='cp1256')
        except Exception as e:
            raise CommandError(f"Cannot reach SofTech {o['host']}: {e}")

        self.stdout.write(f"scanning stktransm (all doccodes) since {since} … "
                          f"(docnumber2 is unindexed — one pass)")
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT doccode, docnumber, docnumber2, docdate "
                f"FROM stktransm WHERE docdate >= '{since}'", timeout=o['timeout'])
        except Exception as e:
            raise CommandError(f"scan failed: {str(e)[:120]}")

        by_d2: dict[int, list] = {}
        by_dn: dict[int, list] = {}
        n = 0
        for r in cur.fetchall():
            n += 1
            rec = {'doccode': str(r[0]).strip(), 'docnumber': r[1],
                   'docnumber2': r[2], 'docdate': str(r[3])[:10]}
            try:
                d2 = int(r[2] or 0)
                if d2 > 0:
                    by_d2.setdefault(d2, []).append(rec)
            except (TypeError, ValueError):
                pass
            try:
                dn_ = int(r[1] or 0)
                if dn_ > 0:
                    by_dn.setdefault(dn_, []).append(rec)
            except (TypeError, ValueError):
                pass
        conn.close()
        self.stdout.write(f"  scanned {n} header rows "
                          f"({len(by_d2)} distinct docnumber2, {len(by_dn)} distinct docnumber)\n")

        for target in o['numbers']:
            self.stdout.write(self.style.MIGRATE_HEADING(f"── {target} ──"))
            vs = _variants(target)
            self.stdout.write(f"  variants: {', '.join(vs)}")
            hits = []
            seen = set()
            for v in vs:
                try:
                    iv = int(v)
                except ValueError:
                    continue
                for field, table in (('docnumber2', by_d2), ('docnumber', by_dn)):
                    for rec in table.get(iv, []):
                        key = (rec['doccode'], rec['docnumber'], rec['docnumber2'])
                        if key in seen:
                            continue
                        seen.add(key)
                        hits.append((v, field, rec))
            if not hits:
                self.stdout.write(self.style.WARNING(
                    "  NOT FOUND in any doccode within the window → likely UNPOSTED "
                    "(or OCR number wrong beyond repair). Widen --since to rule out window."))
            else:
                for v, field, rec in hits:
                    tag = '' if v == _digits(target) else f' (via variant {v})'
                    self.stdout.write(self.style.SUCCESS(
                        f"  FOUND {field}={rec['docnumber2']} docnumber={rec['docnumber']} "
                        f"doccode={rec['doccode']} date={rec['docdate']}{tag}"))
            self.stdout.write('')
