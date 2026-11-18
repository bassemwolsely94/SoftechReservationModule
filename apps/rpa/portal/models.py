"""Supplier-portal robot (Stage 1): portals, accounts, buy lists, jobs, baskets, lines, runs.

Nothing here writes SOFTECH or stores a secret. PortalAccount holds only a label and a branch.
"""
from django.db import models
from django.db.models import Q

from apps.rpa.models import RpaDevice


class SupplierPortal(models.Model):
    KEYS = [('pharma_overseas', 'Pharma Overseas'), ('ibn_sina', 'Ibn Sina')]
    DRIVERS = [('web', 'web'), ('android', 'android')]

    key = models.CharField(max_length=30, unique=True, choices=KEYS)
    supplier_code = models.CharField(max_length=8)
    driver = models.CharField(max_length=10, choices=DRIVERS, default='web')
    enabled = models.BooleanField(default=False)
    live = models.BooleanField(default=False)   # False = dry-run only
    basket_size = models.PositiveSmallIntegerField(default=10)
    short_expiry_months = models.PositiveSmallIntegerField(default=12)
    price_jump_pct = models.DecimalField(max_digits=5, decimal_places=2, default=10)

    def __str__(self):
        return self.key


class PortalAccount(models.Model):
    portal = models.ForeignKey(SupplierPortal, on_delete=models.PROTECT, related_name='accounts')
    label = models.CharField(max_length=120)
    paper_branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, null=True, blank=True,
                                     related_name='portal_accounts')
    identity_text = models.CharField(max_length=255, blank=True, default='')
    active = models.BooleanField(default=True)
    last_credit = models.JSONField(default=dict, blank=True)   # {"consumption","credit","limit","at"}

    def __str__(self):
        return self.label


class BuyList(models.Model):
    SOURCE_KINDS = [('pivot', 'pivot'), ('isr', 'isr'), ('upload', 'upload')]
    STATUS = [('open', 'open'), ('closed', 'closed')]

    source_kind = models.CharField(max_length=10, choices=SOURCE_KINDS)
    source_ref = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=8, choices=STATUS, default='open')
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT,
                                   related_name='portal_buylists')
    created_at = models.DateTimeField(auto_now_add=True)


class BuyListLine(models.Model):
    buylist = models.ForeignKey(BuyList, on_delete=models.CASCADE, related_name='lines')
    seq = models.PositiveIntegerField(default=1)
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='portal_buylines')
    needed_qty = models.PositiveIntegerField()
    remaining_qty = models.PositiveIntegerField()
    chosen_supplier = models.CharField(max_length=120, blank=True, default='')
    tried = models.JSONField(default=list, blank=True)   # [{"supplier","accepted","at","basket"}]
    source_key = models.CharField(max_length=120, blank=True, default='')
    reason = models.CharField(max_length=255, blank=True, default='')   # over-need reason
    # True while the buy list is open; one source line sits in at most one open buy list.
    open_guard = models.BooleanField(default=True)

    class Meta:
        ordering = ['buylist_id', 'seq']
        constraints = [
            models.UniqueConstraint(fields=['source_key'], condition=Q(open_guard=True) & ~Q(source_key=''),
                                    name='portal_buyline_open_source_uniq'),
        ]


class PortalJob(models.Model):
    KINDS = [('order', 'order')]
    STATUS = [('draft', 'draft'), ('approved', 'approved'), ('cancelled', 'cancelled'), ('done', 'done')]

    portal = models.ForeignKey(SupplierPortal, on_delete=models.PROTECT, related_name='jobs')
    account = models.ForeignKey(PortalAccount, on_delete=models.PROTECT, related_name='jobs')
    buylist = models.ForeignKey(BuyList, on_delete=models.PROTECT, related_name='jobs')
    kind = models.CharField(max_length=10, choices=KINDS, default='order')
    status = models.CharField(max_length=10, choices=STATUS, default='draft')
    dry_run = models.BooleanField(default=True)
    estimated_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT,
                                   related_name='portal_jobs_created')
    approved_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='portal_jobs_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class PortalBasket(models.Model):
    STATUS = [
        ('pending', 'pending'), ('ready', 'ready'), ('in_progress', 'in_progress'),
        ('dry_run_ok', 'dry_run_ok'), ('awaiting_submit', 'awaiting_submit'),
        ('submitted', 'submitted'), ('recorded', 'recorded'), ('needs_person', 'needs_person'),
        ('cancelled', 'cancelled'),
    ]
    job = models.ForeignKey(PortalJob, on_delete=models.CASCADE, related_name='baskets')
    seq = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=STATUS, default='pending')
    claimed_by = models.ForeignKey(RpaDevice, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='portal_baskets')
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)
    submitted_seen_at = models.DateTimeField(null=True, blank=True)
    portal_ref = models.CharField(max_length=60, blank=True, default='')
    # '<portal.key>:<portal_ref>', blank when there is no ref.
    portal_key = models.CharField(max_length=100, blank=True, default='')
    order_ref = models.CharField(max_length=60, blank=True, default='')
    credit_seen = models.JSONField(default=dict, blank=True)
    needs_person_reason = models.CharField(max_length=255, blank=True, default='')
    # when it last went to needs_person: an Order History read counts for a retry only if it
    # started after this moment (apps/rpa/portal/queue.resolve)
    needs_person_at = models.DateTimeField(null=True, blank=True)
    diff = models.JSONField(default=dict, blank=True)   # handed-over vs recorded

    class Meta:
        ordering = ['job_id', 'seq']
        constraints = [
            models.UniqueConstraint(fields=['job', 'seq'], name='portal_basket_job_seq_uniq'),
            models.UniqueConstraint(fields=['portal_key'], condition=~Q(portal_key=''),
                                    name='portal_basket_portal_key_uniq'),
        ]


class PortalLine(models.Model):
    STATUS = [('pending', 'pending'), ('ok', 'ok'), ('short', 'short'), ('out', 'out'),
              ('not_found', 'not_found'), ('removed', 'removed')]
    basket = models.ForeignKey(PortalBasket, on_delete=models.CASCADE, related_name='lines')
    buyline = models.ForeignKey(BuyListLine, on_delete=models.PROTECT, related_name='portal_lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='portal_lines')
    wanted_qty = models.PositiveIntegerField()
    accepted_qty = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='pending')
    supplier_key = models.CharField(max_length=40, blank=True, default='')
    supplier_key_padded = models.CharField(max_length=40, blank=True, default='')
    supplier_name_seen = models.CharField(max_length=255, blank=True, default='')
    price = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    discount_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    bonus_text = models.CharField(max_length=120, blank=True, default='')
    supplier_expiry = models.DateField(null=True, blank=True)
    flags = models.JSONField(default=list, blank=True)
    message = models.CharField(max_length=255, blank=True, default='')
    availability_line = models.ForeignKey('supply.AvailabilityLine', on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='portal_lines')

    class Meta:
        ordering = ['basket_id', 'id']


class PortalRun(models.Model):
    KINDS = [('discovery', 'discovery'), ('fill', 'fill'), ('history', 'history')]
    MODES = [('dry_run', 'dry_run'), ('live', 'live')]

    basket = models.ForeignKey(PortalBasket, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='runs')
    discovery_job = models.ForeignKey(PortalJob, on_delete=models.CASCADE, null=True, blank=True,
                                      related_name='discovery_runs')
    kind = models.CharField(max_length=10, choices=KINDS)
    device = models.ForeignKey(RpaDevice, on_delete=models.PROTECT, null=True, blank=True,
                               related_name='portal_runs')
    mode = models.CharField(max_length=8, choices=MODES, default='dry_run')
    started_at = models.DateTimeField()
    # discovery / history runs have no basket lease, so they carry their own (fill runs use the
    # basket's lease_until); a queued history run has device=None until a device takes it
    lease_until = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=30, blank=True, default='')
    steps = models.JSONField(default=list, blank=True)
