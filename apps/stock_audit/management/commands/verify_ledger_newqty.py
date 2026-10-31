"""
P-30 step 0 — check what the stock ledger's `newqty` means before anything is built on it. Read-only: PostgreSQL
mirror only (no SOFTECH query, no database write); writes one Excel file.

    python manage.py verify_ledger_newqty --branch 160
        → newqty_check_160_<date>.xlsx: summary, direction per document type, broken chains, end-state mismatches,
          and «عينة للتحقق» — 20 cases for a store specialist to check on the SOFTECH item card (كارت الصنف)
    python manage.py verify_ledger_newqty --branch 160 --score newqty_check_160_<date>.xlsx
        → reads the filled «الرصيد في كارت الصنف» column and prints the pass / fail verdict
"""
import datetime as dt
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

SAMPLE_SHEET = 'عينة للتحقق'
SEEN = 'الرصيد في كارت الصنف'
MIRROR = 'الرصيد بعد السطر (المرآة)'
RESULT_AR = {'pass': 'ناجح', 'fail': 'غير ناجح', 'awaiting_sheet': 'في انتظار ورقة العينة'}


class Command(BaseCommand):
    help = 'P-30 step 0: verify the stock ledger newqty for one branch (read-only, PostgreSQL only).'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='160')
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--out', default=None, help='Excel path (default newqty_check_<branch>_<date>.xlsx)')
        parser.add_argument('--score', default=None, help='a filled report to score')
        parser.add_argument('--today', default=None, help='YYYY-MM-DD (default today)')

    def handle(self, *args, **o):
        from django.utils import timezone
        from apps.stock_audit import newqty_check as N
        today = dt.date.fromisoformat(o['today']) if o['today'] else timezone.localdate()
        since = today - dt.timedelta(days=o['days'])
        report = N.run(o['branch'], since)
        samples = None
        if o['score']:
            samples = N.score_samples(self._read_sheet(o['score']))
            report['verdict'] = N.verdict(report['chain']['pct'], report['end_state']['pct'], samples)
        else:
            path = o['out'] or f'newqty_check_{o["branch"]}_{today.isoformat()}.xlsx'
            self._write(report, path, today)
            if o['verbosity']:
                self.stdout.write(f'report: {path}')
        if o['verbosity']:
            self._print(report, samples)

    # ── output ───────────────────────────────────────────────────────────────

    def _print(self, r, samples):
        u, c, e, m = r['units'], r['chain'], r['end_state'], r['store_mix']
        self.stdout.write(f'branch {r["branch"]} since {r["since"]}: {u["lines"]} lines')
        self.stdout.write(f'  1 stores {m["stores"]} · outside selling store {m["selling_store"]}: '
                          f'{m["other_share_pct"]}%')
        self.stdout.write(f'  2 chain consistent {c["consistent"]}/{c["pairs"]} = {c["pct"]}%')
        for dc, d in c['by_doccode'].items():
            self.stdout.write(f'      doc {dc}: {d}')
        self.stdout.write(f'  3 end state equal {e["equal"]}/{e["compared"]} = {e["pct"]}%')
        self.stdout.write(f'  4 fractional {u["fractional"]} · negative {u["negative"]} · ≤0 {u["zero_or_less"]}')
        if samples is not None:
            self.stdout.write(f'  5 sample matches {samples["matches"]}/{samples["filled"]}')
        v = r['verdict']
        self.stdout.write(f'verdict: {v["result"]} ({v["rule"]}) {v["checks"]}')

    def _write(self, r, path, today):
        import openpyxl
        from openpyxl.styles import Font, PatternFill
        from apps.branches.models import Branch
        from apps.stock_audit.rules import _DOC_AR
        branch = Branch.objects.filter(softech_branch_id=r['branch']).first()
        label = (branch.name_ar or branch.name) if branch else r['branch']
        doc = lambda dc: f'{dc} {_DOC_AR.get(dc, "")}'.strip()          # noqa: E731
        f = lambda v: float(v) if isinstance(v, Decimal) else v          # noqa: E731
        t = lambda v: v.replace(tzinfo=None) if isinstance(v, dt.datetime) else v   # noqa: E731
        wb = openpyxl.Workbook()
        head_fill = PatternFill('solid', fgColor='022871')

        def sheet(title, cols, rows, first=False):
            ws = wb.active if first else wb.create_sheet()
            ws.title = title
            ws.sheet_view.rightToLeft = True
            ws.append([c for c, _ in cols])
            for i, (_, w) in enumerate(cols, start=1):
                cell = ws.cell(row=1, column=i)
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = head_fill
                ws.column_dimensions[cell.column_letter].width = w
            for row in rows:
                ws.append([t(f(v)) for v in row])
            ws.freeze_panes = 'A2'
            return ws

        u, c, e, m, v = r['units'], r['chain'], r['end_state'], r['store_mix'], r['verdict']
        sheet('ملخص', [('البند', 44), ('النتيجة', 40)], [
            ['الفرع', label], ['من تاريخ', r['since'].isoformat()], ['حتى', today.isoformat()],
            ['عدد الأسطر', u['lines']],
            ['1 · المخازن في الأسطر', ', '.join(f'{s}: {n}' for s, n in m['stores'].items())],
            ['1 · نسبة الأسطر خارج مخزن البيع', f'{m["other_share_pct"]}%'],
            ['2 · اتساق السلسلة (الرصيد السابق ± الكمية = الرصيد)', f'{c["consistent"]}/{c["pairs"]} = {c["pct"]}%'],
            ['3 · آخر رصيد = رصيد الصنف الحالي', f'{e["equal"]}/{e["compared"]} = {e["pct"]}%'],
            ['4 · أرصدة بكسور (شرائط)', u['fractional']], ['4 · أرصدة سالبة', u['negative']],
            ['5 · عينة للتحقق في SOFTECH', f'{len(r["samples"])} حالة — ورقة «{SAMPLE_SHEET}»'],
            ['قاعدة النجاح (مقترحة)', v['rule']], ['النتيجة الآن', RESULT_AR[v['result']]],
        ], first=True)
        sheet('اتجاه المستندات',
              [('المستند', 22), ('داخل', 10), ('خارج', 10), ('داخل + بونص', 12), ('خارج + بونص', 12), ('لا يتسق', 10)],
              [[doc(dc), d.get('in', 0), d.get('out', 0), d.get('in_bonus', 0), d.get('out_bonus', 0),
                d.get('break', 0)] for dc, d in c['by_doccode'].items()])
        sheet('أسطر لا تتسق',
              [('الصنف', 10), ('الاسم', 30), ('المخزن', 8), ('المستند', 18), ('الرقم', 12), ('التاريخ', 12),
               ('الرصيد السابق', 12), ('الكمية', 10), ('بونص', 8), ('الرصيد', 12), ('الفرق', 10)],
              [[b['itemcode'], b['name'], b['storecode'], doc(b['doccode']), b['docnumber'], b['docdate'],
                b['previous_newqty'], b['transqty'], b['bonusqty'], b['newqty'], b['difference']]
               for b in c['breaks']])
        sheet('فرق الرصيد النهائي',
              [('الصنف', 10), ('الاسم', 30), ('المخزن', 8), ('آخر رصيد في الحركات', 16), ('رصيد الصنف', 12),
               ('وقت آخر سطر', 20), ('وقت مزامنة الرصيد', 20)],
              [[x['itemcode'], x['name'], x['storecode'], x['ledger_newqty'], x['item_stock'], x['line_time'],
                x['stock_synced']] for x in e['mismatches']])
        sheet(SAMPLE_SHEET,
              [('الصنف', 10), ('الاسم', 30), ('المخزن', 8), ('المستند', 18), ('الرقم', 12), ('التاريخ', 12),
               ('الوقت', 20), ('الكمية', 10), (MIRROR, 22), (SEEN, 22), ('ملاحظة', 30)],
              [[s['itemcode'], s['name'], s['storecode'], doc(s['doccode']), s['docnumber'], s['docdate'],
                s['trans_time'], s['transqty'], s['newqty'], None, None] for s in r['samples']])
        wb.save(path)

    def _read_sheet(self, path):
        import openpyxl
        try:
            ws = openpyxl.load_workbook(path, data_only=True)[SAMPLE_SHEET]
        except (FileNotFoundError, KeyError) as exc:
            raise CommandError(f'cannot read «{SAMPLE_SHEET}» from {path}: {exc}')
        head = [c.value for c in ws[1]]
        try:
            i_new, i_seen = head.index(MIRROR), head.index(SEEN)
        except ValueError:
            raise CommandError(f'columns «{MIRROR}» / «{SEEN}» not found')
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[i_new] is None:
                continue
            try:
                seen = Decimal(str(row[i_seen])) if row[i_seen] not in (None, '') else None
            except InvalidOperation:
                seen = None
            rows.append({'newqty': Decimal(str(row[i_new])), 'seen': seen})
        return rows
