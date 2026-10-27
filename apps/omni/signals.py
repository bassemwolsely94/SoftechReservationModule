"""
apps/omni/signals.py

Live ingestion into the unified timeline.

Channel records (WAMessage, CallLog) flow in on creation — the native
apps stay untouched. ERP records use attach_only emits: they enrich a
customer's ACTIVE conversation but never spawn one on their own.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.omni import services

logger = logging.getLogger('elrezeiky.omni')


@receiver(post_save, sender='whatsapp.WAMessage', dispatch_uid='omni_ingest_wa_message')
def on_wa_message(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        services.ingest_wa_message(instance)
    except Exception:
        logger.exception('omni: WAMessage ingestion failed for #%s', instance.pk)


@receiver(post_save, sender='social.SocialMessage', dispatch_uid='omni_ingest_social_message')
def on_social_message(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        services.ingest_social_message(instance)
    except Exception:
        logger.exception('omni: SocialMessage ingestion failed for #%s', instance.pk)


@receiver(post_save, sender='callcenter.CallLog', dispatch_uid='omni_ingest_call_log')
def on_call_log(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        services.ingest_call_log(instance)
    except Exception:
        logger.exception('omni: CallLog ingestion failed for #%s', instance.pk)


@receiver(post_save, sender='reservations.Reservation', dispatch_uid='omni_emit_reservation')
def on_reservation(sender, instance, created, **kwargs):
    """ERP exemplar: a new reservation appears in the customer's live timeline."""
    if not created:
        return
    services.emit(
        'erp_reservation',
        instance,
        customer=instance.customer,
        phone=getattr(instance, 'contact_phone', '') or '',
        summary=f'حجز جديد #{instance.pk} — {instance.item_label}',
        payload={'reservation_id': instance.pk, 'status': instance.status},
        attach_only=True,
    )
