"""
apps/tax_invoicing/environment.py — which ETA system this server talks to, and the production gate.

TAX_ETA_ENVIRONMENT picks ETA's published addresses ("preprod" or "production"); explicit
TAX_ETA_API_BASE_URL / TAX_ETA_ID_BASE_URL override them. Nothing set means nothing is reachable.

Anything that sends to the production system (documents, receipts, code requests) also needs
TAX_ETA_PRODUCTION_ALLOWED, read through writer_allowed: pre-production is where the format is proven,
and the first live send is the owner's decision at that moment.
"""
from urllib.parse import urlparse

from django.conf import settings

from config.writers import writer_allowed

# Published in ETA's SDK (sdk.invoicing.eta.gov.eg, FAQ "environments").
ENVIRONMENTS = {
    'preprod': {'api': 'https://api.preprod.invoicing.eta.gov.eg', 'id': 'https://id.preprod.eta.gov.eg',
                'portal': 'https://preprod.invoicing.eta.gov.eg', 'label': 'التجريبية (Pre-production)'},
    'production': {'api': 'https://api.invoicing.eta.gov.eg', 'id': 'https://id.eta.gov.eg',
                   'portal': 'https://invoicing.eta.gov.eg', 'label': 'الفعلية (Production)'},
}
PRODUCTION_API_HOST = 'api.invoicing.eta.gov.eg'
PRODUCTION_ID_HOST = 'id.eta.gov.eg'
PRODUCTION_FLAG = 'TAX_ETA_PRODUCTION_ALLOWED'


class ProductionNotAllowed(Exception):
    pass


def name():
    return str(getattr(settings, 'TAX_ETA_ENVIRONMENT', '') or '').strip().lower()


def _published(kind):
    return ENVIRONMENTS.get(name(), {}).get(kind, '')


def api_base():
    return (str(getattr(settings, 'TAX_ETA_API_BASE_URL', '') or '').strip() or _published('api')).rstrip('/')


def id_base():
    return (str(getattr(settings, 'TAX_ETA_ID_BASE_URL', '') or '').strip() or _published('id')).rstrip('/')


def _host(url):
    try:
        return (urlparse(url).hostname or '').lower()
    except ValueError:
        return ''


def is_production():
    """By the addresses actually in use, not by the name: an explicit URL can point at production."""
    return _host(api_base()) == PRODUCTION_API_HOST or _host(id_base()) == PRODUCTION_ID_HOST


def assert_may_send():
    if is_production() and not writer_allowed(PRODUCTION_FLAG):
        raise ProductionNotAllowed('الإرسال لمنظومة المصلحة الفعلية موقوف حتى يوافق المالك (TAX_ETA_PRODUCTION_ALLOWED)')


def current():
    """The name recorded beside anything ETA answered: 'preprod', 'production', 'custom' for explicit
    non-production URLs, or '' when nothing is configured."""
    if is_production():
        return 'production'
    if name():
        return name()
    return 'custom' if api_base() else ''


def describe():
    """For the screen: what is configured, without any secret."""
    return {
        'environment': name() or None,
        'label': ENVIRONMENTS.get(name(), {}).get('label', 'غير محدد'),
        'api_base': api_base() or None,
        'id_base': id_base() or None,
        'portal': _published('portal') or None,
        'is_production': is_production(),
        'production_allowed': writer_allowed(PRODUCTION_FLAG),
        'erp_client_configured': bool(getattr(settings, 'TAX_ETA_CLIENT_ID', '')
                                      and getattr(settings, 'TAX_ETA_CLIENT_SECRET', '')),
    }
