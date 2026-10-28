"""
Who a sale was made to — shown on every stock-audit finding that sits on a sale/return.

  channel  — SOFTECH channel (ptclassifcode): عميل نقدى / Delivery / تعاقدات … stamped on the
             invoice (PurchaseHistory.sales_channel), else the sales account's own channel.
  account  — the sales account (stktrans.personcode → personsdata): Walk-In, a union, a contract …
             read from its account placeholder Customer (apps/customers/account_link.py).
  pic      — the customer PIC on the invoice (stktransm.phcode) + that customer's name.

Our tables only (PurchaseHistory + Customer, kept by the sales sync) — no SOFTECH reads here.
"""
from apps.customers.account_link import PLACEHOLDER_PREFIX

SALES_DOCCODES = {'115', '30'}


def invoice_key(branchcode, doccode, docnumber, docdate):
    """PurchaseHistory.softech_invoice_id for a ledger document."""
    return f'{branchcode}-{doccode}-{int(docnumber)}-{docdate:%Y%m%d}'


def _channel_labels():
    from apps.sync.models import SoftechPersonClassif
    labels = {}
    for ptcode, cls, descr in SoftechPersonClassif.objects.values_list('ptcode', 'ptclassifcode', 'ptclassifdescr'):
        # customer person types (10 corporate, 11 individual) win over supplier labels
        if descr and (cls not in labels or ptcode in ('10', '11')):
            labels[cls] = descr
    return labels


def accounts(personcodes):
    """{personcode: {'name', 'channel', 'channel_label'}} from the account placeholders."""
    from apps.customers.models import Customer
    codes = {str(c) for c in personcodes if c}
    out = {}
    for pic, name, cls, label in Customer.objects.filter(
            softech_pic__in=[PLACEHOLDER_PREFIX + c for c in codes]).values_list(
            'softech_pic', 'name', 'softech_ptclassifcode', 'person_classif_label'):
        out[pic[len(PLACEHOLDER_PREFIX):]] = {'name': name, 'channel': cls, 'channel_label': label}
    return out


def sales_context(findings):
    """{finding.id: {channel, channel_label, account_code, account_name, pic, pic_name}} for the
    findings that sit on a sale or return document; others are left out."""
    from apps.customers.models import Customer, PurchaseHistory
    on_sale = [f for f in findings if f.doccode in SALES_DOCCODES and f.docnumber and f.docdate]
    if not on_sale:
        return {}
    keys = {f.id: invoice_key(f.branchcode, f.doccode, f.docnumber, f.docdate) for f in on_sale}
    inv = {k: (ch, pic) for k, ch, pic in PurchaseHistory.objects.filter(softech_invoice_id__in=set(keys.values()))
           .values_list('softech_invoice_id', 'sales_channel', 'softech_phcode')}
    pics = {p for _, p in inv.values() if p}
    pic_names = dict(Customer.objects.filter(softech_pic__in=pics, is_account_placeholder=False)
                     .values_list('softech_pic', 'name'))
    accts = accounts({f.personcode for f in on_sale})
    labels = _channel_labels()
    out = {}
    for f in on_sale:
        ch, pic = inv.get(keys[f.id], ('', ''))
        acct = accts.get(f.personcode, {})
        channel = ch or acct.get('channel', '')
        out[f.id] = {
            'channel': channel,
            'channel_label': labels.get(channel) or acct.get('channel_label') or channel,
            'account_code': f.personcode, 'account_name': acct.get('name', ''),
            'pic': pic or '', 'pic_name': pic_names.get(pic, '') if pic else '',
        }
    return out


def channel_options():
    """Channels present among the sales accounts — for the grid's channel filter."""
    from apps.customers.models import Customer
    labels = _channel_labels()
    codes = set(Customer.objects.filter(is_account_placeholder=True).exclude(softech_ptclassifcode='')
                .values_list('softech_ptclassifcode', flat=True))
    return sorted(({'code': c, 'label': labels.get(c, c)} for c in codes), key=lambda x: x['label'])


def personcodes_in_channels(channels):
    """Sales-account codes whose channel is one of `channels` (for the channel filter)."""
    from apps.customers.models import Customer
    return [pic[len(PLACEHOLDER_PREFIX):] for pic in Customer.objects.filter(
        is_account_placeholder=True, softech_ptclassifcode__in=channels).values_list('softech_pic', flat=True)]
