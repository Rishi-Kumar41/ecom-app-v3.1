from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from database import Base

class OrderStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# NEW (MVP): saved address & contact phone for autofill at checkout
    default_shipping_address = Column(Text, nullable=True)
    default_contact_phone    = Column(String(30), nullable=True)


    orders = relationship("Order", back_populates="user")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=True)
    price_cents = Column(Integer, nullable=False)
    image_url = Column(String(500), nullable=True)
    stock = Column(Integer, nullable=False, default=0)
    specs_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING_PAYMENT, nullable=False)
    total_amount_cents = Column(Integer, nullable=False, default=0)
    payment_method = Column(String(50), nullable=True)
    shipping_address = Column(Text, nullable=True)

    contact_name = Column(String(120), nullable=True)
    contact_email = Column(String(120), nullable=True)
    contact_phone = Column(String(30), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_cents = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
