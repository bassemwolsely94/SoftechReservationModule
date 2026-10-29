"""
apps/callcenter/whisper.py

Local Whisper (faster-whisper, CPU, int8) transcription — runs nightly in a
bounded window (default 02:00–06:00) in its own low-priority process, so the
web server and sync jobs aren't slowed. Gemini keeps transcribing right after
each call; both results live side by side in CallTranscript.

"Learning": Whisper itself isn't retrained here. Each night the runner builds
a vocabulary hint (initial_prompt) from words humans keep correcting, plus
WHISPER_EXTRA_TERMS from settings. export_whisper_corrections dumps
audio+corrected-text pairs for an occasional fine-tune.

Settings:
  WHISPER_ENABLED      bool, default False — enqueue + nightly run
  WHISPER_MIN_SECONDS  skip calls shorter than this, default 20
  WHISPER_EXTRA_TERMS  list[str] — always-included vocabulary (drug names…)
  WHISPER_MODEL_DIR    optional local model cache directory
"""
import logging
import os
import re
import tempfile
import time
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.whisper')

ENGINE = 'whisper'
PROMPT_MAX_CHARS = 600          # Whisper uses ~224 tokens of prompt
REALTIME_FACTOR_GUESS = 0.6     # CPU medium int8: ~0.6s processing per audio second


def enabled() -> bool:
    return bool(getattr(settings, 'WHISPER_ENABLED', False))


# ── Enqueue ───────────────────────────────────────────────────────────────────

def enqueue(call_log) -> bool:
    """Queue an answered, recorded, long-enough call. Idempotent."""
    from apps.callcenter.models import CallTranscript
    from apps.callcenter.serializers import call_has_recording

    if not enabled() or call_log.status in ('no_answer', 'busy'):
        return False
    if call_log.duration_seconds < getattr(settings, 'WHISPER_MIN_SECONDS', 20):
        return False
    # PBX calls: the recording is looked up in Issabel's CDR when the job runs
    if not call_has_recording(call_log) and getattr(call_log, 'pbx_session', None) is None:
        return False
    _, created = CallTranscript.objects.get_or_create(call_log=call_log, engine=ENGINE)
    return created


# ── Learning: vocabulary hints from corrections ──────────────────────────────

_WORD = re.compile(r'[؀-ۿA-Za-z0-9]{3,}')


def build_vocabulary_prompt(limit_chars: int = PROMPT_MAX_CHARS) -> str:
    """Words humans added when correcting transcripts, most frequent first."""
    from apps.callcenter.models import CallTranscript

    counts = Counter()
    for orig, fixed in (CallTranscript.objects.exclude(corrected_text='')
                        .order_by('-corrected_at').values_list('text', 'corrected_text')[:500]):
        before = set(_WORD.findall(orig or ''))
        counts.update(w for w in _WORD.findall(fixed) if w not in before)

    terms = list(getattr(settings, 'WHISPER_EXTRA_TERMS', []))
    terms += [w for w, _ in counts.most_common(200) if w not in terms]
    prompt, out = 'مكالمة صيدلية. ', []
    for t in terms:
        if len(prompt) + len(' '.join(out + [t])) > limit_chars:
            break
        out.append(t)
    return prompt + '، '.join(out) if out else prompt


# ── Engine ────────────────────────────────────────────────────────────────────

_model_cache = {}


def _load_model(size: str, threads: int):
    key = (size, threads)
    if key not in _model_cache:
        from faster_whisper import WhisperModel   # imported lazily: optional dependency
        _model_cache[key] = WhisperModel(
            size, device='cpu', compute_type='int8', cpu_threads=threads,
            download_root=getattr(settings, 'WHISPER_MODEL_DIR', None) or None)
    return _model_cache[key]


def transcribe_audio(audio: bytes, mime: str, size: str, threads: int, prompt: str):
    """→ (text, audio_seconds). Writes to a temp file: ffmpeg decodes from disk."""
    suffix = '.' + (mime.split('/')[-1] if '/' in mime else 'wav')
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(audio)
        model = _load_model(size, threads)
        segments, info = model.transcribe(
            path, language='ar', initial_prompt=prompt, vad_filter=True, beam_size=5)
        text = ' '.join(s.text.strip() for s in segments).strip()
        return text, float(getattr(info, 'duration', 0) or 0)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def default_threads() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


# ── Runner ────────────────────────────────────────────────────────────────────

def _window_end(control, now):
    """Datetime the current window closes (handles windows crossing midnight)."""
    local = timezone.localtime(now)
    end = local.replace(hour=control.window_end.hour, minute=control.window_end.minute,
                        second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end


def in_window(control, now=None) -> bool:
    local = timezone.localtime(now or timezone.now()).time()
    start, end = control.window_start, control.window_end
    return (start <= local < end) if start < end else (local >= start or local < end)


def run_queue(ignore_window: bool = False, max_items: int | None = None) -> dict:
    """
    Process pending Whisper jobs oldest-first until the window closes, the queue
    is empty, or someone pauses/stops it. Safe to re-run: 'running' rows left by
    a crash are returned to the queue first.
    """
    from apps.callcenter.models import CallTranscript, WhisperQueueControl
    from apps.omni.transcription import _resolve_call_audio

    control = WhisperQueueControl.get()
    now = timezone.now()
    if not ignore_window and not in_window(control, now):
        return {'processed': 0, 'stopped': 'outside_window'}
    if control.paused:
        return {'processed': 0, 'stopped': 'paused'}

    deadline = _window_end(control, now) if not ignore_window else None
    CallTranscript.objects.filter(engine=ENGINE, status='running').update(status='pending')
    WhisperQueueControl.objects.filter(pk=1).update(
        stop_requested=False, run_started_at=now, run_finished_at=None,
        run_processed=0, run_note='يعمل')

    size = control.model_size or 'medium'
    threads = control.cpu_threads or default_threads()
    prompt = build_vocabulary_prompt()
    processed, stopped = 0, 'queue_empty'
    tried = set()   # a failure is retried on a later night, not straight away

    while True:
        control.refresh_from_db()
        if control.paused or control.stop_requested:
            stopped = 'paused' if control.paused else 'stop_requested'
            break
        if max_items is not None and processed >= max_items:
            stopped = 'max_items'
            break

        with transaction.atomic():
            job = (CallTranscript.objects.select_for_update(skip_locked=True)
                   .filter(engine=ENGINE, status='pending').exclude(pk__in=tried)
                   .select_related('call_log').order_by('created_at').first())
            if job is None:
                break
            # Don't start a call that can't finish before the window closes
            if deadline is not None:
                need = timedelta(seconds=(job.call_log.duration_seconds or 60) * REALTIME_FACTOR_GUESS + 30)
                if timezone.now() + need > deadline:
                    stopped = 'window_closed'
                    break
            tried.add(job.pk)
            job.status, job.started_at, job.attempts = 'running', timezone.now(), job.attempts + 1
            job.save(update_fields=['status', 'started_at', 'attempts'])

        t0 = time.monotonic()
        try:
            audio, mime = _resolve_call_audio(job.call_log)
            if audio is None:
                raise FileNotFoundError('لا يوجد ملف تسجيل متاح')
            text, seconds = transcribe_audio(audio, mime, size, threads, prompt)
            job.text, job.audio_seconds = text, seconds
            job.status = 'done' if text else 'skipped'
            job.error = '' if text else 'تسجيل بلا كلام'
            job.model_name = f'faster-whisper-{size}'
        except Exception as exc:
            logger.warning('whisper: call %s failed (attempt %s): %s', job.call_log_id, job.attempts, exc)
            job.error = f'{type(exc).__name__}: {exc}'[:500]
            job.status = 'failed' if job.attempts >= CallTranscript.MAX_ATTEMPTS else 'pending'
        job.processing_seconds = round(time.monotonic() - t0, 1)
        job.finished_at = timezone.now()
        job.save()
        if job.status == 'done':
            processed += 1
            WhisperQueueControl.objects.filter(pk=1).update(run_processed=processed)

    notes = {'queue_empty': 'اكتمل الطابور', 'window_closed': 'انتهت نافذة التشغيل — يُستكمل الليلة القادمة',
             'paused': 'أُوقف مؤقتاً', 'stop_requested': 'أُوقف بطلب', 'max_items': 'اكتمل العدد المطلوب'}
    WhisperQueueControl.objects.filter(pk=1).update(
        run_finished_at=timezone.now(), run_processed=processed,
        stop_requested=False, run_note=notes.get(stopped, stopped))
    logger.info('whisper run: %d done, stopped=%s', processed, stopped)
    return {'processed': processed, 'stopped': stopped}


RUN_STALE_AFTER = timedelta(hours=5)


def run_is_active(control) -> bool:
    return bool(control.run_started_at and control.run_finished_at is None
                and timezone.now() - control.run_started_at < RUN_STALE_AFTER)


def maybe_launch_runner() -> bool:
    """
    Scheduler tick (every 15 min): start the runner as a separate low-priority
    process when inside the window, not paused, not already running, and work
    is queued. A separate process keeps the CPU load out of the web server.
    """
    import subprocess
    import sys
    from apps.callcenter.models import CallTranscript, WhisperQueueControl

    if not enabled():
        return False
    control = WhisperQueueControl.get()
    if control.paused or run_is_active(control) or not in_window(control):
        return False
    if not CallTranscript.objects.filter(engine=ENGINE, status='pending').exists():
        return False

    manage = os.path.join(str(settings.BASE_DIR), 'manage.py')
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = (subprocess.BELOW_NORMAL_PRIORITY_CLASS
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs['preexec_fn'] = lambda: os.nice(10)
    subprocess.Popen([sys.executable, manage, 'run_whisper_queue'], close_fds=True, **kwargs)
    logger.info('whisper: runner launched')
    return True


def queue_stats() -> dict:
    from django.db.models import Avg, Count, Sum
    from apps.callcenter.models import CallTranscript
    qs = CallTranscript.objects.filter(engine=ENGINE)
    by_status = dict(qs.values_list('status').annotate(n=Count('id')))
    pending_audio = (qs.filter(status='pending')
                     .aggregate(s=Sum('call_log__duration_seconds'))['s'] or 0)
    done = qs.filter(status='done', audio_seconds__gt=0)
    speed = done.aggregate(p=Sum('processing_seconds'), a=Sum('audio_seconds'))
    factor = (speed['p'] / speed['a']) if speed['a'] else REALTIME_FACTOR_GUESS
    return {
        'by_status': by_status,
        'pending_audio_minutes': round(pending_audio / 60, 1),
        'estimated_hours': round(pending_audio * factor / 3600, 1),
        'realtime_factor': round(factor, 2),
        'corrections': qs.exclude(corrected_text='').count(),
    }
