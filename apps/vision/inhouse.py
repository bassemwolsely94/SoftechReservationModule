"""
apps/vision/inhouse.py — P3: the inference slot for ElRezeiky's OWN fine-tuned OCR model.

`recognize_inhouse(image_bytes)` loads a document model (Donut / VisionEncoderDecoder)
fine-tuned on our corpus, from settings.INHOUSE_OCR_MODEL_DIR, and reads the drug names
straight off the image. It returns None when:
  • no model directory is configured / present, or
  • torch / transformers aren't installed, or
  • inference fails.
In every None case the parallel chain (run_engines) simply skips the in-house engine, so
this is safe to ship BEFORE any model exists — the moment the owner trains one and points
INHOUSE_OCR_MODEL_DIR at it, it auto-joins the ensemble alongside Gemini.
"""
import re

_state = {'loaded': False, 'model': None, 'processor': None}


def _load():
    if _state['loaded']:
        return _state['model']
    _state['loaded'] = True
    from django.conf import settings
    import os
    model_dir = getattr(settings, 'INHOUSE_OCR_MODEL_DIR', '') or ''
    if not model_dir or not os.path.isdir(model_dir):
        return None
    try:
        from transformers import DonutProcessor, VisionEncoderDecoderModel
        _state['processor'] = DonutProcessor.from_pretrained(model_dir)
        _state['model'] = VisionEncoderDecoderModel.from_pretrained(model_dir)
        _state['model'].eval()
    except Exception:
        _state['model'] = None
    return _state['model']


def _parse_names(seq):
    """The model is trained to emit drug names separated by its special tokens / newlines."""
    seq = re.sub(r'<[^>]+>', '\n', seq or '')
    return [ln.strip() for ln in seq.splitlines() if ln.strip()]


def recognize_inhouse(image_bytes):
    """Fine-tuned in-house model → readings [{readings:[name],strength,qty}], or None."""
    model = _load()
    if model is None or not image_bytes:
        return None
    try:
        import io
        import torch
        from PIL import Image
        proc = _state['processor']
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        pixel_values = proc(img, return_tensors='pt').pixel_values
        prompt_ids = proc.tokenizer('<s_rx>', add_special_tokens=False, return_tensors='pt').input_ids
        with torch.no_grad():
            out = model.generate(pixel_values, decoder_input_ids=prompt_ids, max_length=256)
        names = _parse_names(proc.batch_decode(out)[0])
        return [{'readings': [n], 'strength': '', 'qty': None} for n in names] or None
    except Exception:
        return None


def is_available():
    """True when a fine-tuned in-house model is loaded and usable."""
    return _load() is not None
