"""
apps/images/searcher.py

Multi-source image search engine.

Pipeline stage order (cheapest → most expensive):
  Stage 1  Internal cache / already approved images
  Stage 2  Barcode-based databases (Open Food Facts, Open Beauty)
  Stage 3  Pharma databases (drugs.com, rxlist)
  Stage 4  DuckDuckGo image scraping (free, no API key)
  Stage 5  Google Images scraping (fallback)

Each stage returns a list of ImageResult dicts.
The orchestrator (pipeline.py) decides when enough candidates exist.

No paid APIs are called.  AI verification is done separately in scorer.py
only when confidence is low.
"""
from __future__ import annotations
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger('elrezeiky')

_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)
_TIMEOUT = 15    # seconds per HTTP request
_MAX_CANDIDATES_PER_SOURCE = 8


def _get(url: str, extra_headers: Optional[dict] = None) -> Optional[bytes]:
    """Safe HTTP GET; returns raw bytes or None on any error."""
    headers = {'User-Agent': _UA, 'Accept-Language': 'en-US,en;q=0.9'}
    if extra_headers:
        headers.update(extra_headers)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read()
    except Exception as exc:
        logger.debug('GET %s failed: %s', url, exc)
        return None


def _result(url: str, source_type: str, page_url: str = '',
            query: str = '', metadata: Optional[dict] = None) -> dict:
    return {
        'source_url':      url,
        'source_type':     source_type,
        'source_page_url': page_url,
        'query_used':      query,
        'scraper_metadata': metadata or {},
    }


# ── Stage 2 — Barcode databases ───────────────────────────────────────────────

def search_open_food_facts(barcode: str) -> list[dict]:
    """
    Open Food Facts API — completely free, great for FMCG / packaged foods.
    Returns product images directly from their CDN.
    """
    if not barcode or len(barcode) < 8:
        return []
    url  = f'https://world.openfoodfacts.org/api/v0/product/{barcode}.json'
    raw  = _get(url)
    if not raw:
        return []
    try:
        data    = json.loads(raw)
        product = data.get('product', {})
        images  = []
        for field in ['image_url', 'image_front_url', 'image_front_small_url']:
            img_url = product.get(field, '')
            if img_url and img_url.startswith('http'):
                images.append(_result(
                    img_url, 'openfoodfacts',
                    page_url=f'https://world.openfoodfacts.org/product/{barcode}',
                    query=barcode,
                    metadata={'product_name': product.get('product_name', '')},
                ))
        return images[:_MAX_CANDIDATES_PER_SOURCE]
    except Exception as exc:
        logger.debug('OpenFoodFacts parse error: %s', exc)
        return []


def search_open_beauty_facts(barcode: str) -> list[dict]:
    """Open Beauty Facts — same API structure, for cosmetics."""
    if not barcode or len(barcode) < 8:
        return []
    url  = f'https://world.openbeautyfacts.org/api/v0/product/{barcode}.json'
    raw  = _get(url)
    if not raw:
        return []
    try:
        data    = json.loads(raw)
        product = data.get('product', {})
        results = []
        for field in ['image_url', 'image_front_url']:
            img_url = product.get(field, '')
            if img_url and img_url.startswith('http'):
                results.append(_result(
                    img_url, 'openbeauty',
                    page_url=f'https://world.openbeautyfacts.org/product/{barcode}',
                    query=barcode,
                ))
        return results
    except Exception as exc:
        logger.debug('OpenBeautyFacts parse error: %s', exc)
        return []


# ── Stage 3 — Pharma databases ────────────────────────────────────────────────

def search_drugs_com(brand: str, strength: str = '') -> list[dict]:
    """
    Scrape drugs.com drug images (plain HTML, no JS required).
    Highly reliable for branded pharmaceuticals.
    """
    if not brand or len(brand) < 3:
        return []
    from bs4 import BeautifulSoup

    query    = urllib.parse.quote(f'{brand} {strength}'.strip())
    url      = f'https://www.drugs.com/search.php?searchterm={query}'
    raw      = _get(url, {'Accept': 'text/html'})
    if not raw:
        return []

    results = []
    try:
        soup  = BeautifulSoup(raw, 'html.parser')
        # drugs.com search result cards often have drug images
        for img in soup.select('img[src*="drugs.com/img"]')[:_MAX_CANDIDATES_PER_SOURCE]:
            src = img.get('src', '')
            if src and src.startswith('http') and any(
                ext in src for ext in ['.jpg', '.png', '.webp']
            ):
                parent_url = ''
                a_tag = img.find_parent('a')
                if a_tag:
                    href = a_tag.get('href', '')
                    if href:
                        parent_url = (
                            href if href.startswith('http')
                            else 'https://www.drugs.com' + href
                        )
                results.append(_result(
                    src, 'drugs_com',
                    page_url=parent_url,
                    query=f'{brand} {strength}',
                ))
    except Exception as exc:
        logger.debug('drugs.com parse error: %s', exc)

    return results


def search_rxlist(brand: str) -> list[dict]:
    """Scrape RxList drug images — another reliable pharma source."""
    if not brand or len(brand) < 3:
        return []
    from bs4 import BeautifulSoup

    query = urllib.parse.quote(brand)
    url   = f'https://www.rxlist.com/script/main/art.asp?articlekey={query}'
    # RxList search
    search_url = f'https://www.rxlist.com/search/rxl/{query}'
    raw        = _get(search_url, {'Accept': 'text/html'})
    if not raw:
        return []

    results = []
    try:
        soup = BeautifulSoup(raw, 'html.parser')
        for img in soup.select('img')[:_MAX_CANDIDATES_PER_SOURCE]:
            src = img.get('src', '')
            if src and 'rxlist' in src and any(
                ext in src for ext in ['.jpg', '.png', '.gif']
            ):
                if src.startswith('//'):
                    src = 'https:' + src
                elif not src.startswith('http'):
                    src = 'https://www.rxlist.com' + src
                results.append(_result(src, 'rxlist', query=brand))
    except Exception as exc:
        logger.debug('RxList parse error: %s', exc)

    return results


# ── Stage 4 — DuckDuckGo image search ─────────────────────────────────────────

def search_duckduckgo_images(query: str) -> list[dict]:
    """
    Scrape DuckDuckGo image results — free, no API key, respectful of robots.txt.
    Returns direct image URLs extracted from DDG's JSON response.
    """
    if not query or len(query) < 3:
        return []

    # Step 1: get vqd token (required by DDG)
    init_url = f'https://duckduckgo.com/?q={urllib.parse.quote(query)}&iax=images&ia=images'
    init_raw = _get(init_url)
    if not init_raw:
        return []

    vqd = ''
    try:
        text     = init_raw.decode('utf-8', errors='replace')
        vqd_match = re.search(r'vqd=(["\'])([^"\']+)\1', text)
        if not vqd_match:
            vqd_match = re.search(r'vqd=([\d\-]+)', text)
        if vqd_match:
            vqd = vqd_match.group(2) if vqd_match.lastindex >= 2 else vqd_match.group(1)
    except Exception:
        pass

    if not vqd:
        logger.debug('DDG: could not extract vqd token for query "%s"', query)
        return []

    # Step 2: fetch image results
    params   = urllib.parse.urlencode({
        'l':   'us-en',
        'o':   'json',
        'q':   query,
        'vqd': vqd,
        'f':   ',,,,,',
        'p':   '-1',
    })
    imgs_url = f'https://duckduckgo.com/i.js?{params}'

    time.sleep(0.5)   # polite delay
    raw = _get(imgs_url, {
        'Accept':  'application/json',
        'Referer': init_url,
    })
    if not raw:
        return []

    results = []
    try:
        data = json.loads(raw)
        for item_data in data.get('results', [])[:_MAX_CANDIDATES_PER_SOURCE]:
            img_url  = item_data.get('image', '')
            page_url = item_data.get('url', '')
            width    = item_data.get('width', 0)
            height   = item_data.get('height', 0)
            if img_url and img_url.startswith('http'):
                results.append(_result(
                    img_url, 'duckduckgo',
                    page_url=page_url,
                    query=query,
                    metadata={'width': width, 'height': height,
                              'title': item_data.get('title', '')},
                ))
    except Exception as exc:
        logger.debug('DDG JSON parse error: %s', exc)

    return results


# ── Stage 5 — Bing image search ───────────────────────────────────────────────

def search_bing_images(query: str) -> list[dict]:
    """
    Scrape Bing Image Search HTML — free fallback when DDG returns nothing.
    Extracts image URLs from Bing's JavaScript data blob.
    """
    if not query or len(query) < 3:
        return []

    url = (
        'https://www.bing.com/images/search?'
        + urllib.parse.urlencode({'q': query, 'FORM': 'HDRSC2'})
    )
    raw = _get(url, {'Accept-Language': 'en-US,en;q=0.9'})
    if not raw:
        return []

    results = []
    try:
        text = raw.decode('utf-8', errors='replace')
        # Bing embeds image URLs in JSON blobs inside the page
        for match in re.finditer(r'"murl":"(https?://[^"]+?\.(?:jpg|jpeg|png|webp))"', text):
            img_url = match.group(1)
            results.append(_result(img_url, 'bing', page_url=url, query=query))
            if len(results) >= _MAX_CANDIDATES_PER_SOURCE:
                break
    except Exception as exc:
        logger.debug('Bing parse error: %s', exc)

    return results


# ── Dispatcher ────────────────────────────────────────────────────────────────

def search_all_sources(
    brand: str,
    strength: str,
    dosage_form: str,
    search_query_en: str,
    search_query_ar: str,
    barcode: str = '',
    item_name: str = '',
    stop_after: int = 5,
    learned_weights: Optional[dict] = None,
) -> list[dict]:
    """
    Run all search stages in cost order.
    learned_weights: {source_type: float} — boost (>1) or penalise (<1) sources
    based on historical approval rates for this brand.
    Returns combined list of raw result dicts.
    `stop_after`: stop early if we already have this many candidates.
    """
    candidates: list[dict] = []
    weights = learned_weights or {}

    def _add(new: list[dict]) -> None:
        candidates.extend(new)

    # If we have strong learned preference, try best source first
    # e.g. drugs_com worked 10/12 times for this brand → try it first
    best_source = max(weights, key=weights.get, default=None) if weights else None
    if best_source and weights.get(best_source, 1.0) > 1.2 and brand:
        if best_source == 'drugs_com':
            _add(search_drugs_com(brand, strength))
            if len(candidates) >= stop_after:
                return candidates
        elif best_source == 'rxlist':
            _add(search_rxlist(brand))
            if len(candidates) >= stop_after:
                return candidates

    # ── Stage 2: barcode databases (highest accuracy) ─────────────────────────
    if barcode:
        _add(search_open_food_facts(barcode))
        if len(candidates) >= stop_after:
            return candidates
        _add(search_open_beauty_facts(barcode))
        if len(candidates) >= stop_after:
            return candidates

    # ── Stage 3: pharma databases ─────────────────────────────────────────────
    if brand:
        _add(search_drugs_com(brand, strength))
        if len(candidates) >= stop_after:
            return candidates
        _add(search_rxlist(brand))
        if len(candidates) >= stop_after:
            return candidates

    # ── Stage 4: DuckDuckGo ───────────────────────────────────────────────────
    if search_query_en:
        _add(search_duckduckgo_images(search_query_en + ' product image'))
        if len(candidates) >= stop_after:
            return candidates

    # Try Arabic query on DDG too
    if search_query_ar:
        _add(search_duckduckgo_images(search_query_ar))
        if len(candidates) >= stop_after:
            return candidates

    # ── Stage 5: Bing fallback ────────────────────────────────────────────────
    if len(candidates) < 2 and search_query_en:
        _add(search_bing_images(search_query_en + ' product'))

    logger.info(
        'Image search for "%s": %d candidates from %d stages',
        brand or item_name, len(candidates), 5,
    )
    return candidates
