"""
apps/vision — the home of ElRezeiky's in-house optical-recognition engine.

Phase 1 (this module): the OcrSample corpus. Every OCR / voice event across sales
(Rx, voice) and purchasing (shortage lists, supplier invoices) is recorded here with
the source media, the engine's raw n-best readings, and — as the human confirms each
line — the ground-truth text + item. This is the OWNED, labelled dataset that:

  • improves matching immediately (feeds the existing learn_alias flywheel), and
  • is the training set for the future in-house recognizer (printed + handwriting,
    Arabic + English), run in parallel with Gemini.

Recording is best-effort and NEVER blocks a sale or a workflow.
"""
from django.conf import settings
from django.db import models


class OcrSample(models.Model):
    MODULE_CHOICES = [
        ('pos_rx',              'روشتة (نقطة البيع)'),
        ('pos_voice',           'صوت (نقطة البيع)'),
        ('purchasing_shortage', 'نواقص السوق'),
        ('purchasing_invoice',  'فاتورة مورّد'),
        ('other',               'أخرى'),
    ]
    ENGINE_CHOICES = [
        ('gemini',    'Gemini'),
        ('easyocr',   'EasyOCR (داخلي)'),
        ('tesseract', 'Tesseract (داخلي)'),
        ('inhouse',   'المحرك الداخلي'),
        ('paddle',    'PaddleOCR'),
    ]
    MEDIA_CHOICES = [('image', 'صورة'), ('audio', 'صوت')]

    module     = models.CharField(max_length=24, choices=MODULE_CHOICES, db_index=True)
    engine     = models.CharField(max_length=16, choices=ENGINE_CHOICES, default='gemini', db_index=True)
    media_type = models.CharField(max_length=8, choices=MEDIA_CHOICES, default='image')

    image = models.ImageField(upload_to='vision/ocr/%Y/%m/', null=True, blank=True)
    audio = models.FileField(upload_to='vision/voice/%Y/%m/', null=True, blank=True)

    # what the WINNING recogniser produced (n-best): [{readings:[...], strength, qty}, ...]
    raw_readings = models.JSONField(default=list, blank=True)
    # per-engine readings when engines ran in PARALLEL: {engine: [{readings,strength,qty}]}
    # — the raw material for the in-house-vs-Gemini accuracy comparison.
    engine_readings = models.JSONField(default=dict, blank=True)
    # ground truth accumulated as the human confirms lines:
    #   [{reading, item_id, softech_id, name, ts}, ...]
    confirmations = models.JSONField(default=list, blank=True)

    branch     = models.ForeignKey('branches.Branch', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    source_ref = models.CharField(max_length=64, blank=True)   # order id / list id / invoice id
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'عيّنة OCR'
        verbose_name_plural = 'عيّنات OCR'
        indexes = [models.Index(fields=['module', 'created_at'])]
        ordering = ['-created_at']

    def __str__(self):
        return f'OcrSample#{self.pk} [{self.module}/{self.engine}] {len(self.confirmations)} conf'

    @property
    def is_labelled(self):
        return bool(self.confirmations)


def record_sample(*, module, media_type='image', engine='gemini', image=None, audio=None,
                  raw_readings=None, branch=None, user=None, source_ref=''):
    """Create an OcrSample. Best-effort — returns the sample or None; never raises."""
    try:
        return OcrSample.objects.create(
            module=module, media_type=media_type, engine=engine,
            image=image if media_type == 'image' else None,
            audio=audio if media_type == 'audio' else None,
            raw_readings=raw_readings or [],
            branch=branch if getattr(branch, 'pk', None) else None,
            user=user if getattr(user, 'pk', None) else None,
            source_ref=str(source_ref or ''),
        )
    except Exception:
        return None


def add_confirmation(sample_id, *, reading, item):
    """Append a human confirmation (ground truth) to a sample. Best-effort → bool."""
    if not sample_id or item is None:
        return False
    try:
        s = OcrSample.objects.filter(pk=sample_id).first()
        if not s:
            return False
        from django.utils import timezone
        s.confirmations = (s.confirmations or []) + [{
            'reading': str(reading or ''),
            'item_id': item.id,
            'softech_id': item.softech_id,
            'name': item.name,
            'ts': timezone.now().isoformat(),
        }]
        s.save(update_fields=['confirmations'])
        return True
    except Exception:
        return False
