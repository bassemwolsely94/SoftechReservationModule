"""Drafting engine (Plan 2 / Task 6): SOFTECH source docs → draft ledger entries, idempotently.

Per source type: read docs → upsert ``GLSourceDoc`` (new / changed / unchanged) → mark the docs the
reader no longer returns ``vanished`` → pick one rule per dirty doc → rebuild every touched group from
all its members → create / replace the group's draft, or reverse an approved entry and redraft.
A month that does not accept postings is never touched: the change becomes a
``SourceException(kind='closed_period_change')`` (Plan 3 posts the correction).

Entries are written only through ``ledger.save_draft`` / ``ledger.reverse`` (keyword arguments);
the engine never approves. Vanished drafts are deleted here with an audit row (Ruling P4).
"""
import hashlib
import json
import logging
from collections import defaultdict
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.finance.models import (
    GLDraftRun, GLSourceDoc, LedgerEntry, PostingRule, SourceException,
)
from apps.users.models import StaffProfile

from . import ledger
from .corrections import effective_lines, net_lines
from .ledger import LedgerError
from .periods import accepts_postings
from .rules import SOURCE_FIELDS, RuleMiss, build_lines, select_rule
from .sources import READERS, SourceDoc, _canon, content_hash
from .sources import expenses, purchases, sales, treasury  # noqa: F401  (register the readers)

logger = logging.getLogger(__name__)

SYSTEM_USERNAME = 'gl-drafting'
REVERSE_REASON = 'تغير مستند سوفتيك'
RESOLVED_NOTE = 'حُلّ تلقائياً عند إعادة الترحيل'
VANISHED_NOTE = 'اختفى المستند من سوفتيك'
STALE_AFTER = timedelta(minutes=30)   # Ruling P11: no heartbeat for 30 min = crashed
VANISH_GUARD_SHARE = Decimal('0.2')   # Ruling P10
VANISH_GUARD_MIN = 10
SOURCE_ORDER = tuple(SOURCE_FIELDS)
COUNT_KEYS = ('read', 'new', 'changed', 'unchanged', 'vanished', 'drafted', 'skipped', 'exceptions',
              'created', 'replaced', 'reversed', 'deleted')
MEMBER_STATUSES = ('new', 'drafted', 'skipped')   # 'skipped' members = a zero group (group_key set)
LIVE = ('draft', 'approved')
GROUP_KINDS = ('closed_period_change', 'ledger_error')   # raised for a whole group; detail.group_key
MESSAGES = {
    'closed_period_change': 'تغير مستند سوفتيك في فترة لا تقبل الترحيل؛ يُصحح في أول شهر مفتوح',
    'edited_by_user': 'عدّل محاسب هذا القيد يدوياً وتغير مستند سوفتيك؛ لم يُستبدل القيد — راجعه يدوياً',
    'duplicate_source_key': 'مفتاح المصدر مكرر في سوفتيك؛ لم يُرحل',
}


class DraftBusy(Exception):
    """Another drafting run is active (the API maps this to 409)."""


class _Superseded(Exception):
    """This run's row is no longer 'running' (a stale takeover marked it failed)."""


def system_user() -> StaffProfile:
    """Ruling P12: get_or_create with the 0021 data-step attributes (inactive, unusable password,
    role 'viewer'), so a flushed database (TransactionTestCase) never breaks drafting."""
    user, _ = User.objects.get_or_create(
        username=SYSTEM_USERNAME, defaults={'is_active': False, 'password': make_password(None)})
    profile, _ = StaffProfile.objects.select_related('user').get_or_create(
        user=user, defaults={'role': 'viewer'})
    return profile


def start_run(*, triggered_by, date_from, date_to, source_types) -> GLDraftRun:
    now = timezone.now()
    cutoff = now - STALE_AFTER
    for stale in GLDraftRun.objects.filter(status='running').filter(
            Q(heartbeat_at__lt=cutoff) | Q(heartbeat_at__isnull=True, started_at__lt=cutoff)):
        stale.status, stale.finished_at = 'failed', now
        stale.detail = {**(stale.detail or {}), 'error': 'stale run (no heartbeat for 30 min)'}
        stale.save(update_fields=['status', 'finished_at', 'detail'])
    try:
        with transaction.atomic():
            return GLDraftRun.objects.create(
                triggered_by=(triggered_by or '')[:60], date_from=date_from, date_to=date_to,
                source_types=list(source_types or []), status='running', heartbeat_at=now)
    except IntegrityError:
        raise DraftBusy('a drafting run is already running')


def mark_failed(run_id, exc) -> None:
    """Last-line-of-defence crash marking (scheduler job / draft-now thread): status 'failed',
    finished_at and detail.error, only if the run is still 'running'."""
    run = GLDraftRun.objects.filter(pk=run_id, status='running').first()
    if run is None:
        return
    run.status, run.finished_at = 'failed', timezone.now()
    run.detail = {**(run.detail or {}), 'error': f'{type(exc).__name__}: {exc}'[:1000]}
    run.save(update_fields=['status', 'finished_at', 'detail'])


def draft_range(date_from, date_to, *, source_types=None, run: GLDraftRun, fetch=None,
                readers=None, allow_mass_vanish=False) -> GLDraftRun:
    """Draft every source type in [date_from, date_to]. ``readers`` overrides ``READERS`` (tests).
    ``allow_mass_vanish`` bypasses the Ruling P10 guard (CLI --allow-mass-vanish only)."""
    readers = READERS if readers is None else readers
    types = list(source_types) if source_types else [t for t in SOURCE_ORDER if t in readers]
    with ExitStack() as stack:
        if fetch is None:
            fetch = _lazy_fetch(stack)
        engine = _Engine(run, fetch, readers, allow_mass_vanish=allow_mass_vanish)
        try:
            engine.load()
            for t in types:
                engine.heartbeat()
                engine.draft_type(t, date_from, date_to)
            partial = engine.reader_errors or engine.group_errors or engine.detail.get('vanish_guard')
            run.status = 'partial' if partial else 'success'
        except _Superseded:
            logger.warning('gl drafting run %s superseded', run.pk)
            run.status = 'failed'
            engine.detail['error'] = 'superseded'
        except Exception as exc:   # fatal: record, never leave the run 'running'
            logger.exception('gl drafting run %s failed', run.pk)
            run.status = 'failed'
            engine.detail['error'] = f'{type(exc).__name__}: {exc}'[:1000]
    run.counts = engine.counts
    run.detail = {**(run.detail or {}), **engine.detail}
    if engine.reader_errors:
        run.detail['reader_errors'] = engine.reader_errors
    if engine.group_errors:
        run.detail['group_errors'] = engine.group_errors
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


def group_proposal(gk):
    """(canonical lines, member keys): what a rebuild of the group proposes from the amounts its docs last read, with
    no SOFTECH read. Lines None when they no longer build (a rule or map changed): a redraft reports why."""
    members = list(GLSourceDoc.objects.filter(group_key=gk, status__in=(*MEMBER_STATUSES, 'exception'))
                   .select_related('rule').order_by('doc_date', 'source_key', 'pk')) if gk else []
    keys = [sd.source_key for sd in members]
    if not members:
        return [], keys
    rule = next((sd.rule for sd in members if sd.status == 'new' and sd.rule_id), None) or members[0].rule
    hq = Branch.objects.filter(softech_branch_id='100').first()
    if rule is None or (hq is None and any(ln.get('branch') == 'hq' for ln in rule.lines)):
        return None, keys
    try:
        return _canon(build_lines(rule, [_to_doc(sd) for sd in members], hq_branch_id=hq.pk if hq else None)), keys
    except RuleMiss:
        return None, keys


def _line_tuple(ln: dict):
    return (str(ln['account_code']), Decimal(ln['debit']), Decimal(ln['credit']), ln.get('branch_id'),
            ln.get('party_code') or '', ln.get('description') or '', ln.get('cheque_no') or '',
            ln.get('due_date') or None)


class _Engine:
    def __init__(self, run, fetch, readers, allow_mass_vanish=False):
        self.run, self.fetch, self.readers = run, fetch, readers
        self.allow_mass_vanish = allow_mass_vanish
        self.counts = dict.fromkeys(COUNT_KEYS, 0)
        self.detail = {'zero_groups': []}
        self.reader_errors = {}
        self.group_errors = {}

    def heartbeat(self):
        """Ruling P11: refresh heartbeat_at; abort if the run row is no longer ours ('running')."""
        if not GLDraftRun.objects.filter(pk=self.run.pk, status='running').update(heartbeat_at=timezone.now()):
            raise _Superseded()

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
        self.old_of = defaultdict(set)   # doc pk -> groups it may still sit in (rebuilt first)
        with transaction.atomic():
            dirty = self._upsert(t, d1, d2, docs, groups)
        for sd, doc in dirty:
            self._classify(sd, doc, groups)
        self._done = set()
        for gk in sorted(groups):
            self._process(gk, groups)

    def _touch_old(self, sd, open_details, groups):
        for g in self._old_groups(sd, open_details):
            groups[g].add(sd.pk)
            self.old_of[sd.pk].add(g)

    def _process(self, gk, groups):
        """Rebuild ``gk`` after the old groups of its pending members (I1c), so a doc whose old
        group could not be rebuilt is held out (status 'exception') instead of sitting in two
        live entries. A non-LedgerError failure becomes a ledger_error exception; the run goes on."""
        if not gk or gk in self._done:
            return
        self._done.add(gk)
        pending = list(GLSourceDoc.objects.filter(group_key=gk, status='new').values_list('pk', flat=True))
        for pk in pending:
            for og in sorted(self.old_of.get(pk, ())):
                if og != gk:
                    self._process(og, groups)
        self.heartbeat()
        triggers = groups.get(gk, set())
        try:
            with transaction.atomic():
                self._group_locked(gk, triggers)
        except (_Superseded, KeyboardInterrupt):
            raise
        except Exception as exc:
            logger.exception('gl drafting group %s failed', gk)
            self._group_failed(gk, triggers, exc)

    def _group_failed(self, gk, triggers, exc):
        err = f'{type(exc).__name__}: {exc}'[:300]
        self.group_errors[gk] = err
        pending = GLSourceDoc.objects.filter(group_key=gk, status='new').values_list('pk', flat=True)
        targets = {*triggers, *pending}
        with transaction.atomic():
            self._exception(list(GLSourceDoc.objects.filter(pk__in=targets)), 'ledger_error',
                            f'تعذر ترحيل المجموعة: {err}', {'code': 'engine_error', 'group_key': gk, 'error': err})
            self._hold(targets)

    def _hold(self, pks):
        """Keep docs out of every group until their old group is rebuilt (retried next run)."""
        GLSourceDoc.objects.filter(pk__in=list(pks)).exclude(status='vanished').update(
            status='exception', last_run=self.run)

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
        # Ruling P19: a closed_period_change sits on one member only; the others are found here
        by_member = defaultdict(list)
        for det in SourceException.objects.filter(status='open', kind='closed_period_change').values_list(
                'detail', flat=True):
            for k in (det or {}).get('member_source_keys') or ():
                by_member[k].append(det)
        if by_member:
            for sd in [*existing.values(), *gone, *retry_vanished]:
                for det in by_member.get(sd.source_key, ()):
                    if det not in open_details[sd.pk]:
                        open_details[sd.pk].append(det)

        # previously-seen docs of this type in the window (before this read changes any status)
        seen_before = len(gone) + sum(1 for sd in existing.values() if sd.status != 'vanished'
                                      and sd.source_type == t and d1 <= sd.doc_date <= d2)
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
                self._touch_old(sd, open_details, groups)
                sd.status = 'new'   # I1a: a crash before classify still retries it next run
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
                self._touch_old(sd, open_details, groups)
                dirty.append((sd, d))
        for sd, d in zip(GLSourceDoc.objects.bulk_create([c[0] for c in create]), [c[1] for c in create]):
            dirty.append((sd, d))
        for i in range(0, len(seen), 1000):
            GLSourceDoc.objects.filter(pk__in=seen[i:i + 1000]).update(last_seen=now, last_run=self.run)

        if (gone and not self.allow_mass_vanish and len(gone) > VANISH_GUARD_MIN
                and len(gone) > VANISH_GUARD_SHARE * seen_before):
            # Ruling P10: a silently empty / short read must never reverse entries en masse
            self.detail.setdefault('vanish_guard', {})[t] = {'would_vanish': len(gone), 'seen': seen_before}
            gone = []
        for sd in gone:
            self._touch_old(sd, open_details, groups)
        if gone:
            gone_pks = [sd.pk for sd in gone]
            GLSourceDoc.objects.filter(pk__in=gone_pks).update(status='vanished', last_run=self.run)
            SourceException.objects.filter(source_doc_id__in=gone_pks, status='open').exclude(
                kind__in=GROUP_KINDS).update(   # C1: group kinds resolve only with their group
                status='resolved', resolved_by=self.user, resolved_at=now, resolution_note=VANISHED_NOTE)
            self.counts['vanished'] += len(gone)
        for sd in retry_vanished:   # still linked to a live entry, or a closed-month change pending
            self._touch_old(sd, open_details, groups)
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
        entry_live = bool(sd.entry_id and sd.entry and sd.entry.status in LIVE)
        if rule.action == 'skip':   # I1b: a skipped doc still inside a live entry must be removed
            return not (sd.status == 'skipped' and not sd.group_key) or entry_live
        if sd.group_key != _group_key(rule, doc):
            return True
        if sd.status == 'drafted':
            return not entry_live
        return sd.status != 'skipped' or entry_live

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
            if (live is not None and not self._corrected_to(live, lines)
                    and not self._remove(live, gk, targets, pending_ok, {'held_out': len(bad)})):
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
        if live is not None and (
                self._corrected_to(live, lines) if self._live_corrections(live).exists()
                else self._same(live, entry_date, rule.book, desc, branch, good[0].source_type, lines)):
            self._set(good_pks, status='drafted', entry=live)
            self.counts['drafted'] += len(pending_ok)
            self._settled(gk, live, live, good_pks, targets)
            return
        if (not accepts_postings(entry_date)
                or (live is not None and not self._can_reverse(live))):
            if live is not None and net_lines(lines) == effective_lines(live, include_drafts=True):
                # a description or attribute only: the ledger already says this, nothing to correct
                self._set(good_pks, status='drafted', entry=live)
                self.counts['drafted'] += len(pending_ok)
                self._settled(gk, live, live, good_pks, targets)
                return
            self._closed(gk, live, targets, pending_ok, lines)
            return
        if live is not None and self._edited_by_user(live):
            self._edited(gk, live, targets, pending_ok, lines,
                         {'proposed_entry_date': entry_date.isoformat(), 'proposed_description': desc,
                          'held_out': len(bad)})
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
                    self._reverse_live(live)
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

    def _remove(self, live, gk, targets, pending_ok, edited_extra=None) -> bool:
        """Delete a draft / reverse an approved entry whose group has nothing left to post."""
        if not self._can_reverse(live):
            self._closed(gk, live, targets, pending_ok, [])
            return False
        if self._edited_by_user(live):
            self._edited(gk, live, targets, pending_ok, [], edited_extra)
            return False
        try:
            with transaction.atomic():
                if live.status == 'draft':
                    self._delete_draft(live)
                    self.counts['deleted'] += 1
                else:
                    self._reverse_live(live)
                    self.counts['reversed'] += 1
        except LedgerError as err:
            self._ledger_error(gk, err, targets, pending_ok)
            return False
        return True

    def _live_corrections(self, live):
        return live.corrections.filter(status__in=LIVE)

    def _corrected_to(self, live, lines) -> bool:
        """The entry has corrections, and with them it already says what the group proposes."""
        return (self._live_corrections(live).exists()
                and net_lines(lines) == effective_lines(live, include_drafts=True))

    def _can_reverse(self, live) -> bool:
        """The entry and every live correction of it sit in months that take postings."""
        return accepts_postings(live.entry_date) and all(
            accepts_postings(day) for day in self._live_corrections(live).values_list('entry_date', flat=True))

    def _reverse_live(self, live):
        """Reverse an approved entry in its own month, its corrections with it (the redraft carries
        the whole figure). The date is explicit: a month closing mid-run must raise, not post a
        mirror into a later month. Runs inside the caller's transaction."""
        for fix in self._live_corrections(live).select_for_update():
            if fix.status == 'draft':
                self._delete_draft(fix)
            else:
                ledger.reverse(fix.pk, user=self.user, reason=REVERSE_REASON, entry_date=fix.entry_date,
                               _from_engine=True)
        ledger.reverse(live.pk, user=self.user, reason=REVERSE_REASON, entry_date=live.entry_date, _from_engine=True)

    def _delete_draft(self, draft):   # Ruling P4: same as the Plan 1 DELETE view
        ledger._audit('gl_entry_draft_deleted', user=self.user, obj=draft,
                      old_data=ledger._snapshot(draft), note=REVERSE_REASON)
        draft.delete()

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
        SourceException.objects.filter(source_doc_id__in=good_pks, status='open').exclude(
            kind__in=GROUP_KINDS).update(   # C1: a closed-month change on another group stays open
            status='resolved', resolved_by=self.user, resolved_at=now, resolution_note=RESOLVED_NOTE)
        SourceException.objects.filter(status='open', kind__in=GROUP_KINDS, detail__group_key=gk).update(
            status='resolved', resolved_by=self.user, resolved_at=now, resolution_note=RESOLVED_NOTE)

    def _closed(self, gk, live, targets, pending_ok, lines):
        """Ruling P19: ONE closed_period_change per group, on its first member (lowest source_key),
        listing every member; the other members are held (status 'exception', no row of their own)
        and are retried with the group until that exception resolves (Plan 3 corrects per group)."""
        docs = {sd.pk: sd for sd in GLSourceDoc.objects.filter(
            Q(pk__in=targets) | Q(group_key=gk, status__in=MEMBER_STATUSES))}
        members = sorted(docs.values(), key=lambda sd: (sd.source_key, sd.pk))
        detail = {'group_key': gk, 'entry_id': live.pk if live else None,
                  'entry_date': live.entry_date.isoformat() if live else None,
                  'member_source_keys': [sd.source_key for sd in members]}
        original = live if live is not None and live.status == 'approved' else None
        fields = {'message': MESSAGES['closed_period_change'], 'detail': _canon(detail),
                  'original_entry': original, 'proposed_lines': _canon(lines)}
        row = (SourceException.objects.select_for_update()
               .filter(status='open', kind='closed_period_change', detail__group_key=gk).order_by('pk').first())
        if row is None:
            # one open row per doc and kind: a member holding another group's open change is never
            # taken over. A member still in this group first, then any free one. All busy: no row;
            # each of them has an open row, so the next run retries (mark_exception_resolved
            # releases a member that moved here once the row it holds resolves).
            busy = set(SourceException.objects.filter(
                status='open', kind='closed_period_change', source_doc_id__in=list(docs))
                .values_list('source_doc_id', flat=True))
            free = [sd for sd in members if sd.pk not in busy]
            holder = next((sd for sd in free if sd.group_key == gk), free[0] if free else None)
            if holder is not None:
                SourceException.objects.create(
                    source_doc=holder, kind='closed_period_change', status='open',
                    source_date=holder.doc_date, **fields)
                self.counts['exceptions'] += 1
            elif members:
                self.group_errors[gk] = 'holder_busy'
        else:
            if row.source_doc_id in docs:   # its date can move (a document-granularity group's key has none)
                fields['source_date'] = docs[row.source_doc_id].doc_date
            for k, v in fields.items():
                setattr(row, k, v)
            row.save(update_fields=list(fields))
            self.counts['exceptions'] += 1
        self._set(pending_ok, status='exception')

    def _edited_by_user(self, live) -> bool:
        return edited_by_user(live, system=self.user)

    def _edited(self, gk, live, targets, pending_ok, lines, extra=None):
        """Ruling P21: never overwrite an accountant's edit; the group waits in the inbox.
        Ruling P23: the row carries the fresh rule lines so the accountant can compare and decide."""
        docs = list(GLSourceDoc.objects.filter(pk__in=targets))
        self._exception(docs, 'ledger_error', MESSAGES['edited_by_user'],
                        {'code': 'edited_by_user', 'entry_id': live.pk, 'group_key': gk,
                         'entry_status': live.status, **(extra or {})},
                        proposed_lines=_canon(lines))
        self._hold({*targets, *pending_ok})

    def _ledger_error(self, gk, err, targets, pending_ok):
        docs = list(GLSourceDoc.objects.filter(pk__in=targets))
        self._exception(docs, 'ledger_error', err.message, {'code': err.code, 'group_key': gk, **err.detail})
        self._hold({*targets, *pending_ok})

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


# ── Ruling P23: the accountant decides on an edited entry SOFTECH changed ────

EDIT_RELEASED = 'gl_entry_edit_released'   # accept SOFTECH: earlier edits no longer protect the entry
EDIT_KEPT = 'gl_entry_edit_kept'           # keep my edit: nothing happens until the next change
ACCEPT_NOTE = 'اعتُمدت نسخة سوفتيك'
KEEP_NOTE = 'أُبقي تعديل المحاسب'
LATE_POSTED = ('gl_late_document_drafted', 'gl_late_correction_drafted')   # corrections.py


class DecisionError(Exception):
    """A refused accept / keep decision; the API maps ``code`` to 404 / 409."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def edited_by_user(live, *, system=None) -> bool:
    """Ruling P21 + P23: an accountant (anyone but the drafting user) saved this entry after the
    latest «اعتماد نسخة سوفتيك» on it. AuditLog ids are monotonic, so "newer" = higher id.
    A late document or correction is saved under the accountant who posted it, with its own audit
    row right after: that save is the system's lines, not an edit."""
    system = system or system_user()
    rows = AuditLog.objects.filter(model_name='LedgerEntry', object_id=str(live.pk))
    released = (rows.filter(action__in=(EDIT_RELEASED, *LATE_POSTED)).order_by('-id')
                .values_list('id', flat=True).first())
    edits = rows.filter(action='gl_entry_draft_saved').exclude(user_id=system.pk)
    if released:
        edits = edits.filter(id__gt=released)
    return edits.exists()


def proposal_version(proposed_lines) -> str:
    """Staleness token of what the accountant compared: sha256 of the canonical proposed lines."""
    raw = json.dumps(_canon(proposed_lines or []), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _engine_running() -> bool:
    cutoff = timezone.now() - STALE_AFTER
    return GLDraftRun.objects.filter(status='running').filter(
        Q(heartbeat_at__gte=cutoff) | Q(heartbeat_at__isnull=True, started_at__gte=cutoff)).exists()


STALE = 'تغيّرت نسخة سوفتيك — راجعها مرة أخرى'


def _decision(exception_id, version):
    """Validate an open edited_by_user exception and lock its group in the engine's order
    (LedgerEntry -> GLSourceDoc -> SourceException), re-checking after the locks.
    -> (row, group_key, group rows, docs, entry)."""
    ex = SourceException.objects.filter(pk=exception_id).first()
    if ex is None:
        raise DecisionError('not_found', 'الاستثناء غير موجود')

    def check(row):
        if row.status != 'open':
            raise DecisionError('not_open', 'الاستثناء ليس مفتوحاً')
        d = row.detail or {}
        if row.kind != 'ledger_error' or d.get('code') != 'edited_by_user':
            raise DecisionError('not_edited_by_user', 'هذا الاستثناء ليس تعديلاً يدوياً غيّره سوفتيك')
        return d
    detail = check(ex)
    gk = detail.get('group_key') or ''
    group = SourceException.objects.filter(
        status='open', kind='ledger_error', detail__code='edited_by_user', detail__group_key=gk)
    entry = LedgerEntry.objects.select_for_update().filter(pk=detail.get('entry_id')).first()
    if entry is None:
        raise DecisionError('entry_gone', 'القيد لم يعد موجوداً — أعد الترحيل')
    docs = list(GLSourceDoc.objects.select_for_update().filter(
        pk__in=set(group.values_list('source_doc_id', flat=True))).order_by('pk'))
    ex = SourceException.objects.select_for_update().get(pk=ex.pk)
    detail = check(ex)
    if detail.get('group_key') != gk or detail.get('entry_id') != entry.pk:
        raise DecisionError('stale', STALE)
    if version is not None and str(version) != proposal_version(ex.proposed_lines):
        raise DecisionError('stale', STALE)
    rows = list(group.select_for_update().order_by('pk'))
    if {r.source_doc_id for r in rows} - {d.pk for d in docs}:   # the group grew meanwhile
        raise DecisionError('stale', STALE)
    return ex, gk, rows, docs, entry


def _close(rows, user, note):
    now = timezone.now()
    for r in rows:
        r.status, r.resolved_by, r.resolved_at, r.resolution_note = 'resolved', user, now, note
        r.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_note'])


def _decision_audit(action, *, user, entry, ex, gk, rows, note, docs):
    ledger._audit(action, user=user, obj=entry, note=note,
                  old_data={'exception_ids': sorted(r.pk for r in rows), 'status': 'open'},
                  new_data={'exception_id': ex.pk, 'group_key': gk, 'entry_status': entry.status,
                            'note': note, 'source_keys': sorted(d.source_key for d in docs)})


def accept_softech(exception_id, *, user, note='', version=None) -> dict:
    """«اعتماد نسخة سوفتيك»: release the entry, resolve the group's edited_by_user rows and put its
    held docs back to 'new' so the next run rebuilds the group (a draft is replaced; an approved
    entry in an open month is reversed + redrafted; a closed month becomes closed_period_change).
    Returns the window the caller redrafts: {date_from, date_to, source_types, entry_id}."""
    note = (note or '').strip()
    with transaction.atomic():
        ex, gk, rows, docs, entry = _decision(exception_id, version)
        _decision_audit(EDIT_RELEASED, user=user, entry=entry, ex=ex, gk=gk, rows=rows,
                        note=note, docs=docs)
        _close(rows, user, note or ACCEPT_NOTE)
        GLSourceDoc.objects.filter(pk__in=[d.pk for d in docs if d.status == 'exception']).update(
            status='new')
        span = [d.doc_date for d in docs] + list(
            GLSourceDoc.objects.filter(group_key=gk).values_list('doc_date', flat=True))
        types = {d.source_type for d in docs} | set(
            GLSourceDoc.objects.filter(group_key=gk).values_list('source_type', flat=True))
    return {'date_from': min(span, default=entry.entry_date), 'date_to': max(span, default=entry.entry_date),
            'source_types': sorted(types or {entry.source_type}), 'entry_id': entry.pk}


def keep_edit(exception_id, *, user, note='', version=None) -> SourceException:
    """«إبقاء تعديلي»: resolve the group's edited_by_user rows and link its held docs back to the
    live entry as 'drafted' (group_key unchanged), so the engine does nothing until SOFTECH changes
    the group again - which asks again. A vanished doc is unlinked so it never re-raises.
    Refused while the engine runs (it could be rebuilding this group) and whenever keeping would
    leave a doc's amount in two entries (moved group, skip rule, still linked to another entry)."""
    note = (note or '').strip()
    if _engine_running():
        raise DecisionError('busy', 'الترحيل يعمل الآن — انتظر حتى ينتهي ثم أعد المحاولة')
    with transaction.atomic():
        ex, gk, rows, docs, entry = _decision(exception_id, version)
        if entry.status not in LIVE:
            raise DecisionError('entry_gone', 'القيد لم يعد قائماً — أعد الترحيل')
        present = [d for d in docs if d.status != 'vanished']
        if any(not d.group_key for d in present):
            raise DecisionError('skipped', 'مستند صارت له قاعدة تخطٍّ (لا يُرحّل) — '
                                           'لا يمكن إبقاء التعديل؛ اعتمد نسخة سوفتيك')
        if any(d.group_key != gk for d in present):   # its amount now belongs to another group
            raise DecisionError('moved', 'مستند انتقل إلى مجموعة أخرى (تاريخ أو قاعدة مختلفة) — '
                                         'لا يمكن إبقاء التعديل؛ اعتمد نسخة سوفتيك')
        others = {d.entry_id for d in present if d.entry_id and d.entry_id != entry.pk}
        if others and LedgerEntry.objects.filter(pk__in=others, status__in=LIVE).exists():
            raise DecisionError('moved', 'مستند ما زال داخل قيد آخر (انتقل من مجموعة أخرى) — '
                                         'لا يمكن إبقاء التعديل؛ اعتمد نسخة سوفتيك')
        _decision_audit(EDIT_KEPT, user=user, entry=entry, ex=ex, gk=gk, rows=rows, note=note, docs=docs)
        _close(rows, user, note or KEEP_NOTE)
        GLSourceDoc.objects.filter(pk__in=[d.pk for d in docs if d.status == 'vanished']).update(
            entry=None, group_key='')
        GLSourceDoc.objects.filter(pk__in=[d.pk for d in present]).update(status='drafted', entry=entry)
        ex.refresh_from_db()
    return ex
