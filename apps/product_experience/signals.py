"""
apps/product_experience/signals.py

Post-save signal: auto-generate thumbnail when a ProductMedia image is saved.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
import logging

logger = logging.getLogger('elrezeiky.product_experience')


@receiver(post_save, sender='product_experience.ProductMedia')
def auto_generate_thumbnail(sender, instance, created, **kwargs):
    """Generate thumbnail after a new image is saved."""
    if instance.media_type == 'image' and instance.file and not instance.thumbnail:
        from .services import generate_thumbnail
        if generate_thumbnail(instance):
            # Save only thumbnail field to avoid recursion
            type(instance).objects.filter(pk=instance.pk).update(thumbnail=instance.thumbnail)
            logger.debug(f'[ProductMedia] Thumbnail generated for pk={instance.pk}')
