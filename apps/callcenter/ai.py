"""
apps/callcenter/ai.py

Gemini AI call summarization.
Called asynchronously from CallLogViewSet.summarize action.

Extracts from call notes/transcript:
  - summary     — concise Arabic summary
  - intent      — e.g. purchase/complaint/inquiry/refill/delivery
  - sentiment   — positive/neutral/negative
  - urgency     — 1-5
  - next_action — suggested next action for the agent

SOFTECH is SELECT ONLY — this module only writes to PostgreSQL.
"""
import json
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """أنت مساعد ذكي لمركز اتصالات صيدلية.
تحليل سجل المكالمة التالي وأعطني JSON بالحقول التالية فقط:
{
  "summary":     "ملخص عربي موجز (2-3 جمل)",
  "intent":      "purchase|complaint|inquiry|refill|delivery|other",
  "sentiment":   "positive|neutral|negative",
  "urgency":     1,
  "next_action": "الإجراء المقترح للموظف"
}
- urgency: رقم من 1 (منخفض) إلى 5 (عاجل جداً)
- أعد JSON فقط بدون أي نص إضافي
"""


def _build_content(call) -> str:
    parts = []
    if call.caller_name:
        parts.append(f"العميل: {call.caller_name}")
    if call.purpose:
        parts.append(f"الغرض: {call.get_purpose_display()}")
    if call.notes:
        parts.append(f"ملاحظات الموظف:\n{call.notes}")
    if call.voice_transcript:
        parts.append(f"نص المكالمة:\n{call.voice_transcript}")
    return "\n\n".join(parts)


def summarize_call_async(call_pk: int) -> None:
    """
    Runs in a background thread.
    Fetches the CallLog, calls Gemini, writes AI fields back to PostgreSQL.
    """
    try:
        from .models import CallLog
        call = CallLog.objects.get(pk=call_pk)
    except Exception as exc:
        logger.error('AI summarize: CallLog %s not found — %s', call_pk, exc)
        return

    content = _build_content(call)
    if not content.strip():
        logger.warning('AI summarize: CallLog %s has no content to summarize', call_pk)
        return

    try:
        from google import genai                      # google-genai SDK
        client = genai.Client()                       # uses GOOGLE_API_KEY from env

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=f"{SYSTEM_PROMPT}\n\n{content}",
        )
        raw = response.text.strip()

        # Strip markdown code fences if Gemini adds them
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]

        data = json.loads(raw)

    except json.JSONDecodeError as exc:
        logger.error('AI summarize: JSON parse error for call %s — %s', call_pk, exc)
        return
    except Exception as exc:
        logger.error('AI summarize: Gemini error for call %s — %s', call_pk, exc)
        return

    # Write results back to CallLog (PostgreSQL only)
    try:
        from .models import CallLog
        urgency = data.get('urgency')
        if urgency is not None:
            try:
                urgency = max(1, min(5, int(urgency)))
            except (ValueError, TypeError):
                urgency = None

        sentiment = data.get('sentiment', '')
        if sentiment not in ('positive', 'neutral', 'negative'):
            sentiment = ''

        CallLog.objects.filter(pk=call_pk).update(
            ai_summary      = data.get('summary', ''),
            ai_intent       = data.get('intent', '')[:50],
            ai_sentiment    = sentiment,
            ai_urgency      = urgency,
            ai_next_action  = data.get('next_action', '')[:255],
            ai_processed_at = timezone.now(),
        )
        logger.info('AI summarize: CallLog %s processed — intent=%s sentiment=%s urgency=%s',
                    call_pk, data.get('intent'), sentiment, urgency)

    except Exception as exc:
        logger.error('AI summarize: DB write error for call %s — %s', call_pk, exc)
