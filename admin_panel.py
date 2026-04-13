"""
Panel Admin — Importadora Maully
Dashboard, pedidos, envios, boletas
"""

import os
import hashlib
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from database import async_session, Order, OrderItem, AdminUser

logger = logging.getLogger("bot")

router = APIRouter(prefix="/admin")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "maully2026")
_sessions = {}  # Simple session store: token -> expiry


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _check_auth(request: Request) -> bool:
    token = request.cookies.get("admin_token", "")
    if token in _sessions and _sessions[token] > datetime.utcnow():
        return True
    return False


def _require_auth(request: Request):
    if not _check_auth(request):
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})


def _fmt_price(n: int) -> str:
    return f"${n:,.0f}".replace(",", ".")


def _fmt_date(dt) -> str:
    if not dt:
        return "-"
    return dt.strftime("%d/%m/%Y %H:%M")


STATUS_LABELS = {
    "pendiente": ("Pendiente", "#f59e0b", "fa-clock"),
    "pagado": ("Pagado", "#10b981", "fa-check-circle"),
    "enviado": ("Enviado", "#3b82f6", "fa-truck"),
    "entregado": ("Entregado", "#059669", "fa-box-open"),
    "cancelado": ("Cancelado", "#ef4444", "fa-times-circle"),
}

SHIPPING_LABELS = {
    "starken": "Starken (por pagar)",
    "dhl": "DHL Express (por pagar)",
    "coordinar_whatsapp": "Coordinar por WhatsApp",
    "retiro_santiago": "Retiro Santiago",
    "retiro_pichilemu": "Retiro Pichilemu",
}


# ── Admin HTML Templates (inline for simplicity) ──

def _page(title: str, content: str, active: str = "", is_auth: bool = True) -> HTMLResponse:
    nav = ""
    if is_auth:
        nav = f"""
        <nav style="background:#1a1a2e;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100">
            <div style="display:flex;align-items:center;gap:20px">
                <a href="/admin" style="color:#d4af37;font-weight:700;font-size:1.1rem;text-decoration:none">MAULLY Admin</a>
                <a href="/admin" style="color:{'#fff' if active=='dash' else '#888'};text-decoration:none;font-size:.85rem">Dashboard</a>
                <a href="/admin/orders" style="color:{'#fff' if active=='orders' else '#888'};text-decoration:none;font-size:.85rem">Pedidos</a>
            </div>
            <a href="/admin/logout" style="color:#888;font-size:.8rem;text-decoration:none">Cerrar Sesion</a>
        </nav>"""
    return HTMLResponse(f"""<!DOCTYPE html><html lang="es"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{title} | Maully Admin</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f0;color:#1a1a2e;min-height:100vh}}
    .container{{max-width:1200px;margin:0 auto;padding:24px}}
    .card{{background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:16px}}
    .stat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}}
    .stat{{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
    .stat .num{{font-size:2rem;font-weight:700;color:#1a1a2e}}
    .stat .label{{font-size:.8rem;color:#888;margin-top:4px}}
    table{{width:100%;border-collapse:collapse;font-size:.85rem}}
    th{{text-align:left;padding:10px 12px;background:#f5f5f0;font-weight:600;color:#666;font-size:.75rem;text-transform:uppercase}}
    td{{padding:10px 12px;border-bottom:1px solid #eee}}
    tr:hover td{{background:#fafaf5}}
    .badge{{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:50px;font-size:.72rem;font-weight:600;color:#fff}}
    .btn{{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:8px;font-size:.82rem;font-weight:500;cursor:pointer;border:none;transition:all .2s}}
    .btn-primary{{background:#1a1a2e;color:#fff}}.btn-primary:hover{{background:#2a2a4e}}
    .btn-success{{background:#10b981;color:#fff}}.btn-gold{{background:#d4af37;color:#fff}}
    .btn-sm{{padding:5px 10px;font-size:.75rem}}
    input,select,textarea{{padding:8px 12px;border:1px solid #ddd;border-radius:8px;font-size:.85rem;width:100%}}
    input:focus,select:focus{{outline:none;border-color:#d4af37;box-shadow:0 0 0 3px rgba(212,175,55,.1)}}
    a{{color:#1a1a2e}}
    .login-box{{max-width:400px;margin:80px auto;text-align:center}}
    .order-detail-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
    @media(max-width:768px){{.order-detail-grid{{grid-template-columns:1fr}}.stat-grid{{grid-template-columns:1fr 1fr}}}}
    </style></head><body>{nav}<div class="container">{content}</div></body></html>""")


# ══════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════

@router.get("/login")
async def login_page():
    return _page("Login", """
    <div class="login-box">
        <div class="card">
            <h2 style="margin-bottom:8px">Maully Admin</h2>
            <p style="color:#888;margin-bottom:24px;font-size:.85rem">Ingresa tu contrasena</p>
            <form method="post" action="/admin/login">
                <input type="password" name="password" placeholder="Contrasena" style="margin-bottom:12px" autofocus>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center">Entrar</button>
            </form>
        </div>
    </div>""", is_auth=False)


@router.post("/login")
async def do_login(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        token = hashlib.md5(f"{password}{datetime.utcnow().isoformat()}".encode()).hexdigest()
        _sessions[token] = datetime.utcnow() + timedelta(hours=12)
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie("admin_token", token, max_age=43200, httponly=True)
        return response
    return RedirectResponse(url="/admin/login?error=1", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("admin_token", "")
    _sessions.pop(token, None)
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_token")
    return response


# ══════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════

@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _check_auth(request):
        return RedirectResponse(url="/admin/login")

    async with async_session() as session:
        now = datetime.utcnow()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        # Stats
        total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
        orders_today = (await session.execute(select(func.count(Order.id)).where(Order.created_at >= today))).scalar() or 0
        orders_week = (await session.execute(select(func.count(Order.id)).where(Order.created_at >= week_ago))).scalar() or 0
        revenue_month = (await session.execute(select(func.sum(Order.total)).where(Order.status.in_(["pagado", "enviado", "entregado"]), Order.created_at >= month_ago))).scalar() or 0
        pending = (await session.execute(select(func.count(Order.id)).where(Order.status == "pagado"))).scalar() or 0

        # Recent orders
        result = await session.execute(
            select(Order).order_by(desc(Order.created_at)).limit(10)
        )
        recent = result.scalars().all()

    orders_html = ""
    for o in recent:
        st = STATUS_LABELS.get(o.status, ("?", "#888", "fa-question"))
        orders_html += f"""<tr>
            <td><a href="/admin/order/{o.order_number}" style="font-weight:600">{o.order_number}</a></td>
            <td>{o.customer_name}</td>
            <td><span class="badge" style="background:{st[1]}"><i class="fas {st[2]}"></i> {st[0]}</span></td>
            <td style="font-weight:600">{_fmt_price(o.total)}</td>
            <td>{_fmt_date(o.created_at)}</td>
        </tr>"""

    return _page("Dashboard", f"""
    <h1 style="font-size:1.5rem;margin-bottom:20px">Dashboard</h1>
    <div class="stat-grid">
        <div class="stat"><div class="num">{orders_today}</div><div class="label">Pedidos Hoy</div></div>
        <div class="stat"><div class="num">{orders_week}</div><div class="label">Pedidos Semana</div></div>
        <div class="stat"><div class="num">{_fmt_price(revenue_month)}</div><div class="label">Ingresos Mes</div></div>
        <div class="stat"><div class="num" style="color:#f59e0b">{pending}</div><div class="label">Pendientes de Envio</div></div>
    </div>
    <div class="card">
        <h3 style="margin-bottom:12px">Ultimos Pedidos</h3>
        <div style="overflow-x:auto">
        <table>
            <thead><tr><th>Orden</th><th>Cliente</th><th>Estado</th><th>Total</th><th>Fecha</th></tr></thead>
            <tbody>{orders_html if orders_html else '<tr><td colspan="5" style="text-align:center;color:#888;padding:24px">Sin pedidos aun</td></tr>'}</tbody>
        </table>
        </div>
    </div>
    """, active="dash")


# ══════════════════════════════════════════════
# ORDERS LIST
# ══════════════════════════════════════════════

@router.get("/orders", response_class=HTMLResponse)
async def orders_list(request: Request, status: str = ""):
    if not _check_auth(request):
        return RedirectResponse(url="/admin/login")

    async with async_session() as session:
        q = select(Order).order_by(desc(Order.created_at))
        if status:
            q = q.where(Order.status == status)
        result = await session.execute(q.limit(100))
        orders = result.scalars().all()

    filters_html = '<a href="/admin/orders" style="margin-right:8px" class="btn btn-sm btn-primary">Todos</a>'
    for k, (label, color, icon) in STATUS_LABELS.items():
        active = "btn-primary" if status == k else ""
        filters_html += f'<a href="/admin/orders?status={k}" class="btn btn-sm" style="background:{color};color:#fff;margin-right:6px">{label}</a>'

    rows = ""
    for o in orders:
        st = STATUS_LABELS.get(o.status, ("?", "#888", "fa-question"))
        ship = SHIPPING_LABELS.get(o.shipping_method, o.shipping_method)
        rows += f"""<tr>
            <td><a href="/admin/order/{o.order_number}" style="font-weight:600">{o.order_number}</a></td>
            <td>{o.customer_name}<br><span style="font-size:.72rem;color:#888">{o.customer_email}</span></td>
            <td><span class="badge" style="background:{st[1]}"><i class="fas {st[2]}"></i> {st[0]}</span></td>
            <td>{ship}</td>
            <td style="font-weight:600">{_fmt_price(o.total)}</td>
            <td>{_fmt_date(o.created_at)}</td>
        </tr>"""

    return _page("Pedidos", f"""
    <h1 style="font-size:1.5rem;margin-bottom:16px">Pedidos</h1>
    <div style="margin-bottom:16px">{filters_html}</div>
    <div class="card">
        <div style="overflow-x:auto">
        <table>
            <thead><tr><th>Orden</th><th>Cliente</th><th>Estado</th><th>Envio</th><th>Total</th><th>Fecha</th></tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="6" style="text-align:center;color:#888;padding:24px">Sin pedidos</td></tr>'}</tbody>
        </table>
        </div>
    </div>
    """, active="orders")


# ══════════════════════════════════════════════
# ORDER DETAIL
# ══════════════════════════════════════════════

@router.get("/order/{order_number}", response_class=HTMLResponse)
async def order_detail(request: Request, order_number: str):
    if not _check_auth(request):
        return RedirectResponse(url="/admin/login")

    async with async_session() as session:
        result = await session.execute(
            select(Order).where(Order.order_number == order_number).options(selectinload(Order.items))
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(404)

    st = STATUS_LABELS.get(order.status, ("?", "#888", "fa-question"))
    ship = SHIPPING_LABELS.get(order.shipping_method, order.shipping_method)

    items_html = ""
    for item in order.items:
        items_html += f"""<tr>
            <td>{item.product_name}</td>
            <td>{item.weight}</td>
            <td style="text-align:center">{item.qty}</td>
            <td style="text-align:right">{_fmt_price(item.price)}</td>
            <td style="text-align:right;font-weight:600">{_fmt_price(item.price * item.qty)}</td>
        </tr>"""

    # Actions based on status
    actions = ""
    if order.status == "pagado":
        actions = f"""
        <form method="post" action="/admin/order/{order_number}/ship" style="display:flex;gap:8px;align-items:end">
            <div style="flex:1"><label style="font-size:.75rem;color:#888">Numero de Seguimiento</label>
            <input name="tracking" placeholder="Ej: STARKEN-12345"></div>
            <button type="submit" class="btn btn-success"><i class="fas fa-truck"></i> Marcar Enviado</button>
        </form>"""
    elif order.status == "enviado":
        actions = f'<form method="post" action="/admin/order/{order_number}/deliver"><button type="submit" class="btn btn-success"><i class="fas fa-box-open"></i> Marcar Entregado</button></form>'

    return _page(f"Orden {order_number}", f"""
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
        <h1 style="font-size:1.3rem">Orden {order.order_number}</h1>
        <span class="badge" style="background:{st[1]};font-size:.85rem;padding:6px 14px"><i class="fas {st[2]}"></i> {st[0]}</span>
    </div>
    <div class="order-detail-grid">
        <div class="card">
            <h3 style="margin-bottom:12px;font-size:.9rem;color:#888">CLIENTE</h3>
            <p style="font-weight:600;font-size:1.1rem">{order.customer_name}</p>
            <p style="color:#666">{order.customer_rut}</p>
            <p style="color:#666">{order.customer_email}</p>
            <p style="color:#666">{order.customer_phone}</p>
            <hr style="margin:12px 0;border:none;border-top:1px solid #eee">
            <p style="font-size:.82rem"><strong>Direccion:</strong> {order.address_street}, {order.address_comuna}, {order.address_region}</p>
            <p style="font-size:.82rem"><strong>Documento:</strong> {order.doc_type.upper()}{f' — {order.business_name} ({order.business_rut})' if order.doc_type == 'factura' else ''}</p>
            {f'<p style="font-size:.82rem"><strong>Giro:</strong> {order.business_giro}</p><p style="font-size:.82rem"><strong>Dir. Empresa:</strong> {order.business_address}</p>' if order.doc_type == 'factura' and order.business_giro else ''}
        </div>
        <div class="card">
            <h3 style="margin-bottom:12px;font-size:.9rem;color:#888">ENVIO Y PAGO</h3>
            <p><strong>Metodo:</strong> {ship}</p>
            <p><strong>Costo envio:</strong> {_fmt_price(order.shipping_cost)}</p>
            <p><strong>Tracking:</strong> {order.tracking_number or 'Sin asignar'}</p>
            <p><strong>Peso total:</strong> {order.total_weight}kg</p>
            <hr style="margin:12px 0;border:none;border-top:1px solid #eee">
            <p><strong>Pago MP:</strong> {order.payment_id or 'Pendiente'}</p>
            <p><strong>Estado pago:</strong> {order.payment_status}</p>
            <p><strong>Pagado:</strong> {_fmt_date(order.paid_at)}</p>
            <p><strong>Enviado:</strong> {_fmt_date(order.shipped_at)}</p>
        </div>
    </div>
    <div class="card">
        <h3 style="margin-bottom:12px;font-size:.9rem;color:#888">PRODUCTOS</h3>
        <table>
            <thead><tr><th>Producto</th><th>Peso</th><th style="text-align:center">Qty</th><th style="text-align:right">Precio</th><th style="text-align:right">Subtotal</th></tr></thead>
            <tbody>{items_html}</tbody>
            <tfoot>
                <tr><td colspan="4" style="text-align:right;font-weight:600">Subtotal:</td><td style="text-align:right">{_fmt_price(order.subtotal)}</td></tr>
                <tr><td colspan="4" style="text-align:right;font-weight:600">Envio:</td><td style="text-align:right">{_fmt_price(order.shipping_cost)}</td></tr>
                <tr><td colspan="4" style="text-align:right;font-weight:700;font-size:1.1rem">Total:</td><td style="text-align:right;font-weight:700;font-size:1.1rem;color:#d4af37">{_fmt_price(order.total)}</td></tr>
            </tfoot>
        </table>
    </div>
    <div class="card">{actions if actions else '<p style="color:#888;text-align:center">Sin acciones disponibles</p>'}</div>
    """, active="orders")


# ══════════════════════════════════════════════
# ORDER ACTIONS
# ══════════════════════════════════════════════

@router.post("/order/{order_number}/ship")
async def mark_shipped(request: Request, order_number: str, tracking: str = Form("")):
    if not _check_auth(request):
        return RedirectResponse(url="/admin/login")

    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.order_number == order_number))
        order = result.scalar_one_or_none()
        if order:
            order.status = "enviado"
            order.tracking_number = tracking
            order.shipped_at = datetime.utcnow()
            await session.commit()
            logger.info(f"[ADMIN] Orden {order_number} marcada como enviada: {tracking}")

    return RedirectResponse(url=f"/admin/order/{order_number}", status_code=303)


@router.post("/order/{order_number}/deliver")
async def mark_delivered(request: Request, order_number: str):
    if not _check_auth(request):
        return RedirectResponse(url="/admin/login")

    async with async_session() as session:
        result = await session.execute(select(Order).where(Order.order_number == order_number))
        order = result.scalar_one_or_none()
        if order:
            order.status = "entregado"
            await session.commit()
            logger.info(f"[ADMIN] Orden {order_number} marcada como entregada")

    return RedirectResponse(url=f"/admin/order/{order_number}", status_code=303)
