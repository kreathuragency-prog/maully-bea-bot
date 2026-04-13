"""
WhatsApp — Parser de mensajes entrantes + envío vía Graph API
Con singleton httpx, retry exponencial, split automático y transcripción Whisper.
"""

import os
import asyncio
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("bot")

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_VERSION = "v21.0"
MAX_MESSAGE_LENGTH = 4000
SEND_RETRIES = 3

# Whisper / audio
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Whisper limita a 25 MB

# ── Singleton HTTP client ──────────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
        )
    return _http_client


async def close_http_client():
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


# ── Parser de webhooks ─────────────────────────────────────────

def parsear_mensaje(body: dict) -> list[dict]:
    """
    Extrae mensajes (texto Y audio) del payload de Meta Cloud API.
    Retorna lista de:
      - texto: {"telefono","texto","msg_id","tipo":"text"}
      - audio: {"telefono","media_id","mime_type","msg_id","tipo":"audio"}
    """
    mensajes = []

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                tipo = msg.get("type")
                telefono = msg.get("from", "")
                msg_id = msg.get("id", "")
                if not telefono:
                    continue

                if tipo == "text":
                    texto = msg.get("text", {}).get("body", "")
                    if not texto:
                        continue
                    mensajes.append({
                        "tipo": "text",
                        "telefono": telefono,
                        "texto": texto.strip(),
                        "msg_id": msg_id,
                    })

                elif tipo in ("audio", "voice"):
                    audio = msg.get("audio") or msg.get("voice") or {}
                    media_id = audio.get("id", "")
                    mime = audio.get("mime_type", "audio/ogg")
                    if not media_id:
                        continue
                    mensajes.append({
                        "tipo": "audio",
                        "telefono": telefono,
                        "media_id": media_id,
                        "mime_type": mime,
                        "msg_id": msg_id,
                    })

                else:
                    logger.info(f"Mensaje tipo no soportado: {tipo}")

    return mensajes


# ── Audio: descarga + transcripción Whisper ─────────────────────

async def _get_media_url(media_id: str) -> str | None:
    url = f"https://graph.facebook.com/{API_VERSION}/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    client = get_http_client()
    try:
        r = await client.get(url, headers=headers)
        if r.status_code != 200:
            logger.error(f"get_media_url fallo [{r.status_code}]: {r.text[:300]}")
            return None
        return r.json().get("url")
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(f"Error pidiendo media_url: {type(e).__name__}")
        return None


async def descargar_audio(media_id: str) -> tuple[bytes, str] | None:
    if not ACCESS_TOKEN:
        logger.error("META_ACCESS_TOKEN no configurado")
        return None

    media_url = await _get_media_url(media_id)
    if not media_url:
        return None

    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    client = get_http_client()
    try:
        r = await client.get(media_url, headers=headers, timeout=httpx.Timeout(connect=5.0, read=60.0, write=5.0, pool=5.0))
        if r.status_code != 200:
            logger.error(f"descargar_audio fallo [{r.status_code}]")
            return None
        if len(r.content) > MAX_AUDIO_BYTES:
            logger.error(f"Audio demasiado grande ({len(r.content)} bytes)")
            return None
        mime = r.headers.get("content-type", "audio/ogg").split(";")[0].strip()
        return r.content, mime
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(f"Error descargando audio: {type(e).__name__}")
        return None


async def transcribir_audio(media_id: str) -> str | None:
    """Descarga audio y lo transcribe con OpenAI Whisper en español."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY no configurado — no se puede transcribir audio")
        return None

    descarga = await descargar_audio(media_id)
    if not descarga:
        return None
    audio_bytes, mime = descarga

    ext = "ogg"
    if "mp4" in mime or "m4a" in mime:
        ext = "m4a"
    elif "mpeg" in mime or "mp3" in mime:
        ext = "mp3"
    elif "wav" in mime:
        ext = "wav"

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    files = {"file": (f"audio.{ext}", audio_bytes, mime)}
    data = {
        "model": WHISPER_MODEL,
        "language": "es",
        "response_format": "text",
        "prompt": "Importadora Maully, fardo, fardos, ropa americana, ropa europea, chaqueta, mezclilla, polerón, buzo, plus size, jeans, caluga, pack, envío, Bea, Santiago, Pichilemu.",
    }

    client = get_http_client()
    try:
        r = await client.post(url, headers=headers, files=files, data=data,
                              timeout=httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0))
        if r.status_code != 200:
            logger.error(f"Whisper rechazó [{r.status_code}]: {r.text[:300]}")
            return None
        texto = r.text.strip()
        if not texto:
            return None
        logger.info(f"Whisper transcribió ({len(audio_bytes)//1024} KB -> {len(texto)} chars)")
        return texto
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.error(f"Error llamando Whisper: {type(e).__name__}")
        return None


# ── Envío de mensajes ──────────────────────────────────────────

def _split_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> list[str]:
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current.strip())
    return chunks


async def _send_single(telefono: str, texto: str) -> bool:
    url = f"https://graph.facebook.com/{API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"body": texto, "preview_url": True},
    }

    client = get_http_client()

    for attempt in range(SEND_RETRIES):
        try:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code == 200:
                return True
            if r.status_code in (429, 500, 502, 503, 504):
                backoff = (2 ** attempt) + (attempt * 0.1)
                logger.warning(f"Meta API {r.status_code}, retry {attempt + 1}/{SEND_RETRIES} en {backoff:.1f}s")
                await asyncio.sleep(backoff)
                continue
            logger.error(f"Meta API [{r.status_code}] no recuperable: {r.text[:300]}")
            return False
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            backoff = 2 ** attempt
            logger.warning(f"Error de red (intento {attempt + 1}/{SEND_RETRIES}): {type(e).__name__}")
            await asyncio.sleep(backoff)

    logger.error(f"Meta API: fallo definitivo tras {SEND_RETRIES} reintentos")
    return False


async def enviar_mensaje(telefono: str, texto: str) -> bool:
    """Envía mensaje vía Meta WhatsApp Cloud API con auto-split y retry."""
    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        logger.error("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
        return False

    if not texto or not texto.strip():
        logger.warning("Intento de enviar texto vacío")
        return False

    chunks = _split_message(texto.strip())
    all_ok = True
    for i, chunk in enumerate(chunks):
        ok = await _send_single(telefono, chunk)
        if not ok:
            all_ok = False
            break
        if i < len(chunks) - 1:
            await asyncio.sleep(0.5)
    return all_ok
