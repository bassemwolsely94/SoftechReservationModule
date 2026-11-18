"""Read shapes for the supplier-portal staff API (/api/rpa/portal/). Display only: every flag shown
here (frozen, needs_person, discovery stalled) is computed by the portal services."""
from django.db.models import Prefetch
from rest_framework import serializers

from apps.rpa.models import BuyList, PortalAccount, PortalJob, PortalLine, PortalRun, RpaScreenshot, SupplierPortal

from . import queue


def _name(profile):
    return getattr(profile, 'full_name', '') if profile is not None else ''


class PortalSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source='get_key_display', read_only=True)

    class Meta:
        model = SupplierPortal
        fields = ['key', 'title', 'supplier_code', 'driver', 'enabled', 'live', 'basket_size',
                  'short_expiry_months', 'price_jump_pct']


class AccountSerializer(serializers.ModelSerializer):
    portal = serializers.CharField(source='portal.key', read_only=True)
    paper_branch_code = serializers.SerializerMethodField()
    paper_branch_name = serializers.SerializerMethodField()

    class Meta:
        model = PortalAccount
        fields = ['id', 'portal', 'label', 'paper_branch', 'paper_branch_code', 'paper_branch_name',
                  'identity_text', 'active', 'last_credit']

    def get_paper_branch_code(self, a):
        return a.paper_branch.softech_branch_id if a.paper_branch_id else ''

    def get_paper_branch_name(self, a):
        return (a.paper_branch.name_ar or a.paper_branch.name) if a.paper_branch_id else ''


class BuyListSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    line_count = serializers.IntegerField(read_only=True)
    open_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = BuyList
        fields = ['id', 'source_kind', 'source_ref', 'status', 'created_by_name', 'created_at',
                  'line_count', 'open_count']

    def get_created_by_name(self, b):
        return _name(b.created_by)


def buyline_row(ln, *, frozen=False, ranking=None):
    return {'id': ln.pk, 'buylist_id': ln.buylist_id, 'seq': ln.seq, 'item_id': ln.item_id,
            'item_code': ln.item.softech_id, 'item_name': ln.item.name, 'needed_qty': ln.needed_qty,
            'remaining_qty': ln.remaining_qty, 'chosen_supplier': ln.chosen_supplier,
            'tried': ln.tried or [], 'reason': ln.reason, 'frozen': frozen,
            'ranking': ranking or []}


def basket_row(b):
    return {'id': b.pk, 'job_id': b.job_id, 'seq': b.seq, 'status': b.status,
            'needs_person': queue.needs_person(b), 'needs_person_reason': b.needs_person_reason,
            'portal_ref': b.portal_ref, 'order_ref': b.order_ref, 'filled_at': b.filled_at,
            'line_count': getattr(b, 'line_count', None)}


class JobSerializer(serializers.ModelSerializer):
    portal = serializers.CharField(source='portal.key', read_only=True)
    portal_title = serializers.CharField(source='portal.get_key_display', read_only=True)
    account_label = serializers.CharField(source='account.label', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    basket_count = serializers.IntegerField(read_only=True, default=None)
    needs_person_count = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = PortalJob
        fields = ['id', 'portal', 'portal_title', 'account', 'account_label', 'buylist', 'kind', 'status',
                  'dry_run', 'estimated_value', 'created_by', 'created_by_name', 'approved_by_name',
                  'approved_at', 'created_at', 'basket_count', 'needs_person_count']

    def get_created_by_name(self, j):
        return _name(j.created_by)

    def get_approved_by_name(self, j):
        return _name(j.approved_by)


def job_detail(job):
    from django.db.models import Count
    from apps.rpa.portal.jobs import _job_lines
    data = JobSerializer(job).data
    baskets = job.baskets.annotate(line_count=Count('lines')).order_by('seq', 'pk')
    data['baskets'] = [basket_row(b) for b in baskets]
    data['discovery'] = queue.discovery_state(job)
    data['account_last_credit'] = job.account.last_credit or {}
    # a draft shows the lines it will order (the over-need reasons are typed against them)
    data['lines'] = ([buyline_row(ln) for ln in _job_lines(job)] if job.status == 'draft' else [])
    return data


def _shots(run):
    return [{'id': s.id, 'step_index': s.step_index, 'url': s.image.url, 'created_at': s.created_at}
            for s in run.shots.all()]


def run_row(run):
    return {'id': run.pk, 'kind': run.kind, 'mode': run.mode,
            'device_label': run.device.label if run.device_id else '', 'started_at': run.started_at,
            'finished_at': run.finished_at, 'outcome': run.outcome, 'steps': run.steps or [],
            'screenshots': _shots(run)}


def portal_line_row(ln):
    return {'id': ln.pk, 'buyline_id': ln.buyline_id, 'item_id': ln.item_id, 'item_code': ln.item.softech_id,
            'item_name': ln.item.name, 'wanted_qty': ln.wanted_qty, 'accepted_qty': ln.accepted_qty,
            'status': ln.status, 'supplier_key': ln.supplier_key, 'supplier_name_seen': ln.supplier_name_seen,
            'price': ln.price, 'discount_pct': ln.discount_pct, 'bonus_text': ln.bonus_text,
            'supplier_expiry': ln.supplier_expiry, 'flags': ln.flags or [], 'message': ln.message}


def basket_detail(b):
    data = basket_row(b)
    lines = b.lines.select_related('item').order_by('pk')
    runs = (PortalRun.objects.filter(basket=b).select_related('device').order_by('-started_at', '-pk')
            .prefetch_related(Prefetch('shots', queryset=RpaScreenshot.objects.order_by('step_index', 'id'))))
    data.update({
        'portal': b.job.portal.key, 'account_label': b.job.account.label, 'dry_run': b.job.dry_run,
        'job_status': b.job.status, 'submitted_seen_at': b.submitted_seen_at, 'credit_seen': b.credit_seen or {},
        'diff': b.diff or {}, 'may_have_ordered': queue.may_have_ordered(b),
        # computed by the queue: cancelling needs a confirmation and a reason; the order number a
        # person most likely links (''); every order the robot read for it (the link editor's prefill)
        'cancel_needs_confirmation': b.status == 'needs_person' and queue.may_have_placed(b),
        'suggested_order_ref': queue.suggested_order_ref(b),
        'history_orders': queue.history_orders(b),
        'line_count': len(lines), 'lines': [portal_line_row(ln) for ln in lines],
        'runs': [run_row(r) for r in runs],
    })
    return data


def discovery_detail(job):
    """The job's portal lines still without a supplier code, each with the robot's candidates."""
    from apps.supply.models import AvailabilityBatch, AvailabilityLine
    waiting = (PortalLine.objects.filter(basket__job=job, supplier_key='', status='pending')
               .select_related('item', 'buyline').order_by('buyline__seq', 'pk'))
    seen, rows = set(), []
    cands = {}
    for al in (AvailabilityLine.objects.filter(batch__source=AvailabilityBatch.SOURCE_PORTAL,
                                               match_reason__job_id=job.pk).order_by('pk')):
        mr = al.match_reason or {}
        cands.setdefault(mr.get('buyline_id'), []).append({
            'availability_line_id': al.pk, 'sku': al.supplier_item_code, 'name': al.raw_text,
            'price': al.price, 'out_of_stock': 'out_of_stock' in (al.signals or []),
            'confirmed': al.is_confirmed, 'code_conflict': bool(mr.get('vendor_code_conflict')),
            'learn_failed': bool(mr.get('learn_failed'))})
    for pl in waiting:
        if pl.buyline_id in seen:
            continue
        seen.add(pl.buyline_id)
        rows.append({'buyline_id': pl.buyline_id, 'seq': pl.buyline.seq, 'item_id': pl.item_id,
                     'item_code': pl.item.softech_id, 'item_name': pl.item.name, 'wanted_qty': pl.wanted_qty,
                     'candidates': cands.get(pl.buyline_id, [])})
    return {'job_id': job.pk, 'lines': rows, **queue.discovery_state(job)}


def remainder_rows(lines, ranking):
    """A remainder row also names the next supplier to try: the best-ranked one not tried yet."""
    rows = []
    for ln in lines:
        row = buyline_row(ln, ranking=ranking.get(ln.item_id))
        tried = {str(t.get('supplier')) for t in row['tried'] if isinstance(t, dict)}
        # a basket cancelled while its order may have been placed: no one-key next supplier - a
        # person checks the supplier's site and picks from the buy list (queue._hold_lines)
        row['may_have_ordered'] = any(isinstance(t, dict) and t.get('may_have_ordered') for t in row['tried'])
        row['next_supplier'] = ('' if row['may_have_ordered'] else
                                next((c for c in row['ranking'] if str(c) not in tried), ''))
        rows.append(row)
    return rows

