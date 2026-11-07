"""Plan 2 / Task 8: drafting API - parties, maps, rules, exceptions, source drill-down."""
import datetime
import io
from decimal import Decimal
from unittest import mock

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.finance.gl import drafting
from apps.finance.models import (
    FinancialPeriod, GLAccount, GLAccountGroup, GLDraftRun, GLParty, GLSourceDoc, GLSourceMap, LedgerEntry,
    PostingRule, ReconParty, SourceException,
)
from apps.tests.factories import make_user
from core.middleware import module_access

BASE = '/api/finance/gl/'
D = datetime.date(2026, 3, 10)

LINES = [
    {'side': 'debit', 'account': '1302', 'amount': 'net', 'branch': 'source'},
    {'side': 'credit', 'account': '6002', 'amount': 'net', 'branch': 'source'},
]


def _rule(**kw):
    d = {'code': 'sales.cash', 'source_type': 'sales_tenders', 'effective_from': '2026-01-01',
         'conditions': {}, 'lines': LINES, 'granularity': 'branch_day', 'book': 'cash'}
    d.update(kw)
    return d


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)
        g = GLAccountGroup.objects.create(name='g', section='balance_sheet')
        for code, nat in (('1302', 'debit'), ('6002', 'credit'), ('1310', 'debit')):
            GLAccount.objects.create(code=code, name=code, group=g, nature=nat, account_type='asset')

    def setUp(self):
        _, self.acct_p, self.acct = make_user('t8_acct', role='accountant')
        _, self.admin_p, self.admin = make_user('t8_admin', role='admin', access_all=True)
        _, _, self.pharm = make_user('t8_pharm', role='pharmacist')
        self.branch = Branch.objects.first()

    def doc(self, key='k1', status='exception', **kw):
        return GLSourceDoc.objects.create(
            source_type=kw.pop('source_type', 'sales_tenders'), source_key=key,
            doc_date=kw.pop('doc_date', D), branch_code='130', amounts={'net': '10.00'},
            content_hash=key, status=status, **kw)

    def exc(self, doc=None, kind='no_rule', **kw):
        doc = doc or self.doc()
        return SourceException.objects.create(source_doc=doc, kind=kind, source_date=doc.doc_date,
                                              message='m', **kw)


class PermissionTests(Base):
    def test_non_all_branch_user_403(self):
        for path in ('parties/', 'maps/', 'rules/', 'exceptions/'):
            self.assertEqual(self.pharm.get(BASE + path).status_code, 403, path)

    def test_rule_edit_needs_ledger_edit(self):
        # accountant holds ledger create/approve but not edit
        self.assertEqual(self.acct.post(BASE + 'rules/', _rule(), format='json').status_code, 403)
        self.assertEqual(self.acct.put(BASE + 'maps/bank/40/', {'account_code': '1302'},
                                       format='json').status_code, 403)
        self.assertEqual(self.acct.post(BASE + 'parties/propose/').status_code, 403)
        r = self.admin.post(BASE + 'rules/', _rule(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(PostingRule.objects.get(code='sales.cash').version, 1)

    def test_party_confirm_needs_approve(self):
        p = GLParty.objects.create(party_type='supplier', code='1', name='x')
        _, _, no_approve = make_user('t8_view', role='viewer', access_all=True)
        self.assertEqual(no_approve.post(f'{BASE}parties/{p.pk}/confirm/',
                                         {'personcode': '77'}, format='json').status_code, 403)
        r = self.acct.post(f'{BASE}parties/{p.pk}/confirm/', {'personcode': '77'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual((p.status, p.softech_personcode), ('confirmed', '77'))

    def test_exception_actions_need_create(self):
        e = self.exc()
        _, _, viewer = make_user('t8_view2', role='viewer', access_all=True)
        self.assertEqual(viewer.post(f'{BASE}exceptions/{e.pk}/ignore/', {'note': 'x'},
                                     format='json').status_code, 403)
        self.assertEqual(viewer.post(BASE + 'exceptions/redraft/', {'ids': [e.pk]},
                                     format='json').status_code, 403)


class PartyTests(Base):
    def test_list_filters_and_shows_softech_name(self):
        rp = ReconParty.objects.create(party_type='supplier', softech_personcode='55', name='اسم سوفتيك')
        GLParty.objects.create(party_type='supplier', code='1', name='الاولى', recon_party=rp,
                               softech_personcode='55', status='proposed', proposal_basis='exact')
        GLParty.objects.create(party_type='customer', code='2', name='ثانية')
        r = self.acct.get(BASE + 'parties/', {'type': 'supplier', 'status': 'proposed'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['results']), 1)
        row = r.data['results'][0]
        self.assertEqual((row['softech_name'], row['proposal_basis']), ('اسم سوفتيك', 'exact'))
        self.assertEqual(len(self.acct.get(BASE + 'parties/', {'q': 'ثان'}).data['results']), 1)

    def test_import_and_propose(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['suppliar code', 'Name'])
        ws.append([101, 'شركة النور'])
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile('p.xlsx', buf.getvalue())
        r = self.admin.post(BASE + 'parties/import/', {'file': f}, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['created'], 1)
        ReconParty.objects.create(party_type='supplier', softech_personcode='9', name='شركة النور')
        r = self.admin.post(BASE + 'parties/propose/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(GLParty.objects.get(code='101').status, 'proposed')
        self.assertEqual(self.admin.post(BASE + 'parties/import/').status_code, 400)

    def _confirm_sheet(self, rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['النوع', 'كود المالية', 'اسم المالية', 'مقترح 1 كود سوفتيك', 'الكود المعتمد (تملؤه المالية)'])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile('s.xlsx', buf.getvalue())

    def test_confirm_upload_previews_then_confirms_valid_rows(self):
        GLParty.objects.create(party_type='supplier', code='29', name='فارما اوفرسيز')
        GLParty.objects.create(party_type='customer', code='99', name='جنوب القاهرة')
        GLParty.objects.create(party_type='supplier', code='16', name='رامكو', status='confirmed',
                               softech_personcode='30')
        rows = [['مورد / دائن', 29, 'فارما اوفرسيز', 565, 565],
                ['عميل', 99, 'جنوب القاهرة', 4227, 4227.0],
                ['مورد / دائن', 16, 'رامكو', 30, 30],      # already confirmed to 30
                ['مورد / دائن', 55, None, 1, 1],           # never imported, no name to add it under
                ['مورد / دائن', 29, 'x', None, None],      # not reviewed -> left out
                ['عميل', 7, 'x', 4227, 4227],              # same SOFTECH customer twice in the file
                ['مورد / دائن', 40, 'x', 'abc', 'abc']]    # not a number
        r = self.acct.post(BASE + 'parties/confirm-upload/', {'file': self._confirm_sheet(rows)}, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.data['applied'])
        self.assertEqual(r.data['counts'], {'will_confirm': 2, 'unchanged': 1, 'error': 3})
        self.assertEqual(GLParty.objects.filter(status='confirmed').count(), 1)   # preview saved nothing
        self.assertFalse(AuditLog.objects.filter(action='gl_party_confirmed').exists())
        r = self.acct.post(BASE + 'parties/confirm-upload/', {'file': self._confirm_sheet(rows), 'dry_run': 'false'},
                           format='multipart')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['counts'], {'confirmed': 2, 'unchanged': 1, 'error': 3})
        self.assertEqual(GLParty.objects.get(code='29').softech_personcode, '565')
        self.assertEqual(GLParty.objects.get(party_type='customer', code='99').status, 'confirmed')
        self.assertEqual(AuditLog.objects.filter(action='gl_party_confirmed').count(), 2)
        self.assertTrue(AuditLog.objects.filter(action='gl_parties_bulk_confirmed').exists())
        by_row = {x['row']: x for x in r.data['results']}
        self.assertIn('مكرر', by_row[7]['detail'])
        self.assertIn('استورد', by_row[5]['detail'])

    def test_confirm_upload_adds_new_codes_and_holds_name_conflicts(self):
        GLParty.objects.create(party_type='supplier', code='1179', name='ممدوح هنرى فهمى عطية')
        GLParty.objects.create(party_type='supplier', code='442', name='بارك فيل')
        GLParty.objects.create(party_type='supplier', code='100', name='د/ راتب')
        rows = [['عميل', 100, 'شركة جنوب القاهرة لتوزيع الكهرباء', 4288, 4288],   # new: the code is another type
                ['مورد / دائن', 1179, 'شركة يو بى فارما', 900, 900],              # another party's name
                ['مورد / دائن', 442, 'شركة بارك فيل مصر للادوية', 3226, 3226]]    # same party, longer name
        url = BASE + 'parties/confirm-upload/'
        r = self.acct.post(url, {'file': self._confirm_sheet(rows)}, format='multipart')
        self.assertEqual(r.data['counts'], {'will_create': 1, 'name_conflict': 1, 'will_confirm': 1})
        self.assertFalse(GLParty.objects.filter(party_type='customer', code='100').exists())
        r = self.acct.post(url, {'file': self._confirm_sheet(rows), 'dry_run': 'false'}, format='multipart')
        self.assertEqual(r.data['counts'], {'created': 1, 'name_conflict': 1, 'confirmed': 1})
        new = GLParty.objects.get(party_type='customer', code='100')
        self.assertEqual((new.name, new.status, new.softech_personcode),
                         ('شركة جنوب القاهرة لتوزيع الكهرباء', 'confirmed', '4288'))
        held = GLParty.objects.get(code='1179')
        self.assertEqual((held.name, held.status, held.softech_personcode), ('ممدوح هنرى فهمى عطية', 'unmapped', ''))
        kept = GLParty.objects.get(code='442')
        self.assertEqual((kept.name, kept.status), ('بارك فيل', 'confirmed'))   # never renamed
        self.assertEqual(GLParty.objects.get(party_type='supplier', code='100').status, 'unmapped')

    def test_confirm_upload_refuses_a_different_code_and_bad_files(self):
        GLParty.objects.create(party_type='supplier', code='16', name='رامكو', status='confirmed',
                               softech_personcode='30')
        r = self.acct.post(BASE + 'parties/confirm-upload/',
                           {'file': self._confirm_sheet([['مورد', 16, 'رامكو', 31, 31]]), 'dry_run': 'false'},
                           format='multipart')
        self.assertEqual(r.data['counts'], {'error': 1})
        self.assertEqual(GLParty.objects.get(code='16').softech_personcode, '30')
        wb = openpyxl.Workbook()
        wb.active.append(['a', 'b'])
        buf = io.BytesIO()
        wb.save(buf)
        r = self.acct.post(BASE + 'parties/confirm-upload/', {'file': SimpleUploadedFile('n.xlsx', buf.getvalue())},
                           format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('الكود المعتمد', r.data['detail'])
        _, _, viewer = make_user('t8_view3', role='viewer', access_all=True)
        r = viewer.post(BASE + 'parties/confirm-upload/', {'file': self._confirm_sheet([])}, format='multipart')
        self.assertEqual(r.status_code, 403)

    def test_reject_and_create(self):
        p = GLParty.objects.create(party_type='supplier', code='1', name='x')
        self.assertEqual(self.acct.post(f'{BASE}parties/{p.pk}/reject/').status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, 'rejected')
        ReconParty.objects.create(party_type='supplier', softech_personcode='8', name='سوفتيك')
        r = self.acct.post(BASE + 'parties/', {'type': 'supplier', 'code': '900', 'name': 'جديد',
                                               'personcode': '8'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        g = GLParty.objects.get(code='900')
        self.assertEqual((g.status, g.softech_personcode, g.name), ('confirmed', '8', 'جديد'))
        r = self.acct.post(f'{BASE}parties/{p.pk}/confirm/', {}, format='json')
        self.assertEqual(r.status_code, 400)


class PartyCreateAuditTests(Base):
    def test_create_party_name_in_audit(self):
        ReconParty.objects.create(party_type='supplier', softech_personcode='8', name='سوفتيك')
        r = self.acct.post(BASE + 'parties/', {'type': 'supplier', 'code': '901', 'name': 'اسم نهائي',
                                               'personcode': '8'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        row = AuditLog.objects.filter(action='gl_party_confirmed').latest('id')
        self.assertEqual(row.new_data['name'], 'اسم نهائي')
        self.assertEqual(r.data['name'], 'اسم نهائي')


class MapTests(Base):
    def test_put_get_audit_and_no_delete(self):
        r = self.admin.put(BASE + 'maps/bank/40/', {'account_code': '1302',
                                                    'branch_id': self.branch.pk, 'note': 'n'},
                           format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['account_code'], '1302')
        self.assertTrue(AuditLog.objects.filter(action='gl_map_saved').exists())
        lst = self.acct.get(BASE + 'maps/', {'kind': 'bank'})
        self.assertEqual([m['source_value'] for m in lst.data['results']], ['40'])
        self.assertEqual(self.admin.delete(BASE + 'maps/bank/40/').status_code, 405)
        self.assertEqual(GLSourceMap.objects.count(), 1)

    def test_validation(self):
        r = self.admin.put(BASE + 'maps/bank/40/', {'account_code': '9999'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data['errors'])
        r = self.admin.put(BASE + 'maps/nope/40/', {'account_code': '1302'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_card_clearing_requires_branch(self):
        r = self.admin.put(BASE + 'maps/card_clearing/130/', {'account_code': '1310'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(GLSourceMap.objects.exists())
        r = self.admin.put(BASE + 'maps/card_clearing/130/',
                           {'account_code': '1310', 'branch_id': self.branch.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_intercompany_map_requires_branch(self):   # Ruling P24: branch = HQ
        r = self.admin.put(BASE + 'maps/intercompany/160/', {'account_code': '1310'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.admin.put(BASE + 'maps/intercompany/160/',
                           {'account_code': '1310', 'branch_id': self.branch.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(GLSourceMap.objects.get(kind='intercompany', source_value='160').account.code, '1310')


class RuleTests(Base):
    def test_versioning_list_and_versions(self):
        self.assertEqual(self.admin.post(BASE + 'rules/', _rule(), format='json').status_code, 201)
        r = self.admin.post(BASE + 'rules/', _rule(effective_from='2026-03-01'), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['version'], 2)
        cur = self.acct.get(BASE + 'rules/', {'source_type': 'sales_tenders'})
        self.assertEqual([(x['code'], x['version']) for x in cur.data['results']], [('sales.cash', 2)])
        v = self.acct.get(BASE + 'rules/sales.cash/versions/')
        self.assertEqual([x['version'] for x in v.data['results']], [2, 1])
        self.assertEqual(self.admin.delete(BASE + 'rules/sales.cash/versions/').status_code, 405)

    def test_validation_errors_400(self):
        r = self.admin.post(BASE + 'rules/', _rule(source_type='nope'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data['errors'])
        r = self.admin.post(BASE + 'rules/', _rule(effective_from='bad'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PostingRule.objects.exists())

    def test_field_validation_400_not_500(self):
        """code slug <= 60, description str <= model length, priority int in smallint range."""
        self.admin.raise_request_exception = False
        bad = [dict(code='bad code'), dict(code='x' * 61), dict(code=''), dict(code=['a']), dict(code='-x'),
               dict(description=['x']), dict(description='x' * 301), dict(description=5),
               dict(priority=40000), dict(priority=-40000), dict(priority='abc'), dict(priority=1.5),
               dict(priority=True), dict(priority=None), dict(source_type=['sales_tenders']),
               dict(granularity={'a': 1})]
        for kw in bad:
            r = self.admin.post(BASE + 'rules/', _rule(**kw), format='json')
            self.assertEqual(r.status_code, 400, (kw, r.status_code))
        self.assertFalse(PostingRule.objects.exists())
        r = self.admin.post(BASE + 'rules/', _rule(code='sales.cash-2_x', description='d' * 300, priority=-32768),
                            format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_preview_range_limit(self):
        body = {'rule': _rule(), 'date_from': '2026-03-01', 'date_to': '2026-05-01'}
        self.assertEqual(self.acct.post(BASE + 'rules/preview/', body, format='json').status_code, 400)
        body['date_to'] = '2026-02-01'
        self.assertEqual(self.acct.post(BASE + 'rules/preview/', body, format='json').status_code, 400)

    def test_preview_saves_nothing_and_stringifies(self):
        from apps.finance.gl.sources import SourceDoc
        doc = SourceDoc('sales_tenders', 'p1', D, '130', 'cash', '',
                        {'net': Decimal('10.50'), 'sales': Decimal('10.50'), 'returns': Decimal('0')},
                        {'paymenttype': '30'})
        Branch.objects.create(name='b130', softech_branch_id='130')
        body = {'rule': _rule(), 'date_from': '2026-03-01', 'date_to': '2026-03-31'}
        with mock.patch.dict('apps.finance.gl.sources.READERS',
                             {'sales_tenders': lambda a, b, f: [doc]}):
            r = self.acct.post(BASE + 'rules/preview/', body, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['totals']['entries'], 1)
        self.assertEqual(r.data['totals']['debit'], '10.50')
        self.assertEqual(r.data['entries'][0]['entry_date'], '2026-03-10')
        self.assertFalse(PostingRule.objects.exists())
        self.assertFalse(LedgerEntry.objects.exists())

    def test_preview_window_boundary(self):
        body = {'rule': _rule(), 'date_from': '2026-03-01', 'date_to': '2026-03-31'}   # 31 days incl.
        with mock.patch.dict('apps.finance.gl.sources.READERS', {'sales_tenders': lambda a, b, f: []}):
            self.assertEqual(self.acct.post(BASE + 'rules/preview/', body, format='json').status_code, 200)
        body['date_to'] = '2026-04-01'   # 32 days incl.
        self.assertEqual(self.acct.post(BASE + 'rules/preview/', body, format='json').status_code, 400)

    def test_non_all_branch_user_403_on_write_route(self):
        body = {'rule': _rule(), 'date_from': '2026-03-01', 'date_to': '2026-03-02'}
        self.assertEqual(self.pharm.post(BASE + 'rules/preview/', body, format='json').status_code, 403)

    def test_rule_post_rejects_effective_to(self):
        r = self.admin.post(BASE + 'rules/', _rule(effective_to='2026-12-31'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(PostingRule.objects.exists())

    def test_preview_bad_rule_400(self):
        body = {'rule': _rule(source_type='nope'), 'date_from': '2026-03-01', 'date_to': '2026-03-02'}
        r = self.acct.post(BASE + 'rules/preview/', body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data['errors'])


class ExceptionTests(Base):
    def test_counts_by_kind_and_source(self):
        d1 = self.doc('c1')
        d2 = self.doc('c2', source_type='credit_sales')
        self.exc(d1, 'no_rule')
        self.exc(d1, 'unmapped_party')
        e3 = self.exc(d2, 'no_rule')
        r = self.acct.get(BASE + 'exceptions/counts/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data, {'total': 3, 'by_kind': {'no_rule': 2, 'unmapped_party': 1}})
        r = self.acct.get(BASE + 'exceptions/counts/', {'source_type': 'credit_sales'})
        self.assertEqual(r.data, {'total': 1, 'by_kind': {'no_rule': 1}})
        e3.status = 'ignored'
        e3.save(update_fields=['status'])
        self.assertEqual(self.acct.get(BASE + 'exceptions/counts/').data['total'], 2)
        self.assertEqual(self.pharm.get(BASE + 'exceptions/counts/').status_code, 403)

    def test_filter_and_ignore_audited(self):
        d1 = self.doc('a')
        d2 = self.doc('b', source_type='credit_sales', doc_date=datetime.date(2026, 4, 2))
        e1 = self.exc(d1, 'no_rule')
        self.exc(d2, 'unmapped_party')
        r = self.acct.get(BASE + 'exceptions/', {'status': 'open'})
        self.assertEqual(len(r.data['results']), 2)
        row = [x for x in r.data['results'] if x['id'] == e1.pk][0]
        self.assertEqual(row['doc']['source_key'], 'a')
        self.assertEqual(row['doc']['amounts'], {'net': '10.00'})
        self.assertEqual(len(self.acct.get(BASE + 'exceptions/', {'kind': 'no_rule'}).data['results']), 1)
        self.assertEqual(len(self.acct.get(BASE + 'exceptions/',
                                           {'source_type': 'credit_sales'}).data['results']), 1)
        self.assertEqual(len(self.acct.get(BASE + 'exceptions/',
                                           {'date_from': '2026-04-01'}).data['results']), 1)
        self.assertEqual(self.acct.get(BASE + 'exceptions/', {'date_from': 'x'}).status_code, 400)
        # ignore: needs a note, audited, doc stays 'exception'
        self.assertEqual(self.acct.post(f'{BASE}exceptions/{e1.pk}/ignore/', {},
                                        format='json').status_code, 400)
        r = self.acct.post(f'{BASE}exceptions/{e1.pk}/ignore/', {'note': 'مقصود'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        e1.refresh_from_db()
        d1.refresh_from_db()
        self.assertEqual((e1.status, e1.resolution_note, e1.resolved_by_id),
                         ('ignored', 'مقصود', self.acct_p.pk))
        self.assertEqual(d1.status, 'exception')
        self.assertTrue(AuditLog.objects.filter(action='gl_exception_ignored',
                                                object_id=str(e1.pk)).exists())
        self.assertEqual(self.acct.post(f'{BASE}exceptions/{e1.pk}/ignore/', {'note': 'x'},
                                        format='json').status_code, 409)
        self.assertEqual(len(self.acct.get(BASE + 'exceptions/').data['results']), 1)   # default open

    def test_redraft_runs_over_selected_docs(self):
        e1 = self.exc(self.doc('a'))
        e2 = self.exc(self.doc('b', source_type='credit_sales', doc_date=datetime.date(2026, 4, 2)))
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(BASE + 'exceptions/redraft/', {'ids': [e1.pk, e2.pk]}, format='json')
        self.assertEqual(r.status_code, 202, r.content)
        run = GLDraftRun.objects.get(pk=r.data['run_id'])
        self.assertEqual((run.date_from, run.date_to), (D, datetime.date(2026, 4, 2)))
        self.assertEqual(sorted(run.source_types), ['credit_sales', 'sales_tenders'])
        self.assertEqual(st.call_args.kwargs['args'][0], run.pk)

    def test_redraft_before_opening_date_refused(self):
        e = self.exc(self.doc('old', doc_date=datetime.date(2025, 12, 31)))
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(BASE + 'exceptions/redraft/', {'ids': [e.pk]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('2026-01-01', r.data['detail'])
        st.assert_not_called()
        self.assertFalse(GLDraftRun.objects.exists())

    def test_redraft_busy_409_and_bad_ids(self):
        e = self.exc()
        drafting.start_run(triggered_by='x', date_from=D, date_to=D, source_types=[])
        with mock.patch('apps.finance.gl.drafting_views.start_thread'):
            r = self.acct.post(BASE + 'exceptions/redraft/', {'ids': [e.pk]}, format='json')
        self.assertEqual(r.status_code, 409)
        GLDraftRun.objects.all().delete()
        self.assertEqual(self.acct.post(BASE + 'exceptions/redraft/', {'ids': []},
                                        format='json').status_code, 400)
        self.assertEqual(self.acct.post(BASE + 'exceptions/redraft/', {'ids': [999999]},
                                        format='json').status_code, 400)


class EntrySourceTests(Base):
    def test_entry_source_lists_member_docs(self):
        rule = PostingRule.objects.create(code='r', version=3, source_type='sales_tenders',
                                          effective_from=datetime.date(2026, 1, 1))
        period, _ = FinancialPeriod.objects.get_or_create(
            year=2026, month=3, period_type='month',
            defaults={'period_start': datetime.date(2026, 3, 1), 'period_end': datetime.date(2026, 3, 31)})
        entry = LedgerEntry.objects.create(entry_date=D, book='general', status='draft',
                                           created_by=self.acct_p, period=period)
        self.doc('m1', status='drafted', entry=entry, rule=rule)
        r = self.acct.get(f'{BASE}entries/{entry.pk}/source/')
        self.assertEqual(r.status_code, 200, r.content)
        row = r.data['docs'][0]
        self.assertEqual((row['source_key'], row['rule_code'], row['rule_version']), ('m1', 'r', 3))
        self.assertEqual(row['amounts'], {'net': '10.00'})
        self.assertEqual(self.acct.get(f'{BASE}entries/999999/source/').status_code, 404)
        self.assertEqual(self.pharm.get(f'{BASE}entries/{entry.pk}/source/').status_code, 403)


class RoutingTests(TestCase):
    def test_write_routes_need_exactly_the_view_grant(self):
        req = module_access.required
        for path, act in (
                ('rules/', 'edit'), ('maps/bank/40/', 'edit'), ('parties/import/', 'edit'),
                ('parties/propose/', 'edit'), ('parties/', 'approve'), ('parties/5/confirm/', 'approve'),
                ('parties/5/reject/', 'approve'), ('parties/confirm-upload/', 'approve'),
                ('exceptions/5/ignore/', 'create'),
                ('exceptions/redraft/', 'create'), ('drafting/run/', 'create')):
            method = 'PUT' if path.startswith('maps/') else 'POST'
            self.assertEqual(req('/api/finance/gl/' + path, method), ('ledger', (act,)), path)
        self.assertEqual(req('/api/finance/gl/rules/preview/', 'POST'), ('ledger', ('view',)))


class MetaEndpointTests(Base):
    """Ruling P16: read-only metadata / person search / unmapped values (ledger view)."""

    def test_rules_meta_reads_rules_py(self):
        from apps.finance.gl import rules as R
        r = self.acct.get(BASE + 'rules/meta/')
        self.assertEqual(r.status_code, 200, r.content)
        d = r.data
        self.assertEqual(d['source_fields']['credit_sales'], list(R.SOURCE_FIELDS['credit_sales']))
        self.assertEqual(d['condition_keys']['paymenttype_in'], ['sales_tenders'])
        self.assertEqual(sorted(d['bank_branch_sources']), sorted(R.BANK_BRANCH_SOURCES))
        self.assertEqual(d['map_key_for_kind']['card_clearing'], 'branch_code')
        # Ruling P24
        self.assertIn('intercompany', d['map_kinds'])
        self.assertEqual(d['map_key_for_kind']['intercompany'], 'counterpart_branch')
        self.assertIn('counterpart_branch', d['map_keys'])
        self.assertIn('tf_bankcode', d['map_keys'])
        self.assertIn('note', d['placeholders'])
        self.assertIn('hq', d['branch_modes'])
        self.assertIn('cheqno', d['placeholders'])
        self.assertEqual(self.pharm.get(BASE + 'rules/meta/').status_code, 403)

    def test_parties_persons_filters_and_caps(self):
        for i in range(55):
            ReconParty.objects.create(party_type='supplier', softech_personcode=f'9{i:03d}', name=f'شركة نور {i}')
        ReconParty.objects.create(party_type='customer', softech_personcode='8001', name='شركة نور عميل')
        r = self.acct.get(BASE + 'parties/persons/', {'type': 'supplier', 'q': 'نور'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(len(r.data['results']), 50)
        self.assertTrue(all(x['party_type'] == 'supplier' for x in r.data['results']))
        r = self.acct.get(BASE + 'parties/persons/', {'type': 'customer', 'q': '8001'})
        self.assertEqual([x['softech_personcode'] for x in r.data['results']], ['8001'])
        self.assertEqual(self.pharm.get(BASE + 'parties/persons/').status_code, 403)

    def test_unmapped_values_distinct_open_with_counts(self):
        d1, d2, d3 = self.doc('u1'), self.doc('u2'), self.doc('u3')
        self.exc(d1, 'unmapped_account', detail={'kind': 'bank', 'value': '40'})
        self.exc(d2, 'unmapped_account', detail={'kind': 'bank', 'value': '40'})
        self.exc(d3, 'unmapped_account', detail={'kind': 'expense', 'value': '43'})
        closed = self.exc(self.doc('u4'), 'unmapped_account', detail={'kind': 'bank', 'value': '99'})
        SourceException.objects.filter(pk=closed.pk).update(status='ignored')
        self.exc(self.doc('u5'), 'unmapped_account', detail={'account': '1302'})   # no map value
        r = self.acct.get(BASE + 'exceptions/unmapped-values/', {'kind': 'unmapped_account'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['results'], [{'kind': 'bank', 'value': '40', 'count': 2},
                                             {'kind': 'expense', 'value': '43', 'count': 1}])
        self.assertEqual(self.pharm.get(BASE + 'exceptions/unmapped-values/').status_code, 403)

    def test_get_routes_are_ledger_view(self):
        for path in ('rules/meta/', 'parties/persons/', 'exceptions/unmapped-values/'):
            self.assertEqual(module_access.required('/api/finance/gl/' + path, 'GET'),
                             ('ledger', ('view',)), path)


class EditDecisionApiTests(Base):
    """Ruling P23: «اعتماد نسخة سوفتيك» / «إبقاء تعديلي» on an edited_by_user exception."""

    def setUp(self):
        super().setUp()
        period, _ = FinancialPeriod.objects.get_or_create(
            year=2026, month=3, period_type='month',
            defaults={'period_start': datetime.date(2026, 3, 1), 'period_end': datetime.date(2026, 3, 31)})
        self.entry = LedgerEntry.objects.create(entry_date=D, book='cash', status='draft', created_by=self.acct_p,
                                                period=period, source_type='sales_tenders', source_key='k1')
        self.sd = self.doc('k1', group_key='k1')
        self.ex = self.exc(self.sd, kind='ledger_error',
                           detail={'code': 'edited_by_user', 'entry_id': self.entry.pk, 'group_key': 'k1',
                                   'entry_status': 'draft'},
                           proposed_lines=[{'account_code': '1302', 'debit': '10.00', 'credit': '0'}])
        self.v = drafting.proposal_version(self.ex.proposed_lines)

    def url(self, action, ex=None):
        return f'{BASE}exceptions/{(ex or self.ex).pk}/{action}/'

    def test_accept_softech_202_starts_redraft_and_audits(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(self.url('accept-softech'), {'note': 'سوفتيك صح', 'version': self.v}, format='json')
        self.assertEqual(r.status_code, 202, r.content)
        run = GLDraftRun.objects.get(pk=r.data['run_id'])
        self.assertEqual((run.date_from, run.date_to, run.source_types), (D, D, ['sales_tenders']))
        self.assertEqual(st.call_args.kwargs['args'][0], run.pk)
        self.ex.refresh_from_db()
        self.sd.refresh_from_db()
        self.assertEqual((self.ex.status, self.ex.resolved_by_id, self.ex.resolution_note),
                         ('resolved', self.acct_p.pk, 'سوفتيك صح'))
        self.assertEqual(self.sd.status, 'new')
        a = AuditLog.objects.get(action='gl_entry_edit_released')
        self.assertEqual((a.object_id, a.user_id, a.new_data['exception_id']),
                         (str(self.entry.pk), self.acct_p.pk, self.ex.pk))

    def test_accept_busy_409_rolls_back(self):
        drafting.start_run(triggered_by='x', date_from=D, date_to=D, source_types=[])
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(self.url('accept-softech'), {'version': self.v}, format='json')
        self.assertEqual(r.status_code, 409)
        st.assert_not_called()
        self.assertEqual(SourceException.objects.get(pk=self.ex.pk).status, 'open')
        self.assertFalse(AuditLog.objects.filter(action='gl_entry_edit_released').exists())

    def test_keep_edit_200_relinks_and_audits(self):
        r = self.acct.post(self.url('keep-edit'), {'note': 'تعديلي صح', 'version': self.v}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['status'], 'resolved')
        self.sd.refresh_from_db()
        self.assertEqual((self.sd.status, self.sd.entry_id, self.sd.group_key), ('drafted', self.entry.pk, 'k1'))
        self.assertTrue(AuditLog.objects.filter(action='gl_entry_edit_kept', object_id=str(self.entry.pk),
                                                user=self.acct_p).exists())

    def test_409_when_not_open_or_wrong_kind(self):
        other = self.exc(self.doc('k2'), kind='no_rule')
        for action in ('accept-softech', 'keep-edit'):
            r = self.acct.post(self.url(action, other), {'version': self.v}, format='json')
            self.assertEqual(r.status_code, 409, action)
            self.assertIn('detail', r.data)
        self.assertEqual(self.acct.post(self.url('keep-edit'), {'version': self.v}, format='json').status_code, 200)
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            self.assertEqual(self.acct.post(self.url('accept-softech'), {'version': self.v}, format='json').status_code, 409)
            st.assert_not_called()
        self.assertEqual(self.acct.post(f'{BASE}exceptions/999999/keep-edit/', {'version': self.v}, format='json').status_code, 404)

    def test_needs_ledger_approve_and_all_branch(self):
        from apps.users.models import RoleModuleAccess
        _, _, viewer = make_user('t8_view3', role='viewer', access_all=True)   # no ledger.approve
        for a in ('view', 'create', 'approve'):
            RoleModuleAccess.objects.update_or_create(
                role='pharmacist', module='ledger', action=a, defaults={'is_allowed': True})
        module_access.clear_cache()
        _, _, scoped = make_user('t8_scoped', role='pharmacist', access_all=False)
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            for client in (viewer, scoped):
                for action in ('accept-softech', 'keep-edit'):
                    self.assertEqual(client.post(self.url(action), {'version': self.v}, format='json').status_code, 403, action)
            st.assert_not_called()
        self.assertEqual(SourceException.objects.get(pk=self.ex.pk).status, 'open')
        self.assertFalse(AuditLog.objects.filter(action__startswith='gl_entry_edit_').exists())

    def test_routes_need_ledger_approve(self):
        req = module_access.required
        self.assertEqual(req(self.url('accept-softech'), 'POST'), ('ledger', ('approve',)))
        self.assertEqual(req(self.url('keep-edit'), 'POST'), ('ledger', ('approve',)))

    def test_list_exposes_proposal_version(self):
        r = self.acct.get(BASE + 'exceptions/?kind=ledger_error')
        self.assertEqual(r.data['results'][0]['proposal_version'], self.v)

    def test_stale_or_missing_version_refused(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            for action in ('accept-softech', 'keep-edit'):
                r = self.acct.post(self.url(action), {'version': 'old'}, format='json')
                self.assertEqual(r.status_code, 409, action)
                self.assertEqual(r.data['detail'], 'تغيّرت نسخة سوفتيك — راجعها مرة أخرى')
                self.assertEqual(self.acct.post(self.url(action), {}, format='json').status_code, 400, action)
            st.assert_not_called()
        self.assertEqual(SourceException.objects.get(pk=self.ex.pk).status, 'open')
        self.assertFalse(AuditLog.objects.filter(action__startswith='gl_entry_edit_').exists())

    def test_keep_edit_refused_while_engine_runs(self):
        drafting.start_run(triggered_by='x', date_from=D, date_to=D, source_types=[])
        r = self.acct.post(self.url('keep-edit'), {'version': self.v}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertIn('الترحيل يعمل الآن', r.data['detail'])
        self.assertEqual(SourceException.objects.get(pk=self.ex.pk).status, 'open')
