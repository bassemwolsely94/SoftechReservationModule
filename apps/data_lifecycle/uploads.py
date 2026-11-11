"""
Data lifecycle Stage 4: shrink new photos on upload (design: growth control starts at the door).

Only the fields listed here are touched. Invoice scans and OCR sample images are evidence and training data, so
they never appear here. A failure never blocks an upload: the original is stored as is.
"""
import logging

from django.apps import apps
from django.core.files.base import ContentFile
from django.db.models.signals import pre_save

from core.upload_safety import shrink_image

logger = logging.getLogger(__name__)

SHRINK_LONGEST_SIDE = {
    'pos_orders.SoftechSalesOrder.prescription_image': 2000,
    'usage_print.UsageSheet.prescription_image': 2000,
    'callcenter.CallLog.prescription_image': 2000,
    'reservations.Reservation.image': 2000,
    'reservations.ReservationImage.image': 2000,
    'whatsapp.WAMediaFile.local_file': 2000,
    'callcenter.CallLogAttachment.file': 2000,
    'callcenter.CaseEvent.attachment': 2000,
    'notifications.ChatterMessage.attachment': 1600,
    'reservations.ReservationActivity.attachment': 1600,
    'transfers.TransferRequestMessage.attachment': 1600,
    'tasks.TaskAttachment.file': 1600,
    'delivery.DeliveryOrder.pod_photo': 1600,
}


def _fields_by_model():
    out = {}
    for key, side in SHRINK_LONGEST_SIDE.items():
        label, field = key.rsplit('.', 1)
        out.setdefault(label, []).append((field, side))
    return out


def _shrink_new_uploads(sender, instance, raw=False, **kwargs):
    if raw:
        return
    for name, side in _fields_by_model().get(sender._meta.label, ()):
        try:
            f = getattr(instance, name, None)
            if not f or getattr(f, '_committed', True):
                continue
            data = f.read()
            f.seek(0)
            new = shrink_image(data, side)
            if new is not None:
                f.file = ContentFile(new, name=f.name)
        except Exception:
            # model label and pk only: a file name can carry a patient's name
            logger.warning('photo shrink skipped for %s pk=%s', sender._meta.label, instance.pk, exc_info=False)


def connect():
    for label in _fields_by_model():
        pre_save.connect(_shrink_new_uploads, sender=apps.get_model(label),
                         dispatch_uid=f'lifecycle_shrink_{label}')
