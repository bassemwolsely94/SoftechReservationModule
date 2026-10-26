"""
PaddleOCR PP-OCRv5 box sidecar (PaddleOCR 3.x API).

PaddlePaddle has no Python 3.14 wheel, so the main Django app (3.14) can't run
PaddleOCR in-process. This tiny server runs in a SEPARATE Python <=3.12 venv and
exposes PP-OCR word boxes over HTTP; the app's `paddleocr` engine POSTs a page
image and feeds the returned boxes through its existing band/template pipeline.

Contract:
  POST /boxes   multipart file field "image" (JPEG/PNG)
  → {"boxes": [{"cx":, "cy":, "w":, "h":, "text":, "conf":}, ...]}   (original-image pixels)
  GET  /health  → {"ok": true, "init": "<how PaddleOCR was constructed>"}

Run (in the 3.12 venv, see README.md):
  python server.py            # serves on 127.0.0.1:8077
Then in the app's .env:
  PADDLE_OCR_URL=http://127.0.0.1:8077/boxes

Notes on PaddleOCR 3.x:
  - default model family is PP-OCRv6, which has NO Arabic — we must request an
    Arabic-capable version (PP-OCRv5 / PP-OCRv3), so we try a few constructors.
  - `show_log` was removed; `use_angle_cls` → `use_textline_orientation`.
  - results expose rec_texts / rec_polys (or rec_boxes) / rec_scores.
"""
import io
import os
import logging

# PaddlePaddle 3.3.x has a CPU bug that crashes inference with
# "(Unimplemented) ConvertPirAttribute2RuntimeAttribute ... onednn_instruction.cc".
# The crash is in the PIR new-executor's oneDNN instruction path, so we disable BOTH
# oneDNN and the PIR executor. MUST be set before paddle is imported.
os.environ.setdefault('FLAGS_use_mkldnn', '0')
os.environ.setdefault('FLAGS_enable_pir_in_executor', '0')
os.environ.setdefault('FLAGS_enable_pir_api', '0')

import re

import numpy as np
from flask import Flask, jsonify, request
from PIL import Image
from paddleocr import PaddleOCR

_ARABIC = re.compile(r'[؀-ۿ]')


def _fix_rtl(text: str) -> str:
    """PaddleOCR emits Arabic in VISUAL order (reversed codepoints), so names come
    out backwards and never match the catalog. Reverse any Arabic-containing string
    back to logical order (e.g. 'مالتسا نذا' → 'اذن استلام'). Pure number/Latin
    boxes (prices, quantities, codes) are left untouched so they aren't corrupted."""
    t = (text or '').strip()
    return t[::-1] if _ARABIC.search(t) else t

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('paddle-sidecar')

app = Flask(__name__)

_LANG = os.environ.get('PADDLE_LANG', 'arabic')
_VER = os.environ.get('PADDLE_OCR_VERSION', 'PP-OCRv5')


def _make_ocr():
    """Construct PaddleOCR with an Arabic-capable model, tolerating 3.x API drift.
    Tries the requested version, then the known-good Arabic variants, then a bare
    lang. Returns (engine, description)."""
    base = [
        ({'lang': _LANG, 'ocr_version': _VER}, f'lang={_LANG},{_VER}'),
        ({'lang': _LANG, 'text_recognition_model_name': 'arabic_PP-OCRv5_mobile_rec'}, 'arabic_PP-OCRv5_mobile_rec'),
        ({'lang': _LANG, 'ocr_version': 'PP-OCRv3'}, f'lang={_LANG},PP-OCRv3'),
        ({'lang': _LANG, 'text_recognition_model_name': 'arabic_PP-OCRv3_mobile_rec'}, 'arabic_PP-OCRv3_mobile_rec'),
        ({'lang': _LANG}, f'lang={_LANG} (defaults)'),
    ]
    # try each model WITH oneDNN explicitly off first (the real fix), then without
    # the param (relying on the env flag) in case a build rejects enable_mkldnn.
    attempts = [({**kw, 'use_textline_orientation': True, 'enable_mkldnn': False}, desc + ' +mkldnn_off')
                for kw, desc in base]
    attempts += [({**kw, 'use_textline_orientation': True}, desc) for kw, desc in base]
    # PaddleOCR 2.x API (old executor — avoids the 3.x PIR/oneDNN CPU crash). These
    # succeed on a 2.x install and are rejected on 3.x, so order doesn't matter.
    attempts += [
        ({'use_angle_cls': True, 'lang': _LANG, 'show_log': False}, f'2.x use_angle_cls,lang={_LANG}'),
        ({'use_angle_cls': True, 'lang': _LANG}, f'2.x use_angle_cls,lang={_LANG}'),
        ({'lang': _LANG}, f'2.x lang={_LANG}'),
    ]
    last = None
    for kw, desc in attempts:
        try:
            eng = PaddleOCR(**kw)
            log.info('PaddleOCR ready via: %s', desc)
            return eng, desc
        except Exception as e:
            log.warning('PaddleOCR init failed (%s): %s', desc, str(e)[:160])
            last = e
    raise RuntimeError(f'could not initialize PaddleOCR for Arabic: {last}')


_ocr, _init_desc = _make_ocr()


def _field(res, key):
    """Read a field from a PaddleOCR 3.x result (dict-like or attribute)."""
    try:
        return res[key]
    except Exception:
        return getattr(res, key, None)


def _poly_xy(poly):
    """Return (xs, ys) from a 4-point polygon OR a [x1,y1,x2,y2] rect."""
    pts = poly.tolist() if hasattr(poly, 'tolist') else list(poly)
    if pts and isinstance(pts[0], (list, tuple)):          # polygon: [[x,y]*4]
        return [p[0] for p in pts], [p[1] for p in pts]
    if len(pts) == 4:                                       # rect: [x1,y1,x2,y2]
        return [pts[0], pts[2]], [pts[1], pts[3]]
    return [], []


def _looks_like_line(x):
    """A 2.x OCR line: [ [[x,y],[x,y],[x,y],[x,y]] , (text, score) ]."""
    return (isinstance(x, (list, tuple)) and len(x) == 2
            and isinstance(x[0], (list, tuple)) and x[0] and isinstance(x[0][0], (list, tuple))
            and isinstance(x[1], (list, tuple)) and len(x[1]) == 2)


def _collect_2x(obj, out):
    """Recursively pull 2.x [box,(text,score)] lines out of any nesting depth."""
    if _looks_like_line(obj):
        box, payload = obj[0], obj[1]
        text = _fix_rtl(str(payload[0] or ''))
        if text:
            xs = [p[0] for p in box]; ys = [p[1] for p in box]
            out.append({'cx': sum(xs) / len(xs), 'cy': sum(ys) / len(ys),
                        'w': max(xs) - min(xs), 'h': max(ys) - min(ys),
                        'text': text, 'conf': float(payload[1] or 0.9)})
        return
    if isinstance(obj, (list, tuple)):
        for it in obj:
            _collect_2x(it, out)


def _run(img):
    arr = np.array(img.convert('RGB'))
    try:
        results = _ocr.predict(arr)                 # 3.x
    except (AttributeError, TypeError):
        try:
            results = _ocr.ocr(arr, cls=True)       # 2.x
        except TypeError:
            results = _ocr.ocr(arr)
    out = []
    # ── 3.x dict-like results (rec_texts / rec_polys) ──
    for res in (results or []):
        texts = _field(res, 'rec_texts')
        polys = _field(res, 'rec_polys')
        if polys is None:
            polys = _field(res, 'rec_boxes')
        scores = _field(res, 'rec_scores')
        if texts is None or polys is None:
            continue
        for i, t in enumerate(texts):
            t = _fix_rtl(str(t or ''))
            if not t or i >= len(polys):
                continue
            xs, ys = _poly_xy(polys[i])
            if not xs:
                continue
            conf = float(scores[i]) if (scores is not None and i < len(scores)) else 0.9
            out.append({'cx': sum(xs) / len(xs), 'cy': sum(ys) / len(ys),
                        'w': max(xs) - min(xs), 'h': max(ys) - min(ys),
                        'text': t, 'conf': conf})
    # ── 2.x nested [box,(text,score)] results (if the 3.x path found nothing) ──
    if not out:
        _collect_2x(results, out)
    return out


@app.get('/health')
def health():
    return jsonify({'ok': True, 'init': _init_desc})


@app.post('/boxes')
def boxes():
    f = request.files.get('image')
    if not f:
        return jsonify({'error': 'no image field'}), 400
    try:
        img = Image.open(io.BytesIO(f.read()))
    except Exception as e:
        return jsonify({'error': f'bad image: {e}'}), 400
    try:
        return jsonify({'boxes': _run(img)})
    except Exception as e:
        log.exception('OCR failed')
        return jsonify({'error': str(e)[:300]}), 500


if __name__ == '__main__':
    host = os.environ.get('PADDLE_HOST', '127.0.0.1')
    port = int(os.environ.get('PADDLE_PORT', '8077'))
    log.info('starting paddle sidecar on %s:%s (init=%s)', host, port, _init_desc)
    app.run(host=host, port=port, threaded=True)
