"""
python manage.py push_ap_allocations_bulk [--confidence high] [--limit N] [--commit]

Record APPROVED mirror allocations into SOFTECH (chequestrans + stktransm) in bulk,
over ONE shared HQ connection. Without --commit (or with the writer flag off) it is
a dry run that only validates plans.

Safety (doc 23 §11/§14):
  • per-row validation failures (invoice already paid another way, voucher already
    fully allocated, foreign currency…) are SKIPPED and counted by reason;
  • an INTEGRITY failure (a half-landed write) STOPS the whole run immediately;
  • every live attempt — written, skipped-as-present or failed — is audited;
  • idempotent: re-running skips rows already present in SOFTECH.
"""
from collections import Counter

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Bulk-write approved A/P allocations to SOFTECH (gated, idempotent, stop-on-integrity-error)'

    def add_arguments(self, parser):
        parser.add_argument('--confidence', default='high',
                            help="candidate confidence class to write ('high', 'medium', … or 'all')")
        parser.add_argument('--strategy', default='', help='limit to one matching strategy')
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--commit', action='store_true', help='actually write (needs the flag ON)')
        parser.add_argument('--reconnect-every', type=int, default=500)
        parser.add_argument('--shard', default='',
                            help="'i/N' — only suppliers with party_id mod N == i. Shards are "
                                 "disjoint by supplier (so by voucher AND invoice), which makes "
                                 "parallel runs safe. Never run a sharded and an unsharded pass "
                                 "at the same time.")

    def _reconnect(self, attempts=10, wait_s=60):
        """HQ dropped mid-run: wait and retry instead of crashing. None = give up."""
        import time
        from config.sybase import get_sybase_connection
        for i in range(attempts):
            try:
                return get_sybase_connection()
            except Exception as exc:
                self.stdout.write(f'  reconnect {i + 1}/{attempts} failed: {str(exc)[:80]}')
                self.stdout.flush()
                time.sleep(wait_s)
        return None

    def handle(self, *args, **o):
        from apps.finance import recon_writer as W
        from apps.finance.models import Allocation
        from config.sybase import get_sybase_connection

        live = o['commit'] and W.writer_enabled()
        if o['commit'] and not W.writer_enabled():
            self.stdout.write(self.style.WARNING('writer flag is OFF → dry run only'))

        qs = (Allocation.objects.filter(origin=Allocation.ORIGIN_APPROVED)
              .select_related('payment', 'invoice', 'invoice__party', 'candidate')
              .order_by('payment__voucher_date', 'payment_id', 'invoice__docdate'))
        if o['confidence'] != 'all':
            qs = qs.filter(candidate__confidence_class=o['confidence'])
        if o['strategy']:
            qs = qs.filter(candidate__strategy=o['strategy'])
        if o['shard']:
            i, n = (int(x) for x in o['shard'].split('/'))
            qs = qs.extra(where=['("finance_apinvoice"."party_id" %% %s) = %s'], params=[n, i])
        ids = list(qs.values_list('id', flat=True))
        if o['limit']:
            ids = ids[:o['limit']]
        self.stdout.write(f"{'LIVE' if live else 'DRY-RUN'}: {len(ids)} approved allocations to write")

        stats, reasons = Counter(), Counter()
        amount_written = 0
        touched = set()                  # invoices written this round → date-order re-chain
        conn = self._reconnect() if live else None
        if live and conn is None:
            self.stdout.write(self.style.ERROR('HQ unreachable — nothing written; re-run later'))
            return
        try:
            for n, aid in enumerate(ids, 1):
                if live and n % o['reconnect_every'] == 0:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = self._reconnect()
                    if conn is None:
                        self.stdout.write(self.style.ERROR(
                            f'HQ unreachable — stopping cleanly at {n}/{len(ids)}; re-run to resume'))
                        break
                alloc = qs.model.objects.select_related(
                    'payment', 'invoice', 'invoice__party').get(pk=aid)
                if alloc.origin != Allocation.ORIGIN_APPROVED:
                    stats['changed_meanwhile'] += 1
                    continue
                try:
                    res = W.push_allocation(alloc, dry_run=not live, conn=conn)
                except W.ReconWriteIntegrityError as exc:
                    self.stdout.write(self.style.ERROR(f'INTEGRITY STOP at allocation {aid}: {exc}'))
                    stats['integrity_stop'] += 1
                    break
                except W.ReconWriteError as exc:
                    stats['skipped'] += 1
                    reasons[str(exc).split('(')[0].strip()[:70]] += 1
                    continue
                except Exception as exc:          # connection hiccup → reconnect, retry once
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = self._reconnect() if live else None
                    if live and conn is None:
                        self.stdout.write(self.style.ERROR(
                            f'HQ unreachable — stopping cleanly at {n}/{len(ids)}; re-run to resume'))
                        stats['stopped_network'] += 1
                        break
                    try:
                        res = W.push_allocation(alloc, dry_run=not live, conn=conn)
                    except W.ReconWriteIntegrityError as exc2:
                        self.stdout.write(self.style.ERROR(f'INTEGRITY STOP at allocation {aid}: {exc2}'))
                        stats['integrity_stop'] += 1
                        break
                    except Exception as exc2:
                        stats['error'] += 1
                        reasons[f'error: {str(exc2)[:60]}'] += 1
                        continue
                if res.get('already_present'):
                    stats['already_present'] += 1
                elif res.get('written'):
                    stats['written'] += 1
                    amount_written += alloc.amount
                    touched.add(alloc.invoice_id)
                else:
                    stats['dry_run_ok'] += 1
                if n % 250 == 0:
                    self.stdout.write(f'  … {n}/{len(ids)} {dict(stats)} ({amount_written} EGP)')
                    self.stdout.flush()
            # every write round ends with the date-order re-chain of what it wrote
            if live and touched and not stats['integrity_stop']:
                if conn is None:
                    conn = self._reconnect()
                if conn is not None:
                    rc = W.rechain_after_write(touched, conn=conn)
                    self.stdout.write(f"RECHAIN {len(touched)} invoices written → re-chained {rc['invoices']} "
                                      f"({rc['rows_changed']} rows, «مغلق» on {rc['now_closed']}) "
                                      f"skipped {rc['skipped']} {rc['errors'] or ''}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        self.stdout.write(self.style.SUCCESS(f'DONE {dict(stats)} — written {amount_written} EGP'))
        for r, c in reasons.most_common(12):
            self.stdout.write(f'  skip reason ×{c}: {r}')
