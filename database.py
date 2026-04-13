"""
Database — Modelos SQLite para el bot multi-negocio
Tablas: contacts, conversations, messages, leads
"""

import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Text, DateTime, Integer, Float, ForeignKey

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    business_detected: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="contact")
    leads: Mapped[list["Lead"]] = relationship(back_populates="contact")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, closed
    assigned_business: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact: Mapped["Contact"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # inbound, outbound
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    business: Mapped[str] = mapped_column(String(50))
    stage: Mapped[str] = mapped_column(String(30), default="nuevo")  # nuevo, contactado, interesado, cerrado
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact: Mapped["Contact"] = relationship(back_populates="leads")


# ══════════════════════════════════════════════
# E-COMMERCE MODELS
# ══════════════════════════════════════════════

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pendiente")  # pendiente, pagado, enviado, entregado, cancelado
    # Cliente
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_rut: Mapped[str] = mapped_column(String(20))
    customer_email: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(30))
    # Direccion
    address_street: Mapped[str] = mapped_column(String(300), default="")
    address_comuna: Mapped[str] = mapped_column(String(100), default="")
    address_region: Mapped[str] = mapped_column(String(100), default="")
    # Documento
    doc_type: Mapped[str] = mapped_column(String(20), default="boleta")  # boleta, factura
    business_name: Mapped[str] = mapped_column(String(200), default="")  # razon social (factura)
    business_rut: Mapped[str] = mapped_column(String(20), default="")    # rut empresa (factura)
    business_giro: Mapped[str] = mapped_column(String(200), default="")  # giro del negocio (factura)
    business_address: Mapped[str] = mapped_column(String(300), default="")  # direccion empresa (factura)
    # Envio
    shipping_method: Mapped[str] = mapped_column(String(30), default="starken")  # starken, dhl, retiro_santiago, retiro_pichilemu
    shipping_cost: Mapped[int] = mapped_column(Integer, default=0)
    tracking_number: Mapped[str] = mapped_column(String(100), default="")
    # Pago
    payment_method: Mapped[str] = mapped_column(String(30), default="mercadopago")
    payment_id: Mapped[str] = mapped_column(String(100), default="")  # MP payment ID
    payment_status: Mapped[str] = mapped_column(String(30), default="pending")  # pending, approved, rejected
    # Totales
    subtotal: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    total_weight: Mapped[int] = mapped_column(Integer, default=0)  # kg
    # Notas
    notes: Mapped[str] = mapped_column(Text, default="")
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(Integer)
    product_name: Mapped[str] = mapped_column(String(300))
    product_cat: Mapped[str] = mapped_column(String(50), default="")
    weight: Mapped[str] = mapped_column(String(20), default="")
    price: Mapped[int] = mapped_column(Integer)  # CLP
    qty: Mapped[int] = mapped_column(Integer, default=1)

    order: Mapped["Order"] = relationship(back_populates="items")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def init_db():
    """Crea todas las tablas si no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
