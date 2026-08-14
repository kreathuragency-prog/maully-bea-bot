"""
Scraper — Extrae productos y precios de los sitios del grupo
- importadoramaully.cl (fardos mayorista)
- puntoski.com (retail ski/outdoor)
Se ejecuta al iniciar el bot para tener info actualizada.
"""

import logging
import re
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("bot")

URL_MAULLY = "https://www.importadoramaully.cl"
URL_PUNTOSKI = "https://www.puntoski.com"


# ══════════════════════════════════════════════════════════════
# MAULLY — extrae desde const products del JS
# ══════════════════════════════════════════════════════════════

async def scrape_maully() -> str:
    """Scrape importadoramaully.cl y devuelve texto con productos/precios."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(URL_MAULLY)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        scripts = soup.find_all("script")
        product_info = []

        for script in scripts:
            text = script.string or ""
            if "const products" in text or "products =" in text:
                for line in text.split("\n"):
                    line = line.strip()
                    if "name:" in line and "price:" in line:
                        try:
                            name_start = line.index("name:'") + 6
                            name_end = line.index("'", name_start)
                            name = line[name_start:name_end]

                            price_start = line.index("price:") + 6
                            price_end = line.index(",", price_start)
                            price = line[price_start:price_end]

                            weight = ""
                            if "weight:'" in line:
                                w_start = line.index("weight:'") + 8
                                w_end = line.index("'", w_start)
                                weight = line[w_start:w_end]

                            tier = ""
                            if "tier:'" in line:
                                t_start = line.index("tier:'") + 6
                                t_end = line.index("'", t_start)
                                tier = line[t_start:t_end]

                            product_info.append(f"- {name} | {weight} | {tier} | ${price} CLP")
                        except (ValueError, IndexError):
                            continue

        if product_info:
            result = f"Catálogo Maully con {len(product_info)} productos disponibles:\n\n"
            result += "\n".join(product_info)
            logger.info(f"Scraper Maully: {len(product_info)} productos extraídos")
            return result

        content_sections = []
        for section in soup.find_all("section"):
            text = section.get_text(separator=" ", strip=True)
            if len(text) > 50:
                content_sections.append(text[:500])

        result = "\n\n".join(content_sections[:10])
        logger.info(f"Scraper Maully: texto general extraído")
        return result

    except Exception as e:
        logger.warning(f"Scraper Maully: no pude acceder a {URL_MAULLY}: {e}")
        return ""


# ══════════════════════════════════════════════════════════════
# PUNTO SKI — scrape genérico de productos (Shopify / HTML)
# ══════════════════════════════════════════════════════════════

async def scrape_puntoski() -> str:
    """
    Scrape puntoski.com y devuelve texto con productos/precios.
    Intenta en orden:
    1. /products-schema.json (JSON-LD nativo de PuntoSki — fuente oficial)
    2. /products.json (formato Shopify — por si migra)
    3. Parseo de HTML genérico buscando product cards (fallback)
    """
    # Método 1: products-schema.json (formato nativo PuntoSki — JSON-LD Schema.org)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(f"{URL_PUNTOSKI}/products-schema.json",
                                     headers={"Accept": "application/json",
                                              "User-Agent": "BeaBot/1.0 (+https://puntoski.com)"})
            if resp.status_code == 200:
                data = resp.json()
                # JSON-LD viene como array de productos Schema.org
                productos = data if isinstance(data, list) else data.get("products", [])
                if productos:
                    lines = [f"Catálogo Punto Ski con {len(productos)} productos disponibles:\n"]
                    sin_stock = 0
                    for p in productos:
                        name = p.get("name", "") or p.get("title", "")
                        sku  = p.get("sku", "")
                        brand = ""
                        b = p.get("brand")
                        if isinstance(b, dict):
                            brand = b.get("name", "")
                        elif isinstance(b, str):
                            brand = b
                        category = p.get("category", "") or ""
                        offers = p.get("offers", {}) or {}
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        precio = offers.get("price") or offers.get("lowPrice") or ""
                        availability = (offers.get("availability") or "").lower()
                        disponible = "instock" in availability or "in_stock" in availability or availability == ""
                        if not disponible:
                            sin_stock += 1
                        precio_str = ""
                        if precio:
                            try:
                                pf = int(float(precio))
                                precio_str = f"${pf:,}".replace(",", ".") + " CLP"
                            except (TypeError, ValueError):
                                precio_str = f"${precio} CLP"
                        stock_str = "" if disponible else " (SIN STOCK)"
                        brand_str = f" [{brand}]" if brand else ""
                        sku_str = f" SKU:{sku}" if sku else ""
                        cat_str = f" · {category}" if category else ""
                        url = p.get("url", "") or (offers.get("url", "") if isinstance(offers, dict) else "")
                        url_str = f" → {url}" if url else ""
                        # Línea compacta para que el modelo no se sature
                        lines.append(f"- {name}{brand_str}{cat_str} | {precio_str}{stock_str}{sku_str}{url_str}")
                    if sin_stock:
                        lines.append(f"\n(Total sin stock: {sin_stock}/{len(productos)})")
                    result = "\n".join(lines)
                    logger.info(f"Scraper Punto Ski (products-schema.json): {len(productos)} productos")
                    return result
    except Exception as e:
        logger.info(f"Scraper Punto Ski: products-schema.json falló ({e}), probando Shopify API")

    # Método 2: API de Shopify (legacy, por si migra)
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(f"{URL_PUNTOSKI}/products.json?limit=250")
            if resp.status_code == 200:
                data = resp.json()
                productos = data.get("products", [])
                if productos:
                    lines = [f"Catálogo Punto Ski con {len(productos)} productos:\n"]
                    for p in productos:
                        title = p.get("title", "")
                        vendor = p.get("vendor", "")
                        tags = ", ".join(p.get("tags", [])[:3]) if p.get("tags") else ""
                        variants = p.get("variants", [])
                        if not variants:
                            continue
                        prices = [float(v.get("price", 0)) for v in variants if v.get("price")]
                        if not prices:
                            continue
                        price_min = int(min(prices))
                        price_max = int(max(prices))
                        precio_str = f"${price_min:,}".replace(",", ".") if price_min == price_max else f"${price_min:,} - ${price_max:,}".replace(",", ".")
                        disponible = any(v.get("available") for v in variants)
                        stock_str = "" if disponible else " (SIN STOCK)"
                        tallas = [v.get("title", "") for v in variants if v.get("available")]
                        tallas_str = f" | tallas: {', '.join(tallas[:6])}" if tallas and tallas[0] != "Default Title" else ""
                        vendor_str = f" [{vendor}]" if vendor else ""
                        tag_str = f" ({tags})" if tags else ""
                        lines.append(f"- {title}{vendor_str}{tag_str} | {precio_str}{stock_str}{tallas_str}")
                    result = "\n".join(lines)
                    logger.info(f"Scraper Punto Ski (Shopify API): {len(productos)} productos")
                    return result
    except Exception as e:
        logger.info(f"Scraper Punto Ski: Shopify API no disponible ({e}), probando HTML")

    # Método 2: parseo HTML genérico
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(URL_PUNTOSKI)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Buscar product cards genéricos (nombre + precio cercanos)
        productos = []
        # Pattern para precios chilenos: $12.900 / $12900 / $12.900 CLP
        price_re = re.compile(r"\$\s?[\d\.,]{3,}")

        # Buscar elementos con precio
        for el in soup.find_all(string=price_re):
            parent = el.parent
            if not parent:
                continue
            # Subir hasta un contenedor que tenga un título cerca
            container = parent
            for _ in range(4):
                if container.parent:
                    container = container.parent
                else:
                    break
            # Buscar título en el contenedor
            titulo = ""
            for h in container.find_all(["h1", "h2", "h3", "h4", "a"]):
                t = h.get_text(strip=True)
                if 5 < len(t) < 120:
                    titulo = t
                    break
            precio_match = price_re.search(str(el))
            precio = precio_match.group() if precio_match else ""
            if titulo and precio:
                linea = f"- {titulo} | {precio}"
                if linea not in productos:
                    productos.append(linea)

        if productos:
            result = f"Catálogo Punto Ski (web): {len(productos)} productos encontrados:\n\n"
            result += "\n".join(productos[:80])
            logger.info(f"Scraper Punto Ski (HTML): {len(productos)} productos")
            return result

        # Fallback: info general del sitio
        title = soup.find("title")
        description = soup.find("meta", attrs={"name": "description"})
        content_sections = []
        if title:
            content_sections.append(f"Sitio: {title.get_text(strip=True)}")
        if description:
            content_sections.append(f"Descripción: {description.get('content', '')}")
        for section in soup.find_all(["section", "main", "div"], limit=20):
            text = section.get_text(separator=" ", strip=True)
            if 100 < len(text) < 800:
                content_sections.append(text)
                if len(content_sections) >= 8:
                    break

        result = "\n\n".join(content_sections)
        logger.info("Scraper Punto Ski: texto general extraído (sin productos estructurados)")
        return result

    except Exception as e:
        logger.warning(f"Scraper Punto Ski: no pude acceder a {URL_PUNTOSKI}: {e}")
        return ""
