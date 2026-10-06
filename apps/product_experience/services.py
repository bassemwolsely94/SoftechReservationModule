"""
apps/product_experience/services.py

Business logic layer for the Product Experience Platform.
Handles: media processing, slug generation, availability computation,
         interaction tracking, share card generation.
"""
import io
import re
import unicodedata
import logging

from django.utils import timezone
from django.utils.text import slugify
from django.core.files.base import ContentFile
from django.db import transaction

logger = logging.getLogger('elrezeiky.product_experience')

# ── Arabic ↔ English transliteration ─────────────────────────────────────────

def transliterate_arabic(text: str) -> str:
    """Convert Arabic text to Latin characters for slug generation."""
    if not text:
        return ''
    _MAP = {
        'ا': 'a', 'أ': 'a', 'إ': 'i', 'آ': 'aa', 'ب': 'b', 'ت': 't', 'ث': 'th',
        'ج': 'j', 'ح': 'h', 'خ': 'kh', 'د': 'd', 'ذ': 'th', 'ر': 'r', 'ز': 'z',
        'س': 's', 'ش': 'sh', 'ص': 's', 'ض': 'd', 'ط': 't', 'ظ': 'z', 'ع': 'a',
        'غ': 'gh', 'ف': 'f', 'ق': 'q', 'ك': 'k', 'ل': 'l', 'م': 'm', 'ن': 'n',
        'ه': 'h', 'و': 'w', 'ي': 'y', 'ى': 'a', 'ة': 'a', 'ء': '', 'ئ': 'y', 'ؤ': 'w',
        '،': '', '؟': '', '؛': '', '«': '', '»': '',
    }
    result = ''.join(_MAP.get(c, c) for c in text)
    result = unicodedata.normalize('NFKD', result)
    result = re.sub(r'[^\w\s-]', '', result)
    result = re.sub(r'\s+', '-', result.strip())
    result = re.sub(r'-+', '-', result)
    return result.lower()


# ── Slug generation ───────────────────────────────────────────────────────────

def generate_product_slug(item) -> str:
    """
    Generate a unique SEO-friendly slug for an item.
    Strategy: transliterate Arabic name + '-' + softech_id
    Falls back to softech_id if name is empty.
    """
    from .models import ProductSEO

    base = ''
    if item.name:
        base = transliterate_arabic(item.name)
        if not base:  # name is all-Arabic, transliteration returned empty
            base = item.name  # use Django's slugify with allow_unicode
    if not base and item.name_scientific:
        base = slugify(item.name_scientific)
    if not base:
        base = f'product-{item.softech_id}'

    candidate = slugify(f'{base}-{item.softech_id}', allow_unicode=True)[:200]
    # Ensure uniqueness
    slug = candidate
    counter = 1
    while ProductSEO.objects.filter(slug=slug).exclude(item=item).exists():
        slug = f'{candidate[:190]}-{counter}'
        counter += 1
    return slug


# ── SEO auto-generation ───────────────────────────────────────────────────────

def ensure_product_seo(item):
    """Get or create ProductSEO for an item, auto-generating slug and titles."""
    from .models import ProductSEO

    seo, created = ProductSEO.objects.get_or_create(
        item=item,
        defaults={'slug': generate_product_slug(item)},
    )
    if created or not seo.slug:
        seo.slug = generate_product_slug(item)
        # Auto-generate titles from item fields
        if not seo.title_ar:
            seo.title_ar = item.name or item.softech_id
        if not seo.title_en and item.name_scientific:
            seo.title_en = item.name_scientific
        if not seo.description_ar and item.effect_name_ar:
            seo.description_ar = f'{item.name} — {item.effect_name_ar}'
        seo.save()
    return seo


# ── Content auto-generation ───────────────────────────────────────────────────

def ensure_product_content(item):
    """Get or create ProductContent, seeding from ERP data if empty."""
    from .models import ProductContent

    content, created = ProductContent.objects.get_or_create(item=item)
    if created:
        content.display_name_ar = item.name or ''
        content.display_name_en = item.name_scientific or ''
        # Seed keywords from item fields
        kw_parts = [item.name, item.name_scientific, item.active_ingredients,
                    item.family_name_ar, item.effect_name_ar]
        content.keywords = ', '.join(p for p in kw_parts if p)
        content.save()
    return content


# ── Attribute auto-generation ─────────────────────────────────────────────────

def ensure_product_attribute(item):
    """Get or create ProductAttribute, seeding from ERP data if empty."""
    from .models import ProductAttribute

    attr, created = ProductAttribute.objects.get_or_create(item=item)
    if created and item.requires_fridge:
        attr.temperature_storage = 'refrigerated'
        attr.save(update_fields=['temperature_storage'])
    return attr


# ── Experience tracker ────────────────────────────────────────────────────────

def get_or_create_experience(item):
    """Get or create ProductExperience for an item."""
    from .models import ProductExperience

    exp, _ = ProductExperience.objects.get_or_create(item=item)
    return exp


def track_interaction(item, interaction_type: str):
    """
    Increment an interaction counter on ProductExperience.
    Valid types: views, shares, wishlist_adds, reservations, refills, call_requests
    """
    valid_types = {'views', 'shares', 'wishlist_adds', 'reservations', 'refills', 'call_requests'}
    if interaction_type not in valid_types:
        logger.warning(f'[ProductExperience] Unknown interaction type: {interaction_type}')
        return

    exp = get_or_create_experience(item)
    exp.increment(interaction_type)
    logger.debug(f'[ProductExperience] {item.softech_id}.{interaction_type} → {getattr(exp, interaction_type)}')


# ── Thumbnail generation ──────────────────────────────────────────────────────

def generate_thumbnail(media_instance, size=(400, 400)):
    """
    Generate a JPEG thumbnail from an image media file.
    Stores it on media_instance.thumbnail field.
    Returns True on success, False on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning('[ProductMedia] Pillow not installed — skipping thumbnail generation')
        return False

    if media_instance.media_type != 'image' or not media_instance.file:
        return False
    if media_instance.thumbnail:
        return True  # already has thumbnail

    try:
        media_instance.file.seek(0)
        img = Image.open(media_instance.file)
        img.thumbnail(size, Image.LANCZOS)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
        elif img.mode == 'RGBA':
            # Replace alpha with white background
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg

        thumb_io = io.BytesIO()
        img.save(thumb_io, format='JPEG', quality=85, optimize=True)
        thumb_io.seek(0)

        ext = 'jpg'
        fname = f'thumb_{media_instance.pk or "new"}.{ext}'
        media_instance.thumbnail.save(fname, ContentFile(thumb_io.read()), save=False)
        return True
    except Exception as e:
        logger.error(f'[ProductMedia] Thumbnail generation failed: {e}')
        return False


def generate_webp(media_instance):
    """
    Generate WebP version for web optimization.
    Returns ContentFile or None.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    if media_instance.media_type != 'image' or not media_instance.file:
        return None

    try:
        media_instance.file.seek(0)
        img = Image.open(media_instance.file)
        if img.mode not in ('RGB',):
            img = img.convert('RGB')
        webp_io = io.BytesIO()
        img.save(webp_io, format='WEBP', quality=85, method=6)
        webp_io.seek(0)
        return ContentFile(webp_io.read())
    except Exception as e:
        logger.error(f'[ProductMedia] WebP generation failed: {e}')
        return None


# ── Availability computation ──────────────────────────────────────────────────

_AVAILABLE_THRESHOLD = 5   # qty > 5 → available
_LIMITED_THRESHOLD   = 1   # 0 < qty <= 5 → limited


def compute_availability_status(qty) -> str:
    """
    Convert raw quantity to customer-facing status.
    NEVER expose quantities. Returns available/limited/unavailable.
    """
    try:
        qty_f = float(qty)
    except (TypeError, ValueError):
        return 'unavailable'
    if qty_f > _AVAILABLE_THRESHOLD:
        return 'available'
    if qty_f > 0:
        return 'limited'
    return 'unavailable'


def get_item_availability(item, branch=None):
    """
    Compute availability for an item across branches (or a specific branch).
    Uses catalog.ItemStock — never exposes raw quantities.
    Returns list of dicts: [{branch_id, branch_name, status}]
    """
    from apps.catalog.models import ItemStock

    qs = ItemStock.objects.filter(item=item).select_related('branch')
    if branch:
        qs = qs.filter(branch=branch)

    results = []
    for stock in qs:
        status = compute_availability_status(stock.quantity_on_hand)
        results.append({
            'branch_id':   stock.branch_id,
            'branch_name': stock.branch.name if stock.branch else '',
            'branch_name_ar': getattr(stock.branch, 'name_ar', '') if stock.branch else '',
            'status':      status,
        })

    # Update cache
    if results:
        _update_availability_cache(item, results)

    return results


def _update_availability_cache(item, availability_list):
    """Update ProductAvailabilityCache in background."""
    from .models import ProductAvailabilityCache
    from apps.branches.models import Branch

    branch_map = {b.id: b for b in Branch.objects.all()}
    for row in availability_list:
        branch = branch_map.get(row['branch_id'])
        if branch:
            ProductAvailabilityCache.objects.update_or_create(
                item=item, branch=branch,
                defaults={'status': row['status']},
            )


def get_item_overall_availability(item) -> str:
    """
    Single availability status across all branches.
    available if any branch has stock, else limited if any has limited, else unavailable.
    """
    from apps.catalog.models import ItemStock

    statuses = set()
    for stock in ItemStock.objects.filter(item=item):
        statuses.add(compute_availability_status(stock.quantity_on_hand))

    if 'available' in statuses:
        return 'available'
    if 'limited' in statuses:
        return 'limited'
    return 'unavailable'


# ── Share card generator ──────────────────────────────────────────────────────

def generate_share_card(item) -> dict:
    """
    Generate WhatsApp / social share card data.
    Returns structured data for frontend rendering.
    """
    content = getattr(item, 'content', None)
    media_qs = item.media.filter(is_primary=True, approved=True)
    primary_media = media_qs.first()
    availability = get_item_overall_availability(item)

    name_ar = (content.display_name_ar if content else None) or item.name
    short_desc = (content.short_description if content else '') or ''

    avail_labels = {
        'available': 'متاح ✅',
        'limited': 'كميات محدودة ⚠️',
        'unavailable': 'غير متاح ❌',
    }

    adherence_icons = []
    if content and content.adherence_icons:
        adherence_icons = content.adherence_icons

    whatsapp_text = (
        f'*{name_ar}*\n'
        + (f'_{short_desc}_\n' if short_desc else '')
        + f'التوافر: {avail_labels.get(availability, "—")}\n'
        + (f'\n{" ".join(i.get("icon","") for i in adherence_icons)}' if adherence_icons else '')
    ).strip()

    return {
        'name_ar':         name_ar,
        'name_en':         (content.display_name_en if content else None) or item.name_scientific or '',
        'short_description': short_desc,
        'availability':    availability,
        'availability_label': avail_labels.get(availability, ''),
        'image_url':       primary_media.url if primary_media else '',
        'thumb_url':       primary_media.thumb_url if primary_media else '',
        'adherence_icons': adherence_icons,
        'whatsapp_text':   whatsapp_text,
        'softech_id':      item.softech_id,
        'barcode':         item.barcode or '',
    }


# ── Bulk initialize helpers ───────────────────────────────────────────────────

def initialize_product_experience(item):
    """
    Ensure all experience records exist for an item.
    Called when an item is first accessed or on demand.
    """
    ensure_product_content(item)
    ensure_product_attribute(item)
    ensure_product_seo(item)
    get_or_create_experience(item)
