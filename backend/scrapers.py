"""SoleOracle scrapers v2 — robust extraction from sneaker sites."""
import json, re, asyncio, logging, traceback
from datetime import datetime, timedelta
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from models import SessionLocal, SneakerDrop, ProductionLeak, ScraperLog, PortfolioItem, PortfolioSnapshot
from sqlalchemy import desc

logger = logging.getLogger("soleoracle.scrapers")
logging.basicConfig(level=logging.INFO)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"\$\s?([\d,]+(?:\.\d{2})?)", text.replace(",", ""))
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
    if "adidas" in nl or "yeezy" in nl:
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


async def scrape_sneakerbar_detroit() -> list:
    drops = []
    base = "https://sneakerbardetroit.com/sneaker-release-dates/"
    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        try:
            resp = await client.get(base)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            all_text = str(soup)
            release_blocks = re.findall(
                r'<(?:strong|b|h[23])>([^<]+(?:Nike|Jordan|Air|adidas|Yeezy|Dunk|Max|Kobe|LeBron|KD|Converse|New Balance|ASICS|Puma|Reebok)[^<]*)</(?:strong|b|h[23])>'
                r'.*?(?=<(?:strong|b|h[23])>|$)',
                all_text, re.DOTALL | re.IGNORECASE
            )
            for block in release_blocks[:60]:
                name_m = re.match(r'([^<]+)', block)
                if not name_m:
                    continue
                name = BeautifulSoup(name_m.group(1), "html.parser").get_text(strip=True)
                if not name or len(name) < 5:
                    continue
                block_text = BeautifulSoup(block, "html.parser").get_text(" ", strip=True)
                colorway = ""
                cw_m = re.search(r"Color:\s*(.+?)(?:\s*Style|\s*Release|\s*Price|\n|$)", block_text)
                if cw_m:
                    colorway = cw_m.group(1).strip()
                style_code = ""
                sc_m = re.search(r"Style\s*(?:Code|#)?:?\s*([A-Z0-9]{2,}\d*-?\d*)", block_text)
                if sc_m:
                    style_code = sc_m.group(1)
                date_m = re.search(r"Release\s*Date:\s*(.+?)(?:\s*Price|\n|$)", block_text)
                release_date = _parse_date(date_m.group(1).strip()) if date_m else None
                price_m = re.search(r"Price:\s*\$?([\d,]+)", block_text)
                price = float(price_m.group(1).replace(",", "")) if price_m else None
                img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', block)
                img_url = img_m.group(1) if img_m else ""
                buy_links = re.findall(r'Buy:\s*<a[^>]+href=["\']([^"\']+)["\']', block) or []
                where_to_buy = [{"name": "Retailer", "url": u} for u in buy_links[:5]]
                drops.append({
                    "name": name[:200], "brand": _detect_brand(name), "colorway": colorway,
                    "style_code": style_code, "retail_price": price, "release_date": release_date,
                    "image_url": img_url, "source": "Sneaker Bar Detroit", "where_to_buy": json.dumps(where_to_buy),
                })
        except Exception as e:
            logger.error(f"SBD scraper error: {e}")
    if len(drops) < 5:
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
                resp = await client.get(base)
                soup = BeautifulSoup(resp.text, "html.parser")
                for el in soup.find_all(["p", "h2", "h3", "h4"]):
                    text = el.get_text(strip=True)
                    if re.search(r'\$\d+', text) and re.search(r'(Nike|Jordan|Air|adidas|Dunk|Max|Kobe)', text, re.I):
                        name_match = re.match(r'^(.+?)(?:Color:|Style|Release|Price:|\$)', text)
                        name = name_match.group(1).strip() if name_match else text[:80]
                        price = _parse_price(text)
                        date = _parse_date(text)
                        img_el = el.find_next("img")
                        img_url = img_el.get("src", "") if img_el and img_el.get("src", "").startswith("http") else ""
                        if name and len(name) > 5:
                            drops.append({"name": name[:200], "brand": _detect_brand(name),
                                          "retail_price": price, "release_date": date,
                                          "image_url": img_url, "source": "Sneaker Bar Detroit"})
        except Exception as e:
            logger.error(f"SBD fallback error: {e}")
    return drops


async def scrape_sole_retriever() -> list:
    drops = []
    try:
        url = "https://www.soleretriever.com/sneaker-release-dates"
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            html = resp.text
            next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if next_data_match:
                try:
                    data = json.loads(next_data_match.group(1))
                    page_props = data.get("props", {}).get("pageProps", {})
                    releases = page_props.get("releases", []) or page_props.get("sneakers", []) or page_props.get("data", [])
                    if isinstance(releases, list):
                        for r in releases[:60]:
                            name = r.get("name", "") or r.get("title", "") or r.get("shoe_name", "")
                            if not name:
                                continue
                            price_val = r.get("price", "") or r.get("retail_price", "")
                            price = float(price_val) if isinstance(price_val, (int, float)) else _parse_price(str(price_val))
                            date_str = r.get("release_date", "") or r.get("date", "")
                            release_dt = None
                            if date_str:
                                try:
                                    release_dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                                except Exception:
                                    release_dt = _parse_date(str(date_str))
                            img = r.get("image", "") or r.get("image_url", "") or r.get("thumbnail", "")
                            style = r.get("style_code", "") or r.get("sku", "") or r.get("styleCode", "")
                            drops.append({"name": name[:200], "brand": _detect_brand(name),
                                          "colorway": r.get("colorway", "") or r.get("color", ""),
                                          "style_code": style, "retail_price": price,
                                          "release_date": release_dt, "image_url": img, "source": "Sole Retriever"})
                except json.JSONDecodeError:
                    pass
            if not drops:
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.select("a[href*='/release/']"):
                    text = link.get_text(" ", strip=True)
                    if len(text) < 8:
                        continue
                    if any(x in text.lower() for x in ["calendar", "release dates", "raffle", "log in", "sign up"]):
                        continue
                    img_el = link.select_one("img")
                    img = ""
                    if img_el:
                        img = img_el.get("src", "") or img_el.get("data-src", "")
                    price = _parse_price(text)
                    name_parts = [t.strip() for t in text.split("\n") if t.strip()]
                    name = name_parts[0] if name_parts else text[:100]
                    href = link.get("href", "")
                    if href and not href.startswith("http"):
                        href = f"https://www.soleretriever.com{href}"
                    drops.append({"name": name[:200], "brand": _detect_brand(name),
                                  "retail_price": price, "image_url": img,
                                  "source": "Sole Retriever", "source_url": href})
    except Exception as e:
        logger.error(f"Sole Retriever scraper error: {e}")
    return drops


async def scrape_nike_snkrs() -> list:
    drops = []
    api_url = "https://api.nike.com/cic/browse/v2?queryid=products&anonymousId=anon&country=US&endpoint=%2Fproduct_feed%2Frollup_threads%2Fv2%3Ffilter%3Dmarketplace(US)%26filter%3Dlanguage(en)%26filter%3DchannelId(d9a5bc94-4b9c-4976-858a-f159cf99c647)%26filter%3DexclusiveAccess(true%2Cfalse)%26anchor%3D0%26consumerChannelId%3Dd9a5bc94-4b9c-4976-858a-f159cf99c647%26count%3D50&language=en&localizedRangeStr=%7BlowestPrice%7D%20%E2%80%94%20%7BhighestPrice%7D"
    try:
        async with httpx.AsyncClient(headers={**HEADERS, "nike-api-caller-id": "com.nike.ux.snkrs.web"}, timeout=20, follow_redirects=True) as client:
            resp = await client.get(api_url)
            if resp.status_code == 200:
                data = resp.json()
                objects = data.get("data", {}).get("products", {}).get("objects", [])
                for obj in objects[:50]:
                    props = obj.get("publishedContent", {}).get("properties", {})
                    pi = obj.get("productInfo", [{}])
                    product_info = pi[0] if pi else {}
                    merch = product_info.get("merchProduct", {})
                    launch = product_info.get("launchView", {})
                    name = props.get("title", "") or props.get("subtitle", "")
                    colorway = merch.get("colorDescription", "")
                    style_code = merch.get("styleColor", "")
                    price = merch.get("price", {}).get("fullPrice")
                    img_objs = product_info.get("imageUrls", {})
                    img_url = img_objs.get("productImageUrl", "") or img_objs.get("squarishURL", "") if img_objs else ""
                    release_str = launch.get("startEntryDate", "") or merch.get("commerceStartDate", "")
                    release_dt = None
                    if release_str:
                        try:
                            release_dt = datetime.fromisoformat(release_str.replace("Z", "+00:00"))
                        except Exception:
                            release_dt = _parse_date(release_str)
                    snkrs_url = f"https://www.nike.com/launch/t/{obj.get('id', '')}"
                    brand = "Jordan" if "jordan" in name.lower() else "Nike"
                    if name:
                        drops.append({"name": name[:200], "brand": brand, "colorway": colorway,
                                      "style_code": style_code, "retail_price": float(price) if price else None,
                                      "release_date": release_dt, "image_url": img_url, "source": "Nike SNKRS",
                                      "where_to_buy": json.dumps([{"name": "Nike SNKRS", "url": snkrs_url}])})
    except Exception as e:
        logger.error(f"Nike SNKRS API error: {e}")
    if not drops:
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
                resp = await client.get("https://www.nike.com/launch")
                soup = BeautifulSoup(resp.text, "html.parser")
                next_data = soup.select_one('script#__NEXT_DATA__')
                if next_data:
                    try:
                        data = json.loads(next_data.string)
                        state = data.get("props", {}).get("pageProps", {})
                        products = state.get("products", []) or state.get("initialData", {}).get("products", [])
                        for p in products[:30]:
                            name = p.get("title", "") or p.get("name", "")
                            if name:
                                drops.append({"name": name[:200],
                                              "brand": "Jordan" if "jordan" in name.lower() else "Nike",
                                              "retail_price": p.get("price"),
                                              "image_url": p.get("image", ""), "source": "Nike SNKRS"})
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Nike HTML fallback error: {e}")
    return drops


async def scrape_sneaker_news() -> list:
    drops = []
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get("https://sneakernews.com/release-dates/")
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for article in soup.select("article, .post, [class*='release']")[:40]:
                title_el = article.select_one("h2, h3, h2 a, h3 a, .title a")
                if not title_el:
                    continue
                name = title_el.get_text(strip=True)
                if not name or len(name) < 5:
                    continue
                if any(skip in name.lower() for skip in ["release dates", "calendar", "best of"]):
                    continue
                link = title_el.get("href", "") or (title_el.parent.get("href", "") if title_el.parent else "")
                img_el = article.select_one("img")
                img = ""
                if img_el:
                    img = img_el.get("src", "") or img_el.get("data-lazy-src", "") or img_el.get("data-src", "")
                text = article.get_text(" ", strip=True)
                price = _parse_price(text)
                date = _parse_date(text)
                drops.append({"name": name[:200], "brand": _detect_brand(name),
                              "retail_price": price, "release_date": date,
                              "image_url": img, "source": "Sneaker News", "source_url": link})
    except Exception as e:
        logger.error(f"Sneaker News scraper error: {e}")
    return drops


async def scrape_production_intel() -> list:
    leaks = []
    production_patterns = [
        re.compile(r"limited to (\d[\d,]*)\s*pairs?", re.I),
        re.compile(r"only (\d[\d,]*)\s*pairs?", re.I),
        re.compile(r"(\d[\d,]*)\s*pairs?\s*(?:produced|manufactured|available)", re.I),
        re.compile(r"production.*?(\d[\d,]*)\s*pairs?", re.I),
    ]
    urls = [("https://hypebeast.com/footwear", "Hypebeast"), ("https://www.complex.com/sneakers", "Complex")]
    async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for url, source in urls:
            try:
                resp = await client.get(url)
                soup = BeautifulSoup(resp.text, "html.parser")
                links = []
                for a in soup.select("a[href]")[:30]:
                    href = a.get("href", "")
                    text = a.get_text(strip=True).lower()
                    if any(kw in href.lower() + " " + text for kw in ["sneaker", "shoe", "jordan", "nike", "release", "dunk", "limited"]):
                        if not href.startswith("http"):
                            href = f"https://{source.lower()}.com{href}"
                        links.append((a.get_text(strip=True), href))
                for title, link in links[:6]:
                    try:
                        await asyncio.sleep(1.5)
                        art_resp = await client.get(link)
                        art_text = BeautifulSoup(art_resp.text, "html.parser").get_text(" ", strip=True)
                        for pat in production_patterns:
                            m = pat.search(art_text)
                            if m:
                                num = int(m.group(1).replace(",", ""))
                                if 50 <= num <= 5_000_000:
                                    leaks.append({"shoe_name": title[:200], "production_number": num,
                                                   "source_url": link, "confidence": "Rumored", "source": source})
                                    break
                    except Exception:
                        continue
            except Exception as e:
                logger.error(f"{source} production error: {e}")
    return leaks


async def scrape_resale_price(style_code: str, name: str) -> dict:
    result = {"stockx_price": None, "goat_price": None, "stockx_url": "", "goat_url": ""}
    if not style_code and not name:
        return result
    search_term = style_code if style_code else name.replace(" ", "+")
    try:
        async with httpx.AsyncClient(headers={**HEADERS, "x-requested-with": "XMLHttpRequest"}, timeout=15, follow_redirects=True) as client:
            resp = await client.get(f"https://stockx.com/api/browse?_search={search_term}&page=1&resultsPerPage=3&dataType=product")
            if resp.status_code == 200:
                products = resp.json().get("Products", [])
                if products:
                    p = products[0]
                    result["stockx_price"] = p.get("market", {}).get("lowestAsk") or p.get("market", {}).get("lastSale")
                    result["stockx_url"] = f"https://stockx.com/{p.get('urlKey', '')}"
    except Exception:
        pass
    if not result["stockx_price"]:
        try:
            async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
                resp = await client.get(f"https://stockx.com/search?s={name.replace(' ', '%20')}")
                soup = BeautifulSoup(resp.text, "html.parser")
                price_els = soup.select("[data-testid*='price'], [class*='price'], [class*='Price']")
                for pe in price_els[:3]:
                    p = _parse_price(pe.get_text(strip=True))
                    if p and p > 20:
                        result["stockx_price"] = p
                        break
                link_el = soup.select_one("a[href*='/product/'], a[href*='/sneakers/']")
                if link_el:
                    href = link_el.get("href", "")
                    result["stockx_url"] = href if href.startswith("http") else f"https://stockx.com{href}"
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            resp = await client.get(f"https://www.goat.com/api/v1/product_templates?query={search_term}&count=3")
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


async def scrape_raffles() -> list:
    raffles = []
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            resp = await client.get("https://www.soleretriever.com/raffles")
            html = resp.text
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
    return raffles


async def run_drop_scrapers():
    logger.info("=== Starting drop scraper run ===")
    db = SessionLocal()
    all_drops = []
    try:
        results = await asyncio.gather(
            scrape_sneakerbar_detroit(), scrape_sole_retriever(),
            scrape_nike_snkrs(), scrape_sneaker_news(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list):
                all_drops.extend(r)
            elif isinstance(r, Exception):
                logger.error(f"Scraper exception: {r}")
        logger.info(f"Raw drops collected: {len(all_drops)}")
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
            hype = 5.0 + (2.0 if d.get("brand") in ("Jordan", "Nike") else 0)
            heat = _compute_heat_index(d.get("production_number"), hype, 1.2, 5.0)
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
                existing.updated_at = datetime.utcnow()
            else:
                drop = SneakerDrop(
                    name=d["name"], brand=d.get("brand", "Nike"),
                    colorway=d.get("colorway", ""), style_code=d.get("style_code", ""),
                    retail_price=d.get("retail_price"), release_date=d.get("release_date"),
                    image_url=d.get("image_url", ""), where_to_buy=d.get("where_to_buy", "[]"),
                    source=d.get("source", ""),
                    heat_index=heat["heat_index"], scarcity_score=heat["scarcity_score"],
                    hype_score=heat["hype_score"], resale_multiple=heat["resale_multiple"],
                    velocity_score=heat["velocity_score"],
                    rarity_tier=_classify_rarity(d.get("production_number")),
                    production_number=d.get("production_number"),
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
