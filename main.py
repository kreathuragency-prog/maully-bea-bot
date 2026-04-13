"""
Bot WhatsApp — Bea, Importadora Maully
Webhook + Panel CRM + E-Commerce + Audio (Whisper)
Seguridad: dedupe, background tasks, rate limiting, PII masking
"""

import sys, os, site
_usp = site.getusersitepackages()
if _usp not in sys.path:
    sys.path.insert(0, _usp)
import jinja2  # noqa: F401

import asyncio
import random
import json
import re
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv

from whatsapp import parsear_mensaje, enviar_mensaje, transcribir_audio, close_http_client
from brain import generar_respuesta, cargar_info_web
from scraper import scrape_maully
from checkout import router as checkout_router
from admin_panel import router as admin_router
from database import init_db
from db_ops import (
    get_or_create_contact,
    get_or_create_conversation,
    save_message, get_conversation_messages,
    get_or_create_lead,
    get_all_conversations, get_conversation_detail,
    get_all_leads, get_dashboard_stats,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("bot")

VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "maully-bea-2026")
PORT = int(os.getenv("PORT", 8000))


# ── PII masking ───────────────────────────────────────────────

def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 6:
        return "****"
    return phone[:4] + "*" * (len(phone) - 8) + phone[-4:]


def mask_text(text: str, max_chars: int = 40) -> str:
    if not text:
        return ""
    t = text.replace("\n", " ").strip()
    return t[:max_chars] + "..." if len(t) > max_chars else t


# ── Background task tracker + dedupe ──────────────────────────

_background_tasks: set[asyncio.Task] = set()
_procesados_cache: dict[str, float] = {}
_MAX_CACHE = 10000
_CACHE_TTL = 600


def track_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _ya_procesado(msg_id: str) -> bool:
    if not msg_id:
        return False
    ahora = time.time()
    if len(_procesados_cache) > _MAX_CACHE:
        expirados = [k for k, v in _procesados_cache.items() if ahora - v > _CACHE_TTL]
        for k in expirados:
            _procesados_cache.pop(k, None)
    if msg_id in _procesados_cache:
        return True
    _procesados_cache[msg_id] = ahora
    return False


# Input validation
MAX_TEXTO = 2000
_RE_TELEFONO = re.compile(r"\+?\d{8,20}")


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    info_web = await scrape_maully()
    cargar_info_web(info_web)
    logger.info("Bea Bot (Importadora Maully) iniciado en puerto %d", PORT)
    yield

    # Shutdown ordenado
    logger.info("Shutdown iniciando...")
    if _background_tasks:
        logger.info(f"Esperando {len(_background_tasks)} tareas pendientes...")
        try:
            await asyncio.wait_for(
                asyncio.gather(*_background_tasks, return_exceptions=True),
                timeout=25.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Timeout, {len(_background_tasks)} tareas canceladas")
            for t in _background_tasks:
                t.cancel()

    try:
        await close_http_client()
    except Exception as e:
        logger.error(f"Error cerrando http client: {e}")

    try:
        from database import engine
        await engine.dispose()
    except Exception as e:
        logger.error(f"Error dispose engine: {e}")

    logger.info("Shutdown completo")


app = FastAPI(title="Importadora Maully — Bea WhatsApp Bot + E-Commerce", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.importadoramaully.cl", "https://importadoramaully.cl", "http://localhost:3002"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(checkout_router)
app.include_router(admin_router)

os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
jinja_env = Environment(loader=FileSystemLoader("templates"), autoescape=True)


def render(template_name: str, **context) -> HTMLResponse:
    template = jinja_env.get_template(template_name)
    return HTMLResponse(template.render(**context))


# ══════════════════════════════════════════════════════════════
# WEBHOOK
# ══════════════════════════════════════════════════════════════

@app.get("/")
async def health():
    return {"status": "ok", "service": "maully-bea-bot", "bot": "Bea"}


@app.get("/webhook")
async def verificar_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verificado OK")
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403, detail="Token invalido")


@app.post("/webhook")
async def recibir_mensaje(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}

    mensajes = parsear_mensaje(body)

    for msg in mensajes:
        telefono = (msg.get("telefono") or "").strip()[:20]
        msg_id = msg.get("msg_id", "")
        tipo = msg.get("tipo", "text")

        if not telefono:
            continue
        if not _RE_TELEFONO.fullmatch(telefono):
            logger.warning(f"teléfono inválido ignorado: {telefono!r}")
            continue
        if _ya_procesado(msg_id):
            logger.info(f"[{mask_phone(telefono)}] msg duplicado, ignorando")
            continue

        if tipo == "text":
            texto = (msg.get("texto") or "").strip()
            if not texto:
                continue
            if len(texto) > MAX_TEXTO:
                texto = texto[:MAX_TEXTO]
            texto = "".join(c for c in texto if c >= " " or c in "\n\t")
            track_task(_procesar_texto_async(telefono, texto))

        elif tipo == "audio":
            media_id = msg.get("media_id", "")
            if not media_id:
                continue
            track_task(_procesar_audio_async(telefono, media_id))

        else:
            logger.info(f"[{mask_phone(telefono)}] tipo no soportado: {tipo}")

    return {"status": "ok"}


async def _procesar_texto_async(telefono: str, texto: str):
    logger.info(f"[{mask_phone(telefono)}] -> {mask_text(texto)}")
    await _responder(telefono, texto_para_ia=texto, texto_para_db=texto)


async def _procesar_audio_async(telefono: str, media_id: str):
    logger.info(f"[{mask_phone(telefono)}] -> [voz] media_id={media_id[:12]}...")

    transcripcion = await transcribir_audio(media_id)

    if not transcripcion:
        logger.error(f"[{mask_phone(telefono)}] Whisper falló")
        try:
            contact = await get_or_create_contact(telefono)
            conv = await get_or_create_conversation(contact.id)
            await save_message(conv.id, "inbound", "[audio - no se pudo transcribir]")
            fallback = "Perdón, no pude escuchar bien tu audio 🙈 Me lo puedes escribir? Así te ayudo más rápido 💛"
            await save_message(conv.id, "outbound", fallback)
            await enviar_mensaje(telefono, fallback)
        except Exception as e:
            logger.error(f"Error fallback audio [{mask_phone(telefono)}]: {type(e).__name__}")
        return

    texto_para_ia = transcripcion
    texto_para_db = f"🎤 {transcripcion}"
    logger.info(f"[{mask_phone(telefono)}] -> [voz transcrita] {mask_text(transcripcion)}")

    await _responder(telefono, texto_para_ia=texto_para_ia, texto_para_db=texto_para_db)


async def _responder(telefono: str, texto_para_ia: str, texto_para_db: str):
    try:
        contact = await get_or_create_contact(telefono)
        conv = await get_or_create_conversation(contact.id)

        # Obtener historial ANTES de guardar el mensaje actual
        historial = await get_conversation_messages(conv.id)
        await save_message(conv.id, "inbound", texto_para_db)

        await get_or_create_lead(contact.id, "maully")

        respuesta = await generar_respuesta(texto_para_ia, historial)

        # Delay humanizado
        es_primer_mensaje = len(historial) == 0
        delay = random.uniform(5, 8) if es_primer_mensaje else random.uniform(2, 4)
        await asyncio.sleep(delay)

        await save_message(conv.id, "outbound", respuesta)

        ok = await enviar_mensaje(telefono, respuesta)
        if ok:
            logger.info(f"[{mask_phone(telefono)}] <- {mask_text(respuesta)}")
        else:
            logger.error(f"[{mask_phone(telefono)}] Error enviando")

    except Exception as e:
        logger.error(f"Error procesando [{mask_phone(telefono)}]: {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════
# PANEL CRM (conversaciones de WhatsApp)
# ══════════════════════════════════════════════════════════════

@app.get("/crm", response_class=HTMLResponse)
async def crm_dashboard(request: Request):
    stats = await get_dashboard_stats()
    convs = await get_all_conversations(limit=10)
    return render("admin.html", active="dashboard", stats=stats, conversations=convs)


@app.get("/crm/conversations", response_class=HTMLResponse)
async def crm_conversations(request: Request):
    convs = await get_all_conversations(limit=100)
    return render("conversations.html", active="conversations", conversations=convs)


@app.get("/crm/conversation/{conv_id}", response_class=HTMLResponse)
async def crm_conversation_detail(request: Request, conv_id: int):
    detail = await get_conversation_detail(conv_id)
    if not detail:
        raise HTTPException(status_code=404)
    return render("conversation_detail.html", active="conversations", conv=detail)


@app.post("/crm/conversation/{conv_id}/reply")
async def crm_reply(conv_id: int, message: str = Form(...)):
    detail = await get_conversation_detail(conv_id)
    if not detail:
        raise HTTPException(status_code=404)
    await save_message(conv_id, "outbound", message)
    ok = await enviar_mensaje(detail["phone"], message)
    if ok:
        logger.info(f"[MANUAL] [{detail['phone']}] <- {message[:80]}...")
    return RedirectResponse(url=f"/crm/conversation/{conv_id}", status_code=303)


@app.get("/crm/leads", response_class=HTMLResponse)
async def crm_leads(request: Request):
    leads = await get_all_leads(limit=100)
    return render("leads.html", active="leads", leads=leads)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
