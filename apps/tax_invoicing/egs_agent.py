"""The seal PC's agent and the Invoicer's live bulk EGS sheet (doc 36, batch S5). Server side.

File jobs (TaxAgentFileJob) ride the signing agent's pull channel (signing-agent/next/), offered only to an agent
that says it is version >= MIN_AGENT_VERSION, and only when no signing job waits:

  request_fetch(actor)            egs_fetch: the agent uploads a copy of the live sheet; record_result stores it
                                  under TAX_EGS_SHEET_DIR/fetched/ (newest 10 kept) and compares its coded
                                  itemcodes with the versions we hold.
  request_write(actor, override)  egs_write of the latest version. Mode 'write' only with the writer flag
                                  TAX_EGS_SHEET_AGENT_WRITE_ENABLED, else 'preview' (the agent writes nothing).
                                  No write when the live file already is the latest version (returns None); a
                                  'held' record instead of a job when the last fetch showed hand edits, unless a
                                  person overrides («اكتب فوقها», audited).
  import_fetched(actor, job)      a fetched copy becomes the next version (source 'fetch') — «استورد التعديلات».
  nightly()                       the 03:00 scheduler job: one fetch, then (switch on) a write on its result.

Hand edits = the live file's coded itemcodes match no version we hold (by hash first, else by coded set). Every
request and outcome is audited (entity 'egs_sheet_agent'). Folders on the seal PC are the agent's own config: no
path is ever sent to it or taken from it."""
import datetime as dt
import hashlib
import io
import json
import logging
import zipfile

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from config.writers import writer_allowed

from . import egs_sheet
from .models import TaxAgentFileJob, TaxEgsSheetVersion
from .services import audit

log = logging.getLogger('elrezeiky.tax_invoicing')

WRITE_FLAG = 'TAX_EGS_SHEET_AGENT_WRITE_ENABLED'
MIN_AGENT_VERSION = 2
MAX_UPLOAD = 20 * 1024 * 1024
MAX_RESULT_CHARS = 64 * 1024
KEEP_FETCHED = 10
CLAIMED_STALE = dt.timedelta(minutes=30)
PENDING_STALE = dt.timedelta(hours=24)
SEEN_KEY = 'tax_signing_agent_seen'
SEEN_EVERY = 60          # seconds between two "last seen" writes from one process
MATCH_VERSIONS = 50      # versions compared by coded set (the hash compares all)
ENTITY = 'egs_sheet_agent'
_LOCK = 'tax_egs_agent_jobs'

NO_FETCH = 'لا توجد قراءة للملف الحالي على جهاز الختم — اقرأ الملف الحالي أولاً'
NOT_FETCH = 'ليست قراءة منتهية للملف الحالي'
FETCHED_GONE = 'نسخة الملف المقروءة لم تعد محفوظة (تُحفظ آخر 10 قراءات فقط) — اقرأ الملف الحالي من جديد'
FETCHED_CHANGED = 'نسخة الملف المقروءة تغيّرت على السيرفر — اقرأ الملف الحالي من جديد'
ALREADY_LATEST = 'الملف الحالي هو نفس آخر نسخة — لا شيء يُستورد'
OVERRIDE_NEEDS_PERSON = 'الكتابة فوق التعديلات اليدوية تحتاج شخصاً يطلبها'
VERSION_FILE_CHANGED = 'ملف النسخة على السيرفر لا يطابق بصمتها — لا يُكتب'
NO_STALE_CLAIM = 'لم يرد جهاز الختم خلال 30 دقيقة'
NO_STALE_PENDING = 'لم يستلم جهاز الختم المهمة خلال 24 ساعة (هل برنامجه محدّث؟)'
UPLOAD_MISSING = 'لم يُرفع الملف'
UPLOAD_TOO_BIG = 'الملف المرفوع أكبر من 20 ميجابايت'
UPLOAD_NOT_XLSX = 'الملف المرفوع ليس ملف Excel (xlsx)'
UPLOAD_UNPACKS_TOO_BIG = 'الملف المرفوع يتمدد لأكثر من 200 ميجابايت — مرفوض'
MAX_UNPACKED = 200 * 1024 * 1024
SWITCH_OFF_AT_SERVE = 'مفتاح الكتابة على جهاز الختم أُغلق بعد استلام المهمة — لم يُرسل الملف'
FETCH_NOT_CURRENT = 'هذه ليست آخر قراءة للملف الحالي (أو كُتبت نسخة بعدها) — اقرأ الملف الحالي من جديد'
WRITE_OPEN = 'توجد مهمة كتابة مفتوحة لجهاز الختم — انتظر نتيجتها ثم اقرأ الملف الحالي من جديد'
WRITE_UNCONFIRMED = ('أبلغ جهاز الختم أن الكتابة تمّت دون تأكيد أن الملف الحالي صار هذه النسخة — اعتُبرت فاشلة؛ '
                     'اقرأ الملف الحالي للتحقق')
IMPORT_REMOVES = 'الملف الحالي ينقصه أصناف مكوّدة في آخر نسخة — الاستيراد يحذف ترميزها؛ أكّد الحذف صراحة'


class EgsAgentError(Exception):
    """A request that cannot be made; the message is Arabic, for the screen."""


def _lock():
    """Serialises job creation (one open job of each kind) for the rest of the transaction."""
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', [_LOCK])


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _fetched_dir():
    return egs_sheet._dir() / 'fetched'


# ── The agent's version handshake and "last seen" ───────────────────────────────────────────────

def agent_version(headers):
    """The X-Tax-Agent-Version header as an int; 0 when missing or not a number (an old agent)."""
    try:
        return int(str(headers.get('X-Tax-Agent-Version', '') or '').strip())
    except ValueError:
        return 0


def record_seen(version):
    """Stores when the agent last polled and its version, at most once a minute per process."""
    from apps.config.models import SystemSetting
    throttle = f'{SEEN_KEY}:{version}'
    if not cache.add(throttle, 1, SEEN_EVERY):
        return
    value = json.dumps({'at': timezone.now().isoformat(), 'version': version})
    SystemSetting.objects.update_or_create(key=SEEN_KEY, defaults={
        'label': 'برنامج جهاز الختم — آخر اتصال', 'value': value, 'value_type': 'json',
        'description': 'آخر مرة سأل فيها برنامج جهاز الختم عن مهمة، ورقم إصداره (يكتبها النظام)'})


def agent_seen():
    """{'at', 'version'} of the agent's last poll, or {}."""
    from apps.config.models import SystemSetting
    value = SystemSetting.get(SEEN_KEY)
    return value if isinstance(value, dict) else {}


# ── Requests ────────────────────────────────────────────────────────────────────────────────────

def expire_stale():
    """A claimed job with no answer for 30 minutes, or a pending one nobody collected in 24 hours, fails (the agent
    died, or the seal PC still runs an old agent), so the next request makes a fresh job."""
    now = timezone.now()
    n = 0
    for status, limit, field, why in ((TaxAgentFileJob.CLAIMED, CLAIMED_STALE, 'claimed_at', NO_STALE_CLAIM),
                                      (TaxAgentFileJob.PENDING, PENDING_STALE, 'created_at', NO_STALE_PENDING)):
        for job in TaxAgentFileJob.objects.filter(status=status, **{f'{field}__lt': now - limit}):
            updated = TaxAgentFileJob.objects.filter(pk=job.pk, status=status).update(
                status=TaxAgentFileJob.FAILED, error=why, finished_at=now)
            if updated:
                n += 1
                audit('egs_sheet_failed', entity=ENTITY, entity_id=job.pk, reason=why,
                      after={'kind': job.kind, 'mode': job.mode, 'was': status})
    return n


def _open(kind):
    return TaxAgentFileJob.objects.filter(kind=kind, status__in=TaxAgentFileJob.OPEN).order_by('id').first()


def request_fetch(actor=None, *, then_write=False):
    """An egs_fetch job (or the open one). `then_write`: ask for a write when its result arrives (nightly)."""
    with transaction.atomic():
        _lock()
        expire_stale()
        job = _open(TaxAgentFileJob.KIND_FETCH)
        if job is not None:
            if then_write and not job.then_write:
                job.then_write = True
                job.save(update_fields=['then_write'])
            return job
        job = TaxAgentFileJob.objects.create(kind=TaxAgentFileJob.KIND_FETCH, requested_by=actor,
                                             then_write=then_write)
        audit('egs_sheet_fetch_requested', actor=actor, entity=ENTITY, entity_id=job.pk,
              after={'then_write': then_write})
    return job


def last_fetch():
    return (TaxAgentFileJob.objects.filter(kind=TaxAgentFileJob.KIND_FETCH, status=TaxAgentFileJob.DONE)
            .order_by('-finished_at', '-id').first())


def _last_written():
    return (TaxAgentFileJob.objects.filter(kind=TaxAgentFileJob.KIND_WRITE, mode=TaxAgentFileJob.MODE_WRITE,
                                           status=TaxAgentFileJob.DONE)
            .select_related('version').order_by('-finished_at', '-id').first())


def live_state():
    """What the live file is, from the newer of the last fetch and the last real write: {'source', 'job',
    'sha256', 'coded_itemcodes', 'hand_edits'}; None when neither exists."""
    fetch, written = last_fetch(), _last_written()
    if written is not None and (fetch is None or written.finished_at > fetch.finished_at):
        return {'source': 'write', 'job': written, 'sha256': written.version.sha256,
                'coded_itemcodes': list(written.version.coded_itemcodes), 'hand_edits': False}
    if fetch is None:
        return None
    r = fetch.result or {}
    sha, codes = (r.get('live') or {}).get('sha256', ''), list(r.get('coded_itemcodes') or [])
    # now, not as at the fetch: a version imported from this very copy since then makes it ours
    return {'source': 'fetch', 'job': fetch, 'sha256': sha, 'coded_itemcodes': codes,
            'hand_edits': egs_sheet.latest() is not None and _match(sha, codes) is None}


def _is_version(live, version):
    return live['sha256'] == version.sha256 or set(live['coded_itemcodes']) == set(version.coded_itemcodes)


def request_write(actor=None, *, override=False, note=''):
    """An egs_write job for the latest version, or: the open one; None when the live file already is the latest
    version; a 'held' record when the last fetch showed hand edits and nobody overrides. EgsAgentError when there
    is no version, no fetch yet, or the version's file is gone or changed."""
    if override and actor is None:
        raise EgsAgentError(OVERRIDE_NEEDS_PERSON)
    with transaction.atomic():
        _lock()
        expire_stale()
        version = egs_sheet.latest()
        if version is None:
            raise EgsAgentError(egs_sheet.NO_HELD)
        if not version.whole_workbook:
            raise EgsAgentError(egs_sheet.NOT_WHOLE)
        job = _open(TaxAgentFileJob.KIND_WRITE)
        if job is not None:
            return job
        live = live_state()
        if live is None:
            raise EgsAgentError(NO_FETCH)
        if _is_version(live, version) and not override:
            return None
        base = {'kind': TaxAgentFileJob.KIND_WRITE, 'version': version, 'requested_by': actor,
                'live_sha256': live['sha256'], 'override': override}
        if live['hand_edits'] and not override:
            held = (TaxAgentFileJob.objects.filter(kind=TaxAgentFileJob.KIND_WRITE, status=TaxAgentFileJob.HELD,
                                                   version=version).order_by('-id').first())
            if held is not None and (held.result or {}).get('fetch_job') == live['job'].pk:
                return held     # the same hold again (nightly): no new row
            r = live['job'].result or {}
            job = TaxAgentFileJob.objects.create(
                **base, status=TaxAgentFileJob.HELD, finished_at=timezone.now(),
                result={'fetch_job': live['job'].pk, 'added': r.get('added_vs_latest', []),
                        'removed': r.get('removed_vs_latest', [])})
            audit('egs_sheet_write_held', actor=actor, entity=ENTITY, entity_id=job.pk, reason=note,
                  after={'version': version.number, 'fetch_job': live['job'].pk,
                         'added': len(job.result['added']), 'removed': len(job.result['removed'])})
            return job
        try:
            data = egs_sheet.open_version(version)
        except egs_sheet.SheetError as exc:
            raise EgsAgentError(str(exc)) from exc
        sha = _sha(data)
        if sha != version.sha256:
            raise EgsAgentError(VERSION_FILE_CHANGED)
        mode = TaxAgentFileJob.MODE_WRITE if writer_allowed(WRITE_FLAG) else TaxAgentFileJob.MODE_PREVIEW
        job = TaxAgentFileJob.objects.create(**base, mode=mode, sha256=sha, result={'size': len(data)})
        audit('egs_sheet_write_override' if override else 'egs_sheet_write_requested', actor=actor, entity=ENTITY,
              entity_id=job.pk, reason=note,
              after={'version': version.number, 'mode': mode, 'sha256': sha, 'live_sha256': live['sha256'],
                     'hand_edits': live['hand_edits']})
    return job


def nightly():
    """03:00: one fetch; with the write switch on, its result asks for a write (request_write decides: nothing
    when the live file is the latest version, held on hand edits)."""
    if egs_sheet.latest() is None:
        return None
    return request_fetch(None, then_write=writer_allowed(WRITE_FLAG))


# ── The agent's side of a job ───────────────────────────────────────────────────────────────────

def claim_next():
    """Claims the oldest pending file job and returns it, or None. A write job created while the switch was on is
    claimed as a preview when the switch has since been turned off."""
    expire_stale()
    with transaction.atomic():
        job = (TaxAgentFileJob.objects.select_for_update(skip_locked=True)
               .filter(status=TaxAgentFileJob.PENDING).order_by('created_at', 'id').first())
        if job is None:
            return None
        job.status, job.claimed_at = TaxAgentFileJob.CLAIMED, timezone.now()
        fields = ['status', 'claimed_at']
        if job.mode == TaxAgentFileJob.MODE_WRITE and not writer_allowed(WRITE_FLAG):
            job.mode = TaxAgentFileJob.MODE_PREVIEW
            job.result = {**(job.result or {}), 'switch_off_at_claim': True}
            fields += ['mode', 'result']
            audit('egs_sheet_switch_off_at_claim', entity=ENTITY, entity_id=job.pk,
                  before={'mode': TaxAgentFileJob.MODE_WRITE}, after={'mode': TaxAgentFileJob.MODE_PREVIEW})
        job.save(update_fields=fields)
    return job


def payload(job):
    """What the agent receives: never a path on its machine, only our URLs and the hashes it must check."""
    base = f'/api/tax-invoicing/signing-agent/files/{job.pk}/'
    out = {'id': job.pk, 'kind': job.kind, 'mode': job.mode, 'result_url': base + 'result/'}
    if job.kind == TaxAgentFileJob.KIND_WRITE:
        out.update({'sha256': job.sha256, 'size': (job.result or {}).get('size'), 'live_sha256': job.live_sha256,
                    'version': job.version.number, 'download_url': base + 'download/'})
    return out


def download_bytes(job):
    """Exactly the stored version file. EgsAgentError (and the job fails) when it is gone or its hash changed, or
    when a write-mode job is served after the write switch was turned off."""
    if job.mode == TaxAgentFileJob.MODE_WRITE and not writer_allowed(WRITE_FLAG):
        audit('egs_sheet_switch_off_at_serve', entity=ENTITY, entity_id=job.pk,
              after={'version': job.version.number, 'mode': job.mode})
        _fail(job, SWITCH_OFF_AT_SERVE)
        raise EgsAgentError(SWITCH_OFF_AT_SERVE)
    if not job.version.whole_workbook:
        _fail(job, egs_sheet.NOT_WHOLE)
        raise EgsAgentError(egs_sheet.NOT_WHOLE)
    try:
        data = egs_sheet.open_version(job.version)
    except egs_sheet.SheetError as exc:
        _fail(job, str(exc))
        raise EgsAgentError(str(exc)) from exc
    if _sha(data) != job.sha256:
        _fail(job, VERSION_FILE_CHANGED)
        raise EgsAgentError(VERSION_FILE_CHANGED)
    return data


def _fail(job, why):
    with transaction.atomic():
        if TaxAgentFileJob.objects.filter(pk=job.pk, status=TaxAgentFileJob.CLAIMED).update(
                status=TaxAgentFileJob.FAILED, error=why[:1000], finished_at=timezone.now()):
            audit('egs_sheet_failed', entity=ENTITY, entity_id=job.pk, reason=why[:300],
                  after={'kind': job.kind, 'mode': job.mode})


def _agent_result(value):
    """The agent's JSON report as a dict, size-capped."""
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except ValueError:
            value = {'unparsed': value[:2000]}
    if not isinstance(value, dict):
        value = {'value': value}
    if len(json.dumps(value, default=str)) > MAX_RESULT_CHARS:
        return {'truncated': True}
    return value


def validate_upload(data):
    """(counts) of an uploaded live sheet; EgsAgentError when it is not an xlsx with the DataEntry header."""
    if len(data) > MAX_UPLOAD:
        raise EgsAgentError(UPLOAD_TOO_BIG)
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise EgsAgentError(UPLOAD_NOT_XLSX)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            unpacked = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile as exc:
        raise EgsAgentError(UPLOAD_NOT_XLSX) from exc
    if unpacked > MAX_UNPACKED:      # a zip bomb never reaches openpyxl
        raise EgsAgentError(UPLOAD_UNPACKS_TOO_BIG)
    try:
        return egs_sheet.read_counts(data)
    except egs_sheet.SheetError as exc:
        raise EgsAgentError(str(exc)) from exc


def _match(sha, codes):
    """The version a live file is: the same hash (newest), else the same coded itemcodes among the newest
    MATCH_VERSIONS; None = hand edits."""
    match = TaxEgsSheetVersion.objects.filter(sha256=sha).order_by('-number').first() if sha else None
    if match is None:
        codes = set(codes)
        for v in TaxEgsSheetVersion.objects.order_by('-number').only('number', 'coded_itemcodes')[:MATCH_VERSIONS]:
            if set(v.coded_itemcodes) == codes:
                return v
    return match


def compare(sha, counts):
    """The fetched file against our versions: which version it is (hash first, else the same coded set, newest),
    hand edits (it is none of them), and its coded itemcodes added / removed against the latest version."""
    codes = set(counts['coded_itemcodes'])
    latest = egs_sheet.latest()
    match = _match(sha, codes)
    held = set(latest.coded_itemcodes) if latest else set()
    key = egs_sheet._code_key
    return {'latest': latest.number if latest else None, 'matches_version': match.number if match else None,
            'hand_edits': latest is not None and match is None,
            'added_vs_latest': sorted(codes - held, key=key), 'removed_vs_latest': sorted(held - codes, key=key)}


def _store_fetched(job, data, sha):
    folder = _fetched_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = f'fetched_{job.pk:06d}_{sha[:12]}.xlsx'
    (folder / name).write_bytes(data)
    return name


def _prune_fetched():
    keep = set(TaxAgentFileJob.objects.exclude(fetched_file='').order_by('-id')
               .values_list('fetched_file', flat=True)[:KEEP_FETCHED])
    folder = _fetched_dir()
    if not folder.is_dir():
        return
    for path in folder.glob('fetched_*.xlsx'):
        if path.name not in keep:
            path.unlink(missing_ok=True)


def _then_write(job_pk):
    try:
        request_write(None, note=f'nightly after fetch #{job_pk}')
    except EgsAgentError as exc:
        log.info('egs sheet nightly write not requested: %s', exc)
    except Exception:
        log.exception('egs sheet nightly write request failed')


def record_result(job, status, result=None, error='', upload=None):
    """The agent's answer for a claimed job. status: done | failed | busy. A done egs_fetch needs `upload` (the
    live sheet's bytes): it is checked (size, xlsx, DataEntry header), stored and compared; a bad upload fails the
    job and raises EgsAgentError. Audited: egs_sheet_fetched / _written / _previewed / _busy / _failed."""
    if status not in (TaxAgentFileJob.DONE, TaxAgentFileJob.FAILED, TaxAgentFileJob.BUSY):
        raise EgsAgentError('حالة غير معروفة')
    report = _agent_result(result or {})
    stored = None
    unconfirmed = (job.kind == TaxAgentFileJob.KIND_WRITE and job.mode == TaxAgentFileJob.MODE_WRITE
                   and status == TaxAgentFileJob.DONE
                   and (report.get('written') is not True or report.get('live_sha256_after') != job.sha256))
    if unconfirmed:     # a real write counts only when the agent read the live file back as this version
        status, error = TaxAgentFileJob.FAILED, WRITE_UNCONFIRMED
    if job.kind == TaxAgentFileJob.KIND_FETCH and status == TaxAgentFileJob.DONE:
        if upload is None:
            _fail(job, UPLOAD_MISSING)
            raise EgsAgentError(UPLOAD_MISSING)
        try:
            counts = validate_upload(upload)
        except EgsAgentError as exc:
            _fail(job, str(exc))
            raise
        sha = _sha(upload)
        stored = _store_fetched(job, upload, sha)
    try:
        with transaction.atomic():
            locked = TaxAgentFileJob.objects.select_for_update().filter(pk=job.pk,
                                                                       status=TaxAgentFileJob.CLAIMED).first()
            if locked is None:
                raise EgsAgentError('لا توجد مهمة مستلمة بهذا الرقم')
            job = locked
            job.status, job.finished_at = status, timezone.now()
            job.error = '' if status == TaxAgentFileJob.DONE else str(error or status)[:1000]
            if stored:
                job.fetched_file = stored
                job.result = {'agent': report, 'live': {'sha256': sha, 'size': len(upload),
                                                        'coded_rows': counts['coded_rows'],
                                                        'total_rows': counts['total_rows']},
                              'coded_itemcodes': counts['coded_itemcodes'], **compare(sha, counts)}
            else:
                job.result = {**(job.result or {}), 'agent': report}
            job.save()
            if unconfirmed:
                audit('egs_sheet_write_anomaly', entity=ENTITY, entity_id=job.pk, reason=WRITE_UNCONFIRMED[:300],
                      after={'version': job.version.number, 'sha256': job.sha256,
                             'written': report.get('written'), 'live_sha256_after': report.get('live_sha256_after')})
            _audit_outcome(job)
            if stored:
                transaction.on_commit(_prune_fetched)
                if job.then_write:
                    transaction.on_commit(lambda pk=job.pk: _then_write(pk))
    except Exception:
        if stored:
            (_fetched_dir() / stored).unlink(missing_ok=True)
        raise
    return job


def _audit_outcome(job):
    r = job.result or {}
    if job.status == TaxAgentFileJob.DONE and job.kind == TaxAgentFileJob.KIND_FETCH:
        action = 'egs_sheet_fetched'
        after = {**r.get('live', {}), 'matches_version': r.get('matches_version'), 'hand_edits': r.get('hand_edits'),
                 'added': len(r.get('added_vs_latest', [])), 'removed': len(r.get('removed_vs_latest', []))}
    elif job.status == TaxAgentFileJob.DONE:
        action = 'egs_sheet_written' if job.mode == TaxAgentFileJob.MODE_WRITE else 'egs_sheet_previewed'
        after = {'version': job.version.number, 'sha256': job.sha256, 'agent': r.get('agent')}
    else:
        action = 'egs_sheet_busy' if job.status == TaxAgentFileJob.BUSY else 'egs_sheet_failed'
        after = {'kind': job.kind, 'mode': job.mode, 'agent': r.get('agent')}
    audit(action, entity=ENTITY, entity_id=job.pk, reason=job.error[:300], after=after)


# ── «استورد التعديلات» ──────────────────────────────────────────────────────────────────────────

def import_fetched(actor, job, *, allow_removals=False):
    """The fetched copy of a done egs_fetch becomes the next version (source 'fetch'), so the hand edits are ours
    and a later build starts from them. Only the current live state may be imported: the newest fetch, with no real
    write after it (an older copy would undo coded items). A copy that lacks coded items of the latest version is
    refused unless `allow_removals` (audited with the list). EgsAgentError when the copy is not current, gone,
    changed, invalid, or already the latest version. Audited (egs_sheet_imported)."""
    if job.kind != TaxAgentFileJob.KIND_FETCH or job.status != TaxAgentFileJob.DONE or not job.fetched_file:
        raise EgsAgentError(NOT_FETCH)
    newest, live = last_fetch(), live_state()
    if newest is None or newest.pk != job.pk or live is None or live['job'].pk != job.pk:
        raise EgsAgentError(FETCH_NOT_CURRENT)
    path = _fetched_dir() / job.fetched_file
    if not path.is_file():
        raise EgsAgentError(FETCHED_GONE)
    data = path.read_bytes()
    sha = _sha(data)
    if sha != (job.result or {}).get('live', {}).get('sha256'):
        raise EgsAgentError(FETCHED_CHANGED)
    latest = egs_sheet.latest()
    if latest is not None and latest.sha256 == sha:
        raise EgsAgentError(ALREADY_LATEST)
    counts = validate_upload(data)
    removed = sorted(set(latest.coded_itemcodes if latest else ()) - set(counts['coded_itemcodes']),
                     key=egs_sheet._code_key)
    if removed and not allow_removals:
        raise EgsAgentError(IMPORT_REMOVES)
    version = None
    try:
        with transaction.atomic():      # no version without its audit event
            _lock()                     # a write in flight would make this copy stale under us
            expire_stale()
            if _open(TaxAgentFileJob.KIND_WRITE) is not None:
                raise EgsAgentError(WRITE_OPEN)
            version = egs_sheet.store(data, source=TaxEgsSheetVersion.SOURCE_FETCH, built_by=actor,
                                      note=f'الملف الحالي من جهاز الختم (قراءة #{job.pk})', whole_workbook=True,
                                      **counts)
            audit('egs_sheet_imported', actor=actor, entity='egs_sheet', entity_id=version.number,
                  after={'number': version.number, 'fetch_job': job.pk, 'sha256': sha,
                         'from': latest.number if latest else None, 'coded_rows': version.coded_rows,
                         'total_rows': version.total_rows, 'allow_removals': allow_removals,
                         'removed': removed})
    except Exception:
        if version is not None:
            egs_sheet.discard_file(version)
        raise
    return version
