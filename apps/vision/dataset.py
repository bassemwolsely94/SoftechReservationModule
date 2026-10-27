"""
apps/vision/dataset.py — P3 step 1: turn the labelled OcrSample corpus into a training
dataset for the in-house handwriting model.

Each labelled sample (image + human-confirmed item names) becomes one (image, target-text)
training pair. The target is the confirmed drug names — the ground truth a document model
(e.g. Donut / TrOCR) learns to read straight from ElRezeiky's own prescriptions and invoices.

Deterministic, read-only over the corpus. Emits a JSONL manifest + an images/ folder that
the training command consumes. No ML deps here — this is just data preparation.
"""
import json
import os
import shutil

from .models import OcrSample


def build_dataset(*, out_dir, module=None, copy_images=True, min_confirmations=1):
    """
    Export labelled image samples → {out_dir}/manifest.jsonl (+ images/ when copy_images).
    Each line: {sample_id, module, image, text:[names]}. Returns a stats dict.
    """
    os.makedirs(out_dir, exist_ok=True)
    img_dir = os.path.join(out_dir, 'images')
    if copy_images:
        os.makedirs(img_dir, exist_ok=True)

    qs = OcrSample.objects.exclude(confirmations=[]).filter(media_type='image')
    if module:
        qs = qs.filter(module=module)

    manifest = os.path.join(out_dir, 'manifest.jsonl')
    exported, skipped = 0, 0
    with open(manifest, 'w', encoding='utf-8') as fh:
        for s in qs.iterator():
            confs = s.confirmations or []
            names = [(c.get('name') or c.get('reading') or '').strip() for c in confs]
            names = [n for n in names if n]
            if len(confs) < min_confirmations or not names or not s.image:
                skipped += 1
                continue
            try:
                src = s.image.path
            except Exception:
                skipped += 1
                continue
            if not os.path.exists(src):
                skipped += 1
                continue

            if copy_images:
                fname = f'{s.id}{os.path.splitext(src)[1] or ".jpg"}'
                try:
                    shutil.copyfile(src, os.path.join(img_dir, fname))
                except Exception:
                    skipped += 1
                    continue
                image_ref = os.path.join('images', fname)
            else:
                image_ref = src

            fh.write(json.dumps({
                'sample_id': s.id, 'module': s.module,
                'image': image_ref, 'text': names,
            }, ensure_ascii=False) + '\n')
            exported += 1

    return {'exported': exported, 'skipped': skipped, 'manifest': manifest, 'out_dir': out_dir}


def dataset_readiness(module=None):
    """How much labelled data is available for training (per the corpus right now)."""
    qs = OcrSample.objects.exclude(confirmations=[]).filter(media_type='image')
    if module:
        qs = qs.filter(module=module)
    return {'labelled_images': qs.count()}
