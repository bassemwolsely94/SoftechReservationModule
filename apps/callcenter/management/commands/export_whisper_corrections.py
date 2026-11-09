"""
python manage.py export_whisper_corrections OUT_DIR

Writes corrected transcripts as a fine-tuning dataset: OUT_DIR/audio/<id>.<ext>
plus OUT_DIR/metadata.jsonl ({"audio": ..., "text": corrected, "original": whisper}).
Use with a standard Whisper fine-tune script on a GPU machine when enough
corrections accumulate (a few hundred+).
"""
import json
import mimetypes
import os

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Export human-corrected transcripts + audio for Whisper fine-tuning.'

    def add_arguments(self, parser):
        parser.add_argument('out_dir')

    def handle(self, *args, out_dir, **opts):
        from apps.callcenter.models import CallTranscript
        from apps.callcenter.whisper import load_job_audio

        audio_dir = os.path.join(out_dir, 'audio')
        os.makedirs(audio_dir, exist_ok=True)
        written = 0
        with open(os.path.join(out_dir, 'metadata.jsonl'), 'w', encoding='utf-8') as meta:
            for t in (CallTranscript.objects.exclude(corrected_text='')
                      .select_related('call_log', 'cdr_call').order_by('pk')):
                audio, mime = load_job_audio(t)
                if audio is None:
                    continue
                ext = mimetypes.guess_extension(mime) or '.wav'
                name = f'{t.pk}{ext}'
                with open(os.path.join(audio_dir, name), 'wb') as f:
                    f.write(audio)
                meta.write(json.dumps({'audio': f'audio/{name}', 'text': t.corrected_text,
                                       'original': t.text, 'engine': t.engine},
                                      ensure_ascii=False) + '\n')
                written += 1
        self.stdout.write(f'exported {written} corrected transcripts to {out_dir}')
