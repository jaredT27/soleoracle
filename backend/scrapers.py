"""SoleOracle scrapers v4 — RSS-based extraction + Nike SNKRS direct calendar."""
import json, re, asyncio, logging, traceback
from datetime import datetime, timedelta
from typing import Optional
from xml.etree import ElementTree as ET
import httpx
from bs4 import BeautifulSoup
from models import SessionLocal, SneakerDrop, ProductionLeak, ScraperLog, PortfolioItem, PortfolioSnapshot
from oracle import estimate_production

logger = logging.getLogger("soleoracle.scrapers")
logging.basicConfig(level=logging.INFO)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

NIKE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Upgrade-Insecure-Requests": "1",
}

# Non-footwear subtitle keywords — if subtitle exists and contains none of the
# footwear keywords, the item is skipped
FOOTWEAR_SUBTITLE_KEYWORDS = ["shoes", "trail", "basketball", "sneaker", "boot", "cleat", "slide", "sandal", "mule"]

# Kids/baby size indicators to skip
KIDS_SUBTITLE_KEYWORDS = ["big kids", "little kids", "toddler", "baby", "preschool", "infant", "grade school", "gs)"]


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"\$\s?[\d,]+(?:\.\d{2})?", text.replace(",", ""))
    return float(m.group(1)) if m else None

def _parse_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    text = text.strip()
    for fmt in ["%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%B %d %Y"]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    m = re.search(r"(\w+ \d{1,2},?\s*\d{4})", text)
    if m:
        for fmt in ["%B %d, %Y", "%B %d %Y"]:
            try:
                return datetime.strptime(m.group(1).replace(",", ", "), fmt)
            except ValueError:
                continue
    return None

def _detect_brand(name: str) -> str:
    nl = name.lower()
    if any(x in nl for x in ["jordan", " aj ", "jumpman"]):
        return "Jordan"
    if "adidas" in nl or "yeezy" in nl or "sp5der" in nl:
        return "adidas"
    if "new balance" in nl:
        return "New Balance"
    if "puma" in nl:
        return "Puma"
    if any(x in nl for x in ["converse", "cons "]):
        return "Converse"
    if "asics" in nl:
        return "ASICS"
    if "reebok" in nl:
        return "Reebok"
    if "saucony" in nl:
        return "Saucony"
    if "hoka" in nl:
        return "HOKA"
    return "Nike"

def _classify_rarity(production: Optional[int]) -> str:
    if production is None:
        return "Unknown"
    if production <= 5000:
        return "Ultra-Rare"
    if production <= 25000:
        return "Limited"
    if production <= 100000:
        return "Semi-Limited"
    return "Mass Release"

def _compute_heat_index(production=None, hype=5.0, resale_mult=1.0, velocity=5.0) -> dict:
    if production is None:
        scarcity = 5.0
    elif production <= 1000:
        scarcity = 10.0
    elif production <= 5000:
        scarcity = 9.0
    elif production <= 15000:
        scarcity = 8.0
    elif production <= 25000:
        scarcity = 7.0
    elif production <= 50000:
        scarcity = 5.5
    elif production <= 100000:
        scarcity = 4.0
    else:
        scarcity = 2.0
    resale_score = min(10.0, max(0.0, (resale_mult - 1.0) * 5.0 + 3.0)) if resale_mult > 0 else 3.0
    heat = round(0.40 * scarcity + 0.25 * hype + 0.20 * resale_score + 0.15 * velocity, 1)
    return {"heat_index": min(10.0, max(0.0, heat)), "scarcity_score": round(scarcity, 1),
            "hype_score": round(hype, 1), "resale_multiple": round(resale_mult, 2),
            "velocity_score": round(velocity, 1)}

def _is_sneaker(name: str) -> bool:
    nl = name.lower()
    sneaker_keywords = [
        'nike', 'jordan', 'air ', 'dunk', 'max', 'adidas', 'yeezy', 'new balance',
        'converse', 'asics', 'puma', 'reebok', 'kobe', 'lebron', 'sb ', 'force 1',
        'foamposite', 'kyrie', 'kd ', 'ja ', 'tatum', 'boost', 'ultra boost',
        'gel-', 'saucony', 'hoka', 'retro', 'pegasus', 'vapormax', 'air max',
    ]
    return any(kw in nl for kw in sneaker_keywords)

# RSS article-level junk filter — skip obvious non-product articles
_JUNK_PHRASES = [
    "best releases", "here's a look", "where to buy", "official images",
    "first look", "everything you need", "top 10", "ranking", "roundup",
    "weekly recap", "month in review", "buying guide", "how to style",
]

def _is_junk_article(title: str) -> bool:
    """Return True if title looks like a listicle / editorial rather than a product page."""
    if len(title) > 100:
        return True
    tl = title.lower()
    return any(phrase in tl for phrase in _JUNK_PHRASES)


# ═══════════════════════════════════════════════
# Nike SNKRS Launch Calendar Scraper (NEW)
# ═══════════════════════════════════════════════
async def scrape_nike_snkrs() -> list[dict]:
    """Fetch upcoming Nike SNKRS drops from the launch calendar page via __NEXT_DATA__."""
    drops = []
    url = "https://www.nike.com/launch/upcoming"
    try:
        async with httpx.AsyncClient(headers=NIKE_HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Nike SNKRS returned HTTP {resp.status_code}")
                return drops

            html = resp.text
            nd_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not nd_match:
                logger.warning("Nike SNKRS: __NEXT_DATA__ not found in page")
                return drops

            try:
                data = json.loads(nd_match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(f"Nike SNKRS: JSON parse error: {e}")
                return drops

            # Try multiple known paths for the product threads/items
            items_raw = None

            # Path 1: props.pageProps.initialState.product.threads.data.items (dict of products)
            try:
                threads_data = (
                    data["props"]["pageProps"]["initialState"]["product"]["threads"]["data"]["items"]
                )
                if isinstance(threads_data, dict):
                    items_raw = list(threads_data.values())
                elif isinstance(threads_data, list):
                    items_raw = threads_data
            except (KeyError, TypeError):
                pass

            # Path 2: props.pageProps.initialState.launch.products
            if not items_raw:
                try:
                    items_raw = data["props"]["pageProps"]["initialState"]["launch"]["products"]
                except (KeyError, TypeError):
                    pass

            # Path 3: props.pageProps.products
            if not items_raw:
                try:
                    items_raw = data["props"]["pageProps"]["products"]
                except (KeyError, TypeError):
                    pass

            # Path 4: props.pageProps.data (generic)
            if not items_raw:
                try:
                    items_raw = data["props"]["pageProps"]["data"]
                except (KeyError, TypeError):
                    pass

            if not items_raw:
                logger.warning("Nike SNKRS: Could not locate product items in __NEXT_DATA__")
                return drops

            logger.info(f"Nike SNKRS: Found {len(items_raw)} raw product threads")

            now = datetime.utcnow()
            cutoff = now + timedelta(days=90)

            for product in items_raw:
                if not isinstance(product, dict):
                    continue

                # ── Title / subtitle ──────────────────────────────────────────
                title = product.get("title", "") or ""
                subtitle = product.get("subtitle", "") or ""

                # Combine for fallback brand detection
                full_name = f"{title} {subtitle}".strip()

                # Filter non-footwear: if subtitle is present and contains none of the
                # footwear keywords, skip (jerseys, shorts, hoodies, etc.)
                if subtitle:
                    subtitle_lower = subtitle.lower()
                    is_footwear = any(kw in subtitle_lower for kw in FOOTWEAR_SUBTITLE_KEYWORDS)
                    if not is_footwear:
                        logger.debug(f"Nike SNKRS: Skipping non-footwear — {title} | {subtitle}")
                        continue

                # Filter kids/toddler sizes
                if subtitle:
                    subtitle_lower = subtitle.lower()
                    is_kids = any(kw in subtitle_lower for kw in KIDS_SUBTITLE_KEYWORDS)
                    if is_kids:
                        logger.debug(f"Nike SNKRS: Skipping kids item — {title} | {subtitle}")
                        continue

                # ── Product info array ────────────────────────────────────────
                product_info = product.get("productInfo") or []
                first_info = product_info[0] if product_info else {}

                # ── Price ─────────────────────────────────────────────────────
                merch_price = first_info.get("merchPrice") or {}
                current_price = (
                    merch_price.get("currentPrice")
                    or merch_price.get("fullPrice")
                    or product.get("currentPrice")
                    or product.get("price")
                )
                retail_price = float(current_price) if current_price else None

                # ── Style code ────────────────────────────────────────────────
                merch_product = first_info.get("merchProduct") or {}
                style_code = (
                    merch_product.get("styleColor")
                    or product.get("styleCode")
                    or product.get("style_code")
                    or ""
                )

                # ── Release date ──────────────────────────────────────────────
                commerce_start = (
                    product.get("commerceStartDate")
                    or product.get("startSellDate")
                    or first_info.get("launchView", {}).get("startEntryDate")
                    or first_info.get("commerceStartDate")
                    or ""
                )
                release_date: Optional[datetime] = None
                if commerce_start:
                    # Nike dates are typically ISO format: "2026-03-05T10:00:00.000Z"
                    try:
                        release_date = datetime.fromisoformat(commerce_start.replace("Z", "+00:00")).replace(tzinfo=None)
                    except ValueError:
                        release_date = _parse_date(commerce_start)

                # Filter items releasing more than 90 days from now
                if release_date and release_date > cutoff:
                    logger.debug(f"Nike SNKRS: Skipping far-future item — {title} ({release_date.date()})")
                    continue

                # ── Image URL ─────────────────────────────────────────────────
                published_content = product.get("publishedContent") or {}
                cover_card = (
                    published_content.get("properties", {}).get("coverCard", {}).get("properties", {})
                )
                image_url = (
                    cover_card.get("squarishURL")
                    or cover_card.get("portraitURL")
                    or published_content.get("properties", {}).get("squarishURL")
                    or product.get("imageUrl")
                    or product.get("image_url")
                    or ""
                )

                # ── Slug / source URL ─────────────────────────────────────────
                slug = (
                    product.get("slug")
                    or published_content.get("properties", {}).get("slug")
                    or ""
                )
                if slug and slug.lower() not in ("null", "none", ""):
                    source_url = f"https://www.nike.com/launch/t/{slug}"
                else:
                    source_url = "https://www.nike.com/launch/upcoming"

                # ── Brand detection ───────────────────────────────────────────
                brand = _detect_brand(full_name)

                # ── Colorway from subtitle ────────────────────────────────────
                # Subtitle often reads "Men's Shoes · Colorway Info" or just colorway
                colorway = subtitle if subtitle else ""

                if not title:
                    continue

                drops.append({
                    "name": title[:200],
                    "brand": brand,
                    "colorway": colorway[:200],
                    "style_code": style_code,
                    "retail_price": retail_price,
                    "release_date": release_date,
                    "image_url": image_url,
                    "source": "Nike SNKRS",
                    "source_url": source_url,
                })

            logger.info(f"Nike SNKRS: {len(drops)} footwear drops extracted after filtering")

    except httpx.RequestError as e:
        logger.error(f"Nike SNKRS network error: {e}")
    except Exception as e:
        logger.error(f"Nike SNKRS scraper error: {e}\n{traceback.format_exc()}")

    return drops


# ═══════════════════════════════════════════════
# RSS Scraper 1: Kicks On Fire (richest, 100 items)
# ═══════════════════════════════════════════════
async def scrape_kicksonfire_rss() -> list[dict]:
    """Kicks On Fire RSS feed — large catalog with images and dates."""
    drops = []
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get("https://www.kicksonfire.com/feed/")
            if resp.status_code != 200:
                logger.warning(f"KOF RSS returned {resp.status_code}")
                return drops

            root = ET.fromstring(resp.text)
            items = root.findall('.//item')
            logger.info(f"KOF RSS: {len(items)} items")

            now = datetime.utcnow()
            cutoff = now + timedelta(days=90)

            for item in items:
                title_el = item.find('title')
                title = title_el.text if title_el is not None and title_el.text else ''
                if not title or not _is_sneaker(title):
                    continue

                # Skip junk editorial articles
                if _is_junk_article(title):
                    continue

                link_el = item.find('link')
                link = link_el.text if link_el is not None and link_el.text else ''

                # Get content (full HTML) or description
                content_el = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
                desc_el = item.find('description')
                content_html = ''
                if content_el is not None and content_el.text:
                    content_html = content_el.text
                elif desc_el is not None and desc_el.text:
                    content_html = desc_el.text

                # Extract image
                imgs = re.findall(r'<img[^>]+src="([^"]+\.(?:jpg|jpeg|png|webp))"', content_html, re.I)
                img = imgs[0] if imgs else ''

                # Extract price
                price_m = re.search(r'\$(\d{2,4})', content_html)
                price = float(price_m.group(1)) if price_m else None

                # Extract release date
                date_m = re.search(
                    r'(?:Release Date|Available|Releases?|Dropping|Launch|Expected).*?'
                    r'(\w+ \d{1,2},?\s*\d{4})',
                    content_html, re.I
                )
                release_date = _parse_date(date_m.group(1)) if date_m else None

                # Skip items releasing more than 90 days out
                if release_date and release_date > cutoff:
                    continue

                # Extract style code
                style_m = re.search(r'Style\s*(?:Code|#)?:?\s*([A-Z0-9]{2,}[-]?\d*[-]?\d*)', content_html)
                style_code = style_m.group(1) if style_m else ''

                # Extract colorway
                color_m = re.search(r'Color(?:way)?:?\s*([^<\n]{3,60})', content_html)
                colorway = color_m.group(1).strip() if color_m else ''

                # Clean up title — remove brand prefix if colorway is separate
                name = title.strip()

                drops.append({
                    "name": name[:200],
                    "brand": _detect_brand(name),
                    "colorway": colorway,
                    "style_code": style_code,
                    "retail_price": price,
                    "release_date": release_date,
                    "image_url": img,
                    "source": "Kicks On Fire",
                    "source_url": link,
                })

    except Exception as e:
        logger.error(f"KOF RSS scraper error: {e}")

    return drops


# ═══════════════════════════════════════════════
# RSS Scraper 2: Sneaker News (quality data with prices)
# ═══════════════════════════════════════════════
async def scrape_sneakernews_rss() -> list[dict]:
    """Sneaker News RSS feed — smaller but high quality with prices + images."""
    drops = []
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get("https://sneakernews.com/feed/")
            if resp.status_code != 200:
                logger.warning(f"SN RSS returned {resp.status_code}")
                return drops

            root = ET.fromstring(resp.text)
            items = root.findall('.//item')
            logger.info(f"Sneaker News RSS: {len(items)} items")

            now = datetime.utcnow()
            cutoff = now + timedelta(days=90)

            for item in items:
                title_el = item.find('title')
                title = title_el.text if title_el is not None and title_el.text else ''
                if not title or len(title) < 10:
                    continue

                # Only include sneaker-related articles
                if not _is_sneaker(title):
                    continue

                # Skip junk editorial articles
                if _is_junk_article(title):
                    continue

                link_el = item.find('link')
                link = link_el.text if link_el is not None and link_el.text else ''

                content_el = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
                desc_el = item.find('description')
                content_html = ''
                if content_el is not None and content_el.text:
                    content_html = content_el.text
                elif desc_el is not None and desc_el.text:
                    content_html = desc_el.text

                imgs = re.findall(r'<img[^>]+src="([^"]+\.(?:jpg|jpeg|png|webp))"', content_html, re.I)
                img = imgs[0] if imgs else ''

                price_m = re.search(r'\$(\d{2,4})', content_html)
                price = float(price_m.group(1)) if price_m else None

                date_m = re.search(r'(\w+ \d{1,2},?\s*\d{4})', content_html)
                release_date = _parse_date(date_m.group(1)) if date_m else None

                # Skip items releasing more than 90 days out
                if release_date and release_date > cutoff:
                    continue

                style_m = re.search(r'Style\s*(?:Code|#)?:?\s*([A-Z0-9]{2,}[-]?\d*[-]?\d*)', content_html)
                style_code = style_m.group(1) if style_m else ''

                color_m = re.search(r'Color(?:way)?:?\s*([^<\n]{3,60})', content_html)
                colorway = color_m.group(1).strip() if color_m else ''

                drops.append({
                    "name": title[:200],
                    "brand": _detect_brand(title),
                    "colorway": colorway,
                    "style_code": style_code,
                    "retail_price": price,
                    "release_date": release_date,
                    "image_url": img,
                    "source": "Sneaker News",
                    "source_url": link,
                })

    except Exception as e:
        logger.error(f"Sneaker News RSS error: {e}")

    return drops


# ═══════════════════════════════════════════════
# RSS Scraper 3: Nice Kicks
# ═══════════════════════════════════════════════
async def scrape_nicekicks_rss() -> list[dict]:
    """Nice Kicks RSS feed."""
    drops = []
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get("https://www.nicekicks.com/feed/")
            if resp.status_code != 200:
                return drops

            root = ET.fromstring(resp.text)
            items = root.findall('.//item')
            logger.info(f"Nice Kicks RSS: {len(items)} items")

            now = datetime.utcnow()
            cutoff = now + timedelta(days=90)

            for item in items:
                title_el = item.find('title')
                title = title_el.text if title_el is not None and title_el.text else ''
                if not title or not _is_sneaker(title):
                    continue

                # Skip junk editorial articles
                if _is_junk_article(title):
                    continue

                link_el = item.find('link')
                link = link_el.text if link_el is not None and link_el.text else ''

                content_el = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
                desc_el = item.find('description')
                content_html = ''
                if content_el is not None and content_el.text:
                    content_html = content_el.text
                elif desc_el is not None and desc_el.text:
                    content_html = desc_el.text

                imgs = re.findall(r'<img[^>]+src="([^"]+\.(?:jpg|jpeg|png|webp))"', content_html, re.I)
                img = imgs[0] if imgs else ''

                price_m = re.search(r'\$(\d{2,4})', content_html)
                price = float(price_m.group(1)) if price_m else None

                date_m = re.search(r'(\w+ \d{1,2},?\s*\d{4})', content_html)
                release_date = _parse_date(date_m.group(1)) if date_m else None

                # Skip items releasing more than 90 days out
                if release_date and release_date > cutoff:
                    continue

                style_m = re.search(r'Style\s*(?:Code|#)?:?\s*([A-Z0-9]{2,}[-]?\d*[-]?\d*)', content_html)
                style_code = style_m.group(1) if style_m else ''

                drops.append({
                    "name": title[:200],
                    "brand": _detect_brand(title),
                    "style_code": style_code,
                    "retail_price": price,
                    "release_date": release_date,
                    "image_url": img,
                    "source": "Nice Kicks",
                    "source_url": link,
                })

    except Exception as e:
        logger.error(f"Nice Kicks RSS error: {e}")

    return drops


# ═══════════════════════════════════════════════
# Curated seed data — real Nike SNKRS confirmed releases
# ═══════════════════════════════════════════════
def get_seed_drops() -> list[dict]:
    """Confirmed upcoming Nike SNKRS releases to ensure the app always has data."""
    seed = [
        {"name": "Nike Air Max 90 'Anthracite/Neon Yellow'", "brand": "Nike", "colorway": "Anthracite/Neon Yellow",
         "style_code": "IQ0289-010", "retail_price": 135, "release_date": datetime(2026, 3, 5),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/51e86060-5beb-4bf3-8a79-c39dff901b71/air-max-90-anthracite-and-neon-yellow.webp",
         "source": "Nike SNKRS"},
        {"name": "Nike Air Max 95 OG 'Neon Yellow'", "brand": "Nike", "colorway": "Black/Neon Yellow-Light Graphite",
         "style_code": "HM4740-001", "retail_price": 190, "release_date": datetime(2026, 3, 5),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/d68f96e7-3ed5-4e9b-92f3-24b882dcf7ff/air-max-95-og-neon-yellow1.webp",
         "source": "Nike SNKRS"},
        {"name": "Nike Air Max 95 'Big Bubble' Women's", "brand": "Nike", "colorway": "Neon Yellow",
         "style_code": "IO9926-001", "retail_price": 190, "release_date": datetime(2026, 3, 5),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/503a0df7-99d8-4400-aeca-80c501048f97/womens-air-max-95-big-bubble-neon-yellow.webp",
         "source": "Nike SNKRS"},
        {"name": "Nike Air Griffey Max 1 'Varsity Royal/Volt'", "brand": "Nike", "colorway": "Varsity Royal/Volt",
         "style_code": "DJ5161-400", "retail_price": 180, "release_date": datetime(2026, 3, 6),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/eda89542-829e-458b-b914-0075539619af/air-griffey-max-1-varsity-royal-and-volt.webp",
         "source": "Nike SNKRS"},
        {"name": "Air Jordan 1 Retro High OG 'Psychic Blue'", "brand": "Jordan", "colorway": "Psychic Blue/Pale Ivory",
         "style_code": "FD2596-102", "retail_price": 185, "release_date": datetime(2026, 3, 7),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/a9b611e9-639c-4c0f-99d0-7e0f1500dc66/womens-air-jordan-1-high-og-psychic-blue-and-pale-ivory.webp",
         "source": "Nike SNKRS"},
        {"name": "Air Jordan 4 Retro 'Imperial Purple'", "brand": "Jordan", "colorway": "Imperial Purple",
         "style_code": "FV5029-500", "retail_price": 220, "release_date": datetime(2026, 3, 7),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/03ce2bfe-f10d-4ec8-bc19-9fe92b35225b/air-jordan-4-imperial-purple.webp",
         "source": "Nike SNKRS"},
        {"name": "Nike Air Max Muse x Veneda Carter", "brand": "Nike", "colorway": "Racer Blue",
         "style_code": "HV9929-100", "retail_price": 160, "release_date": datetime(2026, 3, 13),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/3c37bd39-56b7-4bb8-9b13-5620a69eaaa2/womens-air-max-muse-x-veneda-carter-racer-blue.webp",
         "source": "Nike SNKRS"},
        {"name": "Nike Air Foamposite Pro 'University Blue'", "brand": "Nike", "colorway": "University Blue/White",
         "style_code": "HF0794-400", "retail_price": 240, "release_date": datetime(2026, 3, 27),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/a3bee569-dc21-42e2-a004-161cd7df817f/air-foamposite-pro-university-blue-and-white.webp",
         "source": "Nike SNKRS"},
        {"name": "LeBron XXIII Elite 'Good Intentions'", "brand": "Nike", "colorway": "Hyper Pink/Black",
         "style_code": "IB9557-601", "retail_price": 235, "release_date": datetime(2026, 4, 3),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/30d3617a-aeef-4154-86bb-d8366ee0c5ea/lebron-xxiii-elite-good-intentions-hyper-pink-and-black.webp",
         "source": "Nike SNKRS"},
        {"name": "Nike ACG Ultrafly Trail 'Dutch Green'", "brand": "Nike", "colorway": "Dutch Green",
         "style_code": "IR7317-300", "retail_price": 250, "release_date": datetime(2026, 3, 2),
         "image_url": "https://static.nike.com/a/images/f_auto,q_auto,c_limit,w_1200,g_south/8f4810fe-d03d-444b-9ba5-27ca587e6327/acg-ultrafly-trail-dutch-green.webp",
         "source": "Nike SNKRS"},
    ]
    return seed


# ═══════════════════════════════════════════════
# Scraper: Production intel from Hypebeast RSS
# ═══════════════════════════════════════════════
async def scrape_production_intel() -> list[dict]:
    leaks = []
    production_patterns = [
        re.compile(r"limited to (\d[\d,]*)\s*pairs?", re.I),
        re.compile(r"only (\d[\d,]*)\s*pairs?", re.I),
        re.compile(r"(\d[\d,]*)\s*pairs?\s*(?:produced|manufactured|available|worldwide)", re.I),
        re.compile(r"production.*?(\d[\d,]*)\s*pairs?", re.I),
    ]

    rss_urls = [
        ("https://hypebeast.com/feed", "Hypebeast"),
        ("https://www.kicksonfire.com/feed/", "Kicks On Fire"),
    ]

    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for rss_url, source in rss_urls:
            try:
                resp = await client.get(rss_url)
                if resp.status_code != 200:
                    continue
                root = ET.fromstring(resp.text)
                items = root.findall('.//item')

                for item in items:
                    title_el = item.find('title')
                    title = title_el.text if title_el is not None and title_el.text else ''
                    if not _is_sneaker(title):
                        continue

                    content_el = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
                    desc_el = item.find('description')
                    content = ''
                    if content_el is not None and content_el.text:
                        content = BeautifulSoup(content_el.text, "html.parser").get_text(" ", strip=True)
                    elif desc_el is not None and desc_el.text:
                        content = BeautifulSoup(desc_el.text, "html.parser").get_text(" ", strip=True)

                    for pat in production_patterns:
                        m = pat.search(content)
                        if m:
                            num = int(m.group(1).replace(",", ""))
                            if 50 <= num <= 5_000_000:
                                link_el = item.find('link')
                                link = link_el.text if link_el is not None and link_el.text else ''
                                leaks.append({
                                    "shoe_name": title[:200], "production_number": num,
                                    "source_url": link, "confidence": "Rumored", "source": source
                                })
                                break
            except Exception as e:
                logger.error(f"{source} production RSS error: {e}")

    return leaks


# ═══════════════════════════════════════════════
# Scraper: Resale prices (best effort)
# ═══════════════════════════════════════════════
async def scrape_resale_price(style_code: str, name: str) -> dict:
    result = {"stockx_price": None, "goat_price": None, "stockx_url": "", "goat_url": ""}
    if not style_code and not name:
        return result

    search_term = style_code if style_code else name.replace(" ", "+")

    # StockX browse API
    try:
        async with httpx.AsyncClient(
            headers={**HEADERS, "x-requested-with": "XMLHttpRequest"},
            timeout=15, follow_redirects=True
        ) as client:
            resp = await client.get(
                f"https://stockx.com/api/browse?_search={search_term}&page=1&resultsPerPage=3&dataType=product"
            )
            if resp.status_code == 200:
                products = resp.json().get("Products", [])
                if products:
                    p = products[0]
                    result["stockx_price"] = p.get("market", {}).get("lowestAsk") or p.get("market", {}).get("lastSale")
                    result["stockx_url"] = f"https://stockx.com/{p.get('urlKey', '')}"
    except Exception:
        pass

    # GOAT API
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                f"https://www.goat.com/api/v1/product_templates?query={search_term}&count=3"
            )
            if resp.status_code == 200:
                products = resp.json()
                if isinstance(products, list) and products:
                    p = products[0]
                    cents = p.get("lowestPriceCents", 0)
                    if cents:
                        result["goat_price"] = cents / 100.0
                    result["goat_url"] = f"https://www.goat.com/sneakers/{p.get('slug', '')}"
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════
# Scraper: Sole Retriever raffles (fixed fallback)
# ═══════════════════════════════════════════════
async def scrape_raffles() -> list[dict]:
    raffles = []
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get("https://www.soleretriever.com/raffles")
            html = resp.text

            # Try __NEXT_DATA__ first
            nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if nd:
                try:
                    data = json.loads(nd.group(1))
                    page_props = data.get("props", {}).get("pageProps", {})
                    raffle_data = page_props.get("raffles", []) or page_props.get("data", [])
                    for r in raffle_data[:30]:
                        name = r.get("name", "") or r.get("shoe_name", "") or r.get("title", "")
                        store = r.get("store", "") or r.get("retailer", "") or r.get("retailer_name", "")
                        url = r.get("url", "") or r.get("raffle_url", "") or r.get("link", "")
                        deadline = r.get("deadline", "") or r.get("end_date", "")
                        if name:
                            raffles.append({"shoe_name": name, "store": store or "Various",
                                            "url": url, "deadline": str(deadline)})
                except Exception:
                    pass

            # HTML fallback — look for structured raffle links
            if not raffles:
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.select("a[href*='raffle'], a[href*='/raffles/']"):
                    text = link.get_text(strip=True)
                    if text and len(text) > 5 and not any(x in text.lower() for x in ["log in", "sign up", "about"]):
                        href = link.get("href", "")
                        if not href.startswith("http"):
                            href = f"https://www.soleretriever.com{href}"
                        raffles.append({"shoe_name": text[:200], "store": "Sole Retriever",
                                        "url": href, "deadline": ""})

    except Exception as e:
        logger.error(f"Raffle scraper error: {e}")

    # If live scrape fails, fall back to curated Nike SNKRS raffle data with real URLs
    if not raffles:
        logger.info("Raffle scraper returned no results — using curated SNKRS fallback data")
        raffles = [
            {"shoe_name": "Air Jordan 4 Retro 'Imperial Purple'", "store": "Nike SNKRS",
             "url": "https://www.nike.com/launch/t/air-jordan-4-imperial-purple",
             "deadline": "March 7, 2026"},
            {"shoe_name": "Air Jordan 1 Retro High OG 'Psychic Blue'", "store": "Nike SNKRS",
             "url": "https://www.nike.com/launch/t/womens-air-jordan-1-high-og-psychic-blue-and-pale-ivory",
             "deadline": "March 7, 2026"},
            {"shoe_name": "Nike Air Max 95 OG 'Neon Yellow'", "store": "Nike SNKRS",
             "url": "https://www.nike.com/launch/t/air-max-95-og-neon-yellow1",
             "deadline": "March 5, 2026"},
            {"shoe_name": "Nike Air Max 90 'Anthracite/Neon Yellow'", "store": "Nike SNKRS",
             "url": "https://www.nike.com/launch/t/air-max-90-anthracite-and-neon-yellow",
             "deadline": "March 5, 2026"},
            {"shoe_name": "Nike Air Griffey Max 1 'Varsity Royal'", "store": "Nike SNKRS",
             "url": "https://www.nike.com/launch/t/air-griffey-max-1-varsity-royal-and-volt",
             "deadline": "March 6, 2026"},
            {"shoe_name": "Nike Air Foamposite Pro 'University Blue'", "store": "Nike SNKRS",
             "url": "https://www.nike.com/launch/t/air-foamposite-pro-university-blue-and-white",
             "deadline": "March 27, 2026"},
            {"shoe_name": "LeBron XXIII Elite 'Good Intentions'", "store": "Nike SNKRS",
             "url": "https://www.nike.com/launch/t/lebron-xxiii-elite-good-intentions-hyper-pink-and-black",
             "deadline": "April 3, 2026"},
        ]

    return raffles


# ═══════════════════════════════════════════════
# Orchestrator — run all and save to DB
# ═══════════════════════════════════════════════
async def run_drop_scrapers():
    logger.info("=== Starting drop scraper run ===")
    db = SessionLocal()
    all_drops = []
    try:
        results = await asyncio.gather(
            scrape_kicksonfire_rss(),
            scrape_sneakernews_rss(),
            scrape_nicekicks_rss(),
            scrape_nike_snkrs(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list):
                all_drops.extend(r)
            elif isinstance(r, Exception):
                logger.error(f"Scraper exception: {r}")

        logger.info(f"Raw drops collected: {len(all_drops)}")

        # If scrapers returned nothing, use seed data
        existing_count = db.query(SneakerDrop).count()
        if len(all_drops) < 5 and existing_count < 5:
            logger.info("Low scraper results — adding seed data")
            all_drops.extend(get_seed_drops())

        # Deduplicate
        seen = set()
        unique = []
        for d in all_drops:
            key = re.sub(r"[^a-z0-9]", "", d["name"].lower())[:50]
            if key not in seen and len(key) > 5:
                seen.add(key)
                unique.append(d)

        logger.info(f"Unique drops: {len(unique)}")

        new_count = 0
        for d in unique:
            existing = db.query(SneakerDrop).filter(SneakerDrop.name == d["name"]).first()
            prod = d.get("production_number")
            hype = 5.0 + (2.0 if d.get("brand") in ("Jordan", "Nike") else 0)
            heat = _compute_heat_index(prod, hype, 1.2, 5.0)

            if existing:
                if d.get("retail_price") and not existing.retail_price:
                    existing.retail_price = d["retail_price"]
                if d.get("release_date") and not existing.release_date:
                    existing.release_date = d["release_date"]
                if d.get("image_url") and (not existing.image_url or existing.image_url.startswith("/")):
                    existing.image_url = d["image_url"]
                if d.get("colorway"):
                    existing.colorway = d["colorway"]
                if d.get("style_code"):
                    existing.style_code = d["style_code"]
                if d.get("production_number") and not existing.production_number:
                    existing.production_number = d["production_number"]
                    existing.production_confidence = d.get("production_confidence", "Estimated")
                    existing.rarity_tier = _classify_rarity(d["production_number"])
                # Auto-estimate production if still missing
                if not existing.production_number:
                    est = estimate_production(existing.name, existing.brand, existing.retail_price)
                    existing.production_number = est["production_estimate"]
                    existing.production_confidence = est["confidence"]
                    existing.rarity_tier = _classify_rarity(est["production_estimate"])
                    h = _compute_heat_index(est["production_estimate"], existing.hype_score or 5.0, existing.resale_multiple or 1.0, existing.velocity_score or 5.0)
                    existing.heat_index = h["heat_index"]
                    existing.scarcity_score = h["scarcity_score"]
                existing.updated_at = datetime.utcnow()
            else:
                # Auto-estimate production for new drops if not provided
                if not prod:
                    est = estimate_production(d["name"], d.get("brand", "Nike"), d.get("retail_price"))
                    prod = est["production_estimate"]
                    d["production_confidence"] = est["confidence"]
                    d["rarity_tier"] = _classify_rarity(prod)
                    hype = 5.0 + (2.0 if d.get("brand") in ("Jordan", "Nike") else 0)
                    heat = _compute_heat_index(prod, hype, 1.2, 5.0)

                drop = SneakerDrop(
                    name=d["name"], brand=d.get("brand", "Nike"),
                    colorway=d.get("colorway", ""), style_code=d.get("style_code", ""),
                    retail_price=d.get("retail_price"), release_date=d.get("release_date"),
                    image_url=d.get("image_url", ""),
                    where_to_buy=d.get("where_to_buy", "[]"),
                    source=d.get("source", ""),
                    heat_index=heat["heat_index"], scarcity_score=heat["scarcity_score"],
                    hype_score=heat["hype_score"], resale_multiple=heat["resale_multiple"],
                    velocity_score=heat["velocity_score"],
                    rarity_tier=d.get("rarity_tier") or _classify_rarity(prod),
                    production_number=prod,
                    production_confidence=d.get("production_confidence", "Estimated"),
                )
                db.add(drop)
                new_count += 1

        db.commit()
        db.add(ScraperLog(scraper_name="drop_scrapers", status="success",
                          message=f"{len(all_drops)} raw, {len(unique)} unique, {new_count} new", items_found=len(unique)))
        db.commit()
        logger.info(f"=== Drop scraper done: {new_count} new ===")

    except Exception as e:
        logger.error(f"Orchestrator error: {e}\n{traceback.format_exc()}")
        db.add(ScraperLog(scraper_name="drop_scrapers", status="error", message=str(e)))
        db.commit()
    finally:
        db.close()


async def run_production_scraper():
    logger.info("Starting production intel scraper...")
    db = SessionLocal()
    try:
        leaks = await scrape_production_intel()
        new_count = 0
        for leak in leaks:
            existing = db.query(ProductionLeak).filter(
                ProductionLeak.shoe_name == leak["shoe_name"],
                ProductionLeak.production_number == leak["production_number"],
            ).first()
            if not existing:
                db.add(ProductionLeak(shoe_name=leak["shoe_name"], production_number=leak["production_number"],
                                      source_url=leak.get("source_url", ""), confidence=leak.get("confidence", "Rumored"),
                                      submitted_by="system"))
                new_count += 1
                drop = db.query(SneakerDrop).filter(SneakerDrop.name.ilike(f"%{leak['shoe_name'][:30]}%")).first()
                if drop and (drop.production_number is None or leak.get("confidence") == "Confirmed"):
                    drop.production_number = leak["production_number"]
                    drop.production_confidence = leak.get("confidence", "Rumored")
                    drop.rarity_tier = _classify_rarity(leak["production_number"])
                    h = _compute_heat_index(leak["production_number"], drop.hype_score, drop.resale_multiple, drop.velocity_score)
                    drop.heat_index = h["heat_index"]
                    drop.scarcity_score = h["scarcity_score"]

        db.commit()
        db.add(ScraperLog(scraper_name="production_intel", status="success", items_found=new_count))
        db.commit()
    except Exception as e:
        logger.error(f"Production scraper error: {e}")
        db.add(ScraperLog(scraper_name="production_intel", status="error", message=str(e)))
        db.commit()
    finally:
        db.close()


async def run_resale_updater():
    logger.info("Starting resale updater...")
    db = SessionLocal()
    try:
        from sqlalchemy import desc
        drops = db.query(SneakerDrop).order_by(desc(SneakerDrop.heat_index)).limit(15).all()
        updated = 0
        for drop in drops:
            await asyncio.sleep(2)
            prices = await scrape_resale_price(drop.style_code, drop.name)
            if prices["stockx_price"]:
                drop.stockx_price = prices["stockx_price"]
                drop.stockx_url = prices["stockx_url"]
            if prices["goat_price"]:
                drop.goat_price = prices["goat_price"]
                drop.goat_url = prices["goat_url"]
            if drop.retail_price and (prices["stockx_price"] or prices["goat_price"]):
                resale = prices["stockx_price"] or prices["goat_price"]
                drop.resale_multiple = round(resale / drop.retail_price, 2)
                h = _compute_heat_index(drop.production_number, drop.hype_score, drop.resale_multiple, drop.velocity_score)
                drop.heat_index = h["heat_index"]
                updated += 1

        items = db.query(PortfolioItem).all()
        for item in items:
            await asyncio.sleep(2)
            prices = await scrape_resale_price(item.style_code, item.name)
            best = prices["stockx_price"] or prices["goat_price"]
            if best:
                item.current_value = best
                if item.purchase_price > 0:
                    roi = (best - item.purchase_price) / item.purchase_price
                    item.sell_signal = "Strong Sell" if roi > 1.5 else ("Consider Sell" if roi > 0.5 else "Hold")
                updated += 1

        db.commit()
        db.add(ScraperLog(scraper_name="resale_updater", status="success", items_found=updated))
        db.commit()
    except Exception as e:
        logger.error(f"Resale updater error: {e}")
    finally:
        db.close()


async def take_portfolio_snapshot():
    db = SessionLocal()
    try:
        items = db.query(PortfolioItem).all()
        if items:
            total_value = sum(i.current_value or i.purchase_price for i in items)
            total_cost = sum(i.purchase_price for i in items)
            db.add(PortfolioSnapshot(total_value=total_value, total_cost=total_cost))
            db.commit()
    except Exception:
        pass
    finally:
        db.close()
