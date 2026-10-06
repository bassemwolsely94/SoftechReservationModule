"""
fix_ap_due_before — correct chequestrans.docvaluepaid («مبلغ مستحق») on the links OUR
writer put in SOFTECH (they held cumulative-paid-after; SOFTECH means owed-before, so
«مغلق» never showed on the payment that cleared an invoice). Per invoice, live from
SOFTECH, our links chained chronologically after native ones; native links untouched.
Dry-run unless --commit. See recon_writer.fix_due_before / doc 23.
"""
import time
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from apps.finance import recon_writer as W
from apps.finance.models import Allocation, ReconAuditEvent


class Command(BaseCommand):
    help = 'Correct «مبلغ مستحق» (docvaluepaid) on our written SOFTECH links (dry-run unless --commit).'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true')
        parser.add_argument('--limit', type=int, default=0, help='max invoices (0 = all)')
        parser.add_argument('--invoice', type=int, help='one APInvoice id')

    def _connect(self):
        from config.sybase import get_sybase_connection
        for i in range(30):
            try:
                return get_sybase_connection()
            except Exception as exc:
                self.stdout.write(f'  HQ reconnect {i + 1}: {str(exc)[:70]}')
                time.sleep(30)
        raise SystemExit('HQ unreachable — stopping')

    def _needing_fix(self, conn, groups):
        """Fast prefilter: one bulk dirty read of every chequestrans link, targets from
        the mirror header — keep only invoices where one of OUR rows looks different.
        Each kept invoice is then re-checked LIVE by fix_due_before (the real decision)."""
        from decimal import Decimal as D
        cur = conn.cursor()
        cur.execute(f"SELECT cheqsno, cheqbranchcode, branchcode, doccode, docnumber, "
                    f"CONVERT(char(10), docdate, 111), docvaluepaid FROM {W.DB}.chequestrans "
                    f"WHERE doccode IN ('10','120') AT ISOLATION 0")
        stored = {(int(r[0]), str(r[1]).strip(), str(r[2]).strip(), str(r[3]).strip(), int(r[4]),
                   str(r[5]).strip().replace('/', '-')): D(str(r[6])) for r in cur.fetchall()}
        keep = []
        for allocs in groups:
            inv = allocs[0].invoice
            try:
                targets = W.due_chain(inv.doc_value or D(0), inv.doc_value_pay or D(0),
                                      [((a.payment.voucher_date, a.payment.cheqsno, a.id), a.amount) for a in allocs])
            except W.ReconWriteError:
                keep.append(allocs)            # let the live check report why
                continue
            ordered = sorted(allocs, key=lambda a: (a.payment.voucher_date, a.payment.cheqsno, a.id))
            for a, t in zip(ordered, targets):
                k = (int(a.payment.cheqsno), a.payment.branchcode, inv.branchcode, inv.doccode,
                     int(str(inv.docnumber).split('.')[0]), inv.docdate.strftime('%Y-%m-%d'))
                if k not in stored or abs(stored[k] - t) > D('0.01'):
                    keep.append(allocs)
                    break
        return keep

    def handle(self, *args, **o):
        if o['commit'] and not W.writer_enabled():
            raise SystemExit('AP_RECONCILE_WRITER_ENABLED is off')
        ours = set(ReconAuditEvent.objects.filter(action='allocation_written')
                   .values_list('allocation_id', flat=True))
        # «ours» = every link we have an allocation_written audit for — the nightly ingest
        # re-labels them origin='softech' once it re-reads them from SOFTECH
        qs = Allocation.objects.filter(origin__in=[Allocation.ORIGIN_WRITTEN, Allocation.ORIGIN_SOFTECH],
                                       id__in=ours) \
            .select_related('invoice', 'invoice__party', 'payment')
        if o['invoice']:
            qs = qs.filter(invoice_id=o['invoice'])
        by_inv = defaultdict(list)
        for a in qs:
            by_inv[a.invoice_id].append(a)
        conn = self._connect()
        items = self._needing_fix(conn, list(by_inv.values()))
        if o['limit']:
            items = items[:o['limit']]
        mode = 'COMMIT' if o['commit'] else 'DRY-RUN'
        self.stdout.write(f'{mode}: {len(items)} of {len(by_inv)} invoices with our links need a check')
        stats, reasons, sample = Counter(), Counter(), []
        for n, allocs in enumerate(items, 1):
            inv = allocs[0].invoice
            for attempt in range(4):
                try:
                    res = W.fix_due_before(inv, allocs, conn=conn, commit=o['commit'])
                    ch = res['changes']
                    if ch:
                        stats['invoices_changed'] += 1
                        stats['rows_changed'] += len(ch)
                        stats['now_closed'] += sum(1 for c in ch if c['closes'])
                        if len(sample) < 10:
                            sample.append((inv.branchcode, inv.docnumber, ch))
                    else:
                        stats['already_right'] += 1
                    break
                except W.ReconWriteIntegrityError as e:
                    if 'could NOT be verified' in str(e) and attempt < 3:
                        # HQ dropped mid-transaction. Safe to redo: the targets come only from
                        # the header + paynow, never from the docvaluepaid being corrected, so
                        # re-applying converges whether the drop rolled back or committed.
                        self.stdout.write(f'  HQ drop on invoice {inv.id} — reconnecting and redoing it')
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = self._connect()
                        continue
                    self.stdout.write(self.style.ERROR(f'INTEGRITY STOP at invoice {inv.id}: {e}'))
                    return
                except W.ReconWriteError as e:
                    msg = str(e)
                    if 'lock' in msg.lower() or 'rolled back cleanly' in msg:
                        time.sleep(15)
                        continue
                    stats['skipped'] += 1
                    reasons[msg.split('(')[0].split('—')[-1].strip()[:60] or msg[:60]] += 1
                    break
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = self._connect()
            else:
                stats['skipped'] += 1
                reasons['lock retries exhausted'] += 1
            if n % 2000 == 0:
                self.stdout.write(f'  … {n}/{len(items)} {dict(stats)}')
        try:
            conn.close()
        except Exception:
            pass
        self.stdout.write(f'DONE {mode} {dict(stats)}')
        for k, v in reasons.most_common(8):
            self.stdout.write(f'  skipped ×{v}: {k}')
        for b, dn, ch in sample:
            self.stdout.write(f'  {b}/{dn}: ' + ' | '.join(
                f"{c['cheqsno']} now {c['paynow']}: {c['before']}→{c['after']}{' مغلق' if c['closes'] else ''}" for c in ch))
