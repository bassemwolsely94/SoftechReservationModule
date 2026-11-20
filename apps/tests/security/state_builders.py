"""
apps/tests/security/state_builders.py

Wave 4 (full-project audit, doc 13): the state-aware sweep builder.

The generic seeder (sweep.seed_detail_paths) plants one neutral row per detail route through the
canary Planter. A few routes stayed 'unproven' (baselines/role_unproven.txt) because no neutral
row reaches them:

  * the record needs a link the Planter cannot guess — an ingredient link of THAT item, a posting
    operation (looked up by its UUID op_id, not its pk) or a reversal request of THAT case;
  * the route's other methods answer before any lookup (PUT / PATCH raise 405 on shortage lists,
    count sessions and invoices — Batch 4, Z-10), so the seeder saw "admin got past 404" and never
    planted a record; DELETE then answered 404 to everyone.

Each builder here makes the record in the state its route needs, in the sweep users' branch, and
returns the route with the real ids filled in. The sweep then sends every role there, so the
permission check behind it is exercised. Builders are tried before the generic seeder.

Test-only: nothing here changes a view. A builder never posts to SOFTECH — the replacement records
are left in a state the service refuses with a 400 before any writer runs (case not approved /
reversal without an approval request), and every sweep request is rolled back inside the Tripwire.
"""
import uuid
from decimal import Decimal

from .sweep import SWEEP_ID

UUID_PLACEHOLDER = '00000000-0000-0000-0000-000000000000'


def _case(planter):
    """A fresh replacement case in the sweep branch (not the shared neutral one, so the records
    hung on it below never change what the other case routes answer)."""
    from apps.replacement.models import ReplacementCase
    return planter.build(ReplacementCase, marked=False)


def replacement_operation_post(planter):
    from apps.replacement.models import PostingOperation
    case = _case(planter)
    if case is None:
        return None
    op = PostingOperation.objects.create(
        case=case, kind=PostingOperation.KIND_PURCHASE, status=PostingOperation.ST_PLANNED,
        idempotency_key=f'w4-sweep-{uuid.uuid4().hex[:16]}', requested_by=planter.profile)
    return f'/api/replacement/cases/{case.pk}/operations/{op.op_id}/post/'


def replacement_reversal_decide(planter):
    from apps.replacement.models import ReversalRequest
    case = _case(planter)
    if case is None:
        return None
    # requested_by stays empty (no self-approval refusal) and there is no approval request, so a
    # decision stops at "not awaiting approval" (400) for anyone the permission lets through
    rr = ReversalRequest.objects.create(case=case, kind='other', reason='w4 sweep',
                                        amount=Decimal('1'), status=ReversalRequest.ST_AWAITING)
    return f'/api/replacement/cases/{case.pk}/reversals/{rr.pk}/approve/'


def item_ingredient(planter):
    from apps.chronic.models import ActiveIngredient, ItemIngredientMap
    from apps.tests.factories import make_item
    item = make_item(name='W4 sweep item', softech_id='W4SW1')
    ing = ActiveIngredient.objects.create(name='W4 sweep ingredient')
    m = ItemIngredientMap.objects.create(item=item, active_ingredient=ing)
    return f'/api/items/{item.softech_id}/ingredients/{m.pk}/'


def shortage_list(planter):
    from apps.shortage.models import ShortageList
    sl = ShortageList.objects.create(branch=planter.branch, status='open', title='W4 sweep',
                                     created_by=planter.profile)
    return f'/api/shortage/lists/{sl.pk}/'


def stockcount_session(planter):
    from apps.stockcount.models import StockCountSession
    s = StockCountSession.objects.create(name='W4 sweep', branch_code=planter.branch.softech_branch_id)
    return f'/api/stockcount/sessions/{s.pk}/'


def supplier_invoice(planter):
    from apps.invoices.models import SupplierInvoice
    inv = SupplierInvoice.objects.create(branch=planter.branch, supplier_name='W4 sweep',
                                         invoice_number='W4', status='draft')
    return f'/api/invoices/invoices/{inv.pk}/'


# canonical sweep path (as baselines spell it) → builder
BUILDERS = {
    f'/api/replacement/cases/{SWEEP_ID}/operations/{UUID_PLACEHOLDER}/post/': replacement_operation_post,
    f'/api/replacement/cases/{SWEEP_ID}/reversals/{SWEEP_ID}/approve/': replacement_reversal_decide,
    f'/api/items/x/ingredients/{SWEEP_ID}/': item_ingredient,
    f'/api/shortage/lists/{SWEEP_ID}/': shortage_list,
    f'/api/stockcount/sessions/{SWEEP_ID}/': stockcount_session,
    f'/api/invoices/invoices/{SWEEP_ID}/': supplier_invoice,
}


def build(path, planter):
    """Real path for `path` from its builder, or None (no builder, or it could not build)."""
    fn = BUILDERS.get(path)
    return fn(planter) if fn else None
