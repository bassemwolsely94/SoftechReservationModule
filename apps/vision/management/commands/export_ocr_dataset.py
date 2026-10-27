"""
Export the labelled OCR corpus → a training manifest (JSONL + images/).

    python manage.py export_ocr_dataset --out data/ocr_dataset
    python manage.py export_ocr_dataset --out data/rx --module pos_rx --min-conf 1

Feed the resulting manifest to `train_ocr`.
"""
from django.core.management.base import BaseCommand

from apps.vision.dataset import build_dataset, dataset_readiness


class Command(BaseCommand):
    help = 'Export labelled OcrSamples to a (image, text) training manifest.'

    def add_arguments(self, parser):
        parser.add_argument('--out', required=True, help='output directory')
        parser.add_argument('--module', default=None,
                            help='pos_rx | pos_voice | purchasing_shortage | purchasing_invoice')
        parser.add_argument('--no-copy', action='store_true',
                            help='reference images in place instead of copying them')
        parser.add_argument('--min-conf', type=int, default=1,
                            help='minimum human confirmations per sample')

    def handle(self, *args, **o):
        ready = dataset_readiness(o['module'])
        self.stdout.write(f"labelled images available: {ready['labelled_images']}")
        stats = build_dataset(out_dir=o['out'], module=o['module'],
                              copy_images=not o['no_copy'], min_confirmations=o['min_conf'])
        self.stdout.write(self.style.SUCCESS(
            f"exported {stats['exported']} pairs (skipped {stats['skipped']}) → {stats['manifest']}"))
