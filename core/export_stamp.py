"""
Stamp an exported Excel / Word file (OOXML zip) with who took it, from where and when (N5).

Files leave the company (suppliers, insurers), so the stamp holds only the export id, username,
time, device public_id and zone. The IP address and the device name stay in the export_taken
audit row, found by the export id.

Only the package metadata is touched: docProps/core.xml (creator, last modified by, description,
keywords), docProps/custom.xml (ElR-* properties), plus the custom-properties relationship and
content-type override when they are missing. Every other zip member is copied byte for byte.
A non-zip or malformed package raises ValueError.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, fields, replace
from xml.sax.saxutils import escape, quoteattr

NS = {
    'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
    'dcmitype': 'http://purl.org/dc/dcmitype/',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
}
for _prefix, _uri in NS.items():
    ET.register_namespace(_prefix, _uri)

CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
CUSTOM_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
VT_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
CUSTOM_REL_TYPE = ('http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                   'custom-properties')
CORE_REL_TYPE = ('http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
                 'core-properties')
CUSTOM_CT = 'application/vnd.openxmlformats-officedocument.custom-properties+xml'
CORE_CT = 'application/vnd.openxmlformats-package.core-properties+xml'
# the fixed FMTID every custom property carries (ECMA-376 part 1, 22.3.2.2)
FMTID = '{D5CDD505-2E9C-101B-9397-08002B2CF9AE}'

CONTENT_TYPES = '[Content_Types].xml'
ROOT_RELS = '_rels/.rels'
CORE = 'docProps/core.xml'
CUSTOM = 'docProps/custom.xml'


@dataclass(frozen=True)
class ExportMark:
    export_id: str
    username: str
    at: str          # ISO, Africa/Cairo
    device: str      # the device public_id only: a device name carries the employee's name
    zone: str


_XML_BAD = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _clean(mark):
    """The mark with XML 1.0 control characters removed from every value (a bad username or
    device name must not make an invalid core.xml / custom.xml)."""
    return replace(mark, **{f.name: _XML_BAD.sub('', str(getattr(mark, f.name) or ''))
                            for f in fields(mark)})


def description(mark):
    return f'تصدير {mark.export_id} — {mark.username} — {mark.at} — {mark.device} — {mark.zone}'


def _core_xml(original, mark):
    if original is None:
        root = ET.Element(f'{{{NS["cp"]}}}coreProperties')
    else:
        root = ET.fromstring(original)  # nosec B314 — our own view's export, not an upload
    values = {
        ('dc', 'creator'): mark.username,
        ('cp', 'lastModifiedBy'): mark.username,
        ('dc', 'description'): description(mark),
        ('cp', 'keywords'): mark.export_id,
    }
    for (prefix, name), value in values.items():
        tag = f'{{{NS[prefix]}}}{name}'
        el = root.find(tag)
        if el is None:
            el = ET.SubElement(root, tag)
        for child in list(el):          # keywords may hold <cp:value> children
            el.remove(child)
        el.text = value
    return ET.tostring(root, encoding='UTF-8', xml_declaration=True)


def _custom_xml(mark):
    props = (('ElR-ExportId', mark.export_id), ('ElR-User', mark.username), ('ElR-At', mark.at),
             ('ElR-Device', mark.device), ('ElR-Zone', mark.zone))
    body = ''.join(
        f'<property fmtid="{FMTID}" pid="{pid}" name={quoteattr(name)}>'
        f'<vt:lpwstr>{escape(str(value or ""))}</vt:lpwstr></property>'
        for pid, (name, value) in enumerate(props, start=2))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Properties xmlns="{CUSTOM_NS}" xmlns:vt="{VT_NS}">{body}</Properties>'
            ).encode('utf-8')


def _insert_before_close(xml_bytes, close_tag, fragment):
    """Insert `fragment` before the last `</...close_tag>`: the rest of the part is left as it was
    (its namespace prefixes too, which ElementTree would rename)."""
    text = xml_bytes.decode('utf-8')
    matches = list(re.finditer(rf'</(?:[\w.-]+:)?{close_tag}\s*>', text))
    if not matches:
        raise ValueError(f'no closing {close_tag}')
    at = matches[-1].start()
    return (text[:at] + fragment + text[at:]).encode('utf-8')


def _content_types(xml_bytes, add_core):
    root = ET.fromstring(xml_bytes)  # nosec B314 — our own view's export, not an upload
    parts = {el.get('PartName') for el in root.iter(f'{{{CT_NS}}}Override')}
    out = xml_bytes
    if '/' + CUSTOM not in parts:
        out = _insert_before_close(out, 'Types',
                                   f'<Override PartName="/{CUSTOM}" ContentType="{CUSTOM_CT}"/>')
    if add_core and '/' + CORE not in parts:
        out = _insert_before_close(out, 'Types',
                                   f'<Override PartName="/{CORE}" ContentType="{CORE_CT}"/>')
    return out


def _root_rels(xml_bytes, add_core):
    root = ET.fromstring(xml_bytes)  # nosec B314 — our own view's export, not an upload
    rels = list(root.iter(f'{{{REL_NS}}}Relationship'))
    types = {el.get('Type') for el in rels}
    ids = {el.get('Id') for el in rels}

    def free_id(base):
        n = 1
        while f'{base}{n}' in ids:
            n += 1
        ids.add(f'{base}{n}')
        return f'{base}{n}'

    out = xml_bytes
    if CUSTOM_REL_TYPE not in types:
        out = _insert_before_close(out, 'Relationships',
                                   f'<Relationship Id="{free_id("rIdElR")}" '
                                   f'Type="{CUSTOM_REL_TYPE}" Target="{CUSTOM}"/>')
    if add_core and CORE_REL_TYPE not in types:
        out = _insert_before_close(out, 'Relationships',
                                   f'<Relationship Id="{free_id("rIdElR")}" '
                                   f'Type="{CORE_REL_TYPE}" Target="{CORE}"/>')
    return out


def stamp_ooxml(content: bytes, mark: ExportMark) -> bytes:
    mark = _clean(mark)
    try:
        zin = zipfile.ZipFile(io.BytesIO(content))
        names = zin.namelist()
        if CONTENT_TYPES not in names or ROOT_RELS not in names:
            raise ValueError('not an OOXML package')
        has_core = CORE in names
        replaced = {
            CORE: _core_xml(zin.read(CORE) if has_core else None, mark),
            CUSTOM: _custom_xml(mark),
            CONTENT_TYPES: _content_types(zin.read(CONTENT_TYPES), add_core=not has_core),
            ROOT_RELS: _root_rels(zin.read(ROOT_RELS), add_core=not has_core),
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.filename in replaced:
                    zout.writestr(info, replaced.pop(info.filename))
                else:
                    zout.writestr(info, zin.read(info))
            for name, data in replaced.items():          # core / custom parts that were missing
                zout.writestr(name, data)
        return buf.getvalue()
    except ValueError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError, KeyError, OSError,
            EOFError, UnicodeDecodeError, NotImplementedError, RuntimeError) as exc:
        raise ValueError(f'malformed OOXML package: {exc}') from exc
