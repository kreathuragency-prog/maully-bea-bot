"""
DB Operations — CRUD para contactos, conversaciones, mensajes y leads
Cada mensaje entrante: crea/actualiza contacto, conversacion, mensaje y lead
"""

from datetime import datetime
from sqlalchemy import select, func
from database import async_session, Contact, Conversation, Message, Lead


# ── Contactos ──────────────────────────────────────────────────

async def get_or_create_contact(phone: str) -> Contact:
    """Obtiene contacto existente o crea uno nuevo."""
    async with async_session() as session:
        result = await session.execute(
            select(Contact).where(Contact.phone == phone)
        )
        contact = result.scalar_one_or_none()
        if not contact:
            contact = Contact(phone=phone)
            session.add(contact)
            await session.commit()
            await session.refresh(contact)
        return contact


async def update_contact_business(phone: str, business: str):
    """Actualiza el negocio detectado del contacto."""
    async with async_session() as session:
        result = await session.execute(
            select(Contact).where(Contact.phone == phone)
        )
        contact = result.scalar_one_or_none()
        if contact and business:
            contact.business_detected = business
            contact.updated_at = datetime.utcnow()
            await session.commit()


# ── Conversaciones ─────────────────────────────────────────────

async def get_or_create_conversation(contact_id: int) -> Conversation:
    """Obtiene conversacion activa o crea una nueva."""
    async with async_session() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.contact_id == contact_id)
            .where(Conversation.status == "active")
            .order_by(Conversation.created_at.desc())
        )
        conv = result.scalar_one_or_none()
        if not conv:
            conv = Conversation(contact_id=contact_id, status="active")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
        return conv


async def update_conversation_business(conv_id: int, business: str):
    """Actualiza negocio asignado a la conversacion."""
    async with async_session() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if conv and business:
            conv.assigned_business = business
            conv.updated_at = datetime.utcnow()
            await session.commit()


# ── Mensajes ───────────────────────────────────────────────────

async def save_message(conversation_id: int, direction: str, text: str) -> Message:
    """Guarda un mensaje en la conversacion."""
    async with async_session() as session:
        msg = Message(
            conversation_id=conversation_id,
            direction=direction,
            text=text
        )
        session.add(msg)
        # Actualizar timestamp de la conversacion
        result = await session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if conv:
            conv.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(msg)
        return msg


async def get_conversation_messages(conversation_id: int, limit: int = 20) -> list[dict]:
    """Obtiene mensajes de una conversacion para pasarle a la IA."""
    async with async_session() as session:
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = result.scalars().all()
        messages.reverse()
        return [
            {
                "role": "user" if m.direction == "inbound" else "assistant",
                "content": m.text
            }
            for m in messages
        ]


# ── Leads ──────────────────────────────────────────────────────

async def get_or_create_lead(contact_id: int, business: str) -> Lead:
    """Obtiene o crea lead para un negocio especifico."""
    if not business:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(Lead)
            .where(Lead.contact_id == contact_id)
            .where(Lead.business == business)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            lead = Lead(contact_id=contact_id, business=business, stage="nuevo")
            session.add(lead)
            await session.commit()
            await session.refresh(lead)
        else:
            if lead.stage == "nuevo":
                lead.stage = "contactado"
                lead.updated_at = datetime.utcnow()
                await session.commit()
        return lead


# ── Queries para el panel admin ────────────────────────────────

async def get_all_conversations(limit: int = 50) -> list[dict]:
    """Lista conversaciones con info del contacto y ultimo mensaje."""
    async with async_session() as session:
        result = await session.execute(
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        convs = result.scalars().all()
        data = []
        for conv in convs:
            # Cargar contacto
            contact_result = await session.execute(
                select(Contact).where(Contact.id == conv.contact_id)
            )
            contact = contact_result.scalar_one_or_none()
            # Ultimo mensaje
            last_msg_result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_msg = last_msg_result.scalar_one_or_none()
            # Contar mensajes
            count_result = await session.execute(
                select(func.count(Message.id))
                .where(Message.conversation_id == conv.id)
            )
            msg_count = count_result.scalar()
            data.append({
                "id": conv.id,
                "phone": contact.phone if contact else "?",
                "name": contact.name if contact else "",
                "business": conv.assigned_business or contact.business_detected if contact else "",
                "status": conv.status,
                "msg_count": msg_count,
                "last_message": last_msg.text[:80] if last_msg else "",
                "last_direction": last_msg.direction if last_msg else "",
                "updated_at": conv.updated_at.strftime("%d/%m %H:%M") if conv.updated_at else "",
            })
        return data


async def get_conversation_detail(conv_id: int) -> dict:
    """Detalle completo de una conversacion."""
    async with async_session() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return None
        # Contacto
        contact_result = await session.execute(
            select(Contact).where(Contact.id == conv.contact_id)
        )
        contact = contact_result.scalar_one_or_none()
        # Mensajes
        msgs_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
        )
        messages = msgs_result.scalars().all()
        return {
            "id": conv.id,
            "phone": contact.phone if contact else "?",
            "name": contact.name if contact else "",
            "business": conv.assigned_business or "",
            "status": conv.status,
            "created_at": conv.created_at.strftime("%d/%m/%Y %H:%M"),
            "messages": [
                {
                    "direction": m.direction,
                    "text": m.text,
                    "time": m.created_at.strftime("%H:%M"),
                    "date": m.created_at.strftime("%d/%m"),
                }
                for m in messages
            ]
        }


async def get_all_leads(limit: int = 50) -> list[dict]:
    """Lista todos los leads."""
    async with async_session() as session:
        result = await session.execute(
            select(Lead).order_by(Lead.updated_at.desc()).limit(limit)
        )
        leads = result.scalars().all()
        data = []
        for lead in leads:
            contact_result = await session.execute(
                select(Contact).where(Contact.id == lead.contact_id)
            )
            contact = contact_result.scalar_one_or_none()
            data.append({
                "id": lead.id,
                "phone": contact.phone if contact else "?",
                "name": contact.name if contact else "",
                "business": lead.business,
                "stage": lead.stage,
                "notes": lead.notes,
                "created_at": lead.created_at.strftime("%d/%m/%Y"),
                "updated_at": lead.updated_at.strftime("%d/%m %H:%M") if lead.updated_at else "",
            })
        return data


async def get_dashboard_stats() -> dict:
    """Estadisticas para el dashboard."""
    async with async_session() as session:
        contacts_count = (await session.execute(select(func.count(Contact.id)))).scalar()
        convs_count = (await session.execute(select(func.count(Conversation.id)))).scalar()
        msgs_count = (await session.execute(select(func.count(Message.id)))).scalar()
        leads_count = (await session.execute(select(func.count(Lead.id)))).scalar()
        active_convs = (await session.execute(
            select(func.count(Conversation.id)).where(Conversation.status == "active")
        )).scalar()
        # Leads por negocio
        leads_by_biz = {}
        for biz in ["maully"]:
            count = (await session.execute(
                select(func.count(Lead.id)).where(Lead.business == biz)
            )).scalar()
            if count > 0:
                leads_by_biz[biz] = count
        return {
            "contacts": contacts_count,
            "conversations": convs_count,
            "active_conversations": active_convs,
            "messages": msgs_count,
            "leads": leads_count,
            "leads_by_business": leads_by_biz,
        }
