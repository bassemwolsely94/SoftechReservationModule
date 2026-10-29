"""
Which Customer a synced SOFTECH invoice (PurchaseHistory) belongs to.

The buyer is the invoice's PIC (stktransm.phcode → Customer.softech_pic). An invoice with
no PIC (walk-in cash, most contract sales) belongs to its SOFTECH sales ACCOUNT
(stktrans.personcode → personsdata): one placeholder Customer per account,
softech_pic = 'ACCT-<personcode>', is_account_placeholder=True.

Never match stktrans.personcode against Customer.softech_id — softech_id is the PIC's
per-branch serial (5007 exists as 05HD5007, 08HD5007, 100HD5007 …); doing so attached
every invoice to a random person (fixed 2026-10-28).

READ-ONLY toward SOFTECH (personsdata names only).
"""
import logging

logger = logging.getLogger(__name__)

PLACEHOLDER_PREFIX = 'ACCT-'
_DB = 'SOFTECHDB9.dbo'


def placeholder_pic(personcode):
    return f'{PLACEHOLDER_PREFIX}{personcode}'


def fetch_accounts(conn, personcodes):
    """personsdata rows for these account codes → {code: (name, ptcode, ptclassifcode)}."""
    codes = sorted({str(c).strip() for c in personcodes if str(c or '').strip()})
    out = {}
    if conn is None or not codes:
        return out
    cur = conn.cursor()
    for i in range(0, len(codes), 200):
        chunk = codes[i:i + 200]
        marks = ', '.join('?' for _ in chunk)
        cur.execute(f'SELECT personcode, personname, ptcode, ptclassifcode FROM {_DB}.personsdata '
                    f'WHERE personcode IN ({marks})', chunk, timeout=60)
        for pc, name, ptc, cls in cur.fetchall():
            out[str(pc).strip()] = (str(name or '').strip(), str(ptc or '').strip(), str(cls or '').strip())
    return out


def ensure_account_placeholders(personcodes, conn=None):
    """Get-or-create the placeholder Customer of each account; names/channel from personsdata
    when `conn` is given (existing placeholders are refreshed). Returns {personcode: customer_id}."""
    from apps.customers.models import Customer
    from apps.sync.models import SoftechPersonClassif

    codes = {str(c).strip() for c in personcodes if str(c or '').strip()}
    if not codes:
        return {}
    existing = {c.softech_pic[len(PLACEHOLDER_PREFIX):]: c
                for c in Customer.objects.filter(softech_pic__in=[placeholder_pic(pc) for pc in codes])}
    try:
        accounts = fetch_accounts(conn, codes)
    except Exception as exc:                       # names are cosmetic — never block the sync
        logger.warning('[account_link] personsdata read failed: %s', str(exc)[:160])
        accounts = {}
    labels = {(p, c): d for p, c, d in SoftechPersonClassif.objects.values_list(
        'ptcode', 'ptclassifcode', 'ptclassifdescr')}

    out = {}
    for pc in codes:
        name, ptc, cls = accounts.get(pc, ('', '', ''))
        fields = {}
        if name:
            fields.update(name=name, softech_ptcode=ptc, softech_ptclassifcode=cls,
                          person_classif_label=labels.get((ptc, cls), ''))
        cust = existing.get(pc)
        if cust is None:
            cust = Customer.objects.create(
                softech_pic=placeholder_pic(pc), is_account_placeholder=True,
                **({'name': f'حساب {pc}'} | fields))
        elif fields and any(getattr(cust, k) != v for k, v in fields.items()):
            for k, v in fields.items():
                setattr(cust, k, v)
            cust.save(update_fields=list(fields))
        out[pc] = cust.id
    return out


class CustomerLinker:
    """Resolve invoice → Customer id. Build once per sync, call prepare() with the batch's
    account codes, then resolve() per invoice."""

    def __init__(self, conn=None):
        from apps.customers.models import Customer
        self.conn = conn
        self.by_pic = dict(Customer.objects.filter(is_account_placeholder=False)
                           .exclude(softech_pic__isnull=True).exclude(softech_pic='')
                           .values_list('softech_pic', 'id'))
        self.by_account = {}

    def prepare(self, personcodes):
        todo = {str(c).strip() for c in personcodes} - set(self.by_account)
        if todo:
            self.by_account.update(ensure_account_placeholders(todo, self.conn))

    def resolve(self, phcode, personcode):
        """PIC customer when the PIC is known, else the account placeholder, else None."""
        pic = (phcode or '').strip()
        if pic and pic in self.by_pic:
            return self.by_pic[pic]
        pc = (personcode or '').strip()
        if pc and pc not in self.by_account:
            self.prepare([pc])
        return self.by_account.get(pc)
