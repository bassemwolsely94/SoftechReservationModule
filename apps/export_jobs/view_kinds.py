"""
apps/export_jobs/view_kinds.py — any whitelisted export view, run as a background job (Stage 4, PR 2).

The screen POSTs to the export's own URL + `jobs/` (e.g. /api/stock-audit/findings/export/jobs/?…):
the export's module gate applies there as for the direct download. The job stores that path, the
query string (and the body for a POST export) and replays the SAME view as the requester — the
view's permission classes, its own gates, branch scope, formula guard and labels all run exactly as
they do for the direct download, so the file is the same one.

Only views in VIEW_EXPORTS can be started this way; anything else answers 404. The view's
permission classes (+ an optional extra `gate`) are checked at start, again when the job runs and
again at download.
"""
from importlib import import_module

from django.urls import Resolver404, resolve

from .registry import ExportFile, ExportKind

# key -> (view 'module:attr', label, method, needs_softech, extra gate 'module:attr' | '')
VIEW_EXPORTS = {
    'v:purchasing_advanced': ('apps.purchasing.views:advanced_export', 'المسار المتقدم — مقارنة', 'GET', False, ''),
    'v:purchasing_adv_pivot': ('apps.purchasing.views:advanced_pivot_export', 'المسار المتقدم — محوري', 'GET',
                               False, ''),
    'v:shortage': ('apps.purchasing.shortage_views:shortage_export', 'نواقص السوق', 'GET', False, ''),
    'v:stock_audit_findings': ('apps.stock_audit.views:export_findings', 'تدقيق حركات المخزون', 'GET', False,
                               'apps.export_jobs.view_kinds:stock_audit_gate'),
    'v:eta_history': ('apps.tax_invoicing.history_views:history_export', 'سجل الضرائب — مستندات', 'GET', False, ''),
    'v:eta_recon': ('apps.tax_invoicing.history_views:recon_export', 'مطابقة الضرائب', 'GET', False, ''),
    'v:eta_recon_uncoded': ('apps.tax_invoicing.history_views:recon_uncoded_export', 'أصناف بلا كود ضريبي', 'GET',
                            False, ''),
    'v:delivery_small_orders': ('apps.delivery.report_views:small_orders_export', 'طلبات توصيل صغيرة وبدون رسوم',
                                'GET', False, ''),                         # C20
    'v:supply_out_here': ('apps.supply.out_here_views:out_here_export', 'ناقص هنا · موجود هناك', 'GET', False, ''),
    'v:bought_dearer': ('apps.supply.dearer_views:bought_dearer_export', 'اشترينا أغلى', 'GET', False,
                        'apps.supply.dearer_views:export_gate'),         # C17: company-level, all-branch users
}


def stock_audit_gate(user):
    from apps.stock_audit.access import Access
    acc = Access(user)
    return bool(acc.can_view and acc.can_export)


def _load(dotted):
    module, attr = dotted.split(':')
    return getattr(import_module(module), attr)


class ReplayRequest:
    """Stands in for the request that started the job: same query / body / user, nothing else."""

    def __init__(self, *, user, method='GET', path='/', query=None, body=None, ip=None):
        from core.client_ip import meta_for_ip

        from .runner import query_dict
        self.user = user
        self.method = method
        self.path = self.path_info = path
        self.GET = self.query_params = query_dict(query or {})
        self.POST = {}
        self.data = dict(body or {})
        # the requester's address (core.client_ip at start), so audit rows written by the view keep it
        self.META = {**meta_for_ip(ip), 'REQUEST_METHOD': method}
        self.headers = {}
        self.COOKIES = {}
        self.FILES = {}
        self.auth = None
        self._request = self

    def build_absolute_uri(self, location=None):
        return location or self.path

    def get_full_path(self):
        q = self.GET.urlencode()
        return f'{self.path}?{q}' if q else self.path


def _view_class(view):
    cls = getattr(view, 'cls', None) or getattr(view, 'view_class', None)
    if cls is None:
        raise TypeError(f'{view!r} is not a DRF view')
    return cls


def _instance(view, req, kwargs=None):
    inst = _view_class(view)(**(getattr(view, 'initkwargs', None) or {}))
    inst.request, inst.args, inst.kwargs = req, (), dict(kwargs or {})
    inst.format_kwarg = None
    inst.headers = {}
    return inst


def key_for_path(path):
    """The VIEW_EXPORTS key whose view serves `path`, or None (not an export that may run as a job)."""
    try:
        match = resolve(path)
    except Resolver404:
        return None
    cls = getattr(match.func, 'cls', None) or getattr(match.func, 'view_class', None)
    for key, (dotted, *_rest) in VIEW_EXPORTS.items():
        target = _load(dotted)
        if match.func is target or (cls is not None and cls is _view_class(target)):
            return key
    return None


def _allowed_fn(key):
    dotted, _label, method, _sf, gate = VIEW_EXPORTS[key]

    def allowed(user):
        view = _load(dotted)
        req = ReplayRequest(user=user, method=method)
        inst = _instance(view, req)
        if not all(p.has_permission(req, inst) for p in inst.get_permissions()):
            return False
        return _load(gate)(user) if gate else True
    return allowed


def call_view(job, user):
    """Run the export view for this job as its requester -> the HttpResponse it returns."""
    dotted, _label, method, _sf, _gate = VIEW_EXPORTS[job.kind]
    p = job.params or {}
    path = p.get('path') or '/'
    match = resolve(path)
    if key_for_path(path) != job.kind:
        raise PermissionError('the stored path no longer serves this export')
    req = ReplayRequest(user=user, method=method, path=path, query=p.get('query'), body=p.get('body'),
                        ip=p.get('client_ip'))
    inst = _instance(match.func, req, match.kwargs)
    return getattr(inst, method.lower())(req, *match.args, **match.kwargs)


def _build_fn(key):
    def build(job, user, progress):
        from .runner import file_from_response
        progress(5, 'تجهيز الملف…')
        data, name, ctype = file_from_response(call_view(job, user))
        return ExportFile(data=data, file_name=name, content_type=ctype)
    return build


_cache = {}


def kind_for(key):
    if key not in VIEW_EXPORTS:
        raise KeyError(f'unknown export kind {key!r}')
    if key not in _cache:
        _dotted, label, method, needs_softech, _gate = VIEW_EXPORTS[key]
        _cache[key] = ExportKind(key=key, label=label, allowed=_allowed_fn(key), build=_build_fn(key),
                                 body=(method != 'GET'), needs_softech=needs_softech)
    return _cache[key]
