"""
apps/vision/ocr.py — P2: the recognition chain that runs the IN-HOUSE engines in
parallel with (and as a fallback to) Gemini, so the module is not 100% cloud-dependent
and every read tells us WHICH engine produced it.

Chain, best-first:
  1. Gemini      — n-best drug readings (strongest on hard cursive), cloud.
  2. EasyOCR     — in-house neural OCR (handwriting + mixed AR/EN), local, no key.
  3. Tesseract   — in-house classical OCR (printed ar+eng), local.

Reuses the exact engines already wired in apps/shortage. Returns (readings, engine)
where readings = [{readings:[...], strength, qty}] — the shape _readings_to_candidates
expects. `engine` is banked on the OcrSample so we can compare in-house vs Gemini over
time and, as the in-house engines improve on ElRezeiky's own data, shift the default.
"""


def _line_readings(lines):
    return [{'readings': [str(l)], 'strength': '', 'qty': None}
            for l in (lines or []) if str(l).strip()]


# Gemini stays primary until the in-house model proves itself on the accuracy dashboard;
# 'inhouse' still contributes to the ensemble/consensus and can be promoted later.
_ENGINE_PRIORITY = ['gemini', 'inhouse', 'easyocr', 'tesseract']


def run_engines(image_file, *, api_key=''):
    """
    Run EVERY available engine on the image CONCURRENTLY → {engine: readings}. Each engine
    gets its own copy of the bytes (thread-safe) and is independently guarded, so one
    failing just omits it. Concurrency overlaps Gemini's network wait with the local
    CPU engines. This is the material for the ensemble + the accuracy metrics.
    """
    import io
    import concurrent.futures as cf

    try:
        image_file.seek(0)
    except Exception:
        pass
    data = image_file.read()
    if not data:
        return {}

    def _gemini():
        if not api_key:
            return None
        from apps.shortage.views import _ocr_gemini
        lines, _e, _raw, readings = _ocr_gemini(io.BytesIO(data), api_key)
        return readings or _line_readings(lines) or None

    def _easyocr():
        from apps.shortage.views import _ocr_easyocr
        lines, _e, _raw, _r = _ocr_easyocr(io.BytesIO(data))
        return _line_readings(lines) or None

    def _tesseract():
        import pytesseract
        from PIL import Image
        from apps.shortage.preprocess import preprocess_for_ocr
        from apps.shortage.views import _clean_ocr_lines
        img = preprocess_for_ocr(Image.open(io.BytesIO(data)).convert('RGB'), binarize=True)
        raw = pytesseract.image_to_string(img, lang='ara+eng', config='--psm 11 --oem 1')
        return _line_readings(_clean_ocr_lines(raw)) or None

    def _inhouse():
        # ElRezeiky's own fine-tuned model — None (skipped) until one is trained + configured.
        from .inhouse import recognize_inhouse
        return recognize_inhouse(data)

    def _safe(fn):
        try:
            return fn()
        except Exception:
            return None

    jobs = {'gemini': _gemini, 'inhouse': _inhouse, 'easyocr': _easyocr, 'tesseract': _tesseract}
    out = {}
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = {ex.submit(_safe, fn): name for name, fn in jobs.items()}
        for fut in cf.as_completed(futures):
            r = fut.result()
            if r:
                out[futures[fut]] = r
    return out


def pick_primary(engine_readings):
    """Choose the engine whose readings drive the UI (Gemini > EasyOCR > Tesseract)."""
    for e in _ENGINE_PRIORITY:
        if engine_readings.get(e):
            return e, engine_readings[e]
    for e, r in (engine_readings or {}).items():
        if r:
            return e, r
    return '', []


def build_consensus(engine_readings):
    """
    item_id → sorted list of engines whose top reading resolves (via the catalog) to it.
    An item several engines agree on is a stronger signal — the catalog is the arbiter.
    """
    from apps.shortage.matching import find_best_matches
    item_engines = {}
    for engine, readings in (engine_readings or {}).items():
        seen = set()
        for r in (readings or []):
            reads = r.get('readings') or []
            strength = (r.get('strength') or '').strip()
            if not reads:
                continue
            q = (str(reads[0]) + ' ' + strength).strip()
            m = find_best_matches(q, top_n=1)
            if m:
                iid = m[0]['item_id']
                if iid not in seen:
                    seen.add(iid)
                    item_engines.setdefault(iid, set()).add(engine)
    return {iid: sorted(engs) for iid, engs in item_engines.items()}


def recognize(image_file, *, api_key=''):
    """Read a prescription image → (readings, engine). ('', []) if every engine fails."""
    from apps.shortage.views import _ocr_gemini, _ocr_easyocr, _clean_ocr_lines

    # 1. Gemini (cloud, n-best)
    if api_key:
        try:
            lines, _e, _raw, readings = _ocr_gemini(image_file, api_key)
            if readings:
                return readings, 'gemini'
            if lines:
                return _line_readings(lines), 'gemini'
        except Exception:
            pass

    # 2. EasyOCR (in-house neural — handwriting + mixed script)
    try:
        lines, _e, _raw, _r = _ocr_easyocr(image_file)
        if lines:
            return _line_readings(lines), 'easyocr'
    except Exception:
        pass

    # 3. Tesseract (in-house classical — printed Arabic + English)
    try:
        import pytesseract
        from PIL import Image
        from apps.shortage.preprocess import preprocess_for_ocr
        image_file.seek(0)
        img = preprocess_for_ocr(Image.open(image_file).convert('RGB'), binarize=True)
        raw = pytesseract.image_to_string(img, lang='ara+eng', config='--psm 11 --oem 1')
        lines = _clean_ocr_lines(raw)
        if lines:
            return _line_readings(lines), 'tesseract'
    except Exception:
        pass

    return [], ''
