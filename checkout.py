"""
Checkout API — MercadoPago + Ordenes + Envios
Importadora Maully
"""

import os
import logging
import hashlib
import time
import json
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
from database import async_session, Order, OrderItem

logger = logging.getLogger("bot")

router = APIRouter(prefix="/api")

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
MP_PUBLIC_KEY = os.getenv("MP_PUBLIC_KEY", "")
SITE_URL = os.getenv("SITE_URL", "https://www.importadoramaully.cl")

# ── Costos de envio por region (CLP por kg) ──
SHIPPING_RATES = {
    "starken": {
        "Region Metropolitana": 1500,
        "Valparaiso": 2000, "O'Higgins": 2000, "Maule": 2000,
        "Biobio": 2000, "Nuble": 2000,
        "Araucania": 2500, "Los Rios": 2500, "Los Lagos": 2500,
        "Coquimbo": 2500, "Atacama": 2500,
        "Arica y Parinacota": 3000, "Tarapaca": 3000, "Antofagasta": 3000,
        "Aysen": 3500, "Magallanes": 4000,
        "_default": 2500,
    },
    "dhl": {
        "Region Metropolitana": 3000,
        "Valparaiso": 4000, "O'Higgins": 4000, "Maule": 4000,
        "Biobio": 4000, "Nuble": 4000,
        "Araucania": 5000, "Los Rios": 5000, "Los Lagos": 5000,
        "Coquimbo": 5000, "Atacama": 5000,
        "Arica y Parinacota": 6000, "Tarapaca": 6000, "Antofagasta": 6000,
        "Aysen": 7000, "Magallanes": 8000,
        "_default": 5000,
    },
}

REGIONES_CHILE = [
    "Arica y Parinacota", "Tarapaca", "Antofagasta", "Atacama",
    "Coquimbo", "Valparaiso", "Region Metropolitana", "O'Higgins",
    "Maule", "Nuble", "Biobio", "Araucania", "Los Rios",
    "Los Lagos", "Aysen", "Magallanes"
]


def _gen_order_number() -> str:
    """Genera numero de orden unico: ML-XXXXXX"""
    ts = str(int(time.time()))[-6:]
    h = hashlib.md5(str(time.time()).encode()).hexdigest()[:4].upper()
    return f"ML-{ts}{h}"


def _calc_shipping(method: str, region: str, weight_kg: int) -> int:
    """Calcula costo de envio."""
    if method.startswith("retiro"):
        return 0
    rates = SHIPPING_RATES.get(method, SHIPPING_RATES["starken"])
    rate_per_kg = rates.get(region, rates["_default"])
    # Minimo 5kg para calculo
    effective_weight = max(weight_kg, 5)
    return rate_per_kg * effective_weight


def _validate_rut(rut: str) -> bool:
    """Validacion basica de RUT chileno."""
    rut = rut.replace(".", "").replace("-", "").strip().upper()
    if len(rut) < 8:
        return False
    body = rut[:-1]
    dv = rut[-1]
    if not body.isdigit():
        return False
    s = 0
    mul = 2
    for c in reversed(body):
        s += int(c) * mul
        mul = mul + 1 if mul < 7 else 2
    remainder = 11 - (s % 11)
    expected = "K" if remainder == 10 else ("0" if remainder == 11 else str(remainder))
    return dv == expected


# ══════════════════════════════════════════════
# API ENDPOINTS
# ══════════════════════════════════════════════

@router.get("/config")
async def get_config():
    """Devuelve config publica para el frontend."""
    return {
        "mp_public_key": MP_PUBLIC_KEY,
        "regiones": REGIONES_CHILE,
        "shipping_methods": [
            {"id": "starken", "name": "Starken", "desc": "Envio economico, 5-10 dias habiles. Flete por pagar.", "icon": "fa-truck", "por_pagar": True},
            {"id": "dhl", "name": "DHL Express", "desc": "Envio rapido, 2-5 dias habiles. Flete por pagar.", "icon": "fa-shipping-fast", "por_pagar": True},
            {"id": "coordinar_whatsapp", "name": "Coordinar por WhatsApp", "desc": "Conversemos el mejor envio para ti", "icon": "fa-whatsapp fab", "free": True},
            {"id": "retiro_santiago", "name": "Retiro Santiago", "desc": "Av. La Florida 9421, Santiago", "icon": "fa-store", "free": True},
            {"id": "retiro_pichilemu", "name": "Retiro Pichilemu", "desc": "Av. Millaco 1172, Pichilemu", "icon": "fa-store", "free": True},
        ],
    }


@router.post("/shipping-cost")
async def calc_shipping_cost(request: Request):
    """Calcula costo de envio."""
    data = await request.json()
    method = data.get("method", "starken")
    region = data.get("region", "Region Metropolitana")
    weight = data.get("weight_kg", 10)
    cost = _calc_shipping(method, region, weight)
    return {"cost": cost, "method": method, "region": region}


@router.post("/checkout")
async def create_checkout(request: Request):
    """Crea orden y preferencia de pago en MercadoPago."""
    data = await request.json()

    # Validar campos requeridos
    required = ["name", "rut", "email", "phone", "shipping_method", "items"]
    for field in required:
        if not data.get(field):
            raise HTTPException(400, f"Campo requerido: {field}")

    if not _validate_rut(data["rut"]):
        raise HTTPException(400, "RUT invalido")

    items = data["items"]
    if not items or len(items) == 0:
        raise HTTPException(400, "Carrito vacio")

    # Calcular totales
    subtotal = sum(item["price"] * item.get("qty", 1) for item in items)
    total_weight = sum(int(str(item.get("weight", "20")).replace("kg", "").replace("u", "")) * item.get("qty", 1) for item in items)

    shipping_method = data["shipping_method"]
    region = data.get("region", "Region Metropolitana")
    shipping_cost = _calc_shipping(shipping_method, region, total_weight)
    total = subtotal + shipping_cost

    # Crear orden en DB
    order_number = _gen_order_number()
    async with async_session() as session:
        order = Order(
            order_number=order_number,
            status="pendiente",
            customer_name=data["name"],
            customer_rut=data["rut"],
            customer_email=data["email"],
            customer_phone=data["phone"],
            address_street=data.get("address", ""),
            address_comuna=data.get("comuna", ""),
            address_region=region,
            doc_type=data.get("doc_type", "boleta"),
            business_name=data.get("business_name", ""),
            business_rut=data.get("business_rut", ""),
            business_giro=data.get("business_giro", ""),
            business_address=data.get("business_address", ""),
            shipping_method=shipping_method,
            shipping_cost=shipping_cost,
            subtotal=subtotal,
            total=total,
            total_weight=total_weight,
        )
        session.add(order)
        await session.flush()

        for item in items:
            oi = OrderItem(
                order_id=order.id,
                product_id=item.get("id", 0),
                product_name=item["name"],
                product_cat=item.get("cat", ""),
                weight=str(item.get("weight", "")),
                price=item["price"],
                qty=item.get("qty", 1),
            )
            session.add(oi)

        await session.commit()
        order_id = order.id

    # Crear preferencia MercadoPago
    if not MP_ACCESS_TOKEN:
        return JSONResponse({"error": "MercadoPago no configurado"}, status_code=500)

    mp_items = []
    for item in items:
        mp_items.append({
            "title": item["name"][:256],
            "quantity": item.get("qty", 1),
            "unit_price": item["price"],
            "currency_id": "CLP",
        })

    if shipping_cost > 0:
        mp_items.append({
            "title": f"Envio {shipping_method.upper()} ({total_weight}kg)",
            "quantity": 1,
            "unit_price": shipping_cost,
            "currency_id": "CLP",
        })

    preference = {
        "items": mp_items,
        "payer": {
            "name": data["name"],
            "email": data["email"],
            "phone": {"number": data["phone"]},
        },
        "back_urls": {
            "success": f"{SITE_URL}/checkout.html?status=success&order={order_number}",
            "failure": f"{SITE_URL}/checkout.html?status=failure&order={order_number}",
            "pending": f"{SITE_URL}/checkout.html?status=pending&order={order_number}",
        },
        "auto_return": "approved",
        "external_reference": order_number,
        "notification_url": f"{SITE_URL}/api/mp/webhook",
        "statement_descriptor": "IMPORTADORA MAULLY",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.mercadopago.com/checkout/preferences",
                json=preference,
                headers={
                    "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            mp_data = resp.json()

        logger.info(f"[CHECKOUT] Orden {order_number} creada, MP pref: {mp_data['id']}")

        return {
            "order_number": order_number,
            "order_id": order_id,
            "subtotal": subtotal,
            "shipping_cost": shipping_cost,
            "total": total,
            "mp_preference_id": mp_data["id"],
            "mp_init_point": mp_data["init_point"],
        }

    except Exception as e:
        logger.error(f"[CHECKOUT] Error MercadoPago: {e}")
        raise HTTPException(500, f"Error al crear pago: {str(e)}")


@router.post("/mp/webhook")
async def mp_webhook(request: Request):
    """Webhook de MercadoPago — confirma pagos."""
    try:
        data = await request.json()
    except Exception:
        return {"status": "ok"}

    action = data.get("action", "")
    if action != "payment.updated" and data.get("type") != "payment":
        return {"status": "ok"}

    payment_id = str(data.get("data", {}).get("id", ""))
    if not payment_id:
        return {"status": "ok"}

    # Consultar pago en MercadoPago
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.mercadopago.com/v1/payments/{payment_id}",
                headers={"Authorization": f"Bearer {MP_ACCESS_TOKEN}"},
            )
            resp.raise_for_status()
            payment = resp.json()

        ext_ref = payment.get("external_reference", "")
        status = payment.get("status", "")

        logger.info(f"[MP WEBHOOK] Payment {payment_id} -> {status} for order {ext_ref}")

        if ext_ref:
            async with async_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Order).where(Order.order_number == ext_ref)
                )
                order = result.scalar_one_or_none()
                if order:
                    order.payment_id = payment_id
                    order.payment_status = status
                    if status == "approved":
                        order.status = "pagado"
                        order.paid_at = datetime.utcnow()
                    elif status == "rejected":
                        order.status = "cancelado"
                    await session.commit()
                    logger.info(f"[MP WEBHOOK] Orden {ext_ref} actualizada: {status}")

    except Exception as e:
        logger.error(f"[MP WEBHOOK] Error: {e}")

    return {"status": "ok"}


@router.get("/order/{order_number}")
async def get_order(order_number: str):
    """Obtener estado de una orden."""
    async with async_session() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        result = await session.execute(
            select(Order).where(Order.order_number == order_number).options(selectinload(Order.items))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404, "Orden no encontrada")

        return {
            "order_number": order.order_number,
            "status": order.status,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "items": [
                {"name": i.product_name, "price": i.price, "qty": i.qty, "weight": i.weight}
                for i in order.items
            ],
            "subtotal": order.subtotal,
            "shipping_cost": order.shipping_cost,
            "shipping_method": order.shipping_method,
            "total": order.total,
            "payment_status": order.payment_status,
            "tracking_number": order.tracking_number,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
