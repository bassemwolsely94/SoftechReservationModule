"""
apps/shortage/views.py  — v2

Endpoints:
  POST   /api/shortage/lists/                         Create list
  GET    /api/shortage/lists/                         List all
  GET    /api/shortage/lists/{id}/                    Detail
  POST   /api/shortage/lists/{id}/add-item/           Add single item
  POST   /api/shortage/lists/{id}/bulk-import/        Bulk text import
  POST   /api/shortage/lists/{id}/ocr/                Upload image → extract lines
  POST   /api/shortage/lists/{id}/voice-import/       Voice transcript → add items
  GET    /api/shortage/lists/{id}/items/{iid}/matches/ Top-N fuzzy matches
  PATCH  /api/shortage/lists/{id}/items/{iid}/        Update/confirm item
  DELETE /api/shortage/lists/{id}/items/{iid}/delete/ Delete item
  POST   /api/shortage/lists/{id}/submit/             Change status
  POST   /api/shortage/lists/{id}/resolve/
  GET    /api/shortage/lists/{id}/stock-check/        Internal stock check
  GET    /api/shortage/lists/{id}/export/             CSV export
  GET    /api/shortage/lists/{id}/export-excel/       Excel export
  GET    /api/shortage/lists/aggregate/               Aggregate across lists (query params)
  GET    /api/shortage/lists/export-aggregated/       Aggregated Excel download
"""
import csv
import io
import logging
import re
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ShortageList, ShortageItem
from .matching import find_best_matches, _normalize, parse_quantity_from_text, dedup_key
from .stock_check import check_stock_for_list
from .export import export_list_excel, export_aggregated_excel
from .serializers import (
    ShortageListSerializer, ShortageListDetailSerializer,
    ShortageListCreateSerializer,
    ShortageItemSerializer, ShortageItemWriteSerializer, ShortageItemUpdateSerializer,
)

logger = logging.getLogger('elrezeiky.shortage')


# ─── OCR helper functions ─────────────────────────────────────────────────────

# Below this catalog-match score an OCR'd line is flagged for human review.
_OCR_REVIEW_THRESHOLD = 0.55


def _ocr_response(lines: list, engine: str, raw_text: str, readings: list = None) -> dict:
    """Build the OCR action response, enriching each line with the best catalog
    match (learned corpus first, then fuzzy) so the UI can pre-fill the match and
    flag low-confidence reads for review.

    When ``readings`` is supplied (the n-best path), each line carries several
    candidate drug-name readings; we score EVERY reading against the catalog and
    keep the winner — so a mis-read cursive name ('Plaquenil') is rescued by an
    alternate the catalog recognises ('Singulair'). The winning reading also
    becomes the line's text, so import stores the corrected name."""
    from .matching import (find_best_matches, looks_non_drug, head_mismatch,
                           extract_components, _normalize)
    candidates = []
    review = 0
    for i, text in enumerate(lines):
        rd       = readings[i] if (readings and i < len(readings)) else None
        options  = (rd.get('readings') or [text]) if rd else [text]
        strength = (rd.get('strength') or '') if rd else ''
        qty      = rd.get('qty') if rd else None

        best = None
        best_text = (str(options[0]).strip() + ' ' + str(strength).strip()).strip()
        for opt in options:
            q = (str(opt).strip() + ' ' + str(strength).strip()).strip()
            try:
                hits = find_best_matches(q, top_n=1, min_score=0.15)
            except Exception as exc:
                logger.warning('OCR match preview failed for %r: %s', q, exc)
                continue
            if hits:
                h = hits[0]
                if best is None or float(h['score']) > best['score']:
                    best = {
                        'item_id':   h['item_id'],
                        'item_name': h['item_name'],
                        'score':     round(float(h['score']), 3),
                        'learned':   bool(h.get('learned')),
                    }
                    best_text = q   # show/import the reading the catalog recognised
        # ── Review guard: turn silent confident-wrong matches into a visible flag ─
        needs_review = not best or (not best['learned'] and best['score'] < _OCR_REVIEW_THRESHOLD)
        review_reason = None
        if not best:
            review_reason = 'لا مطابقة'
        elif looks_non_drug(best_text):
            review_reason = 'قد لا يكون دواءً'          # note / name / phone / sentence
        elif not best['learned'] and head_mismatch(best_text, best['item_name']):
            review_reason = 'قد يكون دواءً مختلفاً'     # matched a different molecule
        elif needs_review:
            review_reason = 'ثقة منخفضة'
        else:
            # Compare the NUMBER only (4000iu vs 4000mg = same; 750 vs 500 = differ)
            rs = re.search(r'\d+(?:\.\d+)?', extract_components(best_text).strength or '')
            it = re.search(r'\d+(?:\.\d+)?', extract_components(best['item_name']).strength or '')
            if rs and it and rs.group(0) != it.group(0):
                review_reason = 'تركيز مختلف'          # strength differs
        needs_review = needs_review or bool(review_reason)
        if needs_review:
            review += 1
        cand = {'text': best_text, 'match': best, 'needs_review': needs_review,
                'review_reason': review_reason}
        if qty:
            cand['qty'] = qty
        candidates.append(cand)

    out_lines = [c['text'] for c in candidates]   # winning readings (corrected names)
    return {
        'raw_text':      raw_text,
        'lines':         out_lines,         # back-compat (plain strings)
        'line_count':    len(out_lines),
        'engine':        engine,
        'candidates':    candidates,        # enriched: per-line match + review flag
        'review_count':  review,
    }


def _clean_ocr_lines(raw_text: str) -> list[str]:
    """
    Post-process raw OCR text into clean candidate lines.
    Rejects:  < 3 chars, no 2+ consecutive letters, pure punctuation/digits,
              "isolated-character" noise (>55% single-char tokens).
    """
    lines = []
    for line in raw_text.splitlines():
        line = re.sub(r'[|_\[\]{}\\^~`]+', '', line).strip()
        if len(line) < 3:
            continue
        if not re.search(r'[a-zA-Z؀-ۿ]{2,}', line):
            continue
        if re.fullmatch(r'[\d\s\-_.,;:/\\()]+', line):
            continue
        tokens  = [t for t in line.split() if t]
        singles = sum(1 for t in tokens if len(t) == 1)
        if len(tokens) >= 2 and singles / len(tokens) > 0.55:
            continue
        lines.append(line)
    return lines


# ── EasyOCR singleton (lazy-init, reused across requests) ─────────────────────
_easyocr_reader      = None
_easyocr_reader_lock = __import__('threading').Lock()

def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is not None:
        return _easyocr_reader
    with _easyocr_reader_lock:
        if _easyocr_reader is None:
            import easyocr
            logger.info('Initialising EasyOCR reader (one-time download on first use)…')
            _easyocr_reader = easyocr.Reader(['en', 'ar'], gpu=False, verbose=False)
            logger.info('EasyOCR reader ready.')
    return _easyocr_reader


def _ocr_easyocr(image_file) -> tuple:
    """
    Local neural-network OCR using EasyOCR.
    No API key required.  pip install easyocr
    Downloads ~100 MB model files on first use (cached afterwards).
    Much better than pytesseract for handwriting and mixed scripts.
    Returns (lines, 'easyocr', raw_text) or (None, None, None).
    """
    try:
        import numpy as np
        from PIL import Image, ImageOps

        image_file.seek(0)
        img = Image.open(image_file).convert('RGB')

        # Deskew + contrast + denoise + upscale (handwriting/mixed-script lift)
        from .preprocess import preprocess_for_ocr
        img = preprocess_for_ocr(img, binarize=False)

        reader  = _get_easyocr_reader()
        results = reader.readtext(np.array(img), detail=0, paragraph=False)

        raw_text = '\n'.join(str(r) for r in results)
        lines    = _clean_ocr_lines(raw_text)
        logger.info('EasyOCR: extracted %d lines', len(lines))
        return lines, 'easyocr', raw_text, None

    except ImportError:
        logger.warning('easyocr not installed — run: pip install easyocr')
        return None, None, None, None
    except Exception as exc:
        logger.error('EasyOCR failed: %s', exc, exc_info=True)
        return None, None, None, None


_OCR_PROMPT = (
    'This image is a HANDWRITTEN or printed list of pharmaceutical products from '
    'a pharmacy in Egypt. Names may be in English, Arabic, or a mix, and the '
    'handwriting can be messy, faint, or slanted.\n\n'
    'Transcribe every medication/product line. Rules:\n'
    '- ONE item per line, in the ORDER written.\n'
    '- Read carefully as a pharmacist would: recognise common Egyptian brand and '
    'generic drug names even when letters are unclear, and prefer a real drug '
    'name over a literal but nonsensical transcription.\n'
    '- Include the dosage strength / pack when written (e.g. "Novonorm 14", '
    '"Sugorlo 50/500", "Augmentin 1g", "أوجمنتين 1جم").\n'
    '- Keep Arabic names in Arabic script and English names in Latin script; do '
    'NOT translate between them.\n'
    '- Preserve any quantity written next to the item (e.g. "Panadol 2", "5 علبة").\n'
    '- Do NOT add numbering, bullets, headers, dates, prices, totals, or any '
    'explanatory text.\n'
    '- If a line is truly illegible, output your single best guess anyway.\n'
    '- Output the plain list ONLY, one item per line.\n'
)


# n-best prompt: recognise the drug (not the letters) and offer several readings
# so the catalog can pick the real one — the single biggest lift on hard cursive.
_OCR_JSON_PROMPT = (
    'This image is a HANDWRITTEN or printed list of pharmaceutical products from a '
    'pharmacy in Egypt. Names may be English, Arabic, or a mix; handwriting can be '
    'messy, faint, or slanted.\n\n'
    'Read it as an expert Egyptian pharmacist would: RECOGNISE the real medication '
    'from the scrawl rather than transcribing letters literally.\n'
    'Return STRICT JSON ONLY: {"lines":[{"readings":[...],"strength":"...","qty":number-or-null}]}\n'
    'Rules:\n'
    '- Output EXACTLY ONE object per written line, in order — never merge or drop a '
    'line, even if unsure.\n'
    '- "readings": 1-3 plausible REAL medication names (brand or generic on the '
    'Egyptian/international market), most-likely first. Prefer a real drug name '
    '(e.g. Singulair, Aerius, Seretide Diskus, Acetylcysteine, Augmentin) over a '
    'nonsensical letter-for-letter guess.\n'
    '- Keep Arabic names in Arabic script and English names in Latin; do NOT translate.\n'
    '- "strength": dosage/pack if written (e.g. "10mg", "500", "50/500"), else "".\n'
    '- "qty": quantity written next to the item as a number, else null.\n'
    '- Ignore dates, prices, totals, headers, signatures, and stamps.\n'
)


def _ocr_gemini(image_file, api_key: str) -> tuple:
    """
    Cloud OCR via Google Gemini (free tier: 1,500 req/day, no credit card).
    Uses the current google-genai SDK (pip install google-genai).

    Tries an n-best JSON read first (several candidate drug names per line, so the
    catalog can pick the real one — big lift on cursive), falling back to a plain
    line list. Tries models in order until one succeeds (quota varies by project).
    Returns (lines, 'gemini/<model>', raw_text, readings) where ``readings`` is a
    per-line list of {readings, strength, qty} for the n-best path (else None),
    or (None, None, None, None) on total failure.
    """
    import io as _io
    import json as _json
    try:
        from google import genai
        from google.genai import types
        from PIL import Image
    except ImportError:
        logger.warning('google-genai not installed — run: pip install google-genai')
        return None, None, None, None

    try:
        image_file.seek(0)
        img = Image.open(image_file).convert('RGB')

        # Clean the image before sending to the vision model (natural profile —
        # no harsh binarization, which hurts LLM handwriting reads).
        from .preprocess import preprocess_for_ocr
        img = preprocess_for_ocr(img, binarize=False)

        # Encode as JPEG bytes
        buf = _io.BytesIO()
        img.save(buf, format='JPEG', quality=92)
        part_img = types.Part.from_bytes(data=buf.getvalue(), mime_type='image/jpeg')

        client = genai.Client(api_key=api_key)

        # Try models in preference order; quota limits differ per project/tier
        _MODELS = [
            'gemini-2.5-flash',
            'gemini-2.5-flash-preview-05-20',
            'gemini-2.0-flash',
            'gemini-flash-latest',
        ]
        for model_name in _MODELS:
            # 1. n-best JSON (recognise-the-drug + several readings) ────────────
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[part_img, types.Part.from_text(text=_OCR_JSON_PROMPT)],
                    config=types.GenerateContentConfig(response_mime_type='application/json'),
                )
                data = _json.loads(resp.text)
                readings, lines = [], []
                for ln in (data.get('lines') or []):
                    reads = [str(x).strip() for x in (ln.get('readings') or []) if str(x).strip()]
                    if not reads:
                        continue
                    strength = str(ln.get('strength') or '').strip()
                    readings.append({'readings': reads, 'strength': strength, 'qty': ln.get('qty')})
                    lines.append((reads[0] + ' ' + strength).strip())
                if lines:
                    logger.info('Gemini n-best OCR (%s): %d lines', model_name, len(lines))
                    return lines, f'gemini/{model_name}', resp.text.strip(), readings
            except Exception as e:
                logger.warning('Gemini n-best (%s) failed: %s', model_name, e)

            # 2. Plain line-list fallback ──────────────────────────────────────
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[part_img, types.Part.from_text(text=_OCR_PROMPT)],
                )
                raw_text = resp.text.strip()
                lines = [l.strip() for l in raw_text.splitlines()
                         if l.strip() and len(l.strip()) >= 2]
                if lines:
                    logger.info('Gemini plain OCR (%s): %d lines', model_name, len(lines))
                    return lines, f'gemini/{model_name}', raw_text, None
            except Exception as e:
                logger.warning('Gemini plain (%s) failed: %s', model_name, e)
                continue

        logger.error('All Gemini models exhausted — check quota at https://aistudio.google.com/')
        return None, None, None, None

    except Exception as exc:
        logger.error('Gemini OCR setup failed: %s', exc, exc_info=True)
        return None, None, None, None


class ShortageListViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ShortageList.objects.select_related('branch', 'created_by__user').annotate(
            item_count=Count('items'),
            matched_count=Count('items', filter=Q(items__item__isnull=False)),
            confirmed_count=Count('items', filter=Q(items__is_confirmed=True)),
            unmatched_count=Count('items', filter=Q(items__is_unmatched=True)),
        )
        branch = self.request.query_params.get('branch')
        status_q = self.request.query_params.get('status')
        if branch:
            qs = qs.filter(branch_id=branch)
        if status_q:
            qs = qs.filter(status=status_q)
        return qs.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return ShortageListCreateSerializer
        if self.action == 'retrieve':
            return ShortageListDetailSerializer
        return ShortageListSerializer

    def perform_create(self, serializer):
        profile = getattr(self.request.user, 'staff_profile', None)
        serializer.save(created_by=profile)

    # ─── Add single item ───────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='add-item')
    def add_item(self, request, pk=None):
        shortage_list = self.get_object()
        ser = ShortageItemWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw_name = ser.validated_data.get('raw_name', '').strip()

        # Duplicate prevention — keyed on (drug_name, strength) so that
        # the same drug at different concentrations is allowed.
        dk = dedup_key(raw_name)
        if dk:
            existing_keys = {
                dedup_key(n)
                for n in shortage_list.items.values_list('raw_name', flat=True)
            }
            if dk in existing_keys:
                return Response(
                    {'detail': f'الصنف "{raw_name}" بنفس التركيز موجود بالفعل في هذه القائمة'},
                    status=status.HTTP_409_CONFLICT,
                )

        source = ser.validated_data.get('source', 'manual')
        item = ser.save(shortage_list=shortage_list, source=source)

        # Auto-match (top-1 at high threshold) — user must still confirm
        if not item.item_id:
            matches = find_best_matches(item.raw_name, top_n=1, min_score=0.70)
            if matches:
                from apps.catalog.models import Item
                best = matches[0]
                try:
                    item.item        = Item.objects.get(pk=best['item_id'])
                    item.match_score = best['score']
                    item.save(update_fields=['item', 'match_score'])
                except Item.DoesNotExist:
                    pass

        return Response(ShortageItemSerializer(item).data, status=status.HTTP_201_CREATED)

    # ─── Shared import helper (used by bulk-import & voice-import) ────────────

    def _import_lines(self, shortage_list, lines, source='bulk', confirmed_by=None):
        """
        Core import logic: parse raw lines, auto-match, deduplicate.

        Each entry in ``lines`` may be either a plain string ("name qty") OR a
        dict ``{raw, item_id?, item_softech_id?}``. When an explicit item is
        given (the user corrected/picked it inline before importing), we skip
        fuzzy matching, create the row already matched + confirmed, and teach the
        shared corpus (``learn_alias``) so that name resolves instantly next time.

        Returns { created: [...], skipped: [...] }.
        """
        from apps.catalog.models import Item as CatalogItem
        from .matching import learn_alias

        # Key on (drug_name, strength) — same drug, different concentration = allowed
        existing_keys = {
            dedup_key(n)
            for n in shortage_list.items.values_list('raw_name', flat=True)
        }

        created = []
        skipped = []

        for entry in lines:
            if isinstance(entry, dict):
                raw         = str(entry.get('raw', '')).strip()
                override_id = entry.get('item_id')
                override_sid = (entry.get('item_softech_id') or '').strip() if entry.get('item_softech_id') else ''
            else:
                raw, override_id, override_sid = str(entry).strip(), None, ''
            if not raw:
                continue

            raw_name, qty = parse_quantity_from_text(raw)
            dk = dedup_key(raw_name)

            if dk in existing_keys:
                skipped.append(raw_name)
                continue
            existing_keys.add(dk)

            item_obj  = None
            score     = None
            picked    = False

            # 1. Explicit user pick wins (by PG pk, else SOFTECH itemcode) ──────
            if override_id or override_sid:
                try:
                    item_obj = (CatalogItem.objects.get(pk=override_id) if override_id
                                else CatalogItem.objects.get(softech_id=override_sid))
                    score, picked = 1.0, True
                except (CatalogItem.DoesNotExist, ValueError, TypeError):
                    item_obj = None

            # 2. Otherwise auto-match at medium threshold — user still confirms ─
            if item_obj is None:
                matches = find_best_matches(raw_name, top_n=1, min_score=0.55)
                if matches:
                    best = matches[0]
                    try:
                        item_obj = CatalogItem.objects.get(pk=best['item_id'])
                        score    = best['score']
                    except CatalogItem.DoesNotExist:
                        pass

            si = ShortageItem.objects.create(
                shortage_list   = shortage_list,
                raw_name        = raw_name,
                quantity_needed = qty,
                item            = item_obj,
                match_score     = score,
                source          = source,
                is_confirmed    = picked,
                confirmed_by    = confirmed_by if picked else None,
                confirmed_at    = timezone.now() if picked else None,
            )
            # A hand-picked correction is high-quality training for the corpus.
            if picked and item_obj:
                try:
                    learn_alias(raw_name, item_obj, source='shortage')
                except Exception as e:
                    logger.warning('learn_alias failed on import for %r: %s', raw_name, e)
            created.append(ShortageItemSerializer(si).data)

        return {'created': created, 'skipped': skipped}

    # ─── Bulk text import ──────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request, pk=None):
        """
        POST { lines: ['paracetamol 10', {raw:'أموكسيسيلين 5', item_id: 42}, ...], source: 'bulk' }
        Each line is either "item_name [qty]" or {raw, item_id?, item_softech_id?}
        (a dict carries an explicit user-picked item → created confirmed + learned).
        """
        shortage_list = self.get_object()
        lines  = request.data.get('lines', [])
        source = request.data.get('source', 'bulk')

        if not lines:
            return Response({'detail': 'لا توجد سطور'}, status=status.HTTP_400_BAD_REQUEST)

        profile = getattr(request.user, 'staff_profile', None)
        result = self._import_lines(shortage_list, lines, source=source, confirmed_by=profile)
        return Response({
            'created':       len(result['created']),
            'skipped':       len(result['skipped']),
            'skipped_names': result['skipped'],
            'items':         result['created'],
        })

    # ─── OCR: upload image → extract text lines ────────────────────────────────

    @action(detail=True, methods=['post'], url_path='ocr')
    def ocr_extract(self, request, pk=None):
        """
        POST multipart: { image: <file> }

        Engine priority:
          1. Claude Vision API (claude-haiku-4-5) — handles handwriting, mixed
             Arabic/English, poor lighting.  Requires ANTHROPIC_API_KEY in .env.
          2. pytesseract — printed text, if Tesseract is installed on the server.
          3. 503 if neither is available.

        Returns { raw_text, lines: [...], line_count, engine }
        """
        if 'image' not in request.FILES:
            return Response({'detail': 'لم يتم رفع صورة'}, status=status.HTTP_400_BAD_REQUEST)

        image_file = request.FILES['image']

        from django.conf import settings as django_settings

        # ── 1. Google Gemini (optional, free tier) ─────────────────────────────
        gemini_key = getattr(django_settings, 'GEMINI_API_KEY', '') or ''
        if gemini_key:
            lines, engine, raw_text, readings = _ocr_gemini(image_file, gemini_key)
            if lines is not None:
                return Response(_ocr_response(lines, engine, raw_text, readings))

        # ── 2. EasyOCR (local, no API key, good for handwriting) ──────────────
        image_file.seek(0)
        lines, engine, raw_text, readings = _ocr_easyocr(image_file)
        if lines is not None:
            return Response(_ocr_response(lines, engine, raw_text, readings))

        # ── 3. pytesseract (printed text only) ────────────────────────────────
        image_file.seek(0)
        try:
            import pytesseract
            from PIL import Image
            from .preprocess import preprocess_for_ocr
            img      = Image.open(image_file).convert('RGB')
            # Classical engine → binarized profile (crisp black/white on print).
            img      = preprocess_for_ocr(img, binarize=True)
            raw_text = pytesseract.image_to_string(img, lang='ara+eng', config='--psm 11 --oem 1')
            lines    = _clean_ocr_lines(raw_text)
            return Response(_ocr_response(lines, 'pytesseract', raw_text))
        except ImportError:
            pass
        except Exception as exc:
            logger.error('pytesseract OCR failed: %s', exc, exc_info=True)

        # ── 4. Nothing available ───────────────────────────────────────────────
        return Response(
            {'detail': (
                'لا يوجد محرك OCR متاح على الخادم.\n'
                'الخيارات المجانية:\n'
                '• EasyOCR (محلي): pip install easyocr\n'
                '• Google Gemini (مجاني 1500 طلب/يوم): '
                'أضف GEMINI_API_KEY إلى .env من https://aistudio.google.com/'
            )},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # ─── Voice: transcript → add items ────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='voice-import')
    def voice_import(self, request, pk=None):
        """
        POST { transcript: "أموكسيسيلين عشرة باراسيتامول خمسة", source: 'voice' }
        Splits transcript into item lines and runs the shared import logic.
        The transcript comes from the browser's Web Speech API.
        """
        transcript = (request.data.get('transcript') or '').strip()
        if not transcript:
            return Response({'detail': 'لا يوجد نص صوتي'}, status=status.HTTP_400_BAD_REQUEST)

        # Split on Arabic commas, English commas, newlines, or 2+ consecutive spaces
        lines = re.split(r'[،,\n]+|(?<=[a-zA-Zء-ي])\s{2,}', transcript)
        lines = [l.strip() for l in lines if l.strip()]

        if not lines:
            return Response({'detail': 'لم يتم استخراج أصناف من النص'}, status=status.HTTP_400_BAD_REQUEST)

        shortage_list = self.get_object()
        result = self._import_lines(shortage_list, lines, source='voice')
        return Response({
            'created':       len(result['created']),
            'skipped':       len(result['skipped']),
            'skipped_names': result['skipped'],
            'items':         result['created'],
        })

    # ─── Fuzzy matches for one item ───────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path=r'items/(?P<iid>\d+)/matches')
    def item_matches(self, request, pk=None, iid=None):
        """Return top-3 fuzzy matches for a shortage item (always requires user confirmation)."""
        shortage_list = self.get_object()
        try:
            si = shortage_list.items.get(pk=iid)
        except ShortageItem.DoesNotExist:
            return Response({'detail': 'العنصر غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        top_n = min(int(request.query_params.get('top', 8)), 20)

        # Fetch more candidates than requested so we can re-rank within families
        matches = find_best_matches(si.raw_name, top_n=top_n * 2, min_score=0.15)

        # ── Within-family ranking ─────────────────────────────────────────────
        # When several results share the same base drug name (e.g. all NEVILOB
        # variants), rank them by how closely the strength matches the request.
        # This ensures "نيفيلوب 5mg" surfaces NEVILOB 5MG above NEVILOB 2.5MG.
        from .matching import extract_components, _normalize as _n
        raw_comp  = extract_components(si.raw_name)
        raw_str   = _n(raw_comp.strength or '')

        def _rank_key(m):
            item_comp = extract_components(m['item_name'])
            item_str  = _n(item_comp.strength or '')
            # bonus: strength match → -1 (sorts first), else 0
            str_bonus = -1 if (raw_str and raw_str == item_str) else 0
            return (round(-m['score'], 4), str_bonus)

        matches.sort(key=_rank_key)
        return Response(matches[:top_n])

    # ─── Confirm / update one item ────────────────────────────────────────────

    @action(detail=True, methods=['patch'], url_path=r'items/(?P<iid>\d+)')
    def update_item(self, request, pk=None, iid=None):
        shortage_list = self.get_object()
        try:
            si = shortage_list.items.get(pk=iid)
        except ShortageItem.DoesNotExist:
            return Response({'detail': 'العنصر غير موجود'}, status=status.HTTP_404_NOT_FOUND)

        ser = ShortageItemUpdateSerializer(si, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        si = ser.save()

        # Auto-confirm when item is explicitly selected and not previously confirmed
        if si.item_id and not si.is_confirmed and request.data.get('is_confirmed'):
            profile = getattr(request.user, 'staff_profile', None)
            si.is_confirmed  = True
            si.confirmed_by  = profile
            si.confirmed_at  = timezone.now()
            si.save(update_fields=['is_confirmed', 'confirmed_by', 'confirmed_at'])
            # Teach the shared corpus so this raw name resolves instantly next time.
            try:
                from .matching import learn_alias
                learn_alias(si.raw_name, si.item, source='shortage')
            except Exception as e:
                logger.warning('learn_alias failed for shortage item %s: %s', si.pk, e)

        return Response(ShortageItemSerializer(si).data)

    # ─── Delete one item ──────────────────────────────────────────────────────

    @action(detail=True, methods=['delete'], url_path=r'items/(?P<iid>\d+)/delete')
    def delete_item(self, request, pk=None, iid=None):
        shortage_list = self.get_object()
        try:
            si = shortage_list.items.get(pk=iid)
        except ShortageItem.DoesNotExist:
            return Response({'detail': 'العنصر غير موجود'}, status=status.HTTP_404_NOT_FOUND)
        si.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ─── Status transitions ───────────────────────────────────────────────────

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        sl = self.get_object()
        if sl.status != 'open':
            return Response({'detail': 'القائمة ليست مفتوحة'}, status=status.HTTP_400_BAD_REQUEST)
        sl.status = 'submitted'
        sl.save(update_fields=['status'])
        return Response({'detail': 'تم إرسال القائمة'})

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        sl = self.get_object()
        sl.status = 'resolved'
        sl.save(update_fields=['status'])
        return Response({'detail': 'تم حل القائمة'})

    # ─── Internal stock check ─────────────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='stock-check')
    def stock_check(self, request, pk=None):
        """
        Check stock levels for all confirmed items across branches.
        Returns transfer suggestions when stock is available elsewhere.
        """
        sl     = self.get_object()
        result = check_stock_for_list(sl)
        return Response(result)

    # ─── CSV export ───────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        sl    = self.get_object()
        items = sl.items.select_related('item').order_by('raw_name')
        buf   = io.StringIO()
        w     = csv.writer(buf)
        w.writerow(['الاسم كما أُدخل', 'الصنف المطابق', 'كود ERP',
                    'الكمية', 'الوحدة', 'مصدر الإدخال', 'نسبة التطابق', 'مُأكَّد', 'ملاحظات'])
        for si in items:
            w.writerow([
                si.raw_name,
                si.item.name if si.item_id else '',
                si.item.softech_id if si.item_id else '',
                si.quantity_needed,
                si.unit,
                si.source,
                f'{si.match_score:.0%}' if si.match_score else '',
                'نعم' if si.is_confirmed else 'لا',
                si.notes,
            ])
        response = HttpResponse(
            '﻿' + buf.getvalue(),
            content_type='text/csv; charset=utf-8-sig',
        )
        response['Content-Disposition'] = f'attachment; filename="shortage_{sl.id}.csv"'
        return response

    # ─── Excel export (single list) ───────────────────────────────────────────

    @action(detail=True, methods=['get'], url_path='export-excel')
    def export_excel(self, request, pk=None):
        sl      = self.get_object()
        content = export_list_excel(sl)
        resp    = HttpResponse(
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="shortage_{sl.id}.xlsx"'
        return resp

    @action(detail=True, methods=['get'], url_path='export-supplier-matrix')
    def export_supplier_matrix_action(self, request, pk=None):
        """Comprehensive supplier matrix: a code column per main distributor +
        last-bought/price sourcing guide. Read-only SofTech lookups."""
        from .export import export_supplier_matrix
        sl = self.get_object()
        resp = HttpResponse(
            export_supplier_matrix(sl),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="shortage_{sl.id}_suppliers.xlsx"'
        return resp

    @action(detail=True, methods=['get'], url_path=r'export-supplier-po/(?P<suppcode>[^/]+)')
    def export_supplier_po_action(self, request, pk=None, suppcode=None):
        """Single-supplier purchase order carrying THAT supplier's own item codes."""
        from .export import export_supplier_po
        sl = self.get_object()
        supplier_name = request.query_params.get('name', '')
        resp = HttpResponse(
            export_supplier_po(sl, suppcode, supplier_name),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="po_{sl.id}_{suppcode}.xlsx"'
        return resp

    # ─── Aggregate view (across multiple lists) ───────────────────────────────

    @action(detail=False, methods=['get'], url_path='aggregate')
    def aggregate(self, request):
        """
        GET /api/shortage/lists/aggregate/?branch_ids=1,2&status=open
        Aggregate shortage items across multiple lists.
        """
        branch_ids  = request.query_params.get('branch_ids', '')
        status_q    = request.query_params.get('status', 'open')
        date_from   = request.query_params.get('date_from')
        date_to     = request.query_params.get('date_to')

        qs = ShortageList.objects.all()
        if branch_ids:
            ids = [b.strip() for b in branch_ids.split(',') if b.strip()]
            qs = qs.filter(branch_id__in=ids)
        if status_q:
            qs = qs.filter(status=status_q)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        # Aggregate items
        from collections import defaultdict
        agg: dict = {}

        for sl in qs.prefetch_related('items__item', 'branch'):
            branch_name = sl.branch.name_ar or sl.branch.name
            for si in sl.items.all():
                if si.item_id:
                    key = f'item:{si.item_id}'
                    if key not in agg:
                        agg[key] = {
                            'item_id':    si.item_id,
                            'item_code':  si.item.softech_id,
                            'item_name':  si.item.name,
                            'total_qty':  0.0,
                            'branches':   defaultdict(float),
                            'sources':    set(),
                            'confirmed':  True,
                            'unmatched':  False,
                        }
                    agg[key]['total_qty'] += float(si.quantity_needed)
                    agg[key]['branches'][branch_name] += float(si.quantity_needed)
                    agg[key]['sources'].add(si.source)
                    if not si.is_confirmed:
                        agg[key]['confirmed'] = False
                else:
                    key = f'raw:{_normalize(si.raw_name)}'
                    if key not in agg:
                        agg[key] = {
                            'item_id':    None,
                            'item_code':  '',
                            'item_name':  si.raw_name,
                            'total_qty':  0.0,
                            'branches':   defaultdict(float),
                            'sources':    set(),
                            'confirmed':  False,
                            'unmatched':  True,
                        }
                    agg[key]['total_qty'] += float(si.quantity_needed)
                    agg[key]['branches'][branch_name] += float(si.quantity_needed)
                    agg[key]['sources'].add(si.source)

        # Serialize
        result = []
        for entry in sorted(agg.values(), key=lambda x: -x['total_qty']):
            result.append({
                **entry,
                'branches':       dict(entry['branches']),
                'sources':        list(entry['sources']),
                'branch_breakdown': '; '.join(
                    f"{br}:{qty:.0f}" for br, qty in entry['branches'].items()
                ),
            })

        return Response({'count': len(result), 'results': result})

    # ─── Aggregated Excel export ──────────────────────────────────────────────

    @action(detail=False, methods=['get'], url_path='export-aggregated')
    def export_aggregated(self, request):
        """
        GET /api/shortage/lists/export-aggregated/?branch_ids=1,2&status=open
        Download aggregated Excel across multiple lists.
        """
        branch_ids = request.query_params.get('branch_ids', '')
        status_q   = request.query_params.get('status', 'open')
        date_from  = request.query_params.get('date_from')
        date_to    = request.query_params.get('date_to')

        qs = ShortageList.objects.all()
        if branch_ids:
            ids = [b.strip() for b in branch_ids.split(',') if b.strip()]
            qs = qs.filter(branch_id__in=ids)
        if status_q:
            qs = qs.filter(status=status_q)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        lists = list(qs.prefetch_related('items__item', 'branch'))
        content = export_aggregated_excel(lists)
        resp = HttpResponse(
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        from datetime import date
        resp['Content-Disposition'] = f'attachment; filename="shortage_aggregate_{date.today()}.xlsx"'
        return resp

