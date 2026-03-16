from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Dict
from models import OrderStatus, UserRole

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)

class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    # NEW ↓↓↓
    role: UserRole
    default_shipping_address: Optional[str] = None
    default_contact_phone: Optional[str] = None
    # 
    class Config:
        from_attributes = True


# NEW: payload to save/update the user's default address
class AddressUpdate(BaseModel):
    default_shipping_address: str
    default_contact_phone: Optional[str] = None

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ProductOut(BaseModel):
    id: int
    name: str
    description: str
    category: Optional[str]
    price_cents: int
    image_url: Optional[str]
    stock: int
    specs: Optional[dict] = None
    class Config:
        from_attributes = True

class OrderItemIn(BaseModel):
    product_id: int
    quantity: int

class OrderCreate(BaseModel):
    items: List[OrderItemIn]
    payment_method: str = "dummy"
    shipping_address: str
    contact_name: str
    contact_email: EmailStr
    contact_phone: str

class OrderItemOut(BaseModel):
    product_id: int
    quantity: int
    unit_price_cents: int
    class Config:
        from_attributes = True

class OrderOut(BaseModel):
    id: int
    status: OrderStatus
    total_amount_cents: int
    payment_method: Optional[str]
    shipping_address: Optional[str]
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    items: List[OrderItemOut]
    class Config:
        from_attributes = True
        
class PaymentSessionOut(BaseModel):
    payment_url: str


class AdminProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: Optional[str] = None
    price_cents: int = Field(ge=0)
    stock: int = Field(ge=0)
    description: str = Field(min_length=1)   # NOT NULL in DB
    image_url: Optional[str] = None
    specs: Optional[Dict[str, str]] 