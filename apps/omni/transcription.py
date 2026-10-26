"""
apps/omni/transcription.py

Gemini audio transcription for voice channels (doc 15 Phase 2).

Two sources, one pipeline:
  - Call recordings  (callcenter.CallLog → pbx CallSession recording file/URL)
      → CallLog.voice_transcript, then chains the existing Gemini summarizer
        (apps/callcenter/ai.py) for intent/sentiment/urgency.
  - WhatsApp voice notes (whatsapp.WAMessage type=audio with local media)

Both append an 'ai_insight' TimelineEvent with the transcript, so results
surface in the unified inbox automatically via polling.

Uses the same google-genai SDK + GOOGLE_API_KEY as apps/callcenter/ai.py.
Runs in background threads — never blocks a request.
"""
import logging
import mimetypes
import os

from django.utils import timezone

logger = logging.getLogger('elrezeiky.omni')

TRANSCRIBE_PROMPT = (
    'فرّغ هذا التسجيل الصوتي نصياً كما هو (عربي مصري غالباً). '
    'أعد النص فقط بدون أي تعليقات أو مقدمات.'
)


def _gemini_transcribe(audio_bytes: bytes, mime_type: str) -> str:
    """Audio bytes → Arabic transcript text. Raises on API failure."""
    from google import genai
    from google.genai import types

    client = genai.Client()  # GOOGLE_API_KEY from env
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            TRANSCRIBE_PROMPT,
        ],
    )
    return (response.text or '').strip()


def _resolve_call_audio(log) -> tuple[bytes | None, str]:
    """Locate the recording audio for a CallLog: local mount first, then HTTP."""
    session = getattr(log, 'pbx_session', None)

    if session is not None:
        from apps.pbx import recordings
        return recordings.load_session_audio(session)
    remote = log.recording_url

    if remote:
        try:
            import requests
            resp = requests.get(remote, timeout=30)
            resp.raise_for_status()
            mime = resp.headers.get('Content-Type', '') or \
                mimetypes.guess_type(remote)[0] or 'audio/wav'
            return resp.content, mime.split(';')[0]
        except Exception as exc:
            logger.warning('transcription: recording download failed for call %s: %s',
                           log.pk, exc)
    return None, ''


def _emit_transcript_event(conversation, obj, transcript: str, label: str):
    from apps.omni import services
    services.add_event(
        conversation, 'ai_insight',
        obj=obj,
        summary=f'📝 {label}: {transcript[:230]}',
        payload={'kind': 'transcript', 'text': transcript},
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public entry points (run in a background Thread)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def transcribe_call_log(call_pk: int) -> None:
    """Recording → CallLog.voice_transcript → AI summary → timeline insight."""
    from apps.callcenter.models import CallLog

    try:
        log = CallLog.objects.select_related('customer', 'branch').get(pk=call_pk)
    except CallLog.DoesNotExist:
        logger.error('transcription: CallLog %s not found', call_pk)
        return

    audio, mime = _resolve_call_audio(log)
    if audio is None:
        logger.warning('transcription: no audio available for call %s', call_pk)
        return

    try:
        transcript = _gemini_transcribe(audio, mime)
    except Exception as exc:
        logger.error('transcription: Gemini error for call %s: %s', call_pk, exc)
        return
    if not transcript:
        logger.warning('transcription: empty transcript for call %s', call_pk)
        return

    CallLog.objects.filter(pk=call_pk).update(voice_transcript=transcript)
    logger.info('transcription: call %s transcribed (%d chars)', call_pk, len(transcript))
    try:
        from apps.callcenter.models import CallTranscript
        CallTranscript.objects.update_or_create(
            call_log_id=call_pk, engine='gemini',
            defaults={'text': transcript, 'status': 'done', 'model_name': 'gemini-2.0-flash',
                      'finished_at': timezone.now()})
    except Exception:
        logger.exception('transcription: CallTranscript write failed for call %s', call_pk)

    # Chain the existing intent/sentiment/urgency summarizer
    try:
        from apps.callcenter.ai import summarize_call_async
        summarize_call_async(call_pk)
    except Exception as exc:
        logger.warning('transcription: summarize chain failed for call %s: %s', call_pk, exc)

    # Surface in the unified timeline
    try:
        from apps.omni import services
        convo = services.resolve_conversation(
            customer=log.customer, phone=log.phone_number, channel='voice',
        )
        _emit_transcript_event(convo, log, transcript, 'تفريغ المكالمة')
    except Exception:
        logger.exception('transcription: timeline emit failed for call %s', call_pk)


def auto_transcribe_after_hangup(call_pk: int) -> None:
    """
    Hangup hook for PBX-created CallLogs. Gated by settings (off by default — each
    call costs a Gemini request):
      CALLCENTER_AUTO_TRANSCRIBE              bool, default False
      CALLCENTER_AUTO_TRANSCRIBE_MIN_SECONDS  skip short calls, default 20
      CALLCENTER_AUTO_TRANSCRIBE_DELAY        seconds to wait for Asterisk to
                                              finish writing the file, default 15
    """
    import time
    from django.conf import settings
    from apps.callcenter.models import CallLog

    if not getattr(settings, 'CALLCENTER_AUTO_TRANSCRIBE', False):
        return
    log = CallLog.objects.filter(pk=call_pk).only(
        'status', 'duration_seconds', 'voice_transcript').first()
    # Merged logs may carry the agent's status (e.g. 'callback') for an answered call
    if log is None or log.status in ('no_answer', 'busy') or log.voice_transcript:
        return
    if log.duration_seconds < getattr(settings, 'CALLCENTER_AUTO_TRANSCRIBE_MIN_SECONDS', 20):
        return

    time.sleep(getattr(settings, 'CALLCENTER_AUTO_TRANSCRIBE_DELAY', 15))
    # Re-check: a manual transcribe may have run while we waited
    if CallLog.objects.filter(pk=call_pk).exclude(voice_transcript='').exists():
        return
    transcribe_call_log(call_pk)


def transcribe_wa_voice(message_pk: int) -> None:
    """WhatsApp voice note → transcript → timeline insight."""
    from apps.whatsapp.models import WAMessage

    try:
        msg = WAMessage.objects.select_related('media', 'conversation').get(pk=message_pk)
    except WAMessage.DoesNotExist:
        logger.error('transcription: WAMessage %s not found', message_pk)
        return

    media = msg.media
    if media is None or not media.local_file:
        logger.warning('transcription: WAMessage %s has no local audio file', message_pk)
        return

    try:
        with media.local_file.open('rb') as f:
            audio = f.read()
        mime = media.mime_type.split(';')[0] if media.mime_type else (
            mimetypes.guess_type(media.local_file.name)[0] or 'audio/ogg')
        transcript = _gemini_transcribe(audio, mime)
    except Exception as exc:
        logger.error('transcription: Gemini error for WAMessage %s: %s', message_pk, exc)
        return
    if not transcript:
        return

    try:
        from apps.omni import services
        wa_conv = msg.conversation
        convo = wa_conv.omni_conversation or services.resolve_conversation(
            customer=wa_conv.customer, phone=wa_conv.wa_id, channel='whatsapp',
        )
        _emit_transcript_event(convo, msg, transcript, 'تفريغ رسالة صوتية')
        logger.info('transcription: WAMessage %s transcribed (%d chars)',
                    message_pk, len(transcript))
    except Exception:
        logger.exception('transcription: timeline emit failed for WAMessage %s', message_pk)
