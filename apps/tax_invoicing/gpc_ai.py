"""
apps/tax_invoicing/gpc_ai.py — an AI proposal of the GPC brick for uncoded items that have no learned one.

The AI only picks from a shortlist we build (the family's bricks from people's decisions and ETA's approved codes,
then GS1 bricks that share a word with the item); an answer outside the shortlist, not on the loaded brick list,
or malformed is stored as "no suggestion" with the reason. Medicines (default brick) and items with a learned
brick (gpc_learn) are never asked. Only item data goes out: name, family, category, type, origin, producer —
no prices, no customers. The proposal is only shown; a person confirms the brick (CLAUDE.md rule 10).
Runs from the nightly job or an explicit "ask again", behind TAX_GPC_AI_ENABLED.
"""
import datetime as dt
import json
import logging
import re
from collections import Counter

from django.conf import settings
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

from . import coding_queue, gpc, gpc_learn
from .models import TaxBrickSuggestion, TaxCodingDecision, TaxGpcBrick

logger = logging.getLogger(__name__)

FAMILY_LIMIT = 15
SEGMENTS = ('50', '51', '53')          # food/beverage, healthcare, beauty/personal care first
DEFINITION_CHARS = 160
REASON_CHARS = 120
FRESH_DAYS = 30
OUTAGE_STREAK = 5        # this many "no answer" in a row = the providers are down; stop the run
CONFIDENCE = ('high', 'medium', 'low')
_WORD = re.compile(r'[a-z]{4,}')     # GS1 names are English: an Arabic-only name gets no word matches (family bricks only)
_STOP = {'with', 'from', 'tabs', 'tablet', 'tablets', 'caps', 'capsule', 'capsules', 'syrup', 'other', 'items'}

NO_ITEM = 'الصنف غير مربوط بالكتالوج'
NO_SHORTLIST = 'لا توجد فئات مرشحة'
SHORTLIST_ERROR = 'تعذر بناء القائمة المرشحة'
NO_ANSWER = 'لم يرد مزود الذكاء الاصطناعي'
NOT_LISTED = 'الفئة المقترحة ليست في القائمة المرشحة'
NOT_KNOWN = 'الفئة المقترحة غير موجودة في قائمة GPC'
BAD_ANSWER = 'رد غير صالح من الذكاء الاصطناعي'


def enabled():
    return bool(getattr(settings, 'TAX_GPC_AI_ENABLED', False))


def _segment_order():
    return Case(*[When(segment_code__startswith=s, then=Value(i)) for i, s in enumerate(SEGMENTS)],
                default=Value(len(SEGMENTS)), output_field=IntegerField())


def _entry(b):
    return {'code': b.code, 'name': b.name_en or b.name_ar,
            'definition': (b.definition or '')[:DEFINITION_CHARS]}


def _words(item):
    text = ' '.join([item.family_name or '', item.category.name if item.category_id else '', item.name or ''])
    return sorted({w for w in _WORD.findall(text.lower()) if w not in _STOP})


def shortlist(item, limit=40):
    """[{code, name, definition}]: the family's bricks from people's decisions and ETA's approved codes (most used,
    up to 15), then GS1 bricks whose name or definition shares a word with the item's family / category / name,
    segments 50/51/53 first. With no GS1 list loaded, the bricks of those segments (or the whole owner list when it
    carries no segments) fill the rest."""
    counts = Counter()
    family = item.family_name or ''
    if family:
        for by in (gpc_learn._decision_counts([family]), gpc_learn._eta_counts([family])):
            counts.update(by.get(family, {}))
    top = [code for code, _ in counts.most_common(FAMILY_LIMIT)]
    rows = {b.code: b for b in TaxGpcBrick.objects.filter(code__in=top)}
    listed = gpc.loaded()
    out = [_entry(rows[c]) if c in rows else {'code': c, 'name': '', 'definition': ''}
           for c in top if c in rows or not listed]

    seen = {e['code'] for e in out}
    gs1 = TaxGpcBrick.objects.exclude(source='workbook')
    if gs1.exists():
        words = _words(item)
        if words:
            match = Q()
            for w in words:
                match |= Q(name_en__icontains=w) | Q(definition__icontains=w)
            more = gs1.filter(match)
        else:
            more = gs1.none()
    else:
        more = TaxGpcBrick.objects.filter(segment_code__regex=r'^5[013]')
        if not more.exists():
            more = TaxGpcBrick.objects.all()
    for b in more.exclude(code__in=seen).annotate(seg=_segment_order()).order_by('seg', 'code')[:max(limit - len(out), 0)]:
        out.append(_entry(b))
    return out[:limit]


PROMPT = """Choose the GS1 GPC brick for this item sold in an Egyptian pharmacy. Pick ONLY from the list.
Item: {name}
Family: {family} | Category: {category} | Type: {kind} | Origin: {origin} | Producer: {producer}
Bricks (code | name | definition):
{bricks}
Reply with one JSON object only, no other text:
{{"brick": "<8-digit code from the list, or empty>", "second": "<another code from the list, or empty>",
"confidence": "high|medium|low", "reason": "<Arabic, at most 120 characters>"}}"""


def build_prompt(item, bricks):
    return PROMPT.format(
        name=item.name or '', family=item.family_name or '-',
        category=(item.category.name if item.category_id else '') or '-', kind=item.medicine_type_name or '-',
        origin=item.origin_name or '-', producer=item.producer_name or '-',
        bricks='\n'.join(f"{b['code']} | {b['name']} | {b['definition']}" for b in bricks))


def _store(profile, **fields):
    defaults = {'brick': '', 'second': '', 'reason': '', 'confidence': '', 'source': TaxBrickSuggestion.SOURCE_NONE,
                'model': '', 'error': '', 'asked_at': timezone.now()}
    defaults.update(fields)
    for f in ('reason', 'error'):
        defaults[f] = str(defaults[f])[:200]
    defaults['model'] = str(defaults['model'])[:60]
    row, _ = TaxBrickSuggestion.objects.update_or_create(profile=profile, defaults=defaults)
    return row


def _parse(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


def _code(value):
    value = str(value or '').strip()
    return value if gpc.BRICK.match(value) else ''


def suggest_one(profile):
    """Ask the AI for one item and store the answer. None when nothing is asked: switch off, a medicine, or the item
    already has a learned brick. Every failure is stored as a 'none' suggestion with its reason, never raised."""
    if not enabled():
        return None
    item = coding_queue.catalog_item(profile)
    if item is not None and item.medicine_type_name == 'Medicine':
        return None
    if profile.pk in gpc_learn.learned([profile]):
        return None
    if item is None:
        return _store(profile, error=NO_ITEM)
    try:
        bricks = shortlist(item)
    except Exception as exc:     # our own data, not the AI: say so, and keep the job going
        logger.warning('gpc_ai: shortlist for item %s: %s', profile.softech_itemcode, type(exc).__name__)
        return _store(profile, error=f'{SHORTLIST_ERROR} ({type(exc).__name__})')
    if not bricks:
        return _store(profile, error=NO_SHORTLIST)
    try:
        from apps.enrichment.ai_extractor import complete_json
        raw, model = complete_json(item, build_prompt(item, bricks))
    except Exception as exc:     # a provider / network failure must not stop the job
        logger.warning('gpc_ai: item %s: %s', profile.softech_itemcode, type(exc).__name__)
        return _store(profile, error=f'{NO_ANSWER} ({type(exc).__name__})')
    if not raw:
        return _store(profile, model=model or '', error=NO_ANSWER)
    data = _parse(raw)
    if data is None:
        return _store(profile, model=model or '', error=BAD_ANSWER)
    allowed = {b['code'] for b in bricks}
    brick = _code(data.get('brick'))
    if not brick:
        return _store(profile, model=model or '', error=BAD_ANSWER)
    if brick not in allowed:
        return _store(profile, model=model or '', error=f'{NOT_LISTED}: {brick}')
    if not gpc.known(brick):
        return _store(profile, model=model or '', error=f'{NOT_KNOWN}: {brick}')
    second = _code(data.get('second'))
    if second == brick or second not in allowed or not gpc.known(second):
        second = ''
    confidence = str(data.get('confidence') or '').strip().lower()
    reason = data.get('reason')
    return _store(profile, brick=brick, second=second, source=TaxBrickSuggestion.SOURCE_AI, model=model or '',
                  confidence=confidence if confidence in CONFIDENCE else '',
                  reason=(reason.strip() if isinstance(reason, str) else '')[:REASON_CHARS])


def pending(limit=200):
    """Queue items worth asking, biggest uncoded value first: no learned brick, not a medicine, not kept out,
    and no suggestion asked in the last 30 days. A "no answer" (provider down) is not an answer: asked again next run."""
    from apps.catalog.models import Item

    sold, profiles, _ = coding_queue.candidates()
    kept_out = set(TaxCodingDecision.objects.filter(profile__in=[p.pk for p in profiles],
                                                    decision=TaxCodingDecision.DECISION_KEEP_OUT)
                   .values_list('profile_id', flat=True))
    fresh = set(TaxBrickSuggestion.objects.filter(profile__in=[p.pk for p in profiles],
                                                  asked_at__gte=timezone.now() - dt.timedelta(days=FRESH_DAYS))
                .exclude(error__startswith=NO_ANSWER).values_list('profile_id', flat=True))
    learned = gpc_learn.learned(profiles)
    codes = [p.softech_itemcode for p in profiles]
    items = list(Item.objects.filter(Q(pk__in=[p.item_id for p in profiles if p.item_id]) | Q(softech_id__in=codes))
                 .values_list('pk', 'softech_id', 'medicine_type_name'))
    by_pk, by_code = {pk: kind for pk, _, kind in items}, {code: kind for _, code, kind in items}

    def kind(p):     # the linked item first, as coding_queue.catalog_item
        return by_pk.get(p.item_id) if p.item_id else by_code.get(p.softech_itemcode)

    left = [p for p in profiles if p.pk not in kept_out and p.pk not in fresh and p.pk not in learned
            and kind(p) != 'Medicine']
    left.sort(key=lambda p: (-(sold[p.softech_itemcode]['value'] or 0), p.softech_itemcode))
    return left[:limit]


def run(limit=200):
    """Ask for up to `limit` items. Stops when the switch is off (also between items), and after OUTAGE_STREAK
    "no answer" results in a row (counts['stopped'] = 'provider'): the provider chain never raises, it waits and
    returns nothing, so an outage would otherwise grind through every item. Returns counts."""
    if not enabled():
        return {'skipped': 'switch_off'}
    counts = Counter()
    streak = 0
    for profile in pending(limit):
        if streak >= OUTAGE_STREAK:
            counts['stopped'] = 'provider'
            break
        if not enabled():
            counts['stopped'] = 'switch_off'
            break
        try:
            row = suggest_one(profile)
        except Exception as exc:    # a database hiccup on one item: record and move on
            logger.warning('gpc_ai: item %s: %s', profile.softech_itemcode, type(exc).__name__)
            counts['errors'] += 1
            continue
        if row is None:
            counts['skipped'] += 1
        elif row.source == TaxBrickSuggestion.SOURCE_AI:
            counts['suggested'] += 1
        else:
            counts['none'] += 1
        streak = streak + 1 if row is not None and row.error.startswith(NO_ANSWER) else 0
    return dict(counts)
