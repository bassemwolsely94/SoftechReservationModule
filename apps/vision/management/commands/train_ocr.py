"""
Fine-tune ElRezeiky's IN-HOUSE handwriting OCR model (Donut) on the exported corpus.

    # 1. export the labelled corpus
    python manage.py export_ocr_dataset --out data/ocr_dataset
    # 2. fine-tune (GPU box)
    python manage.py train_ocr --manifest data/ocr_dataset/manifest.jsonl \
        --images data/ocr_dataset --out models/rx_ocr --epochs 8
    # 3. point the app at it
    #    INHOUSE_OCR_MODEL_DIR=models/rx_ocr  → auto-joins run_engines' ensemble

REQUIREMENTS (owner, on a GPU machine — NOT installed on the app server):
    pip install torch transformers datasets sentencepiece pillow

This is a standard image→text (VisionEncoderDecoder / Donut) fine-tune driven by the HF
Seq2SeqTrainer, so the training loop is the library's, not hand-rolled. The model learns to
emit the confirmed drug names for each prescription/invoice image. Data volume matters: run
it only once the corpus has accumulated enough labelled samples (watch the dashboard).
"""
import json
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Fine-tune the in-house Donut OCR model on an exported dataset (GPU + ML deps required).'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True, help='manifest.jsonl from export_ocr_dataset')
        parser.add_argument('--images', default='', help='base dir for relative image paths (dataset out_dir)')
        parser.add_argument('--out', required=True, help='save dir → set INHOUSE_OCR_MODEL_DIR to this')
        parser.add_argument('--base', default='naver-clova-ix/donut-base', help='base model to fine-tune')
        parser.add_argument('--epochs', type=int, default=8)
        parser.add_argument('--batch', type=int, default=2)
        parser.add_argument('--lr', type=float, default=3e-5)

    def handle(self, *args, **o):
        try:
            import torch
            from PIL import Image
            from datasets import Dataset
            from transformers import (DonutProcessor, VisionEncoderDecoderModel,
                                      Seq2SeqTrainer, Seq2SeqTrainingArguments)
        except ImportError:
            raise CommandError(
                'Missing ML dependencies. On a GPU machine run:\n'
                '  pip install torch transformers datasets sentencepiece pillow')

        # ── load the exported (image, names) pairs ─────────────────────────────
        rows = []
        with open(o['manifest'], encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        if not rows:
            raise CommandError('manifest is empty — export the corpus first, and let it accumulate.')
        self.stdout.write(f'training on {len(rows)} labelled samples')

        base_dir = o['images'] or os.path.dirname(o['manifest'])
        processor = DonutProcessor.from_pretrained(o['base'])
        model = VisionEncoderDecoderModel.from_pretrained(o['base'])
        model.config.decoder_start_token_id = processor.tokenizer.convert_tokens_to_ids(['<s_rx>'])[0]
        model.config.pad_token_id = processor.tokenizer.pad_token_id

        def _target(names):
            # the model emits names one per line, wrapped in the task tokens
            return '<s_rx>' + '\n'.join(names) + '</s_rx>'

        def _encode(batch):
            img = Image.open(os.path.join(base_dir, batch['image'])).convert('RGB')
            pixel_values = processor(img, return_tensors='pt').pixel_values[0]
            labels = processor.tokenizer(
                _target(batch['text']), add_special_tokens=False,
                max_length=256, padding='max_length', truncation=True, return_tensors='pt').input_ids[0]
            labels[labels == processor.tokenizer.pad_token_id] = -100
            return {'pixel_values': pixel_values, 'labels': labels}

        ds = Dataset.from_list(rows).map(_encode, remove_columns=['image', 'text', 'sample_id', 'module'])
        ds.set_format(type='torch', columns=['pixel_values', 'labels'])

        args = Seq2SeqTrainingArguments(
            output_dir=o['out'], num_train_epochs=o['epochs'],
            per_device_train_batch_size=o['batch'], learning_rate=o['lr'],
            fp16=torch.cuda.is_available(), logging_steps=25, save_strategy='epoch',
            remove_unused_columns=False, report_to=[])
        Seq2SeqTrainer(model=model, args=args, train_dataset=ds).train()

        model.save_pretrained(o['out'])
        processor.save_pretrained(o['out'])
        self.stdout.write(self.style.SUCCESS(
            f"saved fine-tuned model → {o['out']}  (set INHOUSE_OCR_MODEL_DIR to this path)"))
