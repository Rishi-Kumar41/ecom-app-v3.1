from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi import APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import or_, asc, desc
from typing import List, Optional
import json
import uuid
import stripe
import os


stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET")

from database import Base, engine, get_db
from models import User, Product, Order, OrderItem, OrderStatus, Payment, CartItem, UserRole
from schemas import UserCreate, UserOut, TokenOut, ProductOut, OrderCreate, OrderOut, AdminProductCreate
from auth import hash_password, verify_password, create_access_token, get_current_user
from seed import seed_products
from permission import require_roles

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ecom API", version="3.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_roles(UserRole.admin))]  # server-side authz
)


@app.on_event("startup")
def on_startup():
    db = next(get_db())
    seed_products(db)

    # ---------------- AUTH ----------------
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
    role_value = getattr(user.role, "value", user.role)  # supports Enum or plain string
    token = create_access_token({"sub": str(user.id), "role": role_value})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user

# ---------------- PRODUCTS ----------------
def product_to_out(p: Product) -> ProductOut:
    specs = None
    if p.specs_json:
        try:
            specs = json.loads(p.specs_json)
        except:
            specs = None
    return ProductOut(
        id=p.id, name=p.name, description=p.description,
        category=p.category, price_cents=p.price_cents,
        image_url=p.image_url, stock=p.stock, specs=specs
    )

@app.get("/products", response_model=List[ProductOut])
def list_products(
    q: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    min_price_cents: Optional[int] = Query(None, ge=0),
    max_price_cents: Optional[int] = Query(None, ge=0),
    in_stock: Optional[bool] = Query(None),
    sort: Optional[str] = Query(None),
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
        query = query.filter(Product.stock > 0 if in_stock else Product.stock <= 0)
    if sort == "price_asc":
        query = query.order_by(asc(Product.price_cents))
    elif sort == "price_desc":
        query = query.order_by(desc(Product.price_cents))
    elif sort == "name_asc":
        query = query.order_by(asc(Product.name))
    elif sort == "name_desc":
        query = query.order_by(desc(Product.name))
    products = query.all()
    return [product_to_out(p) for p in products]

@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_to_out(p)

# ---------------- ORDERS ----------------
@app.post("/orders", response_model=OrderOut, status_code=201)
def create_order(payload: OrderCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="No items in order")

    total, items = 0, []

    # Validate products and calculate total
    for it in payload.items:
        prod = db.query(Product).filter(Product.id == it.product_id).first()
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product {it.product_id} not found")
        if prod.stock < it.quantity:
            raise HTTPException(status_code=400, detail="Insufficient stock")
        total += prod.price_cents * it.quantity
        items.append(OrderItem(product_id=prod.id, quantity=it.quantity, unit_price_cents=prod.price_cents))

    # Create the order
    order = Order(
        user_id=current_user.id,
        status=OrderStatus.PENDING_PAYMENT,
        total_amount_cents=total,
        payment_method=payload.payment_method,
        shipping_address=payload.shipping_address,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone
    )
    db.add(order)
    db.flush()  # ensures order.id exists before adding items

    # Add order items
    for it in items:
        it.order_id = order.id
        db.add(it)

    db.commit()
    db.refresh(order)

    return order

# ---------------- PAYMENTS (Stripe) ----------------
@app.post("/payments/stripe-session/{order_id}")
def create_stripe_session(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Fetch the order
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Stripe minimum amount check (50 cents USD ~ 50 INR in test mode)
    MIN_AMOUNT_CENTS = 5000  # 50 INR in paise
    if order.total_amount_cents < MIN_AMOUNT_CENTS:
        print(f"Warning: Order total {order.total_amount_cents} paise is below Stripe minimum. Adjusting to {MIN_AMOUNT_CENTS}.")
        stripe_amount = MIN_AMOUNT_CENTS
    else:
        stripe_amount = order.total_amount_cents

    # Create Stripe Checkout session
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'inr',
                'product_data': {'name': f'Order #{order.id}'},
                'unit_amount': stripe_amount
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=f"http://localhost:4200/payment-success?order_id={order.id}",
        cancel_url=f"http://localhost:4200/payment-failed?order_id={order.id}",
        metadata={'order_id': str(order.id)}
    )

    # Create payment record in DB (initially pending)
    payment = Payment(
        order_id=order.id,
        amount_cents=stripe_amount,
        status="pending",
        gateway_ref=session.id
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return {"checkout_url": session.url} 
     
@app.post("/payments/stripe-webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, stripe_webhook_secret)
    except Exception as e:
        print("Webhook error:", e)
        return JSONResponse(status_code=400, content={"detail": "Invalid payload/signature"})

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        print("Webhook session object:", session)

        order_id_str = session.get('metadata', {}).get('order_id')
        if not order_id_str:
            print("Webhook missing order_id")
            return JSONResponse(status_code=400, content={"detail": "Missing order_id"})

        order = db.query(Order).filter(Order.id == int(order_id_str)).first()
        if not order:
            print(f"Order {order_id_str} not found")
            return JSONResponse(status_code=404, content={"detail": "Order not found"})

        # Update payment record
        payment = db.query(Payment).filter(Payment.order_id == order.id).first()
        if payment:
            payment.status = "success"
        else:
            payment = Payment(
                order_id=order.id,
                amount_cents=order.total_amount_cents,
                status="success",
                gateway_ref=session.get("id")
            )
            db.add(payment)

        # Mark order as paid
        if order.status != OrderStatus.PAID:
            order.status = OrderStatus.PAID

            # Reduce stock
            for item in order.items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    product.stock = max(product.stock - item.quantity, 0)

            # Clear cart
            db.query(CartItem).filter(CartItem.user_id == order.user_id).delete()

        db.commit()
        print(f"Order {order.id} marked as PAID, payment updated.")

    return {"status": "success"}

    # List all orders for the current user
@app.get("/orders", response_model=List[OrderOut])
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == current_user.id).all()
    return orders
    
# Get single order by ID
@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Find the order for this user
    order = db.query(Order).filter(Order.id == order_id, Order.user_id == current_user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Only allow cancellation if not paid yet
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(status_code=400, detail="Order cannot be cancelled at this stage")

    order.status = OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)

    # Return a proper JSON response
    return {"status": "success", "message": f"Order {order.id} cancelled"}

# admin search (Support UI will call this later)
@admin_router.get("/search")
def admin_search(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # For now, return a placeholder result; we’ll implement real search later.
    return {"q": q, "results": []}

# admin add product (Support UI will call this later)
@admin_router.post("/products", response_model=ProductOut)
def admin_add_product(
    payload: AdminProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Create & persist
    p = Product(
        name=payload.name.strip(),
        description=payload.description.strip(),      # NOT NULL in DB
        category=(payload.category or None),
        price_cents=payload.price_cents,
        image_url=(payload.image_url or None),
        stock=payload.stock,
    )
    db.add(p)
    db.commit()
    db.refresh(p)

    # Return the mapped output
    return product_to_out(p)

app.include_router(admin_router)