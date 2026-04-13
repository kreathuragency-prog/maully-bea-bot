"""
Scraper — Extrae productos y precios de importadoramaully.cl
Se ejecuta al iniciar el bot para tener info actualizada
"""

import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("bot")

URL = "https://www.importadoramaully.cl"


async def scrape_maully() -> str:
    """Scrape importadoramaully.cl y devuelve texto con productos/precios."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(URL)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extraer scripts que contienen productos
        scripts = soup.find_all("script")
        product_info = []

        for script in scripts:
            text = script.string or ""
            if "const products" in text or "products =" in text:
                # Extraer lineas con datos de productos
                for line in text.split("\n"):
                    line = line.strip()
                    if "name:" in line and "price:" in line:
                        # Parsear nombre y precio basico
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
            result = f"Catalogo con {len(product_info)} productos disponibles:\n\n"
            result += "\n".join(product_info)
            logger.info(f"Scraper: {len(product_info)} productos extraidos de {URL}")
            return result

        # Fallback: extraer texto general
        content_sections = []
        for section in soup.find_all("section"):
            text = section.get_text(separator=" ", strip=True)
            if len(text) > 50:
                content_sections.append(text[:500])

        result = "\n\n".join(content_sections[:10])
        logger.info(f"Scraper: extraido texto general de {URL}")
        return result

    except Exception as e:
        logger.warning(f"Scraper: no pude acceder a {URL}: {e}")
        return ""
