"""
apps/usage_print/slip.py — what goes on the printed slip, as an ordered list of blocks.

Header/footer content lives in SystemSetting (keys below) so it changes without a release; an empty
value hides that block. New blocks (ads, fridge storage per item, return rules, more QR codes) are
added to SLIP_SETTINGS + footer_blocks() without touching the confirm/print workflow.
"""
import base64
import io

from apps.config.models import SystemSetting
from apps.config.services import get_setting, invalidate_setting

from .models import UsageSheetLine as L

# key → (label, default)
SLIP_SETTINGS = {
    'usage_print.footer_text': ('نص أسفل الورقة', 'استشر الصيدلي عند أي استفسار — لا توقف الدواء بدون استشارة الطبيب'),
    'usage_print.hotline':     ('الخط الساخن', ''),
    'usage_print.whatsapp':    ('رقم واتساب', ''),
    'usage_print.qr_url':      ('رابط QR (الموقع / المتجر)', ''),
    'usage_print.qr_caption':  ('نص تحت QR', ''),
}


def slip_settings():
    return {k: get_setting(k, default=d) for k, (_l, d) in SLIP_SETTINGS.items()}


def save_slip_settings(values):
    """Upsert the editable keys only; returns {key: [old, new]} for what changed."""
    changed = {}
    current = slip_settings()
    for key, (label, _d) in SLIP_SETTINGS.items():
        if key not in values:
            continue
        new = str(values[key] or '').strip()[:500]
        if new == current[key]:
            continue
        SystemSetting.objects.update_or_create(key=key, defaults={'label': label, 'value': new,
                                                                  'value_type': 'string', 'category': 'general'})
        invalidate_setting(key)
        changed[key] = [current[key], new]
    return changed


def _qr_png(url):
    try:
        import qrcode
        img = qrcode.QRCode(box_size=4, border=1)
        img.add_data(url)
        img.make(fit=True)
        buf = io.BytesIO()
        img.make_image().save(buf, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ''


def footer_blocks(conf):
    blocks = []
    if conf['usage_print.footer_text']:
        blocks.append({'type': 'text', 'text': conf['usage_print.footer_text']})
    contact = [f'☎ {conf["usage_print.hotline"]}' if conf['usage_print.hotline'] else '',
               f'واتساب {conf["usage_print.whatsapp"]}' if conf['usage_print.whatsapp'] else '']
    if any(contact):
        blocks.append({'type': 'contact', 'text': '   '.join(c for c in contact if c)})
    if conf['usage_print.qr_url']:
        img = _qr_png(conf['usage_print.qr_url'])
        if img:
            blocks.append({'type': 'qr', 'image': img, 'caption': conf['usage_print.qr_caption']})
    return blocks


def build_slip(sheet, layout):
    branch = sheet.branch
    return {
        'layout': layout,
        'pharmacy': get_setting('pharmacy_name', default='صيدليات الرزيقي'),
        'branch': getattr(branch, 'name_ar', '') or getattr(branch, 'name', ''),
        'invoice': sheet.docnumber,
        'date': sheet.docdate.isoformat(),
        'patient_name': sheet.patient_name,
        'items': [{'name': ln.item_name, 'text': ln.text}
                  for ln in sheet.lines.filter(status=L.STATUS_CONFIRMED).order_by('sort_order', 'id')],
        'footer_blocks': footer_blocks(slip_settings()),
    }
