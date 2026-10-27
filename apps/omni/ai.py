"""
apps/omni/ai.py

Conversation AI assist (doc 15 Phase 4) — reply suggestions + summary.

Reads a window of the unified timeline and asks Gemini for a concise summary,
detected intent/urgency, and 3 suggested Arabic replies the pharmacist can
send with one click. AI assists; it never sends (doc 15 AI principle).

Same google-genai SDK + GOOGLE_API_KEY as apps/callcenter/ai.py.
"""
import json
import logging

logger = logging.getLogger('elrezeiky.omni')

SYSTEM_PROMPT = """أنت مساعد ذكي لصيدلية متعددة الفروع تعمل في مركز تواصل موحّد.
اقرأ سجل المحادثة التالي (رسائل ومكالمات وأحداث) وأعد JSON بالحقول التالية فقط:
{
  "summary": "ملخص عربي موجز في جملتين",
  "intent": "استفسار|طلب|شكوى|توصيل|حجز|تسعير|أخرى",
  "urgency": 1,
  "suggested_replies": ["رد مقترح 1", "رد مقترح 2", "رد مقترح 3"]
}
- urgency رقم من 1 (منخفض) إلى 5 (عاجل جداً)
- الردود المقترحة مهذبة وموجزة وبالعربية المصرية، جاهزة للإرسال
- أعد JSON فقط بدون أي نص إضافي
"""


def _build_transcript(conversation, events) -> str:
    who = (conversation.customer.name if conversation.customer_id
           else conversation.contact_phone or 'عميل')
    lines = [f'العميل: {who}']
    for ev in events:
        tag = {
            'message_in': 'عميل', 'message_out': 'موظف',
            'call': '📞 مكالمة', 'call_missed': '📵 مكالمة فائتة',
            'ai_insight': '✨', 'erp_reservation': '📋 حجز',
        }.get(ev.event_type, ev.event_type)
        lines.append(f'{tag}: {ev.summary}')
    return '\n'.join(lines)


def assist_conversation(conversation, events) -> dict | None:
    """Return {summary, intent, urgency, suggested_replies} or None on failure."""
    transcript = _build_transcript(conversation, events)

    try:
        from google import genai
        client = genai.Client()  # GOOGLE_API_KEY from env
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=f'{SYSTEM_PROMPT}\n\n{transcript}',
        )
        raw = (response.text or '').strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error('omni AI assist: JSON parse error — %s', exc)
        return None
    except Exception as exc:
        logger.error('omni AI assist: Gemini error — %s', exc)
        return None

    urgency = data.get('urgency')
    try:
        urgency = max(1, min(5, int(urgency))) if urgency is not None else None
    except (ValueError, TypeError):
        urgency = None

    replies = data.get('suggested_replies') or []
    if not isinstance(replies, list):
        replies = [str(replies)]

    return {
        'summary': str(data.get('summary', ''))[:1000],
        'intent': str(data.get('intent', ''))[:50],
        'urgency': urgency,
        'suggested_replies': [str(r)[:1000] for r in replies[:5]],
    }
