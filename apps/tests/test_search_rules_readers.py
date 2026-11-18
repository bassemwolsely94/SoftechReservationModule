"""
apps/tests/test_search_rules_readers.py — S4 (wildcards everywhere), task 2.

Hand-written `q` / `search` readers now go through `wq` (`*` and `%` are wildcards, parts in
typed order, any word order as the second tier). One endpoint per query shape; each seeds a
hit and a miss and asserts the hit is in, the miss is out, and nothing is duplicated.
"""
import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.counselling.models import CounsellingContent, CounsellingContentItem
from apps.customers import access as customer_access
from apps.omni.models import Conversation
from apps.stock_audit.models import StockAuditFinding
from apps.tasks.models import OperationalTask
from apps.transits.models import ItemPickOverride, PickZone
from apps.vouchers.models import Voucher

from .factories import make_admin, make_branch, make_item, make_user


def _rows(resp):
    assert resp.status_code == 200, resp.content
    data = resp.data
    if hasattr(data, 'get'):
        data = data.get('results', data.get('rows', data))
    return list(data)


class SingleTextFieldTests(TestCase):
    """vouchers: `?search=` over code / title."""

    def test_voucher_title_pattern(self):
        _, profile, client = make_admin('rd_v_admin')
        branch = make_branch()
        today = datetime.date.today()
        for title in ('Summer Big Sale', 'Winter Clearance'):
            Voucher.objects.create(code=Voucher.generate_code(), title=title,
                                   voucher_type='discount_pct', discount_pct=10, branch=branch,
                                   created_by=profile, status='active', max_uses=10, valid_from=today)
        rows = _rows(client.get('/api/vouchers/vouchers/', {'search': 'sum*sale'}))
        self.assertEqual([r['title'] for r in rows], ['Summer Big Sale'])


class SeveralFieldsTests(TestCase):
    """tasks: `?search=` over title / task number / tags."""

    def test_task_title_pattern(self):
        _, profile, client = make_admin('rd_t_admin')
        branch = make_branch()
        for title in ('Fix the printer', 'Order more gloves'):
            OperationalTask.objects.create(title=title, status='open', priority='low',
                                           task_type='stock_count', branch=branch, created_by=profile)
        rows = _rows(client.get('/api/tasks/', {'search': 'fix*print'}))
        self.assertEqual([r['title'] for r in rows], ['Fix the printer'])


@override_settings(COUNSELLING_CONTENT_ENABLED=True)
class ToManyRelationTests(TestCase):
    """counselling: `?q=` through links__item__name (to-many) — one row even with two links."""

    def test_two_links_one_row(self):
        _, profile, client = make_admin('rd_c_admin')
        hit = CounsellingContent.objects.create(title='sheet one', created_by=profile)
        miss = CounsellingContent.objects.create(title='sheet two', created_by=profile)
        for content, name, code in ((hit, 'Panadol Xtra', 'RD001'), (hit, 'Panadol Xtra Plus', 'RD002'),
                                    (miss, 'Cataflam 50', 'RD003')):
            CounsellingContentItem.objects.create(content=content, item=make_item(name, code),
                                                  linked_by=profile)
        rows = _rows(client.get('/api/counselling/content/', {'q': 'pan*xtra'}))
        self.assertEqual([r['id'] for r in rows], [hit.id])


class CodeFieldTests(TestCase):
    """transits item overrides: `?q=` over item.softech_id (a code, not a name)."""

    def test_item_code_pattern(self):
        _, _, client = make_admin('rd_tr_admin')
        zone = PickZone.objects.create(name='رد', purpose='picking')
        # names carry no digits, so only the item code can match
        for name, code in (('Alpha Syrup', '100045'), ('Beta Tablet', '200045')):
            ItemPickOverride.objects.create(item=make_item(name, code), zone=zone, branch=None)
        rows = _rows(client.get('/api/transits/item-overrides/', {'q': '1000*45'}))
        self.assertEqual([r['item_softech_id'] for r in rows], ['100045'])


class PhoneFieldTests(TestCase):
    """omni: `?q=` over contact_phone; the phone in the response is masked as before."""

    def test_phone_pattern_and_masking(self):
        _, profile, client = make_user('rd_o_cc', role='call_center', access_all=True)
        profile.can_see_customer_phone = False
        profile.save()
        Conversation.objects.create(contact_phone='01001234567')
        Conversation.objects.create(contact_phone='01229998888')
        rows = _rows(client.get('/api/omni/conversations/', {'q': '0100*567'}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['contact_phone'], customer_access.mask('01001234567'))
        self.assertNotIn('01001234567', str(rows[0]))


class ExactPartKeptTests(TestCase):
    """stock_audit findings: `?q=<itemcode>` still finds by the exact item code."""

    def test_exact_itemcode_still_matches(self):
        _, _, client = make_admin('rd_sa_admin')
        for n, code in ((1, '100001'), (2, '100002')):
            StockAuditFinding.objects.create(
                rule_code='sale_below_cost', dedup_key=f'B01|r|{n}', severity='warning', status='open',
                branchcode='B01', itemcode=code, doccode='115', docnumber=n,
                docdate=timezone.localdate(), occurred_at=timezone.now(), softech_user='166',
                value_egp=100, message_ar='رسالة', message_en='message', last_seen=timezone.now())
        rows = _rows(client.get('/api/stock-audit/findings/', {'q': '100001'}))
        self.assertEqual([r['itemcode'] for r in rows], ['100001'])


class BranchRequestLineRematchTests(TestCase):
    """purchasing branch-request line re-match: the fuzzy matcher does not read wildcards,
    so a `*` pattern is answered by the shared rules first (S3 leftover)."""

    def test_wildcard_finds_item(self):
        from apps.supply.models import BranchRequest, BranchRequestLine
        _, _, client = make_admin('rd_br_admin')
        req = BranchRequest.objects.create(branch=make_branch(), raw_text='x')
        line = BranchRequestLine.objects.create(request=req, raw_text='something')
        hit = make_item('Voltaren Emulgel 50', 'RD101')
        make_item('Cataflam 50', 'RD102')
        r = client.get(f'/api/purchasing/isr/branch-requests/{req.id}/lines/{line.id}/search/',
                       {'q': 'volt*gel'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([c['id'] for c in r.data['results']], [hit.id])
