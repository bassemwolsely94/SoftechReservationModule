"""
apps/help/ask.py — «اسأل النظام»: answers "how do I …" questions using ONLY the in-app
help text.

1. retrieve the best-matching help articles (registry.retrieve — deterministic);
2. hand those articles, and nothing else, to the LLM with strict instructions:
   answer only from them, cite the screens used, say so when the answer is not there;
3. keep only citations that point at the articles we sent.

It explains how to use the system. It never decides anything: no prices, discounts,
totals, doses, substitutions or approvals — the prompt forbids it and the answer always
links back to the source article. With no LLM configured (or on failure) the caller
falls back to the retrieved articles.
"""
import json
import logging

from django.conf import settings

from . import registry

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 14000

PROMPT = """You are the in-app help assistant of the ElRezeiky pharmacy operations system.
Answer the staff member's question using ONLY the help articles below. Rules:
- Use only facts written in the articles. Do not use outside knowledge. Do not guess.
- If the articles do not contain the answer, set "found" to false and say briefly that the
  help guide does not cover it and that they should ask their trainer or supervisor.
- Never state prices, discount amounts, totals, drug doses, or which drug can replace
  another, and never approve or authorise anything — point to the screen/process instead.
- Be short and practical: numbered steps when it is a procedure. Name buttons exactly as
  written in the articles (between « »).
- Answer in {lang_name}, formal with Egyptian-friendly wording when Arabic.
- Return JSON only: {{"answer": "...", "found": true|false, "sources": ["screen.key", ...]}}
  where sources are the [key] of the articles you used.

The user's role: {role}

ARTICLES:
{context}

QUESTION:
{question}
"""


def _t(v, lang):
    if isinstance(v, dict) and ('ar' in v or 'en' in v):
        return (v.get(lang) or v.get('ar') or v.get('en') or '').strip()
    return str(v or '').strip()


def _item(it, lang, role):
    if isinstance(it, dict) and 'text' in it:
        if role and it.get('roles') and role not in it['roles']:
            return ''
        return _t(it['text'], lang)
    return _t(it, lang)


def article_text(s, module, lang, role=''):
    """One help article as plain text for the model."""
    out = [f"[{s['key']}] {_t(s.get('title'), lang)} — {_t(module.get('title'), lang)}",
           _t(s.get('summary'), lang)]
    if s.get('audience'):
        out.append('Who: ' + _t(s['audience'], lang))
    for t in s.get('tabs') or []:
        out.append(f"Tab «{_t(t.get('title'), lang)}»: {_t(t.get('body'), lang)}")
    steps = [x for x in (_item(i, lang, role) for i in s.get('steps') or []) if x]
    if steps:
        out.append('Steps:\n' + '\n'.join(f'{n}. {x}' for n, x in enumerate(steps, 1)))
    tips = [x for x in (_item(i, lang, role) for i in s.get('tips') or []) if x]
    if tips:
        out.append('Notes:\n' + '\n'.join(f'- {x}' for x in tips))
    for qa in s.get('faq') or []:
        out.append(f"Q: {_t(qa.get('q'), lang)}\nA: {_t(qa.get('a'), lang)}")
    if s.get('notes'):
        out.append("Trainer's note: " + _t(s['notes'], lang))
    wfs = module.get('workflows') or []
    if s.get('workflows') is not None:
        wfs = [w for w in wfs if w.get('key') in s['workflows']]
    for wf in wfs:
        states = '; '.join(f"{_t(st.get('label'), lang)}: {_t(st.get('desc'), lang)}" for st in wf.get('states') or [])
        out.append(f"Workflow {_t(wf.get('title'), lang)}: {states}")
    return '\n'.join(x for x in out if x)


def build_context(articles, modules, lang, role):
    parts, used, size = [], [], 0
    for s in articles:
        txt = article_text(s, modules.get(s['module'], {}), lang, role)
        if size and size + len(txt) > MAX_CONTEXT_CHARS:
            break
        parts.append(txt[:MAX_CONTEXT_CHARS])
        used.append(s['key'])
        size += len(txt)
    return '\n\n---\n\n'.join(parts), used


def _providers():
    out = []
    if getattr(settings, 'GEMINI_API_KEY', ''):
        out.append((settings.GEMINI_API_KEY, getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')))
    if getattr(settings, 'GEMINI_API_KEY_2', ''):
        out.append((settings.GEMINI_API_KEY_2, getattr(settings, 'GEMINI_MODEL_2', 'gemini-2.5-flash')))
    return out


def available():
    return bool(_providers())


def call_llm(prompt):
    """Raw model text, or None when no provider is configured / all fail."""
    for key, model in _providers():
        try:
            from google import genai
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(model=model, contents=prompt)
            text = (resp.text or '').strip()
            if text:
                return text
        except Exception as exc:     # network, quota, bad key → try the next provider
            logger.warning('help ask: %s failed — %s', model, exc)
    return None


def parse(raw, allowed_keys):
    """→ {answer, found, sources} with sources limited to the articles we sent."""
    text = raw.strip()
    if text.startswith('```'):
        text = text.strip('`')
        if text.lower().startswith('json'):
            text = text[4:]
    start, end = text.find('{'), text.rfind('}')
    try:
        data = json.loads(text[start:end + 1]) if start >= 0 else {}
    except (ValueError, TypeError):
        data = {}
    answer = str(data.get('answer') or '').strip() if data else raw.strip()
    sources = [k for k in (data.get('sources') or []) if k in allowed_keys] if data else []
    found = bool(data.get('found', True)) if data else True
    return {'answer': answer[:4000], 'found': found and bool(answer), 'sources': sources}


def answer(question, lang, role, articles, modules):
    """→ (result dict | None, context keys). None = no model answer (use the articles)."""
    context, keys = build_context(articles, modules, lang, role)
    if not keys:
        return None, []
    raw = call_llm(PROMPT.format(
        lang_name='English' if lang == 'en' else 'Arabic', role=role or '-',
        context=context, question=question))
    if raw is None:
        return None, keys
    return parse(raw, set(keys)), keys
