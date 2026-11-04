"""Drafting engine (Plan 2 / Task 6): SOFTECH source docs → draft ledger entries, idempotently.

Per source type: read docs → upsert ``GLSourceDoc`` (new / changed / unchanged) → mark the docs the
reader no longer returns ``vanished`` → pick one rule per dirty doc → rebuild every touched group from
all its members → create / replace the group's draft, or reverse an approved entry and redraft.
A month that does not accept postings is never touched: the change becomes a
``SourceException(kind='closed_period_change')`` (Plan 3 posts the correction).

Entries are written only through ``ledger.save_draft`` / ``ledger.reverse`` (keyword arguments);
the engine never approves. Vanished drafts are deleted here with an audit row (Ruling P4).
"""
import logging
from collections import defaultdict
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.models import (
    FinancialPeriod, GLDraftRun, GLSourceDoc, LedgerEntry, PostingRule, SourceException,
)
from apps.users.models import StaffProfile

from . import ledger
from .ledger import LedgerError
from .rules import SOURCE_FIELDS, RuleMiss, build_lines, select_rule
from .sources import READERS, SourceDoc, _canon, content_hash
from .sources import expenses, purchases, sales, treasury  # noqa: F401  (register the readers)

try:   # Plan 3 Task 2
    from apps.finance.gl.periods import accepts_postings
except ImportError:   # same contract until Plan 3 lands
    def accepts_postings(d) -> bool:
        p = FinancialPeriod.objects.filter(year=d.year, month=d.month, period_type='month').first()
        return p is None or p.status == 'open'

logger = logging.getLogger(__name__)

SYSTEM_USERNAME = 'gl-drafting'
REVERSE_REASON = 'تغير مستند سوفتيك'
RESOLVED_NOTE = 'حُلّ تلقائياً عند إعادة الترحيل'
VANISHED_NOTE = 'اختفى المستند من سوفتيك'
STALE_AFTER = timedelta(hours=2)
SOURCE_ORDER = tuple(SOURCE_FIELDS)
COUNT_KEYS = ('read', 'new', 'changed', 'unchanged', 'vanished', 'drafted', 'skipped', 'exceptions',
              'created', 'replaced', 'reversed', 'deleted')
MEMBER_STATUSES = ('new', 'drafted', 'skipped')   # 'skipped' members = a zero group (group_key set)
LIVE = ('draft', 'approved')
GROUP_KINDS = ('closed_period_change', 'ledger_error')   # raised for a whole group; detail.group_key
MESSAGES = {
    'closed_period_change': 'تغير مستند سوفتيك في فترة لا تقبل الترحيل؛ يُصحح في أول شهر مفتوح',
    'duplicate_source_key': 'مفتاح المصدر مكرر في سوفتيك؛ لم يُرحل',
}


class DraftBusy(Exception):
    """Another drafting run is active (the API maps this to 409)."""


def system_user() -> StaffProfile:
    profile = StaffProfile.objects.select_related('user').filter(user__username=SYSTEM_USERNAME).first()
    if profile is None:   # same as the 0021 data step (Ruling P1)
        user, _ = User.objects.get_or_create(
            username=SYSTEM_USERNAME, defaults={'is_active': False, 'password': make_password(None)})
        profile, _ = StaffProfile.objects.get_or_create(user=user, defaults={'role': 'viewer'})
    return profile


def start_run(*, triggered_by, date_from, date_to, source_types) -> GLDraftRun:
    now = timezone.now()
    for stale in GLDraftRun.objects.filter(status='running', started_at__lt=now - STALE_AFTER):
        stale.status, stale.finished_at = 'failed', now
        stale.detail = {**(stale.detail or {}), 'error': 'stale run (no finish after 2 h)'}
        stale.save(update_fields=['status', 'finished_at', 'detail'])
    try:
        with transaction.atomic():
            return GLDraftRun.objects.create(
                triggered_by=(triggered_by or '')[:60], date_from=date_from, date_to=date_to,
                source_types=list(source_types or []), status='running')
    except IntegrityError:
        raise DraftBusy('a drafting run is already running')


def draft_range(date_from, date_to, *, source_types=None, run: GLDraftRun, fetch=None,
                readers=None) -> GLDraftRun:
    """Draft every source type in [date_from, date_to]. ``readers`` overrides ``READERS`` (tests)."""
    readers = READERS if readers is None else readers
    types = list(source_types) if source_types else [t for t in SOURCE_ORDER if t in readers]
    with ExitStack() as stack:
        if fetch is None:
            fetch = _lazy_fetch(stack)
        engine = _Engine(run, fetch, readers)
        try:
            engine.load()
            for t in types:
                engine.draft_type(t, date_from, date_to)
            run.status = 'partial' if engine.reader_errors else 'success'
        except Exception as exc:   # fatal: record, never leave the run 'running'
            logger.exception('gl drafting run %s failed', run.pk)
            run.status = 'failed'
            engine.detail['error'] = f'{type(exc).__name__}: {exc}'[:1000]
    run.counts = engine.counts
    run.detail = {**(run.detail or {}), **engine.detail}
    if engine.reader_errors:
        run.detail['reader_errors'] = engine.reader_errors
    run.finished_at = timezone.now()
    run.save(update_fields=['status', 'counts', 'detail', 'finished_at'])
    return run


def _lazy_fetch(stack):
    """One SOFTECH connection per run, opened only if a reader actually needs it."""
    holder = {}

    def fetch(sql):
        if 'f' not in holder:
            from apps.finance.queries.sybase_gl import open_fetch
            holder['f'] = stack.enter_context(open_fetch())
        return holder['f'](sql)
    return fetch


def _group_key(rule, doc) -> str:
    if rule.granularity == 'branch_day':
        return f'{rule.code}:{doc.branch_code}:{doc.doc_date.isoformat()}'
    if rule.granularity == 'party_day':
        return f'{rule.code}:{doc.personcode}:{doc.doc_date.isoformat()}'
    return doc.source_key


def _to_doc(sd: GLSourceDoc) -> SourceDoc:
    return SourceDoc(sd.source_type, sd.source_key, sd.doc_date, sd.branch_code, sd.kind, sd.personcode,
                     {k: Decimal(str(v)) for k, v in (sd.amounts or {}).items()}, dict(sd.attrs or {}))


def _line_tuple(ln: dict):
    return (str(ln['account_code']), Decimal(ln['debit']), Decimal(ln['credit']), ln.get('branch_id'),
            ln.get('party_code') or '', ln.get('description') or '', ln.get('cheque_no') or '',
            ln.get('due_date') or None)


class _Engine:
    def __init__(self, run, fetch, readers):
        self.run, self.fetch, self.readers = run, fetch, readers
        self.counts = dict.fromkeys(COUNT_KEYS, 0)
        self.detail = {'zero_groups': []}
        self.reader_errors = {}

    def load(self):
        """Once per run: system user, HQ branch and the active rules (a rule edit applies next run)."""
        self.user = system_user()
        hq = Branch.objects.filter(softech_branch_id='100').first()
        self.hq_id = hq.pk if hq else None
        self.rules = list(PostingRule.objects.filter(is_active=True))
        self._rule_cache = {r.pk: r for r in self.rules}

    # ── per source type ──────────────────────────────────────────────────────

    def draft_type(self, t, d1, d2):
        reader = self.readers.get(t)
        try:
            if reader is None:
                raise LookupError(f'no reader for {t}')
            docs = [d for d in reader(d1, d2, self.fetch) if d.source_type == t]
        except Exception as exc:   # a failed read: no vanish, other types continue
            logger.exception('gl reader %s failed', t)
            self.reader_errors[t] = f'{type(exc).__name__}: {exc}'[:500]
            return
        self.counts['read'] += len(docs)
        groups = defaultdict(set)        # group_key -> trigger doc pks
        with transaction.atomic():
            dirty = self._upsert(t, d1, d2, docs, groups)
        for sd, doc in dirty:
            self._classify(sd, doc, groups)
        for gk in sorted(groups):
            if gk:
                self._group(gk, groups[gk])

    def _old_groups(self, sd, open_details):
        keys = set()
        if sd.group_key:
            keys.add(sd.group_key)
        if sd.entry_id and sd.entry and sd.entry.status in LIVE and sd.entry.source_key:
            keys.add(sd.entry.source_key)
        for det in open_details.get(sd.pk, ()):
            if det.get('group_key'):
                keys.add(det['group_key'])
        return keys

    def _upsert(self, t, d1, d2, docs, groups):
        by_key, dups = {}, set()
        for d in docs:
            if d.source_key in by_key:
                dups.add(d.source_key)
            else:
                by_key[d.source_key] = d
        for k in dups:   # the reader returned one key twice: never merge, surface it
            b = by_key[k]
            by_key[k] = SourceDoc(t, k, b.doc_date, b.branch_code, '__duplicate__', '', {}, {})
        keys = list(by_key)
        existing = {}
        for i in range(0, len(keys), 1000):
            for sd in GLSourceDoc.objects.select_related('entry').filter(source_key__in=keys[i:i + 1000]):
                existing[sd.source_key] = sd
        window = GLSourceDoc.objects.select_related('entry').filter(
            source_type=t, doc_date__gte=d1, doc_date__lte=d2)
        gone = [sd for sd in window.exclude(status='vanished') if sd.source_key not in by_key]
        retry_vanished = [sd for sd in window.filter(status='vanished') if sd.source_key not in by_key]
        open_details = defaultdict(list)
        pks = [sd.pk for sd in existing.values()] + [sd.pk for sd in gone + retry_vanished]
        for i in range(0, len(pks), 1000):
            for doc_id, det in SourceException.objects.filter(
                    status='open', source_doc_id__in=pks[i:i + 1000]).values_list('source_doc_id', 'detail'):
                open_details[doc_id].append(det or {})

        now, dirty, create, seen = timezone.now(), [], [], []
        for key, d in by_key.items():
            h = content_hash(d)
            sd = existing.get(key)
            if sd is None:
                create.append((GLSourceDoc(
                    source_type=t, source_key=key, doc_date=d.doc_date, branch_code=d.branch_code,
                    kind=d.kind, personcode=d.personcode, amounts=_canon(d.amounts), attrs=_canon(d.attrs),
                    content_hash=h, status='new', last_run=self.run), d))
                self.counts['new'] += 1
                continue
            if sd.content_hash != h or sd.status == 'vanished' or sd.source_type != t:
                for g in self._old_groups(sd, open_details):
                    groups[g].add(sd.pk)
                sd.source_type, sd.doc_date, sd.branch_code = t, d.doc_date, d.branch_code
                sd.kind, sd.personcode = d.kind, d.personcode
                sd.amounts, sd.attrs = _canon(d.amounts), _canon(d.attrs)
                if sd.content_hash != h:
                    sd.version += 1
                sd.content_hash, sd.last_run = h, self.run
                sd.save()
                dirty.append((sd, d))
                self.counts['changed'] += 1
                continue
            self.counts['unchanged'] += 1
            seen.append(sd.pk)
            if self._needs_retry(sd, d, open_details):
                for g in self._old_groups(sd, open_details):
                    groups[g].add(sd.pk)
                dirty.append((sd, d))
        for sd, d in zip(GLSourceDoc.objects.bulk_create([c[0] for c in create]), [c[1] for c in create]):
            dirty.append((sd, d))
        for i in range(0, len(seen), 1000):
            GLSourceDoc.objects.filter(pk__in=seen[i:i + 1000]).update(last_seen=now, last_run=self.run)

        for sd in gone:
            for g in self._old_groups(sd, open_details):
                groups[g].add(sd.pk)
        if gone:
            gone_pks = [sd.pk for sd in gone]
            GLSourceDoc.objects.filter(pk__in=gone_pks).update(status='vanished', last_run=self.run)
            SourceException.objects.filter(source_doc_id__in=gone_pks, status='open').update(
                status='resolved', resolved_by=self.user, resolved_at=now, resolution_note=VANISHED_NOTE)
            self.counts['vanished'] += len(gone)
        for sd in retry_vanished:   # still linked to a live entry, or a closed-month change pending
            for g in self._old_groups(sd, open_details):
                groups[g].add(sd.pk)
        return dirty

    def _needs_retry(self, sd, doc, open_details) -> bool:
        if sd.status == 'new' or open_details.get(sd.pk):
            return True
        if sd.status == 'exception':   # only ignored exceptions left: finance decided
            return False
        if doc.kind == '__duplicate__':
            return False
        try:
            rule = select_rule(doc, self.rules)
        except RuleMiss:
            return True
        if rule.pk != sd.rule_id:
            return True   # a rule version change (Review Focus 5)
        if rule.action == 'skip':
            return not (sd.status == 'skipped' and not sd.group_key)
        if sd.group_key != _group_key(rule, doc):
            return True
        if sd.status == 'drafted':
            return not (sd.entry_id and sd.entry and sd.entry.status in LIVE)
        return sd.status != 'skipped'

    # ── per doc ──────────────────────────────────────────────────────────────

    def _set(self, pks, **fields):
        GLSourceDoc.objects.filter(pk__in=list(pks)).update(last_run=self.run, **fields)

    def _classify(self, sd, doc, groups):
        if doc.kind == '__duplicate__':
            self._exception([sd], 'duplicate_source_key', MESSAGES['duplicate_source_key'],
                            {'source_key': sd.source_key})
            self._set([sd.pk], status='exception', rule=None, group_key='')
            return
        try:
            rule = select_rule(doc, self.rules)
        except RuleMiss as miss:
            self._exception([sd], miss.kind, miss.message, miss.detail)
            self._set([sd.pk], status='exception', rule=None, group_key='')
            return
        if rule.action == 'skip':
            self._set([sd.pk], status='skipped', rule=rule, group_key='')
            self.counts['skipped'] += 1
            still_posted = sd.entry_id and sd.entry and sd.entry.status in LIVE
            if not still_posted:   # its old group (if any) resolves group-level exceptions
                self._resolve([sd.pk], exclude_group_kinds=True)
            return
        gk = _group_key(rule, doc)
        self._set([sd.pk], status='new', rule=rule, group_key=gk)
        groups[gk].add(sd.pk)

    # ── per group ────────────────────────────────────────────────────────────

    def _rule(self, pk):
        if pk not in self._rule_cache:
            self._rule_cache[pk] = PostingRule.objects.get(pk=pk)
        return self._rule_cache[pk]

    def _build(self, rule, members):
        """-> (lines, good members, [(bad member, RuleMiss)]). A failing doc never blocks the rest."""
        def build(sds):
            if self.hq_id is None and any(ln.get('branch') == 'hq' for ln in rule.lines):
                raise RuleMiss('unmapped_account', {'branch_code': '100'})
            return build_lines(rule, [_to_doc(s) for s in sds], hq_branch_id=self.hq_id)
        try:
            return build(members), members, []
        except RuleMiss:
            pass
        good, bad = [], []
        for sd in members:
            try:
                build([sd])
                good.append(sd)
            except RuleMiss as miss:
                bad.append((sd, miss))
        try:
            return (build(good) if good else []), good, bad
        except RuleMiss as miss:   # not expected: per-doc balanced lines sum to balanced lines
            return [], [], bad + [(sd, miss) for sd in good]

    def _group(self, gk, trigger_pks):
        try:
            with transaction.atomic():
                self._group_locked(gk, trigger_pks)
        except Exception:
            logger.exception('gl drafting group %s failed', gk)
            raise

    def _group_locked(self, gk, trigger_pks):
        live = (LedgerEntry.objects.select_for_update()
                .filter(source_key=gk, status__in=LIVE).first())
        members = list(GLSourceDoc.objects.filter(group_key=gk, status__in=MEMBER_STATUSES)
                       .order_by('doc_date', 'source_key', 'pk'))
        pending = [sd for sd in members if sd.status == 'new']
        targets = sorted({*trigger_pks, *(sd.pk for sd in pending)})
        lines, good, bad, rule = [], [], [], None
        if members:
            rule = self._rule((pending or members)[0].rule_id)
            lines, good, bad = self._build(rule, members)
        for sd, miss in bad:
            self._exception([sd], miss.kind, miss.message, miss.detail)
            self._set([sd.pk], status='exception', group_key='')
        bad_pks = {sd.pk for sd, _ in bad}
        targets = [pk for pk in targets if pk not in bad_pks]
        pending_ok = [sd.pk for sd in pending if sd.pk not in bad_pks]
        good_pks = [sd.pk for sd in good]

        if not lines:   # nothing to post: an empty or zero group
            if live is not None and not self._remove(live, gk, targets, pending_ok):
                return
            if good:
                self._set(good_pks, status='skipped', entry=None)
                self.counts['skipped'] += len(pending_ok)
                self.detail['zero_groups'].append(gk)
            self._settled(gk, live, None, good_pks, targets)
            return

        entry_date = good[0].doc_date
        desc = (lines[0].get('description') or rule.description or gk)[:500]
        branch_ids = {ln['branch_id'] for ln in lines if ln.get('branch_id')}
        branch = Branch.objects.get(pk=branch_ids.pop()) if len(branch_ids) == 1 else None
        if live is not None and self._same(live, entry_date, rule.book, desc, branch, good[0].source_type, lines):
            self._set(good_pks, status='drafted', entry=live)
            self.counts['drafted'] += len(pending_ok)
            self._settled(gk, live, live, good_pks, targets)
            return
        if not accepts_postings(entry_date) or (live is not None and not accepts_postings(live.entry_date)):
            self._closed(gk, live, targets, pending_ok, lines)
            return
        try:
            with transaction.atomic():
                kw = dict(user=self.user, entry_date=entry_date, description=desc, lines=lines,
                          book=rule.book, branch=branch, source_type=good[0].source_type, source_key=gk)
                if live is None:
                    entry = ledger.save_draft(**kw)
                    counts = ('created',)
                elif live.status == 'draft':
                    entry = ledger.save_draft(entry=live, **kw)
                    counts = ('replaced',)
                else:
                    ledger.reverse(live.pk, user=self.user, reason=REVERSE_REASON)
                    entry = ledger.save_draft(**kw)
                    counts = ('reversed', 'created')
        except LedgerError as err:
            self._ledger_error(gk, err, targets, pending_ok)
            return
        for c in counts:
            self.counts[c] += 1
        self._set(good_pks, status='drafted', entry=entry)
        self.counts['drafted'] += len(pending_ok)
        self._settled(gk, live, entry, good_pks, targets)

    def _remove(self, live, gk, targets, pending_ok) -> bool:
        """Delete a draft / reverse an approved entry whose group has nothing left to post."""
        if not accepts_postings(live.entry_date):
            self._closed(gk, live, targets, pending_ok, [])
            return False
        try:
            with transaction.atomic():
                if live.status == 'draft':   # Ruling P4: same as the Plan 1 DELETE view
                    ledger._audit('gl_entry_draft_deleted', user=self.user, obj=live,
                                  old_data=ledger._snapshot(live), note=REVERSE_REASON)
                    live.delete()
                    self.counts['deleted'] += 1
                else:
                    ledger.reverse(live.pk, user=self.user, reason=REVERSE_REASON)
                    self.counts['reversed'] += 1
        except LedgerError as err:
            self._ledger_error(gk, err, targets, pending_ok)
            return False
        return True

    def _same(self, live, entry_date, book, desc, branch, source_type, lines) -> bool:
        if (live.entry_date, live.book, live.description, live.branch_id, live.source_type) != (
                entry_date, book, desc, branch.pk if branch else None, source_type):
            return False
        old = [(ln.account.code, ln.debit, ln.credit, ln.branch_id, ln.party_code, ln.description,
                ln.cheque_no, ln.due_date)
               for ln in live.lines.select_related('account').order_by('line_no')]
        return old == [_line_tuple(ln) for ln in lines]

    def _settled(self, gk, old_entry, new_entry, good_pks, targets):
        """The group now matches its source docs: unlink leavers, resolve what this fixed."""
        if old_entry is not None and (new_entry is None or new_entry.pk != old_entry.pk):
            GLSourceDoc.objects.filter(entry_id=old_entry.pk).exclude(pk__in=good_pks).update(entry=None)
        elif new_entry is not None:
            GLSourceDoc.objects.filter(entry_id=new_entry.pk).exclude(pk__in=good_pks).update(entry=None)
        now = timezone.now()
        SourceException.objects.filter(source_doc_id__in=good_pks, status='open').update(
            status='resolved', resolved_by=self.user, resolved_at=now, resolution_note=RESOLVED_NOTE)
        SourceException.objects.filter(status='open', kind__in=GROUP_KINDS, detail__group_key=gk).update(
            status='resolved', resolved_by=self.user, resolved_at=now, resolution_note=RESOLVED_NOTE)

    def _closed(self, gk, live, targets, pending_ok, lines):
        detail = {'group_key': gk, 'entry_id': live.pk if live else None,
                  'entry_date': live.entry_date.isoformat() if live else None}
        original = live if live is not None and live.status == 'approved' else None
        docs = list(GLSourceDoc.objects.filter(pk__in=targets))
        self._exception(docs, 'closed_period_change', MESSAGES['closed_period_change'], detail,
                        original_entry=original, proposed_lines=_canon(lines))
        self._set(pending_ok, status='exception')

    def _ledger_error(self, gk, err, targets, pending_ok):
        docs = list(GLSourceDoc.objects.filter(pk__in=targets))
        self._exception(docs, 'ledger_error', err.message, {'code': err.code, 'group_key': gk, **err.detail})
        self._set(pending_ok, status='exception')

    # ── exceptions ───────────────────────────────────────────────────────────

    def _exception(self, docs, kind, message, detail, original_entry=None, proposed_lines=None):
        for sd in docs:
            SourceException.objects.update_or_create(
                source_doc=sd, kind=kind, status='open',
                defaults={'source_date': sd.doc_date, 'message': (message or '')[:500],
                          'detail': _canon(detail or {}), 'original_entry': original_entry,
                          'proposed_lines': proposed_lines})
        self.counts['exceptions'] += len(docs)

    def _resolve(self, pks, *, exclude_group_kinds=False):
        qs = SourceException.objects.filter(source_doc_id__in=list(pks), status='open')
        if exclude_group_kinds:
            qs = qs.exclude(kind__in=GROUP_KINDS)
        qs.update(status='resolved', resolved_by=self.user, resolved_at=timezone.now(),
                  resolution_note=RESOLVED_NOTE)
