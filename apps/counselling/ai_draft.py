"""
AI-drafted counselling sheets — a starting point for a pharmacist, never customer-facing by itself.

The draft is created through services.create_sheet(source='ai_draft') and stays a draft: this
module has no path to approval (a test reads this file to keep it that way). The pharmacist edits,
then approves in /counselling, which records who approved it.
"""
from rest_framework.exceptions import ValidationError

from . import services
from .models import TEXT_FIELDS

MAX_LEN = 1000
AR_FIELDS = tuple(f'{f}_ar' for f in TEXT_FIELDS)

PROMPT = """أنت صيدلي مصري تكتب مسودة إرشادات استخدام مختصرة لعميل صيدلية، باللغة العربية البسيطة.
الصنف: {name}
الشكل الدوائي: {form}
يستخدم في (من بيانات الصنف، قد تكون ناقصة): {indication}

اكتب كائن JSON فقط بهذه المفاتيح (نص قصير لكل مفتاح، اتركه فارغاً "" إن لم تكن متأكداً):
{keys}
وأيضاً "frequency_code" (واحد من: 1x1, 1x2, 1x3, prn أو "") و"with_food" (before أو after أو any أو "").
لا تخترع جرعات للأطفال أو الحوامل؛ اكتب "حسب إرشاد الطبيب" عند الشك. هذه مسودة سيراجعها صيدلي."""


def build_prompt(item) -> str:
    return PROMPT.format(
        name=item.name,
        form=item.shape_name_ar or item.shape_name or 'غير محدد',
        indication=getattr(item, 'effect_name_ar', '') or item.effect_name or 'غير محدد',
        keys='، '.join(f'"{k}"' for k in AR_FIELDS),
    )


def _filter(raw: dict) -> dict:
    out = {}
    for k in AR_FIELDS:
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()[:MAX_LEN]
    if raw.get('frequency_code') in ('1x1', '1x2', '1x3', 'prn'):
        out['frequency_code'] = raw['frequency_code']
    if raw.get('with_food') in ('before', 'after', 'any'):
        out['with_food'] = raw['with_food']
    return out


def draft_for_item(actor, item):
    from apps.enrichment.ai_extractor import complete_json
    raw, model = complete_json(item, build_prompt(item))
    data = _filter(raw or {})
    if not data:
        raise ValidationError({'detail': 'تعذّر إنشاء مسودة'})
    return services.create_sheet(actor, {'title': item.name, **data}, [item.pk],
                                 source='ai_draft', ai_model=model or '')
