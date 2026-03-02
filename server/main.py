from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_, asc, desc
from typing import List, Optional
import json

from database import Base, engine, get_db
from models import User, Product, Order, OrderItem, OrderStatus
from schemas import (
    UserCreate, UserOut, TokenOut,
    ProductOut, OrderCreate, OrderOut, OrderItemOut,
    AddressUpdate
)
from auth import hash_password, verify_password, create_access_token, get_current_user
from seed import seed_products

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ecom API", version="3.1")

app.add_middleware(
    CORSMiddleware,
    
allow_origins=[
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    db = next(get_db())
    seed_products(db)

# ---- AUTH ----
@app.post("/auth/register", response_model=UserOut)
def register(user: UserCreate, db: Session = Depends(get_db)):
    exists = db.query(User).filter(User.email == user.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")
    u = User(name=user.name, email=user.email, password_hash=hash_password(user.password))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u

@app.post("/auth/login", response_model=TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user

# ---- PRODUCTS ----

def product_to_out(p: Product) -> ProductOut:
    specs = None
    if p.specs_json:
        try:
            specs = json.loads(p.specs_json)
        except Exception:
            specs = None
    return ProductOut(
        id=p.id,
        name=p.name,
        description=p.description,
        category=p.category,
        price_cents=p.price_cents,
        image_url=p.image_url,
        stock=p.stock,
        specs=specs,
    )

@app.get("/products", response_model=List[ProductOut])
def list_products(
    q: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    min_price_cents: Optional[int] = Query(default=None, ge=0),
    max_price_cents: Optional[int] = Query(default=None, ge=0),
    in_stock: Optional[bool] = Query(default=None),
    sort: Optional[str] = Query(default=None),
    db: Session = Depends(get_db)
):
    query = db.query(Product)

    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))
    if category:
        query = query.filter(Product.category == category)
    if min_price_cents is not None:
        query = query.filter(Product.price_cents >= min_price_cents)
    if max_price_cents is not None:
        query = query.filter(Product.price_cents <= max_price_cents)
    if in_stock is not None:
        if in_stock:
            query = query.filter(Product.stock > 0)
        else:
            query = query.filter(Product.stock <= 0)

    if sort == 'price_asc':
        query = query.order_by(asc(Product.price_cents))
    elif sort == 'price_desc':
        query = query.order_by(desc(Product.price_cents))
    elif sort == 'name_asc':
        query = query.order_by(asc(Product.name))
    elif sort == 'name_desc':
        query = query.order_by(desc(Product.name))

    products = query.all()
    return [product_to_out(p) for p in products]

@app.get("/products/categories", response_model=List[str])
def list_categories(db: Session = Depends(get_db)):
    rows = db.query(Product.category).distinct().all()
    return sorted([r[0] for r in rows if r[0]])

@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_to_out(p)

# ---- ORDERS ----
@app.get("/orders", response_model=List[OrderOut])
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == current_user.id).order_by(Order.id.desc()).all()
    out = []
    for o in orders:
        out.append(OrderOut(
            id=o.id,
            status=o.status,
            total_amount_cents=o.total_amount_cents,
            payment_method=o.payment_method,
            shipping_address=o.shipping_address,
            contact_name=o.contact_name,
            contact_email=o.contact_email,
            contact_phone=o.contact_phone,
            items=[OrderItemOut(product_id=it.product_id, quantity=it.quantity, unit_price_cents=it.unit_price_cents) for it in o.items]
        ))
    return out

@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderOut(
        id=o.id,
        status=o.status,
        total_amount_cents=o.total_amount_cents,
        payment_method=o.payment_method,
        shipping_address=o.shipping_address,
        contact_name=o.contact_name,
        contact_email=o.contact_email,
        contact_phone=o.contact_phone,
        items=[OrderItemOut(product_id=it.product_id, quantity=it.quantity, unit_price_cents=it.unit_price_cents) for it in o.items]
    )

@app.post("/orders", response_model=OrderOut, status_code=201)
def create_order(payload: OrderCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items in order")

    total = 0
    items: list[OrderItem] = []
    for it in payload.items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product {it.product_id} not found")
        if prod.stock < it.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {prod.name}")
        total += prod.price_cents * it.quantity
        items.append(OrderItem(product_id=prod.id, quantity=it.quantity, unit_price_cents=prod.price_cents))

    order = Order(
        user_id=current_user.id,
        status=OrderStatus.PENDING_PAYMENT,
        total_amount_cents=total,
        payment_method=payload.payment_method,
        shipping_address=payload.shipping_address,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
    )
    db.add(order)
    db.flush()

    for it in items:
        it.order_id = order.id
        db.add(it)

    db.commit()
    db.refresh(order)

    return OrderOut(
        id=order.id,
        status=order.status,
        total_amount_cents=order.total_amount_cents,
        payment_method=order.payment_method,
        shipping_address=order.shipping_address,
        contact_name=order.contact_name,
        contact_email=order.contact_email,
        contact_phone=order.contact_phone,
        items=[OrderItemOut(product_id=it.product_id, quantity=it.quantity, unit_price_cents=it.unit_price_cents) for it in order.items]
    )

@app.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if o.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Order already cancelled")

    o.status = OrderStatus.CANCELLED
    db.commit(); db.refresh(o)
    return OrderOut(
        id=o.id, status=o.status, total_amount_cents=o.total_amount_cents,
        payment_method=o.payment_method, shipping_address=o.shipping_address,
        contact_name=o.contact_name, contact_email=o.contact_email, contact_phone=o.contact_phone,
        items=[OrderItemOut(product_id=it.product_id, quantity=it.quantity, unit_price_cents=it.unit_price_cents) for it in o.items]
    )

@app.post("/payments/{order_id}/pay", response_model=OrderOut)
def dummy_pay(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if o.status == OrderStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Cannot pay a cancelled order")

    if o.status != OrderStatus.PAID:
        for it in o.items:
            prod = db.query(Product).filter(Product.id == it.product_id).first()
            if prod and prod.stock >= it.quantity:
                prod.stock -= it.quantity
            else:
                raise HTTPException(status_code=400, detail=f"Insufficient stock during payment for product {it.product_id}")
        o.status = OrderStatus.PAID
        db.commit(); db.refresh(o)

    return OrderOut(
        id=o.id, status=o.status, total_amount_cents=o.total_amount_cents,
        payment_method=o.payment_method, shipping_address=o.shipping_address,
        contact_name=o.contact_name, contact_email=o.contact_email, contact_phone=o.contact_phone,
        items=[OrderItemOut(product_id=it.product_id, quantity=it.quantity, unit_price_cents=it.unit_price_cents) for it in o.items]
    )

#(new endpoint)
@app.put("/me/address", response_model=UserOut)
def save_address(
    payload: AddressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    ):
    current_user.default_shipping_address = payload.default_shipping_address
    current_user.default_contact_phone = payload.default_contact_phone
    db.commit()
    db.refresh(current_user)
    return current_user

