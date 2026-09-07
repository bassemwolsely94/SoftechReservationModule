"""
apps/enrichment/ai_extractor.py

Two-stage AI enrichment pipeline:

  Stage 1 — Web scraping
    OpenFDA public API (no key) — US drug label data, indications, warnings,
    side effects, pregnancy categories, drug interactions.

  Stage 2 — Multi-provider AI extraction  (sequential fallback chain)
    Provider 1 — Gemini primary   (settings.GEMINI_API_KEY  + GEMINI_MODEL)
    Provider 2 — Gemini secondary (settings.GEMINI_API_KEY_2 + GEMINI_MODEL_2)
    Provider 3 — OpenAI fallback  (settings.OPENAI_API_KEY  + OPENAI_MODEL)

    The first provider that returns results wins.  A provider is skipped when:
      • its API key is not configured, or
      • it returns 429 / 5xx after all retry attempts.
    This lets two separate Gemini accounts double the effective free-tier quota
    before the system ever falls through to OpenAI.

  Rate limits (conservative free-tier defaults):
    Gemini  : 7 s / request  ≈ 8.6 RPM  (free tier ceiling: 10 RPM)
    OpenAI  : 21 s / request ≈ 2.9 RPM  (free tier ceiling:  3 RPM)
    Each provider tracks its own independent counter — two Gemini accounts
    run at 8.6 RPM each, never fighting over the same quota bucket.

  Override via settings:
    GEMINI_RPM   = 10   → interval = 60/10 * 0.85 = 5.1 s
    OPENAI_RPM   = 3    → interval = 60/3  * 0.85 = 17 s

Security: SOFTECH / Sybase is never touched.
         All reads are from PostgreSQL or public internet APIs.
         All writes go to PostgreSQL (EnrichmentSuggestion rows).
"""
from __future__ import annotations
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from django.conf import settings

from apps.catalog.models import Item

logger = logging.getLogger('elrezeiky')

# ── Constants ──────────────────────────────────────────────────────────────────

OPENFDA_LABEL_URL     = 'https://api.fda.gov/drug/label.json'
GEMINI_ENDPOINT       = (
    'https://generativelanguage.googleapis.com/v1beta/models/'
    '{model}:generateContent?key={key}'
)
OPENAI_ENDPOINT       = 'https://api.openai.com/v1/chat/completions'

_GEMINI_MODEL_DEFAULT = 'gemini-2.5-flash'
_OPENAI_MODEL_DEFAULT = 'gpt-4o-mini'
_REQUEST_TIMEOUT      = 25    # seconds — 2.5-flash can be slow
_MAX_RETRIES          = 2     # attempts per provider before giving up


# ── Per-provider rate limiter ─────────────────────────────────────────────────

class _RateLimiter:
    """
    Thread-safe token bucket — enforces a minimum gap between consecutive calls
    to one API key.  Each provider/account gets its own independent instance.
    """
    def __init__(self, min_interval: float, name: str):
        self._lock         = threading.Lock()
        self._last_call    = 0.0
        self._min_interval = min_interval
        self.name          = name

    def wait(self) -> None:
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


def _make_interval(rpm_setting_name: str, default_rpm: float) -> float:
    """
    Return the minimum inter-request interval (seconds) for a given RPM setting.
    Uses 85 % of the declared limit as a safety margin.
    """
    rpm = float(getattr(settings, rpm_setting_name, default_rpm))
    if rpm <= 0:
        rpm = default_rpm
    return (60.0 / rpm) * (1.0 / 0.85)


# Module-level limiters — one per provider / account
_gemini1_limiter = _RateLimiter(_make_interval('GEMINI_RPM',  10.0), 'Gemini-1')
_gemini2_limiter = _RateLimiter(_make_interval('GEMINI_RPM',  10.0), 'Gemini-2')
_openai_limiter  = _RateLimiter(_make_interval('OPENAI_RPM',   3.0), 'OpenAI')


# ── Shared fields + prompt ─────────────────────────────────────────────────────

ENRICHMENT_FIELDS = [
    'name_ar', 'brand_name',
    'manufacturer_ar',
    'atc_code',
    'indication_ar', 'indication_en',
    'contraindication_ar',
    'warning_ar',
    'pregnancy_category',
    'age_range',
    'administration_route_ar',
    'dosage_ar', 'frequency_ar', 'duration_ar',
    'side_effects_ar', 'side_effects_en',
    'drug_interactions_ar',
    'rx_otc',
    'seo_desc_ar', 'seo_desc_en',
    'medical_keywords_ar', 'medical_keywords_en',
]

# Keep the old name as an alias so any code that imports _GEMINI_FIELDS still works
_GEMINI_FIELDS = ENRICHMENT_FIELDS

_PROMPT_TEMPLATE = """\
أنت خبير دوائي متخصص في البيانات الصيدلانية للأسواق العربية.
استخرج المعلومات الصيدلانية التالية للدواء المذكور وأعد النتيجة بصيغة JSON فقط بدون أي نص إضافي.

معلومات الدواء المتاحة:
- الاسم التجاري: {name}
- الشركة المصنعة: {manufacturer}
- بلد المنشأ: {country}
- الشكل الدوائي: {dosage_form}
- الاستخدام / التصنيف: {indication}
- المواد الفعّالة: {active_ingredients}
- بيانات FDA المتاحة: {fda_data}

يُرجى تعبئة الحقول التالية بدقة طبية. أترك الحقل فارغاً ("") إذا لم تكن متأكداً.
أعد JSON صالحاً فقط بدون أي نص خارج الكائن:

{{
  "name_ar": "الاسم العربي للدواء",
  "brand_name": "الاسم التجاري باللاتيني",
  "manufacturer_ar": "اسم الشركة المصنعة بالعربية",
  "atc_code": "كود ATC مثل C09AA01",
  "indication_ar": "الاستخدامات الطبية بالعربية",
  "indication_en": "Therapeutic indications in English",
  "contraindication_ar": "موانع الاستخدام بالعربية",
  "warning_ar": "التحذيرات والاحتياطات بالعربية",
  "pregnancy_category": "فئة الحمل A أو B أو C أو D أو X",
  "age_range": "الفئة العمرية المناسبة بالعربية",
  "administration_route_ar": "طريقة الاستخدام بالعربية",
  "dosage_ar": "الجرعة المعتادة للبالغين بالعربية",
  "frequency_ar": "تكرار الجرعة بالعربية",
  "duration_ar": "مدة العلاج الموصى بها بالعربية",
  "side_effects_ar": "الآثار الجانبية الشائعة بالعربية",
  "side_effects_en": "Common side effects in English",
  "drug_interactions_ar": "التفاعلات الدوائية المهمة بالعربية",
  "rx_otc": "rx أو otc أو cd فقط",
  "seo_desc_ar": "وصف تسويقي بالعربية جملتين أو ثلاثة",
  "seo_desc_en": "Marketing description in English 2-3 sentences",
  "medical_keywords_ar": "كلمات مفتاحية طبية بالعربية مفصولة بفاصلة",
  "medical_keywords_en": "Medical keywords in English comma separated"
}}
"""


def _build_prompt(item: Item, fda_context: Optional[dict]) -> str:
    fda_parts = []
    if fda_context:
        if fda_context.get('indication_en'):
            fda_parts.append(f'Indications: {fda_context["indication_en"][:200]}')
        if fda_context.get('side_effects_en'):
            fda_parts.append(f'Side effects: {fda_context["side_effects_en"][:150]}')
        if fda_context.get('pregnancy_category'):
            fda_parts.append(f'Pregnancy: {fda_context["pregnancy_category"]}')
        if fda_context.get('rx_otc'):
            fda_parts.append(f'Rx/OTC: {fda_context["rx_otc"]}')

    return _PROMPT_TEMPLATE.format(
        name               = item.name or '',
        manufacturer       = item.producer_name or 'غير معروف',
        country            = item.origin_name_ar or item.origin_name or 'غير معروف',
        dosage_form        = item.shape_name_ar or item.shape_name or 'غير معروف',
        indication         = (
            ' / '.join(filter(None, [
                item.effect_name_ar, item.effect_name2_ar,
                item.effect_name,    item.effect_name2,
            ])) or 'غير محدد'
        ),
        active_ingredients = item.active_ingredients or 'غير معروف',
        fda_data           = ' | '.join(fda_parts) or 'غير متاح',
    )


def _clean_result(raw: dict) -> dict[str, str]:
    """Filter raw AI response to known fields; validate rx_otc."""
    clean: dict[str, str] = {}
    for field in ENRICHMENT_FIELDS:
        val = raw.get(field, '')
        if val and str(val).strip() and str(val).strip() not in ('""', "''"):
            clean[field] = str(val).strip()
    if 'rx_otc' in clean and clean['rx_otc'] not in ('rx', 'otc', 'cd'):
        del clean['rx_otc']
    return clean


def _extract_json(text: str) -> dict:
    """Robustly extract a JSON object from an AI response string."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$',       '', text, flags=re.MULTILINE)
    start = text.find('{')
    end   = text.rfind('}')
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


# ── OpenFDA scraper ────────────────────────────────────────────────────────────

def _fda_join(lst: list, max_chars: int = 400) -> str:
    if not lst:
        return ''
    text = re.sub(r'\s+', ' ', ' '.join(str(x) for x in lst)).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(' ', 1)[0] + '…'
    return text


def scrape_openfda(item_name: str) -> dict[str, str]:
    """
    Query the OpenFDA drug/label endpoint for a drug by brand name.
    Returns a partial dict of enrichment fields (English-language only).
    Silently returns {} on any network or parse error.
    """
    if not item_name:
        return {}
    brand = item_name.split()[0].strip()
    if len(brand) < 3:
        return {}

    try:
        query = f'openfda.brand_name:"{urllib.parse.quote(brand)}"'
        url   = f'{OPENFDA_LABEL_URL}?search={query}&limit=1'
        req   = urllib.request.Request(
            url, headers={'User-Agent': 'ElRezeiky-Enrichment/1.0'}
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.debug('OpenFDA lookup failed for "%s": %s', brand, exc)
        return {}

    results = data.get('results')
    if not results:
        return {}

    label   = results[0]
    openfda = label.get('openfda', {})
    out: dict[str, str] = {}

    ind = label.get('indications_and_usage') or label.get('purpose')
    if ind:
        out['indication_en'] = _fda_join(ind, 400)

    warnings = label.get('warnings') or label.get('warnings_and_cautions')
    if warnings:
        out['warning_ar'] = _fda_join(warnings, 300)

    adv = label.get('adverse_reactions')
    if adv:
        out['side_effects_en'] = _fda_join(adv, 300)

    di = label.get('drug_interactions')
    if di:
        out['drug_interactions_ar'] = _fda_join(di, 300)

    preg = label.get('pregnancy') or label.get('teratogenic_effects')
    if preg:
        text  = _fda_join(preg, 200)
        match = re.search(r'category\s+([ABCDX])\b', text, re.IGNORECASE)
        out['pregnancy_category'] = match.group(1).upper() if match else text[:10]

    dosage = label.get('dosage_and_administration')
    if dosage:
        out['dosage_ar'] = _fda_join(dosage, 250)

    pharm_class = openfda.get('pharm_class_epc') or openfda.get('pharm_class_moa')
    if pharm_class:
        out['medical_keywords_en'] = ', '.join(pharm_class[:5])

    product_type = openfda.get('product_type', [])
    if product_type:
        pt = ' '.join(product_type).lower()
        if 'otc' in pt or 'human otc' in pt:
            out['rx_otc'] = 'otc'
        elif 'prescription' in pt or 'human prescription' in pt:
            out['rx_otc'] = 'rx'

    return out


# ── Provider implementations ───────────────────────────────────────────────────

def _call_gemini(
    item: Item,
    prompt: str,
    api_key: str,
    model: str,
    limiter: _RateLimiter,
) -> dict[str, str]:
    """
    Call one Gemini account.  Returns clean result dict, or {} on permanent failure.
    Retries _MAX_RETRIES times; on 429 honours the Retry-After header.
    """
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature':     0.15,
            'topK':            10,
            'topP':            0.95,
            'maxOutputTokens': 8192,   # 2048 is too small — Arabic clinical text truncates
        },
        'safetySettings': [
            {'category': cat, 'threshold': 'BLOCK_NONE'}
            for cat in [
                'HARM_CATEGORY_HARASSMENT',
                'HARM_CATEGORY_HATE_SPEECH',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT',
                'HARM_CATEGORY_DANGEROUS_CONTENT',
            ]
        ],
    }
    url  = GEMINI_ENDPOINT.format(model=model, key=api_key)
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    for attempt in range(1, _MAX_RETRIES + 1):
        limiter.wait()
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={'Content-Type': 'application/json; charset=utf-8'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                raw = json.loads(resp.read())

            candidate     = raw['candidates'][0]
            finish_reason = candidate.get('finishReason', '')
            text          = candidate['content']['parts'][0]['text']

            if finish_reason == 'MAX_TOKENS':
                logger.warning(
                    '[%s] MAX_TOKENS hit for item %s — JSON truncated, response lost',
                    limiter.name, item.pk,
                )
                return {}   # truncated JSON cannot be parsed; skip to next provider

            result = _clean_result(_extract_json(text))
            logger.info(
                '[%s] extracted %d fields for item %s (%s)',
                limiter.name, len(result), item.pk, item.name,
            )
            return result

        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = int(exc.headers.get('Retry-After', 65))
                logger.warning(
                    '[%s] 429 for item %s — waiting %ds (attempt %d/%d)',
                    limiter.name, item.pk, retry_after, attempt, _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(retry_after)
                    continue
                return {}   # exhausted — caller will try next provider
            elif exc.code in (500, 503):
                wait = 30 * attempt
                logger.warning(
                    '[%s] %d for item %s — waiting %ds (attempt %d/%d)',
                    limiter.name, exc.code, item.pk, wait, attempt, _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)
                    continue
                return {}
            else:
                logger.warning('[%s] HTTP %d for item %s', limiter.name, exc.code, item.pk)
                return {}

        except (KeyError, IndexError, TypeError) as exc:
            logger.warning('[%s] parse error for item %s: %s', limiter.name, item.pk, exc)
            return {}

        except Exception as exc:
            logger.warning('[%s] call failed for item %s: %s', limiter.name, item.pk, exc)
            return {}

    return {}


def _call_openai(
    item: Item,
    prompt: str,
    api_key: str,
    model: str,
    limiter: _RateLimiter,
) -> dict[str, str]:
    """
    Call OpenAI chat completions (gpt-4o-mini by default).
    Uses response_format=json_object to guarantee parseable output.
    """
    payload = {
        'model':           model,
        'temperature':     0.15,
        'max_tokens':      4096,   # 2048 too small for Arabic clinical JSON
        'response_format': {'type': 'json_object'},
        'messages': [
            {
                'role':    'system',
                'content': (
                    'أنت خبير دوائي. أجب دائماً بكائن JSON صالح فقط '
                    'بدون أي نص خارجه. '
                    'You are a pharmaceutical expert. Always respond with '
                    'a valid JSON object only, no text outside it.'
                ),
            },
            {'role': 'user', 'content': prompt},
        ],
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    for attempt in range(1, _MAX_RETRIES + 1):
        limiter.wait()
        try:
            req = urllib.request.Request(
                OPENAI_ENDPOINT, data=body,
                headers={
                    'Content-Type':  'application/json; charset=utf-8',
                    'Authorization': f'Bearer {api_key}',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                raw = json.loads(resp.read())

            choice        = raw['choices'][0]
            finish_reason = choice.get('finish_reason', '')
            text          = choice['message']['content']

            if finish_reason == 'length':
                logger.warning(
                    '[%s] MAX_TOKENS hit for item %s — JSON truncated, response lost',
                    limiter.name, item.pk,
                )
                return {}

            result = _clean_result(_extract_json(text))
            logger.info(
                '[%s] extracted %d fields for item %s (%s)',
                limiter.name, len(result), item.pk, item.name,
            )
            return result

        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = int(exc.headers.get('Retry-After', 65))
                logger.warning(
                    '[%s] 429 for item %s — waiting %ds (attempt %d/%d)',
                    limiter.name, item.pk, retry_after, attempt, _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(retry_after)
                    continue
                return {}
            elif exc.code in (500, 503):
                wait = 30 * attempt
                logger.warning(
                    '[%s] %d for item %s — waiting %ds (attempt %d/%d)',
                    limiter.name, exc.code, item.pk, wait, attempt, _MAX_RETRIES,
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(wait)
                    continue
                return {}
            else:
                logger.warning('[%s] HTTP %d for item %s', limiter.name, exc.code, item.pk)
                return {}

        except (KeyError, IndexError, TypeError) as exc:
            logger.warning('[%s] parse error for item %s: %s', limiter.name, item.pk, exc)
            return {}

        except Exception as exc:
            logger.warning('[%s] call failed for item %s: %s', limiter.name, item.pk, exc)
            return {}

    return {}


# ── Sequential fallback chain ──────────────────────────────────────────────────

def extract_with_ai_fallback(
    item: Item,
    fda_context: Optional[dict] = None,
) -> dict[str, str]:
    """
    Try AI providers in sequence; return the first non-empty result.

    Provider order (configured in settings.py):

      1. Gemini primary   — GEMINI_API_KEY  + GEMINI_MODEL   (default gemini-2.5-flash)
      2. Gemini secondary — GEMINI_API_KEY_2 + GEMINI_MODEL_2
      3. OpenAI fallback  — OPENAI_API_KEY  + OPENAI_MODEL   (default gpt-4o-mini)

    A provider is silently skipped when its key is absent.
    Returns {} only when every configured provider fails.
    """
    prompt = _build_prompt(item, fda_context)

    # ── Provider 1: Gemini primary ────────────────────────────────────────────
    key1 = getattr(settings, 'GEMINI_API_KEY', '').strip()
    if key1:
        model1 = (
            getattr(settings, 'GEMINI_MODEL', _GEMINI_MODEL_DEFAULT).strip()
            or _GEMINI_MODEL_DEFAULT
        )
        result = _call_gemini(item, prompt, key1, model1, _gemini1_limiter)
        if result:
            return result
        logger.info('Gemini-1 returned nothing for item %s — trying next provider', item.pk)

    # ── Provider 2: Gemini secondary ─────────────────────────────────────────
    key2 = getattr(settings, 'GEMINI_API_KEY_2', '').strip()
    if key2:
        model2 = (
            getattr(settings, 'GEMINI_MODEL_2', _GEMINI_MODEL_DEFAULT).strip()
            or _GEMINI_MODEL_DEFAULT
        )
        result = _call_gemini(item, prompt, key2, model2, _gemini2_limiter)
        if result:
            return result
        logger.info('Gemini-2 returned nothing for item %s — trying next provider', item.pk)

    # ── Provider 3: OpenAI ────────────────────────────────────────────────────
    oai_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
    if oai_key:
        oai_model = (
            getattr(settings, 'OPENAI_MODEL', _OPENAI_MODEL_DEFAULT).strip()
            or _OPENAI_MODEL_DEFAULT
        )
        result = _call_openai(item, prompt, oai_key, oai_model, _openai_limiter)
        if result:
            return result
        logger.info('OpenAI returned nothing for item %s — all providers exhausted', item.pk)

    return {}


# ── Backward-compat wrapper ────────────────────────────────────────────────────

def extract_with_gemini(
    item: Item,
    fda_context: Optional[dict] = None,
) -> dict[str, str]:
    """Legacy entry point — delegates to the full fallback chain."""
    return extract_with_ai_fallback(item, fda_context)


# ── Combined pipeline ──────────────────────────────────────────────────────────

def enrich_item_with_ai(item: Item) -> dict[str, str]:
    """
    Full enrichment pipeline for a single item:
      1. Scrape OpenFDA for English label data
      2. Try AI providers in sequence (Gemini-1 → Gemini-2 → OpenAI)
      3. Merge: FDA fields fill gaps; AI fields take priority

    Returns merged dict of {field_name: value}.
    """
    fda_data = scrape_openfda(item.name)
    ai_data  = extract_with_ai_fallback(item, fda_context=fda_data)
    return {**fda_data, **ai_data}
