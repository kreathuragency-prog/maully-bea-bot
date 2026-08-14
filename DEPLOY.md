# Despliegue — Importadora Maully

Guia corta para poner en produccion el bot de Bea + checkout + panel admin.

## 1. Requisitos

- Python 3.11+
- Dominio con SSL (ej: `api.importadoramaully.cl`)
- Cuenta MercadoPago (credenciales de produccion)
- App Meta Developer con WhatsApp Business Cloud API
- VPS con acceso SSH (o cPanel con Python App Manager)

## 2. Variables de entorno (`.env`)

```ini
# OpenAI (ya configurado)
OPENAI_API_KEY=sk-proj-...

# WhatsApp Cloud API (Meta)
META_ACCESS_TOKEN=EAAx...                # Token permanente del system user
META_PHONE_NUMBER_ID=123456789           # Phone Number ID de +56 9 9056 5137
META_VERIFY_TOKEN=maully-bea-2026        # Cualquier string, usarlo tambien en el webhook

# MercadoPago (produccion)
MP_ACCESS_TOKEN=APP_USR-...
MP_PUBLIC_KEY=APP_USR-...

# E-Commerce
SITE_URL=https://www.importadoramaully.cl
ADMIN_PASSWORD=<cambiar a una segura>

# Puerto (cPanel suele pedir uno asignado)
PORT=8000
```

## 3. Instalacion

```bash
cd whatsapp-bot-bea
python -m venv .venv
source .venv/bin/activate       # Linux/Mac
# o   .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

## 4. Arrancar

```bash
python main.py
# o con uvicorn en produccion:
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

## 5. Configurar webhook de WhatsApp

En Meta Developer → WhatsApp → Configuration:

- **Callback URL**: `https://api.importadoramaully.cl/webhook`
- **Verify Token**: mismo valor de `META_VERIFY_TOKEN`
- **Suscribirse** a: `messages`

## 6. Configurar webhook de MercadoPago

En el dashboard de MercadoPago → Tu app → Notificaciones → Webhooks:

- **URL**: `https://api.importadoramaully.cl/api/mp/webhook`
- **Eventos**: `Pagos`

## 7. URLs del sistema

| Path                           | Descripcion                         |
| ------------------------------ | ----------------------------------- |
| `/`                            | Health check                        |
| `/webhook`                     | Webhook WhatsApp (Meta)             |
| `/api/config`                  | Config publica (regiones, envios)   |
| `/api/checkout`                | Crea orden + preferencia MercadoPago|
| `/api/mp/webhook`              | Webhook MercadoPago                 |
| `/api/order/{order_number}`    | Estado de una orden                 |
| `/admin/login`                 | Login panel e-commerce              |
| `/admin`                       | Dashboard e-commerce                |
| `/admin/orders`                | Listado de pedidos                  |
| `/crm`                         | Dashboard conversaciones WhatsApp   |
| `/crm/conversations`           | Chats de Bea                        |
| `/crm/leads`                   | Leads capturados                    |

## 8. Frontend (sitio estatico)

Los archivos del sitio publico viven en la raiz del repo:
- `index.html`, `checkout.html`, `styles.css`, `script.js`, `checkout.js`, `checkout.css`

Subir a cPanel → `public_html/` (dominio `importadoramaully.cl`).

**Importante**: En `checkout.js` linea 9 la `API_BASE` debe apuntar al backend FastAPI en produccion:

```js
const API_BASE = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : 'https://api.importadoramaully.cl';
```

## 9. Checklist post-deploy

- [ ] Test health: `curl https://api.importadoramaully.cl/`
- [ ] Webhook WhatsApp verificado (manda mensaje al +56 9 9056 5137)
- [ ] Login admin funciona (`/admin/login` con `ADMIN_PASSWORD`)
- [ ] Crear orden de prueba con MP en modo **Sandbox** primero
- [ ] Webhook MP recibe confirmacion (ver `[MP WEBHOOK]` en logs)
- [ ] CORS permite llamadas desde `importadoramaully.cl` (ya configurado en `main.py`)
- [ ] Cambiar `ADMIN_PASSWORD` de `maully2026` a una segura
- [ ] Backup automatico de `bot.db` (SQLite)

## 10. Troubleshooting

**Bot no responde en WhatsApp**
- Verifica `META_ACCESS_TOKEN` y `META_PHONE_NUMBER_ID`
- Revisa logs del proceso: debe mostrar `Webhook verificado OK`
- Confirma que el numero esta suscrito al webhook en Meta Developer

**Pago falla**
- Verifica que `MP_ACCESS_TOKEN` sea de produccion (empieza con `APP_USR-`)
- Mira respuesta de `/api/checkout` — el error viene de MercadoPago
- Confirma que `SITE_URL` apunta al dominio publico para los `back_urls`

**Panel admin no carga pedidos**
- Las tablas se crean en `init_db()` al iniciar — si cambiaste el modelo, borra `bot.db` en dev
- Verifica que `_check_auth()` reconozca la cookie (revisa `admin_token`)

**Checkout "Error al crear pago"**
- Backend probablemente sin `MP_ACCESS_TOKEN` configurado
- Abre DevTools → Network → ver respuesta de `/api/checkout`
