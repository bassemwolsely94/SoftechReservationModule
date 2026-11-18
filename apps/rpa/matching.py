"""Match issue-sheet item codes to catalog items (read-only)."""
import re


def normalise_code(value) -> str:
    """'52.0' -> '52', ' 52 ' -> '52'; digits only."""
    text = str(value if value is not None else '').strip()
    if text.endswith('.0'):
        text = text[:-2]
    return re.sub(r'\D', '', text)


def match_items(codes) -> dict:
    """{softech_id: Item} for the codes that exist in the catalog."""
    from apps.catalog.item_columns import load_items
    return load_items(codes=codes)
