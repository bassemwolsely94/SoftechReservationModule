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
        local = recordings.resolve_local_path(session)
        if local:
            mime = mimetypes.guess_type(local)[0] or 'audio/wav'
            with open(local, 'rb') as f:
                return f.read(), mime

        remote = recordings.resolve_remote_url(session)
    else:
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
