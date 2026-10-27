"""
Backfill stale `stktrans.bonusqty` on receipts our insurance re-price touched.

bonusqty = the per-strip price SOFTECH PRINTS on the receipt for pack-split items,
natively kept at itemsaleprice / packing (packing = strips per pack, constant per
item).  Our earlier re-price updated itemsaleprice but not bonusqty, so those
receipts print the OLD strip price while their totals are already correct.

This finds every line we re-priced whose bonusqty drifted, computes the correct
value from the item's NATIVE packing (the mode of itemsaleprice/bonusqty across all
of that item's lines — our few broken lines are the outliers), and — with --apply —
writes it on HQ (+ branch when reachable), recording each change on a revertible
SoftechRepriceRun.

    python manage.py backfill_bonusqty            # dry-run: print the list
    python manage.py backfill_bonusqty --apply     # write + audit
    python manage.py backfill_bonusqty --item 128721
"""
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Fix stale stktrans.bonusqty (per-strip receipt price) on re-priced receipts.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='write changes (default: dry-run)')
        parser.add_argument('--item', default=None, help='limit to one itemcode')

    def handle(self, *args, **opts):
        from apps.insurance.reprice_service import (
            _hq_conn, _open_branch, r2, _d, _DOCCODE, write_enabled,
        )
        from apps.insurance.models import SoftechRepriceRun, SoftechRepriceEdit

        apply = opts['apply']
        only_item = opts['item']

        # 1) affected item -> set of (doc, branch, doccode) from our APPLIED runs
        receipts_by_item = {}
        for run in SoftechRepriceRun.objects.filter(status='applied'):
            for code in (run.new_prices or {}):
                code = str(code).strip()
                if only_item and code != only_item:
                    continue
                receipts_by_item.setdefault(code, set()).add(
                    (run.docnumber, run.branchcode, run.doccode or _DOCCODE))
        if not receipts_by_item:
            self.stdout.write('لا توجد عمليات re-price مُطبَّقة.')
            return

        hq = _hq_conn(charset='cp1256'); hcur = hq.cursor()

        # 2) native packing per item = MODE of round(itemsaleprice/bonusqty, 3)
        packing = {}
        for item in receipts_by_item:
            hcur.execute('SELECT itemsaleprice,bonusqty FROM SOFTECHDB9.dbo.stktrans '
                         'WHERE itemcode=? AND doccode=? AND bonusqty>0 AND itemsaleprice>0',
                         [item, _DOCCODE])
            ratios = Counter()
            for sp, bq in hcur.fetchall():
                try:
                    ratios[round(float(sp) / float(bq), 3)] += 1
                except ZeroDivisionError:
                    pass
            if ratios:
                packing[item] = Decimal(str(ratios.most_common(1)[0][0]))

        # 3) find stale lines within OUR receipts
        # fixes[(doc,branch,doccode)] = [(item, flag, before, after), ...]
        fixes = {}
        for item, receipts in receipts_by_item.items():
            pk = packing.get(item)
            if not pk or pk == 0:
                continue
            for (doc, branch, doccode) in receipts:
                hcur.execute('SELECT dblitemflag,itemsaleprice,bonusqty FROM SOFTECHDB9.dbo.stktrans '
                             'WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=? '
                             'AND itemcode=? AND bonusqty>0', [doc, branch, doccode, item])
                for flag, sp, bq in hcur.fetchall():
                    correct = r2(_d(sp) / pk)
                    if abs(float(correct) - float(bq)) >= 0.01:
                        fixes.setdefault((doc, branch, doccode), []).append(
                            (item, int(_d(flag)), float(bq), float(correct)))

        # 4) print the list
        total_lines = sum(len(v) for v in fixes.values())
        self.stdout.write(self.style.WARNING(
            f'\n{"APPLY" if apply else "DRY-RUN"} — {len(fixes)} إيصال · {total_lines} بند · '
            f'{len(packing)} صنف\n'))
        for item in sorted(packing):
            self.stdout.write(f'  صنف {item}: packing (strips/pack) = {packing[item]}')
        self.stdout.write('')
        for (doc, branch, doccode) in sorted(fixes):
            for (item, flag, before, after) in fixes[(doc, branch, doccode)]:
                self.stdout.write(
                    f'  #{doc} فرع {branch} · صنف {item} flag {flag} · '
                    f'bonusqty {before} → {after}')

        if not apply:
            self.stdout.write(self.style.NOTICE('\n(dry-run — أعد التشغيل بـ --apply للكتابة)'))
            hcur.close(); hq.close()
            return

        if not write_enabled():
            self.stdout.write(self.style.ERROR('الكتابة إلى سوفتك معطّلة (INSURANCE_SOFTECH_WRITE_ENABLED=False).'))
            hcur.close(); hq.close()
            return

        # 5) apply per receipt: HQ always, branch when reachable; audited + revertible
        reprinted = []
        hq_only = []
        for (doc, branch, doccode) in sorted(fixes):
            lines = fixes[(doc, branch, doccode)]
            bconn = None
            try:
                bconn = _open_branch(branch, charset='cp1256'); bconn.begin()
            except Exception:
                bconn = None  # branch offline → fix HQ only
            run = SoftechRepriceRun.objects.create(
                docnumber=str(doc), branchcode=str(branch), doccode=doccode,
                new_prices={'_bonusqty_backfill': ','.join(sorted({l[0] for l in lines}))},
                net_delta=0, nodes=['HQ'] + ([branch] if bconn else []),
                status=SoftechRepriceRun.STATUS_PREVIEW)
            edits = []
            try:
                hq.begin()
                bcur = bconn.cursor() if bconn else None
                for (item, flag, before, after) in lines:
                    rk = {'docnumber': str(doc), 'branchcode': str(branch),
                          'doccode': doccode, 'itemcode': item, 'dblitemflag': flag}
                    for node, cur in [('HQ', hcur)] + ([(branch, bcur)] if bcur else []):
                        cur.execute(
                            'UPDATE SOFTECHDB9.dbo.stktrans SET bonusqty=? '
                            'WHERE docnumber=CONVERT(numeric(6),?) AND branchcode=? AND doccode=? '
                            'AND itemcode=? AND dblitemflag=?',
                            [after, doc, branch, doccode, item, flag])
                        edits.append(SoftechRepriceEdit(
                            run=run, node=node, table='stktrans', row_key=rk,
                            field='bonusqty', before=str(before), after=str(after)))
                if bconn:
                    bconn.commit()
                hq.commit()
                SoftechRepriceEdit.objects.bulk_create(edits, batch_size=500)
                run.status = SoftechRepriceRun.STATUS_APPLIED
                run.save(update_fields=['status'])
                reprinted.append((doc, branch))
                if not bconn:
                    hq_only.append((doc, branch))
            except Exception as e:
                try: hq.rollback()
                except Exception: pass
                if bconn:
                    try: bconn.rollback()
                    except Exception: pass
                run.status = SoftechRepriceRun.STATUS_FAILED
                run.error = str(e)[:2000]
                run.save(update_fields=['status', 'error'])
                self.stdout.write(self.style.ERROR(f'  ✗ #{doc} فرع {branch}: {e}'))
            finally:
                if bconn:
                    try: bcur.close(); bconn.close()
                    except Exception: pass

        hcur.close(); hq.close()
        self.stdout.write(self.style.SUCCESS(
            f'\n✓ تم إصلاح {len(reprinted)} إيصال. أعد طباعتها من سوفتك:'))
        for (doc, branch) in reprinted:
            self.stdout.write(f'  #{doc} (فرع {branch})' + ('  [HQ فقط — الفرع غير متاح]' if (doc, branch) in hq_only else ''))
